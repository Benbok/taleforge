"""The hero's coins: one kind of money, kept beside the other resources. A hero who has none recorded starts with a
small purse, so the first shop is not a wall."""

START_COINS = 20
FOE_COINS = {"weak": (1, 4), "normal": (4, 10), "strong": (10, 22)}  # a foe's purse by its strength


def coins_of(hero) -> int:
    value = (hero.resources or {}).get("coins")
    return START_COINS if value is None else int(value)


def set_coins(hero, amount: int) -> None:
    if amount < 0:
        raise ValueError("Монет не может быть меньше нуля")
    hero.resources = {**hero.resources, "coins": str(amount)}


def foe_purse(power: str, key: str) -> int:
    """What a beaten foe had on it: fixed by the foe and the place, so a replay gives the same coins."""
    import hashlib

    low, high = FOE_COINS.get(power, FOE_COINS["normal"])
    return low + int.from_bytes(hashlib.sha256(key.encode()).digest()[:4]) % (high - low + 1)
