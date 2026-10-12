"""Local Ollama chat provider.

Wraps the ``ollama`` Python package so the agent loop sees the same normalized
:class:`~ai.providers.base.Chunk` objects as every cloud provider. The previous
implementation lived inline in ``ai/ollama.py``; this keeps the behaviour
identical while making it swappable.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

import ollama

from ai.providers.base import (
    Chunk,
    FunctionCall,
    Provider,
    ProviderError,
    ResponseMessage,
    ToolCall,
    parse_arguments,
)


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, host: Optional[str] = None, **config: Any):
        super().__init__(**config)
        self.host = host or None

    def _client(self):
        # ``ollama.chat`` reads OLLAMA_HOST from the environment; passing an
        # explicit client lets us honour ASTRA_OLLAMA_HOST too.
        if self.host:
            return ollama.Client(host=self.host)
        return None

    def stream_chat(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        think: bool = True,
    ) -> Iterator[Chunk]:
        client = self._client()
        try:
            if client is not None:
                response = client.chat(
                    model=model, messages=messages, tools=tools, think=think, stream=True
                )
            else:
                response = ollama.chat(
                    model=model, messages=messages, tools=tools, think=think, stream=True
                )
        except ollama.ResponseError as e:
            raise ProviderError(f"Model error: {getattr(e, 'error', e)}") from e
        except ConnectionError as e:
            raise ProviderError(
                "Cannot connect to Ollama. Is it running? "
                f"Try 'ollama serve' or run '/provider local_setup'. ({e})"
            ) from e
        except Exception as e:
            raise ProviderError(f"Unexpected error calling Ollama: {e}") from e

        try:
            for chunk in response:
                message = getattr(chunk, "message", None)
                content = (getattr(message, "content", "") or "") if message else ""
                thinking = (getattr(message, "thinking", "") or "") if message else ""
                tool_calls = []
                for tc in (getattr(message, "tool_calls", None) or []):
                    fn = getattr(tc, "function", None)
                    tool_calls.append(ToolCall(
                        id=getattr(tc, "id", None),
                        function=FunctionCall(
                            name=getattr(fn, "name", "tool") if fn else "tool",
                            arguments=parse_arguments(getattr(fn, "arguments", None) if fn else None),
                        ),
                    ))
                yield Chunk(ResponseMessage(content=content, thinking=thinking, tool_calls=tool_calls))
        except Exception as e:
            raise ProviderError(f"Error reading response stream: {e}") from e
