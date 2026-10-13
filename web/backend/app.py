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
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .astra_service import (
    CORE_DIR,
    FRONTEND_DIR,
    clear_browser_context,
    command_poll_payload,
    get_browser_context,
    get_service,
    register_browser_message_handler,
    run_browser_message,
    set_browser_context,
    submit_command_result,
)
from .voice_api import get_voice_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up the core (loads tools, resumes the last session) so the first
    # request is fast, then let the browser extension popup talk to it.
    get_service()
    register_browser_message_handler()
    yield


app = FastAPI(title="ASTRA Web", version="1.1.0", lifespan=lifespan)

# The ASTRA Firefox extension runs on its own origin and POSTs page context
# here, so allow cross-origin requests. The server only ever binds to
# 127.0.0.1, so this stays local.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class MousePosition(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    pageX: Optional[float] = None
    pageY: Optional[float] = None


class BrowserContextPayload(BaseModel):
    """A page snapshot pushed by the ASTRA browser extension."""

    url: Optional[str] = None
    title: Optional[str] = None
    html: Optional[str] = None
    text: Optional[str] = None
    selection: Optional[str] = None
    mouse: Optional[MousePosition] = None
    timestamp: Optional[float] = None


class CommandResultPayload(BaseModel):
    """The extension's outcome for a claimed browser command."""

    ok: bool = True
    result: Optional[Any] = None
    error: Optional[str] = None


class BrowserMessagePayload(BaseModel):
    """A chat message sent from the ASTRA browser extension popup."""

    message: str = ""


class SpeakRequest(BaseModel):
    """Text the browser voice mode asks the server to synthesise."""

    text: str = ""


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


# --- browser context (ASTRA Firefox extension) -------------------------------
@app.post("/api/browser/context")
def put_browser_context(payload: BrowserContextPayload):
    """Receive a page snapshot from the ASTRA browser extension.

    The stored snapshot is what the core's ``browser_context`` tool reads, so the
    agent can explain or reason about the page the user is viewing.
    """
    data = payload.model_dump(exclude_none=True)
    stored = set_browser_context(data)
    return {"ok": True, "received_at": stored.get("received_at")}


@app.get("/api/browser/context")
def read_browser_context():
    """Return the latest stored page snapshot (for debugging / status)."""
    return {"context": get_browser_context()}


@app.delete("/api/browser/context")
def delete_browser_context():
    """Forget the stored page snapshot (the extension disconnected)."""
    clear_browser_context()
    return {"ok": True}


@app.get("/api/browser/commands")
def poll_browser_commands():
    """Hand the extension the next queued browser command, if any.

    The extension polls this endpoint while integration is on; each poll returns
    at most one ``{id, name, arguments}`` command (or ``command: null``).
    """
    return command_poll_payload()


@app.post("/api/browser/commands/{command_id}/result")
def browser_command_result(command_id: int, payload: CommandResultPayload):
    """Register the extension's result for a claimed browser command.

    Wakes the tool that is blocking on the command and lets it return to the
    model. Returns 404 when the command is unknown or already finished.
    """
    accepted = submit_command_result(
        command_id, ok=payload.ok, result=payload.result, error=payload.error
    )
    if not accepted:
        raise HTTPException(status_code=404, detail="Command not found or already finished")
    return {"accepted": True}


@app.post("/api/browser/message")
def browser_message(payload: BrowserMessagePayload):
    """Run one chat turn for the ASTRA Firefox extension popup.

    Shares the web UI's conversation, so a message sent from the browser appears
    in the same session. Blocks until the turn finishes.
    """
    return run_browser_message(payload.message)


# --- voice mode (browser microphone + local speech layer) --------------------
@app.get("/api/voice/status")
def voice_status():
    """Whether the local speech layer (whisper.cpp / piper) is ready.

    The browser does the recording and playback, so this only reports whether
    transcription is available (and, separately, whether replies can be spoken).
    """
    return get_voice_service().status()


@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request, format: str = "webm"):
    """Transcribe one recorded clip and return its text.

    The browser voice mode records a short utterance and POSTs the raw audio as
    the request body (``Content-Type: audio/webm`` and friends). Any container
    ffmpeg reads is fine — the clip is normalised to 16 kHz mono WAV before
    whisper. The reply is ``{ok, text}``.
    """
    data = await request.body()
    suffix = "." + (format or "webm").lstrip(".")
    try:
        text = get_voice_service().transcribe_bytes(data, suffix=suffix)
    except Exception as exc:  # noqa: BLE001 - surfaced to the client as 503
        raise HTTPException(status_code=503, detail=str(exc))
    return {"ok": True, "text": text}


@app.post("/api/voice/speak")
def voice_speak(payload: SpeakRequest):
    """Synthesise a reply to speech and stream it back as a WAV."""
    try:
        wav = get_voice_service().synthesize_wav(payload.text)
    except Exception as exc:  # noqa: BLE001 - surfaced to the client
        raise HTTPException(status_code=503, detail=str(exc))
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


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
