"""Инструменты звука (design/audio-mixer.md): мастер называет настроение музыки, трек подбирает движок.

Доступны, только когда владелец включил звук в кампании и в библиотеке есть музыка (``app.core.audio.enabled``).
"""

from __future__ import annotations

import copy
import time

from pydantic import BaseModel, Field

from app.core import audio
from app.tools.registry import ToolContext, ToolError, tool

AUDIO_TOOLS = ("set_music", "play_sfx")


class MusicArgs(BaseModel):
    mood: str = Field(description="настроение сцены; off — тишина")
    reason: str = Field(description="одна строка для журнала: почему музыка меняется")


class SfxArgs(BaseModel):
    sfx: str = Field(description="id эффекта")


def _need(ctx: ToolContext) -> None:
    if not audio.enabled(ctx.campaign):
        raise ToolError("звук в этой кампании выключен или в библиотеке нет музыки")


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
    "сам. Не больше двух за ход.",
    SfxArgs,
    ids={"sfx": "audio:sfx"},
    closes=False,
)
async def play_sfx(ctx: ToolContext, a: SfxArgs) -> dict:
    _need(ctx)
    t = audio.library().get(a.sfx)
    if t is None or a.sfx not in audio.choices(ctx.campaign, "sfx"):
        raise ToolError(f"нет эффекта {a.sfx}; допустимо: {', '.join(audio.choices(ctx.campaign, 'sfx'))}")
    if len(ctx.audio) >= audio.MAX_SFX:
        raise ToolError(f"не больше {audio.MAX_SFX} эффектов за ход")
    audio.cue(ctx, t)
    await ctx.record("play_sfx", payload={"sfx": t.id})
    return {"sfx": t.id, "when": "вместе с текстом хода"}
