"""Compile saved model answers and deterministic fallbacks for the quality gallery. No API calls."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.layout import geometry
from app.core.layout.intent import LayoutIntent
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.layout.spatial import Mandate, default_spatial, intent_candidates

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "experiments/location-layout-templates/quality-v3"


def export(intent: LayoutIntent, name: str, title: str) -> dict:
    bp = DeterministicLayoutProvider().propose(intent, seed=7, root_id=f"quality_{name}")
    directory = OUTPUT / "generated" / name
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "template_id": name,
        "root_id": f"quality_{name}",
        "entry": bp.entry,
        "levels": sorted({a.level for a in bp.areas}),
        "areas": [
            {
                "id": a.area_ref,
                "name": a.public_name,
                "offset": list(a.offset),
                "level": a.level,
                "secret": a.secret,
                "status": "here",
                "revision": 0,
                "sketch": geometry.build_area(bp, a),
            }
            for a in bp.areas
        ],
    }
    (directory / "render_payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (directory / "blueprint.json").write_text(json.dumps(bp.to_json(), ensure_ascii=False, indent=2) + "\n", "utf-8")
    details = [d for a in bp.areas for d in a.details]
    return {
        "id": name,
        "title": title,
        "areas": len(bp.areas),
        "details": len(details),
        "explicit_art": sum(bool(d.visual_key) for d in details),
    }


def main() -> None:
    report = json.loads((OUTPUT / "model-artwork-final.json").read_text(encoding="utf-8"))
    cases = {
        "temple_holders": "Храм с привязками",
        "temple_no_holders": "Храм без привязок",
        "tavern": "Таверна",
        "cave": "Пещера",
        "port": "Порт",
    }
    entries = []
    selected = set()
    for record in report["records"]:
        case = record["case"]
        if not record["accepted"] or case in selected:
            continue
        entries.append(export(LayoutIntent.model_validate(record["intent"]), f"model_{case}", f"Модель: {cases[case]}"))
        selected.add(case)
    for kind in ("tavern", "cave", "port"):
        mandate = Mandate(place=cases[kind], spatial=default_spatial(cases[kind], template_id=f"location.{kind}"))
        entries.append(export(intent_candidates(mandate)[0], f"fallback_{kind}", f"Резерв: {cases[kind]}"))
    for policy, title in (("normal", "Обычный свет"), ("dim", "Полумрак"), ("dark", "Без источников света")):
        details = [
            {
                "detail_ref": "table",
                "name": "Стол",
                "kind": "furniture",
                "visual_key": "feature:table",
                "cells": [[4, 4, 5, 5]],
            },
            {
                "detail_ref": "bench",
                "name": "Скамья",
                "kind": "furniture",
                "visual_key": "feature:bench",
                "cells": [[4, 6, 5, 6]],
            },
            {
                "detail_ref": "crate",
                "name": "Ящик",
                "kind": "object",
                "visual_key": "feature:crate",
                "cells": [[1, 1, 1, 1]],
            },
        ]
        if policy != "dark":
            details.append(
                {
                    "detail_ref": "torch",
                    "name": "Настенный факел",
                    "kind": "light",
                    "visual_key": "feature:torch",
                    "cells": [[6, 5, 6, 5]],
                }
            )
        intent = LayoutIntent.model_validate(
            {
                "entry": "hall",
                "parts": [
                    {
                        "part_ref": "hall",
                        "name": title,
                        "public_name": title,
                        "cols": 12,
                        "rows": 10,
                        "lighting": policy,
                        "details": details,
                    }
                ],
                "approaches": [{"part_ref": "hall", "side": "w", "kind": "door", "public_name": "Вход"}],
            }
        )
        entries.append(export(intent, f"lighting_{policy}", f"Свет: {title}"))
    (OUTPUT / "generated/manifest.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(entries, ensure_ascii=False))


if __name__ == "__main__":
    main()
