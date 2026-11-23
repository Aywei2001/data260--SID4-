import argparse
import json
import math
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from statistics import median
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT.parent / "reports" / "hw10" / "latency"
QUESTION = "What should a grocery store do after receiving a supplier recall notice?"
WAITS = ("queue_wait_planner", "queue_wait_writer", "queue_wait_reviewer")
STAGES = ("cache_lookup", "planner", "writer", "reviewer", *WAITS, "evaluation")


def invoke(python, *args, timeout):
    result = subprocess.run(
        [str(python), *map(str, args)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-3500:])
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("Saved "):
            return Path(line.removeprefix("Saved "))
    raise RuntimeError("The command did not print a saved report path.")


def load_spans(trace_id):
    db_path = (ROOT / "hw10_traces.sqlite3").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(db_path, uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        request = db.execute(
            "SELECT * FROM requests WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        spans = db.execute(
            "SELECT * FROM stages WHERE trace_id = ? ORDER BY event_id", (trace_id,)
        ).fetchall()
    if request is None or (request["http_status"], request["cache_outcome"]) != (
        200,
        "miss",
    ):
        raise ValueError(f"{trace_id}: expected HTTP 200 and a cache miss.")
    if any(span["stage"] == "cache_store" for span in spans):
        raise ValueError(f"{trace_id}: cache writes are still enabled.")
    return request, spans


def stage_spans(trace_id, spans, names):
    selected = {}
    for name in names:
        matches = [span for span in spans if span["stage"] == name]
        if len(matches) != 1 or matches[0]["status"] != "ok":
            raise ValueError(
                f"{trace_id}: expected exactly one successful {name} span."
            )
        if matches[0]["duration_ms"] < 0:
            raise ValueError(f"{trace_id}: negative duration for {name}.")
        selected[name] = matches[0]
    return selected


def summarize(rows):
    total = sum(row["end_to_end_ms"] for row in rows)
    result = []
    for name in (
        "cache_lookup",
        "planner",
        "writer",
        "reviewer",
        "queue_wait_total",
        "evaluation",
    ):
        values = sorted(row["stage_ms"][name] for row in rows)
        result.append(
            {
                "stage": name,
                "p50_ms": median(values),
                "p95_ms": values[math.ceil(0.95 * len(values)) - 1],
                "percent_end_to_end": 100 * sum(values) / total,
            }
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, choices=(1, 50), default=50)
    args = parser.parse_args()
    app_python = ROOT / ".venv" / "Scripts" / "python.exe"
    judge_python = ROOT / ".venv-eval" / "Scripts" / "python.exe"
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"latency_{args.count}_{uuid4().hex[:10]}.json"
    report = {
        "target": args.count,
        "question": QUESTION,
        "boundary": "API ingress through evaluation completion",
        "p95_method": "nearest rank",
        "rows": [],
        "complete": False,
    }

    def save():
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"Report: {path}", flush=True)
    seen = set()
    for number in range(1, args.count + 1):
        print(f"Request {number}/{args.count}", flush=True)
        trace_id = None
        try:
            case_path = invoke(
                app_python,
                "hw10_collect_case.py",
                "--via-api",
                QUESTION,
                timeout=450,
            )
            case = json.loads(case_path.read_text(encoding="utf-8-sig"))
            trace_id = case["trace_id"]
            if trace_id in seen or set(case["messages"]) != {
                "inbox",
                "plan",
                "draft",
                "final",
            }:
                raise ValueError(
                    f"{trace_id}: repeated ID or incomplete Kafka capture."
                )
            if any(
                msg["payload"]["correlation_id"] != trace_id
                for msg in case["messages"].values()
            ):
                raise ValueError(f"{trace_id}: mismatched Kafka correlation ID.")
            request, spans = load_spans(trace_id)
            stage_spans(trace_id, spans, STAGES[:-1])
            evaluation_path = invoke(
                judge_python,
                "hw10_evaluate_case.py",
                case_path,
                timeout=330,
            )
            request, spans = load_spans(trace_id)
            selected = stage_spans(trace_id, spans, STAGES)
            end_to_end = (
                selected["evaluation"]["ended_at"] - request["started_at"]
            ) * 1000
            if end_to_end <= 0:
                raise ValueError(f"{trace_id}: invalid end-to-end duration.")
            durations = {name: span["duration_ms"] for name, span in selected.items()}
            durations["queue_wait_total"] = sum(durations[name] for name in WAITS)
            report["rows"].append(
                {
                    "trace_id": trace_id,
                    "cache_outcome": "miss",
                    "http_status": 200,
                    "api_ms": request["duration_ms"],
                    "end_to_end_ms": end_to_end,
                    "stage_ms": durations,
                    "case": str(case_path),
                    "evaluation_report": str(evaluation_path),
                }
            )
            seen.add(trace_id)
            save()
        except (
            OSError,
            ValueError,
            RuntimeError,
            KeyError,
            sqlite3.Error,
            subprocess.TimeoutExpired,
        ) as exc:
            report["error"] = {
                "request": number,
                "trace_id": trace_id,
                "message": str(exc),
            }
            save()
            raise SystemExit(f"Stopped at request {number}. See {path}\n{exc}") from exc

    report["summary"] = summarize(report["rows"])
    report["complete"] = True
    save()
    print(json.dumps(report["summary"], indent=2))
    print(f"Saved {path}")


if __name__ == "__main__":
    main()
