import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)

DB_PATH = REPORTS / "part3_rel.db"
DB_URL = f"sqlite:///{DB_PATH.as_posix()}"
engine = create_engine(DB_URL)


def setup():
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS s1339_rel (
                id TEXT PRIMARY KEY,
                affected_quantity INTEGER NOT NULL,
                data_version INTEGER NOT NULL
            )
        """))

        existing = connection.execute(
            text("SELECT id FROM s1339_rel WHERE id = :id"),
            {"id": "STALE001"},
        ).first()

        if existing:
            raise RuntimeError(
                "STALE001 already exists. Setup was already performed. "
                "Do not reset it while a demonstration is running."
            )

        connection.execute(
            text("""
                INSERT INTO s1339_rel
                    (id, affected_quantity, data_version)
                VALUES (:id, :quantity, :version)
            """),
            {"id": "STALE001", "quantity": 120, "version": 1},
        )

    print("Created test record STALE001: quantity=120, version=1")
    print("Database URL:", DB_URL)
    print("Record ID: STALE001")


def read_record():
    with engine.connect() as connection:
        row = connection.execute(
            text("""
                SELECT id, affected_quantity, data_version
                FROM s1339_rel
                WHERE id = :id
            """),
            {"id": "STALE001"},
        ).mappings().one()

        return dict(row)


def contains_number(answer, number):
    return re.search(
        rf"(?<!\d){number}(?!\d)",
        answer,
    ) is not None


async def demonstrate():
    # Import only when running, not during database setup.
    from semantic_cache import SemanticCache
    from semantic_handler import SemanticQuestionHandler
    from semantic_demo import run_pipeline

    initial = read_record()
    if initial["affected_quantity"] != 120 or initial["data_version"] != 1:
        raise RuntimeError(
            "Expected the initial test record: quantity=120, version=1."
        )

    run_id = uuid4().hex
    question = "How many units are affected by notice STALE001?"
    caches = []

    report_path = REPORTS / f"stale_demo_{run_id}.json"
    report = {
        "database_table": "s1339_rel",
        "record_id": "STALE001",
        "question": question,
        "steps": [],
        "complete": False,
    }

    def save():
        report_path.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

    def make_handler():
        record = read_record()

        #current database version determines eligible cache entries.
        os.environ["SEMANTIC_DATA_VERSION"] = (
            f"stale-demo-{run_id}-v{record['data_version']}"
        )

        cache = SemanticCache()
        caches.append(cache)
        return SemanticQuestionHandler(cache, run_pipeline)

    async def capture(label, handler):
        response = await handler.answer(question)

        step = {
            "label": label,
            "database_record": read_record(),
            "response": response,
        }

        report["steps"].append(step)
        save()

        print(f"\n=== {label} ===")
        print(json.dumps(step, indent=2))
        return response

    try:
        handler_v1 = make_handler()

        first = await capture("1_initial_cache_miss", handler_v1)
        assert first["is_cached"] is False
        assert contains_number(first["answer"], 120)
        assert not contains_number(first["answer"], 75)

        #deliberately omit a version bump to reproduce stale caching
        with engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE s1339_rel
                    SET affected_quantity = :quantity
                    WHERE id = :id
                """),
                {"quantity": 75, "id": "STALE001"},
            )

        stale = await capture("2_stale_cache_hit", handler_v1)
        assert stale["is_cached"] is True
        assert stale["answer"] == first["answer"]
        assert read_record()["affected_quantity"] == 75

        #update the database's version marker
        with engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE s1339_rel
                    SET data_version = data_version + 1
                    WHERE id = :id
                """),
                {"id": "STALE001"},
            )

        handler_v2 = make_handler()

        fresh = await capture("3_versioned_cache_miss", handler_v2)
        assert fresh["is_cached"] is False
        assert contains_number(fresh["answer"], 75)
        assert not contains_number(fresh["answer"], 120)

        repeated = await capture("4_updated_cache_hit", handler_v2)
        assert repeated["is_cached"] is True
        assert repeated["answer"] == fresh["answer"]

        report["complete"] = True
        print("\nStale-answer and invalidation checks passed.")

    except Exception as exc:
        report["error"] = str(exc)
        raise

    finally:
        save()
        for cache in caches:
            cache.client.close()
        print("Saved report:", report_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["setup", "run"])
    args = parser.parse_args()

    if args.mode == "setup":
        setup()
    else:
        asyncio.run(demonstrate())