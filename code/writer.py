#rule-based Writer: illustrates transport without an external model
#Kafka transport is local to this script; no shared helper is required
import json
import base64

import logging

import os
import sqlite3
import time
from pathlib import Path

from kafka import KafkaConsumer, KafkaProducer

PREFIX = os.environ.get('KAFKA_PREFIX', 's1339')

BROKER = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

logging.getLogger('kafka').setLevel(logging.WARNING)

log = logging.getLogger('pipeline')

def producer():
    return KafkaProducer(
        bootstrap_servers=BROKER, acks='all',
        value_serializer=lambda value: json.dumps(value).encode('utf-8'),
    )

def publish(client, topic, message, stage):
    log.info('%s SEND topic=%s %s', stage, topic, json.dumps(message))
    client.send(topic, value=message,
                key=message['correlation_id'].encode('utf-8')).get(timeout=20)

#persist completion separately for each prefix, stage and correlation id
IDEMPOTENCY_DB = os.environ.get(
    'IDEMPOTENCY_DB', str(Path(__file__).with_name('part3-idempotency.sqlite3'))
)


def process_once(stage, incoming, target, transform, client):
    """Skip completed replays; return True only when publishing new output.

    SQLite locking also serializes duplicate checks across local Writer instances.
    This handles replay after recorded completion, including process restarts.
    Kafka publication and SQLite commit are NOT one atomic transaction: a crash
    after publication but before SQLite commit can still duplicate that output.
    Do not describe this exercise implementation as exactly-once delivery.
    """
    cid = incoming['correlation_id']
    payload = json.dumps(incoming, sort_keys=True, separators=(',', ':'))
    connection = sqlite3.connect(IDEMPOTENCY_DB, timeout=60)
    try:
        connection.execute(
            'CREATE TABLE IF NOT EXISTS completed ('
            'prefix TEXT, stage TEXT, correlation_id TEXT, payload TEXT NOT NULL, '
            'PRIMARY KEY (prefix, stage, correlation_id))'
        )
        connection.execute('BEGIN IMMEDIATE')
        previous = connection.execute(
            'SELECT payload FROM completed '
            'WHERE prefix=? AND stage=? AND correlation_id=?',
            (PREFIX, stage, cid),
        ).fetchone()
        if previous is not None:
            if previous[0] != payload:
                raise ValueError('correlation_id reused with different message data')
            log.info('%s DUPLICATE SKIP correlation_id=%s', stage, cid)
            connection.commit()
            return False
        outgoing = transform(incoming)
        if outgoing.get('correlation_id') != cid:
            raise ValueError('Stage changed correlation_id')
        publish(client, target, outgoing, stage)
        connection.execute(
            'INSERT INTO completed VALUES (?, ?, ?, ?)',
            (PREFIX, stage, cid, payload),
        )
        connection.commit()
        log.info('%s COMPLETED correlation_id=%s', stage, cid)
        return True
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


