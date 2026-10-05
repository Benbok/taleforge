"""Инструменты мастера (ТЗ, разделы 7, 7.1, 7.2, 8.1). Числа считает движок правил, мастер передаёт только
шаблоны, цели и параметры из данных. Каждый изменяющий вызов оставляет событие в журнале с обратной дельтой.

Инструменты разложены по темам. Порядок импорта ниже — порядок регистрации в реестре, в нём их видит модель.
Заклинания — в app/tools/spells.py (``cast_spell``).
"""

# isort: off
from app.tools.master import read  # noqa: F401
from app.tools.master import checks  # noqa: F401
from app.tools.master import items  # noqa: F401
from app.tools.master import entities  # noqa: F401
from app.tools.master import places  # noqa: F401
from app.tools.master import knowledge  # noqa: F401
from app.tools.master import scene  # noqa: F401
from app.tools.master import talk  # noqa: F401
# isort: on
