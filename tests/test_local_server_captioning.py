"""End-to-end captioning against fake LM Studio and Ollama servers."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PIL import Image as PilImage

from auto_captioning.captioning_thread import CaptioningThread
from auto_captioning.models_list import LM_STUDIO_MODEL_ID, OLLAMA_MODEL_ID
from models.image_list_model import ImageListModel

REPLY = '<think>hmm</think>cat, solo, sitting, blue eyes, collar'


class FakeServer(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/api/v0/models':
            self.send_json({'data': [{'id': 'qwen-vl', 'state': 'loaded',
                                      'type': 'vlm'}]})
        elif self.path == '/api/ps':
            self.send_json({'models': [{'name': 'llava'}]})
        elif self.path == '/api/tags':
            self.send_json({'models': [{'name': 'llava'}]})
        else:
            self.send_json({'data': [{'id': 'qwen-vl'}]})

    def do_POST(self):
        payload = json.loads(self.rfile.read(
            int(self.headers['Content-Length'])))
        FakeServer.requests.append((self.path, payload))
        text = REPLY if 'tag' in json.dumps(payload['messages'][-1]).lower() \
            else 'A cat sits calmly.'
        if self.path == '/v1/chat/completions':
            self.send_json({'choices': [{'message': {'content': text}}]})
        else:
            self.send_json({'message': {'content': text}})


@pytest.fixture
def server():
    FakeServer.requests = []
    httpd = HTTPServer(('127.0.0.1', 0), FakeServer)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{httpd.server_port}'
    httpd.shutdown()


@pytest.fixture
def model(qapp, tmp_path):
    folder = tmp_path / 'ds'
    folder.mkdir()
    PilImage.new('RGB', (1600, 1200), 'orange').save(folder / 'a.png')
    (folder / 'a.txt').write_text('cat', encoding='utf-8')
    model = ImageListModel(64, ', ')
    model.dataset_state_dir = tmp_path / 'state'
    model.load_directory(folder)
    return model


def settings(model_id, url, position, prompt='List the tags.', max_tags=0):
    return {
        'model_id': model_id, 'prompt': prompt, 'caption_start': '',
        'caption_position': position, 'device': 'CPU', 'gpu_index': 0,
        'load_in_4_bit': False, 'remove_tag_separators': True,
        'bad_words': '', 'forced_words': '',
        'generation_parameters': {
            'min_new_tokens': 1, 'max_new_tokens': 100, 'num_beams': 1,
            'length_penalty': 1, 'do_sample': False, 'temperature': 1,
            'top_k': 50, 'top_p': 1, 'repetition_penalty': 1,
            'no_repeat_ngram_size': 3},
        'local_server_settings': {
            'lm_studio_url': url, 'lm_studio_model': '',
            'ollama_url': url, 'ollama_model': '',
            'system_prompt': 'You tag images.', 'max_tokens': 4096,
            'temperature': 0.7, 'split_tags': True, 'max_tags': max_tags,
            'max_image_side': 720},
    }


def run(model, caption_settings):
    thread = CaptioningThread(None, model, [model.index(0)],
                              caption_settings, ', ', None)
    results, nl_results = [], []
    thread.caption_generated.connect(
        lambda index, caption, tags: results.append((caption, tags)))
    thread.nl_caption_generated.connect(
        lambda index, caption, append: nl_results.append((caption, append)))
    thread.run_captioning()
    return results, nl_results


@pytest.mark.parametrize('model_id,path', [
    (LM_STUDIO_MODEL_ID, '/v1/chat/completions'),
    (OLLAMA_MODEL_ID, '/api/chat')])
def test_tag_captioning(server, model, model_id, path):
    results, nl_results = run(model, settings(
        model_id, server, 'Insert after last tag', max_tags=3))
    assert results == [('cat, solo, sitting',
                        ['cat', 'cat', 'solo', 'sitting'])]
    assert nl_results == []
    request_path, payload = FakeServer.requests[-1]
    assert request_path == path
    assert payload['messages'][0]['content'] == 'You tag images.'


def test_image_is_resized_to_max_side(server, model):
    import base64
    import io
    run(model, settings(LM_STUDIO_MODEL_ID, server, 'Insert after last tag'))
    content = FakeServer.requests[-1][1]['messages'][-1]['content']
    data = content[1]['image_url']['url'].split(',', 1)[1]
    image = PilImage.open(io.BytesIO(base64.b64decode(data)))
    assert max(image.size) == 720


def test_tag2caption_goes_to_natural_language(server, model):
    from auto_captioning.prompt_presets import get_preset
    preset = get_preset('Tag2Caption (caption from existing tags)')
    caption_settings = settings(OLLAMA_MODEL_ID, server,
                                preset.caption_position,
                                prompt='Write prose about {tags}.')
    results, nl_results = run(model, caption_settings)
    assert nl_results == [('A cat sits calmly.', False)]
    # Tags are untouched.
    assert results[0][1] == ['cat']
    sent = FakeServer.requests[-1][1]['messages'][-1]['content']
    assert sent == 'Write prose about cat.'
