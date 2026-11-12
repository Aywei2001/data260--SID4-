import base64
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

from kafka import KafkaConsumer, KafkaProducer

PREFIX = os.environ.get("KAFKA_PREFIX", "s1339")

BROKER = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

logging.getLogger("kafka").setLevel(logging.WARNING)

log = logging.getLogger("pipeline")


def producer():
    return KafkaProducer(
        bootstrap_servers=BROKER,
        acks="all",
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )


def publish(client, topic, message, stage):
    log.info("%s SEND topic=%s %s", stage, topic, json.dumps(message))
    client.send(
        topic, value=message, key=message["correlation_id"].encode("utf-8")
    ).get(timeout=20)


# persist completion separately for each prefix, stage and correlation id
IDEMPOTENCY_DB = os.environ.get(
    "IDEMPOTENCY_DB", str(Path(__file__).with_name("part3-idempotency.sqlite3"))
)


def process_once(stage, incoming, target, transform, client):
    """Skip completed replays; return True only when publishing new output.

    SQLite locking also serializes duplicate checks across local Writer instances.
    This handles replay after recorded completion, including process restarts.
    Kafka publication and SQLite commit are NOT one atomic transaction: a crash
    after publication but before SQLite commit can still duplicate that output.
    Do not describe this exercise implementation as exactly-once delivery.
    """
    cid = incoming["correlation_id"]
    payload = json.dumps(incoming, sort_keys=True, separators=(",", ":"))
    connection = sqlite3.connect(IDEMPOTENCY_DB, timeout=60)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS completed ("
            "prefix TEXT, stage TEXT, correlation_id TEXT, payload TEXT NOT NULL, "
            "PRIMARY KEY (prefix, stage, correlation_id))"
        )
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute(
            "SELECT payload FROM completed "
            "WHERE prefix=? AND stage=? AND correlation_id=?",
            (PREFIX, stage, cid),
        ).fetchone()
        if previous is not None:
            if previous[0] != payload:
                raise ValueError("correlation_id reused with different message data")
            log.info("%s DUPLICATE SKIP correlation_id=%s", stage, cid)
            connection.commit()
            return False
        outgoing = transform(incoming)
        if outgoing.get("correlation_id") != cid:
            raise ValueError("Stage changed correlation_id")
        publish(client, target, outgoing, stage)
        connection.execute(
            "INSERT INTO completed VALUES (?, ?, ?, ?)",
            (PREFIX, stage, cid, payload),
        )
        connection.commit()
        log.info("%s COMPLETED correlation_id=%s", stage, cid)
        return True
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


# three total attempts
# first attempt plus two retries.
def process_with_retries(stage, record, target, transform, client):
    attempts = int(os.environ.get("MAX_PROCESSING_ATTEMPTS", "3"))
    if attempts < 1 or attempts > 10:
        raise ValueError("MAX_PROCESSING_ATTEMPTS must be between 1 and 10")
    cid = None
    for attempt in range(1, attempts + 1):
        try:
            incoming = json.loads(record.value)
            if not isinstance(incoming, dict):
                raise ValueError("Message must be a JSON object")
            cid = incoming.get("correlation_id")
            if not isinstance(cid, str) or not cid.strip():
                raise ValueError("Invalid correlation_id")
            log.info(
                "%s ATTEMPT %s/%s topic=%s partition=%s offset=%s correlation_id=%s",
                stage,
                attempt,
                attempts,
                record.topic,
                record.partition,
                record.offset,
                cid,
            )
            process_once(stage, incoming, target, transform, client)
            return cid
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            log.warning(
                "%s ATTEMPT FAILED %s/%s correlation_id=%s error=%s",
                stage,
                attempt,
                attempts,
                cid,
                error,
            )
            last_error = f"{type(error).__name__}: {error}"
            if attempt < attempts:
                time.sleep(1)

    # preserve the raw input
    dead_letter = {
        "correlation_id": cid,
        "stage": stage,
        "source_topic": record.topic,
        "source_partition": record.partition,
        "source_offset": record.offset,
        "attempts": attempts,
        "error": last_error,
        "original_message_base64": base64.b64encode(record.value).decode("ascii"),
        "original_message_text": record.value.decode("utf-8", errors="replace"),
    }
    topic = f"{PREFIX}_dead_letter"
    key = cid.encode("utf-8") if isinstance(cid, str) else None
    # do not return to the input-offset commit until the dead letter send succeeds
    client.send(topic, value=dead_letter, key=key).get(timeout=20)
    log.info("%s DEAD LETTER ACK topic=%s %s", stage, topic, json.dumps(dead_letter))
    return cid


def run_stage(stage, source_suffix, target_suffix, transform):
    source = f"{PREFIX}_{source_suffix}"
    target = f"{PREFIX}_{target_suffix}"
    consumer = KafkaConsumer(
        source,
        bootstrap_servers=BROKER,
        group_id=f"{PREFIX}_part2_{stage.lower()}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    client = producer()
    ready = False
    try:
        while True:
            batches = consumer.poll(timeout_ms=1000, max_records=1)
            if consumer.assignment() and not ready:
                log.info("%s READY topic=%s", stage, source)
                ready = True
            for batch in batches.values():
                for record in batch:
                    log.info(
                        "%s RECEIVE topic=%s partition=%s offset=%s raw=%s",
                        stage,
                        source,
                        record.partition,
                        record.offset,
                        record.value.decode("utf-8", errors="replace"),
                    )
                    cid = process_with_retries(stage, record, target, transform, client)
                    # commit only after success, completed replay, or an acknowledged dead letter publication after all attempts.
                    consumer.commit()
                    log.info(
                        "%s OFFSET COMMITTED partition=%s next_offset=%s "
                        "correlation_id=%s",
                        stage,
                        record.partition,
                        record.offset + 1,
                        cid,
                    )
    except KeyboardInterrupt:
        log.info("%s STOP", stage)
    finally:
        consumer.close()
        client.close()


def review(message):
    draft = message["draft"]

    if os.environ.get("SEMANTIC_FIXTURE_FILE"):
        approved = isinstance(draft, str) and bool(draft.strip())
    else:
        required = ("lot", "isolate", "block", "notify", "document")
        approved = isinstance(draft, str) and all(
            word in draft.lower() for word in required
        )

    return {
        "correlation_id": message["correlation_id"],
        "status": "approved" if approved else "needs_revision",
        "answer": draft,
    }


if __name__ == "__main__":
    run_stage("REVIEWER", "drafts", "final", review)
