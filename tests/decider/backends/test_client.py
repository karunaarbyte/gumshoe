import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from gumshoe.decider.backends.client import SystemOneClient
from gumshoe.decider.backends.profile import BackendProfile
from gumshoe.decider.contract.errors import (
    DeciderAPIError,
    DeciderConfigError,
    DeciderConnectionError,
    DeciderParseError,
)
from gumshoe.decider.contract.samples import DEMO_QUESTIONS, DEMO_STATE


def make_client(handler, *, api_key=None, name="nimble", base_url="http://test/v1"):
    profile = BackendProfile(name=name, base_url=base_url, model="m", api_key=api_key)
    return SystemOneClient(profile, transport=httpx.MockTransport(handler))


def test_profile_endpoint_handles_trailing_slash():
    assert BackendProfile("n", "http://x/v1/", "m").endpoint == "http://x/v1/systemone"
    assert BackendProfile("n", "http://x/v1", "m").endpoint == "http://x/v1/systemone"


def test_profile_repr_hides_api_key():
    profile = BackendProfile("jev", "https://x/v1", "m", api_key="s3cret")
    assert "s3cret" not in repr(profile)


async def test_decide_posts_request_and_parses_response(load_fixture):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=load_fixture("nimble_all_types.response.json"))

    async with make_client(handler) as client:
        result = await client.decide(DEMO_STATE, DEMO_QUESTIONS)

    assert seen["url"] == "http://test/v1/systemone"
    assert seen["body"]["model"] == "m"
    assert seen["body"]["state"] == DEMO_STATE
    assert seen["body"]["questions"]["intent"]["type"] == "choice"
    assert seen["auth"] is None
    assert result.choice("intent").choice == "dialogue"


async def test_sends_bearer_token_when_key_present(load_fixture):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=load_fixture("nimble_all_types.response.json"))

    async with make_client(handler, api_key="s3cret", name="jev") as client:
        await client.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert seen["auth"] == "Bearer s3cret"


async def test_node_label_is_accepted_but_not_sent(load_fixture):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=load_fixture("nimble_all_types.response.json"))

    async with make_client(handler) as client:
        await client.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent")
    assert "node" not in seen["body"]
    assert set(seen["body"]) == {"model", "state", "questions"}


async def test_connection_refused_becomes_connection_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    async with make_client(handler, api_key="s3cret", name="jev") as client:
        with pytest.raises(DeciderConnectionError) as info:
            await client.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert "http://test/v1/systemone" in str(info.value)
    assert "s3cret" not in str(info.value)
    assert isinstance(info.value.__cause__, httpx.ConnectError)


async def test_timeout_becomes_connection_error_mentioning_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    async with make_client(handler) as client:
        with pytest.raises(DeciderConnectionError, match="timed out"):
            await client.decide(DEMO_STATE, DEMO_QUESTIONS)


async def test_http_400_becomes_api_error_with_server_message(load_fixture):
    def handler(request):
        return httpx.Response(400, json=load_fixture("nimble_error_400.json"))

    async with make_client(handler) as client:
        with pytest.raises(DeciderAPIError) as info:
            await client.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert info.value.status_code == 400
    assert "score criteria must be an array" in str(info.value)


async def test_model_not_pulled_is_a_readable_404(load_fixture):
    def handler(request):
        return httpx.Response(404, json=load_fixture("nimble_error_404.json"))

    async with make_client(handler) as client:
        with pytest.raises(DeciderAPIError, match="not found") as info:
            await client.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert info.value.status_code == 404


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>Bad gateway page</html>"),
        httpx.Response(200, text='{"model": "m", "answers": {"intent": {"type": "chi'),
        httpx.Response(200, json={"unexpected": "shape"}),
        httpx.Response(200, json={"model": "m", "answers": {"q": {"type": "mystery"}}}),
    ],
)
async def test_garbled_200_becomes_parse_error_with_raw_body(response):
    async with make_client(lambda request: response) as client:
        with pytest.raises(DeciderParseError) as info:
            await client.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert info.value.raw == response.text


async def test_invalid_input_fails_before_any_network_call():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    async with make_client(handler) as client:
        with pytest.raises(ValidationError):
            await client.decide("   ", DEMO_QUESTIONS)
    assert calls == []


async def test_illegal_header_value_points_at_the_api_key_not_the_network():
    def handler(request):
        raise httpx.LocalProtocolError("Illegal header value b'Bearer abc\\n'")

    async with make_client(handler, api_key="s3cret", name="jev") as client:
        with pytest.raises(DeciderConfigError, match="API key") as info:
            await client.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert "s3cret" not in str(info.value)


async def test_decide_accepts_a_decision_id_and_does_not_send_it(load_fixture):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=load_fixture("nimble_all_types.response.json"))

    client = make_client(handler)
    await client.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent", decision_id="abc123")
    assert "abc123" not in json.dumps(seen["body"])
    await client.aclose()


async def test_a_nan_in_a_200_body_is_a_parse_error_not_an_answer():
    body = '{"model": "m", "answers": {"q": {"type": "noul", "noul": NaN}}}'
    async with make_client(lambda request: httpx.Response(200, text=body)) as client:
        with pytest.raises(DeciderParseError):
            await client.decide(DEMO_STATE, DEMO_QUESTIONS)


async def test_a_body_that_will_not_decode_is_a_connection_error():
    def handler(request):
        return httpx.Response(200, headers={"content-encoding": "gzip"}, content=b"not gzip")

    async with make_client(handler, name="jev") as client:
        with pytest.raises(DeciderConnectionError, match="DecodingError"):
            await client.decide(DEMO_STATE, DEMO_QUESTIONS)
