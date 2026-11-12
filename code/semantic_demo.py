import asyncio
import json
import logging

from semantic_cache import SemanticCache
from semantic_handler import SemanticQuestionHandler
from send_question import ask_pipeline


async def run_pipeline(question: str) -> str:
    result = await asyncio.to_thread(ask_pipeline, question)

    if result.get("status") != "approved":
        raise RuntimeError(f"Pipeline did not produce an approved answer: {result}")

    answer = result.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Pipeline returned no final answer")

    return answer


async def main():
    from datetime import datetime, timezone
    from pathlib import Path

    cache = SemanticCache()
    handler = SemanticQuestionHandler(cache, run_pipeline)

    questions = [
        (
            "new",
            "What should a grocery store do after receiving a supplier recall notice?",
        ),
        (
            "exact_duplicate",
            "What should a grocery store do after receiving a supplier recall notice?",
        ),
        (
            "paraphrase",
            "What actions should a grocery retailer take when "
            "a supplier sends a recall notice?",
        ),
        (
            "new",
            "How should a grocery store handle a recall when "
            "the affected lot codes cannot be read?",
        ),
        (
            "exact_duplicate",
            "How should a grocery store handle a recall when "
            "the affected lot codes cannot be read?",
        ),
        (
            "paraphrase",
            "What should a grocery retailer do if recalled "
            "inventory has illegible lot numbers?",
        ),
        (
            "new",
            "How should a grocery store handle a recall when "
            "some affected products have already been sold?",
        ),
        (
            "exact_duplicate",
            "How should a grocery store handle a recall when "
            "some affected products have already been sold?",
        ),
        (
            "paraphrase",
            "What should a grocery retailer do when customers "
            "have already purchased items covered by a recall?",
        ),
        (
            "new",
            "How should a grocery store respond when its "
            "point-of-sale system cannot block recalled items?",
        ),
        (
            "exact_duplicate",
            "How should a grocery store respond when its "
            "point-of-sale system cannot block recalled items?",
        ),
        (
            "paraphrase",
            "How can a grocery retailer prevent sales of recalled "
            "products if its checkout blocking system is unavailable?",
        ),
    ]

    results = []

    for number, (category, question) in enumerate(questions, start=1):
        print(f"\n=== Query {number}/{len(questions)}: {category} ===")

        try:
            response = await handler.answer(question)
            result = {
                "number": number,
                "category": category,
                **response,
            }
        except Exception as exc:
            result = {
                "number": number,
                "category": category,
                "question": question,
                "error": str(exc),
            }

        results.append(result)
        print(json.dumps(result, indent=2))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_version": cache.data_version,
        "similarity_threshold": cache.threshold,
        "attempted_queries": len(questions),
        "failed_queries": sum("error" in item for item in results),
        "metrics_for_successful_queries": handler.report(),
        "results": results,
    }

    output_dir = Path(__file__).resolve().parent / "reports"
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"semantic_cache_test_{timestamp}.json"
    output_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nMeasured summary:")
    print(json.dumps(report["metrics_for_successful_queries"], indent=2))
    print("Failed queries:", report["failed_queries"])
    print("Saved report:", output_path)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
    )
    asyncio.run(main())
