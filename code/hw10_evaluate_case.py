import argparse
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from hw10_trace import init_trace_db, trace_stage

RESULTS = Path(__file__).resolve().parents[1] / "reports" / "hw10" / "evaluations"
MODEL = "llama3.2"
BASE_URL = "http://127.0.0.1:11434"
TEMPERATURE = 0.0

PLAN_CRITERIA = (
    "Score whether the plan addresses the question with relevant, ordered, "
    "actionable steps. Use the expected output as a checklist of relevant topics."
)
HELPFULNESS_CRITERIA = (
    "Score whether the answer directly addresses the question, covers the "
    "relevant reference steps, and avoids unsupported claims or advice. "
    "Accept equivalent wording."
)
REFERENCE = (
    "Identify the affected product and lot from the notice. Isolate affected "
    "stock and prevent its sale. Notify responsible staff and follow the "
    "specific notice for disposition. Document the actions taken."
)


def grade(case_path):
    from deepeval.metrics import GEval
    from deepeval.models import OllamaModel
    from deepeval.test_case import LLMTestCase, SingleTurnParams

    case = json.loads(case_path.read_text(encoding="utf-8"))
    messages = case["messages"]
    trace_id = case["trace_id"]
    if any(m["payload"]["correlation_id"] != trace_id for m in messages.values()):
        raise ValueError("Case contains mismatched correlation IDs")

    judge = OllamaModel(model=MODEL, base_url=BASE_URL, temperature=TEMPERATURE)
    plan = json.dumps(messages["plan"]["payload"]["plan"])
    draft = messages["draft"]["payload"]["draft"]
    final = messages["final"]["payload"]["answer"]

    def score(name, output, criteria):
        metric = GEval(
            name=name,
            criteria=criteria,
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.EXPECTED_OUTPUT,
            ],
            model=judge,
            async_mode=False,
        )
        metric.measure(
            LLMTestCase(
                input=case["question"],
                actual_output=output,
                expected_output=REFERENCE,
            )
        )
        raw = float(metric.score)
        if not 0 <= raw <= 1:
            raise ValueError(f"Unexpected normalized score: {raw}")
        return {"raw_score": raw, "score_1_to_5": 1 + 4 * raw, "reason": metric.reason}

    scores = {
        "plan_quality": score("Plan Quality", plan, PLAN_CRITERIA),
        "draft_helpfulness": score("Helpfulness", draft, HELPFULNESS_CRITERIA),
        "final_helpfulness": score("Helpfulness", final, HELPFULNESS_CRITERIA),
    }
    delta = (
        scores["final_helpfulness"]["score_1_to_5"]
        - scores["draft_helpfulness"]["score_1_to_5"]
    )
    if draft == final:
        interpretation = "The Reviewer returned identical text. Any score difference is judge variation."
    elif delta > 0:
        interpretation = "The judge rated the final answer higher. Compare the reasons and text to explain why."
    elif delta < 0:
        interpretation = "The judge rated the final answer lower. Compare the reasons and text to explain why."
    else:
        interpretation = "The judge measured no change in helpfulness."

    RESULTS.mkdir(parents=True, exist_ok=True)
    output = RESULTS / f"{trace_id}.json"
    output.write_text(
        json.dumps(
            {
                "trace_id": trace_id,
                "question": case["question"],
                "judge": {
                    "method": "DeepEval G-Eval",
                    "model": MODEL,
                    "temperature": TEMPERATURE,
                    "base_url": BASE_URL,
                    "deepeval_version": version("deepeval"),
                    "scale": "1 + 4 × raw_score",
                },
                "criteria": {
                    "plan": PLAN_CRITERIA,
                    "draft_and_final": HELPFULNESS_CRITERIA,
                },
                "reference": REFERENCE,
                "scores": scores,
                "final_minus_draft": delta,
                "draft": draft,
                "final_answer": final,
                "interpretation": interpretation,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", type=Path)
    parser.add_argument("--grade", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.grade:
        grade(args.case)
    else:
        case = json.loads(args.case.read_text(encoding="utf-8"))
        init_trace_db()

        try:
            with trace_stage("evaluation", trace_id=case["trace_id"]):
                subprocess.run(
                    [sys.executable, __file__, str(args.case), "--grade"],
                    timeout=300,
                    check=True,
                )
        except subprocess.TimeoutExpired:
            raise SystemExit("G-Eval timed out after 300 seconds. Check Ollama.")
        except subprocess.CalledProcessError:
            raise SystemExit("G-Eval failed. See the judge error above.")
