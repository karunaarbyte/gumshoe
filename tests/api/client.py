"""A TestClient that sends the Origin a browser would, so ordinary tests can write.

Its default base is `http://localhost`, not Starlette's `http://testserver`: in local mode the
Origin check accepts the request's own `scheme://Host` only for a loopback host (DNS rebinding).
"""

from starlette.testclient import TestClient as _TestClient


class TestClient(_TestClient):
    __test__ = False  # not a test class, whatever pytest thinks of the name

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("base_url", "http://localhost")
        super().__init__(*args, **kwargs)
        self.headers.setdefault("origin", f"{self.base_url.scheme}://{self.base_url.host}")
