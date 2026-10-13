"""Director LLM author, context packing, and proposal decoder (spec §11, §16, Task 13)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import jinja2
from pydantic import TypeAdapter

from app.agents.llm import LLM
from app.core.narrative.contracts import (
    AdaptationProposal,
    AuthorCallReport,
    DirectorInput,
    Ground,
    NarrativeSnapshot,
    Operation,
)

_OP_ADAPTER = TypeAdapter(Operation)

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(Path(__file__).parent / "prompts"),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)

DIRECTOR_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "propose_adaptation",
        "description": "Propose narrative adaptations based on verified player choices and world events.",
        "parameters": {
            "type": "object",
            "properties": {
                "grounds": {
                    "type": "array",
                    "description": "Grounds and evidence justifying the adaptation.",
                    "items": {"type": "object"},
                },
                "summary": {
                    "type": "string",
                    "description": "Short explanation of the proposed changes.",
                },
                "operations": {
                    "type": "array",
                    "description": "Targeted narrative operations to apply.",
                    "items": {"type": "object"},
                },
            },
            "required": ["summary", "operations"],
        },
    },
}


def _format_facts(snapshot: NarrativeSnapshot) -> str:
    lines = []
    for f in snapshot.facts:
        val = f.value if f.value is not None else "(none)"
        lines.append(f"- [{f.ref.namespace}:{f.ref.subject_id}:{f.ref.key}]: {val}")
    return "\n".join(lines)


def _format_evidence(snapshot: NarrativeSnapshot) -> str:
    lines = []
    for ev in snapshot.evidence:
        lines.append(
            f"- {ev.ref.kind}:{ev.ref.source_id} status={ev.status} result={ev.applied_result} "
            f"player_action={ev.player_action_source} targets={ev.player_action_targets}"
        )
    return "\n".join(lines)


def _format_threads(snapshot: NarrativeSnapshot) -> str:
    lines = []
    for t in snapshot.threads:
        lines.append(f"- id={t.id} status={t.status} subjects={t.subject_refs}")
    return "\n".join(lines)


def pack_director_input(
    snapshot: NarrativeSnapshot,
    *,
    token_counter: Callable[[str], int],
    max_tokens: int = 6000,
) -> DirectorInput:
    """Packs bounded prompt and schema for director author.

    Enforces context limits. If a required dependency exceeds budget, complete_for_edit is False
    and permitted_refs is empty, preventing unconstrained creative output.
    """
    sys_template = _env.get_template("director.j2")
    system_text = sys_template.render().strip()
    schema_json = json.dumps(DIRECTOR_TOOL_SCHEMA)

    base_tokens = token_counter(system_text) + token_counter(schema_json)
    if base_tokens > max_tokens:
        return DirectorInput(
            messages=(),
            tool_schema=DIRECTOR_TOOL_SCHEMA,
            permitted_refs=(),
            complete_for_edit=False,
            estimated_input_tokens=min(base_tokens, max_tokens),
        )

    # 1. Facts & required dependencies
    facts_str = _format_facts(snapshot)
    facts_tokens = token_counter(facts_str)
    if base_tokens + facts_tokens > max_tokens:
        # Required dependency did not fit: must NOT permit edits without context
        return DirectorInput(
            messages=(),
            tool_schema=DIRECTOR_TOOL_SCHEMA,
            permitted_refs=(),
            complete_for_edit=False,
            estimated_input_tokens=min(base_tokens + facts_tokens, max_tokens),
        )

    # 2. Evidence & grounds
    ev_str = _format_evidence(snapshot)
    # 3. Threads
    th_str = _format_threads(snapshot)

    actors_str = ", ".join(snapshot.actors) if snapshot.actors else "(none)"
    user_content = (
        f"Campaign actors: {actors_str}\n"
        f"Verified evidence:\n{ev_str}\n"
        f"Known facts:\n{facts_str}\n"
        f"Active threads:\n{th_str}\n"
    )

    total_tokens = base_tokens + token_counter(user_content)
    if total_tokens > max_tokens:
        # Trim user content if necessary while keeping facts
        user_content = f"Campaign actors: {actors_str}\nKnown facts:\n{facts_str}\n"
        total_tokens = base_tokens + token_counter(user_content)

    permitted = set(snapshot.actors)
    for f in snapshot.facts:
        permitted.add(f.ref.subject_id)
    for t in snapshot.threads:
        permitted.add(t.id)

    messages = (
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_content},
    )

    return DirectorInput(
        messages=messages,
        tool_schema=DIRECTOR_TOOL_SCHEMA,
        permitted_refs=tuple(sorted(permitted)),
        complete_for_edit=True,
        estimated_input_tokens=min(total_tokens, max_tokens),
    )


def decode_director_reply(
    snapshot: NarrativeSnapshot,
    arguments: dict[str, Any],
) -> AdaptationProposal:
    """Decodes director tool call arguments into validated AdaptationProposal."""
    permitted_refs = set(snapshot.actors)
    for f in snapshot.facts:
        permitted_refs.add(f.ref.subject_id)
    for t in snapshot.threads:
        permitted_refs.add(t.id)

    grounds_raw = arguments.get("grounds", [])
    parsed_grounds = []
    for g in grounds_raw:
        if isinstance(g, dict):
            parsed_grounds.append(Ground.model_validate(g))
        elif isinstance(g, Ground):
            parsed_grounds.append(g)

    summary = arguments.get("summary", "no_change")
    ops_raw = arguments.get("operations", [])
    parsed_ops = []

    for item in ops_raw:
        validated_op = _OP_ADAPTER.validate_python(item)
        target = (
            getattr(validated_op, "entity_id", None)
            or getattr(validated_op, "target_ref", None)
            or getattr(validated_op, "subject_id", None)
        )
        if isinstance(target, str) and not target.startswith("slot_") and target not in permitted_refs:
            raise ValueError(f"Target ref '{target}' is not permitted in this snapshot context")
        parsed_ops.append(validated_op)

    # If operations are proposed but grounds were empty, bind from snapshot evidence if present
    if parsed_ops and not parsed_grounds and snapshot.evidence:
        parsed_grounds.append(
            Ground(
                kind="divergence",
                evidence_refs=(snapshot.evidence[0].ref,),
                subject_refs=snapshot.actors[:1],
                confidence="explicit",
            )
        )

    return AdaptationProposal(
        schema_version=1,
        proposal_id=snapshot.proposal_id,
        source=snapshot.source,
        base=snapshot.base,
        grounds=tuple(parsed_grounds),
        summary=summary,
        operations=tuple(parsed_ops),
        read_set=snapshot.read_set,
    )


class LlmNarrativeAuthor:
    """LLM-backed narrative author producing validated proposals within token budget."""

    def __init__(
        self,
        llm: LLM,
        model_config: Any = None,
        *,
        token_counter: Callable[[str], int] = len,
        timeout_seconds: int = 90,
        call_observer: Callable[[AuthorCallReport], Awaitable[None]] | None = None,
        session_maker: Any = None,
    ) -> None:
        self._llm = llm
        self._model_config = model_config
        self._token_counter = token_counter
        self._timeout_seconds = timeout_seconds
        self._call_observer = call_observer
        self._session_maker = session_maker

    async def propose(self, snapshot: NarrativeSnapshot) -> AdaptationProposal:
        packed = pack_director_input(
            snapshot,
            token_counter=self._token_counter,
            max_tokens=6000,
        )

        if not packed.complete_for_edit:
            return AdaptationProposal(
                schema_version=1,
                proposal_id=snapshot.proposal_id,
                source=snapshot.source,
                base=snapshot.base,
                grounds=(),
                summary="Контекст не полон для редактирования (omitted context); no_change",
                operations=(),
                read_set=snapshot.read_set,
            )

        cid = snapshot.source.campaign_id
        model_name = getattr(self._model_config, "model", str(self._model_config)) if self._model_config else None
        api_base = getattr(self._model_config, "api_base", None)
        temperature = getattr(self._model_config, "temperature", 0.7)
        seat_id = None
        reserved_call_id: str | None = None

        if self._session_maker is not None:
            from app.agents.architect import model_of
            from app.core.campaigns import master_seat
            from app.db.models import Campaign, LlmCall

            async with self._session_maker() as session:
                campaign = await session.get(Campaign, cid)
                if campaign is not None:
                    # replan/ended/strict/лимит расходов проверяет NarrativePreparerAdapter до claim и до сети
                    # Модель выбирается для кампании через действующий model_of
                    _, camp_model, camp_api_base, camp_temp = await model_of(session, campaign)
                    model_name = camp_model or model_name
                    api_base = camp_api_base or api_base
                    temperature = camp_temp or temperature
                    m_seat = master_seat(campaign)
                    seat_id = m_seat.id if m_seat else None

                    # Резервируем LlmCall до сетевого вызова
                    call = LlmCall(
                        campaign_id=cid,
                        seat_id=seat_id,
                        turn_id=None,
                        purpose="director",
                        model=model_name or "default",
                    )
                    session.add(call)
                    await session.commit()
                    reserved_call_id = call.id
            # Сессия закрыта, транзакция БД не удерживается во время сетевого вызова!

        model_name = model_name or "default"
        t0 = time.perf_counter()
        error_msg: str | None = None
        reply = None

        try:
            reply = await asyncio.wait_for(
                self._llm.complete(
                    list(packed.messages),
                    model=model_name,
                    tools=[packed.tool_schema],
                    tool_choice={"type": "function", "function": {"name": "propose_adaptation"}},
                    max_tokens=4096,
                    temperature=temperature,
                    api_base=api_base,
                ),
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            error_msg = type(exc).__name__
            raise
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            tokens_in = reply.tokens_in if reply else packed.estimated_input_tokens
            tokens_out = reply.tokens_out if reply else 0

            # стоимость — от провайдера; иначе по тарифу модели. Неизвестный тариф (локальная модель) остаётся 0,
            # а ошибка сохраняется в error: она не выдаётся за бесплатный успешный вызов
            cost = float(reply.cost) if reply is not None and getattr(reply, "cost", None) else 0.0
            if not cost and (tokens_in or tokens_out):
                try:
                    import litellm

                    cin, cout = litellm.cost_per_token(
                        model=model_name, prompt_tokens=tokens_in or 0, completion_tokens=tokens_out or 0
                    )
                    cost = float(cin + cout)
                except Exception:  # noqa: BLE001 — у локальной и неизвестной модели тарифа нет
                    cost = 0.0

            report = AuthorCallReport(
                source=snapshot.source,
                author_attempt=snapshot.author_attempt,
                model=model_name,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=cost,
                latency_ms=latency_ms,
                error=error_msg,
                call_id=reserved_call_id,
            )

            # Обновление зарезервированного LlmCall в БД
            if reserved_call_id and self._session_maker:
                from app.db.models import LlmCall

                async with self._session_maker() as s_upd:
                    c_row = await s_upd.get(LlmCall, reserved_call_id)
                    if c_row:
                        c_row.tokens_in = tokens_in
                        c_row.tokens_out = tokens_out
                        c_row.cost = cost
                        c_row.latency_ms = latency_ms
                        c_row.error = error_msg
                        await s_upd.commit()

            if self._call_observer:
                await self._call_observer(report)

        tool_args: dict[str, Any] = {}
        if reply and reply.tool_calls:
            for tc in reply.tool_calls:
                if tc.name == "propose_adaptation":
                    tool_args = tc.arguments
                    break

        return decode_director_reply(snapshot, tool_args)
