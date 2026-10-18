"""Author fixtures use isolated test sessions and never call a provider."""

from app.db.models import User


async def author(session, name="author", role="admin"):
    user = User(name=name, platform_role=role, password_hash="unused")
    session.add(user)
    await session.flush()
    return user
