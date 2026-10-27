from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_client import ModelAdapter  # noqa: E402

from mcp_meals.mcp_GroceryRecall_rel import (  # noqa: E402
    aggregate_company_stats,
    recall_detail_lookup,
    search_grocery_recalls,
)

CODE_DIR = Path(__file__).resolve().parent
RAW_DIR = CODE_DIR / "reports" / "hw07" / "raw"
RUN_LOG = CODE_DIR / "RUN_LOG.txt"

MODEL_SETTINGS = {
    "model_name": "llama3.2",
    "base_url": "http://localhost:11434",
    "temperature": 0.0,
}
MAX_TOOL_CALLS = 8
MAX_MODEL_TURNS = 18
MODEL_CONTEXT_TOKENS = 2048


@dataclass
class SharedBudget:
    """Aggregate tool and token limits shared across reflection retries."""

    max_tool_calls: int = 18
    max_tokens: int = 12_000
    tool_calls: int = 0
    tokens: int = 0


TOOL_FUNCTIONS = {
    "search_grocery_recalls": search_grocery_recalls,
    "recall_detail_lookup": recall_detail_lookup,
    "aggregate_company_stats": aggregate_company_stats,
}
REQUIRED_ARGS = {
    "search_grocery_recalls": {"query"},
    "recall_detail_lookup": {"recall_number"},
    "aggregate_company_stats": {"company_name"},
}

SYSTEM_PROMPT = """You answer grocery recall questions using only the supplied tools.
Return exactly one JSON object, with no markdown:
{"type":"tool_call","name":"search_grocery_recalls","arguments":{"query":"..."}}
{"type":"tool_call","name":"recall_detail_lookup","arguments":{"recall_number":"..."}}
{"type":"tool_call","name":"aggregate_company_stats","arguments":{"company_name":"..."}}
When the requested work is complete, return:
{"type":"final","answer":"..."}
Use only those tool names and exact argument keys. Continue after tool results
until every requested search, supporting detail lookup, or comparison is complete.
If a tool reports no matching record, explain that without inventing details.
Final answers must be concise and use only facts present in tool results.
Do not invent reports, advice, dates, or current status.
In JSON strings, write apostrophes directly, without backslashes."""


TASKS = {
    "A": {
        "prompt": (
            "Search grocery recalls for spinach. Then look up the first result "
            "in detail and summarize its recall reason and date."
        ),
        "sequence": ["search_grocery_recalls", "recall_detail_lookup"],
    },
    "B": {
        "prompt": (
            "Get aggregate recall statistics for Nestle. The aggregate result "
            "includes one supporting example. Look up that example using its "
            "recall_number. Give a concise answer with the aggregate count, example "
            "product, recall number, stated reason, report date, and status. Use only "
            "the aggregate and detail results; do not add assumptions."
        ),
        "sequence": ["aggregate_company_stats", "recall_detail_lookup"],
    },
    "C": {
        "prompt": (
            "Compare one grocery recall involving peanut butter with one involving "
            "spinach. Search each term separately, choose a result whose product "
            "description or stated reason clearly matches that term, then look up "
            "one matching recall from each search in detail. Cite both recall IDs, "
            "products, and reasons, and explain one difference."
        ),
        "sequence": [
            "search_grocery_recalls",
            "search_grocery_recalls",
            "recall_detail_lookup",
            "recall_detail_lookup",
        ],
    },
    "error": {
        "prompt": (
            "Look up recall number HW7-NONEXISTENT-999999. If it does not exist, "
            "say that no record was found. Do not guess its details."
        ),
        "sequence": [],
    },
}


def log_event(event: dict[str, Any]) -> None:
    """Write structured events to the terminal and the complete run log."""
    line = json.dumps(
        {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **event},
        ensure_ascii=False,
    )
    print(line, flush=True)
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as log_file:
        log_file.write(line + "\n")


