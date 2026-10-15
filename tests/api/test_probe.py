import asyncio

import httpx

from gumshoe.api.probe import PersonaProbe

MODELS = ("ministral-3:14b", "gemma4:12b")


def listing(*names):
    return httpx.Response(200, json={"data": [{"id": n} for n in names]})


def probe(handler, *, ttl_s=5.0, clock=None, models=MODELS, base="http://ollama.test/v1"):
    return PersonaProbe(
        base,
        models,
        ttl_s=ttl_s,
        transport=httpx.MockTransport(handler),
        clock=clock or (lambda: 0.0),
    )


async def test_up_when_the_server_lists_every_persona_model():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return listing(*MODELS, "something-else")

    assert await probe(handler).up() is True
    assert seen == ["http://ollama.test/v1/models"]


async def test_down_when_a_persona_model_is_not_pulled():
    # the server answers, but suspects would still fall back to stock lines
    assert await probe(lambda r: listing("ministral-3:14b")).up() is False


async def test_down_when_the_server_cannot_be_reached():
    def handler(request):
        raise httpx.ConnectError("refused")

    assert await probe(handler).up() is False


async def test_down_on_an_error_status_a_timeout_or_an_unreadable_list():
    assert await probe(lambda r: httpx.Response(500)).up() is False
    assert await probe(lambda r: httpx.Response(200, text="not json")).up() is False

    def slow(request):
        raise httpx.ReadTimeout("slow")

    assert await probe(slow).up() is False


async def test_down_for_a_malformed_base_url_instead_of_raising():
    assert await probe(lambda r: listing(*MODELS), base="not a url").up() is False


async def test_the_answer_is_cached_for_the_ttl_then_asked_again():
    calls = []
    now = [0.0]

    def handler(request):
        calls.append(1)
        return listing(*MODELS)

    p = probe(handler, ttl_s=5.0, clock=lambda: now[0])
    assert await p.up() and await p.up()
    assert len(calls) == 1  # a health poll does not hammer the model server
    now[0] = 6.0
    assert await p.up()
    assert len(calls) == 2


async def test_concurrent_checks_share_one_request():
    calls = []

    async def handler(request):
        calls.append(1)
        await asyncio.sleep(0.05)
        return listing(*MODELS)

    p = probe(handler)
    assert await asyncio.gather(p.up(), p.up(), p.up()) == [True, True, True]
    assert len(calls) == 1
