# Taleforge

Текстовая ролевая игра с ИИ-мастером по правилам D&D 5e (SRD 5.1).

ИИ — голос, приложение — мир: вся механика, числа и состояние живут в коде и данных, модель только описывает и вызывает инструменты.

Техническое задание — документ «ТЗ: AI-Мастер для текстовых ролевых игр» в проекте.

## Структура

```
app/
  rules/          # движок правил: интерфейс RulesEngine, кубики
    dnd5e/        # реализация по SRD 5.1
  content/        # загрузка и проверка пакетов контента, ядровая схема
  core/ tools/ agents/ gateway/ api/   # следующие этапы
content/
  dnd5e-srd/      # базовый пакет правил (SRD 5.1, CC BY 4.0)
tests/
```

Пакеты сеттинга лежат рядом с базовым в `content/<id>/` и подключают его через `ruleset_base: srd-5.1`.

## Запуск

```
pip install -e ".[dev]"
pytest
python -m app.content validate content/dnd5e-srd
python -m app.content validate путь/к/пакету --customs   # свой мир
```

## Лицензия SRD

This work includes material taken from the System Reference Document 5.1 ("SRD 5.1") by Wizards of the Coast LLC and available at https://dnd.wizards.com/resources/systems-reference-document. The SRD 5.1 is licensed under the Creative Commons Attribution 4.0 International License available at https://creativecommons.org/licenses/by/4.0/legalcode.