def parse_action(raw_text: str) -> dict[str, Any]:
    """Parse a model response and validate its action and tool arguments."""
    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Response did not contain a JSON object.")
        candidate = raw_text[start : end + 1].replace(chr(92) + chr(39), chr(39))
        action = json.loads(candidate)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Malformed JSON response: {exc}") from exc

    if not isinstance(action, dict):
        raise ValueError("Response must be a JSON object.")

    if action.get("type") == "final":
        answer = action.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("A final action needs a non-empty string answer.")
        return action

    if action.get("type") != "tool_call":
        raise ValueError("JSON field 'type' must be 'tool_call' or 'final'.")

    name = action.get("name")
    if not isinstance(name, str) or name not in TOOL_FUNCTIONS:
        raise LookupError(f"Unknown tool name: {name!r}.")

    arguments = action.get("arguments")
    if not isinstance(arguments, dict):
        raise TypeError("Tool arguments must be a JSON object.")

    expected = REQUIRED_ARGS[name]
    received = set(arguments)
    if received != expected:
        raise TypeError(
            f"Arguments for {name} must be exactly {sorted(expected)}; "
            f"received {sorted(received)}."
        )
    if any(
        not isinstance(value, str) or not value.strip() for value in arguments.values()
    ):
        raise TypeError("Every tool argument must be a non-empty string.")

    return action


def classify_failure(error: Exception) -> str:
    if isinstance(error, TaskPlanError):
        return "lost_multi_step_chain"
    if isinstance(error, LookupError):
        return "unknown_tool"
    if isinstance(error, TypeError):
        return "malformed_arguments"
    if (
        "malformed json" in str(error).lower()
        or "did not contain a json" in str(error).lower()
    ):
        return "text_when_tool_required"
    return "invalid_model_response"


def chain_satisfied(required: list[str], calls: list[str]) -> bool:
    """Check that required calls occurred in order; extra calls are allowed."""
    position = 0
    for name in calls:
        if position < len(required) and name == required[position]:
            position += 1
    return position == len(required)


class TaskPlanError(ValueError):
    """Raised when a tool call breaks a fixed verification task's evidence chain."""


def validate_task_action(
    task_key: str, action: dict[str, Any], calls: list[str], state: dict[str, Any]
) -> None:
    """Ensure verification tasks use the requested sequence and prior tool evidence."""
    name = action.get("name")
    arguments = action.get("arguments", {})
    sequence = TASKS.get(task_key, {}).get("sequence", [])
    step = len(calls)
    if step < len(sequence) and name != sequence[step]:
        raise TaskPlanError(
            f"Task {task_key} requires {sequence[step]} next; received {name}."
        )

    if task_key == "A" and name == "recall_detail_lookup":
        search_ids = state["search_result_ids"]
        if not search_ids or not search_ids[0]:
            raise TaskPlanError("Search returned no recall ID to look up.")
        expected_id = search_ids[0][0]
        if arguments.get("recall_number") != expected_id:
            raise TaskPlanError(
                f"Look up the first search result, recall_number {expected_id}."
            )

    if task_key == "B" and name == "recall_detail_lookup":
        expected_id = state["aggregate_example_id"]
        if not expected_id:
            raise TaskPlanError(
                "The aggregate result did not include a supporting recall ID."
            )
        if arguments.get("recall_number") != expected_id:
            raise TaskPlanError(
                f"Look up the aggregate result's supporting example: {expected_id}."
            )

    if task_key == "C":
        if name == "search_grocery_recalls":
            query = arguments.get("query", "").casefold()
            search_number = len(state["search_queries"])
            required_term = ("peanut butter", "spinach")[search_number]
            if required_term not in query:
                raise TaskPlanError(
                    f"Search entity {search_number + 1} using "
                    f"the term '{required_term}'."
                )
        elif name == "recall_detail_lookup":
            detail_number = len(state["detail_ids"])
            search_ids = state["search_result_ids"]
            if len(search_ids) <= detail_number or not search_ids[detail_number]:
                raise TaskPlanError(
                    f"Search entity {detail_number + 1} returned no "
                    "recall ID to look up."
                )
            allowed_ids = search_ids[detail_number]
            requested_id = arguments.get("recall_number")
            if requested_id not in allowed_ids:
                raise TaskPlanError(
                    f"Use a recall number returned by entity search "
                    f"{detail_number + 1}: {allowed_ids}."
                )
            required_term = ("peanut butter", "spinach")[detail_number]
            matching_rows = [
                row
                for row in state["search_result_rows"][detail_number]
                if all(
                    word
                    in (
                        str(row.get("product_description", ""))
                        + " "
                        + str(row.get("reason_for_recall", ""))
                    ).casefold()
                    for word in required_term.split()
                )
            ]
            relevant_ids = {row.get("recall_number") for row in matching_rows}
            if requested_id not in relevant_ids:
                raise TaskPlanError(
                    f"Choose a recall result whose product or reason matches "
                    f"'{required_term}'. Matching IDs: {sorted(relevant_ids)}."
                )
            if requested_id in state["detail_ids"]:
                raise TaskPlanError(
                    "Use a different recall result for the other entity."
                )


