"""Auto-captioning through a local LM Studio or Ollama server.

No model is downloaded or loaded by TagGUI. Each image is sent (base64) to
whatever model is loaded in LM Studio / Ollama, together with the prompt box
text (user prompt) and the system prompt from the settings.
"""
import base64
import io
import json
import re
import urllib.error
import urllib.request
from datetime import datetime

from PIL import Image as PilImage
from PIL.ImageOps import exif_transpose

from auto_captioning.auto_captioning_model import AutoCaptioningModel
from utils.image import Image

LM_STUDIO_MODEL_ID = 'LM Studio (local server)'
OLLAMA_MODEL_ID = 'Ollama (local server)'
LOCAL_SERVER_MODEL_IDS = (LM_STUDIO_MODEL_ID, OLLAMA_MODEL_ID)

DEFAULT_LM_STUDIO_URL = 'http://localhost:1234'
DEFAULT_OLLAMA_URL = 'http://localhost:11434'
DEFAULT_USER_PROMPT = (
    'Tag this image for LoRA training. Output one line of comma-separated e621 tags, in this order:\n'
    '1. count (solo, duo, trio, group)\n'
    "2. each character's species, plus anthro or feral for each one\n"
    '3. sex only if genitals or clear sex traits are visible\n'
    '4. for each character: fur colours, markings, body type, pose, expression, gaze\n'
    '5. clothing and accessories, with their colours\n'
    '6. held objects as "holding X" plus the object, and other props\n'
    '7. interaction and themes (size difference, romantic, humor)\n'
    '8. medium (traditional media (artwork), marker (artwork), digital media (artwork))\n'
    '9. background (white background, simple background, detailed background)\n'
    'Tag only what is visible. Output the tags only.')
DEFAULT_SYSTEM_PROMPT = (
    'You are an e621 tagger. Reply with one line of lowercase comma-separated tags, using spaces instead of underscores and no other text.\n'
    'Rules:\n'
    '- Use the specific species only, e.g. husky, not wolf, canine or canid. A husky is a husky, never wolf.\n'
    '- Each tag is a short separate e621 tag, never a phrase or sentence. Species, anthro and feral are separate tags (snow leopard, anthro). Separate tags with commas only. Put quoted text in double quotes.\n'
    '- Never use: furry, fursona, anthropomorphic, safe, questionable, explicit, rating tags, quality tags, score tags, age tags, hair tags, watermark, signature, artist name, cartoon style.\n'
    '- Tag every animal character as anthro (stands upright, human-like hands) or feral (animal body, on all fours).\n'
    '- Use male, female and pairing tags such as male/female only when the sex is clearly visible. Otherwise leave sex out.\n'
    '- Use looking at viewer only when the eyes meet the viewer. Otherwise use looking at another, looking up, looking down, looking away or side glance.\n'
    '- Paper, ink, marker or pencil texture means traditional media (artwork). Only clean digital rendering means digital media (artwork).\n'
    '- Pairing tags use a slash: male/male, male/female, female/female.\n'
    '- A biped with a human-like torso and paws used as hands is anthro, not feral.\n'
    '- Tag penis shape by what is visible (canine penis, equine penis), tag knot separately when visible, and use pussy instead of vulva.\n'
    '- For short visible text, add text and text reads "..." with the words exactly as written.\n'
    '- Never guess. If unsure, leave the tag out.')
# Default longest image side sent to the server (the "Max image size"
# setting). Larger images are downscaled; smaller ones are sent as-is.
DEFAULT_MAX_IMAGE_SIDE = 720
MIN_IMAGE_SIDE = 256
MAX_IMAGE_SIDE = 4096


def is_local_server_model(model_id: str) -> bool:
    return model_id in LOCAL_SERVER_MODEL_IDS


