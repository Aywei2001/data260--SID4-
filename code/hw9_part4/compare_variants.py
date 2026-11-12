import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from two_agent_system import (
    ANSWERING_PROMPT,
    ModelAdapter,
    evaluate_answer,
    invoke_text,
    retrieve_facts,
)
from validate_lessons import run_condition


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_baseline(case, reference):
    facts = retrieve_facts(case["question"], reference)

    answer, answer_usage = invoke_text(
        ModelAdapter(),
        ANSWERING_PROMPT,
        {
            "question": case["question"],
            "reference_facts": facts,
            "reusable_lessons": [],
        },
    )

    #scoring only, no feedback or revision is sent to the answerer
    evaluation, raw, evaluator_usage = evaluate_answer(
        ModelAdapter(),
        case["question"],
        answer,
        facts,
    )

    return {
        "reference_facts": facts,
        "attempts": [{
            "attempt": 1,
            "answer": answer,
            "evaluation": evaluation,
            "raw_evaluator_response": raw,
            "loaded_lesson_ids": [],
            "answering_usage": answer_usage,
            "evaluator_usage": evaluator_usage,
        }],
        "initial_pass": evaluation["result"] == "PASS",
        "final_pass": evaluation["result"] == "PASS",
    }


def main():
    paths = {
        "reference": ROOT / "reference_data.json",
        "training": ROOT / "training_data.json",
        "validation": ROOT / "validation_data.json",
        "test": ROOT / "test_data.json",
        "selected_lessons": ROOT / "lessons.json",
        "memory_lessons": (
            REPORTS / "lessons_rejected_candidate.json"
        ),
        "agents": ROOT / "two_agent_system.py",
        "validation_runner": ROOT / "validate_lessons.py",
        "lesson_store": ROOT / "lesson_store.py",
        "adapter": ROOT.parent.parent / "src" / "model_client.py",
    }

    hashes = {
        name: digest(path)
        for name, path in paths.items()
    }

    reference = read_json(paths["reference"])
    cases = read_json(paths["test"])
    memory_lessons = read_json(paths["memory_lessons"])
    selected_lessons = read_json(paths["selected_lessons"])

    if not cases:
        raise ValueError("Test dataset is empty")

    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Test IDs must be unique")

    if not any(
        lesson["lesson_id"] == "lesson_quantity_001"
        for lesson in memory_lessons
    ):
        raise ValueError("Archived training lesson was not found")

    if selected_lessons != []:
        raise ValueError(
            "Expected the frozen selected configuration: no active lessons"
        )

    variants = [
        ("Baseline", None),
        ("Evaluator Repair", []),
        ("Lesson Memory", memory_lessons),
        ("Validated Improvement", selected_lessons),
    ]

    REPORTS.mkdir(exist_ok=True)
    run_id = uuid4().hex
    json_path = REPORTS / f"four_variants_{run_id}.json"
    csv_path = REPORTS / f"four_variants_{run_id}.csv"

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "configuration_hashes": hashes,
        "memory_lesson_snapshot": memory_lessons,
        "selected_lesson_snapshot": selected_lessons,
        "test_learning_enabled": False,
        "fault_injection": False,
        "scoring": "Final model-evaluator PASS versus REVISE",
        "latency_definition": (
            "Wall-clock time for each case, including answer generation "
            "and all evaluator calls, including final scoring. "
            "Excludes report file writes."
        ),
        "manual_review_required": True,
        "results": [],
        "summary": [],
        "complete": False,
    }

    def save():
        json_path.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

    save()

    try:
        for variant_name, lessons in variants:
            variant_results = []
            print(f"\n===== {variant_name} =====", flush=True)

            for case in cases:
                print(f"Running {case['id']}...", flush=True)
                started = perf_counter()

                if variant_name == "Baseline":
                    result = run_baseline(case, reference)
                else:
                    result = run_condition(
                        case,
                        reference,
                        lessons,
                    )

                latency_ms = (perf_counter() - started) * 1000

                item = {
                    "variant": variant_name,
                    **case,
                    **result,
                    "answer_attempts": len(result["attempts"]),
                    "latency_ms": latency_ms,
                    "final_answer": result["attempts"][-1]["answer"],
                }

                variant_results.append(item)
                report["results"].append(item)
                save()

                print(
                    f"Final PASS={result['final_pass']} | "
                    f"attempts={item['answer_attempts']} | "
                    f"latency_ms={latency_ms:.2f}",
                    flush=True,
                )

            total = len(variant_results)
            correct = sum(
                item["final_pass"] for item in variant_results
            )

            report["summary"].append({
                "variant": variant_name,
                "correct_answers": correct,
                "incorrect_answers": total - correct,
                "average_attempts": sum(
                    item["answer_attempts"]
                    for item in variant_results
                ) / total,
                "average_latency_ms": sum(
                    item["latency_ms"]
                    for item in variant_results
                ) / total,
            })
            save()

        unchanged = all(
            digest(path) == hashes[name]
            for name, path in paths.items()
        )
        if not unchanged:
            raise RuntimeError(
                "An input or configuration file changed during comparison"
            )

        report["configuration_unchanged"] = True
        report["complete"] = True

        with csv_path.open(
            "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(report["summary"][0]),
            )
            writer.writeheader()
            writer.writerows(report["summary"])

        print("\nCompleted results table:")
        print(json.dumps(report["summary"], indent=2))
        print("Summary CSV:", csv_path)

    except Exception as exc:
        report["error"] = str(exc)
        raise

    finally:
        save()
        print("Detailed report:", json_path)


if __name__ == "__main__":
    main()