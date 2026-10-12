# Примеры карт локаций

JSON-файлы — стабильные снимки серверного `MapLocationPlan`, а SVG рядом с ними —
воспроизводимый экспорт для документации. Обновить их можно командами:

```text
uv run python tools/export_location_map_examples.py
cd web
npm run map:examples
```

`field-stream-bridge` показывает дорогу, ручей и мост; `temple-known` — приглушённую
память второго уровня; `hero-memory` — индивидуально запомненный участок.