def strip_think(text: str) -> str:
    """Remove reasoning blocks such as `<think>...</think>`."""
    text = re.sub(r'<(think|thinking|reasoning)>.*?</\1>', '', text,
                  flags=re.DOTALL | re.IGNORECASE)
    # A closing tag without an opening tag (the template opened it).
    match = re.search(r'</(think|thinking|reasoning)>', text, re.IGNORECASE)
    if match:
        text = text[match.end():]
    # An opening tag that was never closed (ran out of tokens while thinking).
    text = re.split(r'<(?:think|thinking|reasoning)>', text,
                    flags=re.IGNORECASE)[0]
    return text.strip()


def clean_tag_list(text: str, separator: str) -> str:
    """Normalize a model reply into one tag list.

    Commas, semicolons and newlines all separate tags (commas and semicolons
    inside a double-quoted string such as text reads "a, b" do not).
    text reads '...' is rewritten to text reads "...". Tags are stripped,
    and empty tags and duplicates are dropped, keeping the first occurrence.
    """
    text = text.strip().strip('`').strip()
    text = re.sub(r"(text reads\s*)'([^\n]*?)'(?=\s*(?:[,;\n]|$))",
                  r'\1"\2"', text, flags=re.IGNORECASE)
    parts, current, in_quotes = [], [], False
    for char in text:
        if char == '"':
            in_quotes = not in_quotes
        elif char == '\n' or (char in ',;' and not in_quotes):
            parts.append(''.join(current))
            current, in_quotes = [], False
            continue
        current.append(char)
    parts.append(''.join(current))
    tags = []
    seen = set()
    for part in parts:
        tag = part.strip().strip('-*\u2022').strip().rstrip('.').strip()
        if tag.lower().startswith('tags:'):
            tag = tag[5:].strip()
        if not tag or tag.lower() in seen:
            continue
        seen.add(tag.lower())
        tags.append(tag)
    return separator.join(tags)


def limit_tags(caption: str, separator: str, max_tags: int) -> str:
    """Keep the first `max_tags` tags (0 keeps them all)."""
    if not max_tags or max_tags <= 0:
        return caption
    tags = [tag for tag in caption.split(separator) if tag.strip()]
    return separator.join(tags[:max_tags])


def encode_image(path, max_side: int = DEFAULT_MAX_IMAGE_SIDE) -> str:
    max_side = max(MIN_IMAGE_SIDE, min(int(max_side), MAX_IMAGE_SIDE))
    pil_image = PilImage.open(path)
    pil_image = exif_transpose(pil_image)
    pil_image = pil_image.convert('RGB')
    if max(pil_image.size) > max_side:
        pil_image.thumbnail((max_side, max_side), PilImage.LANCZOS)
    buffer = io.BytesIO()
    pil_image.save(buffer, format='JPEG', quality=95)
    return base64.b64encode(buffer.getvalue()).decode('ascii')


def http_json(url: str, payload: dict | None = None,
              timeout: float = 600) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=data, headers=headers,
                                     method='POST' if data else 'GET')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        body = error.read().decode('utf-8', errors='replace')
        raise LocalServerError(f'Server returned HTTP {error.code} for {url}: '
                               f'{body[:500]}') from None


class LocalServerError(Exception):
    pass


class LocalServerBackend:
    name = ''

    def __init__(self, base_url: str, model: str = ''):
        self.base_url = base_url.strip().rstrip('/')
        # Allow users to paste the URL with `/v1` or `/api`.
        self.base_url = re.sub(r'/(v1|api)$', '', self.base_url)
        self.model = model.strip()

    def check(self, timeout: float = 5) -> str:
        """Check the server and return the model name to use."""
        raise NotImplementedError

    def caption(self, image_b64: str, user_prompt: str, system_prompt: str,
                max_tokens: int, temperature: float,
                timeout: float = 600) -> str:
        raise NotImplementedError

    def unreachable_error(self, error: Exception) -> LocalServerError:
        return LocalServerError(
            f'Could not reach the {self.name} server at {self.base_url} '
            f'({error}). Make sure {self.name} is running and its local '
            f'server is started, and that the server URL is correct.')


