"""Read-only role prompt assembly; estimated budgets never truncate mandatory context."""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.agents import rhythm
from app.agents.master.common import MAX_CALLS, render
from app.agents.master.context_selection import ContextFact, select_context
from app.core import adventure, audio, bonds, persona, plot
from app.core.brief import brief_text
from app.core.narrative.view import master_canon_block
from app.db.models import AgentConfig, CampaignSecret
from app.tools import fortune as fortune_tools
from app.tools import progress as progress_tools
from app.tools.registry import ToolContext


def public_narration_notes(notes, *, audience: set[str] | None = None) -> list[str]:
    """Return only plot notes explicitly marked for the narration audience."""
    target = audience or {"party"}
    result: list[str] = []
    for note in notes or ():
        if not isinstance(note, dict) or not isinstance(note.get("text"), str):
            continue
        note_audience = set(note.get("audience") or ())
        if "party" in note_audience or note_audience & target:
            result.append(note["text"])
    return result


def without_action_context(text: str) -> str:
    """Remove the rendered action-ref block before it is added as a named block."""
    marker = "\nТекущие части заявок (используй точный action_ref):\n"
    prefix, separator, tail = text.partition(marker)
    if not separator:
        return text
    end = tail.find("]\n")
    if end < 0:
        return text
    return prefix + "\n" + tail[end + 2 :]


def without_context_block(text: str, block: str) -> str:
    """Remove one exact rendered block before it is serialized separately."""
    if not block:
        return text
    return text.replace(block, "")


async def collect_narration_facts(ctx: ToolContext, cfg, inputs: dict) -> tuple[ContextFact, ...]:
    """Select explicit narration facts using the audience supplied by finish."""
    facts = tuple(item for item in inputs.get("context_facts", ()) if isinstance(item, ContextFact))
    audience = frozenset(inputs.get("audience") or {"party"})
    subjects = frozenset(inputs.get("subjects") or ())
    return select_context(facts, role="narrate", subjects=subjects, audience=audience).facts


@dataclass
class PromptBundle:
    messages: list[dict]
    blocks: dict[str, str]
    version: str = "role-context-v1"
    fallback_reason: str | None = None

    def metadata(self, role: str) -> dict:
        from app.core.llm_diagnostics import prompt_sizes

        return {
            "prompt_role": role,
            "prompt_version": self.version,
            "fallback_reason": self.fallback_reason,
            "role_blocks": prompt_sizes({"instructions": self.messages[0]["content"], **self.blocks}, []),
        }


def narration_scene(ctx: ToolContext) -> str:
    """Use the same visibility boundaries as player scene updates, per audience/place."""
    from app.core.narrative.view import fact_line
    from app.core.scene_view import visible_scene
    from app.tools.runtime import scene_payload

    world = ctx.world
    audience = ctx.narration_viewer_ids
    if audience is None:
        audience = world.crew or {h.id for h in world.characters.values() if h.status in {"approved", "active"}}
    groups: dict[str | None, list[str]] = {}
    for hero_id in sorted(audience):
        hero = world.characters.get(hero_id)
        if hero is not None:
            groups.setdefault(world.place_of(hero), []).append(hero_id)
    scenes = []
    for ids in groups.values():
        revealed = set.intersection(*(set(world.revealed.get(i, ())) for i in ids))
        view = visible_scene(
            world.scene, world.entities, world.characters, hero_id=ids[0], is_master=False, revealed=frozenset(revealed)
        )
        payload = scene_payload(world.scene, world.entities, world.characters, view)
        known = {}
        for entity in view.entities:
            if entity.kind != "creature":
                continue
            facts = tuple(
                f
                for f in world.narrative_facts((entity.id, entity.template_id))
                if "party" in f.audience
                or (
                    bool(audience)
                    and all(
                        {hero_id, world.characters[hero_id].seat_id} & set(f.audience)
                        for hero_id in audience
                        if hero_id in world.characters
                    )
                )
            )
            if facts:
                known[entity.id] = fact_line(facts, mark_hidden=False)
        payload["known_npc_facts"] = known
        scenes.append(payload)
    heroes = [
        {"id": i, "name": world.characters[i].name, "place": world.place_of(world.characters[i])}
        for ids in groups.values()
        for i in ids
    ]
    return json.dumps({"scenes": scenes, "heroes": heroes}, ensure_ascii=False, default=str)


