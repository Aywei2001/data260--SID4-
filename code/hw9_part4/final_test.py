import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from validate_lessons import run_condition


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    paths = {
        "test_data": ROOT / "test_data.json",
        "reference_data": ROOT / "reference_data.json",
        "lessons": ROOT / "lessons.json",
        "agent_code": ROOT / "two_agent_system.py",
        "evaluation_code": ROOT / "validate_lessons.py",
        "lesson_code": ROOT / "lesson_store.py",
        "model_adapter": ROOT.parent.parent / "src" / "model_client.py",
    }

    frozen_hashes = {
        name: digest(path)
        for name, path in paths.items()
    }

    cases = load_json(paths["test_data"])
    reference = load_json(paths["reference_data"])
    lessons = load_json(paths["lessons"])

    if lessons != []:
        raise ValueError(
            "Expected the selected configuration: zero active lessons."
        )

    if not cases:
        raise ValueError("Test dataset is empty")

    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Test case IDs must be unique")

    for case in cases:
        if set(case) != {"id", "question"}:
            raise ValueError(
                "Each test case must contain only id and question"
            )
        if not isinstance(case["question"], str):
            raise ValueError("Questions must be strings")

    REPORTS.mkdir(exist_ok=True)

    #protect against accidentally treating a rerun as a new final test.
    previous = list(REPORTS.glob("final_test_*.json"))
    if previous:
        raise RuntimeError(
            "A final-test report already exists. Preserve it and inspect "
            "it before deciding whether an operational retry is justified."
        )

    report_path = REPORTS / f"final_test_{uuid4().hex}.json"

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "configuration_hashes": frozen_hashes,
        "reference_version": reference["dataset_version"],
        "selected_lesson_ids": [],
        "lesson_learning_enabled": False,
        "controlled_failure": False,
        "maximum_answer_attempts": 2,
        "results": [],
        "complete": False,
    }

    def save():
        report_path.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

    save()

    try:
        for case in cases:
            print(f"\n=== {case['id']} ===", flush=True)

            # run_condition does not learn lessons or update lesson files.
            result = run_condition(case, reference, lessons)

            item = {
                **case,
                **result,
            }
            report["results"].append(item)
            save()

            print(json.dumps(item, indent=2), flush=True)

        unchanged = all(
            digest(path) == frozen_hashes[name]
            for name, path in paths.items()
        )

        if not unchanged:
            raise RuntimeError(
                "Configuration or input files changed during final testing"
            )

        total = len(cases)
        initial_passes = sum(
            item["initial_pass"]
            for item in report["results"]
        )
        final_passes = sum(
            item["final_pass"]
            for item in report["results"]
        )

        report["summary"] = {
            "cases": total,
            "initial_passes": initial_passes,
            "initial_pass_rate_percent": 100 * initial_passes / total,
            "final_passes": final_passes,
            "final_pass_rate_percent": 100 * final_passes / total,
            "cases_requiring_revision": sum(
                len(item["attempts"]) == 2
                for item in report["results"]
            ),
            "configuration_unchanged": unchanged,
            "manual_factual_review_required": True,
        }

        report["complete"] = True
        print("\nFinal-test summary:")
        print(json.dumps(report["summary"], indent=2))

    except Exception as exc:
        report["error"] = str(exc)
        raise

    finally:
        save()
        print("Saved report:", report_path)


if __name__ == "__main__":
    main()