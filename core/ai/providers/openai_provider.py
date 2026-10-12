"""OpenAI (and OpenAI-compatible) chat provider.

Uses the plain REST API via ``requests`` so no additional SDK is required, and
so the same code can talk to any OpenAI-compatible endpoint (Azure OpenAI,
OpenRouter, Together, a local vLLM server, …) by pointing ``base_url`` at it.
"""
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


def to_openai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Translate ASTRA's internal history into OpenAI chat messages.

    Tool results are associated with the ``tool_call_id`` of the assistant turn
    that requested them. IDs are preserved across reloads (they are stored with
    the assistant message); when a backend did not provide one we synthesize a
    stable id so the request stays valid.
    """
    out: List[Dict[str, Any]] = []
    pending_ids: List[str] = []

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            out.append({"role": "system", "content": msg.get("content") or ""})
        elif role == "user":
            out.append({"role": "user", "content": msg.get("content") or ""})
        elif role == "assistant":
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []
            entry: Dict[str, Any] = {"role": "assistant", "content": content}
            pending_ids = []
            if tool_calls:
                converted = []
                for i, tc in enumerate(tool_calls):
                    fn = (tc or {}).get("function", {}) if isinstance(tc, dict) else {}
                    name = fn.get("name") or "tool"
                    args = fn.get("arguments")
                    if not isinstance(args, str):
                        args = json.dumps(args if args is not None else {})
                    call_id = (tc or {}).get("id") or f"call_{len(out)}_{i}"
                    pending_ids.append(call_id)
                    converted.append({
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": args},
                    })
                entry["tool_calls"] = converted
                if not content:
                    entry["content"] = None
            out.append(entry)
        elif role == "tool":
            call_id = pending_ids.pop(0) if pending_ids else "call_unknown"
            out.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": msg.get("content") or "",
            })
    return out


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        timeout: int = DEFAULT_TIMEOUT,
        **config: Any,
    ):
        super().__init__(**config)
        self.api_key = api_key or ""
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
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
                "OpenAI API key is not set. Run '/provider openai' (terminal) or "
                "open Settings in the web app to add it."
            )

        payload: Dict[str, Any] = {
            "model": model,
            "messages": to_openai_messages(messages),
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = f"{self.base_url}/chat/completions"
        try:
            response = requests.post(
                url, headers=self._headers(), json=payload, stream=True, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach OpenAI at {url}: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(_http_error("OpenAI", response))

        tool_buf: Dict[int, Dict[str, Any]] = {}
        try:
            for data in iter_sse_data(response):
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("error"):
                    err = obj["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise ProviderError(f"OpenAI error: {msg}")

                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if reasoning:
                    yield Chunk(ResponseMessage(thinking=reasoning))
                content = delta.get("content")
                if content:
                    yield Chunk(ResponseMessage(content=content))

                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = tool_buf.setdefault(idx, {"id": None, "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]
        finally:
            response.close()

        if tool_buf:
            calls = []
            for idx in sorted(tool_buf):
                slot = tool_buf[idx]
                calls.append(ToolCall(
                    id=slot["id"],
                    function=FunctionCall(
                        name=slot["name"] or "tool",
                        arguments=parse_arguments(slot["args"]),
                    ),
                ))
            yield Chunk(ResponseMessage(tool_calls=calls))


def _http_error(provider: str, response) -> str:
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                detail = err.get("message") or ""
            elif isinstance(err, str):
                detail = err
            else:
                detail = body.get("message") or ""
    except Exception:
        detail = (response.text or "")[:300]
    return f"{provider} request failed ({response.status_code}): {detail}".strip()
