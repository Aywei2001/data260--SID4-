import hashlib
import os
from uuid import uuid4

import numpy as np
import redis
from redis.commands.search.field import TagField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query
from redis.exceptions import ResponseError
from sentence_transformers import SentenceTransformer


class SemanticCache:
    def __init__(self):
        self.client = redis.Redis.from_url(
            os.environ.get(
                "SEMANTIC_REDIS_URL",
                "redis://localhost:6380/0",
            ),
            decode_responses=False,
        )
        self.client.ping()

        prefix = os.environ.get("SEMANTIC_CACHE_PREFIX", "s1339")
        self.key_prefix = f"{prefix}:semantic:"
        self.index_name = f"{prefix}:semantic_idx"

        self.data_version = os.environ.get(
            "SEMANTIC_DATA_VERSION", "v1"
        )
        self.threshold = 0.85

        self.model_name = "sentence-transformers/all-MiniLM-L6-v2"
        self.model = SentenceTransformer(self.model_name)

        #separate entries by data version and embedding model.
        self.scope = hashlib.sha256(
            f"{self.data_version}|{self.model_name}".encode("utf-8")
        ).hexdigest()

        self._create_index()

    def _create_index(self):
        fields = [
            TagField("scope"),
            VectorField(
                "embedding",
                "FLAT",
                {
                    "TYPE": "FLOAT32",
                    "DIM": 384,
                    "DISTANCE_METRIC": "COSINE",
                },
            ),
        ]

        try:
            self.client.ft(self.index_name).create_index(
                fields,
                definition=IndexDefinition(
                    prefix=[self.key_prefix],
                    index_type=IndexType.HASH,
                ),
            )
        except ResponseError as exc:
            if "index already exists" not in str(exc).lower():
                raise

    def embed(self, question: str) -> bytes:
        vector = self.model.encode(
            question,
            normalize_embeddings=True,
        )
        return np.asarray(vector, dtype=np.float32).tobytes()

    def lookup(self, embedding: bytes) -> dict:
        query = (
            Query(
                f"(@scope:{{{self.scope}}})"
                "=>[KNN 1 @embedding $vector AS distance]"
            )
            .sort_by("distance")
            .return_fields("query", "answer", "distance")
            .paging(0, 1)
            .dialect(2)
        )

        results = self.client.ft(self.index_name).search(
            query,
            query_params={"vector": embedding},
        )

        if not results.docs:
            return {
                "is_cached": False,
                "similarity_score": None,
                "answer": None,
                "matched_key": None,
                "matched_query": None,
                "matched_answer": None,
            }

        match = results.docs[0]
        similarity = max(
            -1.0,
            min(1.0, 1.0 - float(match.distance)),
        )
        is_cached = similarity >= self.threshold

        answer = match.answer
        if isinstance(answer, bytes):
            answer = answer.decode("utf-8")

        matched_query = match.query
        if isinstance(matched_query, bytes):
            matched_query = matched_query.decode("utf-8")

        matched_key = match.id
        if isinstance(matched_key, bytes):
            matched_key = matched_key.decode("utf-8")

        return {
            "is_cached": is_cached,
            "similarity_score": similarity,
            "answer": answer if is_cached else None,
            "matched_key": matched_key,
            "matched_query": matched_query,
            "matched_answer": answer,
        }

    def store(
        self,
        question: str,
        embedding: bytes,
        final_answer: str,
    ) -> str:
        key = f"{self.key_prefix}{uuid4()}"

        self.client.hset(
            key,
            mapping={
                "query": question,
                "embedding": embedding,
                "answer": final_answer,
                "data_version": self.data_version,
                "embedding_model": self.model_name,
                "scope": self.scope,
            },
        )

        return key