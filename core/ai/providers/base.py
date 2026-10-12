"""
Provider abstraction for ASTRA.

A *provider* is the thin piece of the system that knows how to talk to a
particular model backend (Ollama, OpenAI, Anthropic, Gemini). Everything else —
the agent loop, tool execution, history persistence, session management — lives
in :mod:`ai.model` and is provider independent.

Providers receive ASTRA's internal, OpenAI-flavoured history and translate it to
whatever wire format their API expects. They yield normalized :class:`Chunk`
objects whose shape mirrors the Ollama SDK (``chunk.message.content``,
``chunk.message.thinking``, ``chunk.message.tool_calls[].function.name``) so the
agent loop can treat every backend identically.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional


class ProviderError(RuntimeError):
    """A user-actionable provider failure (auth, network, bad request)."""


@dataclass
class FunctionCall:
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    id: Optional[str]
    function: FunctionCall


@dataclass
class ResponseMessage:
    content: str = ""
    thinking: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)


@dataclass
class Chunk:
    """A single streamed piece of a model response."""

    message: ResponseMessage


def parse_arguments(raw: Any) -> Dict[str, Any]:
    """Best-effort coercion of a tool-call argument payload into a dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def text_chunk(text: str) -> Chunk:
    return Chunk(ResponseMessage(content=text))


def thinking_chunk(text: str) -> Chunk:
    return Chunk(ResponseMessage(thinking=text))


class Provider:
    """Base class for model backends."""

    name = "base"

    def __init__(self, **config: Any):
        self.config = config

    def stream_chat(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        think: bool = True,
    ) -> Iterator[Chunk]:  # pragma: no cover - abstract
        raise NotImplementedError


def iter_sse_data(response) -> Iterator[str]:
    """Yield the ``data:`` payloads of a streaming ``text/event-stream`` response.

    Understands the OpenAI/Gemini convention (``data:`` lines only) as well as
    Anthropic's event/data pairs. A trailing ``data: [DONE]`` terminates the
    stream. Event names are exposed by prefixing them as ``event|payload`` when
    present, otherwise the raw payload is yielded.
    """
    event = None
    for raw in response.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = raw.strip("\r")
        if not line:
            continue
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
            continue
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            return
        if event:
            yield f"{event}|{data}"
            event = None
        else:
            yield data