class LmStudioBackend(LocalServerBackend):
    name = 'LM Studio'

    def check(self, timeout: float = 5) -> str:
        if self.model:
            return self.model
        try:
            # LM Studio's REST API shows which models are currently loaded.
            try:
                response = http_json(f'{self.base_url}/api/v0/models',
                                     timeout=timeout)
                models = response.get('data', [])
                loaded = [m for m in models if m.get('state') == 'loaded']
                vision = [m for m in loaded if m.get('type') == 'vlm']
                chosen = (vision or loaded)
                if chosen:
                    self.model = chosen[0]['id']
                    return self.model
                if models:
                    raise LocalServerError(
                        'No model is loaded in LM Studio. Load a vision '
                        'model (for example Qwen3.5-9B with its mmproj) in '
                        'LM Studio, or type a model name in the "Model name" '
                        'field.')
            except LocalServerError as error:
                if 'No model is loaded' in str(error):
                    raise
            # Fall back to the OpenAI-compatible endpoint.
            response = http_json(f'{self.base_url}/v1/models',
                                 timeout=timeout)
        except (urllib.error.URLError, OSError) as error:
            raise self.unreachable_error(error) from None
        models = response.get('data', [])
        if not models:
            raise LocalServerError(
                'No model is loaded in LM Studio. Load a vision model in LM '
                'Studio, or type a model name in the "Model name" field.')
        self.model = models[0]['id']
        return self.model

    def caption(self, image_b64, user_prompt, system_prompt, max_tokens,
                temperature, timeout=600) -> str:
        messages = []
        if system_prompt.strip():
            messages.append({'role': 'system', 'content': system_prompt})
        messages.append({'role': 'user', 'content': [
            {'type': 'text', 'text': user_prompt},
            {'type': 'image_url',
             'image_url': {'url': f'data:image/jpeg;base64,{image_b64}'}}
        ]})
        payload = {'model': self.model, 'messages': messages,
                   'max_tokens': max_tokens, 'temperature': temperature,
                   'stream': False}
        try:
            response = http_json(f'{self.base_url}/v1/chat/completions',
                                 payload, timeout=timeout)
        except (urllib.error.URLError, OSError) as error:
            raise self.unreachable_error(error) from None
        if 'error' in response:
            raise LocalServerError(f'LM Studio error: {response["error"]}')
        try:
            text = response['choices'][0]['message'].get('content') or ''
        except (KeyError, IndexError):
            raise LocalServerError(
                f'Unexpected response from LM Studio: '
                f'{json.dumps(response)[:500]}') from None
        return text


class OllamaBackend(LocalServerBackend):
    name = 'Ollama'

    def check(self, timeout: float = 5) -> str:
        try:
            if self.model:
                http_json(f'{self.base_url}/api/tags', timeout=timeout)
                return self.model
            # Prefer a model that is already loaded in memory.
            running = http_json(f'{self.base_url}/api/ps',
                                timeout=timeout).get('models', [])
            if running:
                self.model = running[0].get('name') or running[0]['model']
                return self.model
            installed = http_json(f'{self.base_url}/api/tags',
                                  timeout=timeout).get('models', [])
        except (urllib.error.URLError, OSError) as error:
            raise self.unreachable_error(error) from None
        if not installed:
            raise LocalServerError(
                'Ollama has no models. Pull a vision model with '
                '`ollama pull <model>`, or type a model name in the '
                '"Model name" field.')
        self.model = installed[0].get('name') or installed[0]['model']
        return self.model

    def caption(self, image_b64, user_prompt, system_prompt, max_tokens,
                temperature, timeout=600) -> str:
        messages = []
        if system_prompt.strip():
            messages.append({'role': 'system', 'content': system_prompt})
        messages.append({'role': 'user', 'content': user_prompt,
                         'images': [image_b64]})
        payload = {'model': self.model, 'messages': messages,
                   'stream': False,
                   'options': {'temperature': temperature,
                               'num_predict': max_tokens}}
        try:
            response = http_json(f'{self.base_url}/api/chat', payload,
                                 timeout=timeout)
        except (urllib.error.URLError, OSError) as error:
            raise self.unreachable_error(error) from None
        if 'error' in response:
            raise LocalServerError(f'Ollama error: {response["error"]}')
        return response.get('message', {}).get('content') or ''


