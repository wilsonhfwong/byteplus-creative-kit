import asyncio
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from byteplus_creative import settings
from byteplus_creative.cloud_server import create_server, status

ROOT = Path(__file__).resolve().parents[1]


def test_environment_only_and_status_redaction():
    with patch.dict(os.environ, {'ARK_API_KEY': 'fake-secret-value', 'ARK_AK': 'fake-ak', 'ARK_SK': 'fake-sk'}, clear=True):
        loaded = settings.load_settings()
        result = status(loaded)
        assert result['generation_configured'] and result['asset_library_configured']
        assert 'fake-secret-value' not in json.dumps(result)
        assert settings.redact('fake-secret-value https://example.com/file?signature=private', loaded) == '[redacted] https://example.com/file?[redacted]'
        with pytest.raises(ValueError):
            settings.load_settings(Path('/tmp/not-used.json'))


def test_isolation_does_not_read_personal_profiles(tmp_path):
    from seedream.credentials import load_api_key
    from seedream.exceptions import AuthError
    with patch.dict(os.environ, {}, clear=True):
        settings.configure_environment(settings.load_settings())
        with patch('pathlib.Path.exists', side_effect=AssertionError('Read a profile')):
            with pytest.raises(AuthError):
                load_api_key()


@pytest.mark.asyncio
async def test_generation_routes_payload_and_parses_response(monkeypatch):
    monkeypatch.setenv('ARK_API_KEY', 'fake-test-key')
    server = create_server()
    from seedream import http
    captured = []
    def fake_request(url, **kwargs):
        captured.append((url, kwargs))
        return {'created': 123, 'data': [{'url': 'https://example.com/generated.png'}], 'usage': {'generated_images': 1}}
    monkeypatch.setattr(http, '_do_request', fake_request)
    result = await server.call_tool('seedream_generate', {'prompt': 'A mountain', 'model': 'seedream-4-5-251128', 'size': '2K'})
    assert len(captured) == 1
    url, request = captured[0]
    assert url.endswith('/images/generations')
    assert request['headers']['Authorization'] == 'Bearer fake-test-key'
    assert request['payload']['prompt'] == 'A mountain'
    assert 'https://example.com/generated.png' in str(result)


@pytest.mark.asyncio
async def test_real_stdio_discovery_and_missing_config(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in settings.ENV_FIELDS}
    env.update(BYTEPLUS_CREATIVE_DATA_DIR=str(tmp_path/'data'), BYTEPLUS_CREATIVE_OUTPUT_DIR=str(tmp_path/'outputs'))
    params = StdioServerParameters(command=sys.executable, args=['-m', 'byteplus_creative.cloud_server'], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            names = {t.name for t in (await client.list_tools()).tools}
            assert {'creative_kit_status', 'seedream_generate', 'seedance_text_to_video', 'seedance_library_import', 'seed_media_download'} <= names
            assert 'creative_kit_setup' not in names
            result = await client.call_tool('creative_kit_status', {})
            text = ''.join(c.text for c in result.content if c.type == 'text')
            assert json.loads(text)['generation_configured'] is False
            missing = await client.call_tool('seedream_generate', {'prompt': 'A mountain'})
            assert 'ARK_API_KEY' in str(missing)
            missing_asset = await client.call_tool('seedance_library_list_groups', {})
            assert 'ARK_AK' in str(missing_asset)
    assert not (tmp_path/'outputs').exists()


@pytest.mark.asyncio
async def test_download_is_workspace_scoped_and_never_overwrites(tmp_path, monkeypatch):
    from byteplus_creative import tools
    monkeypatch.setattr(tools, 'OUTPUT_DIR', tmp_path)
    server = create_server()
    class Response(io.BytesIO):
        url = 'https://example.com/output.png'
    monkeypatch.setattr(tools.urllib.request, 'urlopen', lambda *a, **k: Response(b'fake-image'))
    first = await server.call_tool('seed_media_download', {'url': 'https://example.com/output.png', 'filename': 'image.png'})
    assert (tmp_path/'image.png').read_bytes() == b'fake-image'
    assert str(tmp_path/'image.png') in str(first)
    second = await server.call_tool('seed_media_download', {'url': 'https://example.com/output.png', 'filename': 'image.png'})
    assert 'already exists' in str(second)
    invalid = await server.call_tool('seed_media_download', {'url': 'https://example.com/output.png', 'filename': '../escape.png'})
    assert 'without directory paths' in str(invalid)
    assert not list(tmp_path.glob('.download-*'))
