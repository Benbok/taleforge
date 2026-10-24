import hashlib
import json

from pydantic import Field, model_validator
from sqlalchemy import select, update

from app.agents.hero_creation import ask_hero
from app.core.campaigns import Conflict, NotFound
from app.core.universal.state import card_of, load_library_hero
from app.db.models import HeroDialogue, HeroEditReceipt, LibraryCharacter
from app.rules.universal.contracts import AbilityScores, ClosedModel, HeroBudget, HeroDescription, UniversalSheet
from app.rules.universal.mechanics import validate_starting_scores


class HeroEdit(ClosedModel):
    description_patch: dict[str, str] = Field(default_factory=dict)
    base_scores: AbilityScores | None = None
    expected_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def bounded_edit(self):
        if set(self.description_patch) - set(HeroDescription.model_fields):
            raise ValueError("можно менять только описательные поля героя")
        HeroDescription.model_validate({"identity": "_", **self.description_patch})
        if self.base_scores:
            validate_starting_scores(self.base_scores)
        return self


def editable_sheet(hero):
    sheet = UniversalSheet.model_validate(hero.sheet)
    if sheet.level != 1 or sheet.xp != 0 or sheet.unspent_points != 0:
        raise Conflict("редактируется только базовый герой первого уровня")
    if sheet.budget and (sheet.budget.growth_total or sheet.budget.unspent):
        raise Conflict("игровое развитие нельзя редактировать в библиотеке")
    validate_starting_scores(sheet.abilities)
    return sheet


async def propose_hero_edit(
    session, owner_id: str, library_id: str, message: str, expected_revision: int, *, llm
) -> HeroDialogue:
    hero = await load_library_hero(session, owner_id, library_id)
    sheet = editable_sheet(hero)
    if hero.revision != expected_revision:
        raise Conflict("карточка изменилась; загрузите новую версию")
    result = await ask_hero(
        session,
        llm,
        sheet.description.model_dump(),
        [dict(role="user", content=message)],
        purpose="hero_edit",
        current_abilities=sheet.abilities.model_dump(mode="json"),
    )
    if result.proposal is None:
        raise Conflict(result.question)
    hero = await session.scalar(
        select(LibraryCharacter).where(LibraryCharacter.id == library_id).execution_options(populate_existing=True)
    )
    if hero is None or hero.revision != expected_revision:
        raise Conflict("карточка изменилась; загрузите новую версию")
    edit = HeroEdit(
        description_patch=result.description.model_dump(),
        base_scores=result.proposal.abilities,
        expected_revision=expected_revision,
    )
    draft = HeroDialogue(
        owner_user_id=owner_id,
        target_id=library_id,
        description=result.description.model_dump(),
        status="edit_ready",
        proposal=edit.model_dump(mode="json"),
        transcript=[
            dict(role="user", content=message),
            dict(role="assistant", explanations=result.proposal.explanations),
        ],
    )
    session.add(draft)
    await session.commit()
    return draft


async def apply_hero_edit(session, owner_id: str, library_id: str, edit: HeroEdit, request_key: str) -> dict:
    hero = await load_library_hero(session, owner_id, library_id)
    fingerprint = hashlib.sha256(json.dumps(edit.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    receipt = await session.scalar(
        select(HeroEditReceipt).where(HeroEditReceipt.hero_id == library_id, HeroEditReceipt.request_key == request_key)
    )
    if receipt:
        if receipt.fingerprint != fingerprint:
            raise Conflict("ключ запроса уже использован для другой правки")
        return receipt.result
    sheet = editable_sheet(hero)
    if hero.revision != edit.expected_revision:
        raise Conflict("карточка изменилась; загрузите новую версию, ваш текст сохранён в редакторе")
    description = HeroDescription.model_validate({**sheet.description.model_dump(), **edit.description_patch})
    scores = validate_starting_scores(edit.base_scores or sheet.abilities)
    sheet = UniversalSheet(
        description=description,
        abilities=scores,
        trained=sheet.trained,
        budget=HeroBudget(initial_scores=scores),
        starting_equipment=sheet.starting_equipment,
    )
    changed = await session.execute(
        update(LibraryCharacter)
        .where(
            LibraryCharacter.id == library_id,
            LibraryCharacter.owner_user_id == owner_id,
            LibraryCharacter.revision == edit.expected_revision,
        )
        .values(
            sheet=sheet.model_dump(mode="json"),
            name=description.name or "Без имени",
            revision=edit.expected_revision + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        await session.rollback()
        receipt = await session.scalar(
            select(HeroEditReceipt).where(
                HeroEditReceipt.hero_id == library_id, HeroEditReceipt.request_key == request_key
            )
        )
        if receipt and receipt.fingerprint == fingerprint:
            return receipt.result
        raise Conflict("карточка изменилась; загрузите новую версию")
    await session.refresh(hero)
    card = card_of(hero)
    session.add(HeroEditReceipt(hero_id=library_id, request_key=request_key, fingerprint=fingerprint, result=card))
    await session.commit()
    return card


async def confirm_edit(session, owner_id, library_id, proposal_id, request_key):
    draft = await session.get(HeroDialogue, proposal_id)
    if draft is None or draft.owner_user_id != owner_id or draft.target_id != library_id:
        raise NotFound("предложение не найдено")
    if draft.status not in ("edit_ready", "edit_confirmed"):
        raise Conflict("предложение не готово")
    card = await apply_hero_edit(
        session, owner_id, library_id, HeroEdit.model_validate(draft.proposal), "proposal:" + proposal_id
    )
    draft.status = "edit_confirmed"
    await session.commit()
    return card
