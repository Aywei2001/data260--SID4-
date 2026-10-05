import asyncio
import json
from pathlib import Path
from mcp_GroceryRecall_rel import search_grocery_recalls, recall_detail_lookup, aggregate_company_stats

def create_envelope(data = None, error = None) -> dict:
    if error:
        return {"ok": False, "data": None, "error": error}
    
    return {"ok": True, "data": data, "error": None}

async def execute_tool(name: str, inputs: dict) -> str:

    query_value = str(inputs.get("query", "")).lower()
    company_value = str(inputs.get("company_name", "")).lower()

    if "banned" in query_value or "unauthorized" in company_value or "classified" in query_value:
        return json.dumps({ "ok": False, "data": None, "error": "You are not authorized to access banned or restricted grocery recall records"})

    try:
        if name == "search_grocery_recalls":
            res = await search_grocery_recalls(**inputs)
        elif name == "recall_detail_lookup":
            res = await recall_detail_lookup(**inputs)
        elif name == "aggregate_company_stats":
            res = await aggregate_company_stats(**inputs)
        else:
            res = {"ok": False, "data": None, "error": f"Unknown tool: {name}"}
    except Exception as e:
        res = {"ok": False, "data": None, "error": str(e)}

    return json.dumps(res)

class MockModel:
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    def chat(self, model, messages, tools):
        resp = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return resp

def run_agent(user_input: str, max_steps: int = 5, client=None):
    logs_dir = Path(__file__).resolve().parents[2] / "reports" / "hw05" / "raw"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "agent_runs.jsonl"

    messages = [{"role": "user", "content": user_input}]
    
    #all available tools for loop
    available_tools = [{"type": "function",
                        "function": {"name": "search_grocery_recalls", "description": "Search grocery recalls by product description query.",
                                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
                        {"type": "function",
                            "function": {"name": "recall_detail_lookup", "description": "Get detailed information about a specific recall by its recall number.",
                                        "parameters": {"type": "object", "properties": {"recall_number": {"type": "string"}}, "required": ["recall_number"]}} },
                        {"type": "function",
                        "function": {"name": "aggregate_company_stats", "description": "Get aggregated recall statistics for a specific recalling company.",
                                    "parameters": {"type": "object", "properties": {"company_name": {"type": "string"}}, "required": ["company_name"]}}}]

    step_count = 0
    tool_call_count = 0
    stop_reason = "completed"

    run_log_entries = []

    #Ollama agent loop
    while step_count < max_steps:
        step_count += 1

        if client:
            response = client.chat(model="llama3", messages=messages, tools=available_tools)
        else:
            response = ollama.chat(model="llama3", messages=messages, tools=available_tools)

        message = response.get("message", {})
        messages.append(message)

        tool_calls = message.get("tool_calls", [])
        
        if not tool_calls:
            stop_reason = "model_finished"
            break

        for tool_call in tool_calls:
            tool_call_count += 1
            func_name = tool_call["function"]["name"]
            func_args = tool_call["function"]["arguments"]

            tool_result_json = asyncio.run(execute_tool(func_name, func_args))


            run_log_entries.append({"step": step_count, "tool_call": func_name, "input": func_args, "result": json.loads(tool_result_json)})

            messages.append({"role": "tool", "name": func_name, "content": tool_result_json})

    else:
        stop_reason = "max_steps_exceeded"

    
    run_record = {
        "user_input": user_input,
        "steps": step_count,
        "tool_call_count": tool_call_count,
        "stop_reason": stop_reason,
        "history": run_log_entries
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(run_record) + "\n")

    return run_record

def assert_test(test_name: str, condition: bool, results: list, error: str = ""):
    results[1] += 1
    try:
        assert condition, error
        print(f"Test Passed: {test_name}")
        results[0] += 1
    except AssertionError as e:
        print(f"Test Failed: {test_name}, {e}")

def run_test():
    #results [0] is passed test count
    #results [1] is total tests
    results = [0, 0]
    
    res1 = asyncio.run(execute_tool("search_grocery_recalls", {"query": "contamination"}))
    data1 = json.loads(res1)
    assert_test("Valid Search", data1["ok"] == True and len(data1["data"]) > 0, results)

    res2 = asyncio.run(execute_tool("search_grocery_recalls", {"query": "The Avengers"}))
    data2 = json.loads(res2)
    assert_test("Invalid Search", data2["ok"] == False and data2["error"] is not None, results)

    res3 = asyncio.run(execute_tool("recall_detail_lookup", {"recall_number": "F-0975-2021"}))
    data3 = json.loads(res3)
    assert_test("Valid Detail Lookup", data3["ok"] == True or data3["data"] is not None, results)

    res4 = asyncio.run(execute_tool("recall_detail_lookup", {"recall_number": "67"}))
    data4 = json.loads(res4)
    assert_test("Invalid Detail Lookup", data4["ok"] == False, results)

    res5 = asyncio.run(execute_tool("aggregate_company_stats", {"company_name": "Safeway"}))
    data5 = json.loads(res5)
    assert_test("Valid Aggregate Stats", data5["ok"] == True, results)

    res6 = asyncio.run(execute_tool("aggregate_company_stats", {"company_name": "Pokemon"}))
    data6 = json.loads(res6)
    assert_test("Invalid Aggregate Stats", data6["ok"] == False, results)

    allowed_demo = asyncio.run(execute_tool("search_grocery_recalls", {"query": "cheese"}))
    blocked_demo = asyncio.run(execute_tool("search_grocery_recalls", {"query": "banned substance"}))
    
    allowed_data = json.loads(allowed_demo)
    blocked_data = json.loads(blocked_demo)
    
    assert_test("Safety Rule Allowed Call", allowed_data["ok"] == True, results)
    assert_test("Safety Rule Blocked Call", blocked_data["ok"] == False and "Safety violation" in blocked_data["error"], results)

    safety_test_res = asyncio.run(execute_tool("aggregate_company_stats", {"company_name": "unauthorized firm"}))
    safety_data = json.loads(safety_test_res)
    assert_test("Offline Test - Safety Rule Enforcement", safety_data["ok"] == False, results)

    mock_responses = [{"message": {"tool_calls": [{"function": {"name": "search_grocery_recalls", "arguments": {"query": "cheese"}}}]}},
                    {"message": {"tool_calls": [{"function": {"name": "search_grocery_recalls", "arguments": {"query": "cheese"}}}]}},
                    {"message": {"tool_calls": [{"function": {"name": "search_grocery_recalls", "arguments": {"query": "cheese"}}}]}} ]
    mock_client = MockModel(mock_responses)
    agent_output = run_agent("Find cheese recalls repeatedly", max_steps=2, client=mock_client)
    assert_test("Offline Test - Max Steps Limit Reached", agent_output["stop_reason"] == "max_steps_exceeded", results)

    print(f"\nTest Results: {results[0]}/{results[1]} tests passed")


if __name__ == "__main__":
    run_test()