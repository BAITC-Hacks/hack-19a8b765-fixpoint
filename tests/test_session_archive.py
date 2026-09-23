import base64
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from app.main import app, settings, sessions
from app.services.session_archive import SessionArchive


def request(sid, number=1):
    return {'session_id':sid, 'request_id':f'request-{number}', 'text':f'Проверка {number}',
            'demo_scenario':'SC33', 'speak':False}


def test_completed_dialogue_survives_close_and_restart(monkeypatch):
    monkeypatch.setattr(settings, 'mock_mode', True)
    with TestClient(app) as client:
        sid = client.post('/api/sessions').json()['session_id']
        result = client.post('/api/turn', json=request(sid)).json()
        assert client.post(f'/api/sessions/{sid}/close').json()['archived']
        assert sid not in sessions
        assert client.post('/api/turn', json=request(sid)).status_code == 409
    with TestClient(app) as client:
        saved = client.get(f'/api/sessions/{sid}').json()
        assert saved['status'] == 'closed'
        assert saved['turns'][0]['text'] == result['text']
        assert saved['traces'][0] == result['trace']
        assert saved['state']['active_scenario'] == 'SC33'
        assert saved['mock_backend']['clients']
        listing = client.get('/api/sessions').json()
        assert listing['total'] == 1
        assert listing['sessions'][0]['turn_count'] == 1
        exported = client.get(f'/api/sessions/{sid}/export')
        assert exported.json() == saved
        assert f'saqta-session-{sid}.json' in exported.headers['content-disposition']
        assert client.post(f'/api/sessions/{sid}/close').status_code == 200


def test_archive_keeps_more_than_twenty_turns_and_retry_is_not_duplicated(monkeypatch):
    monkeypatch.setattr(settings, 'mock_mode', True)
    with TestClient(app) as client:
        sid = client.post('/api/sessions').json()['session_id']
        for number in range(23):
            response = client.post('/api/turn', json=request(sid, number))
            assert response.status_code == 200
        last = response.json()
        assert client.post('/api/turn', json=request(sid, 22)).json() == last
        assert client.post('/api/turn', json=request(sid, 0)).status_code == 409
        client.post(f'/api/sessions/{sid}/close')
        saved = client.get(f'/api/sessions/{sid}').json()
        assert len(saved['turns']) == len(saved['traces']) == 23
        assert saved['turns'][0]['input']['text'] == 'Проверка 0'
        assert len({turn['request_id'] for turn in saved['turns']}) == 23


def test_open_session_after_restart_is_read_only(monkeypatch):
    monkeypatch.setattr(settings, 'mock_mode', True)
    with TestClient(app) as client:
        sid = client.post('/api/sessions').json()['session_id']
        client.post('/api/turn', json=request(sid))
    with TestClient(app) as client:
        assert client.get(f'/api/sessions/{sid}').json()['status'] == 'interrupted'
        assert client.post('/api/turn', json=request(sid, 2)).status_code == 409
        assert len(client.get(f'/api/sessions/{sid}/trace').json()) == 1


def test_audio_archive_saves_playback_metric_without_audio_or_key(monkeypatch):
    monkeypatch.setattr(settings, 'mock_mode', True)
    monkeypatch.setattr(settings, 'openai_api_key', 'secret-that-must-not-be-saved')
    async def transcribe(*args):
        return 'Где офис?'
    async def sentences(*args):
        yield b'distinctive-synthesized-audio'
    monkeypatch.setattr('app.core.engine.transcribe', transcribe)
    monkeypatch.setattr('app.core.engine.sentences', sentences)
    with TestClient(app) as client:
        sid = client.post('/api/sessions').json()['session_id']
        with client.websocket_connect(f'/api/sessions/{sid}/stream') as ws:
            ws.receive_json()
            ws.send_json({'type':'audio.start', 'payload':{'mime':'audio/webm'}})
            ws.send_json({'type':'audio.chunk', 'payload':{'data':base64.b64encode(b'distinctive-input-audio').decode()}})
            ws.send_json({'type':'audio.end', 'request_id':'audio-1', 'payload':{'speak':True}})
            while True:
                event = ws.receive_json()
                if event['type'] == 'turn.completed':
                    break
            ws.send_json({'type':'playback.started', 'payload':{'turn_id':'turn-1', 'ttfa_ms':2345}})
            assert ws.receive_json()['payload']['latency_ms']['total'] == 2345
            assert ws.receive_json()['type'] == 'playback.metric'
        client.post(f'/api/sessions/{sid}/close')
    with TestClient(app) as client:
        saved = client.get(f'/api/sessions/{sid}').json()
        assert saved['traces'][0]['latency_ms']['total'] == 2345
        assert saved['turns'][0]['input']['source'] == 'audio'
        assert saved['turns'][0]['trace']['transcript'] == 'Где офис?'
        text = (settings.session_archive_dir / f'{sid}.json').read_text(encoding='utf-8')
        assert 'audio_base64' not in text and 'secret-that-must-not-be-saved' not in text
        assert base64.b64encode(b'distinctive-input-audio').decode() not in text
        assert base64.b64encode(b'distinctive-synthesized-audio').decode() not in text


