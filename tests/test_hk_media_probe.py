import json

import pytest
import requests

from scripts.probe_hk_media import main, probe_options


def test_proxy_requires_explicit_existing_https_endpoint(monkeypatch, capsys):
    monkeypatch.delenv('DSA_NEWS_PROBE_PROXY', raising=False)
    with pytest.raises(SystemExit):
        probe_options(['--proxy-env', 'DSA_NEWS_PROBE_PROXY'])
    monkeypatch.setenv('DSA_NEWS_PROBE_PROXY', 'http://user:private-value@proxy.example:443')
    with pytest.raises(SystemExit):
        probe_options(['--proxy-env', 'DSA_NEWS_PROBE_PROXY'])
    assert 'private-value' not in capsys.readouterr().err


def test_proxy_failures_do_not_leak_credentials_or_silently_fallback(monkeypatch, tmp_path, capsys):
    endpoint = 'https://probe-user:private-value@proxy.example:443'
    monkeypatch.setenv('DSA_NEWS_PROBE_PROXY', endpoint)
    monkeypatch.chdir(tmp_path)
    calls = []

    def failed_get(url, **kwargs):
        calls.append(kwargs)
        raise requests.exceptions.ProxyError('Failed to connect '+endpoint)

    monkeypatch.setattr('scripts.probe_hk_media.requests.get', failed_get)
    main(['--proxy-env', 'DSA_NEWS_PROBE_PROXY', '--network-label', 'candidate'])
    output = capsys.readouterr().out
    rows = json.loads((tmp_path/'probe/media/results.json').read_text())
    assert len(calls) == len(rows) == 6
    assert all(call['proxies'] == {'https':endpoint} for call in calls)
    assert all(call.get('verify', True) for call in calls)
    assert all(row['error_type'] == 'ProxyError' and row['total_ms'] >= 0 for row in rows)
    assert all(not row['egress_location_verified'] for row in rows)
    assert 'private-value' not in output
    assert 'private-value' not in json.dumps(rows)
