"""A TestClient that sends the Origin a browser would, so ordinary tests can write."""

from starlette.testclient import TestClient as _TestClient


class TestClient(_TestClient):
    __test__ = False  # not a test class, whatever pytest thinks of the name

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.headers.setdefault("origin", f"{self.base_url.scheme}://{self.base_url.host}")
