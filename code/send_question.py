#send one question and read its matching final JSON from Kafka."""
import argparse
import json
import time
from uuid import uuid4

from kafka import KafkaConsumer, TopicPartition

#kafka transport is local to this script; no shared helper is required.
import logging

import os

from kafka import KafkaProducer

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('question', nargs='?', default=
                        'What steps should a grocery store follow after '
                        'receiving a supplier recall notice?')
    args = parser.parse_args()
    final_topic = f'{PREFIX}_final'
    consumer = KafkaConsumer(bootstrap_servers=BROKER, group_id=None,
                             enable_auto_commit=False)
    client = producer()
    try:
        partitions = consumer.partitions_for_topic(final_topic)
        if not partitions:
            raise RuntimeError('Create the four Part 2 topics first')
        assigned = [TopicPartition(final_topic, p) for p in sorted(partitions)]
        consumer.assign(assigned)
        consumer.seek_to_end(*assigned)
        for partition in assigned:
            consumer.position(partition)
        cid = str(uuid4())
        publish(client, f'{PREFIX}_inbox',
                {'correlation_id': cid, 'question': args.question}, 'YOU')
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            for batch in consumer.poll(timeout_ms=500).values():
                for record in batch:
                    result = json.loads(record.value)
                    if result.get('correlation_id') == cid:
                        log.info('YOU RECEIVE topic=%s correlation preserved=True %s',
                                 final_topic, json.dumps(result))
                        print(json.dumps(result, indent=2))
                        return
        raise TimeoutError(f'No final response for correlation_id={cid}')
    finally:
        consumer.close()
        client.close()


if __name__ == '__main__':
    main()
