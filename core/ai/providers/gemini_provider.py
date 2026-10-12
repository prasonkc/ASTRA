"""Google Gemini chat provider (Generative Language API, streaming)."""
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

# Schema keywords Gemini's function declarations understand. Anything else
# (``$schema``, ``additionalProperties``, ``title`` …) makes the API reject the
# request, so we strip it.
_GEMINI_SCHEMA_KEYS = {
    "type", "format", "description", "nullable", "enum", "items", "properties",
    "required", "minimum", "maximum", "minItems", "maxItems", "minLength",
    "maxLength", "pattern",
}


def sanitize_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    out: Dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _GEMINI_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            out["properties"] = {k: sanitize_schema(v) for k, v in value.items()}
        elif key == "items":
            out["items"] = sanitize_schema(value)
        else:
            out[key] = value
    if "type" not in out and "properties" in out:
        out["type"] = "object"
    return out


def to_gemini(messages: List[Dict[str, Any]]) -> tuple:
    """Translate ASTRA's internal history into ``(system, contents)``."""
    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    pending_names: List[str] = []

    def append(role: str, parts: List[Dict[str, Any]]) -> None:
        if not parts:
            return
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": parts})

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            system_parts.append(msg.get("content") or "")
        elif role == "user":
            append("user", [{"text": msg.get("content") or ""}])
        elif role == "assistant":
            parts: List[Dict[str, Any]] = []
            if msg.get("content"):
                parts.append({"text": msg["content"]})
            pending_names = []
            for tc in msg.get("tool_calls") or []:
                fn = (tc or {}).get("function", {}) if isinstance(tc, dict) else {}
                name = fn.get("name") or "tool"
                pending_names.append(name)
                parts.append({
                    "functionCall": {
                        "name": name,
                        "args": parse_arguments(fn.get("arguments")),
                    }
                })
            append("model", parts)
        elif role == "tool":
            name = pending_names.pop(0) if pending_names else "tool"
            append("user", [{
                "functionResponse": {
                    "name": name,
                    "response": {"result": msg.get("content") or ""},
                }
            }])

    return ("\n\n".join(p for p in system_parts if p), contents)


def to_gemini_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    declarations = []
    for tool in tools or []:
        fn = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = fn.get("name")
        if not name:
            continue
        decl: Dict[str, Any] = {"name": name, "description": fn.get("description") or ""}
        params = fn.get("parameters")
        if params:
            decl["parameters"] = sanitize_schema(params)
        declarations.append(decl)
    return [{"functionDeclarations": declarations}] if declarations else []


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://generativelanguage.googleapis.com",
        timeout: int = DEFAULT_TIMEOUT,
        **config: Any,
    ):
        super().__init__(**config)
        self.api_key = api_key or ""
        self.base_url = (base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        self.timeout = timeout

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
                "Gemini API key is not set. Run '/provider gemini' (terminal) or "
                "open Settings in the web app to add it."
            )

        system, contents = to_gemini(messages)
        payload: Dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        gemini_tools = to_gemini_tools(tools)
        if gemini_tools:
            payload["tools"] = gemini_tools

        url = f"{self.base_url}/v1beta/models/{model}:streamGenerateContent"
        params = {"alt": "sse", "key": self.api_key}
        try:
            response = requests.post(
                url, params=params, json=payload, stream=True, timeout=self.timeout,
                headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach Gemini at {url}: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(_http_error("Gemini", response))

        call_index = 0
        calls: List[ToolCall] = []
        try:
            for data in iter_sse_data(response):
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("error"):
                    err = obj["error"]
                    raise ProviderError(f"Gemini error: {err.get('message') if isinstance(err, dict) else err}")

                for candidate in obj.get("candidates") or []:
                    content = candidate.get("content") or {}
                    for part in content.get("parts") or []:
                        if "functionCall" in part:
                            fc = part["functionCall"] or {}
                            calls.append(ToolCall(
                                id=f"call_{call_index}",
                                function=FunctionCall(
                                    name=fc.get("name") or "tool",
                                    arguments=parse_arguments(fc.get("args")),
                                ),
                            ))
                            call_index += 1
                        elif part.get("text"):
                            if part.get("thought"):
                                yield Chunk(ResponseMessage(thinking=part["text"]))
                            else:
                                yield Chunk(ResponseMessage(content=part["text"]))
        finally:
            response.close()

        if calls:
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
