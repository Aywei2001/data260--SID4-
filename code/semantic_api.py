import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from semantic_cache import SemanticCache
from semantic_demo import run_pipeline
from semantic_handler import SemanticQuestionHandler

from time import perf_counter, time
from uuid import uuid4

from hw10_trace import current_trace, init_trace_db, record_request


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)
log = logging.getLogger("semantic_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_trace_db()
    cache = await asyncio.to_thread(SemanticCache)

    app.state.handler = SemanticQuestionHandler(
        cache,
        run_pipeline,
    )

    try:
        yield
    finally:
        cache.client.close()


app = FastAPI(
    title="Grocery Supply and Recall Notices Q&A",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_qa_request(request: Request, call_next):
    if request.method != "POST" or request.url.path != "/qa":
        return await call_next(request)

    trace = {
        "trace_id": str(uuid4()),
        "cache_outcome": "unknown",
    }
    token = current_trace.set(trace)
    started_at = time()
    started = perf_counter()
    http_status = 500

    try:
        response = await call_next(request)
        http_status = response.status_code
        response.headers["X-Trace-ID"] = trace["trace_id"]
        return response
    except Exception as exc:
        trace["error"] = type(exc).__name__
        raise
    finally:
        try:
            record_request(
                trace,
                started_at,
                (perf_counter() - started) * 1000,
                http_status,
            )
        finally:
            current_trace.reset(token)


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


@app.post("/qa")
async def answer_question(body: QuestionRequest, request: Request):
    question = body.question.strip()
    if not question:
        raise HTTPException(
            status_code=422,
            detail="Question must not be blank",
        )

    try:
        result = await request.app.state.handler.answer(question)
        trace = current_trace.get()
        if trace is not None:
            result["trace_id"] = trace["trace_id"]
        return result
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="The agent pipeline timed out",
        ) from exc
    except Exception as exc:
        log.exception("Q&A request failed")
        raise HTTPException(
            status_code=503,
            detail="The cache or agent pipeline could not complete the request",
        ) from exc


@app.get("/qa/metrics")
async def cache_metrics(request: Request):
    return request.app.state.handler.report()