def test_provider_failure_and_tts_warning_are_archived(monkeypatch):
    from app.services.llm import ProviderError
    monkeypatch.setattr(settings, 'mock_mode', True)
    async def fail_tts(*args):
        raise ProviderError('TTS failure')
        yield b''
    monkeypatch.setattr('app.core.engine.sentences', fail_tts)
    with TestClient(app) as client:
        sid = client.post('/api/sessions').json()['session_id']
        client.post('/api/turn', json={**request(sid), 'speak':True})
        saved = client.get(f'/api/sessions/{sid}').json()
        assert saved['turns'][0]['text']
        assert any(event.get('code') == 'tts_unavailable' for event in saved['turns'][0]['events'])
        client.post('/api/turn', json={**request(sid, 2), 'audio_base64':'###'})
        saved = client.get(f'/api/sessions/{sid}').json()
        assert saved['turns'][-1]['trace']['errors']
        assert [turn['trace']['turn'] for turn in saved['turns']] == [1, 2]


def test_storage_failure_before_turn_blocks_actions(monkeypatch):
    monkeypatch.setattr(settings, 'mock_mode', True)
    with TestClient(app) as client:
        sid = client.post('/api/sessions').json()['session_id']
        original = app.state.archive.save
        def fail(*args):
            raise OSError('disk unavailable')
        monkeypatch.setattr(app.state.archive, 'save', fail)
        assert client.post('/api/turn', json=request(sid)).status_code == 503
        assert sessions[sid]['engine'].state.turn == 0
        assert sessions[sid]['engine'].backend.audit == []
        monkeypatch.setattr(app.state.archive, 'save', original)
        assert client.post('/api/turn', json=request(sid)).status_code == 200


def test_atomic_write_preserves_previous_archive_and_rejects_paths(tmp_path, monkeypatch):
    import app.services.session_archive as module
    store = SessionArchive(tmp_path)
    sid = str(uuid4())
    document = {'schema_version':1, 'session_id':sid, 'status':'active', 'turns':[]}
    store.save(document)
    def fail(*args):
        raise OSError('replace unavailable')
    monkeypatch.setattr(module.os, 'replace', fail)
    with pytest.raises(OSError):
        store.save({**document, 'status':'closed'})
    assert store.read(sid)['status'] == 'active'
    assert not list(tmp_path.glob('*.tmp'))
    for bad in ('../other', '..\\other', '/absolute', 'x', ''):
        with pytest.raises(ValueError):
            store.path(bad)


def test_storage_failure_after_write_keeps_result_and_does_not_repeat_action(monkeypatch):
    from app.core.models import Answer, Candidate, RoutingDecision
    from app.services.llm import LLM
    monkeypatch.setattr(settings, 'mock_mode', False)
    monkeypatch.setattr(settings, 'openai_api_key', 'test-only')
    async def structured(self, prompt, payload, schema):
        if schema is Answer:
            return Answer(text='Результат демонстрационной операции.')
        return RoutingDecision(scenarios=[Candidate(scenario_id='SC29', confidence=.95, reason='change',
            slots={'phone':'+77010000001','contact_field':'address','new_value':'Archive test address'})],
            language='ru', response_language='ru', reason='change')
    monkeypatch.setattr(LLM, 'structured', structured)
    with TestClient(app) as client:
        sid = client.post('/api/sessions').json()['session_id']
        preview = client.post('/api/turn', json={'session_id':sid, 'request_id':'prepare',
                                                 'text':'Изменить адрес, телефон +77010000001'}).json()
        assert preview['trace']['status'] == 'confirmation'
        original = app.state.archive.save
        def fail_final(document):
            if len(document['turns']) == 2:
                raise OSError('disk became full after execute')
            original(document)
        monkeypatch.setattr(app.state.archive, 'save', fail_final)
        confirm = {'session_id':sid, 'request_id':'confirm', 'text':'да'}
        result = client.post('/api/turn', json=confirm).json()
        assert result['trace']['status'] == 'completed' and result['trace']['errors']
        assert client.post('/api/turn', json=confirm).json() == result
        assert sum(a['action'] == 'update_contact' for a in sessions[sid]['engine'].backend.audit) == 1
        monkeypatch.setattr(app.state.archive, 'save', original)
        client.post(f'/api/sessions/{sid}/close')
        saved = client.get(f'/api/sessions/{sid}').json()
        assert saved['mock_backend']['clients'][0]['address'] == 'Archive test address'
        assert len(saved['turns']) == 2


def test_startup_marks_crash_receipt_interrupted_and_skips_broken_json(monkeypatch):
    monkeypatch.setattr(settings, 'mock_mode', True)
    store = SessionArchive(settings.session_archive_dir)
    sid = str(uuid4())
    store.save({'schema_version':1, 'session_id':sid, 'status':'active', 'created_at':'2026-09-23T00:00:00Z',
                'turns':[], 'in_progress':{'request_id':'accepted-before-crash'}})
    (settings.session_archive_dir / f'{uuid4()}.json').write_text('{broken', encoding='utf-8')
    with TestClient(app) as client:
        saved = client.get(f'/api/sessions/{sid}').json()
        assert saved['status'] == 'interrupted'
        assert saved['in_progress']['request_id'] == 'accepted-before-crash'
        assert client.get('/api/sessions').json()['total'] == 1
        assert client.get('/api/sessions/not-a-uuid').status_code == 404


def test_listing_pagination(monkeypatch):
    monkeypatch.setattr(settings, 'mock_mode', True)
    with TestClient(app) as client:
        ids = [client.post('/api/sessions').json()['session_id'] for _ in range(3)]
        first = client.get('/api/sessions?limit=2').json()
        second = client.get('/api/sessions?limit=2&offset=2').json()
        assert first['total'] == second['total'] == 3
        assert {row['session_id'] for row in first['sessions'] + second['sessions']} == set(ids)
        assert client.get('/api/sessions?limit=100000').status_code == 422
