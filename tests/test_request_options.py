import os
import runpy
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'contrib/deepseek_data/request_options.py'
options = runpy.run_path(str(MODULE))['reasoning_options']


def test_defaults_are_preserved_and_compat_is_opt_in():
    defaults = [{'reasoning_effort': 'high'}, {'reasoning_effort': 'low'},
                {'thinking': {'type': 'enabled', 'budget_tokens': 16384}}, {}]
    with patch.dict(os.environ, {'QUEST_DEEPSEEK_COMPAT': '0'}):
        for default in defaults:
            assert options(default) == default
    with patch.dict(os.environ, {'QUEST_DEEPSEEK_COMPAT': '1'}):
        for default in defaults:
            assert options(default) == {'extra_body': {'thinking': {'type': 'disabled'}}}
