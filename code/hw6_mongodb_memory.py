import math
import os
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from langchain_community.embeddings import OllamaEmbeddings
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_client import ModelAdapter
from hw6_mongodb import mongo_db

router = APIRouter(prefix="/api", tags=["memory"])

messages_collection = mongo_db["messages"]
summaries_collection = mongo_db["summaries"]
episodes_collection = mongo_db["episodes"]

SHORT_TERM_N = 4
SUMMARY_EVERY_USER_MSGS = 5
EPISODE_TOP_K = 3
EPISODE_FACT_MAX_LENGTH = 300

MODEL_NAME = os.getenv("SMOL_MODEL", "llama3.2")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

_model_adapter = None
_embedder = None


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"


class SummaryScope(str, Enum):
    session = "session"
    user = "user"


class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    session_id: str | None = None
    message: str = Field(..., min_length=1)


class MessageDocument(BaseModel):
    user_id: str
    session_id: str
    role: MessageRole
    content: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class SummaryDocument(BaseModel):
    user_id: str
    session_id: str | None = None
    scope: SummaryScope
    text: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class EpisodeDocument(BaseModel):
    user_id: str
    session_id: str
    fact: str = Field(..., min_length=1, max_length=EPISODE_FACT_MAX_LENGTH)
    importance: float = Field(..., ge=0, le=1)
    embedding: list[float] = Field(..., min_length=1)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


def get_model_adapter():
    global _model_adapter
    if _model_adapter is None:
        _model_adapter = ModelAdapter(
            model_name=MODEL_NAME,
            base_url=OLLAMA_URL,
            temperature=0.0,
        )
    return _model_adapter


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = OllamaEmbeddings(
            model=EMBEDDING_MODEL,
            base_url=OLLAMA_URL,
        )
    return _embedder


