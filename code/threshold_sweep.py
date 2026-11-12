import argparse
import hashlib
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import yaml

from semantic_cache import SemanticCache
from send_question import ask_pipeline


ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "cache_cases.yaml"
REPORTS = ROOT / "reports"
BASELINE_PATH = REPORTS / "part3_baseline_answers.json"

log = logging.getLogger("threshold_sweep")


def save_json(path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_dataset():
    raw = DATASET_PATH.read_bytes()
    dataset = yaml.safe_load(raw.decode("utf-8-sig"))

    cases = dataset["cases"]
    baseline = dataset["baseline"]

    expected_categories = {
        "exact_duplicate": 10,
        "paraphrase": 10,
        "similar_but_different": 10,
        "unrelated": 10,
    }

    if len(baseline) != 10 or len(cases) != 40:
        raise ValueError("Expected 10 baseline entries and 40 cases")

    if Counter(c["category"] for c in cases) != expected_categories:
        raise ValueError("Expected exactly 10 cases in each category")

    if sum(c["expected_hit"] for c in cases) != 20:
        raise ValueError("Expected 20 hit labels and 20 miss labels")

    if len({c["id"] for c in cases}) != 40:
        raise ValueError("Case IDs must be unique")

    seed_ids = {seed["id"] for seed in baseline}
    for case in cases:
        if case["expected_hit"]:
            if case["expected_seed_id"] not in seed_ids:
                raise ValueError(f"Invalid seed reference: {case['id']}")

    digest = hashlib.sha256(raw).hexdigest()
    return dataset, digest


def pipeline_answer(question):
    result = ask_pipeline(question, timeout=180)

    if result.get("status") != "approved":
        raise RuntimeError(f"Pipeline returned an unapproved result: {result}")

    answer = result.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Pipeline returned no final answer")

    return answer


def prepare_baseline(dataset, digest):
    if BASELINE_PATH.exists():
        raise RuntimeError(
            f"{BASELINE_PATH} already exists. Review it rather than "
            "overwriting previously generated baseline answers."
        )

    document = {
        "dataset_sha256": digest,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "answers": [],
    }

    for seed in dataset["baseline"]:
        print(f"\nGenerating {seed['id']}: {seed['query']}", flush=True)
        answer = pipeline_answer(seed["query"])

        item = {
            **seed,
            "reference_answer": seed["answer"],
            "answer": answer,
        }

        document["answers"].append(item)
        save_json(BASELINE_PATH, document)

        print("Reference:", item["reference_answer"])
        print("Generated:", answer, flush=True)

    print(f"\nSaved: {BASELINE_PATH}")
    print("Review all 10 answers against their references before the sweep.")


def run_sweep(dataset, digest):
    document = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    if document["dataset_sha256"] != digest:
        raise ValueError("Dataset changed after baseline preparation")

    prepared = document["answers"]
    expected_ids = {seed["id"] for seed in dataset["baseline"]}

    if (
        len(prepared) != 10
        or {seed["id"] for seed in prepared} != expected_ids
    ):
        raise ValueError("Baseline preparation is incomplete")

    #new version isolates this run from previous cache entries.
    run_id = uuid4().hex
    os.environ["SEMANTIC_DATA_VERSION"] = f"part3-sweep-{run_id}"

    cache = SemanticCache()
    created_keys = []

    report_path = REPORTS / f"threshold_sweep_{run_id}.json"
    csv_path = REPORTS / f"threshold_summary_{run_id}.csv"

    report = {
        "run_id": run_id,
        "dataset_sha256": digest,
        "data_version": cache.data_version,
        "embedding_model": cache.model_name,
        "baseline_policy": "Fixed 10 reviewed pipeline answers",
        "evaluation_misses_stored": False,
        "false_hit_rate_definition": (
            "False hits among expected-miss cases / 20"
        ),
        "latency_definition": (
            "Embedding, lookup, and real pipeline execution on misses; "
            "excludes startup, baseline preparation, and report file writes"
        ),
        "baseline_answers": prepared,
        "rows": [],
        "results": [],
        "complete": False,
    }

    save_json(report_path, report)

    try:
        key_to_seed = {}

        for seed in prepared:
            embedding = cache.embed(seed["query"])
            key = cache.store(seed["query"], embedding, seed["answer"])
            created_keys.append(key)
            key_to_seed[key] = seed["id"]

        for threshold in dataset["evaluation"]["thresholds"]:
            cache.threshold = float(threshold)
            threshold_results = []

            for case in dataset["cases"]:
                print(
                    f"\nThreshold {threshold:.2f} | {case['id']}",
                    flush=True,
                )

                started = perf_counter()

                operation_started = perf_counter()
                embedding = cache.embed(case["query"])
                embedding_ms = (
                    perf_counter() - operation_started
                ) * 1000

                operation_started = perf_counter()
                match = cache.lookup(embedding)
                lookup_ms = (
                    perf_counter() - operation_started
                ) * 1000

                agent_ms = 0.0

                if match["is_cached"]:
                    answer = match["answer"]
                    log.info(
                        "Cache hit similarity=%s",
                        match["similarity_score"],
                    )
                else:
                    log.info(
                        "Cache miss nearest_similarity=%s",
                        match["similarity_score"],
                    )
                    operation_started = perf_counter()
                    answer = pipeline_answer(case["query"])
                    agent_ms = (
                        perf_counter() - operation_started
                    ) * 1000

                    

                latency_ms = (perf_counter() - started) * 1000

                matched_key = match["matched_key"]
                if isinstance(matched_key, bytes):
                    matched_key = matched_key.decode("utf-8")

                matched_seed = key_to_seed.get(matched_key)
                hit = match["is_cached"]

                false_hit = hit and not case["expected_hit"]
                wrong_seed_hit = (
                    hit
                    and case["expected_hit"]
                    and matched_seed != case["expected_seed_id"]
                )

                item = {
                    "threshold": threshold,
                    "case_id": case["id"],
                    "category": case["category"],
                    "query": case["query"],
                    "expected_hit": case["expected_hit"],
                    "expected_seed_id": case["expected_seed_id"],
                    "is_cached": hit,
                    "matched_seed_id": matched_seed,
                    "matched_query": match["matched_query"],
                    "matched_answer": match["matched_answer"],
                    "similarity_score": match["similarity_score"],
                    "returned_answer": answer,
                    "correct_answer": case["correct_answer"],
                    "false_hit": false_hit,
                    "wrong_seed_hit": wrong_seed_hit,
                    "incorrect_hit": false_hit or wrong_seed_hit,
                    "latency_ms": latency_ms,
                    "timings_ms": {
                        "embedding": embedding_ms,
                        "lookup": lookup_ms,
                        "agent": agent_ms,
                    },
                }

                threshold_results.append(item)
                report["results"].append(item)
                save_json(report_path, report)

                print(
                    f"cached={hit} "
                    f"similarity={match['similarity_score']} "
                    f"false_hit={false_hit} "
                    f"latency_ms={latency_ms:.2f}",
                    flush=True,
                )

            hits = sum(r["is_cached"] for r in threshold_results)
            false_hits = sum(r["false_hit"] for r in threshold_results)
            wrong_seeds = sum(
                r["wrong_seed_hit"] for r in threshold_results
            )

            row = {
                "threshold": threshold,
                "queries": 40,
                "hits": hits,
                "misses": 40 - hits,
                "false_hits": false_hits,
                "wrong_seed_hits": wrong_seeds,
                "incorrect_hits": false_hits + wrong_seeds,
                "hit_rate_percent": 100 * hits / 40,
                "false_hit_rate_percent": 100 * false_hits / 20,
                "mean_latency_ms": sum(
                    r["latency_ms"] for r in threshold_results
                ) / 40,
                "total_cost": None,
            }

            report["rows"].append(row)
            save_json(report_path, report)

        report["complete"] = True

        import csv

        with csv_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(report["rows"][0]),
            )
            writer.writeheader()
            writer.writerows(report["rows"])

        print("\nCompleted threshold table:")
        print(json.dumps(report["rows"], indent=2))
        print("Detailed report:", report_path)
        print("Summary CSV:", csv_path)

    except Exception as exc:
        report["error"] = str(exc)
        print(f"\nSweep stopped. Partial results saved to {report_path}")
        raise

    finally:
        save_json(report_path, report)

        # Delete only entries this run created, not other caches.
        try:
            for key in created_keys:
                cache.client.delete(key)
        finally:
            cache.client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "run"])
    parser.add_argument("--baseline-reviewed", action="store_true")
    args = parser.parse_args()

    REPORTS.mkdir(exist_ok=True)
    dataset, digest = load_dataset()

    if args.mode == "prepare":
        prepare_baseline(dataset, digest)
    else:
        if not args.baseline_reviewed:
            parser.error(
                "Review the prepared baseline answers, then supply "
                "--baseline-reviewed"
            )
        run_sweep(dataset, digest)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
    )
    main()