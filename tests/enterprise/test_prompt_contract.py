from types import SimpleNamespace
from unittest.mock import patch

from openchatbi.prompts import system_prompt


def test_application_rules_override_alias_defaults_and_refresh():
    cfg = SimpleNamespace(bi_config={'text2sql_extra_rule': 'Use department_name, never a translated alias.'})
    with patch.object(system_prompt, 'get_text2sql_prompt_template', return_value='Generic alias rule'), \
         patch.object(system_prompt, 'get_dialect_rules', return_value={}), \
         patch.object(system_prompt.config, 'get', return_value=cfg):
        prompt = system_prompt.get_text2sql_dialect_prompt_template('postgres')
        assert prompt.endswith(cfg.bi_config['text2sql_extra_rule'])
        assert 'override conflicting general alias rules' in prompt
        cfg.bi_config = {}
        assert system_prompt.get_text2sql_dialect_prompt_template('postgres') == 'Generic alias rule'
