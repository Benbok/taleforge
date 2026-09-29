"""Инструменты звука (design/audio-mixer.md): мастер выбирает дорожки из библиотеки, сервер хранит и рассылает.

Доступны, только когда владелец включил звук в кампании и в библиотеке есть треки (``app.core.audio.enabled``).
"""

from __future__ import annotations

import copy
import time
from typing import Literal

from pydantic import BaseModel, Field

from app.core import audio
from app.tools.registry import ToolContext, ToolError, tool

AUDIO_TOOLS = ("set_soundscape", "play_sfx")
Level = Literal["low", "mid", "high"]


class SoundscapeArgs(BaseModel):
    music: str | None = Field(None, description="мелодия: id дорожки или off; не передавай — слой не меняется")
    rhythm: str | None = Field(None, description="ритм (только ударные): id или off")
    ambience: str | None = Field(None, description="атмосфера места: id или off")
    music_level: Level | None = None
    rhythm_level: Level | None = None
    ambience_level: Level | None = None
    reason: str = Field(description="одна строка для журнала: почему звук меняется")


class SfxArgs(BaseModel):
    sfx: str = Field(description="id эффекта")


def _need(ctx: ToolContext) -> None:
    if not audio.enabled(ctx.campaign):
        raise ToolError("звук в этой кампании выключен или библиотека пуста")


@tool(
    "set_soundscape",
    "Звук сцены: мелодия, ритм и атмосфера, по одной дорожке в слое. Меняй на поворотах: начало и конец боя, "
    "новое место, раскрытая тайна, смена настроения. Не передавай слой — он не меняется; off — тишина в слое.",
    SoundscapeArgs,
    ids={"music": "audio:music", "rhythm": "audio:rhythm", "ambience": "audio:ambience"},
    closes=False,
)
async def set_soundscape(ctx: ToolContext, a: SoundscapeArgs) -> dict:
    _need(ctx)
    sc = ctx.world.scene
    lib = audio.library()
    st = audio.mixer(sc)
    before = copy.deepcopy(sc.state)
    wanted: dict[str, audio.Track | None] = {}
    for layer in audio.LOOPS:
        val = getattr(a, layer)
        if val is None:
            continue
        if val == "off":
            wanted[layer] = None
            continue
        t = lib.get(val)
        if t is None or t.layer != layer or t.id not in audio.choices(ctx.campaign, layer):
            raise ToolError(f"{layer}: нет дорожки {val}; допустимо: {', '.join(audio.choices(ctx.campaign, layer))}")
        wanted[layer] = t
    levels = {k: getattr(a, f"{k}_level") for k in audio.LOOPS if getattr(a, f"{k}_level")}
    if not wanted and not levels:
        raise ToolError("не указан ни один слой: передай music, rhythm, ambience или их громкость")

    # мелодия не дёргается: не чаще раза в минуту, если бой не начался и не закончился
    if "music" in wanted:
        cur = st.get("music")
        changing = (wanted["music"].id if wanted["music"] else None) != (cur["track"] if cur else None)
        last = (st["changed"] or {}).get("music") or {}
        ago = time.time() - float(last.get("at", 0))
        if changing and ago < audio.MUSIC_COOLDOWN and last.get("mode") == sc.mode:
            raise ToolError(f"мелодия сменилась {int(ago)} с назад: оставь её, меняй только на повороте сцены")

    # мелодия и ритм должны совпадать по темпу, иначе получится каша
    def current(layer: str) -> audio.Track | None:
        if layer in wanted:
            return wanted[layer]
        cur = st.get(layer)
        return lib.get(cur["track"]) if cur else None

    music, rhythm = current("music"), current("rhythm")
    if not audio.tempo_fits(music, rhythm):
        fit = [
            t.id
            for t in lib.for_pack(audio.pack_of(ctx.campaign))
            if t.layer == "rhythm" and audio.tempo_fits(music, t)
        ]
        raise ToolError(
            f"ритм {rhythm.id} ({rhythm.bpm:g} bpm) не ложится на мелодию {music.id} ({music.bpm:g} bpm); "
            f"подходят: {', '.join(fit) or 'нет, выключи ритм (off)'}"
        )

    for layer in audio.LOOPS:
        if layer in wanted or layer in levels:
            track = wanted[layer] if layer in wanted else current(layer)
            audio.set_layer(sc, layer, track, levels.get(layer))
    ctx.signals.add("audio")
    now_ = {k: (current(k).id if current(k) else "off") for k in audio.LOOPS}
    await ctx.record(
        "set_soundscape",
        payload={"reason": a.reason, "layers": now_},
        inverse=[{"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": before}],
    )
    return {"playing": now_}


@tool(
    "play_sfx",
    "Короткий звуковой эффект один раз (гром, рык, скрип двери). Не больше двух за ход.",
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
