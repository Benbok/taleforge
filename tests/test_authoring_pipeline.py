import asyncio
from types import SimpleNamespace

from sqlalchemy import select

from app.agents.llm import LLMReply, ToolCall
from app.core.authoring import jobs
from app.core.authoring.contracts import AuthorProjectCreate
from app.core.authoring.projects import author_write, create_project
from app.core.authoring.runner import AuthorRunner
from app.db.models import AuthorJob, AuthorProject, CampaignSecret, LlmCall
from app.db.session import make_engine, make_sessionmaker
from tests.authoring_helpers import author

OVERVIEW = "Остров туманов. " + "Рыбацкие деревни живут между приливами, а в тумане слышна песня. " * 4
LORE = {
    "overview": OVERVIEW,
    "era_and_magic": "Позднее средневековье, магия редка и пугает.",
    "regions": [
        {"id": "reg_coast", "name": "Берег", "description": "Скалы"},
        {"id": "reg_deep", "name": "Глубь", "description": "Пещеры"},
    ],
    "history": [{"when": f"{i} век назад", "event": f"событие {i}"} for i in range(4)],
    "factions": [
        {"name": "Рыбаки", "goal": "выжить", "relations": "боятся культа"},
        {"name": "Культ", "goal": "разбудить спящего", "relations": "враги всех"},
    ],
    "figures": [
        {"name": "Ирса", "role": "жрица", "motive": "голос"},
        {"name": "Бертольд", "role": "смотритель", "motive": "долг"},
    ],
    "current_situation": "Корабли пропадают.",
    "mysteries": ["Кто поёт", "Что спит"],
    "tone": "мрачный",
    "taboos": [],
}


class Llm:
    def __init__(self, args=None, cost=0.01):
        self.args = LORE if args is None else args
        self.cost = cost
        self.calls = 0

    async def complete(self, messages, **kw):
        self.calls += 1
        call = ToolCall(id=f"tc{self.calls}", name="submit_world_lore", arguments=self.args)
        return LLMReply(
            text="", tool_calls=[call], model="m", tokens_in=10, tokens_out=20, cost=self.cost, cost_known=True
        )


def _run(settings, body, *, budget=1.0, llm=None):
    async def go():
        engine = make_engine(settings.database_url)
        maker = make_sessionmaker(engine)
        try:
            async with maker() as s:
                owner = await author(s)
                project = await create_project(s, owner, AuthorProjectCreate(title="W", budget_usd=budget))
                await s.commit()
                pid = project.id
            svc = SimpleNamespace(maker=maker, llm=llm or Llm(), bus=None)
            await body(maker, svc, pid)
        finally:
            await engine.dispose()

    asyncio.run(go())


async def _request(maker, pid, stage, key, **kw):
    async with maker() as s:
        project = await s.get(AuthorProject, pid)
        receipt = await jobs.request_stage(s, project, stage, None, project.draft_revision, key, **kw)
        await s.commit()
        return receipt


def test_lore_stage_saves_structured_setting_and_cost(settings):
    async def body(maker, svc, pid):
        receipt = await _request(maker, pid, "lore", "k1")
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            job = await s.get(AuthorJob, receipt.job_id)
            assert job.status == "ready", job.error_code
            project = await s.get(AuthorProject, pid)
            secret = await s.get(CampaignSecret, project.workspace_campaign_id)
            assert secret.setting["lore"]["overview"] == OVERVIEW
            assert "lore" in project.dependencies
            call = await s.scalar(select(LlmCall).where(LlmCall.author_job_id == job.id))
            assert call.purpose == "lore"
            view = await jobs.stage_view(s, pid, full=False)
            assert view.spent_usd > 0 and view.content is None

    _run(settings, body)


def test_ready_stage_is_not_rerun_and_edit_invalidates_nothing_extra(settings):
    async def body(maker, svc, pid):
        await _request(maker, pid, "lore", "k1")
        runner = AuthorRunner(svc)
        await runner.run_due()
        again = await _request(maker, pid, "lore", "k2")
        assert again.status == "ready"
        await runner.run_due()
        assert svc.llm.calls == 1

    _run(settings, body)


