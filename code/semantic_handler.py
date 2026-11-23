import logging
import os
from time import perf_counter
from typing import Awaitable, Callable
from semantic_cache import SemanticCache
from hw10_trace import current_trace, trace_stage

log = logging.getLogger("semantic_cache")


class SemanticQuestionHandler:
    def __init__(
        self,
        cache: SemanticCache,
        run_pipeline: Callable[[str], Awaitable[str]],
    ):
        self.cache = cache
        self.run_pipeline = run_pipeline
        self.measurements = []

    async def answer(self, question: str) -> dict:
        question = question.strip()
        if not question:
            raise ValueError("Question must not be empty")

        started = perf_counter()

        operation_started = perf_counter()
        with trace_stage("embedding"):
            embedding = self.cache.embed(question)
        embedding_ms = (perf_counter() - operation_started) * 1000

        operation_started = perf_counter()
        with trace_stage("cache_lookup"):
            match = self.cache.lookup(embedding)
            trace = current_trace.get()
            if trace is not None:
                trace["cache_outcome"] = "hit" if match["is_cached"] else "miss"
        lookup_ms = (perf_counter() - operation_started) * 1000

        trace = current_trace.get()
        if trace is not None:
            trace["cache_outcome"] = "hit" if match["is_cached"] else "miss"

        agent_ms = 0.0
        store_ms = 0.0

        if match["is_cached"]:
            answer = match["answer"]

            log.info(
                "Cache hit: similarity=%.4f",
                match["similarity_score"],
            )
        else:
            log.info(
                "Cache miss: nearest_similarity=%s",
                match["similarity_score"],
            )

            operation_started = perf_counter()
            with trace_stage("pipeline"):
                answer = await self.run_pipeline(question)
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("Agent did not return a valid final answer")
            agent_ms = (perf_counter() - operation_started) * 1000

            operation_started = perf_counter()
            if os.environ.get("HW10_DISABLE_CACHE_WRITES") != "1":
                operation_started = perf_counter()
                with trace_stage("cache_store"):
                    self.cache.store(question, embedding, answer)
                store_ms = (perf_counter() - operation_started) * 1000

        latency_ms = (perf_counter() - started) * 1000

        response = {
            "question": question,
            "answer": answer,
            "is_cached": match["is_cached"],
            "similarity_score": match["similarity_score"],
            "latency_ms": latency_ms,
            "data_version": self.cache.data_version,
            "timings_ms": {
                "embedding": embedding_ms,
                "lookup": lookup_ms,
                "agent": agent_ms,
                "store": store_ms,
            },
        }

        self.measurements.append(
            {
                "is_cached": response["is_cached"],
                "latency_ms": latency_ms,
            }
        )

        log.info(
            "Response: is_cached=%s latency_ms=%.2f",
            response["is_cached"],
            latency_ms,
        )

        return response

    def report(self) -> dict:
        hits = [item["latency_ms"] for item in self.measurements if item["is_cached"]]
        misses = [
            item["latency_ms"] for item in self.measurements if not item["is_cached"]
        ]

        total = len(self.measurements)

        return {
            "total_queries": total,
            "cache_hits": len(hits),
            "cache_misses": len(misses),
            "cache_hit_rate_percent": (100 * len(hits) / total if total else 0.0),
            "average_cached_latency_ms": (sum(hits) / len(hits) if hits else None),
            "average_non_cached_latency_ms": (
                sum(misses) / len(misses) if misses else None
            ),
        }
