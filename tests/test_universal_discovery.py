import asyncio

from app.core.universal.discovery import learned_abilities, record_realized_ability
from app.core.universal.profiles import put_profile
from app.core.universal.resolution import ActionRef, ProposedAction, ResolutionContext, resolve_action
from app.rules.universal.profiles import ActionOutcome, EffectOutcome, EffectSpec, ProfileSpec
from tests.test_universal_resolution import setup


class FixedDice:
    def __init__(self, values):
        self.values = iter(values)

    def d20(self):
        return next(self.values)

    def die(self, sides):
        return next(self.values)


def test_success_learns_once_miss_and_partial_composite_do_not(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = await put_profile(s, "c", ProfileSpec(id="vine", attribute="wis", kind="damage"))
            proposal = ProposedAction(
                ref=ActionRef(profile_id="vine", revision=1),
                actor_id="hero",
                targets=["target"],
                profile=p,
                reason="Vine strike",
            )
            miss = await resolve_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([1])), proposal, "miss"
            )
            assert not miss.success
            assert await learned_abilities(s, "hero") == []
            hit = await resolve_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([18, 3])), proposal, "hit"
            )
            assert hit.success
            assert len(await learned_abilities(s, "hero")) == 1
            await resolve_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([18, 3])),
                proposal.model_copy(update={"reason": "Renamed vine"}),
                "hit2",
            )
            assert len(await learned_abilities(s, "hero")) == 1
            control = EffectSpec(id="bind", kind="cannot_move")
            composite = await put_profile(
                s, "c", ProfileSpec(id="composite", attribute="wis", kind="damage", effects=[control])
            )
            proposed = ProposedAction(
                ref=ActionRef(profile_id="composite", revision=1),
                actor_id="hero",
                targets=["target"],
                profile=composite,
                operations=[control],
            )
            partial = ActionOutcome(
                success=True,
                effect_outcomes=[
                    EffectOutcome(effect_id="primary", target_id="target", applied=True),
                    EffectOutcome(effect_id="bind", target_id="target", applied=False),
                ],
            )
            assert await record_realized_ability(s, "hero", proposed, partial, "unused") is None
            assert len(await learned_abilities(s, "hero")) == 1
        await engine.dispose()

    asyncio.run(run())


def test_learned_revision_stays_usable_and_is_scoped_to_its_actor(tmp_path):
    from app.db.models import Character, Seat

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = await put_profile(s, "c", ProfileSpec(id="sense", kind="check", attribute="wis", resource_key="wis"))
            proposal = ProposedAction(
                ref=ActionRef(profile_id=p.id, revision=1), actor_id="hero", targets=["hero"], profile=p
            )
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([14]))
            assert (await resolve_action(ctx, proposal, "learn")).success
            learned = (await learned_abilities(s, "hero"))[0]
            await put_profile(s, "c", p.model_copy(update={"revision": 2}))
            assert (
                await resolve_action(ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([14])), proposal, "reuse")
            ).success
            assert (await learned_abilities(s, "hero"))[0] == learned
            s.add(Seat(id="other-seat", campaign_id="c", role="player", position=2, user_id="u", occupant_type="human"))
            target = await s.get(Character, "target")
            target.seat_id = "other-seat"
            await s.flush()
            other = proposal.model_copy(update={"actor_id": "target", "targets": ["target"]})
            result = await resolve_action(
                ResolutionContext(s, "c", "u", "other-seat", "target", FixedDice([])), other, "stale-other"
            )
            assert result.status == "denied"
        await engine.dispose()

    asyncio.run(run())
