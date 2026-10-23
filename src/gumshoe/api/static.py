"""Serve the built UI from the API's origin, with a single-page-app fallback.

One catch-all route, added after every API route so those win. It never matches a path under
`/api` (any method): those fall through to the router's own 404, exactly as without the UI. Any
other path answers GET and HEAD only: a file inside the build, a 404 for a missing file (a last
segment with a dot) or for any dot segment (`.env`, `.git/`, `..`), or `index.html` for
everything else (the client-side routes).

A directory that looks like a source tree rather than a build (it holds a `package.json`, `.env`,
`src/` or `node_modules/`, or it is the project root or above it) is never mounted.

Files are looked up on each request: a rebuild needs no restart once `index.html` is back, but
replacing the directory while the server runs may answer a request or two with a 500.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from starlette.exceptions import HTTPException
from starlette.routing import Match, Route
from starlette.types import Scope

from gumshoe.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# The hashed build files never change under one name; index.html names them, so it revalidates.
INDEX_CACHE = "no-cache"
ASSET_CACHE = "public, max-age=31536000, immutable"
# What a source tree has and a build output does not.
SOURCE_MARKERS = ("package.json", ".env", "src", "node_modules")


def _dotted(parts: tuple[str, ...] | list[str]) -> bool:
    return any(part.startswith(".") for part in parts)


def file_inside(root: Path, wanted: str) -> Path | None:
    """`wanted` as a file strictly inside `root` (an already resolved directory), with symlinks
    resolved before the check and no dot segment on either side; else None. Never raises.
    An empty segment (a trailing slash, `//`) is refused too: one file has exactly one URL."""
    parts = wanted.split("/")
    if "\\" in wanted or "\x00" in wanted or "" in parts or _dotted(parts):
        return None
    try:
        candidate = (root / wanted).resolve()
        inside = candidate.relative_to(root)  # absolute paths and `..` land outside: ValueError
        if not inside.parts or _dotted(inside.parts):  # the root, or a link to a dotfile
            return None
        return candidate if candidate.is_file() else None
    except (OSError, ValueError):  # a name too long, a symlink loop, ...
        return None


def _is_api(path: str) -> bool:
    return path == "api" or path.startswith("api/")


def _looks_like_a_file(path: str) -> bool:
    return "." in path.rsplit("/", 1)[-1]


def _source_tree(root: Path) -> bool:
    if root == PROJECT_ROOT or root in PROJECT_ROOT.parents:
        return True
    return any((root / marker).exists() for marker in SOURCE_MARKERS)


class _UiRoute(Route):
    """A route that does not exist for `/api` paths, whatever the method, so a POST there is the
    plain 404 rather than this route's 405."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        match, child = super().matches(scope)
        if match is not Match.NONE and _is_api(child["path_params"]["path"]):
            return Match.NONE, {}
        return match, child


def mount_ui(app: FastAPI, dist: Path) -> bool:
    """Serve `dist` at `/`; False, with nothing added, when `dist/index.html` does not exist or
    `dist` looks like a source tree. Call it after every other route is registered."""
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file():
        return False
    if _source_tree(root):
        logger.warning("not serving the UI from %s: it looks like a source tree, not a build", root)
        return False

    def serve(request: Request) -> Response:
        path: str = request.path_params["path"]
        if _dotted(path.split("/")):
            raise HTTPException(404)  # the app's handler: the same answer as any unknown path
        found = file_inside(root, path)
        if found is not None and found != index:
            immutable = found.relative_to(root).parts[0] == "assets"
            cache = ASSET_CACHE if immutable else INDEX_CACHE
            return FileResponse(found, headers={"cache-control": cache})
        if _looks_like_a_file(path) and found != index:
            raise HTTPException(404)
        return FileResponse(index, headers={"cache-control": INDEX_CACHE})

    # GET also answers HEAD (Starlette adds it), and FileResponse then sends no body.
    app.router.routes.append(
        _UiRoute("/{path:path}", serve, methods=["GET"], include_in_schema=False)
    )
    return True
