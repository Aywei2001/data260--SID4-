from __future__ import annotations

import csv as csv_lib
import io
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx

from .agent import run_agent

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
MAX_BYTES = 80 * 1024 * 1024
MAX_ROWS = 1_000_000
app = FastAPI(title="PedalPlan API")
datasets: dict[str, dict] = {}


@app.exception_handler(HTTPException)
async def http_error(_request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


class RunRequest(BaseModel):
    datasetId: str
    pricingUrl: str
    scenario: str = "Typical month"
    prompt: str = ""


@app.get("/api/health")
async def health():
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen3")
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f"{base_url}/api/tags")
        models = response.json().get("models", []) if response.is_success else []
        available = any(item.get("name") == model or item.get("name", "").startswith(model + ":") for item in models)
    except Exception:
        available = False
    return {"ok": True, "modelConfigured": available}


@app.post("/api/upload")
async def upload_csv(uploaded_file: UploadFile = File(..., alias="csv")):
    raw = await uploaded_file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"CSV exceeds the {MAX_BYTES // (1024 * 1024)} MB upload limit.")
    try:
        decoded = raw.decode("utf-8-sig")
        reader = csv_lib.DictReader(io.StringIO(decoded, newline=""))
        headers = reader.fieldnames or []
        if not headers or any(not name for name in headers):
            raise ValueError("CSV must have a non-empty header row.")
        rows = []
        for row in reader:
            normalized = {key: (value if value is not None else "") for key, value in row.items() if key is not None}
            if any(str(value).strip() for value in normalized.values()):
                rows.append(normalized)
                if len(rows) > MAX_ROWS:
                    raise OverflowError(f"CSV exceeds the {MAX_ROWS:,} row limit.")
        if not rows:
            raise ValueError("The CSV has headers but no data rows.")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.") from exc
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except (csv_lib.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    dataset_id = str(uuid.uuid4())
    filename = Path(uploaded_file.filename or "uploaded.csv").name
    datasets[dataset_id] = {"rows": rows, "filename": filename, "headers": headers}
    return {"id": dataset_id, "filename": filename, "rowCount": len(rows), "headers": headers}


@app.post("/api/agent/run")
async def analyze(request: RunRequest):
    dataset = datasets.get(request.datasetId)
    if dataset is None:
        raise HTTPException(status_code=400, detail="Upload a CSV before running the agent.")
    if not request.pricingUrl.strip():
        raise HTTPException(status_code=400, detail="Enter the official pricing page URL.")
    try:
        return await run_agent(dataset, request.pricingUrl, request.scenario, request.prompt)
    except RuntimeError as exc:
        status = 503 if "not configured" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc







