"""Звуковое сопровождение (проект design/audio-mixer.md): библиотека треков и состояние микшера сцены.

Треки лежат в одной папке ``AUDIO_DIR`` (в проекте — ``audio/``): файлы и ``tracks.yaml`` с карточками. Карточка —
источник правды: слой, настроения, места, темп, привязка к мирам. Админка пишет в ту же папку. Файл без карточки —
«неразобранный»: мастер его не видит.

Слои: ``music``, ``rhythm``, ``ambience`` — петли, в каждом не больше одной дорожки; ``sfx`` — один раз.
Мастер выбирает дорожки инструментами (app/tools/audio.py), сервер хранит выбор в ``scenes.state["audio"]`` и
рассылает его событием ``audio.state``; браузеры сводят слои сами.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.core.campaigns import Conflict, NotFound

LOOPS = ("music", "rhythm", "ambience")
LAYERS = (*LOOPS, "sfx")
LAYER_NAMES = {"music": "мелодия", "rhythm": "ритм", "ambience": "атмосфера", "sfx": "эффекты"}
MOODS = (
    "calm",
    "warm",
    "mystery",
    "wonder",
    "dread",
    "horror",
    "sorrow",
    "tension",
    "chase",
    "battle",
    "heroic",
    "triumph",
)
LEVELS = {"low": 0.35, "mid": 0.6, "high": 0.85}
CUES = ("victory", "death", "secret")  # короткие фразы, которые движок играет сам
EXT = {".ogg": "audio/ogg", ".opus": "audio/ogg", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}
MAX_BYTES = 20 * 1024 * 1024
MUSIC_COOLDOWN = 60.0  # секунд реального времени между сменами мелодии, кроме начала и конца боя
MAX_SFX = 2  # эффектов мастера за ход
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CARDS = "tracks.yaml"


@dataclass
class Track:
    id: str
    file: str
    layer: str
    title: str
    hint: str = ""
    moods: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    bpm: float | None = None
    bars: int | None = None
    gain_db: float = 0.0
    packs: list[str] = field(default_factory=list)
    cue: str | None = None
    off: bool = False
    version: str = ""  # меняется вместе с файлом: адрес с ним кэшируется браузером навсегда

    def card(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "file": self.file, "layer": self.layer, "title": self.title}
        if self.hint:
            out["hint"] = self.hint
        for k in ("moods", "places", "packs"):
            if getattr(self, k):
                out[k] = list(getattr(self, k))
        for k in ("bpm", "bars", "cue"):
            if getattr(self, k) is not None:
                out[k] = getattr(self, k)
        if self.gain_db:
            out["gain_db"] = self.gain_db
        if self.off:
            out["off"] = True
        return out

    def public(self) -> dict[str, Any]:
        """Что нужно плееру: адрес, громкость и сетка петли."""
        return {
            "id": self.id,
            "title": self.title,
            "layer": self.layer,
            "url": f"/api/audio/{self.id}?v={self.version}",
            "bpm": self.bpm,
            "bars": self.bars,
            "gain_db": self.gain_db,
        }

    def line(self, world: bool) -> str:
        """Строка каталога для мастера: коротко, чтобы не тратить токены."""
        tags = ", ".join(self.moods)
        if self.places:
            tags += ("; " if tags else "") + ", ".join(self.places)
        mark = "[мир] " if world else ""
        bpm = f" {int(self.bpm)} bpm" if self.bpm and self.layer in ("music", "rhythm") else ""
        return f"{self.id} — {mark}{self.hint or self.title}{f' [{tags}]' if tags else ''}{bpm}"


def _num(v: Any, what: str, tid: str) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise Conflict(f"трек {tid}: {what} — не число") from None


def parse_card(raw: Any) -> Track:
    """Карточка из tracks.yaml или из админки. Ошибка называет трек и поле."""
    if not isinstance(raw, dict):
        raise Conflict("карточка трека должна быть словарём с полями id, file, layer, title")
    tid = str(raw.get("id") or "").strip()
    if not ID_RE.fullmatch(tid):
        raise Conflict(f"id трека «{tid}»: только латиница в нижнем регистре, цифры, _ и -, до 64 символов")
    layer = str(raw.get("layer") or "")
    if layer not in LAYERS:
        raise Conflict(f"трек {tid}: слой «{layer}» неизвестен; допустимо: {', '.join(LAYERS)}")
    file = str(raw.get("file") or "").strip()
    if not file or "/" in file or "\\" in file or file.startswith("."):
        raise Conflict(f"трек {tid}: file — имя файла в папке звука, без папок")
    moods = [str(m) for m in raw.get("moods") or []]
    bad = [m for m in moods if m not in MOODS]
    if bad:
        raise Conflict(f"трек {tid}: неизвестные настроения {', '.join(bad)}; допустимо: {', '.join(MOODS)}")
    cue = raw.get("cue") or None
    if cue is not None and (cue not in CUES or layer != "sfx"):
        raise Conflict(f"трек {tid}: cue бывает только у эффектов и только {', '.join(CUES)}")
    bars = _num(raw.get("bars"), "bars", tid)
    return Track(
        id=tid,
        file=file,
        layer=layer,
        title=str(raw.get("title") or tid).strip()[:80],
        hint=str(raw.get("hint") or "").strip()[:160],
        moods=moods,
        places=[str(p).strip().lower() for p in raw.get("places") or [] if str(p).strip()],
        bpm=_num(raw.get("bpm"), "bpm", tid),
        bars=int(bars) if bars else None,
        gain_db=_num(raw.get("gain_db"), "gain_db", tid) or 0.0,
        packs=[str(p) for p in raw.get("packs") or []],
        cue=cue,
        off=bool(raw.get("off")),
    )


def tempo_fits(a: Track | None, b: Track | None) -> bool:
    """Мелодия и ритм сочетаются, если у обоих темп совпадает или отличается ровно вдвое. Без темпа — с любым."""
    if a is None or b is None or not a.bpm or not b.bpm:
        return True
    r = max(a.bpm, b.bpm) / min(a.bpm, b.bpm)
    return abs(r - 1) < 0.02 or abs(r - 2) < 0.04


class Library:
    """Папка треков. Перечитывается, когда меняется tracks.yaml или состав папки."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._stamp: tuple | None = None
        self._tracks: dict[str, Track] = {}
        self._errors: list[str] = []
        self._unsorted: list[str] = []

    # --- чтение ---

    def _files(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(p for p in self.root.iterdir() if p.is_file() and p.suffix.lower() in EXT)

    def _load(self) -> None:
        cards = self.root / CARDS
        files = self._files()
        stamp = (
            cards.stat().st_mtime_ns if cards.is_file() else None,
            tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files),
        )
        if stamp == self._stamp:
            return
        tracks: dict[str, Track] = {}
        errors: list[str] = []
        raw: Any = []
        if cards.is_file():
            try:
                raw = yaml.safe_load(cards.read_text(encoding="utf-8")) or []
            except yaml.YAMLError as e:
                errors.append(f"{CARDS} не читается: {e}")
                raw = []
        if not isinstance(raw, list):
            errors.append(f"{CARDS}: ожидается список карточек")
            raw = []
        by_name = {p.name: p for p in files}
        for item in raw:
            try:
                t = parse_card(item)
            except Conflict as e:
                errors.append(str(e))
                continue
            if t.id in tracks:
                errors.append(f"трек {t.id} описан дважды")
                continue
            p = by_name.get(t.file)
            if p is None:
                errors.append(f"трек {t.id}: нет файла {t.file} в папке звука")
                continue
            st = p.stat()
            t.version = hashlib.sha1(f"{t.file}:{st.st_size}:{st.st_mtime_ns}".encode()).hexdigest()[:10]
            tracks[t.id] = t
        used = {t.file for t in tracks.values()}
        self._tracks, self._errors = tracks, errors
        self._unsorted = [p.name for p in files if p.name not in used]
        self._stamp = stamp

    def all(self) -> list[Track]:
        self._load()
        return list(self._tracks.values())

    def get(self, tid: str) -> Track | None:
        self._load()
        return self._tracks.get(tid)

    def errors(self) -> list[str]:
        self._load()
        return list(self._errors)

    def unsorted(self) -> list[str]:
        self._load()
        return list(self._unsorted)

    def path(self, t: Track) -> Path:
        return self.root / t.file

    def playable(self) -> list[Track]:
        return [t for t in self.all() if not t.off]

    def for_pack(self, pack_id: str | None) -> list[Track]:
        """Треки кампании: сначала привязанные к её миру, потом общие. Треки других миров не видны."""
        own = [t for t in self.playable() if pack_id and pack_id in t.packs]
        common = [t for t in self.playable() if not t.packs]
        return own + common

    # --- запись (админка) ---

    def _raw_cards(self) -> list[Any]:
        cards = self.root / CARDS
        if not cards.is_file():
            return []
        try:
            raw = yaml.safe_load(cards.read_text(encoding="utf-8")) or []
        except yaml.YAMLError as e:
            raise Conflict(f"{CARDS} не читается, поправьте его вручную: {e}") from None
        if not isinstance(raw, list):
            raise Conflict(f"{CARDS}: ожидается список карточек, поправьте файл вручную")
        return raw

    def _write_cards(self, raw: list[Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=120)
        tmp = self.root / f".{CARDS}.tmp"
        tmp.write_text(
            "# Карточки треков: слой, настроения, места, темп, миры. Правит админка «Звук» или вы вручную.\n" + text,
            encoding="utf-8",
        )
        tmp.replace(self.root / CARDS)
        self._stamp = None

    def save_file(self, name: str, data: bytes) -> str:
        """Кладёт загруженный файл в папку. Имя очищается; занятое имя получает номер."""
        if not data:
            raise Conflict("пустой файл: браузер ничего не передал")
        if len(data) > MAX_BYTES:
            raise Conflict(f"файл больше {MAX_BYTES // (1024 * 1024)} МБ: сократите петлю или сожмите в OGG")
        stem, ext = Path(name or "").stem, Path(name or "").suffix.lower()
        if ext not in EXT:
            raise Conflict("формат не поддерживается: загрузите OGG (лучше всего), MP3, WAV или M4A")
        stem = re.sub(r"[^0-9A-Za-z_-]+", "_", stem).strip("_").lower()[:48] or "track"
        self.root.mkdir(parents=True, exist_ok=True)
        final, n = f"{stem}{ext}", 1
        while (self.root / final).exists():
            n += 1
            final = f"{stem}_{n}{ext}"
        (self.root / final).write_bytes(data)
        self._stamp = None
        return final

    def put(self, raw: dict[str, Any]) -> Track:
        """Создаёт или заменяет карточку по id."""
        t = parse_card(raw)
        if not (self.root / t.file).is_file():
            raise Conflict(f"нет файла {t.file} в папке звука: сначала загрузите его")
        cards = self._raw_cards()
        for other in cards:
            if isinstance(other, dict) and other.get("file") == t.file and other.get("id") != t.id:
                raise Conflict(f"файл {t.file} уже описан карточкой {other.get('id')}")
        out, replaced = [], False
        for other in cards:
            if isinstance(other, dict) and other.get("id") == t.id:
                out.append(t.card())
                replaced = True
            else:
                out.append(other)
        if not replaced:
            out.append(t.card())
        self._write_cards(out)
        return self.get(t.id) or t

    def remove(self, tid: str, *, delete_file: bool) -> None:
        cards = self._raw_cards()
        card = next((c for c in cards if isinstance(c, dict) and c.get("id") == tid), None)
        if card is None:
            raise NotFound("трек не найден: его уже удалили из tracks.yaml")
        self._write_cards([c for c in cards if c is not card])
        if delete_file:
            p = self.root / str(card.get("file") or "")
            if p.is_file() and p.parent == self.root:
                p.unlink()
        self._stamp = None

    def remove_unsorted(self, name: str) -> None:
        if name not in self.unsorted():
            raise NotFound("файл не найден среди неразобранных")
        (self.root / name).unlink()
        self._stamp = None


_library: Library | None = None


def configure(root: Path) -> Library:
    global _library
    _library = Library(root)
    return _library


def library() -> Library:
    global _library
    if _library is None:
        from app.config import ROOT

        _library = Library(ROOT / "audio")
    return _library


# --- кампания и сцена ---


def pack_of(campaign) -> str | None:
    """Мир кампании: её пакет сеттинга или верхний пакет цепочки."""
    if campaign.pack_id:
        return campaign.pack_id
    chain = campaign.content_chain or []
    return chain[-1][0] if chain else None


def enabled(campaign) -> bool:
    """Звук в кампании: владелец включил его, и в библиотеке есть хоть одна петля."""
    if not (campaign.settings or {}).get("audio_enabled"):
        return False
    return any(t.layer in LOOPS for t in library().for_pack(pack_of(campaign)))


def choices(campaign, layer: str) -> list[str]:
    return [t.id for t in library().for_pack(pack_of(campaign)) if t.layer == layer and not t.cue]


def where(ctx) -> str | None:
    """Чей звук меняет ход: место группы разделившегося отряда; None — общий звук отряда."""
    w = ctx.world
    return w.focus if w.focus and w.split else None


def mixer(scene, place: str | None = None) -> dict[str, Any]:
    """Микшер сцены. ``place`` — место группы разделившегося отряда: у неё свой звук, сначала — копия общего."""
    state = scene.state or {}
    own = (state.get("audio_at") or {}).get(place) if place else None
    st = dict(own if own is not None else state.get("audio") or {})
    for k in LOOPS:
        st.setdefault(k, None)
    st.setdefault("v", 0)
    st.setdefault("changed", {})
    st.setdefault("mourned", [])
    return st


def _store(scene, st: dict[str, Any], place: str | None = None) -> None:
    st["v"] = int(st.get("v", 0)) + 1
    if place:
        scene.state = {**(scene.state or {}), "audio_at": {**((scene.state or {}).get("audio_at") or {}), place: st}}
    else:
        scene.state = {**(scene.state or {}), "audio": st}


def regroup(ctx) -> None:
    """Части отряда сошлись: звучит то, что было у группы в месте встречи; разошлись — звук ушедших мест забыт."""
    sc = ctx.world.scene
    at = dict((sc.state or {}).get("audio_at") or {})
    if not at:
        return
    w = ctx.world
    groups = w.groups()
    if len(groups) > 1:
        if w.focus in at:  # группа ушла в другое место — её звук идёт с ней
            for p in w.scene_places():
                at.setdefault(p, at[w.focus])
        keep = {p: v for p, v in at.items() if p in groups}
        if keep != at:
            sc.state = {**sc.state, "audio_at": keep}
        return
    st = {k: v for k, v in sc.state.items() if k != "audio_at"}
    place = next(iter(groups), None)
    if place in at:
        v = max(int(at[place].get("v", 0)), int((st.get("audio") or {}).get("v", 0))) + 1
        st["audio"] = {**at[place], "v": v}
        ctx.signals.add("audio")
    sc.state = st


def views(campaign, scene, groups: dict) -> list[tuple[list[str] | None, dict[str, Any]]]:
    """Кому какой звук: пока отряд вместе — один всем; разделился — каждой группе свой, мастеру — общий."""
    if len(groups) <= 1:
        return [(None, public_state(campaign, scene))]
    out: list[tuple[list[str] | None, dict[str, Any]]] = []
    placed: set[str] = set()
    for place, heroes in groups.items():
        seats = [h.seat_id for h in heroes if h.seat_id]
        placed.update(seats)
        if seats:
            out.append((seats, public_state(campaign, scene, place)))
    rest = [x.id for x in campaign.seats if x.id not in placed]
    if rest:
        out.append((rest, public_state(campaign, scene)))
    return out


def public_state(campaign, scene, place: str | None = None) -> dict[str, Any]:
    """Состояние для игроков: включён ли звук, что звучит в каждом слое и с какого момента (для совпадения петель
    у всех). ``now`` — часы сервера: по ним клиент поправляет свои. ``place`` — звук группы этого места."""
    st = mixer(scene, place)
    lib = library()
    layers: dict[str, Any] = {}
    for k in LOOPS:
        cur = st.get(k)
        t = lib.get(cur["track"]) if cur else None
        layers[k] = {**t.public(), "level": LEVELS[cur.get("level", "mid")], "since": cur["since"]} if t else None
    on = bool((campaign.settings or {}).get("audio_enabled"))
    return {"enabled": on, "v": st["v"], "now": time.time(), "layers": layers if on else dict.fromkeys(LOOPS)}


def set_layer(
    scene, layer: str, track: Track | None, level: str | None = None, place: str | None = None, auto: bool = False
) -> None:
    """``auto`` — выбор движка, а не мастера: мастер может сменить такую дорожку сразу, без паузы в минуту."""
    st = mixer(scene, place)
    cur = st.get(layer)
    if track is None:
        st[layer] = None
    elif cur and cur["track"] == track.id:
        st[layer] = {**cur, "level": level or cur.get("level", "mid")}
    else:
        st[layer] = {"track": track.id, "level": level or "mid", "since": time.time()}
    st["changed"] = {
        **st["changed"],
        layer: {"at": time.time(), "mode": scene.mode, **({"auto": True} if auto else {})},
    }
    _store(scene, st, place)


def cue(ctx, track: Track) -> None:
    """Эффект прозвучит, когда ход будет опубликован: вместе с текстом мастера."""
    if track.id not in {c["id"] for c in ctx.audio}:
        ctx.audio.append(track.public())
    ctx.signals.add("audio")


def pick(campaign, layer: str, *, mood: str | None = None, cue_: str | None = None, fits: Track | None = None):
    """Первый подходящий трек: сначала мира, потом общий."""
    for t in library().for_pack(pack_of(campaign)):
        if t.layer != layer or (cue_ and t.cue != cue_) or (mood and mood not in t.moods):
            continue
        if not cue_ and t.cue:
            continue
        if fits is not None and not tempo_fits(fits, t):
            continue
        return t
    return None


def on_mode(ctx, mode: str, victory: bool = False) -> None:
    """Страховка движка: начался бой, а ритма нет — включаем боевой; бой окончен — ритм гаснет."""
    if not enabled(ctx.campaign):
        return
    sc = ctx.world.scene
    place = where(ctx)
    st = mixer(sc, place)
    lib = library()
    if mode == "combat" and st.get("rhythm") is None:
        music = lib.get(st["music"]["track"]) if st.get("music") else None
        t = pick(ctx.campaign, "rhythm", mood="battle", fits=music)
        if t is not None:
            set_layer(sc, "rhythm", t, place=place)
            ctx.signals.add("audio")
    elif mode == "free":
        if st.get("rhythm") is not None:
            set_layer(sc, "rhythm", None, place=place)
            ctx.signals.add("audio")
        if victory and (t := pick(ctx.campaign, "sfx", cue_="victory")):
            cue(ctx, t)


AUTO_QUIET = 600.0  # секунд: столько движок уважает тишину, которую мастер выбрал сам (music: off)
CALM = ("calm", "mystery", "wonder", "warm")
MOVE_TOOLS = ("move", "make_current")


def place_words(ctx, place: str | None) -> set[str]:
    """Чем место описано для подбора дорожки: части id шаблона, теги шаблона и места (tavern, carcass, ruins…)."""
    w = ctx.world
    pid = place or (w.scene_places()[0] if w.scene_places() else None) or w.scene.location_id
    out: set[str] = set()
    seen: set[str] = set()
    while pid and pid not in seen and len(seen) < 3:  # место и пара родителей: таверна в трущобах города
        seen.add(pid)
        e = w.entities.get(pid)
        if e is None:
            break
        tid = e.template_id or ""
        out |= {x for x in re.split(r"[._]", tid.lower()) if x and x != "location"}
        rec = w.catalog.find(tid) if tid else None
        out |= {str(t).lower() for t in ((rec.data.get("tags") if rec else None) or [])}
        out |= {str(t).lower() for t in (e.state or {}).get("tags") or []}
        pid = e.location_id
    return out


def _fit(t: Track, words: set[str], mood: str | None) -> float:
    score = 3.0 * len(set(t.places) & words)
    if mood:
        score += 4.0 if mood in t.moods else -10.0
    else:
        score += 1.0 if set(t.moods) & set(CALM) else 0.0
        score -= 5.0 if set(t.moods) & {"battle", "chase"} else 0.0
    return score


def best_music(campaign, words: set[str], mood: str | None) -> Track | None:
    tracks = [t for t in library().for_pack(pack_of(campaign)) if t.layer == "music" and not t.cue]
    if mood and not any(mood in t.moods for t in tracks):
        mood = "tension" if mood == "battle" and any("tension" in t.moods for t in tracks) else None
    if not tracks:
        return None
    # при равенстве — первая в каталоге: сначала дорожки мира
    return max(tracks, key=lambda t: (_fit(t, words, mood), -tracks.index(t)))


def autopilot(ctx) -> None:
    """Страховка движка, когда мастер не ведёт звук сам (техническая модель решения часто забывает про
    set_soundscape): при тишине включает мелодию под место или бой, при переходе в другое место подбирает
    дорожку под него. Выбор мастера в этом ходе и его осознанная тишина не трогаются."""
    if not enabled(ctx.campaign) or any(ev.tool == "set_soundscape" for ev in ctx.events):
        return
    sc = ctx.world.scene
    place = where(ctx)
    st = mixer(sc, place)
    fight = ctx.world.fighting_here()
    words = place_words(ctx, place)
    last = (st.get("changed") or {}).get("music") or {}
    ago = time.time() - float(last.get("at", 0))
    lib = library()
    cur = lib.get(st["music"]["track"]) if st.get("music") else None
    if cur is None:
        if last and not last.get("auto") and ago < AUTO_QUIET and last.get("mode") == sc.mode:
            return  # мастер сам выбрал тишину
        t = best_music(ctx.campaign, words, "battle" if fight else None)
    elif any(ev.tool in MOVE_TOOLS for ev in ctx.events) and not fight and ago >= MUSIC_COOLDOWN:
        t = best_music(ctx.campaign, words, None)
        if t is None or _fit(t, words, None) <= _fit(cur, words, None):
            return  # нынешняя дорожка подходит новому месту не хуже
    else:
        return
    if t is None:
        return
    set_layer(sc, "music", t, place=place, auto=True)
    rhythm = lib.get(st["rhythm"]["track"]) if st.get("rhythm") else None
    if rhythm is not None and not tempo_fits(t, rhythm):
        set_layer(sc, "rhythm", None, place=place, auto=True)  # ритм не ложится на новую мелодию: каша хуже тишины
    ctx.signals.add("audio")


def finalize(ctx) -> None:
    """Конец хода, до фиксации: короткие фразы на гибель героя и раскрытую тайну."""
    if not enabled(ctx.campaign):
        return
    sc = ctx.world.scene
    st = mixer(sc)
    fallen = [
        ch.id
        for ch in ctx.world.characters.values()
        if ch.status == "dead" and ch.id in ctx.changed and ch.id not in st["mourned"]
    ]
    if fallen:
        st["mourned"] = [*st["mourned"], *fallen]
        _store(sc, st)
        if t := pick(ctx.campaign, "sfx", cue_="death"):
            cue(ctx, t)
    if any(ev.tool == "plot_reveal" for ev in ctx.events) and (t := pick(ctx.campaign, "sfx", cue_="secret")):
        cue(ctx, t)


def prompt_block(campaign, scene, place: str | None = None) -> str:
    """Блок «Звук» для системной инструкции мастера: что звучит и каталог дорожек."""
    if not enabled(campaign):
        return ""
    pack = pack_of(campaign)
    st = mixer(scene, place)
    lib = library()
    now_ = []
    for k in LOOPS:
        cur = st.get(k)
        t = lib.get(cur["track"]) if cur else None
        playing = f"{t.id} ({cur.get('level', 'mid')})" if t else "тишина"
        now_.append(f"{LAYER_NAMES[k]}: {playing}")
    lines = []
    for k in LAYERS:
        items = [t for t in lib.for_pack(pack) if t.layer == k and not t.cue]
        if items:
            lines.append(f"{LAYER_NAMES[k].capitalize()}:")
            lines += [f"- {t.line(bool(pack and pack in t.packs))}" for t in items]
    return "Сейчас звучит — " + "; ".join(now_) + ".\nДорожки:\n" + "\n".join(lines)
