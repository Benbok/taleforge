import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents.author_editor import apply_proposal, propose
from app.agents.llm import LLMError, LLMReply
from app.core.authoring.contracts import AuthorProjectCreate, EditRequest
from app.core.authoring.edits import EditError, apply_edits
from app.core.authoring.projects import create_project
from app.core.campaigns import Conflict
from app.db.models import AuthorProject, CampaignSecret, LlmCall
from app.db.session import make_engine, make_sessionmaker
from tests.authoring_helpers import author
from tests.test_authoring_edits import patch, sketch_plan

RENAME = {"operations": [{"op": "update_plot_object", "ref": "npc_a", "fields": {"name": "Лис-старик"}}]}


class Llm:
    def __init__(self, text=None, error=False):
        self.text = json.dumps(RENAME, ensure_ascii=False) if text is None else text
        self.error = error

    async def complete(self, messages, **kw):
        if self.error:
            raise LLMError("недоступна")
        return LLMReply(text=self.text, model="m", tokens_in=5, tokens_out=5, cost=0.001, cost_known=True)


def _run(settings, body, llm=None):
    async def go():
        engine = make_engine(settings.database_url)
        maker = make_sessionmaker(engine)
        try:
            async with maker() as s:
                owner = await author(s)
                project = await create_project(s, owner, AuthorProjectCreate(title="W", budget_usd=1.0))
                (await s.get(CampaignSecret, project.workspace_campaign_id)).plot = sketch_plan()
                await s.commit()
                pid = project.id
            await body(maker, SimpleNamespace(maker=maker, llm=llm or Llm()), pid)
        finally:
            await engine.dispose()

    asyncio.run(go())


async def state(maker, pid):
    async with maker() as s:
        project = await s.get(AuthorProject, pid)
        secret = await s.get(CampaignSecret, project.workspace_campaign_id)
        return project.draft_revision, secret.plot


def test_proposal_does_not_mutate_and_apply_uses_the_same_validator(settings):
    async def body(maker, svc, pid):
        rev, plan = await state(maker, pid)
        proposal = await propose(svc, pid, EditRequest(instruction="переименуй лиса", base_revision=rev))
        assert await state(maker, pid) == (rev, plan)  # предложение ничего не меняет
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            result = await apply_proposal(s, project, proposal, "k1")
            await s.commit()
        assert result.applied
        assert (await state(maker, pid))[1]["npcs"][0]["name"] == "Лис-старик"
        async with maker() as s:
            call = await s.scalar(select(LlmCall).where(LlmCall.purpose == "author_edit"))
            assert call is not None and call.error is None

    _run(settings, body)


def test_stale_proposal_is_a_conflict(settings):
    async def body(maker, svc, pid):
        rev, _plan = await state(maker, pid)
        proposal = await propose(svc, pid, EditRequest(instruction="x", base_revision=rev))
        async with maker() as s:  # автор успевает изменить черновик вручную
            project = await s.get(AuthorProject, pid)
            await apply_edits(s, project, patch({"op": "set_lore", "fields": {"tone": "мрачный"}}), rev, "manual")
            await s.commit()
        before = await state(maker, pid)
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            with pytest.raises(Conflict):
                await apply_proposal(s, project, proposal, "k2")
            await s.rollback()
        assert await state(maker, pid) == before
        with pytest.raises(Conflict):  # и новый запрос по старой ревизии
            await propose(svc, pid, EditRequest(instruction="x", base_revision=rev))

    _run(settings, body)


@pytest.mark.parametrize(
    "llm", [Llm(error=True), Llm(text="не json"), Llm(text='{"operations":[{"op":"fight","who":"x"}]}')]
)
def test_failed_or_invalid_proposal_leaves_draft_untouched(settings, llm):
    async def body(maker, svc, pid):
        before = await state(maker, pid)
        with pytest.raises(EditError):
            await propose(svc, pid, EditRequest(instruction="сделай что-нибудь", base_revision=before[0]))
        assert await state(maker, pid) == before

    _run(settings, body, llm=llm)


def test_proposal_with_unsafe_field_is_rejected_by_the_manual_validator(settings):
    bad = json.dumps({"operations": [{"op": "update_plot_object", "ref": "npc_a", "fields": {"template_id": "x"}}]})

    async def body(maker, svc, pid):
        before = await state(maker, pid)
        with pytest.raises(EditError):
            await propose(svc, pid, EditRequest(instruction="x", base_revision=before[0]))
        assert await state(maker, pid) == before

    _run(settings, body, llm=Llm(text=bad))
