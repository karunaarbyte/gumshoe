"""Is the persona model server answering? Health reports it, so a stopped Ollama is not silent."""

import time
from collections.abc import Callable

import httpx

PROBE_TIMEOUT_S = 1.0


class PersonaProbe:
    """Asks the OpenAI-compatible model list, and remembers the answer for `ttl_s` seconds so a
    UI polling health does not become load on the model server."""

    def __init__(
        self,
        base_url: str,
        *,
        ttl_s: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = base_url.rstrip("/") + "/models"
        self._ttl = ttl_s
        self._transport = transport
        self._clock = clock
        self._answer: tuple[float, bool] | None = None

    async def up(self) -> bool:
        now = self._clock()
        if self._answer is not None and now - self._answer[0] < self._ttl:
            return self._answer[1]
        try:
            async with httpx.AsyncClient(
                timeout=PROBE_TIMEOUT_S, transport=self._transport
            ) as http:
                response = await http.get(self._url)
            up = response.is_success
        except httpx.HTTPError:
            up = False
        self._answer = (now, up)
        return up
