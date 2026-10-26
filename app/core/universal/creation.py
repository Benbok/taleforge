from sqlalchemy import delete, select, update

from app.agents.hero_creation import ask_hero
from app.core.campaigns import AccessDenied, Conflict, NotFound, get_viewer
from app.db.models import Character, HeroDialogue, LibraryCharacter, User, new_id
from app.rules.universal.contracts import HeroBudget, HeroDescription, StartingAllocationProposal, UniversalSheet
from app.rules.universal.mechanics import starting_defense_bonuses


async def load_dialogue(session, owner_id: str, dialogue_id: str) -> HeroDialogue:
    draft = await session.scalar(
        select(HeroDialogue)
        .where(
            HeroDialogue.id == dialogue_id,
            HeroDialogue.owner_user_id == owner_id,
        )
        .execution_options(populate_existing=True)
    )
    if draft is None:
        raise NotFound("черновик не найден")
    return draft


async def delete_dialogue(session, owner_id: str, dialogue_id: str, expected_revision: int) -> None:
    draft = await load_dialogue(session, owner_id, dialogue_id)
    if draft.status not in ("questions", "ready"):
        raise Conflict("Герой уже создан; его можно удалить из библиотеки.")
    if draft.revision != expected_revision:
        raise Conflict("Черновик изменился; обновите запись перед удалением.")
    result = await session.execute(
        delete(HeroDialogue).where(
            HeroDialogue.id == dialogue_id,
            HeroDialogue.owner_user_id == owner_id,
            HeroDialogue.revision == expected_revision,
            HeroDialogue.status.in_(("questions", "ready")),
        )
    )
    if result.rowcount != 1:
        await session.rollback()
        raise Conflict("Черновик изменился; обновите запись перед удалением.")
    await session.commit()


def dialogue_view(draft: HeroDialogue) -> dict:
    view = {
        key: getattr(draft, key)
        for key in ("id", "revision", "status", "description", "transcript", "proposal", "hero_id", "campaign_id")
    }
    view["transcript"] = [message for message in draft.transcript if message.get("role") in ("user", "assistant")]
    return view


async def _campaign_target(session, owner_id, campaign_id, target_id):
    if not campaign_id:
        if target_id:
            raise Conflict("для заготовки нужна кампания")
        return None
    viewer = await get_viewer(session, await session.get(User, owner_id), campaign_id)
    if target_id:
        # Existing game cards cannot be edited or replaced via creation.
        if not viewer.is_owner or target_id != "premade":
            raise AccessDenied("можно создать только новую заготовку")
        return None
    if not viewer.is_player:
        raise AccessDenied("нужно место игрока")
    existing = await session.scalar(select(Character.id).where(Character.seat_id == viewer.seat.id))
    if existing:
        raise Conflict("на месте уже есть герой")
    return viewer.seat.id


async def start_dialogue(
    session,
    owner_id: str,
    description: HeroDescription,
    campaign_id: str | None = None,
    target_id: str | None = None,
    *,
    llm,
) -> HeroDialogue:
    await _campaign_target(session, owner_id, campaign_id, target_id)
    draft = HeroDialogue(
        owner_user_id=owner_id,
        campaign_id=campaign_id,
        target_id=target_id,
        description=description.model_dump(),
        transcript=[],
    )
    session.add(draft)
    await session.commit()
    return await answer_dialogue(session, draft.id, owner_id, draft.revision, "", llm=llm)


async def answer_dialogue(
    session, dialogue_id: str, owner_id: str, expected_revision: int, answer: str, *, llm
) -> HeroDialogue:
    draft = await load_dialogue(session, owner_id, dialogue_id)
    if draft.campaign_id:
        from app.core.universal.clock import lock_campaign

        await lock_campaign(session, draft.campaign_id)
        draft = await load_dialogue(session, owner_id, dialogue_id)
    if draft.status == "confirmed" or draft.revision != expected_revision:
        raise Conflict("версия черновика изменилась; обновите предложение")
    history = list(draft.transcript)
    if answer:
        history.append(dict(role="user", content=answer))
    from app.core.universal.admission import admission_source, world_context

    context = await world_context(session, draft.campaign_id)
    admitting = bool(draft.campaign_id and draft.target_id and draft.target_id != "premade")
    source = await admission_source(session, draft) if admitting else None
    kwargs = {"world_context": context} if context else {}
    if source:
        kwargs.update(purpose="hero_admission", current_abilities=source.abilities.model_dump(mode="json"))
    result = await ask_hero(session, llm, draft.description, history, **kwargs)
    if admitting:
        source = await admission_source(session, draft)
    if source and result.proposal:
        result.proposal = result.proposal.model_copy(
            update={"abilities": source.abilities, "equipment": source.starting_equipment}
        )
    history.append(
        dict(
            role="assistant",
            content=result.question or "Предлагаю распределение характеристик.",
            proposal=result.proposal.model_dump(mode="json") if result.proposal else None,
        )
    )
    changed = await session.execute(
        update(HeroDialogue)
        .where(
            HeroDialogue.id == dialogue_id,
            HeroDialogue.owner_user_id == owner_id,
            HeroDialogue.revision == expected_revision,
            HeroDialogue.status != "confirmed",
        )
        .values(
            revision=expected_revision + 1,
            description=result.description.model_dump(),
            transcript=history,
            status="ready" if result.proposal else "questions",
            proposal=result.proposal.model_dump(mode="json") if result.proposal else None,
        )
    )
    if changed.rowcount != 1:
        await session.rollback()
        raise Conflict("версия черновика изменилась; обновите предложение")
    await session.commit()
    return await load_dialogue(session, owner_id, dialogue_id)


