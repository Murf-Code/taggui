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

CAPTION_USER_PROMPT = (
    'Describe this image concise and accurately for dataset training, in '
    'one paragraph of plain sentences.')

SHORT_TAGS_USER_PROMPT = (
    'List only what is visible, as comma-separated booru tags. No '
    'sentences. No artist names, signatures, or handles. Put the most '
    'specific tags first.')


@dataclass
class PromptPreset:
    name: str
    description: str
    user_prompt: str
    system_prompt: str
    caption_position: str
    split_tags: bool
    temperature: float | None = None


PROMPT_PRESETS = [
    PromptPreset(
        'e621 tags (Prompt Helper default)',
        'The default tagging prompts. Tags are added after the last tag.',
        DEFAULT_USER_PROMPT, DEFAULT_SYSTEM_PROMPT,
        CaptionPosition.AFTER_LAST_TAG, True),
    PromptPreset(
        'Booru tags (short)',
        'Short comma-separated tag list, most specific first.',
        SHORT_TAGS_USER_PROMPT, DEFAULT_SYSTEM_PROMPT,
        CaptionPosition.AFTER_LAST_TAG, True),
    PromptPreset(
        'Natural-language caption',
        'A plain description written into the natural-language caption.',
        CAPTION_USER_PROMPT, GROUNDING_SYSTEM_PROMPT,
        CaptionPosition.NL_REPLACE, False, 0.4),
    PromptPreset(
        'Tag2Caption (caption from existing tags)',
        'Turns the tags already on each image into a natural caption '
        '(TagBench\'s Tag2Caption).',
        TAG2CAPTION_USER_PROMPT, GROUNDING_SYSTEM_PROMPT,
        CaptionPosition.NL_REPLACE, False, 0.1),
]


def get_preset(name: str) -> PromptPreset | None:
    return next((preset for preset in PROMPT_PRESETS
                 if preset.name == name), None)
