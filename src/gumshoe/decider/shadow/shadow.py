"""Run the primary and a shadow decider side by side; the game uses the primary's answer."""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Coroutine, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from gumshoe.decider.contract.base import Decider
from gumshoe.decider.contract.errors import DeciderAllFailedError, DeciderError
from gumshoe.decider.contract.models import DecisionResult, Question
from gumshoe.decider.shadow.records import CallOutcome, Recorder, Role, build_record

logger = logging.getLogger(__name__)

COLD_AFTER_S = 300.0
DRAIN_GRACE_S = 5.0


def _log_if_crashed(task: "asyncio.Task[CallOutcome]") -> None:
    """Done-callback: retrieve and log an unexpected exception so it is never left unretrieved."""
    if not task.cancelled() and (exc := task.exception()) is not None:
        logger.error("shadow call crashed", exc_info=exc)


class ShadowDecider:
    def __init__(
        self,
        primary: Decider,
        shadow: Decider | None,
        recorder: Recorder,
        *,
        cold_after_s: float = COLD_AFTER_S,
        drain_grace_s: float = DRAIN_GRACE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if shadow is not None and shadow.name == primary.name:
            raise ValueError("primary and shadow must differ (stats are keyed by backend name)")
        self.name = primary.name
        self._primary = primary
        self._shadow = shadow
        self._recorder = recorder
        self.cold_after_s = cold_after_s
        self.drain_grace_s = drain_grace_s  # how long aclose waits for unfinished shadow calls
        self._clock = clock
        self._last_end: dict[str, float] = {}  # backend name -> clock() when its last call ended
        self._background: set[asyncio.Task[None]] = set()

    async def decide(
        self,
        state: str,
        questions: Mapping[str, Question],
        *,
        node: str = "adhoc",
        decision_id: str | None = None,
    ) -> DecisionResult:
        decision_id = decision_id if decision_id is not None else uuid.uuid4().hex
        primary_task = asyncio.create_task(
            self._call(self._primary, "primary", state, questions, node)
        )
        shadow_task = (
            asyncio.create_task(self._call(self._shadow, "shadow", state, questions, node))
            if self._shadow is not None
            else None
        )
        if shadow_task is not None:
            shadow_task.add_done_callback(_log_if_crashed)
        try:
            primary = await primary_task
        except BaseException:  # includes CancelledError: don't leave the shadow call running
            if shadow_task is not None:
                shadow_task.cancel()
            raise

        if primary.result is not None:
            self._spawn(self._finish(decision_id, node, state, primary, shadow_task))
            return primary.result

        return await self._after_primary_failure(decision_id, node, state, primary, shadow_task)

    async def drain(self, grace_s: float | None = None) -> None:
        """Wait up to `grace_s` seconds for background recording; cancel what is still running."""
        pending = set(self._background)
        if not pending:
            return
        _, still_running = await asyncio.wait(pending, timeout=grace_s)
        for task in still_running:
            task.cancel()
        # let them finish unwinding (and record what they have) before anything is closed
        await asyncio.gather(*still_running, return_exceptions=True)

    async def aclose(self) -> None:
        try:
            await self.drain(grace_s=self.drain_grace_s)
        finally:
            await self._primary.aclose()
            if self._shadow is not None:
                await self._shadow.aclose()

    # -- internals ---------------------------------------------------------------------------

    async def _call(
        self,
        decider: Decider,
        role: Role,
        state: str,
        questions: Mapping[str, Question],
        node: str,
    ) -> CallOutcome:
        """One backend call. Any failure becomes part of the outcome, so fallback and recording
        never depend on a backend classifying its errors perfectly. An exception that is not a
        DeciderError is a backend bug: it is logged with its traceback and recorded as a failure."""
        started = self._clock()
        last_end = self._last_end.get(decider.name)
        cold = last_end is None or started - last_end > self.cold_after_s
        ts = datetime.now(UTC).isoformat(timespec="microseconds")
        t0 = time.perf_counter()
        result: DecisionResult | None = None
        failure: DeciderError | None = None
        try:
            result = await decider.decide(state, questions, node=node)
        except DeciderError as exc:
            failure = exc
        except Exception as exc:
            logger.error("%s call crashed (%s)", role, decider.name, exc_info=exc)
            failure = DeciderError(decider.name, f"unexpected {type(exc).__name__}")
            failure.__cause__ = exc
        finally:
            self._last_end[decider.name] = self._clock()
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return CallOutcome(
            backend=decider.name,
            role=role,
            ts=ts,
            cold=cold,
            latency_ms=latency_ms,
            result=result,
            failure=failure,
        )

    async def _after_primary_failure(
        self,
        decision_id: str,
        node: str,
        state: str,
        primary: CallOutcome,
        shadow_task: asyncio.Task[CallOutcome] | None,
    ) -> DecisionResult:
        assert primary.failure is not None
        if shadow_task is None:  # nothing to fall back to: surface the original error
            await self._record(decision_id, node, state, [primary], used_role=None, fallback=False)
            raise primary.failure

        try:
            shadow = await shadow_task  # already running; cancelling the turn cancels it too
        except (
            Exception
        ):  # a bug in the shadow (already logged): the primary's failure is the story
            await self._record(decision_id, node, state, [primary], used_role=None, fallback=False)
            raise primary.failure from None
        if shadow.result is not None:
            await self._record(
                decision_id, node, state, [primary, shadow], used_role="shadow", fallback=True
            )
            return shadow.result

        assert shadow.failure is not None
        await self._record(
            decision_id, node, state, [primary, shadow], used_role=None, fallback=False
        )
        raise DeciderAllFailedError(
            {primary.backend: primary.failure, shadow.backend: shadow.failure}
        ) from primary.failure

    async def _finish(
        self,
        decision_id: str,
        node: str,
        state: str,
        primary: CallOutcome,
        shadow_task: asyncio.Task[CallOutcome] | None,
    ) -> None:
        """Background: wait for the shadow, then record the pair. The turn is already over."""
        calls = [primary]
        if shadow_task is not None:
            try:
                # shield: if *we* are cancelled (drain gave up), cancel the shadow ourselves below
                calls.append(await asyncio.shield(shadow_task))
            except asyncio.CancelledError:
                shadow_task.cancel()
                await self._record(
                    decision_id, node, state, calls, used_role="primary", fallback=False
                )
                raise
            except Exception:
                pass  # a crashed shadow was already logged by _log_if_crashed; record the primary
        await self._record(decision_id, node, state, calls, used_role="primary", fallback=False)

    async def _record(
        self,
        decision_id: str,
        node: str,
        state: str,
        calls: Sequence[CallOutcome],
        *,
        used_role: Role | None,
        fallback: bool,
    ) -> None:
        records = [
            build_record(
                decision_id=decision_id,
                node=node,
                state=state,
                call=call,
                used=call.role == used_role,
                fallback=fallback,
            )
            for call in calls
        ]
        try:
            await self._recorder.record(records)
        except Exception:  # a broken stats store must never break the game
            logger.exception("could not record decision %s", decision_id)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)  # strong reference: the loop only keeps weak ones
        task.add_done_callback(self._background.discard)
