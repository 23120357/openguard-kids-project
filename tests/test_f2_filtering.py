import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from dnslib import AAAA, QTYPE, RCODE, RR, A, DNSRecord

from agent.core import AgentCore
from agent.filtering import DNSProxy, domain_decision, trusted_windows_process
from common.filter_categories import DEFAULT_ACTIONS, category_catalog, classify_domain
from server.app.event_schemas import FilterRules

from .conftest import pair


def proxy_for(**changes):
    core = Mock()
    rules = FilterRules(enabled=True, **changes).model_dump()
    core.activity_context.return_value = ("child", rules, 123)
    return DNSProxy(core), core


def test_observed_app_queue_hides_paths_and_acknowledges():
    core = AgentCore(wall_clock=lambda: 1000)
    core.record_observed_app("child", "study.exe", "A" * 64)
    assert core.pending_observed_apps() == [
        {"child_id": "child", "name": "study.exe", "sha256": "a" * 64}
    ]
    core.acknowledge_observed_apps([{"child_id": "child", "sha256": "a" * 64}])
    assert core.pending_observed_apps() == []
    core.clear_activity(["child"])
    assert core._observed_apps == {}


def test_catalog_and_category_precedence():
    catalog = category_catalog()
    assert len([host for host in catalog if not host.endswith('.test')]) >= 200
    assert set(catalog.values()) == set(DEFAULT_ACTIONS)
    rules = FilterRules(enabled=True).model_dump()
    assert classify_domain('portal.hcmus.edu.vn') == 'education'
    assert classify_domain('notfacebook.com') == 'unclassified'
    assert domain_decision('www.facebook.com', rules)
    assert domain_decision('age-restricted.example.test', rules)
    assert domain_decision('hcmus.edu.vn', rules) is None
    assert domain_decision('unknown.example.test', rules) is None
    rules['domain_allow'] = ['facebook.com']
    assert domain_decision('www.facebook.com', rules) is None
    rules['domain_block'] = ['facebook.com']
    assert domain_decision('www.facebook.com', rules)
    rules['safety_domains'] = ['facebook.com']
    assert domain_decision('www.facebook.com', rules) is None
    rules['enabled'] = False
    assert domain_decision('age-restricted.example.test', rules) is None


def test_public_50_block_and_20_education_matrix():
    with Path('tests/assets/f2_dns_cases.csv').open(encoding='utf-8') as stream:
        cases = list(csv.DictReader(stream))
    blocked = [item['domain'] for item in cases if item['expected'] == 'block']
    allowed = [item['domain'] for item in cases if item['expected'] == 'allow']
    assert len(set(blocked)) == 50 and len(set(allowed)) == 20
    rules = FilterRules(enabled=True, domain_block=blocked).model_dump()
    assert all(domain_decision(host, rules) for host in blocked)
    assert all(domain_decision('www.' + host, rules) for host in blocked)
    assert all(domain_decision(host, rules) is None for host in allowed)


@pytest.mark.parametrize('host,target', [
    ('www.google.com', 'forcesafesearch.google.com'),
    ('www.google.com.vn', 'forcesafesearch.google.com'),
    ('www.bing.com', 'strict.bing.com'),
    ('edgeservices.bing.com', 'strict.bing.com'),
])
@pytest.mark.parametrize('qtype', ['A', 'AAAA', 'CNAME', 'HTTPS'])
def test_safesearch_answers_preserve_question_and_never_query_original(monkeypatch, host, target, qtype):
    queried = []

    def send(query, *args, **kwargs):
        queried.append(str(query.q.qname).rstrip('.'))
        answer = query.reply()
        data = A('192.0.2.1') if query.q.qtype == QTYPE.A else AAAA('2001:db8::1')
        answer.add_answer(RR(query.q.qname, query.q.qtype, ttl=60, rdata=data))
        return answer.pack()

    monkeypatch.setattr(DNSRecord, 'send', send)
    proxy, core = proxy_for()
    query = DNSRecord.question(host, qtype)
    answer = proxy.resolve(query, SimpleNamespace(protocol='udp'))
    assert answer.q == query.q and answer.header.id == query.header.id
    assert answer.header.rcode == RCODE.NOERROR
    assert str(answer.rr[0].rdata).rstrip('.') == target
    assert queried == ([target] if qtype in ('A', 'AAAA') else [])
    assert core.record_activity.call_args.args[1] == 'domain_query'


