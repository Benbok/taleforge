from sqlalchemy import select, update

from app.agents.hero_creation import ask_hero
from app.core.campaigns import AccessDenied, Conflict, NotFound, get_viewer
from app.db.models import Character, HeroDialogue, LibraryCharacter, User, new_id
from app.rules.universal.contracts import HeroBudget, HeroDescription, StartingAllocationProposal, UniversalSheet


async def load_dialogue(session, owner_id: str, dialogue_id: str) -> HeroDialogue:
    draft = await session.scalar(select(HeroDialogue).where(
        HeroDialogue.id == dialogue_id, HeroDialogue.owner_user_id == owner_id,
    ).execution_options(populate_existing=True))
    if draft is None:
        raise NotFound('черновик не найден')
    return draft


def dialogue_view(draft: HeroDialogue) -> dict:
    return {key: getattr(draft, key) for key in ('id', 'revision', 'status', 'description', 'transcript',
                                               'proposal', 'hero_id', 'campaign_id')}


async def _campaign_target(session, owner_id, campaign_id, target_id):
    if not campaign_id:
        if target_id:
            raise Conflict('для заготовки нужна кампания')
        return None
    viewer = await get_viewer(session, await session.get(User, owner_id), campaign_id)
    if target_id:
        # Existing game cards cannot be edited or replaced via creation.
        if not viewer.is_owner or target_id != 'premade':
            raise AccessDenied('можно создать только новую заготовку')
        return None
    if not viewer.is_player:
        raise AccessDenied('нужно место игрока')
    existing = await session.scalar(select(Character.id).where(Character.seat_id == viewer.seat.id))
    if existing:
        raise Conflict('на месте уже есть герой')
    return viewer.seat.id


async def start_dialogue(session, owner_id: str, description: HeroDescription,
                         campaign_id: str | None = None, target_id: str | None = None, *, llm) -> HeroDialogue:
    await _campaign_target(session, owner_id, campaign_id, target_id)
    draft = HeroDialogue(owner_user_id=owner_id, campaign_id=campaign_id, target_id=target_id,
                         description=description.model_dump(), transcript=[])
    session.add(draft)
    await session.commit()
    return await answer_dialogue(session, draft.id, owner_id, draft.revision, '', llm=llm)


async def answer_dialogue(session, dialogue_id: str, owner_id: str, expected_revision: int,
                          answer: str, *, llm) -> HeroDialogue:
    draft = await load_dialogue(session, owner_id, dialogue_id)
    if draft.status == 'confirmed' or draft.revision != expected_revision:
        raise Conflict('версия черновика изменилась; обновите предложение')
    history = list(draft.transcript)
    if answer:
        history.append(dict(role='user', content=answer))
    result = await ask_hero(session, llm, draft.description, history)
    history.append(dict(role='assistant', content=result.question or 'Предлагаю распределение характеристик.',
                        proposal=result.proposal.model_dump(mode='json') if result.proposal else None))
    changed = await session.execute(update(HeroDialogue).where(
        HeroDialogue.id == dialogue_id, HeroDialogue.owner_user_id == owner_id,
        HeroDialogue.revision == expected_revision, HeroDialogue.status != 'confirmed',
    ).values(revision=expected_revision + 1, description=result.description.model_dump(), transcript=history,
             status='ready' if result.proposal else 'questions',
             proposal=result.proposal.model_dump(mode='json') if result.proposal else None))
    if changed.rowcount != 1:
        await session.rollback()
        raise Conflict('версия черновика изменилась; обновите предложение')
    await session.commit()
    return await load_dialogue(session, owner_id, dialogue_id)


async def confirm_hero(session, dialogue_id: str, owner_id: str, expected_revision: int) -> str:
    draft = await load_dialogue(session, owner_id, dialogue_id)
    if draft.status == 'confirmed' and draft.revision == expected_revision + 1:
        return draft.hero_id
    if draft.status != 'ready' or draft.revision != expected_revision:
        raise Conflict('подтвердите актуальное готовое предложение')
    proposal = StartingAllocationProposal.model_validate(draft.proposal)
    description = HeroDescription.model_validate(draft.description)
    seat_id = await _campaign_target(session, owner_id, draft.campaign_id, draft.target_id)
    sheet = UniversalSheet(abilities=proposal.abilities, description=description,
                           budget=HeroBudget(initial_scores=proposal.abilities))
    hero_id = new_id('ch' if draft.campaign_id else 'lc')
    changed = await session.execute(update(HeroDialogue).where(
        HeroDialogue.id == dialogue_id, HeroDialogue.revision == expected_revision,
        HeroDialogue.status == 'ready',
    ).values(status='confirmed', revision=expected_revision + 1, hero_id=hero_id))
    if changed.rowcount != 1:
        await session.rollback()
        draft = await load_dialogue(session, owner_id, dialogue_id)
        if draft.status == 'confirmed' and draft.revision == expected_revision + 1:
            return draft.hero_id
        raise Conflict('предложение уже изменено')
    data = dict(id=hero_id, owner_user_id=owner_id, name=description.name or 'Без имени',
                sheet=sheet.model_dump(mode='json'))
    if draft.campaign_id:
        from app.rules.universal.mechanics import derive
        derived = derive(sheet, [])
        session.add(Character(**data, campaign_id=draft.campaign_id, seat_id=seat_id,
                              status='premade' if draft.target_id else 'approved', creation_method='description',
                              resources=dict(hp=str(derived.hp_max),
                                             energies={k: str(v) for k, v in derived.energy_max.items()})))
    else:
        session.add(LibraryCharacter(**data))
    await session.commit()
    return hero_id
