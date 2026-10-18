"""The adventure's recorded intro, prepared in the author workspace.

The same text and recording a game would otherwise prepare on its own (``prelude.INTRO_KEY``): written once by
the master's model, voiced by the voice the author picks — local Voice Studio (free) or cloud Gemini — and
copied into every game launched from the adventure, so games do not pay for it again.
"""

import asyncio
import shutil
from pathlib import Path

from app.agents import prelude, voiceover
from app.agents.architect import model_of
from app.db.models import AuthorProject, Campaign, CampaignSecret, LlmCall

PROVIDERS = ("voicestudio", "gemini", "none")


class IntroError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def encode(provider: str, voice: str | None, rewrite: bool) -> str:
    return f"{provider}|{voice or ''}|{'rewrite' if rewrite else 'revoice'}"


def decode(target: str) -> tuple[str, str | None, bool]:
    provider, voice, mode = (target.split("|") + ["", "", ""])[:3]
    if provider not in PROVIDERS:
        raise IntroError("unknown_provider")
    return provider, voice or None, mode != "revoice"


def voice_dir(media_dir: Path, campaign_id: str) -> Path:
    return Path(media_dir) / "voice" / campaign_id


def drop_voices(media_dir: Path, campaign_id: str, voices: list[dict] | None) -> None:
    folder = voice_dir(media_dir, campaign_id)
    for v in voices or []:
        for f in folder.glob(f"{v.get('id')}.*"):
            f.unlink(missing_ok=True)


def copy_voices(media_dir: Path, source_id: str, target_id: str, voices: list[dict]) -> list[dict]:
    """Recordings of the published intro into a new game's folder: the client reads voices per campaign."""
    src, dst = voice_dir(media_dir, source_id), voice_dir(media_dir, target_id)
    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    for v in voices:
        files = list(src.glob(f"{v.get('id')}.*"))
        for f in files:
            shutil.copyfile(f, dst / f.name)
        if files:
            copied.append(v)
    return copied


async def prepare(svc, project_id: str, world_id: str, job_id: str, target: str) -> dict:
    """Write (or keep) the text, then voice it by the chosen source. Returns what was stored."""
    provider, voice, rewrite = decode(target)
    media_dir = Path(getattr(svc, "media_dir", None) or "media")
    async with svc.maker() as s:
        world = await s.get(Campaign, world_id)
        cfg, plan = await prelude._ai_plan(s, world)
        if cfg is None:
            raise IntroError("no_plot")
        secret = await s.get(CampaignSecret, world_id)
        old = dict(((secret.setting if secret else None) or {}).get(prelude.INTRO_KEY) or {})
        _provider, model, api_base, temperature = await model_of(s, world)
        messages = prelude._intro_messages(world, cfg, plan)
        await s.rollback()
    text = "" if rewrite else str(old.get("text") or "")
    if not text:
        call = LlmCall(campaign_id=world_id, purpose="campaign_intro", model=model, author_job_id=job_id)
        text = await prelude.write_intro(svc, messages, call, api_base, temperature)
        if not text:
            raise IntroError("intro_not_written")
    voices: list[dict] = []
    tts = getattr(svc, "tts", None)
    if provider != "none":
        if tts is None or not tts.get_engine(provider).enabled:
            raise IntroError("voice_unavailable")

        async def synth(part: str) -> dict | None:
            return await tts.voice_for_narration(media_dir, world_id, part, provider=provider, voice_name=voice)

        job = voiceover.VoiceJob(synth, prelude.clean_story)
        voices = [v for v in await asyncio.gather(*job.finish(text)) if v]
        if not voices:
            raise IntroError("voice_failed")
    drop_voices(media_dir, world_id, old.get("voices"))  # the previous recording is replaced only on success
    stored = {
        "text": text,
        "voices": voices,
        "version": plan.get("version"),
        "provider": provider,
        "voice": voice,
        "parts": len(voiceover.split(text)),
    }
    async with svc.maker() as s:
        secret = await s.get(CampaignSecret, world_id)
        secret.setting = {**(secret.setting or {}), prelude.INTRO_KEY: stored}
        await s.commit()
    return {"provider": provider, "voices": len(voices), "parts": stored["parts"], "chars": len(text)}


async def set_text(session, project: AuthorProject, text: str) -> dict:
    """The author's own text: the old recording no longer matches it and is dropped."""
    secret = await session.get(CampaignSecret, project.workspace_campaign_id)
    plan = (secret.plot if secret else None) or {}
    old = dict(((secret.setting if secret else None) or {}).get(prelude.INTRO_KEY) or {})
    stored = {**old, "text": text.strip(), "voices": [], "version": plan.get("version")}
    secret.setting = {**(secret.setting or {}), prelude.INTRO_KEY: stored}
    return old
