import argparse
import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from importlib.metadata import version
from itertools import combinations
from pathlib import Path
from uuid import uuid4
from hw10_evaluate_case import BASE_URL, HELPFULNESS_CRITERIA, MODEL, TEMPERATURE


ROOT = Path(__file__).resolve().parent


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def rank(values):
    #use average ranks for ties
    ranked = [0.0] * len(values)
    order = sorted(range(len(values)), key=values.__getitem__)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        for index in order[start:end]:
            ranked[index] = (start + 1 + end) / 2
        start = end
    return ranked


def summarize(rows):
    first = [row for row in rows if row["run"] == 1]
    human = [row["human_score"] for row in first]
    judge = [row["score_1_to_5"] for row in first]
    try:
        rho = statistics.correlation(rank(human), rank(judge))
    except statistics.StatisticsError:
        rho = None  #constant score series has undefined rank correlation

    by_case = {}
    for row in rows:
        by_case.setdefault(row["case_id"], []).append(row["raw_score"])
    changes = [
        4 * abs(a - b)
        for scores in by_case.values()
        for a, b in combinations(scores, 2)
    ]
    changed = sum(len(set(scores)) > 1 for scores in by_case.values())
    return {
        "cases": len(by_case),
        "agreement_run": 1,
        "spearman_rho": rho,
        "mean_absolute_difference": statistics.mean(
            abs(a - b) for a, b in zip(human, judge, strict=True)
        ),
        "repeatability": {
            "runs": 3,
            "cases_with_score_change": changed,
            "percent_with_score_change": 100 * changed / len(by_case),
            "run_pairs_compared": len(changes),
            "mean_absolute_pairwise_change": statistics.mean(changes),
            "max_absolute_pairwise_change": max(changes),
        },
    }


def grade(input_path, output_path):
    from deepeval.metrics import GEval
    from deepeval.models import OllamaModel
    from deepeval.test_case import LLMTestCase, SingleTurnParams

    case = load_json(input_path)
    metric = GEval(
        name="Helpfulness",
        criteria=HELPFULNESS_CRITERIA,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=OllamaModel(model=MODEL, base_url=BASE_URL, temperature=TEMPERATURE),
        async_mode=False,
    )
    metric.measure(LLMTestCase(
        input=case["question"],
        actual_output=case["writer_draft"],
        expected_output=case["reference"],
    ))
    raw = float(metric.score)
    if not math.isfinite(raw) or not 0 <= raw <= 1:
        raise ValueError(f"Invalid normalized score: {raw}")
    write_json(output_path, {
        "raw_score": raw,
        "score_1_to_5": 1 + 4 * raw,
        "reason": metric.reason,
    })


def git(*args):
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, timeout=20,
    ).strip()


def run(commit, timeout):
    case_path = ROOT / "eval_cases.json"
    label_path = ROOT / "human_labels.csv"
    cases = load_json(case_path)
    with label_path.open(encoding="utf-8-sig", newline="") as handle:
        labels = list(csv.DictReader(handle))

    ids = [case["case_id"] for case in cases]
    label_ids = [row["case_id"] for row in labels]
    if len(ids) != 20 or len(set(ids)) != 20:
        raise ValueError("Expected 20 uniquely identified cases.")
    if len(label_ids) != 20 or set(ids) != set(label_ids):
        raise ValueError("Expected one human label for each of the 20 cases.")
    if any(not case[key].strip() for case in cases
           for key in ("question", "writer_draft", "reference")):
        raise ValueError("Every case needs a question, draft, and reference.")
    scores = {row["case_id"]: int(row["human_score"]) for row in labels}
    if any(not 1 <= score <= 5 for score in scores.values()):
        raise ValueError("Human scores must be integers from 1 to 5.")

    frozen = git("rev-parse", "--verify", f"{commit}^{{commit}}")
    hashes = {}
    for path in (case_path, label_path):
        tagged = git("rev-parse", "--verify", f"{frozen}:code/{path.name}")
        current = git("hash-object", "--", path.name)
        if current != tagged:
            raise ValueError(f"{path.name} differs from the freeze commit.")
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

    folder = ROOT.parent / "reports" / "hw10" / "judge_validation"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"judge_validation_{uuid4().hex[:12]}.json"
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_commit": frozen,
        "input_sha256": hashes,
        "judge": {
            "method": "DeepEval G-Eval",
            "model": MODEL,
            "base_url": BASE_URL,
            "temperature": TEMPERATURE,
            "deepeval_version": version("deepeval"),
            "criteria": HELPFULNESS_CRITERIA,
            "scale": "1 + 4 * raw_score",
            "timeout_seconds_per_score": timeout,
        },
        "results": [],
        "complete": False,
    }
    write_json(path, report)
    print(f"Report: {path}", flush=True)

    with tempfile.TemporaryDirectory(prefix="hw10-judge-") as directory:
        input_path = Path(directory) / "input.json"
        output_path = Path(directory) / "score.json"
        for number in range(1, 4):
            for case in cases:
                case_id = case["case_id"]
                #judge receives the case fields and the reference
                write_json(input_path, {
                    key: case[key] for key in ("question", "writer_draft", "reference")
                })
                output_path.unlink(missing_ok=True)
                print(f"Run {number}/3 | {case_id}", flush=True)
                try:
                    subprocess.run(
                        [sys.executable, str(Path(__file__).resolve()),
                         "--worker", str(input_path), str(output_path)],
                        check=True,
                        timeout=timeout,
                    )
                    score = load_json(output_path)
                except (subprocess.SubprocessError, OSError, ValueError) as exc:
                    report["error"] = {
                        "run": number, "case_id": case_id,
                        "type": type(exc).__name__, "message": str(exc),
                    }
                    write_json(path, report)
                    raise SystemExit(f"Grading stopped. Partial report: {path}") from exc
                report["results"].append({
                    "run": number, "case_id": case_id, "trace_id": case["trace_id"],
                    "human_score": scores[case_id], **score,
                })
                write_json(path, report)

    for source in (case_path, label_path):
        if hashlib.sha256(source.read_bytes()).hexdigest() != hashes[source.name]:
            report["error"] = f"{source.name} changed during grading"
            write_json(path, report)
            raise SystemExit(f"{report['error']}. Partial report: {path}")

    report["summary"] = summarize(report["results"])
    report["complete"] = True
    write_json(path, report)
    print(json.dumps(report["summary"], indent=2))
    print(f"Saved {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-commit")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--worker", nargs=2, type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        grade(*args.worker)
    elif args.freeze_commit and args.timeout > 0:
        run(args.freeze_commit, args.timeout)
    else:
        parser.error("Provide --freeze-commit and a positive timeout.")