class LocalServerModel(AutoCaptioningModel):
    """Base class for models served by a local server."""
    backend_class = LocalServerBackend
    url_key = ''
    model_key = ''

    def __init__(self, captioning_thread_, caption_settings: dict):
        super().__init__(captioning_thread_, caption_settings)
        server_settings = caption_settings.get('local_server_settings', {})
        self.server_settings = server_settings
        self.backend = self.backend_class(
            server_settings.get(self.url_key, ''),
            server_settings.get(self.model_key, ''))
        self.system_prompt = server_settings.get('system_prompt', '')
        self.max_tokens = server_settings.get('max_tokens', 1024)
        self.temperature = server_settings.get('temperature', 0.7)
        self.split_tags = server_settings.get('split_tags', True)
        self.max_image_side = server_settings.get(
            'max_image_side', DEFAULT_MAX_IMAGE_SIDE)
        # 0 keeps every tag.
        self.max_tags = server_settings.get('max_tags', 0)
        # Natural-language output is kept as prose, never split into tags.
        self.is_nl_output = caption_settings.get('caption_position') in (
            'Replace natural-language caption',
            'Add to natural-language caption')

    def get_error_message(self) -> str | None:
        if not self.backend.base_url:
            return f'Enter the {self.backend.name} server URL.'
        return None

    def load_processor_and_model(self):
        self.thread.clear_console_text_edit_requested.emit()
        print(f'Connecting to {self.backend.name} at '
              f'{self.backend.base_url}...')
        model_name = self.backend.check()
        print(f'Using {self.backend.name} model: {model_name}')

    def get_captioning_message(self, are_multiple_images_selected: bool,
                               captioning_start_datetime: datetime) -> str:
        message = (f'Captioning with {self.backend.name} '
                   f'(model: {self.backend.model}')
        if are_multiple_images_selected:
            start = self.get_captioning_start_datetime_string(
                captioning_start_datetime)
            message += f', start time: {start}'
        return message + ')...'

    @staticmethod
    def get_default_prompt() -> str:
        return DEFAULT_USER_PROMPT

    def get_model_inputs(self, image_prompt: str, image: Image) -> dict:
        try:
            image_b64 = encode_image(image.path, self.max_image_side)
        except OSError as error:
            # Let the captioning thread skip unreadable images.
            from PIL import UnidentifiedImageError
            raise UnidentifiedImageError(str(error)) from None
        return {'image_b64': image_b64}

    def generate_caption(self, model_inputs: dict,
                         image_prompt: str) -> tuple[str, str]:
        user_prompt = image_prompt or DEFAULT_USER_PROMPT
        raw_text = self.backend.caption(
            model_inputs['image_b64'], user_prompt, self.system_prompt,
            self.max_tokens, self.temperature)
        text = strip_think(raw_text)
        if not text:
            print('Warning: the model returned an empty caption. If it is a '
                  'reasoning model, increase "Max tokens".')
        separator = self.thread.tag_separator
        split_tags = self.split_tags and not self.is_nl_output
        if split_tags:
            caption = clean_tag_list(text, separator)
            caption = limit_tags(caption, separator, self.max_tags)
        else:
            caption = ' '.join(text.split())
        if self.caption_start.strip() and not caption.startswith(
                self.caption_start.strip()):
            joiner = separator if split_tags else ' '
            caption = f'{self.caption_start.strip()}{joiner}{caption}'
        return caption, caption


class LmStudioModel(LocalServerModel):
    backend_class = LmStudioBackend
    url_key = 'lm_studio_url'
    model_key = 'lm_studio_model'


class OllamaModel(LocalServerModel):
    backend_class = OllamaBackend
    url_key = 'ollama_url'
    model_key = 'ollama_model'
