"""Are the persona models answering? Health reports it, so a stopped Ollama is not silent."""

import asyncio
import time
from collections.abc import Callable, Sequence

import httpx

PROBE_TIMEOUT_S = 1.0


class PersonaProbe:
    """Asks the OpenAI-compatible model list and is up only when every persona model is in it (a
    running server without the models still gives stock lines). The answer is kept for `ttl_s`
    seconds, and concurrent checks share one request, so a UI polling health is no load."""

    def __init__(
        self,
        base_url: str,
        models: Sequence[str],
        *,
        ttl_s: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = base_url.rstrip("/") + "/models"
        self._models = frozenset(models)
        self._ttl = ttl_s
        self._transport = transport
        self._clock = clock
        self._answer: tuple[float, bool] | None = None
        self._lock = asyncio.Lock()

    def _fresh(self) -> bool | None:
        if self._answer is not None and self._clock() - self._answer[0] < self._ttl:
            return self._answer[1]
        return None

    async def up(self) -> bool:
        if (cached := self._fresh()) is not None:
            return cached
        async with self._lock:
            if (cached := self._fresh()) is not None:  # another caller asked while we waited
                return cached
            up = await self._ask()
            self._answer = (self._clock(), up)  # stamped after the request, not before
            return up

    async def _ask(self) -> bool:
        try:
            async with httpx.AsyncClient(
                timeout=PROBE_TIMEOUT_S, transport=self._transport
            ) as http:
                response = await http.get(self._url)
            if not response.is_success:
                return False
            listed = {item["id"] for item in response.json()["data"]}
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, TypeError):
            return False
        return self._models <= listed
