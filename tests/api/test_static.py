import asyncio
import os

import pytest

from gumshoe.api import create_app
from gumshoe.api.static import ASSET_CACHE, INDEX_CACHE, file_inside, mount_ui
from gumshoe.config import PROJECT_ROOT, Settings
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import fake_factory

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'"
)
INDEX = "<!doctype html><title>Gumshoe</title><div id=root></div>"
NOT_FOUND = {"code": "not_found", "message": "Not Found"}
TOKEN = "t" * 40
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
# Unknown API paths, and the admin-gated ones (which must look exactly like them without the token)
API_PATHS = [
    "/api/nothing-here",
    "/api",
    "/api/",
    "/api/assets/app-abc123.js",
    "/api/index.html",
    "/api/admin/usage",
    "/api/admin/usage/",
    "/api/decisions",
    "/api/decisions/abc",
    "/api/stats/decisions",
]


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "assets" / "app-abc123.js").write_text("console.log(1)")
    (root / "assets" / "app-abc123.css").write_text("body{}")
    (tmp_path / "secret.txt").write_text("top secret")
    return root


def app_for(tmp_path, dist, **settings):
    async def up():
        return True

    store = SqliteStatsStore(tmp_path / "decisions.db")
    return create_app(
        store,
        make_service=fake_factory(Script()),
        settings=Settings(_env_file=None, ui_dist=dist, **settings),
        personas_up=up,
    )


def client_for(tmp_path, dist, **settings):
    return TestClient(app_for(tmp_path, dist, **settings))


def shape(response):
    """What a probe can see: status, body and headers."""
    return response.status_code, response.content, sorted(response.headers.items())


def raw_get(app, path):
    """GET `path` exactly as written: the HTTP client would normalise `..` away before sending."""
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8", "surrogateescape"),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body


def test_the_index_is_served_at_the_root_and_must_revalidate(tmp_path, dist):
    with client_for(tmp_path, dist) as client:
        r = client.get("/")
    assert r.status_code == 200 and "<title>Gumshoe</title>" in r.text
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["content-security-policy"]


def test_assets_are_cached_for_a_year(tmp_path, dist):
    with client_for(tmp_path, dist) as client:
        r = client.get("/assets/app-abc123.js")
    assert r.status_code == 200 and r.text == "console.log(1)"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_an_unknown_path_falls_back_to_the_index(tmp_path, dist):
    with client_for(tmp_path, dist) as client:
        r = client.get("/some/client/route")
    assert r.status_code == 200 and "<title>Gumshoe</title>" in r.text


def test_api_paths_never_return_the_index(tmp_path, dist):
    with client_for(tmp_path, dist) as client:
        r = client.get("/api/nope")
        assert (r.status_code, r.json()["code"]) == (404, "not_found")
        assert client.get("/api/meta").status_code == 200
        assert client.post("/api/nothing", json={}).status_code in (403, 404, 405)


@pytest.mark.parametrize(
    "path",
    [
        "/assets/../../secret.txt",
        "/%2e%2e/secret.txt",
        "/..%2fsecret.txt",
        "//etc/passwd",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/\\..\\secret.txt",
    ],
)
def test_nothing_outside_dist_is_ever_served(tmp_path, dist, path):
    with client_for(tmp_path, dist) as client:
        r = client.get(path)
    assert "top secret" not in r.text and "root:" not in r.text


def test_a_symlink_out_of_dist_is_not_followed(tmp_path, dist):
    os.symlink(tmp_path / "secret.txt", dist / "leak.txt")
    with client_for(tmp_path, dist) as client:
        r = client.get("/leak.txt")
    assert "top secret" not in r.text


def test_without_a_build_the_api_behaves_as_before(tmp_path):
    with client_for(tmp_path, tmp_path / "missing") as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/meta").status_code == 200


def test_only_get_and_head_serve_pages(tmp_path, dist):
    with client_for(tmp_path, dist) as client:
        assert client.post("/", json={}).status_code in (403, 405)