def record_task_result(
    name: str, arguments: dict[str, Any], result: dict[str, Any], state: dict[str, Any]
) -> None:
    """Keep the returned IDs/products so later calls can be checked against them."""
    data = result.get("data") if result.get("ok") else None
    if name == "aggregate_company_stats" and isinstance(data, dict):
        state["aggregate_summary"] = data
        state["aggregate_products"] = data.get("recent_products_recalled", [])
        example = data.get("supporting_example", {})
        state["aggregate_example_id"] = example.get("recall_number")
    elif name == "search_grocery_recalls":
        rows = data if isinstance(data, list) else []
        state["search_queries"].append(arguments["query"])
        state["search_result_ids"].append(
            [row.get("recall_number") for row in rows if row.get("recall_number")]
        )
        state["search_result_rows"].append(rows)
    elif name == "recall_detail_lookup" and isinstance(data, dict):
        returned_id = data.get("recall_number")
        if returned_id == arguments["recall_number"]:
            state["detail_ids"].append(returned_id)
            state["detail_results"].append(data)


def format_task_b_answer(state: dict[str, Any]) -> str:
    """Build Task B's required summary from the verified tool results."""
    aggregate = state["aggregate_summary"]
    detail = state["detail_results"][0]
    product_name = detail["product_description"].split(".", 1)[0]
    return (
        f"The Nestle aggregate query returned "
        f"{aggregate['total_recalls_recorded']} recall records. Supporting example: "
        f"{product_name} (recall {detail['recall_number']}). "
        f"Stated reason: {detail['reason_for_recall']} "
        f"Report date: {detail['recall_date']}. Status: {detail['status']}."
    )


def task_evidence_satisfied(
    task_key: str, required: list[str], calls: list[str], state: dict[str, Any]
) -> bool:
    """Check both the ordered tool calls and the data passed between them."""
    if not chain_satisfied(required, calls):
        return False
    searches = state["search_result_ids"]
    details = state["detail_ids"]
    if task_key == "A":
        return bool(searches and searches[0] and details == [searches[0][0]])
    if task_key == "B":
        return bool(
            state["aggregate_example_id"] and details == [state["aggregate_example_id"]]
        )
    if task_key == "C":
        queries = state["search_queries"]
        return bool(
            len(queries) == 2
            and "peanut butter" in queries[0].casefold()
            and "spinach" in queries[1].casefold()
            and len(searches) == 2
            and searches[0]
            and searches[1]
            and len(details) == 2
            and details[0] in searches[0]
            and details[1] in searches[1]
            and details[0] != details[1]
            and all(
                any(
                    row.get("recall_number") == details[index]
                    and all(
                        word
                        in (
                            str(row.get("product_description", ""))
                            + " "
                            + str(row.get("reason_for_recall", ""))
                        ).casefold()
                        for word in topic.split()
                    )
                    for row in state["search_result_rows"][index]
                )
                for index, topic in enumerate(("peanut butter", "spinach"))
            )
        )
    return True


