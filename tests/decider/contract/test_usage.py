import asyncio

from gumshoe.decider import UsageLedger, client_key, estimate_tokens
from gumshoe.decider.contract.models import ChoiceQuestion, NoulQuestion


def test_the_estimate_grows_with_the_request_and_is_at_least_one():
    small = estimate_tokens("hi", {"q": NoulQuestion(instructions="x")})
    big = estimate_tokens(
        "hello " * 500,
        {"q": ChoiceQuestion(instructions="pick", criteria={"a": "x", "b": "y"})},
    )
    assert 1 <= small < big
    assert estimate_tokens("", {}) == 1


def test_the_estimate_counts_utf8_bytes_three_to_a_token():
    assert estimate_tokens("a" * 30, {}) == 10
    assert estimate_tokens("a" * 2, {}) == 1
    assert estimate_tokens("\u732b" * 10, {}) == 10  # 3 bytes each in UTF-8, not 1 character
    assert estimate_tokens("\u00e9" * 30, {}) == 20  # 2 bytes each
    q = NoulQuestion(instructions="\u732b" * 30)
    assert estimate_tokens("", {"q": q}) == len(q.model_dump_json().encode()) // 3


def test_the_client_key_defaults_to_empty_and_is_per_task():
    assert client_key.get() == ""

    async def in_task(value):
        client_key.set(value)
        await asyncio.sleep(0)
        return client_key.get()

    async def main():
        return await asyncio.gather(in_task("a"), in_task("b"))

    assert asyncio.run(main()) == ["a", "b"]
    assert client_key.get() == ""


def test_a_class_with_the_two_methods_is_a_ledger():
    class Mine:
        def add_usage(self, day, key, tokens): ...
        def usage_totals(self, day):
            return {}

    assert isinstance(Mine(), UsageLedger)
