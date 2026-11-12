"""Verify the committed HW9 tag with disposable services and write verification.json."""

import argparse
import io
import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
import uuid
import zipfile
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

SID4 = "1339"
SEED = 1339
VERIFY_SEED = 261339
MODEL = "llama3.2"
IMAGES = {"kafka": "apache/kafka:4.1.2", "redis": "redis:8"}
REQUIRED = (
    "code/hw7_authentication.py",
    "code/planner.py",
    "code/writer.py",
    "code/reviewer.py",
    "code/send_question.py",
    "code/semantic_api.py",
    "code/semantic_cache.py",
    "code/semantic_handler.py",
    "code/semantic_demo.py",
    "code/threshold_sweep.py",
    "code/cache_cases.yaml",
    "code/stale_demo.py",
    "code/hw9_part4/two_agent_system.py",
    "code/hw9_part4/lesson_store.py",
    "code/hw9_part4/validate_lessons.py",
    "code/hw9_part4/compare_variants.py",
    "code/hw9_part4/final_test.py",
    "code/hw9_part4/reference_data.json",
    "code/hw9_part4/training_data.json",
    "code/hw9_part4/validation_data.json",
    "code/hw9_part4/test_data.json",
    "code/hw9_part4/lessons.json",
    "src/model_client.py",
    "reports/hw09/raw/lessons_rejected_candidate.json",
)


def command(args, *, cwd=None, timeout=45):
    result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout)
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"{' '.join(map(str, args[:3]))}: {detail}")
    return result.stdout


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for(probe, label, timeout=90):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise TimeoutError(f"{label} was not ready. Last error: {last_error}")


def http_json(url, body=None, timeout=5):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def docker_remove(name):
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=25)


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def start_python(stack, code, logs, name, args, env):
    path = logs / f"{name}.log"
    with path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-u", *args],
            cwd=code,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    stack.callback(stop, process)
    return process, path


