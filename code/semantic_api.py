import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from semantic_cache import SemanticCache
from semantic_demo import run_pipeline
from semantic_handler import SemanticQuestionHandler


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)
log = logging.getLogger("semantic_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
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
        return await request.app.state.handler.answer(question)
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