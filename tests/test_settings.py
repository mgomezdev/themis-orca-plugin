import json

import pytest

from themis_orca.settings import Settings, api_base_url


@pytest.mark.parametrize(("url", "expected"), [
    ("http://themis.local:8000", "http://themis.local:8000/api/v1"),
    ("https://example.test/themis/", "https://example.test/themis/api/v1"),
    ("https://example.test/api/v1/", "https://example.test/api/v1"),
    ("http://[::1]:8000", "http://[::1]:8000/api/v1"),
])
def test_deployment_urls(url, expected):
    assert api_base_url(url) == expected


@pytest.mark.parametrize("url", [
    "", "file:///etc/passwd", "https://user:secret@example.test", "https://example.test?api_key=secret",
    "https://example.test/#token", "https://example.test:bad", "https://example.test\n",
    "https://example.test\\other", "https://example.test:0", "https:///missing", None,
])
def test_invalid_urls_do_not_echo_input(url):
    with pytest.raises(ValueError) as exc:
        api_base_url(url)
    assert "secret" not in str(exc.value)


def test_settings_keep_key_out_of_repr():
    settings = Settings.from_json('{"url":"https://themis.test","api_key":"private-key"}')
    assert settings.api_key == "private-key"
    assert "private-key" not in repr(settings)


@pytest.mark.parametrize("raw", ["[]", "null", "invalid", '{}', '{"api_key":12}', '{"api_key":"a\\nb"}'])
def test_invalid_config(raw):
    with pytest.raises(ValueError):
        Settings.from_json(raw)


def test_missing_url():
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        Settings.from_json(json.dumps({"api_key": "key"}))
