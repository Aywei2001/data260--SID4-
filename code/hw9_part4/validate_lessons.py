import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from two_agent_system import (
    ANSWERING_PROMPT,
    ModelAdapter,
    evaluate_answer,
    invoke_text,
    retrieve_facts,
)
from lesson_store import quantity_question


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_condition(case, reference, lessons):
    facts = retrieve_facts(case["question"], reference)

    applicable = [
        lesson for lesson in lessons
        if quantity_question(case["question"])
        and lesson.get("applies_to") == "affected_quantity"
    ]

    answering_agent = ModelAdapter()
    evaluator_agent = ModelAdapter()

    attempts = []
    previous_answer = None
    feedback = None

    for number in range(1, 3):
        payload = {
            "question": case["question"],
            "reference_facts": facts,
            "reusable_lessons": [
                {
                    "lesson_id": lesson["lesson_id"],
                    "failure_pattern": lesson["failure_pattern"],
                    "correction": lesson["correction"],
                }
                for lesson in applicable
            ],
        }

        if previous_answer is not None:
            payload["previous_answer"] = previous_answer
            payload["evaluator_feedback"] = feedback

        answer, answer_usage = invoke_text(
            answering_agent,
            ANSWERING_PROMPT,
            payload,
        )

        evaluation, raw, evaluator_usage = evaluate_answer(
            evaluator_agent,
            case["question"],
            answer,
            facts,
        )

        attempts.append({
            "attempt": number,
            "answer": answer,
            "evaluation": evaluation,
            "raw_evaluator_response": raw,
            "loaded_lesson_ids": [
                lesson["lesson_id"] for lesson in applicable
            ],
            "answering_usage": answer_usage,
            "evaluator_usage": evaluator_usage,
        })

        if evaluation["result"] == "PASS":
            break

        previous_answer = answer
        feedback = evaluation["feedback"]

    return {
        "reference_facts": facts,
        "attempts": attempts,
        "initial_pass": (
            attempts[0]["evaluation"]["result"] == "PASS"
        ),
        "final_pass": (
            attempts[-1]["evaluation"]["result"] == "PASS"
        ),
    }


def main():
    reference_path = ROOT / "reference_data.json"
    validation_path = ROOT / "validation_data.json"
    lessons_path = ROOT / "lessons.json"

    reference = read_json(reference_path)
    cases = read_json(validation_path)
    lessons = read_json(lessons_path)

    #compare one candidate against no lessons.
    candidates = [
        lesson for lesson in lessons
        if lesson["lesson_id"] == "lesson_quantity_001"
    ]
    if len(candidates) != 1:
        raise ValueError("Expected one lesson_quantity_001 candidate")

    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Validation cases must have unique IDs")

    REPORTS.mkdir(exist_ok=True)
    output = REPORTS / f"lesson_validation_{uuid4().hex}.json"

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "validation_sha256": file_hash(validation_path),
        "reference_sha256": file_hash(reference_path),
        "lessons_sha256": file_hash(lessons_path),
        "candidate_lessons": candidates,
        "maximum_answer_attempts": 2,
        "fault_injection": False,
        "lesson_learning_enabled": False,
        "results": [],
        "complete": False,
    }

    def save():
        output.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

    try:
        for index, case in enumerate(cases):
            print(f"\n=== {case['id']} ===", flush=True)

            #alternate order to reduce a consistent order advantage 
            order = (
                ["before", "after"]
                if index % 2 == 0
                else ["after", "before"]
            )
            conditions = {}

            for condition in order:
                conditions[condition] = run_condition(
                    case,
                    reference,
                    [] if condition == "before" else candidates,
                )

            before = conditions["before"]
            after = conditions["after"]

            initial_regression = (
                before["initial_pass"] and not after["initial_pass"]
            )
            final_regression = (
                before["final_pass"] and not after["final_pass"]
            )

            item = {
                **case,
                "execution_order": order,
                "before": before,
                "after": after,
                "initial_regression": initial_regression,
                "final_regression": final_regression,
            }

            report["results"].append(item)
            save()

            print(
                "Initial PASS: "
                f"{before['initial_pass']} -> {after['initial_pass']}"
            )
            print(
                "Final PASS: "
                f"{before['final_pass']} -> {after['final_pass']}"
            )

        results = report["results"]
        initial_regressions = sum(
            item["initial_regression"] for item in results
        )
        final_regressions = sum(
            item["final_regression"] for item in results
        )

        report["summary"] = {
            "cases": len(results),
            "before_initial_passes": sum(
                item["before"]["initial_pass"] for item in results
            ),
            "after_initial_passes": sum(
                item["after"]["initial_pass"] for item in results
            ),
            "before_final_passes": sum(
                item["before"]["final_pass"] for item in results
            ),
            "after_final_passes": sum(
                item["after"]["final_pass"] for item in results
            ),
            "initial_regressions": initial_regressions,
            "final_regressions": final_regressions,
            "candidate_passes_automated_nonregression_check": (
                initial_regressions == 0
                and final_regressions == 0
            ),
            "manual_answer_review_required": True,
        }

        report["complete"] = True
        print("\nSummary:")
        print(json.dumps(report["summary"], indent=2))

    except Exception as exc:
        report["error"] = str(exc)
        raise

    finally:
        save()
        print("Saved report:", output)


if __name__ == "__main__":
    main()