async def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate and execute one async domain tool without crashing the loop."""
    if name not in TOOL_FUNCTIONS:
        return {"ok": False, "data": None, "error": f"Unknown tool: {name}"}
    if not isinstance(arguments, dict) or set(arguments) != REQUIRED_ARGS[name]:
        return {
            "ok": False,
            "data": None,
            "error": (
                f"Expected exactly these arguments: {sorted(REQUIRED_ARGS[name])}."
            ),
        }
    if any(
        not isinstance(value, str) or not value.strip() for value in arguments.values()
    ):
        return {
            "ok": False,
            "data": None,
            "error": "Tool arguments must be non-empty strings.",
        }

    try:
        return await TOOL_FUNCTIONS[name](**arguments)
    except Exception as exc:
        return {"ok": False, "data": None, "error": f"{name} failed: {exc}"}


def expected_task_call(
    task_key: str, calls: list[str], state: dict[str, Any]
) -> dict[str, Any] | None:
    """Build the exact next call for the fixed A/B/C/error demonstrations."""
    step = len(calls)
    if task_key == "A":
        if step == 0:
            return {
                "type": "tool_call",
                "name": "search_grocery_recalls",
                "arguments": {"query": "spinach"},
            }
        if step == 1 and state["search_result_ids"] and state["search_result_ids"][0]:
            return {
                "type": "tool_call",
                "name": "recall_detail_lookup",
                "arguments": {"recall_number": state["search_result_ids"][0][0]},
            }
    elif task_key == "B":
        if step == 0:
            return {
                "type": "tool_call",
                "name": "aggregate_company_stats",
                "arguments": {"company_name": "Nestle"},
            }
        if step == 1 and state["aggregate_example_id"]:
            return {
                "type": "tool_call",
                "name": "recall_detail_lookup",
                "arguments": {"recall_number": state["aggregate_example_id"]},
            }
    elif task_key == "C":
        if step == 0:
            query = "peanut butter"
            return {
                "type": "tool_call",
                "name": "search_grocery_recalls",
                "arguments": {"query": query},
            }
        if step == 1:
            return {
                "type": "tool_call",
                "name": "search_grocery_recalls",
                "arguments": {"query": "spinach"},
            }
        if step in (2, 3):
            search_index = step - 2
            if len(state["search_result_rows"]) > search_index:
                required_term = ("peanut butter", "spinach")[search_index]
                for row in state["search_result_rows"][search_index]:
                    text = (
                        str(row.get("product_description", ""))
                        + " "
                        + str(row.get("reason_for_recall", ""))
                    ).casefold()
                    recall_id = row.get("recall_number")
                    if recall_id and all(
                        word in text for word in required_term.split()
                    ):
                        return {
                            "type": "tool_call",
                            "name": "recall_detail_lookup",
                            "arguments": {"recall_number": recall_id},
                        }
    elif task_key == "error" and step == 0:
        return {
            "type": "tool_call",
            "name": "recall_detail_lookup",
            "arguments": {"recall_number": "HW7-NONEXISTENT-999999"},
        }
    return None


def build_repair_prompt(
    task_key: str,
    calls: list[str],
    state: dict[str, Any],
    category: str,
    problem: str,
) -> str:
    """Give a specific repair instruction and prevent premature final answers."""
    next_call = expected_task_call(task_key, calls, state)
    if next_call is None:
        required = TASKS.get(task_key, {}).get("sequence", [])
        if task_evidence_satisfied(task_key, required, calls, state):
            return (
                f"The previous response failed ({category}): {problem} "
                "All required tool calls are complete. Summarize the tool results "
                "already in this conversation. For Task B, include the aggregate "
                "count and supporting example product, recall number, stated reason, "
                "report date, and status. Keep it concise; do not say data is missing. "
                "Return exactly one valid JSON final object and write apostrophes "
                "without backslashes."
            )
        return (
            f"The previous response failed ({category}): {problem} "
            "No further required tool call can be formed. Briefly explain the actual "
            "tool result or missing data in one valid JSON final object. Do not invent "
            "details."
        )
    return (
        f"The previous response failed ({category}): {problem} "
        "The next required action is exactly "
        f"{json.dumps(next_call, ensure_ascii=False)}. "
        "Return that tool_call as one JSON object only. Do not return a final answer "
        "until this required tool has executed."
    )


async def run_agent(
    user_input: str,
    *,
    task_id: str = "custom",
    required_sequence: list[str] | None = None,
    adapter: ModelAdapter | None = None,
    budget: SharedBudget | None = None,
) -> dict[str, Any]:
    # run a tool-using conversation with bounded model turns and repairs
    adapter = adapter or ModelAdapter(**MODEL_SETTINGS)
    required_sequence = required_sequence or []
    run_id = str(uuid.uuid4())
    history: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]
    calls: list[str] = []
    tool_results: list[dict[str, Any]] = []
    task_key = task_id.split("_")[1] if task_id.startswith("reliability_") else task_id
    task_state: dict[str, Any] = {
        "aggregate_summary": None,
        "aggregate_products": [],
        "aggregate_example_id": None,
        "search_queries": [],
        "search_result_ids": [],
        "search_result_rows": [],
        "detail_ids": [],
        "detail_results": [],
    }
    raw_responses: list[str] = []
    failures: list[str] = []
    first_well_formed: bool | None = None
    after_repair_well_formed: bool | None = None
    repairs_used = 0
    repair_pending = False
    model_turns = 0
    answer = "Stopped before a valid final answer was produced."
    stop_reason: str | None = None

    log_event(
        {"event": "run_start", "run_id": run_id, "task": task_id, "input": user_input}
    )

    while model_turns < MAX_MODEL_TURNS and len(calls) < MAX_TOOL_CALLS:
        if budget is not None and budget.tokens >= budget.max_tokens:
            answer = "Stopped because the shared token budget was exhausted."
            stop_reason = "budget_exhausted"
            break
        model_turns += 1
        original_llm = adapter.llm
        if budget is not None:
            remaining_tokens = budget.max_tokens - budget.tokens
            # reserve the whole configured context window for prompt tokens,
            # then cap generated tokens to the remainder so one response cannot
            # consume more than the shared token budget.
            max_output_tokens = remaining_tokens - MODEL_CONTEXT_TOKENS
            if max_output_tokens < 1:
                answer = "Stopped because the shared token budget was exhausted."
                stop_reason = "budget_exhausted"
                break
            adapter.llm = original_llm.model_copy(
                update={"num_predict": max_output_tokens}
            )
        try:
            ai_message, usage = adapter.complete_raw(history)
        finally:
            adapter.llm = original_llm
        if budget is not None:
            budget.tokens += int(usage.get("total_token_count", 0))
        raw_text = str(ai_message.content)
        raw_responses.append(raw_text)
        history.append({"role": "assistant", "content": raw_text})
        log_event(
            {
                "event": "model_response",
                "run_id": run_id,
                "turn": model_turns,
                "content": raw_text,
                "usage": usage,
            }
        )
        if budget is not None and budget.tokens > budget.max_tokens:
            answer = "Stopped because the shared token budget was exhausted."
            stop_reason = "budget_exhausted"
            break

        try:
            action = parse_action(raw_text)
            if action["type"] == "tool_call":
                validate_task_action(task_key, action, calls, task_state)
        except (ValueError, TypeError, LookupError) as exc:
            category = classify_failure(exc)
            failures.append(category)
            if first_well_formed is None:
                first_well_formed = False
            if repair_pending:
                answer = f"Stopped after the repair attempt failed: {exc}"
                stop_reason = "human_review"
                break
            repairs_used += 1
            repair_pending = True
            history.append(
                {
                    "role": "user",
                    "content": build_repair_prompt(
                        task_key, calls, task_state, category, str(exc)
                    ),
                }
            )
            log_event(
                {
                    "event": "repair_prompt",
                    "run_id": run_id,
                    "category": category,
                    "problem": str(exc),
                }
            )
            continue

        if action["type"] == "final":
            if first_well_formed is None:
                first_well_formed = not required_sequence
            if repair_pending and after_repair_well_formed is None:
                after_repair_well_formed = not required_sequence
            if not task_evidence_satisfied(
                task_key, required_sequence, calls, task_state
            ):
                failures.append("lost_multi_step_chain")
                if not repair_pending:
                    repairs_used += 1
                    repair_pending = True
                    history.append(
                        {
                            "role": "user",
                            "content": build_repair_prompt(
                                task_key,
                                calls,
                                task_state,
                                "lost_multi_step_chain",
                                f"Required calls are {required_sequence}; "
                                f"completed calls are {calls}.",
                            ),
                        }
                    )
                    log_event(
                        {
                            "event": "repair_prompt",
                            "run_id": run_id,
                            "category": "lost_multi_step_chain",
                        }
                    )
                    continue
                answer = (
                    "Stopped because the required multi-step "
                    "tool sequence was not completed."
                )
                stop_reason = "human_review"
                break

            answer = action["answer"].strip()
            stop_reason = "success"
            if after_repair_well_formed is None:
                after_repair_well_formed = first_well_formed
            break

        if first_well_formed is None:
            first_well_formed = True
        if repair_pending and after_repair_well_formed is None:
            after_repair_well_formed = True
        repair_pending = False

        name = action["name"]
        arguments = action["arguments"]
        if budget is not None and budget.tool_calls >= budget.max_tool_calls:
            answer = "Stopped because the shared tool-call budget was exhausted."
            stop_reason = "budget_exhausted"
            break
        if budget is not None:
            budget.tool_calls += 1
        calls.append(name)
        log_event(
            {
                "event": "tool_call",
                "run_id": run_id,
                "name": name,
                "arguments": arguments,
            }
        )
        result = await execute_tool(name, arguments)
        tool_results.append({"name": name, "arguments": arguments, "result": result})
        record_task_result(name, arguments, result, task_state)
        log_event(
            {
                "event": "tool_result",
                "run_id": run_id,
                "name": name,
                "result": result,
            }
        )
        history.append(
            {
                "role": "tool",
                "name": name,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )

        # Task B's answer is deterministic after both exact tool results are verified.
        # Build it here instead of relying on another model JSON response.
        if task_key == "B" and task_evidence_satisfied(
            task_key, required_sequence, calls, task_state
        ):
            answer = format_task_b_answer(task_state)
            result = {
                "run_id": run_id,
                "task": task_id,
                "answer": answer,
                "tool_calls": calls,
                "tool_results": tool_results,
                "required_chain_satisfied": True,
                "stop_reason": "success",
                "token_count": budget.tokens
                if budget is not None
                else adapter.stats_info([])["total_tokens"],
                "first_action_well_formed": first_well_formed,
                "after_repair_well_formed": after_repair_well_formed,
                "repair_used": repairs_used > 0,
                "failure_categories": failures,
                "raw_responses": raw_responses,
            }
            log_event({"event": "final_result", **result})
            return result

    else:
        answer = (
            f"Stopped at the hard limit of {MAX_TOOL_CALLS} tool calls."
            if len(calls) >= MAX_TOOL_CALLS
            else f"Stopped at the hard limit of {MAX_MODEL_TURNS} model turns."
        )
        stop_reason = "budget_exhausted"

    result = {
        "run_id": run_id,
        "task": task_id,
        "answer": answer,
        "tool_calls": calls,
        "tool_results": tool_results,
        "required_chain_satisfied": task_evidence_satisfied(
            task_key, required_sequence, calls, task_state
        ),
        "first_action_well_formed": first_well_formed,
        "after_repair_well_formed": after_repair_well_formed,
        "repair_used": repairs_used > 0,
        "failure_categories": failures,
        "raw_responses": raw_responses,
        "stop_reason": stop_reason or "human_review",
        "token_count": budget.tokens
        if budget is not None
        else adapter.stats_info([])["total_tokens"],
    }
    log_event({"event": "final_result", **result})
    return result


async def run_reliability(attempts: int) -> dict[str, Any]:
    # Run at least 20 fixed A, B, C attempts and save per-attempt raw records.
    if attempts < 20:
        raise ValueError("The assignment requires at least 20 reliability attempts.")

    results = []
    task_names = ["A", "B", "C"]
    for index in range(attempts):
        task_name = task_names[index % len(task_names)]
        task = TASKS[task_name]
        # same model for every attempt.
        result = await run_agent(
            task["prompt"],
            task_id=f"reliability_{task_name}_{index + 1}",
            required_sequence=task["sequence"],
            adapter=ModelAdapter(**MODEL_SETTINGS),
        )
        results.append(result)

    initial_good = sum(item["first_action_well_formed"] is True for item in results)
    repaired_good = sum(
        (
            item["after_repair_well_formed"]
            if item["after_repair_well_formed"] is not None
            else item["first_action_well_formed"]
        )
        is True
        for item in results
    )
    chain_good = sum(item["required_chain_satisfied"] for item in results)
    categories = {
        category: sum(category in item["failure_categories"] for item in results)
        for category in (
            "malformed_arguments",
            "unknown_tool",
            "text_when_tool_required",
            "lost_multi_step_chain",
            "invalid_model_response",
        )
    }
    summary = {
        "attempts": attempts,
        "model_settings": MODEL_SETTINGS,
        "well_formed_initial_rate": initial_good / attempts,
        "well_formed_after_repair_rate": repaired_good / attempts,
        "required_chain_completion_rate": chain_good / attempts,
        "failure_counts": categories,
        "attempt_results": results,
    }

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"reliability_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    raw_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    summary_path = CODE_DIR / "reports" / "hw07" / "reliability_summary.md"
    table_lines = [
        "# HW7 reliability results",
        "",
        f"Attempts: {attempts}; model settings: `{json.dumps(MODEL_SETTINGS)}`",
        "",
        "| Measure | Result |",
        "|---|---:|",
        f"| Well-formed initial action | {initial_good}/{attempts} "
        f"({summary['well_formed_initial_rate']:.1%}) |",
        f"| Well-formed after repair | {repaired_good}/{attempts} "
        f"({summary['well_formed_after_repair_rate']:.1%}) |",
        f"| Required chain complete | {chain_good}/{attempts} "
        f"({summary['required_chain_completion_rate']:.1%}) |",
        "",
        "| Failure type | Attempts affected |",
        "|---|---:|",
    ]
    table_lines.extend(
        f"| {category} | {count} |" for category, count in categories.items()
    )
    table_lines.extend(
        [
            "",
            "Per-attempt data",
            "",
            "| # | Task | Initial | Repaired | Chain | Failures |",
            "|---:|---|---|---|---|---|",
        ]
    )
    table_lines.extend(
        "| {n} | {task} | {initial} | {repaired} | {chain} | {failures} |".format(
            n=index,
            task=item["task"],
            initial=item["first_action_well_formed"],
            repaired=item["after_repair_well_formed"],
            chain=item["required_chain_satisfied"],
            failures=", ".join(item["failure_categories"]) or "none",
        )
        for index, item in enumerate(results, start=1)
    )
    summary_path.write_text("\n".join(table_lines) + "\n", encoding="utf-8")
    log_event(
        {
            "event": "reliability_summary",
            "attempts": attempts,
            "initial_well_formed_rate": summary["well_formed_initial_rate"],
            "after_repair_well_formed_rate": summary["well_formed_after_repair_rate"],
            "required_chain_completion_rate": summary["required_chain_completion_rate"],
            "failure_counts": categories,
            "raw_data": str(raw_path),
        }
    )
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the HW7 GroceryRecall agent loop."
    )
    parser.add_argument(
        "--task", choices=["A", "B", "C", "error", "all"], default="all"
    )
    parser.add_argument("--reliability", action="store_true")
    parser.add_argument("--attempts", type=int, default=20)
    args = parser.parse_args()

    if args.reliability:
        summary = await run_reliability(args.attempts)
        printable = {
            key: value for key, value in summary.items() if key != "attempt_results"
        }
        print(json.dumps(printable, indent=2))
        return

    selected = list(TASKS) if args.task == "all" else [args.task]
    for task_name in selected:
        task = TASKS[task_name]
        result = await run_agent(
            task["prompt"],
            task_id=task_name,
            required_sequence=task["sequence"],
        )
        print(f"\nTask {task_name}:\n{result['answer']}\n")


if __name__ == "__main__":
    asyncio.run(main())
