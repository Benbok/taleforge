"""Инструменты звука (design/audio-mixer.md): мастер называет настроение музыки, трек подбирает движок.

Доступность определяется флагами кампании; музыка выбирается из существующей библиотеки.
"""

from __future__ import annotations

import copy
import time
from dataclasses import replace

from pydantic import BaseModel, Field

from app.config import Settings
from app.core import audio
from app.db.models import SfxPlayback
from app.sfx.contracts import SfxInput
from app.sfx.playback import audience_of, context_of
from app.sfx.service import enqueue
from app.tools.registry import ToolContext, ToolError, tool

AUDIO_TOOLS = ("set_music", "play_sfx", "request_sfx")


class MusicArgs(BaseModel):
    mood: str = Field(description="настроение сцены; off — тишина")
    reason: str = Field(description="одна строка для журнала: почему музыка меняется")


class SfxArgs(BaseModel):
    sfx: str = Field(description="id эффекта")


def _need(ctx: ToolContext) -> None:
    if not audio.enabled(ctx.campaign):
        raise ToolError("звук в этой кампании выключен")


@tool(
    "set_music",
    "Музыка сцены: назови настроение, трек под него и под место подберёт движок. Меняй только на поворотах: "
    "новое место, раскрытая тайна, смена настроения. Начало и конец боя движок ведёт сам. off — тишина.",
    MusicArgs,
    ids={"mood": "audio:moods"},
    closes=False,
)
async def set_music(ctx: ToolContext, a: MusicArgs) -> dict:
    _need(ctx)
    sc = ctx.world.scene
    place = audio.where(ctx)  # отряд разделён: звук только этой группы
    st = audio.mixer(sc, place)
    before = copy.deepcopy(sc.state)
    if a.mood == "off":
        track, mood = None, None
    else:
        if a.mood not in audio.moods(ctx.campaign):
            raise ToolError(f"нет музыки с настроением {a.mood}; есть: {', '.join(audio.moods(ctx.campaign))}, off")
        track, mood = audio.choose(ctx, a.mood, place), a.mood
    cur = audio.current(sc, place)
    if (track.id if track else None) != (cur.id if cur else None):
        # музыка не дёргается: не чаще раза в минуту, если бой не начался и не закончился
        last = (st["changed"] or {}).get("music") or {}
        ago = time.time() - float(last.get("at", 0))
        if ago < audio.MUSIC_COOLDOWN and last.get("mode") == sc.mode and not last.get("auto"):
            raise ToolError(f"музыка сменилась {int(ago)} с назад: оставь её, меняй только на повороте сцены")
    audio.set_music(sc, track, mood, place)
    ctx.signals.add("audio")
    playing = track.title if track else "тишина"
    await ctx.record(
        "set_music",
        payload={"reason": a.reason, "mood": a.mood, "track": track.id if track else None},
        inverse=[{"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": before}],
    )
    return {"playing": playing}


@tool(
    "play_sfx",
    "Короткий звуковой эффект один раз (гром, рык, скрип двери). Эффекты боя, заклинаний и находок движок играет "
    "сам. Обычно один эффект приходится на одно действие; не больше 16 за ход.",
    SfxArgs,
    ids={"sfx": "audio:sfx"},
    closes=False,
)
async def play_sfx(ctx: ToolContext, a: SfxArgs) -> dict:
    _need(ctx)
    t = audio.library().get(a.sfx)
    if t is None or a.sfx not in audio.choices(ctx.campaign, "sfx"):
        raise ToolError(f"нет эффекта {a.sfx}; допустимо: {', '.join(audio.choices(ctx.campaign, 'sfx'))}")
    if len(ctx.audio) + len(ctx.sfx_requests) >= audio.MAX_SFX:
        raise ToolError(f"не больше {audio.MAX_SFX} эффектов за ход")
    audio.cue(ctx, t)
    await ctx.record("play_sfx", payload={"sfx": t.id})
    return {"sfx": t.id, "when": "вместе с текстом хода"}


@tool(
    "request_sfx",
    "Редкий короткий эффект сцены: описание по-английски (без речи/музыки), 1–4 секунды. "
    "Не жди результат и не запрашивай каждый служебный вызов: одно выполненное действие — один эффект. "
    "Для похожего сохранённого звука передай sound_id из библиотеки вместо description.",
    SfxInput,
    closes=False,
)
async def request_sfx(ctx: ToolContext, a: SfxInput) -> dict:
    if not audio.enabled(ctx.campaign):
        return {"status": "skipped", "reason": "звук выключен"}
    if not a.sound_id and not (ctx.campaign.settings or {}).get("sfx_enabled"):
        return {"status": "skipped", "reason": "генерация выключена в кампании"}
    if len(ctx.audio) >= audio.MAX_SFX:
        return {"status": "skipped", "reason": "лимит эффектов хода исчерпан"}
    cfg = ctx.session.info.get("settings", Settings())
    if not (ctx.campaign.settings or {}).get("sfx_enabled"):
        cfg = replace(cfg, sfx_enabled=False)  # allow existing files, never repair a miss by generating when off
    try:
        receipt = await enqueue(ctx.session, cfg, ctx.campaign.id, a, staged=True)
    except (audio.NotFound, audio.Conflict) as exc:
        return {"status": "skipped", "reason": str(exc)}
    if receipt["status"] == "skipped":
        return receipt
    context = context_of(ctx)
    row = SfxPlayback(
        campaign_id=ctx.campaign.id,
        sound_id=receipt["sound_id"],
        turn_id=ctx.turn_id,
        asset_id=receipt.get("asset_id"),
        context=context,
        audience=audience_of(ctx, context),
    )
    ctx.session.add(row)
    await ctx.session.flush()
    ctx.sfx_requests.append(row.id)
    await ctx.record("request_sfx", payload={"request_id": row.id, "sound_id": receipt["sound_id"]})
    return {**receipt, "request_id": row.id, "playback": "asynchronous"}
