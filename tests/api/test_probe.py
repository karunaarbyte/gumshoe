import httpx

from gumshoe.api.probe import PersonaProbe


def probe(handler, *, ttl_s=5.0, clock=None):
    return PersonaProbe(
        "http://ollama.test/v1",
        ttl_s=ttl_s,
        transport=httpx.MockTransport(handler),
        clock=clock or (lambda: 0.0),
    )


async def test_up_when_the_model_server_lists_its_models():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": []})

    assert await probe(handler).up() is True
    assert seen == ["http://ollama.test/v1/models"]


async def test_down_when_the_server_cannot_be_reached():
    def handler(request):
        raise httpx.ConnectError("refused")

    assert await probe(handler).up() is False


async def test_down_on_an_error_status_or_a_timeout():
    assert await probe(lambda r: httpx.Response(500)).up() is False

    def slow(request):
        raise httpx.ReadTimeout("slow")

    assert await probe(slow).up() is False


async def test_the_answer_is_cached_for_the_ttl_then_asked_again():
    calls = []
    now = [0.0]

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"data": []})

    p = probe(handler, ttl_s=5.0, clock=lambda: now[0])
    assert await p.up() and await p.up()
    assert len(calls) == 1  # a health poll does not hammer the model server
    now[0] = 6.0
    assert await p.up()
    assert len(calls) == 2
