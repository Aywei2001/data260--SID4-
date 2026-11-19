import json
from urllib.error import URLError
from urllib.request import urlopen
import streamlit as st
from datetime import datetime, timezone
from time import time
from pathlib import Path
from hw10_trace import DB_PATH, trace_db

METRICS_URL = "http://127.0.0.1:8440/qa/metrics"

st.set_page_config(page_title="Grocery Recall Operations")
st.title("Grocery Recall Operations")

page = st.sidebar.radio("Page", ["Summary", "Evaluation", "Trace lookup"])


@st.cache_data(ttl=5, show_spinner=False)
def load_metrics(url):
    with urlopen(url, timeout=5) as response:
        return json.load(response)


def milliseconds(value):
    return "—" if value is None else f"{value:,.2f} ms"


@st.cache_data(ttl=5, show_spinner=False)
def load_recent_requests(minutes):
    end = time()
    start = end - minutes * 60
    with trace_db() as db:
        rows = db.execute(
            """
            SELECT * FROM requests
            WHERE ended_at >= ? AND ended_at <= ?
            ORDER BY ended_at DESC
            """,
            (start, end),
        ).fetchall()
    return start, end, [dict(row) for row in rows]


@st.cache_data(ttl=5, show_spinner=False)
def load_trace(trace_id):
    with trace_db() as db:
        request = db.execute(
            "SELECT * FROM requests WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        stages = db.execute(
            """
            SELECT stage, started_at, ended_at, duration_ms, status, error
            FROM stages WHERE trace_id = ?
            ORDER BY started_at, event_id
            """,
            (trace_id,),
        ).fetchall()
    return dict(request) if request else None, [dict(row) for row in stages]


