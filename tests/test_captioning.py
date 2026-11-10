from pathlib import Path

# Import order matches the app (the two modules import each other).
from auto_captioning.captioning_thread import add_caption_to_tags
from auto_captioning.auto_captioning_model import replace_template_variables
from auto_captioning.models.local_server import limit_tags
from auto_captioning.prompt_presets import PROMPT_PRESETS, get_preset
from utils.enums import CaptionPosition
from utils.image import Image


def test_nl_positions_leave_tags_alone():
    for position in (CaptionPosition.NL_REPLACE, CaptionPosition.NL_APPEND):
        assert add_caption_to_tags(['a'], 'A caption.', position) == ['a']


def test_existing_positions_unchanged():
    assert add_caption_to_tags(['a'], 'b',
                               CaptionPosition.AFTER_LAST_TAG) == ['a', 'b']


def test_limit_tags():
    assert limit_tags('a, b, c', ', ', 2) == 'a, b'
    assert limit_tags('a, b, c', ', ', 0) == 'a, b, c'


def test_tag2caption_preset_uses_existing_tags():
    preset = get_preset('Tag2Caption (caption from existing tags)')
    assert preset.caption_position == CaptionPosition.NL_REPLACE
    assert not preset.split_tags
    image = Image(Path('x.png'), None, ['cat', 'solo'])
    prompt = replace_template_variables(preset.user_prompt, image)
    assert 'VERIFIED REFERENCE TAGS FOR THIS IMAGE: cat, solo.' in prompt


def test_default_preset_is_prompt_helper_default():
    from auto_captioning.models.local_server import (DEFAULT_SYSTEM_PROMPT,
                                                     DEFAULT_USER_PROMPT)
    default = PROMPT_PRESETS[0]
    assert default.user_prompt == DEFAULT_USER_PROMPT
    assert default.system_prompt == DEFAULT_SYSTEM_PROMPT
