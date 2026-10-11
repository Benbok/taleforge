"""Общее вступление готового приключения: одно на все кампании по модулю.

Вступление ко всей кампании героев не касается (о них — знакомство отряда при старте сессии, prelude.introduce),
поэтому у кампаний по одному модулю оно одинаковое. Текст и голос пишутся один раз — сразу после публикации
модуля — и лежат в папке модуля; новая кампания получает копию, не тратя ни вызова модели, ни синтеза.

Кэш — ``media/modules/<id>/intro.json``: ``version`` — версия пакета модуля (новая публикация сбрасывает кэш),
``texts`` — текст по зацепке книги, ``voices`` — записи по зацепке и голосу (``зацепка|провайдер|голос``).
Записи лежат как голос «кампании» ``module-<id>`` и при выдаче копируются в папку кампании под теми же id.
Характер мастера в общий текст не входит: он у каждой кампании свой.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from app.agents import prelude, voiceover
from app.agents.llm import model_for
from app.content.catalog import load_catalog, resolve_chain
from app.core import adventure
from app.core.campaigns import default_model_profile
from app.core.voice import _dir as voice_dir
from app.db.models import AdventureModule, ContentPack, LlmCall

log = logging.getLogger(__name__)

CACHE = "intro.json"
DEFAULT_PROVIDER = "gemini"  # озвучка новой кампании по умолчанию (CampaignIn.tts_provider)
_locks: dict[str, asyncio.Lock] = {}


def store(module_id: str) -> str:
    """Под этим id лежат записи модуля в media/voice."""
    return f"module-{module_id}"


def _path(media_dir: Path, module_id: str) -> Path:
    return Path(media_dir) / "modules" / module_id / CACHE


def _load(media_dir: Path, module_id: str, version: str) -> dict:
    try:
        data = json.loads(_path(media_dir, module_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if data.get("version") != version:
        return {"version": version, "texts": {}, "voices": {}}
    return data


def _save(media_dir: Path, module_id: str, data: dict) -> None:
    path = _path(media_dir, module_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _voice_key(hook: str, provider: str | None, voice: str | None) -> str:
    return f"{hook}|{provider or DEFAULT_PROVIDER}|{voice or ''}"


def forget(media_dir: Path, module_id: str) -> None:
    """Удалённый модуль уносит и своё вступление."""
    shutil.rmtree(voice_dir(Path(media_dir), store(module_id)), ignore_errors=True)


def cached(media_dir: Path, module_id: str, version: str, hook: str, provider: str | None, voice: str | None):
    """(текст, записи) из кэша без генерации: записи — None, если голоса с такими настройками ещё нет."""
    data = _load(media_dir, module_id, version)
    return data["texts"].get(hook) or "", data["voices"].get(_voice_key(hook, provider, voice))


async def ensure(
    svc,
    module_id: str,
    version: str,
    plan: dict,
    *,
    title: str,
    tts: bool,
    provider: str | None,
    voice: str | None,
    campaign_id: str | None = None,
    seat_id: str | None = None,
) -> tuple[str, list[dict]]:
    """Вступление модуля для зацепки каркаса и голоса: из кэша, а чего нет — пишется и кладётся в кэш.
    Под замком модуля: две кампании, созданные разом, не пишут его дважды."""
    hook = ((plan.get("module_hook") or {}).get("id")) or "-"
    key = _voice_key(hook, provider, voice)
    lock = _locks.setdefault(module_id, asyncio.Lock())
    async with lock:
        data = _load(svc.media_dir, module_id, version)
        if not data["texts"]:
            forget(svc.media_dir, module_id)  # записи прошлой версии модуля: у кампаний свои копии
        text = data["texts"].get(hook) or ""
        voices = data["voices"].get(key)
        if text and (voices is not None or not tts):
            return text, voices or []

        job = None
        if tts:
            sid = store(module_id)

            async def synth(part: str) -> dict | None:
                return await svc.tts.voice_for_narration(svc.media_dir, sid, part, provider=provider, voice_name=voice)

            job = voiceover.VoiceJob(synth, prelude.clean_story)

        if not text:
            async with svc.maker() as s:
                p = await default_model_profile(s)
            model, api_base, temperature = (
                (model_for(p.provider, p.model or None), p.api_base, p.temperature) if p else (model_for(), None, 0.8)
            )
            if campaign_id:  # первая кампания пишет текст на модели своего мастера
                from app.agents.architect import model_of
                from app.db.models import Campaign

                async with svc.maker() as s:
                    _, model, api_base, temperature = await model_of(s, await s.get(Campaign, campaign_id))
            call = LlmCall(campaign_id=campaign_id, seat_id=seat_id, purpose="module_intro", model=model)
            msgs = prelude.intro_messages(title, plan.get("public_intro") or "", None, plan)
            text = await prelude.write_intro(svc, msgs, call, api_base, temperature, job=job)
            if not text:
                if job is not None:
                    job.cancel()
                return "", []
        voices = [v for v in await asyncio.gather(*job.finish(text)) if v] if job is not None else []
        data["texts"][hook] = text
        if job is not None and voices:  # неудачный синтез не кэшируем: следующая кампания попробует снова
            data["voices"][key] = voices
        _save(svc.media_dir, module_id, data)
        return text, voices


def copy_voices(media_dir: Path, module_id: str, campaign_id: str, voices: list[dict]) -> list[dict]:
    """Записи модуля в папку кампании: клиент берёт голос по id в пределах своей кампании."""
    src, dst = voice_dir(Path(media_dir), store(module_id)), voice_dir(Path(media_dir), campaign_id)
    dst.mkdir(parents=True, exist_ok=True)
    out = []
    for v in voices:
        files = list(src.glob(f"{v.get('id')}.*"))
        if not files:
            log.warning("запись вступления модуля %s пропала: %s", module_id, v.get("id"))
            continue
        for f in files:
            shutil.copyfile(f, dst / f.name)
        out.append(v)
    return out


async def prepare_module(svc, module_id: str) -> bool:
    """После публикации: вступление для зацепки книги по умолчанию и голоса новой кампании по умолчанию."""
    try:
        async with svc.maker() as s:
            m = await s.get(AdventureModule, module_id)
            if m is None or not m.pack_id:
                return False
            title, version = m.title, m.pack_version
            pack = await s.get(ContentPack, (m.pack_id, m.pack_version))
            catalog = (await load_catalog(s, await resolve_chain(s, pack))).view(False)
            adv = adventure.adventure_of(catalog)
        if adv is None:
            return False
        plan, _ = adventure.start_plan(adv, None)
        tts = getattr(svc, "tts", None)
        on = bool(tts and svc.media_dir and tts.get_engine(DEFAULT_PROVIDER).enabled)
        text, _ = await ensure(
            svc,
            module_id,
            version,
            plan,
            title=plan.get("title") or title,
            tts=on,
            provider=DEFAULT_PROVIDER,
            voice=None,
        )
        return bool(text)
    except Exception:  # noqa: BLE001 — без заготовки кампания напишет вступление сама
        log.exception("вступление модуля %s не подготовлено", module_id)
        return False
