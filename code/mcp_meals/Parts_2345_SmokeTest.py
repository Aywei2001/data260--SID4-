import asyncio
import json
from datetime import datetime
from pathlib import Path

# Import low-level domain tools and functions from your module
from mcp_GroceryRecall_rel import (
    search_grocery_recalls,
    recall_detail_lookup,
    aggregate_company_stats
)

# Import Part 4 & 5 harness functions from your safe tool file
from mcpGroceryRecall_safeTool import (
    create_envelope,
    execute_tool,
    run_agent,
    MockModel
)


def run_smoke_test_suite():
    test_results = []
    passed_count = 0
    total_count = 0

    def record_test(part: str, name: str, passed: bool, details: dict = None):
        nonlocal passed_count, total_count
        total_count += 1
        if passed:
            passed_count += 1
        
        test_results.append({
            "test_id": total_count,
            "part": part,
            "test_name": name,
            "status": "PASS" if passed else "FAIL",
            "details": details or {}
        })
        print(f"[{'PASS' if passed else 'FAIL'}] [{part}] Test {total_count}: {name}")

    env_ok = create_envelope(data={"test_key": "val"})
    record_test(
        "Part 2", 
        "Envelope Success Format {ok: True, data: ..., error: None}",
        env_ok == {"ok": True, "data": {"test_key": "val"}, "error": None},
        env_ok
    )

   
    env_err = create_envelope(error="Sample error")
    record_test(
        "Part 2", 
        "Envelope Error Format {ok: False, data: None, error: ...}",
        env_err == {"ok": False, "data": None, "error": "Sample error"},
        env_err
    )

    raw_search_valid = asyncio.run(search_grocery_recalls(query="cheese"))
    record_test(
        "Part 3",
        "Direct search_grocery_recalls - Valid query ('cheese')",
        raw_search_valid.get("ok") is True and len(raw_search_valid.get("data", [])) > 0,
        {"ok": raw_search_valid.get("ok"), "item_count": len(raw_search_valid.get("data", []))}
    )

    
    raw_search_invalid = asyncio.run(search_grocery_recalls(query="The Avengers"))
    record_test(
        "Part 3",
        "Direct search_grocery_recalls - Invalid query ('The Avengers')",
        raw_search_invalid.get("ok") is False and raw_search_invalid.get("error") is not None,
        {"ok": raw_search_invalid.get("ok"), "error": raw_search_invalid.get("error")}
    )

    
    raw_detail_valid = asyncio.run(recall_detail_lookup(recall_number="F-0975-2021"))
    record_test(
        "Part 3",
        "Direct recall_detail_lookup - Valid number ('F-0975-2021')",
        raw_detail_valid.get("ok") is True or raw_detail_valid.get("data") is not None,
        {"ok": raw_detail_valid.get("ok")}
    )

   
    raw_detail_invalid = asyncio.run(recall_detail_lookup(recall_number="67"))
    record_test(
        "Part 3",
        "Direct recall_detail_lookup - Invalid number ('67')",
        raw_detail_invalid.get("ok") is False and raw_detail_invalid.get("error") is not None,
        {"ok": raw_detail_invalid.get("ok"), "error": raw_detail_invalid.get("error")}
    )

 
    raw_stats_valid = asyncio.run(aggregate_company_stats(company_name="Safeway"))
    record_test(
        "Part 3",
        "Direct aggregate_company_stats - Valid firm ('Safeway')",
        raw_stats_valid.get("ok") is True and raw_stats_valid.get("data") is not None,
        {"ok": raw_stats_valid.get("ok")}
    )

   
    raw_stats_invalid = asyncio.run(aggregate_company_stats(company_name="Pokemon"))
    record_test(
        "Part 3",
        "Direct aggregate_company_stats - Invalid firm ('Pokemon')",
        raw_stats_invalid.get("ok") is False and raw_stats_invalid.get("error") is not None,
        {"ok": raw_stats_invalid.get("ok"), "error": raw_stats_invalid.get("error")}
    )

    ex_search_valid = json.loads(asyncio.run(execute_tool("search_grocery_recalls", {"query": "contamination"})))
    record_test(
        "Part 4",
        "execute_tool dispatch - search_grocery_recalls",
        ex_search_valid.get("ok") is True and len(ex_search_valid.get("data", [])) > 0,
        {"ok": ex_search_valid.get("ok")}
    )


    ex_unknown = json.loads(asyncio.run(execute_tool("nonexistent_tool", {})))
    record_test(
        "Part 4",
        "execute_tool error boundary - Unknown Tool name",
        ex_unknown.get("ok") is False and "Unknown tool" in str(ex_unknown.get("error")),
        ex_unknown
    )

   
    safe_allowed = json.loads(asyncio.run(execute_tool("search_grocery_recalls", {"query": "cheese"})))
    record_test(
        "Part 5",
        "Safety Rule - Allowed query ('cheese')",
        safe_allowed.get("ok") is True,
        {"ok": safe_allowed.get("ok")}
    )

    safe_blocked = json.loads(asyncio.run(execute_tool("search_grocery_recalls", {"query": "banned substance"})))
    record_test(
        "Part 5",
        "Safety Rule - Blocked query ('banned substance')",
        safe_blocked.get("ok") is False and "Safety violation" in str(safe_blocked.get("error")),
        safe_blocked
    )

    mock_responses = [{"message": {"tool_calls": [{"function": {"name": "search_grocery_recalls", "arguments": {"query": "cheese"}}}]}},
                        {"message": {"tool_calls": [{"function": {"name": "search_grocery_recalls", "arguments": {"query": "cheese"}}}]}},
                        {"message": {"tool_calls": [{"function": {"name": "search_grocery_recalls", "arguments": {"query": "cheese"}}}]}} ]
    mock_client = MockModel(mock_responses)
    agent_output = run_agent("Find cheese recalls repeatedly", max_steps=2, client=mock_client)
    
    record_test(
        "Part 5",
        "Offline Agent Loop - max_steps limit ceiling reached",
        agent_output.get("stop_reason") == "max_steps_exceeded",
        {
            "user_input": agent_output.get("user_input"),
            "steps": agent_output.get("steps"),
            "tool_call_count": agent_output.get("tool_call_count"),
            "stop_reason": agent_output.get("stop_reason")
        }
    )

    verification_payload = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_tests": total_count,
            "passed": passed_count,
            "failed": total_count - passed_count,
            "status": "SUCCESS" if passed_count == total_count else "FAILED"
        },
        "tests": test_results
    }

    output_path = Path("verification.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(verification_payload, f, indent=4)

    print(f" Smoke Test Complete: {passed_count}/{total_count} tests passed.")
    print(f" Verification output saved to: {output_path.resolve()}")



if __name__ == "__main__":
    run_smoke_test_suite()