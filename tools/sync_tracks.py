from pathlib import Path

import yaml

p = Path("audio/tracks.yaml")
content = p.read_text(encoding="utf-8")
data = yaml.safe_load(content)

for item in data:
    if "file" not in item:
        item["file"] = f"{item['id']}.ogg"

# Format cleanly
lines = ["# Библиотека звуков TaleForge — Сеттинг «Эхо Левиафанов»", ""]
for item in data:
    lines.append(f"- id: {item['id']}")
    lines.append(f"  file: {item['file']}")
    lines.append(f"  layer: {item['layer']}")
    lines.append(f'  title: "{item["title"]}"')
    lines.append(f'  hint: "{item["hint"]}"')
    lines.append(f"  moods: [{', '.join(item.get('moods', []))}]")
    lines.append(f"  places: [{', '.join(item.get('places', []))}]")
    bpm_val = item.get("bpm")
    lines.append(f"  bpm: {bpm_val if bpm_val is not None else 'null'}")
    if "bars" in item and item["bars"] is not None:
        lines.append(f"  bars: {item['bars']}")
    lines.append(f"  gain_db: {item.get('gain_db', 0)}")
    lines.append(f"  packs: [{', '.join(item.get('packs', []))}]")
    lines.append("")

p.write_text("\n".join(lines), encoding="utf-8")
print("Successfully synced audio/tracks.yaml with file attribute")
