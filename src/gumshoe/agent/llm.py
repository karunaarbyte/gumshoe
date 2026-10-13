"""The persona language model: a Protocol plus an Ollama (OpenAI-compatible) client.

The only agent module that imports httpx. Every failure is an `LlmError`, so the loop can fall
back to its canned line without caring why the model did not answer.
"""

from collections.abc import Sequence
from typing import Literal, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict


class LlmError(Exception):
    """The model could not be reached, timed out or answered with something unusable."""


class LlmMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant"]
    content: str


@runtime_checkable
class Llm(Protocol):
    async def complete(self, model: str, system: str, messages: Sequence[LlmMessage]) -> str: ...

    async def aclose(self) -> None: ...


class OllamaLlm:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def complete(self, model: str, system: str, messages: Sequence[LlmMessage]) -> str:
        body = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                *({"role": m.role, "content": m.content} for m in messages),
            ],
        }
        try:
            response = await self._http.post(self._url, json=body)
        except httpx.TimeoutException as exc:
            raise LlmError("the model timed out") from exc
        except httpx.TransportError as exc:
            raise LlmError("the model could not be reached") from exc
        if response.is_error:
            raise LlmError(f"the model answered HTTP {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LlmError("the model's answer had an unexpected shape") from exc
        if not isinstance(content, str):
            raise LlmError("the model's answer was not text")
        return content

    async def aclose(self) -> None:
        await self._http.aclose()
