import threading
import uuid
from typing import Any, Dict, Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from main import OSINTPipelineState, run_osint_pipeline

app = FastAPI(title="OSINT Research Agent API")

_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}


# ── Request / Response models ──────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    company: str


class JobQueued(BaseModel):
    job_id: str
    status: str


# ── Background worker ──────────────────────────────────────────────────────────

def _run_pipeline(job_id: str, company: str) -> None:
    with _lock:
        _jobs[job_id]["status"] = "running"

    try:
        result: OSINTPipelineState = run_osint_pipeline(company)
        with _lock:
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["result"] = result
    except Exception as exc:
        with _lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error_log"] = str(exc)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/research", status_code=202)
def start_research(body: ResearchRequest, background_tasks: BackgroundTasks) -> JobQueued:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {"status": "queued", "result": None, "error_log": None}
    background_tasks.add_task(_run_pipeline, job_id, body.company)
    return JobQueued(job_id=job_id, status="queued")


@app.get("/research/{job_id}")
def get_research(job_id: str) -> JSONResponse:
    with _lock:
        job = _jobs.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    status = job["status"]
    payload: Dict[str, Any] = {"job_id": job_id, "status": status}

    if status == "completed" and job["result"] is not None:
        result: OSINTPipelineState = job["result"]
        payload["result"] = result.model_dump(mode="json")
    elif status == "failed":
        payload["error_log"] = job["error_log"]

    return JSONResponse(content=payload)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)
