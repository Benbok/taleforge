"""Общее вступление готового приключения: одно на все кампании по модулю, проверенное админом.

Вступление ко всей кампании героев не касается (о них — знакомство отряда при старте сессии, prelude.introduce),
поэтому у кампаний по одному модулю оно одинаковое. Админ в карточке приключения создаёт черновик (текст и
голос), читает и слушает его, пересоздаёт при желании и сохраняет. Кампании берут только сохранённое: без него
вступление пишет сама кампания, как раньше.

Хранится в ``media/modules/<id>/intro.json``: ``saved`` — сохранённое по зацепке книги
``{text, provider, voice, voices}``, ``draft`` — черновик ``{hook_id, provider, voice, text, voices, status, error}``.
Записи лежат как голос «кампании» ``module-<id>`` и при выдаче копируются в папку кампании под теми же id.
Характер мастера в общий текст не входит: он у каждой кампании свой.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import UTC, datetime, timedelta
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
NO_HOOK = "-"


STALE_MIN = 30  # черновик «в работе» дольше этого — прерван перезапуском сервера


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ago(minutes: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


class IntroError(Exception):
    pass


def store(module_id: str) -> str:
    """Под этим id лежат записи модуля в media/voice."""
    return f"module-{module_id}"


def _path(media_dir: Path, module_id: str) -> Path:
    return Path(media_dir) / "modules" / module_id / CACHE


def load(media_dir: Path, module_id: str) -> dict:
    try:
        data = json.loads(_path(media_dir, module_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    draft = data.get("draft")
    if draft and draft.get("status") == "working" and (draft.get("started_at") or "") < _ago(STALE_MIN):
        draft = {**draft, "status": "failed", "error": "создание прервалось (сервер перезапускали): создайте заново"}
    return {"saved": data.get("saved") or {}, "draft": draft}


def _write(media_dir: Path, module_id: str, data: dict) -> None:
    path = _path(media_dir, module_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _drop_voices(media_dir: Path, module_id: str, voices: list[dict] | None) -> None:
    folder = voice_dir(Path(media_dir), store(module_id))
    for v in voices or []:
        for f in folder.glob(f"{v.get('id')}.*"):
            f.unlink(missing_ok=True)


def forget(media_dir: Path, module_id: str) -> None:
    """Удалённый модуль уносит и записи своего вступления."""
    shutil.rmtree(voice_dir(Path(media_dir), store(module_id)), ignore_errors=True)


def hook_of(plan: dict | None) -> str:
    return ((plan or {}).get("module_hook") or {}).get("id") or NO_HOOK


def voice_of(svc, provider: str | None, voice: str | None) -> tuple[str, str | None]:
    """Провайдер и голос с подставленными умолчаниями: «голос не выбран» и голос по умолчанию — один голос."""
    tts = getattr(svc, "tts", None)
    p = provider or getattr(tts, "default_provider", None) or DEFAULT_PROVIDER
    engine = tts.get_engine(p) if tts is not None and hasattr(tts, "get_engine") else None
    return p, voice or getattr(engine, "voice", None)


def saved_for(media_dir: Path, module_id: str, hook: str) -> dict | None:
    entry = load(media_dir, module_id)["saved"].get(hook)
    return entry if entry and entry.get("text") else None


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


async def _adventure(svc, module_id: str):
    async with svc.maker() as s:
        m = await s.get(AdventureModule, module_id)
        if m is None or not m.pack_id:
            raise IntroError("приключение ещё не опубликовано")
        pack = await s.get(ContentPack, (m.pack_id, m.pack_version))
        catalog = (await load_catalog(s, await resolve_chain(s, pack))).view(False)
        title = m.title
    adv = adventure.adventure_of(catalog)
    if adv is None:
        raise IntroError("в пакете приключения нет записи adventure: опубликуйте его заново")
    return adv, title


async def hooks(svc, module_id: str) -> list[dict]:
    adv, _ = await _adventure(svc, module_id)
    return [{"id": h["id"], "title": h.get("title") or h["id"]} for h in adventure.hooks(adv)]


def start_draft(media_dir: Path, module_id: str, hook_id: str | None, provider: str | None, voice: str | None) -> dict:
    """Черновик «в работе»: старый несохранённый черновик и его записи уходят."""
    data = load(media_dir, module_id)
    old = data["draft"] or {}
    if old.get("status") == "working":
        raise IntroError("черновик вступления ещё готовится: дождитесь его")
    _drop_voices(media_dir, module_id, old.get("voices"))
    data["draft"] = {
        "hook_id": hook_id,
        "provider": provider,
        "voice": voice,
        "text": "",
        "voices": [],
        "status": "working",
        "error": None,
        "started_at": now_iso(),
    }
    _write(media_dir, module_id, data)
    return data


async def make_draft(svc, module_id: str, text: str | None = None) -> None:
    """Пишет черновик, заведённый start_draft: текст (если админ не дал свой) и голос по частям."""
    media_dir = Path(svc.media_dir)
    draft = dict(load(media_dir, module_id)["draft"] or {})
    try:
        adv, title = await _adventure(svc, module_id)
        plan, hook = adventure.start_plan(adv, draft.get("hook_id"))
        draft["hook_id"] = hook["id"] if hook else NO_HOOK
        provider, voice = voice_of(svc, draft.get("provider"), draft.get("voice"))
        draft["provider"], draft["voice"] = provider, voice
        tts = getattr(svc, "tts", None)
        job = None
        if tts is not None and tts.get_engine(provider).enabled:
            sid = store(module_id)

            async def synth(part: str) -> dict | None:
                return await tts.voice_for_narration(media_dir, sid, part, provider=provider, voice_name=voice)

            job = voiceover.VoiceJob(synth, prelude.clean_story)
        text = (text or "").strip()
        if not text:
            async with svc.maker() as s:
                p = await default_model_profile(s)
            model, api_base, temperature = (
                (model_for(p.provider, p.model or None), p.api_base, p.temperature) if p else (model_for(), None, 0.8)
            )
            call = LlmCall(campaign_id=None, purpose="module_intro", model=model)
            msgs = prelude.intro_messages(plan.get("title") or title, plan.get("public_intro") or "", None, plan)
            text = await prelude.write_intro(svc, msgs, call, api_base, temperature, job=job)
            if not text:
                raise IntroError(f"модель не написала вступление: {call.error or 'пустой ответ'}"[:500])
        voices = [v for v in await asyncio.gather(*job.finish(text)) if v] if job is not None else []
        draft.update(text=text, voices=voices, status="ready")
        if job is None:
            draft["error"] = "озвучка выключена: у выбранного источника нет ключа или он не подключён"
        elif len(voices) < len(voiceover.split(text)):
            draft["error"] = "часть записей не озвучилась: пересоздайте голос"
    except IntroError as e:
        draft.update(status="failed", error=str(e))
    except Exception as e:  # noqa: BLE001 — сбой черновика не должен ронять сервер
        log.exception("черновик вступления модуля %s не готов", module_id)
        draft.update(status="failed", error=f"внутренняя ошибка: {e}"[:500])
    data = load(media_dir, module_id)
    data["draft"] = draft
    _write(media_dir, module_id, data)


def save_draft(media_dir: Path, module_id: str) -> dict:
    """Черновик становится вступлением своей зацепки для новых кампаний; прежнее уходит (у кампаний копии)."""
    data = load(media_dir, module_id)
    d = data["draft"] or {}
    if d.get("status") != "ready" or not d.get("text"):
        raise IntroError("сохранять нечего: сначала создайте вступление и дождитесь его")
    hook = d.get("hook_id") or NO_HOOK
    _drop_voices(media_dir, module_id, (data["saved"].get(hook) or {}).get("voices"))
    data["saved"][hook] = {
        "text": d["text"],
        "provider": d.get("provider"),
        "voice": d.get("voice"),
        "voices": d.get("voices") or [],
        "saved_at": now_iso(),
    }
    data["draft"] = None
    _write(media_dir, module_id, data)
    return data


def discard_draft(media_dir: Path, module_id: str) -> dict:
    data = load(media_dir, module_id)
    d = data["draft"] or {}
    if d.get("status") == "working":
        raise IntroError("черновик ещё готовится: дождитесь его")
    _drop_voices(media_dir, module_id, d.get("voices"))
    data["draft"] = None
    _write(media_dir, module_id, data)
    return data


async def prepare_module(svc, module_id: str) -> None:
    """После первой публикации: черновик для зацепки и голоса по умолчанию — админу остаётся прочитать,
    послушать и сохранить."""
    media_dir = Path(svc.media_dir)
    data = load(media_dir, module_id)
    if data["saved"] or data["draft"]:
        return
    try:
        start_draft(media_dir, module_id, None, DEFAULT_PROVIDER, None)
    except IntroError:
        return
    await make_draft(svc, module_id)
