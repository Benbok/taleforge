import asyncio

import pytest

from app.core.universal.profiles import put_profile
from app.core.universal.resolution import ActionRef, ProposedAction, ResolutionContext, resolve_action
from app.rules.dice import FixedDice
from app.rules.universal.profiles import ProfileSpec
from tests.test_universal_resolution import setup


@pytest.mark.parametrize(
    "case,code",
    [("duration", "unsupported_duration"), ("energy", "insufficient_resources"), ("target", "target_unavailable")],
)
def test_preparation_and_execution_share_failure_codes(tmp_path, case, code):
    from app.core.universal.validation import validate_action
    from app.rules.universal.failures import ActionValidationError

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = ProfileSpec(
                id="ability",
                kind="check",
                attribute="wis",
                resource_key="wis",
                duration=3 if case == "duration" else 1,
                intensity="strong" if case == "energy" else "normal",
            )
            if case == "energy":
                from app.db.models import Character

                h = await s.get(Character, "hero")
                h.resources = {**h.resources, "energies": {**h.resources["energies"], "wis": "0"}}
                await s.flush()
            proposal = ProposedAction(
                ref=ActionRef(profile_id=p.id, revision=1),
                actor_id="hero",
                targets=["missing" if case == "target" else "hero"],
                profile=p,
            )
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            with pytest.raises(ActionValidationError) as error:
                await validate_action(ctx, proposal, require_saved_profile=False)
            assert error.value.failure.code == code
            await put_profile(s, "c", p)
            result = await resolve_action(ctx, proposal, "once")
            assert result.status == "denied" and result.failure.code == code
        await engine.dispose()

    asyncio.run(run())
