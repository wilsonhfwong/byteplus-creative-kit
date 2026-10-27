import io
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from byteplus_creative import settings
from byteplus_creative.cloud_cli import create_commands, status

ROOT = Path(__file__).resolve().parents[1]


def test_environment_only_status_redaction():
    with patch.dict(os.environ, {'ARK_API_KEY': 'fake-secret-value', 'ARK_AK': 'fake-ak', 'ARK_SK': 'fake-sk'}, clear=True):
        loaded = settings.load_settings()
        result = status(loaded)
        assert result['execution'] == 'cloud-command'
        assert result['generation_configured'] and result['asset_library_configured']
        assert 'fake-secret-value' not in json.dumps(result)
        assert settings.redact('fake-secret-value https://example.com/file?signature=private', loaded) == '[redacted] https://example.com/file?[redacted]'
        with pytest.raises(ValueError):
            settings.load_settings(Path('/tmp/not-used.json'))


def test_isolation_does_not_read_personal_profiles():
    from seedream.credentials import load_api_key
    from seedream.exceptions import AuthError
    with patch.dict(os.environ, {}, clear=True):
        settings.configure_environment(settings.load_settings())
        with patch('pathlib.Path.exists', side_effect=AssertionError('Read a profile')):
            with pytest.raises(AuthError):
                load_api_key()


def test_generation_routes_payload_and_parses_response(monkeypatch):
    monkeypatch.setenv('ARK_API_KEY', 'fake-test-key')
    commands = create_commands()
    from seedream import http
    captured = []
    def fake_request(url, **kwargs):
        captured.append((url, kwargs))
        return {'created': 123, 'data': [{'url': 'https://example.com/generated.png'}], 'usage': {'generated_images': 1}}
    monkeypatch.setattr(http, '_do_request', fake_request)
    result = commands.call('seedream_generate', {'prompt': 'A mountain', 'model': 'seedream-4-5-251128', 'size': '2K'})
    assert len(captured) == 1
    url, request = captured[0]
    assert url.endswith('/images/generations')
    assert request['headers']['Authorization'] == 'Bearer fake-test-key'
    assert request['payload']['prompt'] == 'A mountain'
    assert result['images'][0]['url'] == 'https://example.com/generated.png'


def test_video_submit_and_poll_are_separate_requests(monkeypatch):
    monkeypatch.setenv('ARK_API_KEY', 'fake-test-key')
    commands = create_commands()
    from seedance import http
    requests = []
    def fake_request(url, **kwargs):
        requests.append((url, kwargs))
        if kwargs['method'] == 'POST':
            return {'id': 'task-test-1', 'status': 'queued'}
        return {'id': 'task-test-1', 'status': 'succeeded', 'content': {'video_url': 'https://example.com/video.mp4'}}
    monkeypatch.setattr(http, '_do_request', fake_request)
    submitted = commands.call('seedance_text_to_video', {'prompt': 'A mountain', 'model': '2.5'})
    assert submitted['task_id'] == 'task-test-1' and submitted['status'] == 'queued'
    assert len(requests) == 1
    result = commands.call('seedance_check_task', {'task_id': submitted['task_id']})
    assert result['status'] == 'succeeded'
    assert result['video_url'] == 'https://example.com/video.mp4'
    assert len(requests) == 2 and requests[1][1]['method'] == 'GET'


