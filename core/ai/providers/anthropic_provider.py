"""Anthropic Claude chat provider (Messages API, streaming)."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional

import requests

from ai.providers.base import (
    Chunk,
    FunctionCall,
    Provider,
    ProviderError,
    ResponseMessage,
    ToolCall,
    iter_sse_data,
    parse_arguments,
)

DEFAULT_TIMEOUT = 600
ANTHROPIC_VERSION = "2023-06-01"


def to_anthropic(
    messages: List[Dict[str, Any]],
) -> tuple:
    """Translate ASTRA's internal history into ``(system, messages)``.

    Anthropic needs a separate ``system`` string and strictly alternating
    user/assistant turns. Tool results are carried in ``user`` messages as
    ``tool_result`` blocks that reference the originating ``tool_use`` id.
    """
    system_parts: List[str] = []
    convo: List[Dict[str, Any]] = []
    pending_tool_ids: List[str] = []
    tool_results: List[Dict[str, Any]] = []

    def flush_tool_results() -> None:
        if tool_results:
            convo.append({"role": "user", "content": list(tool_results)})
            tool_results.clear()

    def add_user_text(text: str) -> None:
        if not text:
            return
        if convo and convo[-1]["role"] == "user":
            convo[-1]["content"].append({"type": "text", "text": text})
        else:
            convo.append({"role": "user", "content": [{"type": "text", "text": text}]})

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            system_parts.append(msg.get("content") or "")
        elif role == "user":
            flush_tool_results()
            add_user_text(msg.get("content") or "")
        elif role == "assistant":
            flush_tool_results()
            blocks: List[Dict[str, Any]] = []
            if msg.get("content"):
                blocks.append({"type": "text", "text": msg["content"]})
            pending_tool_ids = []
            for i, tc in enumerate(msg.get("tool_calls") or []):
                fn = (tc or {}).get("function", {}) if isinstance(tc, dict) else {}
                call_id = (tc or {}).get("id") or f"tool_{len(convo)}_{i}"
                pending_tool_ids.append(call_id)
                blocks.append({
                    "type": "tool_use",
                    "id": call_id,
                    "name": fn.get("name") or "tool",
                    "input": parse_arguments(fn.get("arguments")),
                })
            if blocks:
                convo.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            call_id = pending_tool_ids.pop(0) if pending_tool_ids else "tool_unknown"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": msg.get("content") or "",
            })

    flush_tool_results()
    return ("\n\n".join(p for p in system_parts if p), convo)


def to_anthropic_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for tool in tools or []:
        fn = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = fn.get("name")
        if not name:
            continue
        out.append({
            "name": name,
            "description": fn.get("description") or "",
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.anthropic.com",
        timeout: int = DEFAULT_TIMEOUT,
        max_tokens: int = 8192,
        **config: Any,
    ):
        super().__init__(**config)
        self.api_key = api_key or ""
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.timeout = timeout
        self.max_tokens = max_tokens

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "accept": "text/event-stream",
        }

    def stream_chat(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        think: bool = True,
    ) -> Iterator[Chunk]:
        if not self.api_key:
            raise ProviderError(
                "Anthropic API key is not set. Run '/provider anthropic' (terminal) "
                "or open Settings in the web app to add it."
            )

        system, convo = to_anthropic(messages)
        if not convo:
            convo = [{"role": "user", "content": [{"type": "text", "text": ""}]}]

        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": convo,
            "stream": True,
        }
        if system:
            payload["system"] = system
        conv_tools = to_anthropic_tools(tools)
        if conv_tools:
            payload["tools"] = conv_tools

        url = f"{self.base_url}/v1/messages"
        try:
            response = requests.post(
                url, headers=self._headers(), json=payload, stream=True, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach Anthropic at {url}: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(_http_error("Anthropic", response))

        tool_buf: Dict[int, Dict[str, Any]] = {}
        calls: List[ToolCall] = []

        def materialize() -> List[ToolCall]:
            ordered = []
            for idx in sorted(tool_buf):
                slot = tool_buf[idx]
                ordered.append(ToolCall(
                    id=slot.get("id"),
                    function=FunctionCall(
                        name=slot.get("name") or "tool",
                        arguments=parse_arguments(slot.get("args") or "{}"),
                    ),
                ))
            return ordered

        try:
            for payload_str in iter_sse_data(response):
                event, _, data = payload_str.partition("|")
                if not data:
                    event, data = "", event
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                etype = obj.get("type") or event

                if etype == "error":
                    err = obj.get("error") or {}
                    raise ProviderError(f"Anthropic error: {err.get('message') or err}")
                if etype == "content_block_start":
                    block = obj.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        tool_buf[obj.get("index", 0)] = {
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "args": "",
                        }
                elif etype == "content_block_delta":
                    delta = obj.get("delta") or {}
                    dtype = delta.get("type")
                    if dtype == "text_delta" and delta.get("text"):
                        yield Chunk(ResponseMessage(content=delta["text"]))
                    elif dtype == "thinking_delta" and delta.get("thinking"):
                        yield Chunk(ResponseMessage(thinking=delta["thinking"]))
                    elif dtype == "input_json_delta":
                        slot = tool_buf.setdefault(obj.get("index", 0), {"id": None, "name": "tool", "args": ""})
                        slot["args"] += delta.get("partial_json") or ""
        finally:
            response.close()

        if tool_buf:
            calls = materialize()
            yield Chunk(ResponseMessage(tool_calls=calls))


def _http_error(provider: str, response) -> str:
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                detail = err.get("message") or ""
            else:
                detail = body.get("message") or ""
    except Exception:
        detail = (response.text or "")[:300]
    return f"{provider} request failed ({response.status_code}): {detail}".strip()