def call_model(system_prompt: str, user_prompt: str) -> dict:
    #Calling HW1 adapter here
    result, _usage = get_model_adapter().complete(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    return result


def embed_text(text: str) -> list[float]:
    return get_embedder().embed_query(text)


def cosine_similarity(first: list[float], second: list[float]) -> float:
    if not first or len(first) != len(second):
        return 0.0

    dot = sum(a * b for a, b in zip(first, second))
    first_norm = math.sqrt(sum(a * a for a in first))
    second_norm = math.sqrt(sum(b * b for b in second))

    if first_norm == 0 or second_norm == 0:
        return 0.0

    return dot / (first_norm * second_norm)


def latest_summary(user_id: str, scope: str, session_id: str | None = None):
    query = {"user_id": user_id, "scope": scope}
    if scope == "session":
        query["session_id"] = session_id
    else:
        query["session_id"] = None

    return summaries_collection.find_one(query, sort=[("created_at", -1)])


def retrieve_episodes(user_id: str, message_embedding: list[float]) -> list[dict]:
    ranked = []

    for episode in episodes_collection.find({"user_id": user_id}):
        score = cosine_similarity(message_embedding, episode.get("embedding", []))
        episode["similarity"] = score
        ranked.append(episode)

    ranked.sort(key=lambda item: item["similarity"], reverse=True)
    return ranked[:EPISODE_TOP_K]


def extract_episodes(user_id: str, session_id: str, message: str) -> None:
    #ask the adapter for up to three facts and encode importance
    result = call_model(
        system_prompt=(
            "Extract up to 3 durable, useful facts from the user's message. "
            "Return JSON with a tags array. Each tag must be formatted "
            "'0.85::short fact', where the number is importance from 0 to 1. "
            "Do not invent facts. Return an empty tags array if there are no facts."
        ),
        user_prompt=message,
    )

    for tagged_fact in result.get("tags", [])[:3]:
        score_text, separator, fact = tagged_fact.partition("::")
        if not separator:
            fact = tagged_fact
            importance = 0.5
        else:
            try:
                importance = max(0.0, min(1.0, float(score_text.strip())))
            except ValueError:
                importance = 0.5

        fact = fact.strip()[:EPISODE_FACT_MAX_LENGTH]
        if not fact:
            continue

        document = EpisodeDocument(
            user_id=user_id,
            session_id=session_id,
            fact=fact,
            importance=importance,
            embedding=embed_text(fact),
        )
        episodes_collection.insert_one(document.model_dump())


def save_summary(user_id: str, session_id: str | None, scope: str, text: str) -> None:
    document = SummaryDocument(
        user_id=user_id,
        session_id=session_id,
        scope=SummaryScope(scope),
        text=text,
    )
    summaries_collection.insert_one(document.model_dump())


def update_summaries_if_due(user_id: str, session_id: str) -> None:
    user_message_count = messages_collection.count_documents(
        {"user_id": user_id, "session_id": session_id, "role": "user"}
    )

    if user_message_count == 0 or user_message_count % SUMMARY_EVERY_USER_MSGS:
        return

    session_messages = list(
        messages_collection.find(
            {"user_id": user_id, "session_id": session_id}
        ).sort("created_at", 1)
    )
    transcript = "\n".join(
        f'{message["role"]}: {message["content"]}'
        for message in session_messages
    )

    session_summary = call_model(
        system_prompt=(
            "Summarize the conversation as concise and useful bullet points. "
            "Return JSON with one key: summary."
        ),
        user_prompt=transcript,
    ).get("summary", "").strip()

    if session_summary:
        save_summary(user_id, session_id, "session", session_summary)

    #occasionally condense summaries from multiple sessions into user level memory
    existing_lifetime = latest_summary(user_id, "user")

    new_session_summary_query = {
        "user_id": user_id,
        "scope": "session",
    }

    if existing_lifetime:
        new_session_summary_query["created_at"] = {
            "$gt": existing_lifetime["created_at"]
        }

    new_session_summaries = list(
        summaries_collection.find(new_session_summary_query)
    )

    newly_summarized_sessions = {
        item["session_id"]
        for item in new_session_summaries
        if item.get("session_id")
    }

    if len(newly_summarized_sessions) >= 3:
        recent_summaries = list(
            summaries_collection.find(
                {"user_id": user_id, "scope": "session"}
            ).sort("created_at", -1).limit(10)
        )

        summary_texts = [
            item["text"] for item in reversed(recent_summaries)
        ]

        if existing_lifetime:
            summary_texts.insert(0, existing_lifetime["text"])

        lifetime = call_model(
            system_prompt=(
                "Condense these session summaries into concise, durable long-term user memory. "
                "Return JSON with one key named summary."
            ),
            user_prompt="\n".join(summary_texts),
        ).get("summary", "").strip()

        if lifetime:
            save_summary(user_id, None, "user", lifetime)

def call_model_messages(messages: list[dict]) -> dict:
    result, _usage = get_model_adapter().complete(messages)
    return result


@router.post("/chat")
def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid4())
    now = datetime.now(timezone.utc)

    user_message = MessageDocument(
        user_id=request.user_id,
        session_id=session_id,
        role=MessageRole.user,
        content=request.message,
        created_at=now,
    )
    messages_collection.insert_one(user_message.model_dump())

    recent_messages = list(
        messages_collection.find(
            {"user_id": request.user_id, "session_id": session_id}
        ).sort("created_at", -1).limit(SHORT_TERM_N)
    )
    recent_messages.reverse()

    session_summary = latest_summary(request.user_id, "session", session_id)
    lifetime_summary = latest_summary(request.user_id, "user")

    message_embedding = embed_text(request.message)
    relevant_episodes = retrieve_episodes(request.user_id, message_embedding)

    memory_parts = []
    if lifetime_summary:
        memory_parts.append("Lifetime user memory:\n" + lifetime_summary["text"])
    if session_summary:
        memory_parts.append("Current session summary:\n" + session_summary["text"])
    if relevant_episodes:
        memory_parts.append(
            "Relevant facts:\n"
            + "\n".join(f"- {item['fact']}" for item in relevant_episodes)
        )

    system_prompt = (
        "You are a helpful assistant. Use the supplied memory when relevant. "
        "Do not claim to remember information that is not in the conversation or supplied memory.\n"
        "Return your response as JSON with exactly one key named summary. "
        "The summary value must be a helpful, natural assistant reply.\n"
        + "\n".join(memory_parts)
    )

    conversation = [{"role": "system", "content": system_prompt}]
    conversation.extend(
        {"role": item["role"], "content": item["content"]}
        for item in recent_messages
    )

    try:
        assistant_reply = call_model_messages(conversation).get("summary", "").strip()
        if not assistant_reply:
            assistant_reply = "I’m sorry, I couldn’t generate a reply."
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Local Ollama model is unavailable: {exc}",
        )

    assistant_message = MessageDocument(
        user_id=request.user_id,
        session_id=session_id,
        role=MessageRole.assistant,
        content=assistant_reply,
    )
    messages_collection.insert_one(assistant_message.model_dump())

    #extract facts and refresh summaries after recording this turn
    try:
        extract_episodes(request.user_id, session_id, request.message)
        update_summaries_if_due(request.user_id, session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Memory extraction or summarization failed: {exc}",
        )

    return {
        "user_id": request.user_id,
        "session_id": session_id,
        "assistant_reply": assistant_reply,
        "memory_used": {
            "short_term_message_count": len(recent_messages),
            "short_term_messages": [
                {"role": item["role"], "content": item["content"]}
                for item in recent_messages
            ],
            "session_summary": (
                session_summary["text"] if session_summary else None
            ),
            "lifetime_summary": (
                lifetime_summary["text"] if lifetime_summary else None
            ),
            "episodic_facts": [
                {
                    "fact": item["fact"],
                    "importance": item.get("importance", 0.5),
                    "similarity": item["similarity"],
                }
                for item in relevant_episodes
            ],
        },
    }