async def build_prompt_bundle(ctx: ToolContext, cfg: AgentConfig, *, role: str, inputs: dict) -> PromptBundle:
    if role not in {"decide", "narrate", "voice_line", "review"}:
        raise ValueError(f"Unknown prompt role: {role}")
    request = inputs.get("request")
    legacy = inputs.get("legacy_messages")
    if role == "decide" and inputs.get("uncertain") and legacy is not None:
        return PromptBundle(legacy, {}, fallback_reason="uncertain_intent")
    if not isinstance(request, str) or not request:
        if legacy is None:
            raise ValueError("Missing request and legacy context")
        return PromptBundle(legacy, {}, fallback_reason="missing_request")
    # The detached narration context is shared by parallel narrator/voice tasks.
    # Its snapshot belongs only to this composition; decide/review always read live state.
    values = getattr(ctx, "_narration_prompt_values", None) if role in {"narrate", "voice_line"} else None
    if values is None:
        values = await master_prompt_values(ctx, cfg)
    # Only stable campaign policy switches influence the instruction prefix.
    stable = {
        k: values[k] for k in ("difficulty", "leveling", "random_events", "critical_checks", "has_plot", "max_calls")
    }
    stable.update(
        campaign_name="игровой мир",
        style=None,
        brief=None,
        excluded_themes=None,
        public_intro=None,
        secrets=None,
        pacing=None,
        dc_scale="Смотри блок шкалы сложности.",
        audio="Доступный звук перечислен в контексте." if values["audio"] else None,
    )
    system = render(
        {
            "decide": "decide_system.j2",
            "narrate": "narrator_system.j2",
            "voice_line": "voice_system.j2",
            "review": "review_system.j2",
        }[role],
        **stable,
    )
    policy = {k: values[k] for k in ("campaign_name", "style", "brief", "excluded_themes", "public_intro")}
    blocks = {"policy": json.dumps(policy, ensure_ascii=False, default=str)}
    if role in {"decide", "review"}:
        blocks["canon"] = values["secrets"]
    if role == "decide":
        from app.agents.master.resolution import action_context_prompt

        blocks["actions"] = await action_context_prompt(ctx)
        blocks["difficulty_scale"] = values["dc_scale"]
        blocks["pacing"] = values["pacing"] or ""
        blocks["audio"] = values["audio"] or ""
        if inputs.get("resolution"):
            blocks["resolution"] = inputs["resolution"]
    if inputs.get("mood"):
        blocks["mood"] = inputs["mood"]
    blocks["request"] = request
    dynamic = "\n\n".join(f"{name}:\n{content}" for name, content in blocks.items() if content)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": dynamic}]
    budget = {"decide": 12000, "narrate": 12000, "voice_line": 2000, "review": 8000}[role]
    over_budget = (len(system) + len(dynamic) + 3) // 4 > budget
    if over_budget and legacy is not None and role in {"decide", "narrate", "review"}:
        return PromptBundle(legacy, blocks, fallback_reason="soft_budget")
    return PromptBundle(messages, blocks, fallback_reason="soft_budget" if over_budget else None)


async def master_prompt_values(ctx: ToolContext, cfg: AgentConfig) -> dict:
    s, c = ctx.session, ctx.campaign
    secret = await s.get(CampaignSecret, c.id)
    secrets = ""
    has_plot = bool(secret and plot.has_plan(secret.plot))
    if has_plot:
        # «Сюжет сейчас» — текущий акт и что рядом; весь каркас мастер читает через get_plot
        extra = json.dumps(secret.setting, ensure_ascii=False)[:4000] if secret.setting else ""
        home = ctx.world.entities.get(ctx.world.home() or "")
        if adventure.room_of(home) is not None:  # комната готового приключения: место каркаса — место модуля
            home = ctx.world.entities.get(home.location_id or "")
        now_ = plot.now_block(secret.plot, location_entity_id=home.id if home else None)
        secrets = (now_ + ("\n" + extra if extra else ""))[:16000]
        book = adventure.master_block(ctx.world)
        if book:
            secrets += "\n\nПо книге:\n" + book[:12000]
    elif secret and (secret.setting or secret.plot):
        secrets = json.dumps({"setting": secret.setting, "plot": secret.plot}, ensure_ascii=False)[:12000]
    if canon := master_canon_block(ctx.world):
        secrets = (secrets + "\n\n" if secrets else "") + canon
    ties = [
        f"{ch.name} ({ch.id}):\n{text}"
        for ch in ctx.world.characters.values()
        if ch.status in ("approved", "active") and (text := bonds.render(ch, private=True))
    ]
    if ties:
        secrets = (secrets + "\n" if secrets else "") + "Связи героев (ответы игроков):\n" + "\n".join(ties)
    # характеры героев (анкета и летопись) мастер видит, как видит лист: чтобы NPC и сцены цепляли героев
    chars = []
    for ch in ctx.world.characters.values():
        if ch.status not in ("approved", "active"):
            continue
        if text := persona.render(ch.persona, await persona.notes_of(s, c.id, ch.id)):
            chars.append(f"{ch.name} ({ch.id}):\n{text}")
    if chars:
        secrets = (secrets + "\n" if secrets else "") + "Характеры героев:\n" + "\n".join(chars)
    style = cfg.persona or ""
    own = persona.render((cfg.settings or {}).get("character"), await persona.notes_of(s, c.id, None), master=True)
    if own:
        style = (style + "\n\n" if style else "") + "Твой характер как мастера:\n" + own
    dc = ", ".join(f"{e.id} = {e.data['value']} ({e.name})" for e in ctx.world.catalog.dc_scale())
    return dict(
        campaign_name=c.name,
        style=style or None,
        brief=brief_text(c.brief),
        excluded_themes=", ".join((c.settings or {}).get("excluded_themes") or []),
        public_intro=c.public_intro,
        secrets=secrets,
        has_plot=has_plot,
        pacing=rhythm.pacing_note((c.brief or {}).get("length"), await rhythm.turns_played(s, c.id)),
        dc_scale=dc,
        max_calls=MAX_CALLS,
        difficulty=c.difficulty,
        leveling=progress_tools.leveling(c),
        random_events=fortune_tools.random_events(c),
        critical_checks=(c.settings or {}).get("critical_checks", True) is not False,
        audio=audio.prompt_block(c, ctx.world.scene, audio.where(ctx), ctx.saved_sfx),
    )
