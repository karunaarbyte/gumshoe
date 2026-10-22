import httpx
import pytest

from gumshoe.api.app import create_app
from gumshoe.config import Settings
from gumshoe.decider import DeciderAPIError, ShadowDecider
from gumshoe.decider.contract.samples import DEMO_QUESTIONS, DEMO_STATE
from gumshoe.stats.store import SqliteStatsStore
from tests.decider.fakes import FakeDecider
from tests.stats.factories import choice, make_record


@pytest.fixture
def store(tmp_path):
    return SqliteStatsStore(tmp_path / "decisions.db")


@pytest.fixture
async def client(store):
    transport = httpx.ASGITransport(app=create_app(store))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"origin": "http://test"}
    ) as c:
        yield c


def seed(
    store, decision_id, *, node="intent", minute="00", jev="dialogue", nimble="dialogue", cold=False
):
    ts = f"2026-10-01T10:{minute}:00.000000+00:00"
    store.insert(
        [
            make_record(decision_id=decision_id, node=node, ts=ts, answers={"intent": choice(jev)}),
            make_record(
                decision_id=decision_id,
                node=node,
                ts=ts,
                backend="nimble",
                role="shadow",
                used=False,
                cold=cold,
                latency_ms=1500.0,
                answers={"intent": choice(nimble)},
            ),
        ]
    )


async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    # httpx.ASGITransport runs no lifespan, so the game never started
    assert (body["status"], body["game"]) == ("ok", "off")


async def test_stats_on_an_empty_database(client):
    response = await client.get("/api/stats/decisions")
    assert response.status_code == 200
    body = response.json()
    assert body["nodes"] == [] and body["include_cold"] is False and body["since"] is None


async def test_stats_report_shape_and_values(client, store):
    seed(store, "d1", minute="01")
    seed(store, "d2", minute="02", nimble="meta")
    body = (await client.get("/api/stats/decisions")).json()
    [node] = body["nodes"]
    assert node["node"] == "intent" and node["decisions"] == 2 and node["compared"] == 2
    assert node["agreement_rate"] == 0.5
    backends = {b["backend"]: b for b in node["backends"]}
    assert backends["jev"]["latency_ms"]["p50"] == 500.0
    assert backends["nimble"]["latency_ms"]["p50"] == 1500.0


async def test_stats_node_filter(client, store):
    seed(store, "d1", node="intent")
    seed(store, "d2", node="route")
    body = (await client.get("/api/stats/decisions", params={"node": "route"})).json()
    assert [n["node"] for n in body["nodes"]] == ["route"]


async def test_stats_since_filter(client, store):
    seed(store, "old", minute="00")
    seed(store, "new", minute="30")
    body = (
        await client.get("/api/stats/decisions", params={"since": "2026-10-01T10:15:00Z"})
    ).json()
    assert body["nodes"][0]["decisions"] == 1
    assert body["since"] == "2026-10-01T10:15:00.000000+00:00"


async def test_stats_since_without_a_timezone_means_utc(client, store):
    seed(store, "old", minute="00")
    seed(store, "new", minute="30")
    body = (
        await client.get("/api/stats/decisions", params={"since": "2026-10-01T10:15:00"})
    ).json()
    assert body["nodes"][0]["decisions"] == 1


async def test_stats_include_cold_changes_latency_samples(client, store):
    seed(store, "d1", minute="01", cold=True)
    default = (await client.get("/api/stats/decisions")).json()["nodes"][0]
    nimble = next(b for b in default["backends"] if b["backend"] == "nimble")
    assert nimble["cold_calls"] == 1 and nimble["latency_ms"]["p50"] is None
    full = (await client.get("/api/stats/decisions", params={"include_cold": "true"})).json()
    nimble = next(b for b in full["nodes"][0]["backends"] if b["backend"] == "nimble")
    assert nimble["latency_ms"]["p50"] == 1500.0


@pytest.mark.parametrize("since", ["yesterday-ish", "2026-13-45", ""])
async def test_stats_rejects_a_malformed_since(client, since):
    response = await client.get("/api/stats/decisions", params={"since": since})
    assert response.status_code == 422


async def test_malicious_node_parameter_is_just_an_unknown_node(client, store):
    seed(store, "d1")
    response = await client.get("/api/stats/decisions", params={"node": "x' OR '1'='1"})
    assert response.status_code == 200 and response.json()["nodes"] == []
    assert len(store.fetch_calls()) == 2