def test_invalid_lore_fails_without_overwriting_previous(settings):
    async def body(maker, svc, pid):
        await _request(maker, pid, "lore", "k1")
        await AuthorRunner(svc).run_due()
        svc.llm.args = {"overview": "коротко"}
        receipt = await _request(maker, pid, "lore", "k2", regenerate=True)
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            assert (await s.get(AuthorJob, receipt.job_id)).status == "failed"
            project = await s.get(AuthorProject, pid)
            secret = await s.get(CampaignSecret, project.workspace_campaign_id)
            assert secret.setting["lore"]["overview"] == OVERVIEW

    _run(settings, body)


def test_exhausted_budget_blocks_before_the_call(settings):
    async def body(maker, svc, pid):
        receipt = await _request(maker, pid, "lore", "k1")
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            job = await s.get(AuthorJob, receipt.job_id)
            assert (job.status, job.error_code) == ("blocked", "budget_exhausted")
        assert svc.llm.calls == 0

    _run(settings, body, budget=0.001)


def test_plot_reuses_architect_without_intro(settings, monkeypatch):
    seen = {}

    async def fake_generate(svc, cid, note="", structure_id=None, **kw):
        seen.update(kw)
        return "plan_1"

    monkeypatch.setattr("app.agents.architect.generate", fake_generate)

    async def body(maker, svc, pid):
        await _request(maker, pid, "lore", "k1")
        await AuthorRunner(svc).run_due()
        receipt = await _request(maker, pid, "plot", "k2")
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            job = await s.get(AuthorJob, receipt.job_id)
            assert job.status == "ready" and job.result == {"plan_version_id": "plan_1"}
        assert seen["prepare_intro"] is False and seen["author_job_id"] == receipt.job_id

    _run(settings, body)


def test_edit_during_run_marks_job_stale(settings):
    async def body(maker, svc, pid):
        receipt = await _request(maker, pid, "lore", "k1")

        class Editing(Llm):
            async def complete(self, messages, **kw):
                async with maker() as s:  # автор меняет анкету, пока модель думает
                    project = await s.get(AuthorProject, pid)
                    from app.db.models import Campaign

                    world = await s.get(Campaign, project.workspace_campaign_id)
                    world.brief = {"genre": "новый"}
                    await author_write(s, project, project.draft_revision)
                    await s.commit()
                return await super().complete(messages, **kw)

        svc.llm = Editing()
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            assert (await s.get(AuthorJob, receipt.job_id)).status == "stale"
            project = await s.get(AuthorProject, pid)
            assert "lore" not in (project.dependencies or {})

    _run(settings, body)


def test_invalid_lore_is_retried_once_with_errors_and_both_calls_are_billed(settings):
    async def body(maker, svc, pid):
        svc.llm.args = {"overview": "коротко"}
        receipt = await _request(maker, pid, "lore", "k1")
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            assert (await s.get(AuthorJob, receipt.job_id)).error_code == "lore_invalid"
            calls = list(await s.scalars(select(LlmCall).where(LlmCall.author_job_id == receipt.job_id)))
            assert len(calls) == 2 and all(c.error for c in calls)
        assert svc.llm.calls == 2

    _run(settings, body)


def test_plot_prompt_receives_authored_lore(settings):
    from app.agents.architect import build_input
    from app.db.models import Campaign
    from tests.test_authoring_materialization import _prepared_project, _with_maker

    pid, cid = _prepared_project(settings)

    async def body(maker):
        async with maker() as s:
            (await s.get(CampaignSecret, cid)).setting = {"lore": LORE}
            await s.commit()
            prompt, _sid = await build_input(s, await s.get(Campaign, cid))
        assert "Мир автора" in prompt and "Ирса" in prompt and "Кто поёт" in prompt

    _with_maker(settings, body)


def test_transient_network_error_is_retried(settings, monkeypatch):
    from app.agents.llm import LLMError
    from app.core.authoring import lore

    real_sleep = lore.asyncio.sleep

    async def no_wait(*_):
        await real_sleep(0)

    monkeypatch.setattr(lore.asyncio, "sleep", no_wait)

    class Flaky(Llm):
        async def complete(self, messages, **kw):
            self.calls += 1
            if self.calls == 1:
                raise LLMError("Cannot connect to host generativelanguage.googleapis.com:443")
            return await super().complete(messages, **kw)

    async def body(maker, svc, pid):
        svc.llm = Flaky()
        receipt = await _request(maker, pid, "lore", "k1")
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            assert (await s.get(AuthorJob, receipt.job_id)).status == "ready"
            calls = list(await s.scalars(select(LlmCall).where(LlmCall.author_job_id == receipt.job_id)))
            assert [bool(c.error) for c in calls] == [True, False]

    _run(settings, body)
