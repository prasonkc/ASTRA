"""
FastAPI application for astra-web.

Serves the vanilla frontend and a small JSON/streaming API that proxies the
standalone ASTRA core. There is no agent logic here — everything is delegated to
``astra_service.AstraService``.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .astra_service import CORE_DIR, FRONTEND_DIR, get_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up the core (loads tools, resumes the last session) so the first
    # request is fast.
    get_service()
    yield


app = FastAPI(title="ASTRA Web", version="1.0.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class NewSessionRequest(BaseModel):
    title: Optional[str] = None


class SwitchRequest(BaseModel):
    session_id: str


class ProviderRequest(BaseModel):
    provider: str
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    thinking: Optional[bool] = None


class ThinkingRequest(BaseModel):
    thinking: bool


class LocalSetupRequest(BaseModel):
    model: str
    install: bool = True


@app.get("/api/files")
def serve_generated_file(path: str):
    """Serve a file ASTRA generated inside the core directory.

    The core tools resolve relative output paths against the core working
    directory (and web downloads into ``./downloads``), so every generated
    document lives under CORE_DIR. This endpoint turns those on-disk paths
    into openable/downloadable links for the web UI.
    """
    try:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = CORE_DIR / candidate
        resolved = candidate.resolve()
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")

    # Keep serving restricted to files inside the core directory; never
    # expose arbitrary host paths.
    if CORE_DIR.resolve() not in resolved.parents or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        resolved,
        filename=resolved.name,
        content_disposition_type="inline",
    )


@app.get("/api/health")
def health():
    service = get_service()
    return {
        "status": "ok",
        "model": service.model_name,
        "provider": service.provider_name,
        "session_id": service.current_session(),
    }


# --- provider configuration --------------------------------------------------
@app.get("/api/providers")
def get_providers():
    """Current provider/model plus everything the settings panel needs."""
    return get_service().get_config()


@app.post("/api/providers")
def set_provider(payload: ProviderRequest):
    """Activate a provider/model and optionally store an API key / base URL."""
    snapshot = get_service().set_provider(
        payload.provider,
        model=payload.model,
        api_key=payload.api_key,
        base_url=payload.base_url,
        thinking=payload.thinking,
    )
    return {"ok": True, "live": snapshot, "config": get_service().get_config()}


@app.post("/api/thinking")
def set_thinking(payload: ThinkingRequest):
    """Toggle reasoning ("thinking") on/off for the active model."""
    service = get_service()
    enabled = service.set_thinking(payload.thinking)
    return {"ok": True, "thinking": enabled, "config": service.get_config()}


@app.get("/api/providers/ollama/status")
def ollama_status():
    """Whether Ollama is installed/running and which models are available."""
    return get_service().local_status()


@app.post("/api/providers/ollama/setup")
def ollama_setup(payload: LocalSetupRequest):
    """Install Ollama (optional) and pull a model, streaming progress as NDJSON."""
    service = get_service()

    def event_stream():
        for event in service.stream_local_setup(payload.model, install=payload.install):
            yield json.dumps(event) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/sessions")
def list_sessions():
    service = get_service()
    return {
        "session_id": service.current_session(),
        "sessions": service.list_sessions(),
    }


@app.post("/api/sessions")
def create_session(payload: Optional[NewSessionRequest] = None):
    service = get_service()
    title = payload.title if payload else None
    return {"session_id": service.create_session(title)}


@app.post("/api/sessions/switch")
def switch_session(payload: SwitchRequest):
    service = get_service()
    if not service.switch_session(payload.session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": payload.session_id}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    service = get_service()
    if not service.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True, "session_id": service.current_session()}


@app.get("/api/sessions/{session_id}/messages")
def get_messages(session_id: str):
    service = get_service()
    return {
        "session_id": session_id,
        "messages": service.get_messages(session_id),
    }


@app.post("/api/chat")
def chat(payload: ChatRequest):
    service = get_service()
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    def event_stream():
        for event in service.stream_chat(payload.message, payload.session_id):
            yield json.dumps(event) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# --- static frontend ---------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/favicon.ico")
def favicon():
    icon = FRONTEND_DIR / "favicon.svg"
    if icon.exists():
        return FileResponse(str(icon), media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Not found")