@router.get("/memory/{user_id}")
def get_memory(user_id: str):
    recent_messages = list(
        messages_collection.find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(16)
    )
    recent_messages.reverse()

    latest_session = summaries_collection.find_one(
        {"user_id": user_id, "scope": "session"},
        sort=[("created_at", -1)],
    )
    lifetime = latest_summary(user_id, "user")

    recent_episodes = list(
        episodes_collection.find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(20)
    )

    return {
        "user_id": user_id,
        "messages": [
            {
                "session_id": item["session_id"],
                "role": item["role"],
                "content": item["content"],
                "created_at": item["created_at"],
            }
            for item in recent_messages
        ],
        "latest_session_summary": latest_session["text"] if latest_session else None,
        "lifetime_summary": lifetime["text"] if lifetime else None,
        "episodes": [
            {
                "session_id": item["session_id"],
                "fact": item["fact"],
                "importance": item["importance"],
                "created_at": item["created_at"],
            }
            for item in recent_episodes
        ],
    }


@router.get("/aggregate/{user_id}")
def get_aggregate(user_id: str):
    daily_counts = list(
        messages_collection.aggregate(
            [
                {"$match": {"user_id": user_id}},
                {
                    "$group": {
                        "_id": {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$created_at",
                                "timezone": "UTC",
                            }
                        },
                        "message_count": {"$sum": 1},
                    }
                },
                {"$sort": {"_id": 1}},
            ]
        )
    )

    recent_summaries = list(
        summaries_collection.find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(5)
    )

    return {
        "user_id": user_id,
        "daily_message_counts": [
            {"date": item["_id"], "message_count": item["message_count"]}
            for item in daily_counts
        ],
        "recent_summaries": [
            {
                "scope": item["scope"],
                "session_id": item.get("session_id"),
                "text": item["text"],
                "created_at": item["created_at"],
            }
            for item in recent_summaries
        ],
    }