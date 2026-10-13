import json
from typing import Any

import httpx
import pytest

from gumshoe.agent.llm import Llm, LlmError, LlmMessage, OllamaLlm


def reply_with(content, status=200):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["url"] = str(request.url)
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})

    return handler, seen


async def test_complete_posts_chat_messages_and_returns_the_text():
    handler, seen = reply_with("I was in the hall.")
    llm = OllamaLlm("http://ollama/v1/", transport=httpx.MockTransport(handler))
    text = await llm.complete(
        "gemma4:12b", "You are Berta.", [LlmMessage(role="user", content="Where were you?")]
    )
    assert text == "I was in the hall."
    assert seen["url"] == "http://ollama/v1/chat/completions"
    assert seen["body"]["model"] == "gemma4:12b" and seen["body"]["stream"] is False
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "You are Berta."},
        {"role": "user", "content": "Where were you?"},
    ]
    assert isinstance(llm, Llm)
    await llm.aclose()


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500, json={"choices": [{"message": {"content": "x"}}]}),
        lambda request: httpx.Response(200, text="not json"),
        lambda request: httpx.Response(200, json={"choices": []}),
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": 7}}]}),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("down")),
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    ],
    ids=["http-500", "not-json", "no-choices", "content-not-text", "connect-error", "timeout"],
)
async def test_every_failure_is_an_llm_error(handler):
    llm = OllamaLlm("http://ollama/v1", transport=httpx.MockTransport(handler))
    with pytest.raises(LlmError):
        await llm.complete("m", "s", [LlmMessage(role="user", content="hi")])
    await llm.aclose()