def cli(tmp_path, *arguments, extras=None):
    env = {k: v for k, v in os.environ.items() if k not in settings.ENV_FIELDS}
    env.update(BYTEPLUS_CREATIVE_DATA_DIR=str(tmp_path/'data'), BYTEPLUS_CREATIVE_OUTPUT_DIR=str(tmp_path/'outputs'))
    env.update(extras or {})
    process = subprocess.run([sys.executable, '-m', 'byteplus_creative.cloud_cli', *arguments], cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    return process.returncode, json.loads(process.stdout)


def test_real_cloud_commands_discovery_and_missing_configuration(tmp_path):
    code, result = cli(tmp_path, 'list')
    assert code == 0
    names = {t['name'] for t in result['commands']}
    assert len(names) == 25
    assert {'creative_kit_status', 'seedream_generate', 'seedance_text_to_video', 'seedance_library_import', 'seed_media_download'} <= names
    assert 'creative_kit_setup' not in names
    code, result = cli(tmp_path, '--check')
    assert code == 0 and not result['generation_configured']
    arguments = tmp_path/'arguments.json'
    arguments.write_text(json.dumps({'prompt': 'A mountain'}))
    code, missing = cli(tmp_path, 'call', 'seedream_generate', '--arguments', str(arguments))
    assert code == 1 and missing['status'] == 'error' and 'ARK_API_KEY' in missing['error']
    code, missing = cli(tmp_path, 'call', 'seedance_library_list_groups')
    assert code == 1 and 'ARK_AK' in missing['error']
    assert not (tmp_path/'outputs').exists()


def test_commands_read_current_environment_and_hide_secrets(tmp_path):
    _, missing = cli(tmp_path, '--check')
    _, configured = cli(tmp_path, '--check', extras={'ARK_API_KEY': 'dummy-api-secret'})
    assert not missing['generation_configured'] and configured['generation_configured']
    assert 'dummy-api-secret' not in json.dumps(configured)


def test_input_validation_unknown_operations_and_failure_exit_codes(tmp_path):
    code, result = cli(tmp_path, 'call', 'not-a-command')
    assert code == 1 and result['status'] == 'error'
    arguments = tmp_path/'bad.json'
    arguments.write_text(json.dumps({'unexpected': 'https://example.com/file?secret=private'}))
    code, result = cli(tmp_path, 'call', 'seedream_generate', '--arguments', str(arguments))
    assert code == 1 and 'Invalid command arguments' in result['error']
    assert 'private' not in json.dumps(result)
    arguments.write_text('[1,2]')
    code, result = cli(tmp_path, 'call', 'creative_kit_status', '--arguments', str(arguments))
    assert code == 1 and 'JSON object' in result['error']
    arguments.write_text('{broken')
    code, result = cli(tmp_path, 'call', 'creative_kit_status', '--arguments', str(arguments))
    assert code == 1 and result['status'] == 'error'


def test_downloads_are_workspace_scoped_and_never_overwrite(tmp_path, monkeypatch):
    from byteplus_creative import tools
    monkeypatch.setattr(tools, 'OUTPUT_DIR', tmp_path)
    commands = create_commands()
    class Response(io.BytesIO):
        url = 'https://example.com/output.png'
    monkeypatch.setattr(tools.urllib.request, 'urlopen', lambda *a, **k: Response(b'fake-image'))
    first = commands.call('seed_media_download', {'url': 'https://example.com/output.png', 'filename': 'image.png'})
    assert (tmp_path/'image.png').read_bytes() == b'fake-image'
    assert first['local_path'] == str(tmp_path/'image.png')
    second = commands.call('seed_media_download', {'url': 'https://example.com/output.png', 'filename': 'image.png'})
    assert second['status'] == 'error' and 'already exists' in second['error']
    invalid = commands.call('seed_media_download', {'url': 'https://example.com/output.png', 'filename': '../escape.png'})
    assert invalid['status'] == 'error' and 'without directory paths' in invalid['error']
    assert not list(tmp_path.glob('.download-*'))


def test_plugin_is_skills_only():
    manifest = json.loads((ROOT/'plugin.json').read_text())
    assert manifest['version'] == '0.2.1'
    assert 'mcpServers' not in manifest
    assert manifest['extensions']['com.openai'].get('requires_local_executor') is not True
    assert not any((ROOT / name).exists() for name in ('mcp.json', '.mcp.json', '.codex-plugin/plugin.json'))
    assert len(list((ROOT/'skills').glob('*/SKILL.md'))) == 2


def test_wrapper_status_works_without_uv_or_network(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in settings.ENV_FIELDS}
    env.update(PATH="/nonexistent", HTTPS_PROXY="http://unreachable.invalid:9", HTTP_PROXY="http://unreachable.invalid:9",
        BYTEPLUS_CREATIVE_DATA_DIR=str(tmp_path/'data'), ARK_API_KEY="fake-test-secret")
    process = subprocess.run([sys.executable, str(ROOT/'scripts/run.py'), '--check'], env=env, capture_output=True, text=True, timeout=10)
    assert process.returncode == 0
    result = json.loads(process.stdout)
    assert result['generation_configured'] is True
    assert 'fake-test-secret' not in process.stdout
    assert not (tmp_path/'data').exists()


def test_bundled_runtime_restores_exact_source_without_network():
    import base64, hashlib, io, zipfile
    skill = ROOT/'skills/byteplus-creative-setup'
    manifest = json.loads((skill/'references/runtime-manifest.json').read_text())
    raw = base64.b64decode(''.join((skill/part).read_text().strip() for part in manifest['parts']), validate=True)
    assert hashlib.sha256(raw).hexdigest() == manifest['sha256']
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert 'scripts/run.py' in archive.namelist()
        for name in archive.namelist():
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
            assert archive.read(name) == (ROOT/name).read_bytes()