def test_safesearch_block_priority_disable_and_upstream_failure(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('offline')

    monkeypatch.setattr(DNSRecord, 'send', unavailable)
    query = DNSRecord.question('www.google.com')
    handler = SimpleNamespace(protocol='udp')
    proxy, _ = proxy_for()
    assert proxy.resolve(query, handler).header.rcode == RCODE.SERVFAIL
    blocked, _ = proxy_for(domain_block=['google.com'])
    assert blocked.resolve(query, handler).header.rcode == RCODE.NXDOMAIN
    monkeypatch.setattr(DNSRecord, 'send', lambda query, *args, **kwargs: query.reply().pack())
    disabled, _ = proxy_for(safe_search=False)
    assert disabled.resolve(query, handler).rr == []
    proxy.core.activity_context.return_value[1]['enabled'] = False
    assert proxy.resolve(query, handler).rr == []


def test_windows_name_exemption_requires_real_system_location(tmp_path, monkeypatch):
    windows = tmp_path / 'Windows'
    (windows / 'System32').mkdir(parents=True)
    attacker = tmp_path / 'child'
    attacker.mkdir()
    monkeypatch.setenv('SystemRoot', str(windows))
    assert trusted_windows_process('explorer.exe', windows / 'explorer.exe')
    assert trusted_windows_process('dwm.exe', windows / 'System32' / 'dwm.exe')
    assert not trusted_windows_process('explorer.exe', attacker / 'explorer.exe')
    assert not trusted_windows_process('dwm.exe', windows / 'Temp' / 'dwm.exe')


def test_renamed_blocked_process_is_not_exempt(tmp_path, monkeypatch):
    import psutil
    import win32process
    import win32ts

    from agent.filtering import AppController

    executable = tmp_path / 'explorer.exe'
    executable.write_bytes(b'lab executable fixture')
    core = Mock()
    scanner = AppController(core)
    digest = scanner.file_hash(executable)
    rules = FilterRules(enabled=True, app_block=[{'name':'original.exe', 'sha256':digest}]).model_dump()
    core.activity_context.return_value = ('child', rules, 123)
    process = Mock()
    process.name.return_value = 'explorer.exe'
    process.exe.return_value = str(executable)
    process.create_time.return_value = 1
    monkeypatch.setattr(psutil, 'Process', lambda pid: process)
    monkeypatch.setattr(win32process, 'EnumProcesses', lambda: [54321])
    monkeypatch.setattr(win32ts, 'ProcessIdToSessionId', lambda pid: 1)
    scanner.scan()
    process.kill.assert_called_once()
    assert core.record_activity.call_args.args[1] == 'blocked_app'


def test_category_api_roundtrip_validation_and_signed_sync(parent, child):
    tokens, _ = pair(parent, child)
    url = f"/api/children/{child['id']}/filtering"
    document = parent.get(url).json()
    assert document['category_actions'] == DEFAULT_ACTIONS
    body = FilterRules(enabled=True).model_dump()
    body['category_actions']['unclassified'] = 'block'
    response = parent.put(url, json={**body, 'expected_version': document['version']})
    assert response.status_code == 200
    assert response.json()['category_actions']['unclassified'] == 'block'
    synced = parent.get('/api/device/filtering', headers={'Authorization':'Bearer '+tokens['access_token']}).json()
    assert synced['policies'][0]['category_actions'] == body['category_actions']
    assert synced['integrity']['signature']
    body['category_actions']['unsupported'] = 'allow'
    assert parent.put(url, json={**body, 'expected_version':1}).status_code == 422


def test_domain_preview_uses_agent_rules_without_saving(parent, child):
    url = f"/api/children/{child['id']}/filtering/preview"
    rules = FilterRules(enabled=True).model_dump()
    before = parent.get(f"/api/children/{child['id']}/filtering").json()
    catalog = parent.get('/api/filtering/catalog').json()
    assert len(catalog['groups']) == 6
    assert 'facebook.com' in next(g['domains'] for g in catalog['groups'] if g['key'] == 'social')
    for changes, expected in [({}, 'block'), ({'domain_allow':['facebook.com']}, 'allow'),
                              ({'domain_allow':['facebook.com'], 'domain_block':['facebook.com']}, 'block'),
                              ({'safety_domains':['facebook.com'], 'domain_block':['facebook.com']}, 'allow'),
                              ({'enabled':False}, 'allow')]:
        response = parent.post(url, json={'domain':'www.facebook.com', 'rules':{**rules, **changes}})
        assert response.status_code == 200
        assert response.json()['action'] == expected
        assert response.json()['category'] == 'social'
        assert response.json()['reason']
    assert parent.get(f"/api/children/{child['id']}/filtering").json() == before
    assert parent.post(url, json={'domain':'https://facebook.com/private', 'rules':rules}).status_code == 422
    assert parent.post('/api/children/not-owned/filtering/preview', json={'domain':'facebook.com', 'rules':rules}).status_code == 404
    parent.cookies.clear()
    assert parent.get('/api/filtering/catalog').status_code == 401


def test_custom_categories_are_scoped_normalized_and_used_by_agent(parent, child):
    from pydantic import ValidationError

    rules = FilterRules(enabled=True, category_overrides={'FACEBOOK.COM.':'education', 'custom.test':'games'}).model_dump()
    assert domain_decision('www.facebook.com', rules) is None
    assert domain_decision('custom.test', rules)
    assert classify_domain('www.facebook.com', rules['category_overrides']) == 'education'
    assert classify_domain('www.facebook.com') == 'social'
    assert classify_domain('sub.custom.test', {'custom.test':'games', 'sub.custom.test':'education'}) == 'education'
    for overrides in ({'a.test':'invalid'}, {'https://a.test/path':'games'}, {'a.test':'games','A.TEST':'education'}):
        with pytest.raises(ValidationError):
            FilterRules(category_overrides=overrides)
    url = f"/api/children/{child['id']}/filtering"
    saved = parent.put(url, json={**rules, 'expected_version':0})
    assert saved.status_code == 200
    assert parent.get(url).json()['category_overrides'] == rules['category_overrides']
    other = parent.post('/api/children', json={'display_name':'Other', 'pin':'234567'}).json()
    assert parent.get(f"/api/children/{other['id']}/filtering").json()['category_overrides'] == {}
    preview = parent.post(url + '/preview', json={'domain':'facebook.com','rules':rules}).json()
    assert preview['category'] == 'education' and preview['action'] == 'allow'
    tokens, _ = pair(parent, child)
    synced = parent.get('/api/device/filtering', headers={'Authorization':'Bearer '+tokens['access_token']}).json()
    assert next(p for p in synced['policies'] if p['child_id'] == child['id'])['category_overrides'] == rules['category_overrides']
    rules['category_overrides'] = {}
    assert parent.put(url, json={**rules,'expected_version':1}).status_code == 200
    assert domain_decision('facebook.com', parent.get(url).json())
