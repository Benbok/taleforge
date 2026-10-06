"""Контракт событий WebSocket: какие события шлёт сервер и что лежит в их ``payload``.

Каждое событие сервера описано здесь моделью Pydantic. Из этих моделей собирается OpenAPI-схема приложения
(``app/contract.py``), а из неё — типы клиента (``web/src/lib/api.gen.ts``). Поэтому новое событие или новое
поле начинается здесь: без записи в ``SERVER_EVENTS`` тесты не пройдут, а клиент о нём не узнает.

В тестах ``envelope()`` проверяет каждое отправленное событие по его модели (``STRICT``), так что поле,
переименованное на сервере, ловится тестом сервера, а поле, которое клиент ждёт иначе, — проверкой типов клиента.

Поле ``x: T | None`` есть всегда и может быть null, ``x: T | None = None`` может и отсутствовать, а
``x: T = absent()`` либо отсутствует, либо не null. Модели ``_Strict`` не допускают лишних полей. Большие формы
(карточка сущности, схема места, ответ инструмента мастера) пока описаны открытыми моделями ``_Open``:
известные поля проверяются, новые пропускаются.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model

from app.core.views import HeroPublic, HeroSheet, absent

# В тестах — True: каждое событие проверяется по своей модели (tests/conftest.py).
STRICT = False
# Нарушения контракта при STRICT: событие могло уйти из фоновой задачи, где исключение только пишется в лог,
# поэтому тест проверяет и этот список.
VIOLATIONS: list[str] = []


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class Option(_Strict):
    id: str
    label: str


# --- общие формы ---


class StandIn(_Strict):
    user_id: str = absent()
    name: str
    ai: bool = absent()


class PendingReply(_Strict):
    id: str
    created_at: str | None


class TurnEconomy(_Strict):
    action: bool
    attacks_left: int
    bonus: bool
    move_left_ft: int
    disengage: bool


class Turn(_Strict):
    round: int
    actor_id: str
    name: str
    seat_id: str | None
    deadline: float | None
    submitted: bool
    economy: TurnEconomy = absent()


class ChatMessage(_Strict):
    """Сообщение чата. ``data`` — свободная форма: карточка броска, голосовая запись, место части отряда."""

    id: str
    seq: int
    kind: str
    seat_id: str | None
    author: str | None
    content: str
    whisper: bool
    data: dict[str, Any] | None
    created_at: str | None
    state: Literal["pending", "processing", "answered", "failed"] | None


class Vote(_Strict):
    vote_id: str
    seat_id: str
    subject: Literal["player", "master"]
    who: str
    hero: str | None
    options: list[Option]
    voters: list[str]
    voted: list[str]
    tally: dict[str, int]
    deadline: float


class RestHero(_Strict):
    id: str
    name: str
    seat_id: str | None
    voter: bool
    choice: Literal["sleep", "watch", "no"] | None
    hit_dice: int | None
    hit_dice_left: int


class RestVote(_Strict):
    vote_id: str
    kind: Literal["short", "long"]
    kind_ru: str
    place: str | None
    place_name: str
    safety: Literal["safe", "risky", "dangerous"]
    safety_ru: str
    warning: str | None
    safer: list[str]
    proposer: str | None
    heroes: list[RestHero]
    choices: list[Literal["sleep", "watch", "no"]]
    deadline: float


class ReactionPrompt(_Strict):
    prompt_id: str
    character_id: str
    trigger: str
    options: list[Option]
    expires_at: float


class SessionSummary(_Strict):
    recap: str
    events: list[str]
    quests: list[str]


class SceneEntity(_Open):
    id: str
    name: str
    kind: str
    zone: str


class OrderEntry(_Strict):
    id: str
    name: str
    initiative: int | None
    side: Literal["hero", "enemy", "ally"]
    seat_id: str | None = absent()
    out: str | None


class PartyPart(_Strict):
    id: str | None
    place: str | None
    names: list[str]
    here: bool


class Place(_Strict):
    id: str
    name: str


class Scene(_Open):
    mode: Literal["free", "combat"]
    round: int
    location: Place | None
    party: list[PartyPart] = absent()
    entities: list[SceneEntity]
    order: list[OrderEntry] = absent()
    turn: Turn | None


class AudioTrack(_Open):
    id: str
    title: str
    layer: str
    url: str
    gain_db: float


class AudioState(_Open):
    enabled: bool
    v: int
    now: float
    music: AudioTrack | None
    cues: list[AudioTrack] = []


class SeatState(_Strict):
    id: str
    role: Literal["master", "player"]
    position: int
    occupant_type: Literal["human", "agent", "empty"]
    user_name: str | None
    presence: Literal["online", "reconnecting", "offline"] | None
    stand_in: StandIn | None


class SnapshotCampaign(_Strict):
    id: str
    name: str
    status: Literal["lobby", "active", "paused", "ended"]
    public_intro: str


class SnapshotSession(_Strict):
    id: str
    started_at: str


class SnapshotMe(_Strict):
    user_id: str
    seat_id: str | None
    role: Literal["master", "player"] | None
    is_owner: bool
    stand_in_for: list[str]


# --- payload событий ---


class StateSnapshot(_Strict):
    protocol: int
    campaign: SnapshotCampaign
    session: SnapshotSession | None
    me: SnapshotMe
    seats: list[SeatState]
    votes: list[Vote]
    rest_votes: list[RestVote]
    turn: Turn | None
    reaction: ReactionPrompt | None
    summary: SessionSummary | None
    heroes: list[HeroPublic]
    scene: Scene
    audio: AudioState | None
    actions: list[str]
    blocked: dict[str, str]
    pending: PendingReply | None
    messages: list[ChatMessage]
    replay: bool
    collect_window_sec: int


class StateActions(_Strict):
    actions: list[str]
    blocked: dict[str, str]
    pending: PendingReply | None
    as_seat: str = absent()


class AuthOk(_Strict):
    user_id: str
    name: str


class Empty(_Strict):
    pass


class Error(_Strict):
    code: str
    message: str


class CampaignPlan(_Strict):
    plan: dict[str, Any]
    poster: Any = None
    public_intro: str


class CampaignStatusChanged(_Strict):
    status: Literal["lobby", "active", "paused", "ended"]


class Epilogue(_Open):
    chronicle: str


class CharacterBonds(_Strict):
    character_id: str
    bonds: dict[str, Any]


class CharacterReviewFailed(_Strict):
    character_id: str
    error: str


class CharacterReviewed(_Strict):
    status: str
    comment: str | None
    character: HeroSheet = absent()


class CharacterSheet(_Strict):
    character: HeroSheet
    event_id: str | None = absent()


class CharacterUpdated(_Strict):
    character: HeroPublic


class EntityCard(_Open):
    id: str
    error: str = absent()


class KnowledgeRevealed(_Strict):
    entity_id: str | None
    name: str | None
    level: Any = None


class MapChanged(_Strict):
    place_id: str = absent()


class MapState(_Open):
    pass


class MapStepResult(_Open):
    request_id: str | None
    ok: bool


class MasterStatus(_Strict):
    stage: str


class MasterToolResult(_Open):
    request_id: str | None
    ok: bool


class MessageChunk(_Strict):
    id: str
    seq: int
    seat_id: str | None
    kind: str
    chunk: str
    reset: bool = absent()


class MessageNotice(_Strict):
    text: str
    message_id: str


class MessageRejected(_Strict):
    reason: str
    client_id: str | None = None
    text: str = absent()


class MessageState(_Strict):
    ids: list[str]
    state: Literal["pending", "processing", "answered", "failed"]


class MessageWithdrawn(_Strict):
    id: str
    seq: int = absent()
    text: str = absent()


class PresenceChanged(_Strict):
    seat_id: str
    status: Literal["online", "reconnecting", "offline"]


class ReactionClosed(_Strict):
    prompt_id: str
    choice: str


class RestEnded(_Strict):
    vote_id: str


class SeatChanged(_Strict):
    seat_id: str


class StandInChanged(_Strict):
    seat_id: str
    stand_in: StandIn | None


class StatExplained(_Open):
    stat: str
    character_id: str
    error: str = absent()


class TurnChanged(_Strict):
    turn: Turn | None


class VoteEnded(Vote):
    outcome: str
    label: str | None


# Тип события → модель его payload. Порядок — по алфавиту, как события видит клиент.
SERVER_EVENTS: dict[str, type[BaseModel]] = {
    "audio.state": AudioState,
    "auth.ok": AuthOk,
    "campaign.deleted": Empty,
    "campaign.epilogue": Epilogue,
    "campaign.plan": CampaignPlan,
    "character.bonds": CharacterBonds,
    "character.review_failed": CharacterReviewFailed,
    "character.reviewed": CharacterReviewed,
    "character.sheet": CharacterSheet,
    "character.updated": CharacterUpdated,
    "entity.card": EntityCard,
    "error": Error,
    "knowledge.revealed": KnowledgeRevealed,
    "map.changed": MapChanged,
    "map.state": MapState,
    "map.step.result": MapStepResult,
    "master.status": MasterStatus,
    "master.tool.result": MasterToolResult,
    "message.chunk": MessageChunk,
    "message.new": ChatMessage,
    "message.notice": MessageNotice,
    "message.rejected": MessageRejected,
    "message.state": MessageState,
    "message.withdrawn": MessageWithdrawn,
    "pong": Empty,
    "presence.changed": PresenceChanged,
    "reaction.closed": ReactionClosed,
    "reaction.prompt": ReactionPrompt,
    "rest.ended": RestEnded,
    "rest.vote": RestVote,
    "scene.updated": Scene,
    "seat.changed": SeatChanged,
    "session.ended": CampaignStatusChanged,
    "session.paused": CampaignStatusChanged,
    "session.started": CampaignStatusChanged,
    "session.summary": SessionSummary,
    "stand_in.changed": StandInChanged,
    "stat.explained": StatExplained,
    "state.actions": StateActions,
    "state.snapshot": StateSnapshot,
    "turn.changed": TurnChanged,
    "vote.ended": VoteEnded,
    "vote.started": Vote,
    "vote.updated": Vote,
}


def _envelope_model(type_: str, payload: type[BaseModel]) -> type[BaseModel]:
    name = "Event_" + type_.replace(".", "_")
    return create_model(
        name,
        __base__=_Strict,
        type=(Literal[type_], ...),  # type: ignore[valid-type]
        campaign_id=(str | None, ...),
        seq=(int | None, ...),
        payload=(payload, ...),
    )


EVENT_MODELS = [_envelope_model(t, m) for t, m in SERVER_EVENTS.items()]


# Любое событие сервера: объединение по полю ``type`` (в схеме — ServerEvent).
ServerEvent = Annotated[Union[tuple(EVENT_MODELS)], Field(discriminator="type")]  # noqa: UP007


class UnknownEvent(ValueError):
    pass


def check(type_: str, payload: dict[str, Any]) -> None:
    """Проверка события по контракту (только при ``STRICT``)."""
    model = SERVER_EVENTS.get(type_)
    try:
        if model is None:
            raise UnknownEvent(f"событие {type_!r} не описано в app/gateway/protocol.py")
        model.model_validate(payload)
    except ValueError as e:
        VIOLATIONS.append(f"{type_}: {e}")
        raise
