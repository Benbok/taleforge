from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.universal import creation
from app.db.models import HeroDialogue
from app.rules.universal.contracts import ClosedModel, HeroDescription

router = APIRouter(prefix="/api/hero-creation/dialogues", tags=["hero-workshop"])


class CreationIn(ClosedModel):
    description: HeroDescription
    campaign_id: str | None = None
    target_id: str | None = None


class RevisionIn(ClosedModel):
    expected_revision: int = Field(ge=1)


class AnswerIn(RevisionIn):
    answer: str = Field(min_length=1, max_length=4000)


@router.get("")
async def pending(user: UserDep, session: SessionDep) -> list[dict]:
    drafts = (
        await session.scalars(
            select(HeroDialogue)
            .where(
                HeroDialogue.owner_user_id == user.id,
                HeroDialogue.status != "confirmed",
            )
            .order_by(HeroDialogue.created_at.desc())
        )
    ).all()
    return [creation.dialogue_view(draft) for draft in drafts]


@router.post("", status_code=201)
async def start(body: CreationIn, user: UserDep, session: SessionDep, request: Request) -> dict:
    draft = await creation.start_dialogue(
        session, user.id, body.description, body.campaign_id, body.target_id, llm=request.app.state.hero_llm
    )
    return creation.dialogue_view(draft)


@router.get("/{dialogue_id}")
async def get(dialogue_id: str, user: UserDep, session: SessionDep) -> dict:
    return creation.dialogue_view(await creation.load_dialogue(session, user.id, dialogue_id))


@router.post("/{dialogue_id}/answers")
async def answer(dialogue_id: str, body: AnswerIn, user: UserDep, session: SessionDep, request: Request) -> dict:
    draft = await creation.answer_dialogue(
        session, dialogue_id, user.id, body.expected_revision, body.answer, llm=request.app.state.hero_llm
    )
    return creation.dialogue_view(draft)


@router.post("/{dialogue_id}/confirm")
async def confirm(dialogue_id: str, body: RevisionIn, user: UserDep, session: SessionDep) -> dict:
    return {"hero_id": await creation.confirm_hero(session, dialogue_id, user.id, body.expected_revision)}