def wait_for_log(process, path, marker):
    def ready():
        return marker in path.read_text(encoding="utf-8", errors="replace")

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and process.poll() is None:
        if ready():
            return
        time.sleep(1)
    tail = path.read_text(encoding="utf-8", errors="replace")[-3000:]
    raise RuntimeError(f"{marker} was not reached. Process output: {tail}")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def run_checks(root, check):
    code = root / "code"
    part4 = code / "hw9_part4"
    sys.path[:0] = [str(part4), str(code), str(root)]
    logs = root / "smoke-logs"
    logs.mkdir()

    env = dict(os.environ)
    for name in (
        "SEMANTIC_FIXTURE_FILE",
        "SEMANTIC_REL_DATABASE_URL",
        "SEMANTIC_REL_RECORD_ID",
        "PYTHONOPTIMIZE",
    ):
        env.pop(name, None)
        os.environ.pop(name, None)
    run_id = uuid.uuid4().hex[:10]
    redis_port = free_port()
    kafka_port = free_port()
    api_port = free_port()
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{(root / 'smoke.db').as_posix()}",
            "JWT_SECRET_KEY": uuid.uuid4().hex,
            "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0",
            "REDIS_PREFIX": "s1339",
            "SEMANTIC_REDIS_URL": f"redis://127.0.0.1:{redis_port}/0",
            "SEMANTIC_CACHE_PREFIX": "s1339",
            "SEMANTIC_DATA_VERSION": "hw9-smoke",
            "KAFKA_BOOTSTRAP_SERVERS": f"127.0.0.1:{kafka_port}",
            "KAFKA_PREFIX": "s1339",
            "IDEMPOTENCY_DB": str(root / "smoke-idempotency.db"),
            "WRITER_DELAY_SECONDS": "0",
            "ORDERING_PARTITION0_DELAY": "0",
            "PYTHONHASHSEED": str(VERIFY_SEED),
            "SEED": str(SEED),
            "VERIFY_SEED": str(VERIFY_SEED),
        }
    )
    os.environ.update(env)
    random.seed(VERIFY_SEED)

    def datasets():
        import yaml

        data = yaml.safe_load(
            (code / "cache_cases.yaml").read_text(encoding="utf-8-sig")
        )
        expected = {
            "exact_duplicate",
            "paraphrase",
            "similar_but_different",
            "unrelated",
        }
        cases = data["cases"]
        require(len(data["baseline"]) == 10, "Expected ten cache seeds")
        require(len(cases) == 40, "Expected forty threshold cases")
        require(
            {case["category"] for case in cases} == expected, "Unexpected categories"
        )
        for category in expected:
            require(sum(c["category"] == category for c in cases) == 10, category)
        require(
            data["evaluation"]["thresholds"] == [0.75, 0.80, 0.85, 0.90, 0.95],
            "Unexpected threshold configuration",
        )
        for split in ("training", "validation", "test"):
            inputs = json.loads(
                (part4 / f"{split}_data.json").read_text(encoding="utf-8-sig")
            )
            require(
                inputs and all(set(c) == {"id", "question"} for c in inputs),
                f"Invalid {split} dataset",
            )
        return {"threshold_cases": 40, "thresholds": data["evaluation"]["thresholds"]}

    check("tagged_datasets", datasets)
    with ExitStack() as stack:

        def services():
            command(["docker", "version"])
            for service, image in IMAGES.items():
                name = f"hw9-smoke-{service}-{run_id}"
                stack.callback(docker_remove, name)
                docker = ["docker", "run", "-d", "--name", name]
                if service == "redis":
                    docker += ["-p", f"127.0.0.1:{redis_port}:6379"]
                else:
                    docker += ["-p", f"127.0.0.1:{kafka_port}:9092"]
                    settings = {
                        "KAFKA_NODE_ID": "1",
                        "KAFKA_PROCESS_ROLES": "broker,controller",
                        "KAFKA_LISTENERS": "PLAINTEXT://:9092,CONTROLLER://:9093",
                        "KAFKA_ADVERTISED_LISTENERS": f"PLAINTEXT://127.0.0.1:{kafka_port}",
                        "KAFKA_CONTROLLER_LISTENER_NAMES": "CONTROLLER",
                        "KAFKA_CONTROLLER_QUORUM_VOTERS": "1@localhost:9093",
                        "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1",
                        "KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS": "0",
                        "KAFKA_AUTO_CREATE_TOPICS_ENABLE": "false",
                    }
                    for key, value in settings.items():
                        docker += ["-e", f"{key}={value}"]
                command([*docker, image], timeout=300)

            import redis
            from kafka.admin import KafkaAdminClient, NewTopic

            with redis.Redis.from_url(env["REDIS_URL"]) as client:
                wait_for(client.ping, "Redis")
                require(
                    client.execute_command("COMMAND INFO", "FT.CREATE"),
                    "Redis vector search is unavailable",
                )

            def kafka_ready():
                client = KafkaAdminClient(
                    bootstrap_servers=env["KAFKA_BOOTSTRAP_SERVERS"],
                    request_timeout_ms=5000,
                )
                try:
                    client.list_topics()
                    return True
                finally:
                    client.close()

            wait_for(kafka_ready, "Kafka", timeout=120)
            topics = {
                "entity_requests": 1,
                "entity_responses": 1,
                "inbox": 1,
                "tasks": 2,
                "drafts": 1,
                "final": 1,
                "dead_letter": 1,
            }
            client = KafkaAdminClient(bootstrap_servers=env["KAFKA_BOOTSTRAP_SERVERS"])
            try:
                client.create_topics(
                    [
                        NewTopic(f"s1339_{name}", partitions, 1)
                        for name, partitions in topics.items()
                    ]
                )
                expected = {f"s1339_{name}" for name in topics}
                wait_for(lambda: expected <= set(client.list_topics()), "Kafka topics")
            finally:
                client.close()
            return {"topics": sorted(expected), "images": IMAGES}

        service_ok = check("isolated_kafka_and_redis", services)
        model_ok = check("local_model_available", lambda: check_model())

        def round_trip():
            import hw7_authentication as hw

            stack.callback(hw.engine.dispose)
            stack.callback(hw.redis_client.close)

            with hw.SessionLocal() as db:
                supplier = hw.RelatedEntity(
                    primary_text="Smoke supplier",
                    secondary_text="Verification fixture",
                    code="HW9_SMOKE_SUPPLIER",
                )
                db.add(supplier)
                db.flush()
                supplier_id = supplier.id
                db.commit()

            with ExitStack() as workers:
                proc, path = start_python(
                    workers,
                    code,
                    logs,
                    "counter-worker",
                    ["hw7_authentication.py", "worker"],
                    env,
                )
                wait_for_log(proc, path, "Consumer is ready and listening")
                fields = {
                    "name": "Smoke notice",
                    "description": "Verification fixture",
                    "unique_code": "HW9_SMOKE_NOTICE",
                    "quantity": 3,
                    "related_entity_id": supplier_id,
                }
                created = hw.send_request("CREATE_GROCERY_RECALL_NOTICE", fields)
                require(created["success"], created)
                notice_id = created["grocery_recall_notice_id"]
                for count in range(1, 12):
                    reply = hw.send_request(
                        "GET_GROCERY_RECALL_NOTICE",
                        {
                            "grocery_recall_notice_id": notice_id,
                        },
                    )
                    require(reply["success"], reply)
                    notice = reply["grocery_recall_notice"]
                    require(notice["grocery_recall_notice_id"] == notice_id, "Wrong ID")
                    require(
                        all(notice[k] == v for k, v in fields.items()), "Wrong fields"
                    )
                    require(
                        notice["view_count"] == count, "Unexpected running view count"
                    )
            with hw.SessionLocal() as db:
                saved = db.get(hw.GroceryRecallNotice, notice_id).view_count
            key = f"s1339:views:grocery_recall_notice:{notice_id}"
            live = int(hw.redis_client.get(key))
            require((live, saved) == (11, 10), "Expected 11 in Redis and 10 in SQLite")
            return {
                "kafka_round_trip": True,
                "redis_count": live,
                "database_count": saved,
            }

        def start_agents(group, settings, label):
            for stage in ("planner", "writer", "reviewer"):
                proc, path = start_python(
                    group,
                    code,
                    logs,
                    f"{label}-{stage}",
                    [f"{stage}.py"],
                    settings,
                )
                wait_for_log(proc, path, f"{stage.upper()} READY")

        def semantic_endpoint():
            with ExitStack() as agents:
                start_agents(agents, env, "qa")
                proc, path = start_python(
                    agents,
                    code,
                    logs,
                    "qa-api",
                    [
                        "-m",
                        "uvicorn",
                        "semantic_api:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(api_port),
                    ],
                    env,
                )
                wait_for_log(proc, path, "Application startup complete")
                base = f"http://127.0.0.1:{api_port}"
                body = {
                    "question": (
                        "What should a grocery store do after receiving "
                        "a supplier recall notice?"
                    )
                }
                first = http_json(base + "/qa", body, timeout=240)
                second = http_json(base + "/qa", body, timeout=240)
                require(
                    first["is_cached"] is False and first["timings_ms"]["agent"] > 0,
                    "Cold request did not use the agent pipeline",
                )
                require(
                    second["is_cached"] is True and second["timings_ms"]["agent"] == 0,
                    "Repeated request did not skip the pipeline",
                )
                require(
                    bool(first["answer"].strip())
                    and first["answer"] == second["answer"],
                    "Stored answer was not reused",
                )
                require(
                    second["similarity_score"] >= 0.99, "Exact query similarity was low"
                )
                metrics = http_json(base + "/qa/metrics")
                require(metrics["cache_hits"] == metrics["cache_misses"] == 1, metrics)
                return {
                    "hit_rate_percent": metrics["cache_hit_rate_percent"],
                    "miss_ms": first["latency_ms"],
                    "hit_ms": second["latency_ms"],
                }

        def threshold_sample():
            import yaml
            from semantic_cache import SemanticCache

            data = yaml.safe_load(
                (code / "cache_cases.yaml").read_text(encoding="utf-8-sig")
            )
            with patch.dict(os.environ, SEMANTIC_DATA_VERSION="hw9-threshold-smoke"):
                cache = SemanticCache()
            try:
                seed = data["baseline"][0]
                cache.store(seed["query"], cache.embed(seed["query"]), seed["answer"])
                sample = next(
                    case for case in data["cases"] if case["id"] == "similar_01"
                )
                exact_vec = cache.embed(seed["query"])
                sample_vec = cache.embed(sample["query"])
                rows = []
                for threshold in data["evaluation"]["thresholds"]:
                    cache.threshold = threshold
                    exact = cache.lookup(exact_vec)
                    candidate = cache.lookup(sample_vec)
                    require(exact["is_cached"] is True, "Exact repeat missed")
                    score = candidate["similarity_score"]
                    require(score is not None, "Expected a nearest candidate")
                    require(
                        candidate["is_cached"] == (score >= threshold),
                        "Bad threshold rule",
                    )
                    incorrect = int(
                        candidate["is_cached"] and not sample["expected_hit"]
                    )
                    misses = int(not candidate["is_cached"])
                    rows.append(
                        {
                            "threshold": threshold,
                            "score": score,
                            "false_hits": incorrect,
                            "cost_units": misses + 100 * incorrect,
                        }
                    )
                return {"sample_case": sample["id"], "rows": rows}
            finally:
                cache.client.close()

        def stale_answer():
            command([sys.executable, "stale_demo.py", "setup"], cwd=code)
            rel_env = dict(
                env,
                SEMANTIC_REL_DATABASE_URL=(
                    f"sqlite:///{(code / 'reports' / 'part3_rel.db').as_posix()}"
                ),
                SEMANTIC_REL_RECORD_ID="STALE001",
                SEMANTIC_FIXTURE_FILE=str(code / "cache_cases.yaml"),
            )
            with ExitStack() as agents:
                start_agents(agents, rel_env, "stale")
                command([sys.executable, "stale_demo.py", "run"], cwd=code, timeout=600)
            (path,) = (code / "reports").glob("stale_demo_*.json")
            data = json.loads(path.read_text(encoding="utf-8"))
            require(data["complete"], "Stale demo did not complete")
            require(
                [s["response"]["is_cached"] for s in data["steps"]]
                == [False, True, False, True],
                "Unexpected cache sequence",
            )
            return {
                "steps": [
                    {
                        "label": s["label"],
                        "quantity": s["database_record"]["affected_quantity"],
                        "version": s["database_record"]["data_version"],
                        "cached": s["response"]["is_cached"],
                    }
                    for s in data["steps"]
                ]
            }

        def repair_and_reuse():
            import lesson_store
            from compare_variants import run_baseline
            from two_agent_system import run_case
            from validate_lessons import run_condition

            # Keep all lesson writes in the disposable archive directory.
            lesson_store.LESSONS_PATH = root / "smoke-lessons.json"
            lesson_store.FAILURES_PATH = root / "smoke-failures.json"
            reference = json.loads(
                (part4 / "reference_data.json").read_text(encoding="utf-8-sig")
            )
            training = json.loads(
                (part4 / "training_data.json").read_text(encoding="utf-8-sig")
            )
            cases = {case["id"]: case for case in training}
            for _ in range(2):
                repair = run_case(cases["train_01"], reference, controlled_failure=True)
                require(repair["attempt_count"] == 2, "Controlled case did not revise")
                require(
                    repair["attempts"][0]["evaluation"]["result"] == "REVISE",
                    "Evaluator accepted injected wrong quantity",
                )
                require(
                    repair["final_evaluation"]["result"] == "PASS"
                    and "120" in repair["final_answer"],
                    "Correct repair did not pass",
                )

            reused = run_case(cases["train_04"], reference)
            require(
                "lesson_quantity_001" in reused["attempts"][0]["loaded_lesson_ids"],
                "Later question did not load the lesson",
            )
            require(
                reused["final_evaluation"]["result"] == "PASS"
                and "75" in reused["final_answer"],
                "Reuse answer did not pass",
            )

            lesson_file = lesson_store.LESSONS_PATH
            snapshot = lesson_file.read_bytes()
            memory = json.loads(
                (root / "reports/hw09/raw/lessons_rejected_candidate.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            selected = json.loads(
                (part4 / "lessons.json").read_text(encoding="utf-8-sig")
            )
            require(selected == [], "Expected the selected empty lesson set")
            require(
                any(lesson["lesson_id"] == "lesson_quantity_001" for lesson in memory),
                "Archived training lesson missing",
            )

            # Exercise the variant paths on training data, not held-out inputs.
            sample = cases["train_04"]
            results = {
                "Baseline": run_baseline(sample, reference),
                "Evaluator Repair": run_condition(sample, reference, []),
                "Lesson Memory": run_condition(sample, reference, memory),
                "Validated Improvement": run_condition(sample, reference, selected),
            }
            for name, result in results.items():
                expected = ["lesson_quantity_001"] if name == "Lesson Memory" else []
                attempts = result["attempts"]
                limit = 1 if name == "Baseline" else 2
                require(1 <= len(attempts) <= limit, f"{name}: invalid attempt count")
                require(
                    all(a["loaded_lesson_ids"] == expected for a in attempts),
                    f"{name}: wrong lesson configuration",
                )
            validation = json.loads(
                (part4 / "validation_data.json").read_text(encoding="utf-8-sig")
            )
            validation_case = next(c for c in validation if c["id"] == "validation_07")
            before = run_condition(validation_case, reference, [])
            after = run_condition(validation_case, reference, memory)
            require(
                all(not a["loaded_lesson_ids"] for a in before["attempts"]),
                "Validation baseline loaded a lesson",
            )
            require(
                all(
                    a["loaded_lesson_ids"] == ["lesson_quantity_001"]
                    for a in after["attempts"]
                ),
                "Validation did not load candidate",
            )
            require(lesson_file.read_bytes() == snapshot, "Scoring changed lessons")
            return {
                "repair_attempts": 2,
                "lesson_reused": True,
                "validation_sample": {
                    "case_id": validation_case["id"],
                    "before_initial_pass": before["initial_pass"],
                    "after_initial_pass": after["initial_pass"],
                    "before_final_pass": before["final_pass"],
                    "after_final_pass": after["final_pass"],
                },
                "variants": {
                    name: {
                        "attempts": len(result["attempts"]),
                        "final_pass": result["final_pass"],
                    }
                    for name, result in results.items()
                },
            }

        check(
            "part1_kafka_round_trip_and_counter",
            round_trip,
            blocked=None if service_ok else "Kafka or Redis startup failed",
        )
        blocker = (
            None
            if service_ok and model_ok
            else "Kafka, Redis, or local model unavailable"
        )
        check("part2_http_cache_miss_and_hit", semantic_endpoint, blocked=blocker)
        check(
            "part3_threshold_sample",
            threshold_sample,
            blocked=None if service_ok else "Redis startup failed",
        )
        check("part3_stale_answer_invalidation", stale_answer, blocked=blocker)
        check(
            "part4_repair_lesson_reuse_and_variant_paths",
            repair_and_reuse,
            blocked=None if model_ok else "Local model unavailable",
        )


def check_model():
    result = http_json("http://localhost:11434/api/tags")
    names = {model["name"] for model in result["models"]}
    require(
        MODEL in names or MODEL + ":latest" in names, f"Ollama model {MODEL} is missing"
    )
    return {"model": MODEL, "endpoint": "http://localhost:11434"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = (args.output or repo / "reports/hw09/verification.json").resolve()
    report = {
        "homework_number": 9,
        "SID4": SID4,
        "tag": "hw9",
        "commit_hash": None,
        "SEED": SEED,
        "VERIFY_SEED": VERIFY_SEED,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "model": MODEL,
            "temperature": 0.0,
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "prefix": "s1339",
            "python": sys.version.split()[0],
            "docker_images": IMAGES,
            "seed_scope": (
                "Python seeded; Ollama seed is unavailable through the adapter"
            ),
            "scope": "Smoke checks; full sweep and held-out experiments are separate",
        },
        "checks": [],
        "passed": False,
    }

    def check(name, function, *, blocked=None):
        if blocked:
            entry = {"name": name, "ran": False, "passed": False, "detail": blocked}
        else:
            try:
                detail = function()
                entry = {"name": name, "ran": True, "passed": True, "detail": detail}
            except Exception as exc:
                entry = {
                    "name": name,
                    "ran": True,
                    "passed": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
                traceback.print_exc()
        report["checks"].append(entry)
        print(f"{'PASS' if entry['passed'] else 'FAIL'} {name}", flush=True)
        return entry["passed"]

    def archive_tag(root):
        try:
            commit = (
                command(
                    ["git", "rev-parse", "--verify", "refs/tags/hw9^{commit}"],
                    cwd=repo,
                )
                .decode()
                .strip()
            )
        except RuntimeError as exc:
            raise RuntimeError(
                "Cannot resolve the hw9 tag. Commit the complete HW9 submission "
                "and create the hw9 tag before running verification."
            ) from exc
        report["commit_hash"] = commit
        archive = command(
            ["git", "archive", "--format=zip", commit], cwd=repo, timeout=120
        )
        with zipfile.ZipFile(io.BytesIO(archive)) as files:
            for entry in files.infolist():
                require(
                    (root / entry.filename).resolve().is_relative_to(root),
                    "Unsafe path in Git archive",
                )
            files.extractall(root)
        missing = [name for name in REQUIRED if not (root / name).is_file()]
        require(not missing, "Files absent from hw9 tag: " + ", ".join(missing))
        return {"commit": commit, "required_files": len(REQUIRED)}

    try:
        with tempfile.TemporaryDirectory(prefix="hw9-smoke-") as directory:
            root = Path(directory).resolve()
            if check("tagged_source_and_inputs", lambda: archive_tag(root)):
                check("smoke_test_runner", lambda: run_checks(root, check))
    finally:
        report["passed"] = bool(report["checks"]) and all(
            c["passed"] for c in report["checks"]
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Verification report: {output}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