# --- the API's own 404 is untouched (any method, admin off or a wrong token) ---


@pytest.mark.parametrize(
    "settings, headers",
    [({}, {}), ({"admin_token": TOKEN}, {"authorization": "Bearer " + "x" * 40})],
    ids=["admin-off", "wrong-token"],
)
def test_api_paths_answer_exactly_as_without_the_ui(tmp_path, dist, settings, headers):
    with (
        client_for(tmp_path, dist, **settings) as ui_on,
        client_for(tmp_path, tmp_path / "no-ui", **settings) as ui_off,
    ):
        for method in METHODS:
            unknown = shape(ui_off.request(method, "/api/nothing-here", headers=headers))
            assert unknown[0] == 404
            if method != "HEAD":
                assert unknown[1] == b'{"code":"not_found","message":"Not Found"}'
            for path in API_PATHS:
                on = shape(ui_on.request(method, path, headers=headers))
                off = shape(ui_off.request(method, path, headers=headers))
                assert on == off == unknown, (method, path)


def test_the_right_token_still_reaches_the_admin_routes_with_the_ui_on(tmp_path, dist):
    with client_for(tmp_path, dist, admin_token=TOKEN) as client:
        r = client.get("/api/admin/usage", headers={"authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and "jev_tokens_today" in r.json()


def test_api_routes_win_over_the_ui(tmp_path, dist):
    with client_for(tmp_path, dist) as client:
        assert client.get("/api/meta").json()["default_preset"] == "standard"
        assert client.get("/api/health").json()["game"] == "on"


@pytest.mark.parametrize("path", ["/assets/x.js", "/missing.png", "/assets/app-abc123.js.map"])
def test_a_missing_file_is_a_real_404_not_the_index(tmp_path, dist, path):
    with client_for(tmp_path, dist) as client:
        r = client.get(path)
        unknown = client.get("/api/nothing-here")
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    assert shape(r) == shape(unknown)


def test_the_page_for_a_route_is_the_same_as_the_root(tmp_path, dist):
    with client_for(tmp_path, dist) as client:
        root = client.get("/")
        for path in ("/game/abc", "/stats", "/index.html", "/assets", "/assets/"):
            r = client.get(path)
            assert (r.status_code, r.text) == (root.status_code, root.text) == (200, INDEX), path
            assert r.headers["cache-control"] == INDEX_CACHE


def test_content_types(tmp_path, dist):
    with client_for(tmp_path, dist) as client:
        assert client.get("/").headers["content-type"].startswith("text/html")
        assert (
            client.get("/assets/app-abc123.js")
            .headers["content-type"]
            .startswith("text/javascript")
        )
        assert client.get("/assets/app-abc123.css").headers["content-type"].startswith("text/css")


@pytest.mark.parametrize("path", ["/", "/some/route", "/assets/app-abc123.js"])
def test_the_ui_carries_the_security_headers(tmp_path, dist, path):
    with client_for(tmp_path, dist) as client:
        r = client.get(path)
    assert r.headers["content-security-policy"] == CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "same-origin"
    assert r.headers["x-frame-options"] == "DENY"


def test_hsts_on_the_ui_in_public_mode(tmp_path, dist):
    from pydantic import SecretStr

    public = {"public_origin": "https://g.example.com", "session_secret": SecretStr("s" * 32)}
    with client_for(tmp_path, dist, **public) as client:
        assert client.get("/").headers["strict-transport-security"] == "max-age=31536000"


@pytest.mark.parametrize(
    "path, cache",
    [("/", INDEX_CACHE), ("/some/route", INDEX_CACHE), ("/assets/app-abc123.js", ASSET_CACHE)],
)
def test_head_answers_like_get_without_a_body(tmp_path, dist, path, cache):
    with client_for(tmp_path, dist) as client:
        got = client.get(path)
        head = client.head(path)
    assert head.status_code == 200 and head.content == b""
    assert head.headers["cache-control"] == cache
    assert head.headers["content-length"] == got.headers["content-length"]
    assert head.headers["content-type"] == got.headers["content-type"]


def test_other_methods_on_ui_paths_are_refused(tmp_path, dist):
    with client_for(tmp_path, dist) as client:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            for path in ("/", "/some/route", "/assets/app-abc123.js"):
                r = client.request(method, path)
                assert r.status_code == 405, (method, path)
                assert b"Gumshoe" not in r.content and b"console" not in r.content


# --- containment ---


@pytest.mark.parametrize(
    "path",
    [
        "/../secret.txt",
        "/assets/../../secret.txt",
        "/assets/../../../../../../etc/passwd",
        "//etc/passwd",
        "/" + str(os.path.abspath("/etc/passwd")),
        "/..\\secret.txt",
        "/assets\\..\\..\\secret.txt",
        "/index.html\x00.js",
        "/assets/app-abc123.js\x00",
        "/" + "x" * 5000,
        "/" + "x" * 300 + ".js",
    ],
)
def test_raw_traversal_never_leaves_dist(tmp_path, dist, path):
    status, body = raw_get(app_for(tmp_path, dist), path)
    assert b"top secret" not in body and b"root:" not in body
    assert status in (200, 404) and (status == 404 or body == INDEX.encode())


@pytest.mark.parametrize(
    "path",
    [
        "/..%2f..%2fetc/passwd",
        "/..%2fsecret.txt",
        "/%2e%2e/",
        "/%2e%2e/secret.txt",
        "/%2Fetc%2Fpasswd",
        "/%5c..%5csecret.txt",
        "/assets/..%5c..%5csecret.txt",
        "/x%00.txt",
        "/assets/app-abc123.js%00",
    ],
)
def test_encoded_traversal_never_leaves_dist(tmp_path, dist, path):
    with client_for(tmp_path, dist) as client:
        r = client.get(path)
    assert b"top secret" not in r.content and b"root:" not in r.content
    assert r.status_code in (200, 404) and (r.status_code == 404 or r.text == INDEX)


def test_a_symlinked_directory_out_of_dist_is_not_followed(tmp_path, dist):
    os.symlink(tmp_path, dist / "out")
    with client_for(tmp_path, dist) as client:
        r = client.get("/out/secret.txt")
    assert "top secret" not in r.text and r.status_code == 404


def test_a_symlink_inside_dist_is_served(tmp_path, dist):
    os.symlink(dist / "assets" / "app-abc123.js", dist / "assets" / "alias.js")
    with client_for(tmp_path, dist) as client:
        assert client.get("/assets/alias.js").text == "console.log(1)"


@pytest.mark.parametrize(
    "wanted",
    [
        "",
        "../secret.txt",
        "assets/../../secret.txt",
        "/etc/passwd",
        str(os.path.abspath("/etc/passwd")),
        "..\\secret.txt",
        "index.html\x00",
        "x" * 5000,
        "assets",
        "assets/app-abc123.js/",
        "assets//app-abc123.js",
        ".env",
        "assets/.hidden",
        "a/./b",
    ],
)
def test_file_inside_refuses_anything_but_a_file_in_root(dist, wanted):
    assert file_inside(dist.resolve(), wanted) is None


def test_file_inside_finds_a_file(dist):
    root = dist.resolve()
    assert file_inside(root, "assets/app-abc123.js") == root / "assets" / "app-abc123.js"


# --- mounting and the setting ---


def test_nothing_is_mounted_without_an_index(tmp_path):
    from fastapi import FastAPI

    app = FastAPI()
    (tmp_path / "empty").mkdir()
    before = list(app.router.routes)
    assert mount_ui(app, tmp_path / "missing") is False
    assert mount_ui(app, tmp_path / "empty") is False
    assert app.router.routes == before


def test_a_dist_without_an_index_leaves_the_api_as_before(tmp_path):
    (tmp_path / "half" / "assets").mkdir(parents=True)
    (tmp_path / "half" / "assets" / "a.js").write_text("x")
    with client_for(tmp_path, tmp_path / "half") as client:
        assert client.get("/").status_code == 404
        assert client.get("/assets/a.js").status_code == 404


def test_the_ui_is_not_in_the_openapi_schema(tmp_path, dist):
    with client_for(tmp_path, dist, api_docs=True) as client:
        paths = client.get("/openapi.json").json()["paths"]
    assert all(p.startswith("/api/") for p in paths)


def test_docs_off_look_like_any_other_page_or_missing_file(tmp_path, dist):
    with client_for(tmp_path, dist) as client:
        page = shape(client.get("/some/route"))
        missing = shape(client.get("/missing.json"))
        assert shape(client.get("/docs")) == page
        assert shape(client.get("/redoc")) == page
        assert shape(client.get("/openapi.json")) == missing


def test_docs_on_still_win_over_the_ui(tmp_path, dist):
    with client_for(tmp_path, dist, api_docs=True) as client:
        assert "swagger" in client.get("/docs").text.lower()
        assert client.get("/openapi.json").json()["info"]["title"] == "Gumshoe API"


def test_ui_dist_defaults_to_the_frontend_build(monkeypatch):
    monkeypatch.delenv("UI_DIST", raising=False)
    assert Settings(_env_file=None).ui_dist == PROJECT_ROOT / "frontend" / "dist"


def test_ui_dist_is_read_from_the_environment_against_the_root(monkeypatch, tmp_path):
    monkeypatch.setenv("UI_DIST", "elsewhere/dist")
    assert Settings(_env_file=None).ui_dist == PROJECT_ROOT / "elsewhere" / "dist"
    monkeypatch.setenv("UI_DIST", str(tmp_path))
    assert Settings(_env_file=None).ui_dist == tmp_path


def test_the_default_app_reads_ui_dist_from_the_environment(monkeypatch, tmp_path, dist):
    monkeypatch.setenv("UI_DIST", str(dist))

    async def up():
        return True

    app = create_app(
        SqliteStatsStore(tmp_path / "d.db"), make_service=fake_factory(Script()), personas_up=up
    )
    with TestClient(app) as client:
        assert client.get("/").text == INDEX


# --- fix round 1: dotfiles, source trees, caching from the resolved file ---


@pytest.fixture
def dotted(dist):
    # (a `.env` itself would stop the mount: a source-tree marker, tested below)
    (dist / ".env.production").write_text("JEV_API_KEY=leak")
    (dist / ".npmrc").write_text("token leak")
    (dist / "assets" / ".hidden").write_text("hidden leak")
    (dist / ".git").mkdir()
    (dist / ".git" / "config").write_text("git leak")
    (dist / ".well-known").mkdir()
    (dist / ".well-known" / "security.txt").write_text("well-known leak")
    (dist / "a").mkdir()
    (dist / "a" / "b.txt").write_text("plain b")
    (dist / "favicon.ico").write_text("icon")
    return dist


@pytest.mark.parametrize(
    "path",
    [
        "/.env",
        "/.env.production",
        "/.npmrc",
        "/assets/.hidden",
        "/.git/config",
        "/.git",
        "/.git/",
        "/%2eenv",
        "/%2eenv.production",
        "/%2Enpmrc",
        "/.well-known/security.txt",
        "/assets/%2ehidden",
    ],
)
def test_dotfiles_are_a_plain_404(tmp_path, dotted, path):
    with client_for(tmp_path, dotted) as client:
        r = client.get(path)
        missing = client.get("/missing.png")
    assert b"leak" not in r.content
    assert shape(r) == shape(missing)


@pytest.mark.parametrize(
    "path", ["/a/./b.txt", "/./.npmrc", "/a/../.npmrc", "/assets/./.hidden", "/./"]
)
def test_dot_segments_sent_raw_are_a_404(tmp_path, dotted, path):
    status, body = raw_get(app_for(tmp_path, dotted), path)
    assert status == 404 and b"leak" not in body and b"plain b" not in body


def test_a_symlink_to_a_dotfile_is_not_followed(tmp_path, dotted):
    os.symlink(dotted / ".env.production", dotted / "visible.txt")
    os.symlink(dotted / ".git", dotted / "gitdir")
    with client_for(tmp_path, dotted) as client:
        assert client.get("/visible.txt").status_code == 404
        r = client.get("/gitdir/config")  # no dot in the last segment: a client route
        assert b"leak" not in r.content and (r.status_code, r.text) == (200, INDEX)


def test_a_normal_file_beside_dotfiles_is_still_served(tmp_path, dotted):
    with client_for(tmp_path, dotted) as client:
        assert client.get("/a/b.txt").text == "plain b"
        assert client.get("/assets/app-abc123.js").text == "console.log(1)"


def test_the_cache_rule_comes_from_the_resolved_file(tmp_path, dotted):
    with client_for(tmp_path, dotted) as client:
        icon = client.get("/assets/../favicon.ico")  # normalised by the client, but also raw:
        assert (icon.text, icon.headers["cache-control"]) == ("icon", INDEX_CACHE)
        assert client.get("/favicon.ico").headers["cache-control"] == INDEX_CACHE
        asset = client.get("/assets/app-abc123.js")
        assert asset.headers["cache-control"] == ASSET_CACHE
        trailing = client.get("/assets/app-abc123.js/")
        assert trailing.headers["cache-control"] != ASSET_CACHE
        assert client.get("/assets//app-abc123.js").headers["cache-control"] != ASSET_CACHE


def test_an_asset_reached_through_a_symlink_outside_assets_is_not_immutable(tmp_path, dist):
    os.symlink(dist / "index.html", dist / "assets" / "page.html")
    with client_for(tmp_path, dist) as client:
        r = client.get("/assets/page.html")
    assert r.status_code == 200 and r.headers["cache-control"] == INDEX_CACHE


@pytest.mark.parametrize("marker", ["package.json", ".env", "src", "node_modules"], ids=lambda m: m)
def test_a_source_tree_is_never_mounted(tmp_path, dist, marker, caplog):
    from fastapi import FastAPI

    if marker in ("src", "node_modules"):
        (dist / marker).mkdir()
    else:
        (dist / marker).write_text("SECRET=do-not-log")
    app = FastAPI()
    before = list(app.router.routes)
    with caplog.at_level("WARNING"):
        assert mount_ui(app, dist) is False
    assert app.router.routes == before
    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert "do-not-log" not in caplog.text


def test_a_source_tree_leaves_the_app_api_only(tmp_path, dist):
    (dist / "package.json").write_text("{}")
    with client_for(tmp_path, dist) as client:
        assert client.get("/").status_code == 404
        assert client.get("/package.json").status_code == 404


@pytest.mark.parametrize("where", ["equal", "inside"])
def test_the_project_root_or_above_is_never_mounted(monkeypatch, dist, where):
    from fastapi import FastAPI

    # a build-looking dir (index.html, no markers) that is, or holds, the project root
    project = dist if where == "equal" else dist / "assets"
    monkeypatch.setattr("gumshoe.api.static.PROJECT_ROOT", project.resolve())
    app = FastAPI()
    before = list(app.router.routes)
    assert mount_ui(app, dist) is False
    assert app.router.routes == before


def test_the_real_project_root_and_above_are_never_mounted():
    from fastapi import FastAPI

    for candidate in (PROJECT_ROOT, PROJECT_ROOT.parent):
        assert mount_ui(FastAPI(), candidate) is False, candidate


def test_the_frontend_source_dir_is_never_mounted():
    from fastapi import FastAPI

    assert mount_ui(FastAPI(), PROJECT_ROOT / "frontend") is False


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_ui_dist_means_the_default(monkeypatch, blank):
    monkeypatch.setenv("UI_DIST", blank)
    assert Settings(_env_file=None).ui_dist == PROJECT_ROOT / "frontend" / "dist"
    assert Settings(_env_file=None, ui_dist=blank).ui_dist == PROJECT_ROOT / "frontend" / "dist"
