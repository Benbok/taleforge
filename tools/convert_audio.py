#!/usr/bin/env python3
"""
tools/convert_audio.py

Утилита конвертации аудиофайлов (MP4, MP3, WAV) в формат OGG Vorbis
для звукового микшера TaleForge с поддержкой создания бесшовных лупов (loop crossfade).

Использование:
    1. Пакетная конвертация из папки audio/raw/:
       python tools/convert_audio.py

    2. Конвертация отдельного MP4 файла в конкретный трек:
       python tools/convert_audio.py audio/raw/tavern.mp4 --id mel_tavern_cozy

    3. Конвертация с созданием идеального бесшовного лупа (60 секунд, 3 сек кроссфейд):
       python tools/convert_audio.py audio/raw/battle.mp4 --id rhy_assault_taiko --loop

    4. Интерактивный режим выбора треков из tracks.yaml:
       python tools/convert_audio.py --interactive
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = PROJECT_ROOT / "audio"
RAW_DIR = AUDIO_DIR / "raw"
TRACKS_YAML = AUDIO_DIR / "tracks.yaml"


def check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def get_audio_duration(file_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 0.0


def parse_tracks_yaml() -> list[dict]:
    """Простой парсер tracks.yaml без сторонних библиотек"""
    if not TRACKS_YAML.exists():
        return []

    tracks = []
    current_track = {}
    content = TRACKS_YAML.read_text(encoding="utf-8")

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("- id:"):
            if current_track and "id" in current_track:
                tracks.append(current_track)
            current_track = {"id": line.replace("- id:", "").strip()}
        elif ":" in line and current_track:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # убираем кавычки
            val = val.strip("'\"")
            current_track[key] = val

    if current_track and "id" in current_track:
        tracks.append(current_track)

    return tracks


def convert_file(
    input_file: Path,
    output_file: Path,
    loop: bool = True,
    fade: float = 4.0,
    start: float = 0.0,
    duration: float = 0.0,
) -> bool:
    """Конвертирует MP4/MP3/WAV в OGG Vorbis с плавным бесшовным кроссфейдом конца в начало"""
    total_dur = get_audio_duration(input_file)
    print(f"\n[+] Обработка: {input_file.name} -> {output_file.name}")
    if total_dur > 0:
        print(f"    Длительность исходника: {total_dur:.1f} сек")

    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Если это короткий SFX (меньше 10 секунд), зацикливать не нужно
    if total_dur > 0 and total_dur <= 10.0:
        loop = False

    if loop and total_dur > (fade * 2):
        # Если duration не указан, берем ВСЮ длину трека
        actual_dur = duration if duration > 0 else (total_dur - start)
        actual_fade = min(fade, actual_dur / 4)
        head_dur = actual_dur - actual_fade

        print(f"    Режим БЕСШОВНОГО ЛУПА: длина ({actual_dur:.1f}с), кроссфейд конца в начало ({actual_fade:.1f}с)")

        filter_complex = (
            f"[0:a]asplit=2[a1][a2];"
            f"[a1]atrim=start={head_dur}:end={actual_dur},asetpts=PTS-STARTPTS[tail];"
            f"[a2]atrim=start={start}:end={head_dur},asetpts=PTS-STARTPTS[head];"
            f"[tail][head]acrossfade=d={actual_fade}:c1=tri:c2=tri[out]"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_file),
            "-vn",
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-c:a",
            "libvorbis",
            "-q:a",
            "4",
            str(output_file),
        ]
    else:
        print("    Прямая конвертация (без зацикливания)")
        cmd = ["ffmpeg", "-y", "-i", str(input_file), "-vn", "-c:a", "libvorbis", "-q:a", "4", str(output_file)]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[!] Ошибка ffmpeg: {res.stderr}")
            return False

        size_kb = output_file.stat().st_size / 1024
        print(f"    Готово: {output_file} ({size_kb:.1f} КБ)")
        return True
    except Exception as e:
        print(f"[!] Ошибка: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Конвертер аудио TaleForge (MP4/MP3 -> OGG)")
    parser.add_argument("input", nargs="?", help="Входной файл или папка (по умолчанию audio/raw/)")
    parser.add_argument("--id", help="Целевой ID трека из tracks.yaml (например mel_tavern_cozy)")
    parser.add_argument("--no-loop", action="store_true", help="Отключить бесшовный луп (простая прямая конвертация)")
    parser.add_argument(
        "--start", "-s", type=float, default=0.0, help="Начало фрагмента в секундах (по умолч. 0.0 - с самого начала)"
    )
    parser.add_argument(
        "--duration", "-d", type=float, default=0.0, help="Длина лупа в секундах (по умолч. 0.0 - весь трек целиком)"
    )
    parser.add_argument(
        "--fade", "-f", type=float, default=4.0, help="Длина кроссфейда конца в начало в секундах (по умолч. 4.0)"
    )
    parser.add_argument("--interactive", "-i", action="store_true", help="Интерактивный выбор ID для каждого файла")

    args = parser.parse_args()

    if not check_ffmpeg():
        print("[!] ОШИБКА: FFmpeg не найден в системе. Убедитесь, что ffmpeg доступен в PATH.")
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    all_tracks = parse_tracks_yaml()
    track_ids = {t["id"] for t in all_tracks}
    do_loop = not args.no_loop

    # 1. Если указан конкретный файл
    if args.input and Path(args.input).is_file():
        in_path = Path(args.input)
        if args.id:
            out_id = args.id
        else:
            stem = in_path.stem
            out_id = stem if stem in track_ids else stem

        out_path = AUDIO_DIR / f"{out_id}.ogg"
        convert_file(in_path, out_path, loop=do_loop, start=args.start, duration=args.duration, fade=args.fade)
        return

    # 2. Поиск файлов в папке (по умолчанию audio/raw/)
    search_dir = Path(args.input) if args.input and Path(args.input).is_dir() else RAW_DIR
    raw_files = sorted(
        [f for f in search_dir.iterdir() if f.is_file() and f.suffix.lower() in [".mp4", ".mp3", ".wav", ".m4a"]]
    )

    if not raw_files:
        print(f"[*] В папке '{search_dir}' пока нет файлов для конвертации.")
        print(f"[*] Скидывайте скачанные с Suno .mp4 в папку: {search_dir}")
        print("    Пример: положи файл 'mel_tavern_cozy.mp4' в audio/raw/ и запусти этот скрипт.")
        return

    print(f"[*] Найдено файлов для конвертации: {len(raw_files)}")

    for raw_file in raw_files:
        stem = raw_file.stem
        target_id = None

        if stem in track_ids:
            target_id = stem
        elif args.id:
            target_id = args.id
        elif args.interactive:
            print(f"\nФайл: {raw_file.name}")
            missing = [t for t in all_tracks if not (AUDIO_DIR / f"{t['id']}.ogg").exists()]
            print("Доступные незаполненные треки:")
            for idx, t in enumerate(missing[:15]):
                print(f"  [{idx + 1}] {t['id']} — {t.get('title', '')} ({t.get('layer', '')})")
            choice = input("Введите номер трека (или точный ID, либо Enter для пропуска): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(missing):
                target_id = missing[int(choice) - 1]["id"]
            elif choice in track_ids:
                target_id = choice
            else:
                target_id = stem
        else:
            target_id = stem

        out_file = AUDIO_DIR / f"{target_id}.ogg"
        convert_file(raw_file, out_file, loop=do_loop, start=args.start, duration=args.duration, fade=args.fade)

    print("\n[V] Конвертация завершена!")


if __name__ == "__main__":
    main()
