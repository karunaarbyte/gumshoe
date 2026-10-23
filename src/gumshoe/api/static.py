"""Serve the built UI from the API's origin, with a single-page-app fallback.

One catch-all route, added after every API route so those win. It never matches a path under
`/api` (any method): those fall through to the router's own 404, exactly as without the UI. Any
other path answers GET and HEAD only: a file inside the build, a 404 for a missing file (a last
segment with a dot), or `index.html` for everything else (the client-side routes).
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from starlette.exceptions import HTTPException
from starlette.routing import Match, Route
from starlette.types import Scope

# The hashed build files never change under one name; index.html names them, so it revalidates.
INDEX_CACHE = "no-cache"
ASSET_CACHE = "public, max-age=31536000, immutable"


def file_inside(root: Path, wanted: str) -> Path | None:
    """`wanted` as a file strictly inside `root` (an already resolved directory), with symlinks
    resolved before the check; else None. Never raises for a strange name."""
    if not wanted or "\\" in wanted or "\x00" in wanted:
        return None
    try:
        candidate = (root / wanted).resolve()
        candidate.relative_to(root)  # absolute paths and `..` land outside: ValueError
        return candidate if candidate != root and candidate.is_file() else None
    except (OSError, ValueError):  # a name too long, a symlink loop, ...
        return None


def _is_api(path: str) -> bool:
    return path == "api" or path.startswith("api/")


def _looks_like_a_file(path: str) -> bool:
    return "." in path.rsplit("/", 1)[-1]


class _UiRoute(Route):
    """A route that does not exist for `/api` paths, whatever the method, so a POST there is the
    plain 404 rather than this route's 405."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        match, child = super().matches(scope)
        if match is not Match.NONE and _is_api(child["path_params"]["path"]):
            return Match.NONE, {}
        return match, child


def mount_ui(app: FastAPI, dist: Path) -> bool:
    """Serve `dist` at `/`; False, with nothing added, when `dist/index.html` does not exist.
    Call it after every other route is registered."""
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file():
        return False

    def serve(request: Request) -> Response:
        path: str = request.path_params["path"]
        found = file_inside(root, path)
        if found is not None and found != index:
            cache = ASSET_CACHE if path.startswith("assets/") else INDEX_CACHE
            return FileResponse(found, headers={"cache-control": cache})
        if _looks_like_a_file(path) and found != index:
            raise HTTPException(404)  # the app's handler: the same answer as any unknown path
        return FileResponse(index, headers={"cache-control": INDEX_CACHE})

    # GET also answers HEAD (Starlette adds it), and FileResponse then sends no body.
    app.router.routes.append(
        _UiRoute("/{path:path}", serve, methods=["GET"], include_in_schema=False)
    )
    return True
