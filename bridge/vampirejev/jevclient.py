"""Jev client. The real client is the only place the API key is read, and only from the environment.

Navigator calls must not retry: a retry that lands after the freshness window
would be acted on as if it were new. Card calls can wait, because the game is
paused, but they use the same no-retry policy and a longer timeout so one hung
call cannot pin the bridge.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# Provisional until the Phase 0 probe records latency from this machine.
# jev-1.13.0 is the current target of the jev-latest alias. Open question 7.
MODEL_STABLE = "jev-1.13.0"
MODEL_PREVIEW = "jev-1.14.0"
PINNED_MODEL = MODEL_STABLE

NAV_TIMEOUT_S = 0.8
CARD_TIMEOUT_S = 4.0


class MissingApiKey(RuntimeError):
    pass


@dataclass
class JevRequest:
    kind: str
    state: dict[str, Any]
    question_id: str
    instructions: str
    criteria: dict[str, str]
    option_order: list[str]
    include_play_safe: bool
    built_mono: float
    snapshot_t_ms: int
    timeout_s: float


@dataclass
class JevResult:
    ok: bool
    kind: str
    model: str = ""
    choice: str = ""
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    play_safe: Optional[float] = None
    latency_s: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    option_order: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    criteria: dict[str, str] = field(default_factory=dict)
    built_mono: float = 0.0
    snapshot_t_ms: int = 0
    error: str = ""


def require_api_key(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    key = str(env.get("TYPESAFE_API_KEY") or "").strip()
    if not key:
        raise MissingApiKey("TYPESAFE_API_KEY is not set")
    return key


class FakeJevClient:
    """Offline stand-in. Tests pass a scripted choice; the default is the first option after the shuffle."""

    def __init__(
        self,
        choice: str | None = None,
        confidence: float = 0.9,
        play_safe: float = 0.4,
        fail: BaseException | None = None,
    ) -> None:
        self.choice = choice
        self.confidence = confidence
        self.play_safe = play_safe
        self.fail = fail
        self.calls: list[JevRequest] = []

    async def ask(self, request: JevRequest) -> JevResult:
        self.calls.append(request)
        if self.fail is not None:
            raise self.fail
        order = list(request.option_order)
        picked = self.choice if self.choice in order else (order[0] if order else "")
        probabilities = {item: 0.0 for item in order}
        if picked:
            remain = max(0.0, 1.0 - self.confidence)
            share = remain / max(1, len(order) - 1) if len(order) > 1 else 0.0
            for item in order:
                probabilities[item] = self.confidence if item == picked else share
            if len(order) == 1:
                probabilities[picked] = 1.0
        return JevResult(
            ok=True,
            kind=request.kind,
            model="fake",
            choice=picked,
            probabilities=probabilities,
            confidence=self.confidence if request.kind == "movement" or request.question_id == "next" else self.confidence,
            play_safe=self.play_safe if request.include_play_safe else None,
            option_order=order,
            state=dict(request.state),
            criteria=dict(request.criteria),
            built_mono=request.built_mono,
            snapshot_t_ms=request.snapshot_t_ms,
        )


class TypeSafeJevClient:
    def __init__(self, model: str = PINNED_MODEL) -> None:
        self.model = model
        self._client: Any = None

    async def ask(self, request: JevRequest) -> JevResult:
        require_api_key()
        started = time.perf_counter()
        try:
            response = await self._call(request)
        except MissingApiKey:
            raise
        except Exception as exc:
            return JevResult(
                ok=False,
                kind=request.kind,
                model=self.model,
                error=type(exc).__name__ + ": " + str(exc),
                latency_s=time.perf_counter() - started,
                option_order=list(request.option_order),
                state=dict(request.state),
                criteria=dict(request.criteria),
                built_mono=request.built_mono,
                snapshot_t_ms=request.snapshot_t_ms,
            )
        return _from_response(response, request, time.perf_counter() - started, self.model)

    async def _call(self, request: JevRequest) -> Any:
        from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, RetryPolicy

        if self._client is None:
            self._client = AsyncTypeSafeClient(model=self.model, timeout=request.timeout_s)
            enter = getattr(self._client, "__aenter__", None)
            if enter is not None:
                await enter()
        questions: dict[str, Any] = {
            request.question_id: Choice(instructions=request.instructions, criteria=dict(request.criteria)),
        }
        if request.include_play_safe:
            questions["play_safe"] = Noul(
                instructions="Should the player play carefully right now rather than aggressively?"
            )
        return await self._client.system_one(
            state=request.state,
            questions=questions,
            model=self.model,
            retry=RetryPolicy(max_retries=0, timeout=request.timeout_s),
            timeout=request.timeout_s,
        )

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        close = getattr(client, "__aexit__", None)
        if close is not None:
            await close(None, None, None)


def _from_response(response: Any, request: JevRequest, latency_s: float, fallback_model: str) -> JevResult:
    model = str(getattr(response, "model", "") or fallback_model)
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None) if usage is not None else None
    output_tokens = getattr(usage, "output_tokens", None) if usage is not None else None
    choices = getattr(response, "choices", {}) or {}
    answer = choices.get(request.question_id)
    choice = str(getattr(answer, "choice", "") or "")
    confidence = float(getattr(answer, "confidence", 0.0) or 0.0)
    raw_probs = getattr(answer, "probabilities", {}) or {}
    probabilities = {str(key): float(value) for key, value in dict(raw_probs).items()}
    play_safe = None
    if request.include_play_safe:
        nouls = getattr(response, "nouls", {}) or {}
        noul = nouls.get("play_safe")
        if noul is not None:
            play_safe = float(getattr(noul, "noul", 0.0))
    return JevResult(
        ok=bool(choice),
        kind=request.kind,
        model=model,
        choice=choice,
        probabilities=probabilities,
        confidence=confidence,
        play_safe=play_safe,
        latency_s=latency_s,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        option_order=list(request.option_order),
        state=dict(request.state),
        criteria=dict(request.criteria),
        built_mono=request.built_mono,
        snapshot_t_ms=request.snapshot_t_ms,
        error="" if choice else "empty choice",
    )
