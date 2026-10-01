"""Everything that differs between Jev and Nimble."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BackendProfile:
    name: str
    base_url: str
    model: str
    api_key: str | None = field(default=None, repr=False)

    @property
    def endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/systemone"
