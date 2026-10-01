"""HTTP client for the System One API shared by Jev and Nimble."""

from collections.abc import Mapping
from types import TracebackType

import httpx
from pydantic import ValidationError

from gumshoe.decider.errors import (
    DeciderAPIError,
    DeciderConnectionError,
    DeciderParseError,
)
from gumshoe.decider.models import DecisionRequest, DecisionResult, Question
from gumshoe.decider.profile import BackendProfile


class SystemOneClient:
    def __init__(
        self,
        profile: BackendProfile,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = profile.name
        self._profile = profile
        self._timeout = timeout
        headers = {}
        if profile.api_key:
            headers["Authorization"] = f"Bearer {profile.api_key}"
        self._http = httpx.AsyncClient(headers=headers, timeout=timeout, transport=transport)

    async def decide(
        self, state: str, questions: Mapping[str, Question], *, node: str = "adhoc"
    ) -> DecisionResult:
        # `node` labels the pipeline stage for wrappers (stats); the wire request has no use for it.
        request = DecisionRequest(
            model=self._profile.model, state=state, questions=dict(questions)
        )
        url = self._profile.endpoint
        try:
            response = await self._http.post(url, json=request.model_dump(mode="json"))
        except httpx.TimeoutException as exc:
            raise DeciderConnectionError(
                self.name, f"timed out after {self._timeout:g}s calling {url}"
            ) from exc
        except httpx.TransportError as exc:
            raise DeciderConnectionError(
                self.name, f"cannot reach {url} ({type(exc).__name__})"
            ) from exc

        if response.is_error:
            raise DeciderAPIError(self.name, response.status_code, response.text)

        try:
            return DecisionResult.model_validate_json(response.content)
        except ValidationError as exc:
            raise DeciderParseError(self.name, str(exc), response.text) from exc

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "SystemOneClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
