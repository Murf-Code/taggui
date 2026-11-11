"""Prompt presets for the LM Studio / Ollama captioner, ported from
TagBench's caption modes. They only fill in the prompt boxes and where the
result goes; nothing leaves the computer except the request to the local
server."""
from dataclasses import dataclass

from auto_captioning.models.local_server import (DEFAULT_SYSTEM_PROMPT,
                                                 DEFAULT_USER_PROMPT)
from utils.enums import CaptionPosition

GROUNDING_SYSTEM_PROMPT = (
    'You are an objective visual data-labeling model. Your task is to '
    'provide a factual, highly accurate description of the image for model '
    'training.\n\n'
    'STRICT GROUNDING RULES:\n'
    '1. Describe ONLY elements that are directly visible in the image or '
    'explicitly stated in verified tags.\n'
    '2. Never guess, assume, or extrapolate details (e.g., unseen background '
    'items, specific context, emotions, or implied actions).\n'
    '3. Do NOT mention any artist names, creators, signatures, watermarks, '
    'or online handles.\n'
    '4. If a visual element is ambiguous or unclear, describe its appearance '
    'broadly without guessing what it is.')

# `{tags}` is replaced with the image's current tags by TagGUI.
TAG2CAPTION_USER_PROMPT = (
    'Describe this image concise and accurately for dataset training.\n\n'
    'VERIFIED REFERENCE TAGS FOR THIS IMAGE: {tags}.\n'
    'Ensure your visual caption is consistent with these tags.')

# TagBench sends JoyCaption no instructions for "JoyCaption — caption"; a
# local server needs a user prompt, so this is Tag2Caption's opening line.
CAPTION_USER_PROMPT = (
    'Describe this image concise and accurately for dataset training.')


def short_tags_user_prompt(max_tags: int) -> str:
    """TagBench's `tagInstructions` (src/caption-jobs.ts)."""
    return ('List only what is visible, as comma-separated booru tags. '
            'No sentences. No artist names, signatures, or handles. '
            f'At most {max_tags} tags. Put the most specific tags first.')


# TagBench's default "Max tags" (src/AutoCaption.tsx).
DEFAULT_PRESET_MAX_TAGS = 40


@dataclass
class PromptPreset:
    name: str
    description: str
    user_prompt: str
    system_prompt: str
    caption_position: str
    split_tags: bool
    temperature: float | None = None
    uses_max_tags: bool = False


# Names and hints are TagBench's caption modes (src/caption-jobs.ts
# CAPTION_MODES); the first entry puts back TagGUI's own default prompts.
PROMPT_PRESETS = [
    PromptPreset(
        'Default prompts',
        'The default tagging prompts. Tags are added after the last tag.',
        DEFAULT_USER_PROMPT, DEFAULT_SYSTEM_PROMPT,
        CaptionPosition.AFTER_LAST_TAG, True),
    PromptPreset(
        'JoyCaption \u2014 tags',
        'Comma-separated tags from the picture.',
        '', DEFAULT_SYSTEM_PROMPT,
        CaptionPosition.AFTER_LAST_TAG, True, 0.4, uses_max_tags=True),
    PromptPreset(
        'JoyCaption \u2014 caption',
        'A natural description of the picture.',
        CAPTION_USER_PROMPT, GROUNDING_SYSTEM_PROMPT,
        CaptionPosition.NL_REPLACE, False, 0.4),
    PromptPreset(
        'Tag2Caption',
        'Turns the tags already on the picture into a natural caption, '
        'with the same instructions as Tag2Caption.',
        TAG2CAPTION_USER_PROMPT, GROUNDING_SYSTEM_PROMPT,
        CaptionPosition.NL_REPLACE, False, 0.1),
]


def get_preset(name: str) -> PromptPreset | None:
    return next((preset for preset in PROMPT_PRESETS
                 if preset.name == name), None)
