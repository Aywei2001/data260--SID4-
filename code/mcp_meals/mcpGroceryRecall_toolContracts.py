import time
import random
import json
import os
import asyncio  
from pathlib import Path
import logging
from mcp_GroceryRecall_rel import search_grocery_recalls, recall_detail_lookup, aggregate_company_stats

logging.getLogger("httpx").setLevel(logging.WARNING)


def call_retry(tool_func, tool_arg: dict, fail_rate: float, seed: int, max_retries: int = 3):
    rng = random.Random(seed)

    delay = 0.1

    for attempt in range(max_retries + 1):
        start = time.time()
        try:
            if rng.random() < fail_rate:
                raise TimeoutError("Connection timed out.")

            result = asyncio.run(tool_func(**tool_arg))

            total_latency = (time.time() - start) * 1000
            return {"success": True, "attempts": attempt + 1, "latency_ms": total_latency, "result": result, "error": None}
        except Exception as e:
            total_latency = (time.time() - start) * 1000
            if attempt == max_retries:
                return {"success": False, "attempts": attempt + 1, "latency_ms": total_latency, "error": str(e)}
            time.sleep(delay)
            delay *= 2


def start_simulation():
    verify_seed = 261339

    rates = [0.0, 0.2, 0.5]

    output_directory = Path(__file__).resolve().parents[2] / "reports" / "hw05" / "raw"
    output_directory.mkdir(parents = True, exist_ok = True)

    target_test = (search_grocery_recalls, {"query": "cheese"})

    summary_results = []

    for rate in rates:
        latencies = []
        successes = 0
        raw_logs = []

        for i in range(50):
            call_seed = verify_seed + int(rate * 100) + i
            func, args = target_test
            res = call_retry(func, args, fail_rate = rate, seed = call_seed)

            raw_logs.append(res)
            if res["success"]:
                successes += 1
                latencies.append(res["latency_ms"])

        success_rate = (successes / 50) * 100
        mean_latency = sum(latencies) / len(latencies) if latencies else 0
        latencies.sort()
        p99_latency = latencies[int(len(latencies) * 0.99)] if latencies else 0

        summary_results.append({"injected_failure_rate": f"{int(rate * 100)}%", "success_rate": f"{success_rate}%",
            "mean_latency_ms": round(mean_latency, 2), "p99_latency_ms": round(p99_latency, 2)})

        with open(output_directory / f"grocery_failure_rate_{int(rate * 100)}.json", "w") as f:
            json.dump(raw_logs, f, indent=2)

    print(json.dumps(summary_results, indent=2))


if __name__ == "__main__":
    start_simulation()