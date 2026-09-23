import asyncio
import json
import httpx
from fastapi.testclient import TestClient
from app.main import app, settings
from app.config import Settings
from app.services.llm import LLM, ProviderError
from app.core.context import Dialogue
from app.core.router import Router
from app.core.models import RoutingDecision

def test_mock_api_session_and_voice_error(monkeypatch):
    monkeypatch.setattr(settings,'mock_mode',True)
    with TestClient(app) as client:
        assert client.get('/health').json()['scenarios']==40
        sid=client.post('/api/sessions').json()['session_id']
        payload={'session_id':sid,'request_id':'r1','text':'test','speak':False,'demo_scenario':'SC33'}
        first=client.post('/api/turn',json=payload).json()
        second=client.post('/api/turn',json=payload).json()
        assert first==second
        assert first['text']=='В каком вы городе?'
        assert first['state']['active_scenario']=='SC33'
        assert first['trace']['scenarios'][0]['scenario_id']=='SC33'
        assert first['trace']['latency_ms']['total'] is None
        assert client.post('/api/turn',json={**payload,'text':'changed'}).status_code==409
        assert any(e.get('text')=='В каком вы городе?' for e in first['events'])
        assert client.post('/api/route',json={'text':'test'}).status_code==503
        assert client.post('/api/turn',json={'session_id':sid,'audio_base64':'###','speak':False}).json()['events'][0]['event']=='error'
        assert client.get('/api/sessions/'+sid).json()['state']['active_scenario']=='SC33'
        assert client.delete('/api/sessions/'+sid).status_code==200
        assert client.get('/api/sessions/'+sid).status_code==404

def test_websocket_protocol(monkeypatch):
    monkeypatch.setattr(settings,'mock_mode',True)
    with TestClient(app) as client, client.websocket_connect('/ws/voice') as ws:
        assert ws.receive_json()['event']=='session_started'
        ws.send_json({'event':'text_input','text':'hello','speak':False})
        events=[]
        while not events or events[-1]['event']!='turn_complete':
            events.append(ws.receive_json())
        assert [e['event'] for e in events]==['stt_transcript','routing_decision','assistant_response','execution_trace','turn_complete']
        assert events[-1]['metrics']['stt_ms'] is None

def test_websocket_discards_oversized_audio_before_stt(monkeypatch):
    import app.main as main
    from app.core.models import Candidate
    monkeypatch.setattr(settings,'mock_mode',True)
    monkeypatch.setattr(main,'MAX_AUDIO',4)
    received=[]
    async def fake_run(self,text='',language='auto',audio=None,mime='audio/wav',speak=True,demo_scenario=None):
        received.append(audio)
        yield {'event':'stt_transcript','turn':1,'text':text}
        yield {'event':'routing_decision','turn':1,'scenarios':[Candidate(scenario_id='SYS_UNCLEAR',confidence=.5,reason='test').model_dump()],
               'alternatives':[],'reason':'test','language':'ru','response_language':'ru'}
        yield {'event':'assistant_response','turn':1,'text':'ok'}
        yield {'event':'execution_trace','turn':1,'execution':{'status':'system','actions':[]}}
        yield {'event':'turn_complete','turn':1,'metrics':{}}
    monkeypatch.setattr(main.Engine,'run',fake_run)
    with TestClient(app) as client, client.websocket_connect('/ws/voice') as ws:
        assert ws.receive_json()['event']=='session_started'
        ws.send_json({'event':'audio_start','mime':'audio/wav'})
        ws.send_bytes(b'1234')
        ws.send_bytes(b'56')
        assert ws.receive_json()['event']=='error'
        ws.send_json({'event':'speech_end'})
        ws.send_json({'event':'audio_start','mime':'audio/wav'})
        ws.send_bytes(b'ab')
        ws.send_json({'event':'speech_end'})
        while ws.receive_json()['event']!='turn_complete':
            pass
    assert received==[b'ab']

def test_real_adapter_with_fake_http_validates_json_and_urgent_order(catalog):
    async def run():
        config=Settings(_env_file=None,groq_api_key='test-not-a-real-key',llm_provider='groq')
        llm=LLM(config)
        await llm.client.aclose()
        count=0
        async def handler(req):
            nonlocal count
            count+=1
            body=json.loads(req.content)
            assert body['response_format']['type']=='json_object'
            assert 'SC40' in body['messages'][1]['content']
            content='{}' if count==1 else json.dumps({'scenarios':[{'scenario_id':'SC33','confidence':.8,'reason':'office'}, {'scenario_id':'SC11','confidence':.9,'reason':'urgent'}],
                'language':'mixed','response_language':'kk','reason':'two intents'})
            return httpx.Response(200,json={'choices':[{'message':{'content':content}}]})
        llm.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        d=await Router(catalog,llm).route('test',Dialogue())
        assert [s.scenario_id for s in d.scenarios]==['SC11','SC33'] and count==2
        await llm.close()
    asyncio.run(run())

def test_frontend_websocket_contract_and_replay(monkeypatch):
    monkeypatch.setattr(settings,'mock_mode',True)
    with TestClient(app) as client:
        sid=client.post('/api/sessions').json()['session_id']
        with client.websocket_connect(f'/api/sessions/{sid}/stream',headers={'origin':'http://127.0.0.1:4173'}) as ws:
            assert ws.receive_json()['type']=='session.ready'
            request={'type':'text.submit','request_id':'unique','payload':{'text':'hello','language':'ru'}}
            ws.send_json(request)
            events=[]
            while not events or events[-1]['type']!='turn.completed':
                events.append(ws.receive_json())
            assert any(e['type']=='assistant.text' and e['payload']['text'] for e in events)
            trace=next(e['payload'] for e in events if e['type']=='trace.updated')
            assert trace['transcript']=='hello' and trace['mode']=='mock'
            assert len({e['event_id'] for e in events})==len(events)
            ws.send_json(request)
            assert [ws.receive_json() for _ in events]==events
        assert len(client.get(f'/api/sessions/{sid}/trace').json())==1

