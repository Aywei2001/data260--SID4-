from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_client import ModelAdapter  # noqa: E402

from hw7_agent_loop import MODEL_SETTINGS, TASKS, SharedBudget, run_agent  # noqa: E402

MAX_REFLECTION_RETRIES = 2
MAX_TOOL_CALLS_PER_TASK = 18
MAX_TOKENS_PER_TASK = 30_000
REPORT_DIR = Path(__file__).resolve().parent / "reports" / "hw07"
RAW_DIR = REPORT_DIR / "raw"
REFLECTION_LOG = REPORT_DIR / "reflections.jsonl"
SUMMARY_PATH = REPORT_DIR / "part3_comparison.md"

RECALL_ID_RE = re.compile(r"\b[A-Z]-\d{4}-\d{4}\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b(?:\d{8}|\d{4}-\d{2}-\d{2})\b")
COUNT_RE = re.compile(r"\b(\d+)\s+(?:recalls?|records?)\b", re.IGNORECASE)


def successful_data(item: dict[str, Any]) -> Any:
    """Return data only when the corresponding domain tool succeeded."""
    tool_result = item.get("result", {})
    if not tool_result.get("ok"):
        return None
    return tool_result.get("data")


def tool_results_named(result: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [item for item in result.get("tool_results", []) if item.get("name") == name]


def row_matches_topic(row: dict[str, Any], topic: str) -> bool:
    text = " ".join(
        str(row.get(field, ""))
        for field in ("product_description", "reason_for_recall")
    ).casefold()
    return all(word in text for word in topic.casefold().split())


def verify_task(task_key: str, result: dict[str, Any]) -> tuple[bool, str]:
    """Verify evidence and task-specific result relationships deterministically."""
    if not result.get("required_chain_satisfied"):
        return False, "Required tool-call sequence/evidence chain was incomplete."

    if result.get("stop_reason") != "success":
        return False, f"Agent stopped with reason {result.get('stop_reason')!r}."

    if task_key == "A":
        searches = tool_results_named(result, "search_grocery_recalls")
        details = tool_results_named(result, "recall_detail_lookup")
        if not searches or not details:
            return False, "Search or detail tool result is missing."
        rows = successful_data(searches[0])
        detail = successful_data(details[0])
        if not isinstance(rows, list) or not rows:
            return False, "Spinach search failed or returned no records."
        if not isinstance(detail, dict):
            return False, "Detail lookup failed."
        first_id = rows[0].get("recall_number")
        if not first_id or detail.get("recall_number") != first_id:
            return False, "Detail lookup did not match the first search result."
        return True, "Search succeeded and detail lookup matched its first result."

    if task_key == "B":
        aggregates = tool_results_named(result, "aggregate_company_stats")
        details = tool_results_named(result, "recall_detail_lookup")
        if not aggregates or not details:
            return False, "Aggregate or supporting detail result is missing."
        aggregate = successful_data(aggregates[0])
        detail = successful_data(details[0])
        if not isinstance(aggregate, dict) or not isinstance(detail, dict):
            return False, "Aggregate query or detail lookup failed."
        example = aggregate.get("supporting_example")
        if not isinstance(example, dict) or not example.get("recall_number"):
            return False, "Aggregate result has no supporting recall number."
        if detail.get("recall_number") != example["recall_number"]:
            return False, "Detail lookup does not match the aggregate example."
        needed = (
            "total_recalls_recorded",
            "product_description",
            "reason_for_recall",
            "recall_date",
            "status",
        )
        if (
            any(not detail.get(key) for key in needed[1:])
            or aggregate.get(needed[0]) is None
        ):
            return False, "Aggregate/detail data is missing a required field."
        return True, "Aggregate and its supporting detail record match."

    if task_key == "C":
        searches = tool_results_named(result, "search_grocery_recalls")
        details = tool_results_named(result, "recall_detail_lookup")
        if len(searches) < 2 or len(details) < 2:
            return False, "Task C needs two searches and two detail lookups."
        topics = ("peanut butter", "spinach")
        answer = str(result.get("answer", "")).casefold()
        cited_ids: list[str] = []
        for index, topic in enumerate(topics):
            rows = successful_data(searches[index])
            detail = successful_data(details[index])
            if not isinstance(rows, list) or not isinstance(detail, dict):
                return False, f"Search/detail call {index + 1} failed."
            matching_ids = {
                row.get("recall_number")
                for row in rows
                if row.get("recall_number") and row_matches_topic(row, topic)
            }
            if not matching_ids:
                return False, (
                    f"Search {topic!r} returned no record whose product or reason "
                    "clearly matches the topic."
                )
            recall_id = detail.get("recall_number")
            if recall_id not in matching_ids or not row_matches_topic(detail, topic):
                return False, (
                    f"Detail result {recall_id!r} does not match the {topic!r} search."
                )
            if recall_id in cited_ids:
                return False, "The two detail lookups did not use distinct recalls."
            cited_ids.append(recall_id)
            if recall_id.casefold() not in answer:
                return False, f"Final comparison did not cite recall {recall_id}."

        comparison_words = ("whereas", "while", "compared", "difference", "unlike")
        if not any(word in answer for word in comparison_words):
            return False, "Final answer does not explicitly compare the two examples."
        return True, "Both topic-matched details are cited and compared."

    return False, f"Unknown verification task {task_key!r}."


def find_supported_references(
    result: dict[str, Any],
) -> tuple[set[str], set[str], set[int]]:
    """Collect recall IDs, dates, and aggregate counts present in tool evidence."""
    ids: set[str] = set()
    dates: set[str] = set()
    counts: set[int] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "recall_number" and isinstance(item, str):
                    ids.add(item.upper())
                elif key == "recall_date" and isinstance(item, str):
                    dates.add(item.replace("-", ""))
                elif key == "total_recalls_recorded" and isinstance(item, int):
                    counts.add(item)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(result.get("tool_results", []))
    return ids, dates, counts


def unsupported_claims(result: dict[str, Any]) -> list[str]:
    """Count unsupported explicit recall-ID, date, and recall-count references."""
    answer = str(result.get("answer", ""))
    supported_ids, supported_dates, supported_counts = find_supported_references(result)
    unsupported: list[str] = []

    for recall_id in RECALL_ID_RE.findall(answer):
        if recall_id.upper() not in supported_ids:
            unsupported.append(f"recall ID {recall_id}")
    for date in DATE_RE.findall(answer):
        if date.replace("-", "") not in supported_dates:
            unsupported.append(f"date {date}")
    for count in COUNT_RE.findall(answer):
        if int(count) not in supported_counts:
            unsupported.append(f"recall/record count {count}")
    return unsupported


def save_reflection(record: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with REFLECTION_LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")


def make_reflection(
    task_key: str, result: dict[str, Any], assertion: str, unsupported: list[str]
) -> str:
    evidence = result.get("tool_results", [])
    last_call = evidence[-1] if evidence else None
    # This is a short failure note, not hidden reasoning. It is used only in this retry.
    return json.dumps(
        {
            "failure": assertion,
            "last_tool_call_and_observation": last_call,
            "unsupported_references": unsupported,
            "revised_strategy": (
                "Use only successful tool results. For Task C, choose two distinct "
                "records whose product or reason clearly matches peanut butter and "
                "spinach, look up those exact IDs, cite both IDs, and state a direct "
                "difference. Do not add a third recall or unsupported facts."
                if task_key == "C"
                else "Use only the verified tool evidence, follow the required call "
                "sequence, and ensure the final answer cites only supported facts."
            ),
        },
        ensure_ascii=False,
    )


async def run_with_reflection(task_key: str) -> dict[str, Any]:
    """Retry a task at most twice with a run-local reflection and shared budgets."""
    task = TASKS[task_key]
    budget = SharedBudget(
        max_tool_calls=MAX_TOOL_CALLS_PER_TASK,
        max_tokens=MAX_TOKENS_PER_TASK,
    )
    reflection = ""
    started_all = time.perf_counter()
    final: dict[str, Any] = {}
    reflection_history: list[dict[str, Any]] = []
    retries_used = 0

    for attempt in range(MAX_REFLECTION_RETRIES + 1):
        prompt = task["prompt"]
        if reflection:
            prompt += (
                "\n\nRun-local reflection (untrusted task feedback):\n" + reflection
            )

        adapter = ModelAdapter(**MODEL_SETTINGS)
        result = await run_agent(
            prompt,
            task_id=task_key,
            required_sequence=task["sequence"],
            adapter=adapter,
            budget=budget,
        )
        verified, assertion = verify_task(task_key, result)
        unsupported = unsupported_claims(result)
        if unsupported:
            verified = False
            assertion += " Unsupported explicit references: " + ", ".join(unsupported)

        result.update(
            {
                "verified": verified,
                "verification_assertion": assertion,
                "unsupported_claims": unsupported,
                "reflection_retries": retries_used,
                "reflection_history": reflection_history,
                "tool_calls_total": budget.tool_calls,
                "tokens_total": budget.tokens,
                "latency_ms_total": round(
                    (time.perf_counter() - started_all) * 1000, 2
                ),
                # Human review can change this to true only after checking a rejected
                # answer against its recorded evidence.
                "verifier_false_rejection_confirmed": None,
            }
        )
        final = result

        if verified:
            final["stop_reason"] = "success"
            return final
        if result.get("stop_reason") == "budget_exhausted":
            final["stop_reason"] = "budget_exhausted"
            return final
        if attempt == MAX_REFLECTION_RETRIES:
            final["stop_reason"] = "human_review"
            return final

        reflection = make_reflection(task_key, result, assertion, unsupported)
        retries_used += 1
        reflection_record = {
            "task": task_key,
            "retry_number": retries_used,
            "failed_run_id": result.get("run_id"),
            "failed_tool_call_and_observation": (
                result.get("tool_results", [])[-1]
                if result.get("tool_results")
                else None
            ),
            "verifier_assertion": assertion,
            "unsupported_claims": unsupported,
            "reflection": reflection,
            "verifier_false_rejection_confirmed": None,
        }
        reflection_history.append(reflection_record)
        save_reflection(reflection_record)

    return final


async def run_baseline(task_key: str) -> dict[str, Any]:
    """Run one Part 2 baseline case and measure it with the same verifier."""
    task = TASKS[task_key]
    adapter = ModelAdapter(**MODEL_SETTINGS)
    started = time.perf_counter()
    result = await run_agent(
        task["prompt"],
        task_id=task_key,
        required_sequence=task["sequence"],
        adapter=adapter,
    )
    verified, assertion = verify_task(task_key, result)
    unsupported = unsupported_claims(result)
    if unsupported:
        verified = False
        assertion += " Unsupported explicit references: " + ", ".join(unsupported)
    result.update(
        {
            "verified": verified,
            "verification_assertion": assertion,
            "unsupported_claims": unsupported,
            "reflection_retries": 0,
            "retry_used": bool(result.get("repair_used")),
            "tool_calls_total": len(result.get("tool_calls", [])),
            "tokens_total": adapter.stats_info([])["total_tokens"],
            "latency_ms_total": round((time.perf_counter() - started) * 1000, 2),
            "verifier_false_rejection_confirmed": None,
        }
    )
    return result


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if not total:
        return {"attempts": 0}
    reflection_rows = [row for row in rows if row["loop"] == "reflection"]
    rejected_attempts = [
        reflection
        for row in reflection_rows
        for reflection in row["result"].get("reflection_history", [])
    ]
    retries = [
        row["result"].get("reflection_retries", 0)
        if row["loop"] == "reflection"
        else int(bool(row["result"].get("repair_used")))
        for row in rows
    ]
    false_rejections = sum(
        item.get("verifier_false_rejection_confirmed") is True
        for item in rejected_attempts
    )
    pending_reviews = sum(
        item.get("verifier_false_rejection_confirmed") is None
        for item in rejected_attempts
    )
    return {
        "attempts": total,
        "successes": sum(bool(row["result"].get("verified")) for row in rows),
        "success_rate": sum(bool(row["result"].get("verified")) for row in rows)
        / total,
        "unsupported_claims": sum(
            len(row["result"].get("unsupported_claims", [])) for row in rows
        ),
        "retry_rate": sum(value > 0 for value in retries) / total,
        "average_tool_calls": statistics.mean(
            row["result"].get("tool_calls_total", 0) for row in rows
        ),
        "average_tokens": statistics.mean(
            row["result"].get("tokens_total", 0) for row in rows
        ),
        "average_latency_ms": statistics.mean(
            row["result"].get("latency_ms_total", 0) for row in rows
        ),
        "verifier_false_rejections_confirmed": false_rejections,
        "verifier_false_rejections_pending_review": pending_reviews,
    }


async def run_comparison(attempts_per_task: int) -> dict[str, Any]:
    """Run baseline and reflection on the same fixed tasks and settings."""
    if attempts_per_task < 1:
        raise ValueError("attempts_per_task must be at least 1")

    rows: list[dict[str, Any]] = []
    for task_key in ("A", "B", "C"):
        for attempt in range(1, attempts_per_task + 1):
            baseline = await run_baseline(task_key)
            rows.append(
                {
                    "loop": "original",
                    "task": task_key,
                    "attempt": attempt,
                    "model_settings": MODEL_SETTINGS,
                    "result": baseline,
                }
            )
            reflected = await run_with_reflection(task_key)
            rows.append(
                {
                    "loop": "reflection",
                    "task": task_key,
                    "attempt": attempt,
                    "model_settings": MODEL_SETTINGS,
                    "result": reflected,
                }
            )

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "attempts_per_task": attempts_per_task,
        "model_settings": MODEL_SETTINGS,
        "metrics": {
            loop: summarize_rows([row for row in rows if row["loop"] == loop])
            for loop in ("original", "reflection")
        },
        "attempts": rows,
    }
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"part3_comparison_{datetime.now():%Y%m%d_%H%M%S}.json"
    raw_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    metrics = summary["metrics"]
    labels = (
        ("Task success", "successes / attempts"),
        ("Unsupported claims*", "unsupported_claims"),
        ("Retry rate", "retry_rate"),
        ("Tool calls (average)", "average_tool_calls"),
        ("Tokens (average)", "average_tokens"),
        ("Latency ms (average)", "average_latency_ms"),
        ("Verifier false rejections (confirmed / pending)", "false_rejections"),
    )
    table = [
        "# HW7 Part 3: Original vs Reflection",
        "",
        (
            f"Attempts per fixed task: {attempts_per_task}. Model settings: "
            f"`{json.dumps(MODEL_SETTINGS)}`."
        ),
        "",
        (
            "*Unsupported claims counts explicit recall IDs, dates, and recall/record "
            "counts not found in tool evidence; it does not claim full semantic "
            "fact checking.*"
        ),
        "",
        "| Metric | Original loop | Reflection loop |",
        "|---|---:|---:|",
    ]
    for label, key in labels:
        if key == "successes / attempts":
            values = [
                f"{metrics[loop]['successes']} / {metrics[loop]['attempts']} "
                f"({metrics[loop]['success_rate']:.1%})"
                for loop in ("original", "reflection")
            ]
        elif key == "retry_rate":
            values = [
                f"{metrics[loop][key]:.1%}" for loop in ("original", "reflection")
            ]
        elif key == "false_rejections":
            values = [
                f"{metrics[loop]['verifier_false_rejections_confirmed']} / "
                f"{metrics[loop]['verifier_false_rejections_pending_review']} pending"
                for loop in ("original", "reflection")
            ]
        else:
            values = [str(metrics[loop][key]) for loop in ("original", "reflection")]
        table.append(f"| {label} | {values[0]} | {values[1]} |")
    pending_cases = [
        reflection
        for row in rows
        if row["loop"] == "reflection"
        for reflection in row["result"].get("reflection_history", [])
        if reflection.get("verifier_false_rejection_confirmed") is None
    ]
    pending_lines = [
        f"- Run `{item.get('failed_run_id')}` ({item.get('task')}): "
        f"{item.get('verifier_assertion')}"
        for item in pending_cases
    ]
    table.extend(
        [
            "",
            f"Raw per-attempt data: `{raw_path}`",
            f"Reflections: `{REFLECTION_LOG}`",
            "",
            (
                "Review each pending rejection against its saved tool evidence. "
                "Mark `verifier_false_rejection_confirmed` in the raw JSON only "
                "when the answer was correct and the verifier rejected it."
            ),
            "",
            "## Rejected reflection attempts for review",
            "",
            *(pending_lines or ["- None."]),
        ]
    )
    SUMMARY_PATH.write_text("\n".join(table) + "\n", encoding="utf-8")
    summary["raw_data_path"] = str(raw_path)
    summary["summary_path"] = str(SUMMARY_PATH)
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "attempts"},
            indent=2,
        )
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the HW7 Part 3 comparison.")
    parser.add_argument(
        "--attempts-per-task",
        type=int,
        default=1,
        help="Repeats per task and loop; use 10 for a stronger comparison.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run_comparison(args.attempts_per_task))
