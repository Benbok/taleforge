# ruff: noqa: F811
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.agents.llm import LLMReply
from app.agents.prelude import INTRO_KEY
from app.core.authoring import jobs
from app.core.authoring.intro import copy_voices, encode, set_text
from app.core.authoring.runner import AuthorRunner
from app.db.models import AuthorJob, AuthorProject, CampaignSecret, LlmCall
from app.gateway.coordination import InMemoryCoordination
from tests.test_authoring_materialization import _prepared_project, _with_maker, homed_plan

INTRO = "Туман стелется над бухтой. Колокол маяка молчит третью ночь. Где-то внизу поют."


class Llm:
    def __init__(self):
        self.calls = 0

    async def complete(self, messages, **kw):
        self.calls += 1
        return LLMReply(text=INTRO, model="m", tokens_in=50, tokens_out=40, cost=0.0007, cost_known=True)


class Engine:
    def __init__(self, enabled):
        self.enabled = enabled


class Tts:
    """Local Voice Studio is up, the cloud is not configured: the author's choice decides."""

    def __init__(self):
        self.used: list[str] = []

    def get_engine(self, provider):
        return Engine(provider == "voicestudio")

    async def voice_for_narration(self, media_dir, campaign_id, text, provider=None, voice_name=None):
        self.used.append(provider)
        folder = Path(media_dir) / "voice" / campaign_id
        folder.mkdir(parents=True, exist_ok=True)
        vid = f"v{len(self.used):016x}"
        (folder / f"{vid}.wav").write_bytes(b"RIFF")
        return {"id": vid, "duration": 1.5}


def svc_for(maker, tmp_path):
    return SimpleNamespace(
        maker=maker, llm=Llm(), tts=Tts(), media_dir=tmp_path, bus=None, coordination=InMemoryCoordination()
    )


async def request(maker, pid, target, key):
    async with maker() as s:
        project = await s.get(AuthorProject, pid)
        receipt = await jobs.request_stage(s, project, "intro", target, project.draft_revision, key, regenerate=True)
        await s.commit()
        return receipt.job_id


async def stored(maker, cid):
    async with maker() as s:
        return dict(((await s.get(CampaignSecret, cid)).setting or {}).get(INTRO_KEY) or {})


def test_intro_is_written_once_voiced_locally_and_billed_to_the_project(settings, tmp_path):
    pid, cid = _prepared_project(settings, homed_plan())

    async def body(maker):
        svc = svc_for(maker, tmp_path)
        job_id = await request(maker, pid, encode("voicestudio", "narrator", rewrite=True), "i1")
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            job = await s.get(AuthorJob, job_id)
            assert job.status == "ready", job.error_code
            call = await s.scalar(select(LlmCall).where(LlmCall.author_job_id == job_id))
            assert call.purpose == "campaign_intro"
        intro = await stored(maker, cid)
        assert intro["text"] == INTRO and intro["provider"] == "voicestudio" and intro["voice"] == "narrator"
        assert intro["voices"] and set(svc.tts.used) == {"voicestudio"}
        first = intro["voices"]
        # переозвучить без нового текста: модель не вызывается, прежние записи заменяются
        await request(maker, pid, encode("voicestudio", "other", rewrite=False), "i2")
        await AuthorRunner(svc).run_due()
        again = await stored(maker, cid)
        assert svc.llm.calls == 1 and again["text"] == INTRO and again["voice"] == "other"
        assert not list((tmp_path / "voice" / cid).glob(f"{first[0]['id']}.*"))

    _with_maker(settings, body)


def test_unavailable_cloud_voice_fails_and_keeps_the_previous_intro(settings, tmp_path):
    pid, cid = _prepared_project(settings, homed_plan())

    async def body(maker):
        svc = svc_for(maker, tmp_path)
        await request(maker, pid, encode("none", None, rewrite=True), "i1")
        await AuthorRunner(svc).run_due()
        assert (await stored(maker, cid))["voices"] == []
        job_id = await request(maker, pid, encode("gemini", None, rewrite=False), "i2")
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            job = await s.get(AuthorJob, job_id)
            assert (job.status, job.error_code) == ("failed", "voice_unavailable")
        assert (await stored(maker, cid))["text"] == INTRO

    _with_maker(settings, body)


def test_own_text_drops_the_old_recording_and_voices_copy_into_a_game(settings, tmp_path):
    pid, cid = _prepared_project(settings, homed_plan())

    async def body(maker):
        svc = svc_for(maker, tmp_path)
        await request(maker, pid, encode("voicestudio", None, rewrite=True), "i1")
        await AuthorRunner(svc).run_due()
        voices = (await stored(maker, cid))["voices"]
        copied = copy_voices(tmp_path, cid, "c_game", voices)
        assert copied == voices and list((tmp_path / "voice" / "c_game").glob("*.wav"))
        async with maker() as s:
            await set_text(s, await s.get(AuthorProject, pid), "Своё вступление автора.")
            await s.commit()
        intro = await stored(maker, cid)
        assert intro["text"] == "Своё вступление автора." and intro["voices"] == []

    _with_maker(settings, body)
