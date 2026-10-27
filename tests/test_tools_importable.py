import importlib

import pytest


@pytest.mark.parametrize("name", ["tools.import_srd", "tools.eval_turn_efficiency"])
def test_maintenance_tools_import_without_retired_modules(name):
    importlib.import_module(name)