async def test_recent_decisions_newest_first_and_limited(client, store):
    for i in range(5):
        seed(store, f"d{i}", minute=f"0{i}")
    body = (await client.get("/api/decisions", params={"limit": 3})).json()
    assert [d["decision_id"] for d in body] == ["d4", "d3", "d2"]
    first = body[0]
    assert [c["backend"] for c in first["calls"]] == ["jev", "nimble"]  # primary first
    assert first["calls"][0]["answers"]["intent"]["verdict"] == "dialogue"


async def test_recent_decisions_default_limit_is_twenty(client, store):
    for i in range(25):
        seed(store, f"d{i:02}", minute=f"{i:02}")
    assert len((await client.get("/api/decisions")).json()) == 20


async def test_recent_decisions_node_filter(client, store):
    seed(store, "a", node="intent")
    seed(store, "b", node="route")
    body = (await client.get("/api/decisions", params={"node": "route"})).json()
    assert [d["decision_id"] for d in body] == ["b"]


async def test_recent_decisions_on_an_empty_database(client):
    response = await client.get("/api/decisions")
    assert response.status_code == 200 and response.json() == []


@pytest.mark.parametrize("limit", ["0", "201", "-1", "abc"])
async def test_recent_decisions_rejects_bad_limits(client, limit):
    assert (await client.get("/api/decisions", params={"limit": limit})).status_code == 422


async def test_unknown_routes_are_404_and_wrong_methods_405(client):
    missing = await client.get("/api/nope")
    wrong = await client.post("/api/decisions")
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    assert wrong.status_code == 405 and wrong.json()["code"] == "method_not_allowed"


async def test_one_decision_by_id_and_404_until_it_is_recorded(client, store):
    seed(store, "d1")
    found = await client.get("/api/decisions/d1")
    missing = await client.get("/api/decisions/not-yet")
    assert found.status_code == 200 and found.json()["decision_id"] == "d1"
    assert missing.status_code == 404
    assert missing.json() == {
        "code": "not_recorded_yet",
        "message": "that decision has not been recorded yet",
    }


async def test_decisions_by_ids_ignore_the_limit(client, store):
    for i in range(5):
        seed(store, f"d{i}", minute=f"0{i}")
    body = (await client.get("/api/decisions", params={"ids": "d0,d3,nope", "limit": 1})).json()
    assert [d["decision_id"] for d in body] == ["d3", "d0"]


@pytest.mark.parametrize("ids", ["", ",", ",".join(f"d{i}" for i in range(201))])
async def test_ids_must_name_1_to_200_decisions(client, ids):
    response = await client.get("/api/decisions", params={"ids": ids})
    assert response.status_code == 422 and response.json()["code"] == "bad_request"


async def test_disagree_keeps_only_decisions_where_the_backends_differ(client, store):
    seed(store, "same", minute="01")
    seed(store, "differ", minute="02", nimble="meta")
    body = (await client.get("/api/decisions", params={"disagree": "true"})).json()
    assert [d["decision_id"] for d in body] == ["differ"]


async def test_costs_use_the_configured_prices(store):
    settings = Settings(_env_file=None, jev_usd_per_mtok_in=1.0, jev_usd_per_mtok_out=1.0)
    seed(store, "d1")
    transport = httpx.ASGITransport(app=create_app(store, settings=settings))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"origin": "http://test"}
    ) as c:
        [decision] = (await c.get("/api/decisions")).json()
        report = (await c.get("/api/stats/decisions")).json()
    jev = decision["calls"][0]
    assert (jev["input_tokens"], jev["output_tokens"], jev["est_cost_usd"]) == (400, 80, 0.00048)
    [node] = report["nodes"]
    costs = {b["backend"]: b["est_cost_usd"] for b in node["backends"]}
    assert costs == {"jev": 0.00048, "nimble": 0.0}


async def test_a_backend_failure_reaches_the_decisions_api_without_its_response_body(client, store):
    body = '{"echo": "sk-secret-123"}'
    primary = FakeDecider("nimble", error=DeciderAPIError("nimble", 502, body))
    decider = ShadowDecider(primary, None, store)
    with pytest.raises(DeciderAPIError):
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent", decision_id="d1")
    await decider.drain()
    raw = (await client.get("/api/decisions")).text
    one = (await client.get("/api/decisions/d1")).text
    for text in (raw, one):
        assert "sk-secret" not in text
        assert "DeciderAPIError (nimble, HTTP 502)" in text


