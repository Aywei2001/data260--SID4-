import json
import argparse
from pathlib import Path
from time import monotonic
from uuid import uuid4
from kafka import KafkaConsumer, TopicPartition
from send_question import BROKER, PREFIX, producer, publish
from urllib.error import HTTPError
from urllib.request import Request, urlopen

QUESTION = "What should a grocery store do after receiving a supplier recall notice?"
REPORTS = Path(__file__).resolve().parents[1] / "reports" / "hw10" / "pipeline_cases"
TOPICS = {
    f"{PREFIX}_tasks": ("plan", "plan"),
    f"{PREFIX}_drafts": ("draft", "draft"),
    f"{PREFIX}_final": ("final", "answer"),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default=QUESTION)
    parser.add_argument("--via-api", action="store_true")
    args = parser.parse_args()
    question = args.question.strip()
    if not question:
        parser.error("Question must not be blank")

    topics = dict(TOPICS)
    if args.via_api:
        topics[f"{PREFIX}_inbox"] = ("inbox", "question")

    correlation_id = None if args.via_api else str(uuid4())
    messages = {}
    reader = KafkaConsumer(
        bootstrap_servers=BROKER,
        group_id=None,
        enable_auto_commit=False,
        request_timeout_ms=10000,
        api_version_auto_timeout_ms=5000,
    )
    sender = None

    try:
        partitions = []
        for topic in topics:
            available = reader.partitions_for_topic(topic)
            if not available:
                raise RuntimeError(f"Missing Kafka topic: {topic}")
            partitions.extend(TopicPartition(topic, p) for p in sorted(available))

        # Start listening before sending the question.
        reader.assign(partitions)
        end_offsets = reader.end_offsets(partitions)
        for partition, offset in end_offsets.items():
            reader.seek(partition, offset)

        if args.via_api:
            request = Request(
                "http://127.0.0.1:8440/qa",
                data=json.dumps({"question": question}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=240) as response:
                    correlation_id = response.headers.get("X-Trace-ID")
                    result = json.load(response)
            except HTTPError as exc:
                trace_id = exc.headers.get("X-Trace-ID", "unavailable")
                raise RuntimeError(
                    f"/qa returned HTTP {exc.code}, trace {trace_id}"
                ) from exc

            if not correlation_id or result.get("trace_id") != correlation_id:
                raise RuntimeError("/qa response is missing a consistent trace ID")
            if result.get("is_cached") is not False:
                raise RuntimeError(
                    f"Trace {correlation_id} was a cache hit. Use a fresh cache version."
                )
            print(f"API cache miss, trace {correlation_id}", flush=True)
        else:
            sender = producer()
            publish(
                sender,
                f"{PREFIX}_inbox",
                {"correlation_id": correlation_id, "question": question},
                "HW10 EVAL",
            )

        deadline = monotonic() + 180
        while len(messages) < len(topics) and monotonic() < deadline:
            for batch in reader.poll(timeout_ms=500).values():
                for record in batch:
                    try:
                        payload = json.loads(record.value)
                    except (ValueError, UnicodeError):
                        print(f"Skipping malformed JSON at {record.topic}:{record.offset}")
                        continue

                    if not isinstance(payload, dict):
                        continue
                    if payload.get("correlation_id") != correlation_id:
                        continue

                    stage, field = topics[record.topic]
                    expected_type = list if stage == "plan" else str
                    value = payload.get(field)
                    if not isinstance(value, expected_type) or not value:
                        raise ValueError(f"Matching {stage} message has an invalid {field}")

                    messages.setdefault(stage, {
                        "topic": record.topic,
                        "partition": record.partition,
                        "offset": record.offset,
                        "timestamp_ms": record.timestamp,
                        "payload": payload,
                    })

        missing = {stage for stage, field in topics.values()} - messages.keys()
        if missing:
            raise TimeoutError(f"{correlation_id}: missing {', '.join(sorted(missing))}")

        REPORTS.mkdir(parents=True, exist_ok=True)
        path = REPORTS / f"{correlation_id}.json"
        path.write_text(json.dumps({
            "trace_id": correlation_id,
            "correlation_id": correlation_id,
            "question": question,
            "messages": messages,
        }, indent=2), encoding="utf-8")
        print(f"Saved {path}")

    finally:
        if sender is not None:
            sender.close(timeout=5)
        reader.close()


if __name__ == "__main__":
    main()