async def confirm_hero(session, dialogue_id: str, owner_id: str, expected_revision: int) -> str:
    draft = await load_dialogue(session, owner_id, dialogue_id)
    if draft.campaign_id:
        from app.core.universal.clock import lock_campaign

        await lock_campaign(session, draft.campaign_id)
        draft = await load_dialogue(session, owner_id, dialogue_id)
    if draft.status == "confirmed" and draft.revision == expected_revision + 1:
        await _finish_admission(session, draft.campaign_id, draft.hero_id)
        return draft.hero_id
    if draft.status != "ready" or draft.revision != expected_revision:
        raise Conflict("подтвердите актуальное готовое предложение")
    proposal = StartingAllocationProposal.model_validate(draft.proposal)
    if proposal.equipment is None:
        raise Conflict("У этого черновика ещё нет стартового снаряжения. Попросите мастера подобрать оружие и броню.")
    description = HeroDescription.model_validate(draft.description)
    admitting = bool(draft.campaign_id and draft.target_id and draft.target_id != "premade")
    source = None
    if admitting:
        from app.core.universal.admission import admission_source

        source = await admission_source(session, draft)
    seat_id = await _campaign_target(session, owner_id, draft.campaign_id, None if admitting else draft.target_id)
    sheet = UniversalSheet(
        abilities=proposal.abilities,
        description=description,
        budget=HeroBudget(initial_scores=proposal.abilities),
        starting_equipment=proposal.equipment,
    )
    if source:
        sheet = source.model_copy(update={"description": description})
    hero_id = new_id("ch" if draft.campaign_id else "lc")
    changed = await session.execute(
        update(HeroDialogue)
        .where(
            HeroDialogue.id == dialogue_id,
            HeroDialogue.revision == expected_revision,
            HeroDialogue.status == "ready",
        )
        .values(status="confirmed", revision=expected_revision + 1, hero_id=hero_id)
    )
    if changed.rowcount != 1:
        await session.rollback()
        draft = await load_dialogue(session, owner_id, dialogue_id)
        if draft.status == "confirmed" and draft.revision == expected_revision + 1:
            return draft.hero_id
        raise Conflict("предложение уже изменено")
    data = dict(
        id=hero_id, owner_user_id=owner_id, name=description.name or "Без имени", sheet=sheet.model_dump(mode="json")
    )
    if draft.campaign_id:
        from app.rules.universal.mechanics import derive

        derived = derive(sheet, starting_defense_bonuses(sheet))
        from app.db.models import Campaign

        campaign = await session.get(Campaign, draft.campaign_id)
        if admitting:
            original = await session.get(LibraryCharacter, draft.target_id)
            data["portrait_id"] = original.portrait_id
            data["sheet"]["source_library_id"] = draft.target_id
        session.add(
            Character(
                **data,
                campaign_id=draft.campaign_id,
                seat_id=seat_id,
                status="premade" if draft.target_id == "premade" else "approved",
                location_id=(campaign.settings or {}).get("studio_entry_location_id"),
                creation_method="description",
                resources=dict(hp=str(derived.hp_max), energies={k: str(v) for k, v in derived.energy_max.items()}),
            )
        )
    else:
        session.add(LibraryCharacter(**data))
    await session.commit()  # L1 is durable before the separate admission event.
    await _finish_admission(session, draft.campaign_id, hero_id)
    return hero_id


async def _finish_admission(session, campaign_id, hero_id):
    hero = await session.get(Character, hero_id) if campaign_id else None
    if hero is not None and hero.status in {"active", "approved"}:
        from app.core.universal.progression import catch_up_copy

        await catch_up_copy(session, campaign_id, hero_id)
        await session.commit()


async def copy_library_hero(session, viewer, original):
    from app.core.universal.admission import world_context
    from app.core.universal.clock import lock_campaign
    from app.core.universal.editing import editable_sheet
    from app.rules.universal.mechanics import derive

    await lock_campaign(session, viewer.campaign.id)
    if original.owner_user_id != viewer.user.id:
        raise AccessDenied("Можно добавить только своего библиотечного героя")
    if await world_context(session, viewer.campaign.id):
        raise Conflict("Review and explicitly confirm the world adaptation before joining.")
    if viewer.seat:
        existing = await session.scalar(
            select(Character).where(Character.campaign_id == viewer.campaign.id, Character.seat_id == viewer.seat.id)
        )
        if existing and existing.sheet.get("source_library_id") == original.id:
            return existing
    seat_id = await _campaign_target(session, viewer.user.id, viewer.campaign.id, None)
    # Re-validate the base, then serialize a separate object; no mutable JSON is shared.
    sheet = editable_sheet(original)
    derived = derive(sheet, starting_defense_bonuses(sheet))
    copied = Character(
        owner_user_id=viewer.user.id,
        campaign_id=viewer.campaign.id,
        seat_id=seat_id,
        name=original.name,
        portrait_id=original.portrait_id,
        location_id=(viewer.campaign.settings or {}).get("studio_entry_location_id"),
        status="approved",
        creation_method="description",
        sheet={**sheet.model_dump(mode="json"), "source_library_id": original.id},
        resources=dict(hp=str(derived.hp_max), energies={k: str(v) for k, v in derived.energy_max.items()}),
    )
    session.add(copied)
    await session.flush()
    return copied
