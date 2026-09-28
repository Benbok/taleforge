"""Проверка пакета из командной строки.

python -m app.content validate content/dnd5e-srd
python -m app.content validate ../my-world --packs-root content --customs
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.content.loader import PackError, load_with_dependencies

DEFAULT_PACKS_ROOT = Path(__file__).resolve().parents[2] / "content"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.content")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="проверить пакет: схема, ссылки, совместимость с движком")
    v.add_argument("path", type=Path)
    v.add_argument(
        "--packs-root",
        type=Path,
        default=DEFAULT_PACKS_ROOT,
        help="где искать базовый пакет правил и зависимости (по умолчанию content/)",
    )
    v.add_argument("--strict", action="store_true", help="op: custom тоже ошибка")
    v.add_argument("--customs", action="store_true", help="перечислить места с op: custom")
    v.add_argument("--max-errors", type=int, default=200)
    im = sub.add_parser("import", help="проверить и записать пакет с зависимостями в БД (DATABASE_URL)")
    im.add_argument("path", type=Path)
    im.add_argument("--packs-root", type=Path, default=DEFAULT_PACKS_ROOT)
    args = ap.parse_args(argv)

    if args.cmd == "import":
        return asyncio.run(_import(args.path, args.packs_root))

    try:
        _, report = load_with_dependencies(args.path, args.packs_root, strict=args.strict)
    except PackError as e:
        print(f"ОШИБКА: {e}")
        return 1

    print(report.summary())
    if args.customs and report.customs:
        print("\nop: custom:")
        print("\n".join(f"  {c}" for c in report.customs))
    for w in report.warnings:
        print(f"предупреждение: {w}")
    if report.errors:
        print(f"\nОШИБКИ ({len(report.errors)}):")
        print("\n".join(report.errors[: args.max_errors]))
        return 1
    print("OK")
    return 0


async def _import(path: Path, packs_root: Path) -> int:
    from app.config import Settings
    from app.content.importer import import_pack
    from app.db.session import make_engine, make_sessionmaker

    engine = make_engine(Settings.from_env().database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            for pid, version, state in await import_pack(session, path, packs_root):
                print(f"{pid} {version}: {'записан' if state == 'imported' else 'без изменений'}")
    except PackError as e:
        print(f"ОШИБКА: {e}")
        return 1
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
