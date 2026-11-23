import json
import sqlite3
from contextlib import closing, contextmanager
from contextvars import ContextVar
from pathlib import Path
from time import perf_counter, time

DB_PATH = Path(__file__).resolve().with_name("hw10_traces.sqlite3")

# Each API request gets its own dictionary. Middleware and the handler share it.
current_trace = ContextVar("current_trace", default=None)


@contextmanager
def trace_db():
    with closing(sqlite3.connect(DB_PATH, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        with db:
            yield db


def init_trace_db():
    with trace_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS requests (
                trace_id TEXT PRIMARY KEY,
                started_at REAL NOT NULL,
                ended_at REAL NOT NULL,
                duration_ms REAL NOT NULL,
                http_status INTEGER NOT NULL,
                cache_outcome TEXT NOT NULL,
                error TEXT
            );

            CREATE INDEX IF NOT EXISTS requests_by_end
                ON requests(ended_at);

            CREATE TABLE IF NOT EXISTS stages (
                event_id INTEGER PRIMARY KEY,
                trace_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL NOT NULL,
                duration_ms REAL NOT NULL,
                status TEXT NOT NULL,
                error TEXT
            );

            CREATE INDEX IF NOT EXISTS stages_by_trace
                ON stages(trace_id, started_at);
        """)


def record_request(trace, started_at, elapsed_ms, http_status):
    with trace_db() as db:
        db.execute(
            """
            INSERT INTO requests
                (trace_id, started_at, ended_at, duration_ms,
                 http_status, cache_outcome, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace["trace_id"],
                started_at,
                time(),
                elapsed_ms,
                http_status,
                trace["cache_outcome"],
                trace.get("error")
                or (f"HTTP {http_status}" if http_status >= 400 else None),
            ),
        )


@contextmanager
def trace_stage(stage, trace_id=None):
    if trace_id is None:
        trace = current_trace.get()
        trace_id = trace["trace_id"] if trace else None

    if trace_id is None:
        yield
        return

    started_at = time()
    started = perf_counter()
    error = None

    try:
        yield
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        ended_at = time()
        elapsed_ms = (perf_counter() - started) * 1000
        span = {
            "trace_id": trace_id,
            "stage": stage,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_ms": elapsed_ms,
            "status": "error" if error is not None else "ok",
            "error": error,
        }
        trace = current_trace.get()
        if stage == "cache_lookup" and trace is not None:
            span["cache_outcome"] = trace.get("cache_outcome", "unknown")

        print(json.dumps(span), flush=True)
        with trace_db() as db:
            db.execute(
                """
                INSERT INTO stages
                    (trace_id, stage, started_at, ended_at,
                     duration_ms, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    stage,
                    started_at,
                    ended_at,
                    elapsed_ms,
                    "error" if error is not None else "ok",
                    error,
                ),
            )


def record_queue_wait(stage, record, received_at):
    try:
        payload = json.loads(record.value)
    except (ValueError, UnicodeError, TypeError):
        return

    trace_id = payload.get("correlation_id") if isinstance(payload, dict) else None
    if not isinstance(trace_id, str) or not trace_id:
        return

    timestamp_ms = record.timestamp
    error = None
    if not isinstance(timestamp_ms, (int, float)) or timestamp_ms <= 0:
        error = "Kafka record has no usable timestamp"
        published_at = received_at
    else:
        published_at = timestamp_ms / 1000
        if published_at > received_at:
            error = "Kafka timestamp is later than worker receipt"

    duration_ms = (received_at - published_at) * 1000 if error is None else 0.0
    span = {
        "trace_id": trace_id,
        "stage": f"queue_wait_{stage.lower()}",
        "started_at": published_at,
        "ended_at": received_at,
        "duration_ms": duration_ms,
        "status": "ok" if error is None else "error",
        "error": error,
    }

    with trace_db() as db:
        db.execute(
            """
            INSERT INTO stages
                (trace_id, stage, started_at, ended_at, duration_ms, status, error)
            VALUES
                (:trace_id, :stage, :started_at, :ended_at, :duration_ms, :status, :error)
            """,
            span,
        )

    print(json.dumps(span), flush=True)
