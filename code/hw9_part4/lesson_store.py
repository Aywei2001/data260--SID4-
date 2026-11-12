import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parent
LESSONS_PATH = ROOT / "lessons.json"
FAILURES_PATH = ROOT / "lesson_failures.json"

PATTERN_ID = "wrong_affected_quantity"


def read_list(path):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def write_list(path, items):
    path.write_text(
        json.dumps(items, indent=2),
        encoding="utf-8",
    )


def quantity_question(question):
    return bool(re.search(
        r"\b(units|quantity|unit count)\b",
        question,
        flags=re.IGNORECASE,
    ))


def observe_failure(
    question,
    answer,
    facts,
    evaluation,
    controlled=False,
):
    #initial implementation recognizes one specific failure pattern.
    if evaluation["result"] != "REVISE":
        return None

    if not quantity_question(question) or len(facts) != 1:
        return None

    correct_quantity = facts[0].get("affected_quantity")
    stated_quantity = re.search(
        r"\b(\d+)\s+units\b",
        answer,
        flags=re.IGNORECASE,
    )

    if correct_quantity is None or stated_quantity is None:
        return None

    if int(stated_quantity.group(1)) == correct_quantity:
        return None

    failures = read_list(FAILURES_PATH)
    failures.append({
        "event_id": uuid4().hex,
        "pattern_id": PATTERN_ID,
        "question": question,
        "answer": answer,
        "reference_quantity": correct_quantity,
        "evaluator_explanation": evaluation["explanation"],
        "evaluator_feedback": evaluation["feedback"],
        "controlled_failure": controlled,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    write_list(FAILURES_PATH, failures)

    matching = [
        item for item in failures
        if item["pattern_id"] == PATTERN_ID
    ]

    # Require two observed failures before creating a reusable lesson.
    if len(matching) < 2:
        print(
            "Failure pattern observed once; "
            "waiting for a repeated occurrence.",
            flush=True,
        )
        return None

    lessons = read_list(LESSONS_PATH)

    existing = next(
        (
            item for item in lessons
            if item["lesson_id"] == "lesson_quantity_001"
        ),
        None,
    )

    if existing is not None:
        return existing["lesson_id"]

    lesson = {
        "lesson_id": "lesson_quantity_001",
        "failure_pattern": (
            "An answer states an affected quantity that does not "
            "match the requested notice's reference record."
        ),
        "correction": (
            "Match the requested notice ID exactly. Read its "
            "affected_quantity directly from the supplied reference "
            "record before answering. Do not copy a quantity from "
            "another notice or a previous answer."
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "use_count": 0,
        "applies_to": "affected_quantity",
        "source_failure_ids": [
            item["event_id"] for item in matching
        ],
        "development_evidence": (
            "controlled failures"
            if all(item["controlled_failure"] for item in matching)
            else "see individual failure records"
        ),
    }

    lessons.append(lesson)
    write_list(LESSONS_PATH, lessons)

    print("Created lesson:", lesson["lesson_id"], flush=True)
    return lesson["lesson_id"]


def relevant_lessons(question):
    lessons = read_list(LESSONS_PATH)

    if not quantity_question(question):
        return []

    return [
        lesson for lesson in lessons
        if lesson.get("applies_to") == "affected_quantity"
    ]


def record_lesson_use(lesson_ids):
    if not lesson_ids:
        return

    lessons = read_list(LESSONS_PATH)

    for lesson in lessons:
        if lesson["lesson_id"] in lesson_ids:
            lesson["use_count"] += 1

    write_list(LESSONS_PATH, lessons)