def test_full_http_turn_with_injected_llm(monkeypatch):
    from app.core.models import Candidate,Answer
    monkeypatch.setattr(settings,'mock_mode',False)
    monkeypatch.setattr(settings,'groq_api_key','test-local-only')
    monkeypatch.setattr(settings,'llm_provider','groq')
    async def structured(self,prompt,payload,schema):
        if schema is Answer:
            return Answer(text='Расчёт по тестовым данным выполнен.')
        return RoutingDecision(scenarios=[Candidate(scenario_id='SC01',confidence=.92,reason='quote',
            slots={'region':'almaty','vehicle_type':'car','drivers_iin':['000000000000']})],language='ru',response_language='ru',reason='quote')
    monkeypatch.setattr(LLM,'structured',structured)
    with TestClient(app) as client:
        response=client.post('/api/turn',json={'text':'Сколько стоит ОГПО?','request_id':'quote'}).json()
        assert response['text']=='Расчёт по тестовым данным выполнен.'
        assert response['trace']['status']=='completed'
        assert next(a for a in response['trace']['actions'] if a['name']=='calc_ogpo_price')['result']['price']==38000
        assert response['trace']['mode']=='groq'

def test_llm_failure_has_no_action_or_claimed_success(monkeypatch):
    monkeypatch.setattr(settings,'mock_mode',False)
    monkeypatch.setattr(settings,'groq_api_key','test-local-only')
    monkeypatch.setattr(settings,'llm_provider','groq')
    async def fail_provider(*args,**kwargs):
        raise ProviderError('Provider unavailable')
    monkeypatch.setattr(LLM,'structured',fail_provider)
    with TestClient(app) as client:
        response=client.post('/api/turn',json={'text':'Отмените мой полис'}).json()
        assert response['text'] is None
        assert response['trace']['status']=='error'
        assert response['trace']['actions']==[] and response['trace']['errors']

def test_unknown_model_scenario_is_rejected(catalog):
    class Fake:
        settings=type('Config',(),{'provider':'groq'})()
        async def structured(self,*args):
            return RoutingDecision(scenarios=[{'scenario_id':'SC99','confidence':1,'reason':'invented'}],language='ru',response_language='ru',reason='test')
    import pytest
    with pytest.raises(ProviderError):
        asyncio.run(Router(catalog,Fake()).route('test',Dialogue()))

def test_closed_session_replays_but_rejects_new_turn(monkeypatch):
    monkeypatch.setattr(settings,'mock_mode',True)
    with TestClient(app) as client:
        sid=client.post('/api/sessions').json()['session_id']
        payload={'session_id':sid,'request_id':'handoff','demo_scenario':'SC37','speak':False}
        result=client.post('/api/turn',json=payload).json()
        assert result['state']['closed'] and result['trace']['status']=='handoff'
        assert client.post('/api/turn',json=payload).json()==result
        assert client.post('/api/turn',json={**payload,'request_id':'new'}).status_code==409

def test_server_voice_pipeline_with_injected_providers(monkeypatch):
    import app.core.engine as engine
    from app.core.models import Candidate,Answer
    monkeypatch.setattr(settings,'mock_mode',False)
    monkeypatch.setattr(settings,'llm_provider','openai')
    monkeypatch.setattr(settings,'openai_api_key','local-test-only')
    calls=[]
    async def stt(audio,mime,language,llm):
        calls.append((audio,mime,language))
        return 'Алматыдағы кеңсе қайда?'
    async def tts(text,language):
        assert language=='kk'
        yield b'synthetic-audio-for-transport-test'
    async def structured(self,prompt,payload,schema):
        if schema is Answer:
            return Answer(text='Кеңсе туралы ақпарат.')
        return RoutingDecision(scenarios=[Candidate(scenario_id='SC33',confidence=.95,reason='office',slots={'city':'Almaty'})],
            language='kk',response_language='kk',reason='office')
    monkeypatch.setattr(engine,'transcribe',stt)
    monkeypatch.setattr(engine,'sentences',tts)
    monkeypatch.setattr(settings,'tts_provider','edge')
    monkeypatch.setattr(LLM,'structured',structured)
    with TestClient(app) as client:
        sid=client.post('/api/sessions').json()['session_id']
        with client.websocket_connect(f'/api/sessions/{sid}/stream') as ws:
            ws.receive_json()
            ws.send_json({'type':'audio.start','payload':{'mime':'audio/webm','language':'kk'}})
            ws.send_bytes(b'recorded-test-input')
            ws.send_json({'type':'audio.end','request_id':'voice','payload':{'speak':True}})
            events=[]
            while not events or events[-1]['type']!='turn.completed':
                events.append(ws.receive_json())
            trace=next(e['payload'] for e in events if e['type']=='trace.updated')
            assert trace['response_language']=='kk' and trace['status']=='completed'
            assert trace['latency_ms']['stt'] is not None
            assert trace['latency_ms']['server_first_audio'] is not None
            assert trace['latency_ms']['total'] is None
            assert any(e['type']=='audio.segment' for e in events)
    assert calls==[(b'recorded-test-input','audio/webm','kk')]