# PART 3: Three total attempts = first attempt plus two retries.
def process_with_retries(stage, record, target, transform, client):
    attempts = int(os.environ.get('MAX_PROCESSING_ATTEMPTS', '3'))
    if attempts < 1 or attempts > 10:
        raise ValueError('MAX_PROCESSING_ATTEMPTS must be between 1 and 10')
    cid = None
    for attempt in range(1, attempts + 1):
        try:
            incoming = json.loads(record.value)
            if not isinstance(incoming, dict):
                raise ValueError('Message must be a JSON object')
            cid = incoming.get('correlation_id')
            if not isinstance(cid, str) or not cid.strip():
                raise ValueError('Invalid correlation_id')
            log.info('%s ATTEMPT %s/%s topic=%s partition=%s offset=%s '
                     'correlation_id=%s', stage, attempt, attempts,
                     record.topic, record.partition, record.offset, cid)
            # PART 3 ordering: optional partition-dependent workload delay.
            # Applied BEFORE the SQLite transaction so it does not serialize
            # both Writers' processing delays. It affects ordering tests only.
            if incoming.get('ordering_run_id') and record.partition == 0:
                delay = float(os.environ.get('ORDERING_PARTITION0_DELAY', '0'))
                if not 0 <= delay <= 5:
                    raise ValueError('ORDERING_PARTITION0_DELAY must be 0..5')
                time.sleep(delay)

            def transform_with_metadata(message):
                outgoing = transform(message)
                if message.get('ordering_run_id'):
                    outgoing.update({field: message[field] for field in (
                        'ordering_run_id', 'ordering_mode',
                        'grocery_recall_notice_id', 'sequence', 'send_index')})
                    outgoing.update(writer_pid=os.getpid(),
                                    source_partition=record.partition,
                                    source_offset=record.offset)
                return outgoing

            processed = process_once(
                stage, incoming, target, transform_with_metadata, client)
            if processed and incoming.get('ordering_run_id'):
                log.info('WRITER ORDER PROCESSED pid=%s run=%s notice=%s '
                         'sequence=%s partition=%s offset=%s',
                         os.getpid(), incoming['ordering_run_id'],
                         incoming['grocery_recall_notice_id'], incoming['sequence'],
                         record.partition, record.offset)
            return cid
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            # Retry invalid payload/domain failures; Kafka and SQLite failures
            # propagate WITHOUT committing, rather than discarding valid work.
            log.warning('%s ATTEMPT FAILED %s/%s correlation_id=%s error=%s',
                        stage, attempt, attempts, cid, error)
            last_error = f'{type(error).__name__}: {error}'
            if attempt < attempts:
                time.sleep(1)

    #preserve the raw input 
    dead_letter = {
        'correlation_id': cid,
        'stage': stage,
        'source_topic': record.topic,
        'source_partition': record.partition,
        'source_offset': record.offset,
        'attempts': attempts,
        'error': last_error,
        'original_message_base64': base64.b64encode(record.value).decode('ascii'),
        'original_message_text': record.value.decode('utf-8', errors='replace'),
    }
    topic = f'{PREFIX}_dead_letter'
    key = cid.encode('utf-8') if isinstance(cid, str) else None
    #do not return to the input-offset commit until the dead letter send succeeds.
    client.send(topic, value=dead_letter, key=key).get(timeout=20)
    log.info('%s DEAD LETTER ACK topic=%s %s', stage, topic,
             json.dumps(dead_letter))
    return cid


def run_stage(stage, source_suffix, target_suffix, transform):
    source = f'{PREFIX}_{source_suffix}'
    target = f'{PREFIX}_{target_suffix}'
    consumer = KafkaConsumer(
        source, bootstrap_servers=BROKER,
        group_id=f'{PREFIX}_part2_{stage.lower()}',
        auto_offset_reset='earliest', enable_auto_commit=False,
    )
    client = producer()
    ready = False
    last_assignment = None
    try:
        while True:
            batches = consumer.poll(timeout_ms=1000, max_records=1)
            assignment = tuple(sorted(p.partition for p in consumer.assignment()))
            if assignment != last_assignment:
                log.info('WRITER ASSIGNMENT pid=%s group=%s partitions=%s',
                         os.getpid(), f'{PREFIX}_part2_writer', assignment)
                last_assignment = assignment
            if consumer.assignment() and not ready:
                log.info('%s READY topic=%s', stage, source)
                ready = True
            for batch in batches.values():
                for record in batch:
                    log.info('%s RECEIVE topic=%s partition=%s offset=%s raw=%s',
                             stage, source, record.partition, record.offset,
                             record.value.decode('utf-8', errors='replace'))
                    cid = process_with_retries(
                        stage, record, target, transform, client)
                    # Commit only after success, completed replay, or an
                    # acknowledged dead-letter publication after all attempts.
                    consumer.commit()
                    log.info('%s OFFSET COMMITTED partition=%s next_offset=%s '
                             'correlation_id=%s', stage, record.partition,
                             record.offset + 1, cid)
    except KeyboardInterrupt:
        log.info('%s STOP', stage)
    finally:
        consumer.close()
        client.close()


def make_draft(message):
    #optional delay exposes the mid-processing crash window.
    delay = float(os.environ.get('WRITER_DELAY_SECONDS', '0'))
    if delay < 0 or delay > 120:
        raise ValueError('WRITER_DELAY_SECONDS must be between 0 and 120')
    log.info('WRITER PROCESS START pid=%s correlation_id=%s delay_seconds=%s',
             os.getpid(), message['correlation_id'], delay)
    time.sleep(delay)
    sections = {
        'Identify the product and affected lot from the recall notice.':
            'Match the product name, lot code, and dates against the notice.',
        'Describe inventory isolation and sale blocking.':
            'Locate affected inventory, isolate it, and block its sale.',
        'Describe notification, disposition, and documentation.':
            'Notify responsible staff and the supplier; follow the notice for '
            'return or disposal, and document quantities and actions.',
    }
    draft = ' '.join(sections[step] for step in message['plan'])
    return {
        'correlation_id': message['correlation_id'],
        'question': message['question'],
        'plan': message['plan'],
        'draft': draft,
    }


if __name__ == '__main__':
    run_stage('WRITER', 'tasks', 'drafts', make_draft)

