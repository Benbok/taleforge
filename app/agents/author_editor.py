"""Bounded AI editor for author drafts. It only proposes a typed patch; applying goes through apply_edits."""

import json
import re

from pydantic import ValidationError

from app.agents.architect import model_of
from app.agents.llm import LLMError
from app.core.authoring import jobs
from app.core.authoring.contracts import DraftPatch, EditProposal, EditRequest
from app.core.authoring.edits import EditError, apply_edits, preview_edit
from app.core.campaigns import Conflict
from app.core.llm_diagnostics import reply_metrics
from app.db.models import AuthorProject, Campaign, CampaignSecret, LlmCall

MAX_TOKENS = 2000
ESTIMATE_USD = 0.05
SYSTEM = (
    "Ты помощник автора настольной кампании. Предложи правку черновика строго JSON-объектом "
    '{"operations": [...]} из разрешённых операций: set_lore, update_plot_object, update_item, set_placement, '
    "upsert_route, remove_object, edit_map. Другие действия (бой, перемещение героев, игровая история) "
    "недоступны. Без пояснений и без markdown.\nСхема: "
)


def _outline(plan: dict) -> dict:
    keys = ("locations", "npcs", "antagonists", "items", "routes")
    return {k: [{f: x.get(f) for f in ("id", "ref", "name") if f in x} for x in plan.get(k) or []] for k in keys}


async def propose(svc, project_id: str, request: EditRequest) -> EditProposal:
    """Never mutates the draft: a refused, failed or invalid answer leaves the project as it was."""
    async with svc.maker() as s:
        project = await s.get(AuthorProject, project_id)
        if project.draft_revision != request.base_revision:
            raise Conflict("stale_revision")
        world = await s.get(Campaign, project.workspace_campaign_id)
        secret = await s.get(CampaignSecret, world.id)
        plan = dict((secret.plot if secret else None) or {})
        setting = dict((secret.setting if secret else None) or {})
        spent, _ = await jobs.spend(s, project_id)
        if project.budget_usd is not None and spent + ESTIMATE_USD > project.budget_usd:
            raise Conflict("budget_exhausted")
        _provider, model, api_base, temperature = await model_of(s, world)
        world_id = world.id
        await s.rollback()
    system = SYSTEM + json.dumps(DraftPatch.model_json_schema(by_alias=True), ensure_ascii=False)
    user = f"Черновик: {json.dumps(_outline(plan), ensure_ascii=False)}\nЗапрос автора: {request.instruction}"
    call = LlmCall(campaign_id=world_id, purpose="author_edit", model=model)
    try:
        reply = await svc.llm.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=model,
            max_tokens=MAX_TOKENS,
            temperature=min(temperature, 0.7),
            api_base=api_base,
        )
    except LLMError as exc:
        call.error = str(exc)[:2000]
        await _save(svc, call)
        raise EditError("llm_unavailable") from exc
    call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
    call.cost, call.latency_ms = reply.cost, reply.latency_ms
    for metric, value in reply_metrics(reply).items():
        setattr(call, metric, value)
    try:
        body = re.sub(r"^```(?:json)?|```$", "", (reply.text or "").strip(), flags=re.M).strip()
        patch = DraftPatch.model_validate(json.loads(body))
        proposal = preview_edit(plan, setting, patch)  # the same validator the manual form uses
    except (ValueError, ValidationError, EditError) as exc:
        call.error = "invalid_proposal"
        await _save(svc, call)
        raise EditError("invalid_proposal") from exc
    await _save(svc, call)
    return proposal.model_copy(update={"base_revision": request.base_revision})


async def apply_proposal(session, project, proposal: EditProposal, request_key: str):
    """A proposal made against an older revision fails with Conflict (HTTP 409); nothing is applied."""
    return await apply_edits(session, project, proposal.patch, proposal.base_revision, request_key)


async def _save(svc, call: LlmCall) -> None:
    async with svc.maker() as s:
        s.add(call)
        await s.commit()