# --- the stats page: since, question, agrees, shadow errors, roles --------------------------------


def seed_weighed(store, decision_id, *, minute, intent_b="dialogue", weight=(1.0, 1.0)):
    from gumshoe.decider import ScoreAnswer

    def score(v):
        return ScoreAnswer(type="score", score=v, legend={}, probabilities={}, confidence=0.5)

    ts = f"2026-10-01T10:{minute}:00.000000+00:00"
    store.insert(
        [
            make_record(
                decision_id=decision_id,
                ts=ts,
                answers={"intent": choice("dialogue"), "weight": score(weight[0])},
            ),
            make_record(
                decision_id=decision_id,
                ts=ts,
                backend="nimble",
                role="shadow",
                used=False,
                answers={"intent": choice(intent_b), "weight": score(weight[1])},
            ),
        ]
    )


async def test_decisions_can_start_from_a_date(client, store):
    seed(store, "old", minute="01", nimble="meta")
    seed(store, "new", minute="30", nimble="meta")
    since = "2026-10-01T10:15:00Z"
    plain = (await client.get("/api/decisions", params={"since": since})).json()
    assert [d["decision_id"] for d in plain] == ["new"]
    differing = (
        await client.get("/api/decisions", params={"since": since, "disagree": "true"})
    ).json()
    assert [d["decision_id"] for d in differing] == ["new"]


async def test_since_without_disagree_still_returns_only_the_latest_limit(client, store):
    for minute in ("20", "30", "40", "50"):
        seed(store, f"d{minute}", minute=minute)
    body = (
        await client.get("/api/decisions", params={"since": "2026-10-01T10:25:00Z", "limit": 2})
    ).json()
    assert [d["decision_id"] for d in body] == ["d50", "d40"]  # newest first, d20 is before since


async def test_disagree_can_be_narrowed_to_one_question(client, store):
    seed_weighed(store, "weight_only", minute="01", weight=(2.4, 2.6))
    seed_weighed(store, "intent_only", minute="02", intent_b="meta")
    params = {"disagree": "true", "question": "weight"}
    body = (await client.get("/api/decisions", params=params)).json()
    assert [d["decision_id"] for d in body] == ["weight_only"]


async def test_a_question_filter_without_disagree_is_refused(client):
    response = await client.get("/api/decisions", params={"question": "weight"})
    assert response.status_code == 422 and response.json()["code"] == "bad_request"


async def test_each_decision_says_which_questions_agree(client, store):
    seed_weighed(store, "d", minute="01", weight=(1.0, 1.9))
    [view] = (await client.get("/api/decisions")).json()
    assert view["agrees"] == {"intent": True, "weight": True}


async def test_the_weight_threshold_comes_from_the_settings(store):
    settings = Settings(_env_file=None, dramatic_from=3.0)
    seed_weighed(store, "d", minute="01", weight=(2.8, 3.2))  # one band under the default 2.5
    transport = httpx.ASGITransport(app=create_app(store, settings=settings))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"origin": "http://test"}
    ) as c:
        [view] = (await c.get("/api/decisions")).json()
        [node] = (await c.get("/api/stats/decisions")).json()["nodes"]
    assert view["agrees"]["weight"] is False and node["question_agreement"]["weight"] == 0.0


async def test_stats_report_shadow_errors_roles_and_the_score_offset(client, store):
    seed_weighed(store, "ok", minute="01", weight=(1.0, 2.0))
    store.insert(
        [
            make_record(decision_id="bad", ts="2026-10-01T10:05:00.000000+00:00"),
            make_record(
                decision_id="bad",
                ts="2026-10-01T10:05:00.000000+00:00",
                backend="nimble",
                role="shadow",
                used=False,
                error="DeciderConnectionError (nimble)",
                answers=None,
            ),
        ]
    )
    [node] = (await client.get("/api/stats/decisions")).json()["nodes"]
    assert (node["decisions"], node["compared"], node["shadow_errors"]) == (2, 1, 1)
    assert node["score_offset"] == {"weight": 1.0}
    assert node["intent_confusion"]["dialogue"] == {"(error)": 1, "dialogue": 1}
    assert {b["backend"]: b["role"] for b in node["backends"]} == {
        "jev": "primary",
        "nimble": "shadow",
    }