def utc_display(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(
        timespec="milliseconds"
    )


def percent(numerator, denominator):
    return f"{100 * numerator / denominator:.1f}%" if denominator else "—"


if page == "Summary":
    st.header("Summary")
    minutes = st.selectbox("Time window (minutes)", [5, 15, 60], index=1)

    if st.button("Refresh metrics"):
        load_recent_requests.clear()

    if not DB_PATH.is_file():
        st.info("Start the Q&A API to initialize request logging.")
        st.stop()

    start, end, rows = load_recent_requests(minutes)
    
    total = len(rows)
    hits = sum(row["cache_outcome"] == "hit" for row in rows)
    misses = sum(row["cache_outcome"] == "miss" for row in rows)
    errors = sum(row["http_status"] >= 400 for row in rows)
    mean_ms = sum(row["duration_ms"] for row in rows) / total if total else None

    count, hit, miss, rate = st.columns(4)
    count.metric("Completed requests", total)
    hit.metric("Cache hits", hits)
    miss.metric("Cache misses", misses)
    rate.metric("Cache hit rate", percent(hits, hits + misses))

    error_rate, latency = st.columns(2)
    error_rate.metric("HTTP error rate", percent(errors, total))
    latency.metric("Mean end-to-end latency", milliseconds(mean_ms))
    hit_rows = [
        row for row in rows
        if row["cache_outcome"] == "hit" and row["http_status"] == 200
    ]
    mean_hit_ms = (
        sum(row["duration_ms"] for row in hit_rows) / len(hit_rows)
        if hit_rows else None
    )
    st.metric("Mean successful cache-hit latency", milliseconds(mean_hit_ms))
    st.caption(
        "Cache-hit latency uses successful hits in the selected time window "
        "and ends when the API response is prepared."
    )

    st.caption(
        f"{total - hits - misses} requests had no recorded cache outcome. "
        "Hit rate uses requests with a known outcome. Error rate counts HTTP "
        "4xx and 5xx. Mean latency includes all completed API requests."
    )
    if rows:
        st.dataframe(
            [
                {
                    "trace_id": row["trace_id"],
                    "completed_at": utc_display(row["ended_at"]),
                    "cache": row["cache_outcome"],
                    "http_status": row["http_status"],
                }
                for row in rows
            ],
            hide_index=True,
        )

elif page == "Evaluation":
    st.header("Evaluation")
    reports_dir = Path(__file__).resolve().parents[1] / "reports" / "hw10"
    reports_by_id = {}

    for folder in (
        reports_dir / "raw" / "evaluations",
        reports_dir / "evaluations",
    ):
        for path in folder.glob("*.json"):
            reports_by_id[path.stem] = path

    files = sorted(reports_by_id.values(), key=lambda path: path.stem)

    if not files:
        st.info("Run the Part 2 evaluator to generate a score report.")
    else:
        selected = st.selectbox("Case trace ID", files, format_func=lambda p: p.stem)
        result = json.loads(selected.read_text(encoding="utf-8"))

        st.write(result["question"])
        st.caption(f"Judge: {result['judge']['model']} · Scores on a 1–5 scale")
        st.dataframe(
            [
                {"Criterion": name, "Score": round(item["score_1_to_5"], 2),
                 "Reason": item["reason"]}
                for name, item in result["scores"].items()
            ],
            hide_index=True,
        )
        st.metric("Final minus draft", f"{result['final_minus_draft']:+.2f}")
        st.write(result["interpretation"])

        with st.expander("Writer draft and Reviewer answer"):
            st.text(result["draft"])
            st.text(result["final_answer"])

    st.subheader("Judge validation")

    validation_path = (
        Path(__file__).resolve().parents[1]
        / "reports"
        / "hw10"
        / "raw"
        / "judge_validation"
        / "judge_validation_4d276abead67.json"
    )

    if not validation_path.is_file():
        st.info("The saved judge-validation report is missing.")
    else:
        validation_report = json.loads(validation_path.read_text(encoding="utf-8"))

        if not validation_report.get("complete"):
            st.warning("The judge-validation report is incomplete.")
        else:
            summary = validation_report["summary"]
            repeat = summary["repeatability"]
            judge = validation_report["judge"]
            rho = summary["spearman_rho"]

            st.caption(
                f"{judge['method']} · {judge['model']} · "
                f"temperature {judge['temperature']} · "
                f"{summary['cases']} drafts × {repeat['runs']} runs"
            )

            agreement, difference = st.columns(2)
            agreement.metric(
                "Spearman correlation", f"{rho:.4f}" if rho is not None else "Undefined"
            )
            difference.metric(
                "Mean absolute difference",
                f"{summary['mean_absolute_difference']:.2f} points",
            )
            st.caption(
                f"Human agreement compares human labels with judge run "
                f"{summary['agreement_run']}."
            )

            changed, average, maximum = st.columns(3)
            changed.metric(
                "Cases with a score change",
                f"{repeat['cases_with_score_change']}/{summary['cases']} "
                f"({repeat['percent_with_score_change']:.1f}%)",
            )
            average.metric(
                "Mean pairwise change",
                f"{repeat['mean_absolute_pairwise_change']:.4f} points",
            )
            maximum.metric(
                "Maximum pairwise change",
                f"{repeat['max_absolute_pairwise_change']:.2f} points",
            )
            st.caption(
                f"Repeatability uses {repeat['run_pairs_compared']} "
                "within-case run pairs on the 1–5 scale."
            )
            st.write(
                "The judge scored most drafts consistently, but its rankings "
                "showed weak agreement with the human labels. Use these scores "
                "to support human review of deployment decisions."
            )

else:
    st.header("Trace lookup")
    trace_id = st.text_input("Trace ID").strip()

    if st.button("Refresh trace"):
        load_trace.clear()

    if trace_id and DB_PATH.is_file():
        request, stages = load_trace(trace_id)

        if request:
            st.write(
                f"Cache outcome: **{request['cache_outcome']}** · "
                f"HTTP **{request['http_status']}** · "
                f"**{request['duration_ms']:.2f} ms** total"
            )
            st.caption(
                f"API received {utc_display(request['started_at'])} · "
                f"API completed {utc_display(request['ended_at'])}"
            )
            if request["error"]:
                st.error(request["error"])

        if stages:
            st.dataframe(
                [
                    {
                        **stage,
                        "started_at": utc_display(stage["started_at"]),
                        "ended_at": utc_display(stage["ended_at"]),
                        "duration_ms": round(stage["duration_ms"], 2),
                    }
                    for stage in stages
                ],
                hide_index=True,
            )
        elif request:
            st.info("No stages ran for this request.")
        else:
            st.info("No events found for this trace ID.")