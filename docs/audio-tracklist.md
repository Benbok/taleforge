# Стартовый набор треков — список для подготовки

Под проект [audio-mixer.md](audio-mixer.md). Набор общий (поле `packs` пустое), но звучит в духе «Эха Левиафанов»: медь, пар, гул живых кораблей, гримдарк без лютневой пасторали. Всё, что ниже, годится и для другого мира.

## Общие правила для всех петель

- **Темп — 100 BPM у всех мелодий и ритмов**, размер 4/4. Спокойные треки могут звучать «вполсилы» (ощущение 50 BPM), но сетка та же. Тогда любой ритм ложится на любую мелодию.
- **Длина петли** — ровно 16 или 32 такта (38,4 или 76,8 с при 100 BPM). Конец должен переходить в начало без паузы и без затухания.
- **Мелодии — без ударных**, ритмы — без мелодии и баса с нотами (только перкуссия, шумы, низкий удар).
- **Атмосферы** — без музыки и без темпа, 1–2 минуты, бесшовная петля.
- **Формат** — OGG (Vorbis или Opus), стерео, 44,1 или 48 кГц, громкость примерно −16 LUFS. Если генератор отдаёт MP3 или WAV, перевести в OGG (например, Audacity: «Экспорт → OGG»).
- В подсказки генератору всегда добавлять: `seamless loop, no intro, no outro, no fade`.

Подсказки даны по-английски: генераторы музыки понимают их лучше.

## Слой 1. Мелодия (music), 100 BPM, без ударных

| id | Название | Когда | Настроения | Подсказка генератору |
|---|---|---|---|---|
| `mel_rest` | Тёплый отсек | отдых, лагерь, таверна, разговор | calm, warm | `slow warm ambient folk, cello and bowed dulcimer, soft pad, melancholic but safe, 100 bpm half-time feel, no drums, seamless loop, no intro, no outro, no fade` |
| `mel_explore` | Под рёбрами гиганта | исследование, путь, туши, руины | mystery, wonder | `mysterious exploration score, low strings ostinato, glass harmonica, distant metallic resonance, 100 bpm, no drums, seamless loop, no intro, no outro, no fade` |
| `mel_dread` | Отклик роя | ужас, заражённые, тайна, погоня в темноте | dread, horror, tension | `dark horror drone score, dissonant string clusters, whispering choir, organic creaking textures, sparse, 100 bpm grid, no drums, seamless loop, no intro, no outro, no fade` |
| `mel_battle` | Медь и ликвор | бой, босс, героический момент | battle, heroic | `epic dark orchestral battle theme, brass and low strings, driving ostinato, grimdark steampunk, 100 bpm, no drums, no percussion, seamless loop, no intro, no outro, no fade` |
| `mel_sorrow` (по желанию) | Тишина после | потеря, похороны, эпилог | sorrow | `sad solo cello with soft pad, slow, 100 bpm half-time feel, no drums, seamless loop, no intro, no outro, no fade` |

## Слой 2. Ритм (rhythm), 100 BPM, только перкуссия

| id | Название | Когда | Настроения | Подсказка генератору |
|---|---|---|---|---|
| `rhy_war` | Барабаны Кордона | бой | battle | `war drums only, taiko and industrial metal hits, powerful, 100 bpm, percussion only, no melody, no bass notes, seamless loop, no intro, no outro, no fade` |
| `rhy_march` | Шаг шагохода | поход, марш, спешка | tension, heroic | `marching percussion, frame drum and mechanical clanks, steady, 100 bpm, percussion only, no melody, seamless loop, no intro, no outro, no fade` |
| `rhy_pulse` | Тревожный пульс | погоня, таймер угрозы, крадущаяся опасность | tension, chase, dread | `tense heartbeat pulse, low sub kick and ticking clock, sparse, 100 bpm, percussion only, no melody, seamless loop, no intro, no outro, no fade` |

## Слой 3. Атмосфера (ambience), без темпа

| id | Название | Места | Подсказка генератору (звуковые эффекты) |
|---|---|---|---|
| `amb_tavern` | Портовая таверна | tavern, town | `crowded tavern ambience, murmuring voices, clinking mugs, creaking wood, distant harbor bell, seamless loop` |
| `amb_carcass` | Внутри туши | carcass, dungeon | `inside a giant dead creature, deep organic groans, dripping fluid, echoing hollow space, distant metal creaks, seamless loop` |
| `amb_wastes` | Пепельная черта | wastes, road, camp | `desolate windy wasteland, ash wind gusts, distant thunder, faint crackling campfire, seamless loop` |
| `amb_sea` | Ночное море | sea, ship, coast | `night sea ambience, waves against a ship hull, rigging creaks, distant whale-like calls, seamless loop` |
| `amb_city` (по желанию) | Город-мастерская | city, market | `industrial steampunk city ambience, steam hiss, telegraph clicks, distant trains, crowd, seamless loop` |

## Слой 4. Эффекты (sfx), один раз, 1–4 секунды

| id | Что | Подсказка генератору |
|---|---|---|
| `sfx_thunder` | Гром | `single close thunder crack with rumble` |
| `sfx_roar` | Рык твари роя | `monstrous insectoid roar with wet chitin clicks` |
| `sfx_door` | Скрип тяжёлой двери или люка | `heavy iron hatch creaking open` |
| `sfx_bell` | Тревожный колокол | `single alarm bell toll with echo` |
| `sfx_blast` | Взрыв, выстрел | `distant explosion with debris` |
| `sfx_whisper` | Шёпот Резонанса | `eerie layered whispers swelling and fading` |

## Короткие фразы на события (sfx, играет движок сам), 3–6 секунд

| id | Событие | Подсказка генератору |
|---|---|---|
| `stg_victory` | победа в бою | `short triumphant brass sting, 4 seconds, ends cleanly` |
| `stg_death` | гибель героя | `short tragic low string and choir sting, 5 seconds, ends cleanly` |
| `stg_secret` | раскрытая тайна | `short mysterious reveal sting, glass harmonica and swell, 4 seconds` |

## Как положить в проект

Файлы — в папку `audio/`, карточки — в `audio/tracks.yaml`. Пример одной карточки:

```yaml
- id: mel_rest
  file: mel_rest.ogg
  layer: music
  title: "Тёплый отсек"
  hint: "тёплый покой: отдых, лагерь, таверна, разговор"
  moods: [calm, warm]
  places: [tavern, camp]
  bpm: 100
  bars: 16
```

Минимум для проверки — по одному треку на слой: `mel_rest`, `rhy_war`, `amb_tavern`, `sfx_thunder`. Остальное можно добавлять постепенно, в том числе через админку.
