"""
FastAPI application for astra-web.

Serves the vanilla frontend and a small JSON/streaming API that proxies the
standalone ASTRA core. There is no agent logic here — everything is delegated to
``astra_service.AstraService``.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .astra_service import FRONTEND_DIR, get_service


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


@app.get("/api/health")
def health():
    service = get_service()
    return {
        "status": "ok",
        "model": service.model_name,
        "session_id": service.current_session(),
    }


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
