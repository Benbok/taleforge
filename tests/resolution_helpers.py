from app.core.resolution.contracts import ActionRef
from app.db.models import Message
from app.tools.resolution.requests import bind_message_actions


async def prepare_actions(ctx, hero_id: str, actions: list[dict]) -> tuple[Message, list[ActionRef]]:
    message = Message(
        campaign_id=ctx.campaign.id,
        seat_id=ctx.world.characters[hero_id].seat_id,
        kind="action",
        seq=100,
        content="test",
        intent={"actions": actions},
        turn_id=ctx.turn_id,
    )
    ctx.session.add(message)
    await ctx.session.flush()
    refs = bind_message_actions(message, hero_id)
    return message, refs


async def prepare_action(ctx, hero_id: str, actions: list[dict]) -> ActionRef:
    _msg, refs = await prepare_actions(ctx, hero_id, actions)
    return refs[0]

