import asyncio
import base64
import binascii
import copy
import hashlib
import json
from contextlib import asynccontextmanager
from time import monotonic
from uuid import uuid4
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .core.scenarios import Catalog
from .core.context import Dialogue
from .core.contracts import TurnRequest, TurnResponse, trace_from
from .core.engine import Engine
from .core.models import TextRequest
from .core.router import Router
from .services.llm import LLM, ProviderError

catalog = Catalog(settings.data_dir)
MAX_AUDIO = 12 * 1024 * 1024
sessions = {}

@asynccontextmanager
async def lifespan(app):
    app.state.llm = LLM(settings)
    yield
    await app.state.llm.close()
    sessions.clear()

app = FastAPI(title='Saqta Voice Router', version='0.1.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins.split(','),
                   allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type'])

def decode_audio(value):
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as e:
        raise ValueError('Некорректное base64-аудио.') from e
    if len(data) > MAX_AUDIO:
        raise ValueError('Запись слишком большая: максимум 12 МБ.')
    return data

def session(session_id):
    now = monotonic()
    for key, value in list(sessions.items()):
        if now-value['at'] > 3600 and not value['lock'].locked():
            del sessions[key]
    if session_id:
        if session_id not in sessions:
            raise HTTPException(404, 'Сессия истекла. Начните новый разговор.')
        entry = sessions[session_id]
        entry['at'] = now
        return session_id, entry
    if len(sessions) >= 100:
        raise HTTPException(503, 'Слишком много активных сессий.')
    key = str(uuid4())
    entry = {'engine':Engine(catalog, app.state.llm), 'lock':asyncio.Lock(), 'at':now,
             'requests':{}, 'traces':[], 'event_id':0}
    sessions[key] = entry
    return key, entry

def wire_event(entry, kind, payload, turn_id=None):
    entry['event_id'] += 1
    return {'type':kind, 'event_id':entry['event_id'], 'turn_id':turn_id, 'payload':payload}

async def execute_turn(req, key, entry, send=None):
    async with entry['lock']:
        fingerprint = hashlib.sha256(req.model_dump_json(exclude={'session_id','request_id'}).encode()).hexdigest()
        previous = entry['requests'].get(req.request_id)
        if previous:
            if previous['fingerprint'] != fingerprint:
                raise HTTPException(409, 'request_id уже использован с другими параметрами.')
            if previous['result'] is None:
                raise HTTPException(409, 'Запрос уже обработан; полный ответ удалён из кэша. Проверьте историю.')
            if send:
                for raw, wire in previous['emitted']:
                    await send(raw, wire)
            return previous['result']
        if len(entry['requests']) >= 1000:
            raise HTTPException(409, 'Лимит ходов сессии достигнут. Начните новый разговор.')
        record = {'fingerprint':fingerprint, 'result':None, 'emitted':[]}
        entry['requests'][req.request_id] = record
        engine = entry['engine']
        turn_id = f'turn-{engine.state.turn+1}'
        events = []
        connected = True
        async def emit(raw, wire):
            nonlocal connected
            record['emitted'].append((raw, wire))
            if send and connected:
                try:
                    await send(raw, wire)
                except (WebSocketDisconnect, RuntimeError, OSError):
                    connected = False
        try:
            audio = decode_audio(req.audio_base64) if req.audio_base64 else None
            async for event in engine.run(req.text, req.language, audio, req.mime, req.speak, req.demo_scenario):
                events.append(event)
                kind = event['event']
                if kind == 'turn_complete':
                    continue
                mapping = {'assistant_response':'assistant.text', 'stt_transcript':'transcript.final',
                           'audio_chunk':'audio.segment', 'error':'error'}
                await emit(event,wire_event(entry,mapping.get(kind,'turn.status'),event,turn_id))
        except (ProviderError, ValueError) as e:
            event = {'event':'error', 'message':str(e)}
            events.append(event)
            await emit(event,wire_event(entry,'error',{'message':str(e)},turn_id))
        trace = trace_from(events,engine)
        result = TurnResponse(session_id=key,request_id=req.request_id,turn_id=turn_id,
            text=next((e['text'] for e in events if e['event']=='assistant_response'),None),
            state=copy.deepcopy(engine.state.public()),trace=trace,events=events).model_dump()
        record['result'] = result
        entry['traces'].append(trace.model_dump())
        entry['traces'] = entry['traces'][-20:]
        await emit(None,wire_event(entry,'trace.updated',trace.model_dump(),turn_id))
        complete = next((e for e in events if e['event']=='turn_complete'),None)
        await emit(complete,wire_event(entry,'turn.completed',{
            'closed':trace.status=='handoff' or any(s['scenario_id']=='SYS_GOODBYE' for s in trace.scenarios),
            'status':trace.status},turn_id))
        for old in list(entry['requests'].values())[:-20]:
            old['result'],old['emitted'] = None,[]
        entry['at'] = monotonic()
        return result

@app.get('/health')
@app.get('/api/health')
def health():
    return {'status':'ok','provider':settings.provider,
            'model':settings.model if settings.provider!='mock' else None,
            'llm_ready':settings.provider!='mock' and bool(settings.key),
            'dataset':catalog.summary(),'scenarios':len(catalog.scenarios),'as_of_date':str(catalog.as_of)}

@app.get('/api/scenarios')
def scenarios():
    return {'scenarios':list(catalog.scenarios.values()),'system_intents':list(catalog.system.values())}

@app.post('/api/sessions')
async def create_session():
    key,_ = session(None)
    return {'session_id':key}

@app.get('/api/sessions/{session_id}')
async def snapshot(session_id: str):
    _,entry = session(session_id)
    async with entry['lock']:
        return {'session_id':session_id,'state':entry['engine'].state.public(),
                'traces':entry['traces'],'request_ids':list(entry['requests'])}

@app.get('/api/sessions/{session_id}/trace')
async def traces(session_id: str):
    return (await snapshot(session_id))['traces']

@app.post('/api/route')
async def route(req: TextRequest):
    if settings.provider=='mock':
        raise HTTPException(503,'Для оценки маршрутизации нужен API-ключ.')
    try:
        return (await Router(catalog,app.state.llm).route(req.text,Dialogue(),req.language)).model_dump()
    except ProviderError as e:
        raise HTTPException(502,str(e)) from e

@app.post('/api/turn',response_model=TurnResponse)
async def turn(req: TurnRequest):
    key,entry = session(req.session_id)
    return await execute_turn(req,key,entry)

@app.delete('/api/sessions/{session_id}')
async def delete_session(session_id: str):
    entry = sessions.get(session_id)
    if entry:
        async with entry['lock']:
            sessions.pop(session_id,None)
    return {'deleted':True}

@app.websocket('/ws/voice')
@app.websocket('/api/sessions/{session_id}/stream')
async def voice(ws: WebSocket,session_id: str | None = None):
    origin = ws.headers.get('origin')
    if origin and origin not in settings.allowed_origins.split(','):
        await ws.close(code=1008)
        return
    await ws.accept()
    modern = session_id is not None
    try:
        key,entry = session(session_id)
    except HTTPException:
        await ws.close(code=1008)
        return
    async def error(message):
        raw = {'event':'error','message':message}
        await ws.send_json(wire_event(entry,'error',{'message':message}) if modern else raw)
    async def send(raw,wire):
        item = wire if modern else raw
        if item is not None:
            await ws.send_json(item)
    ready = {'session_id':key,'provider':settings.provider}
    await ws.send_json(wire_event(entry,'session.ready',ready) if modern else {'event':'session_started',**ready})
    buffer = bytearray()
    mime,language = 'audio/wav','auto'
    try:
        while True:
            message = await ws.receive()
            if message['type']=='websocket.disconnect':
                break
            if key not in sessions:
                await error('Сессия закрыта.')
                break
            entry['at'] = monotonic()
            if message.get('bytes') is not None:
                buffer.extend(message['bytes'])
                if len(buffer)>MAX_AUDIO:
                    buffer.clear()
                    await error('Запись превышает 12 МБ.')
                continue
            try:
                data = json.loads(message.get('text') or '{}')
                if not isinstance(data,dict):
                    raise ValueError('Ожидается JSON-объект.')
                event = data.get('type') if modern else data.get('event')
                payload = data.get('payload',{}) if modern else data
                if not isinstance(payload,dict):
                    raise ValueError('payload должен быть JSON-объектом.')
                if event in ('audio.start','audio_start'):
                    buffer.clear()
                    mime,language = payload.get('mime','audio/wav'),payload.get('language','auto')
                elif event in ('audio.chunk','audio_chunk'):
                    buffer.extend(decode_audio(payload.get('data','')))
                    if len(buffer)>MAX_AUDIO:
                        buffer.clear()
                        raise ValueError('Запись превышает 12 МБ.')
                elif event in ('text.submit','text_input','audio.end','speech_end'):
                    audio = bytes(buffer) if event in ('audio.end','speech_end') else None
                    buffer.clear()
                    req = TurnRequest(session_id=key,request_id=data.get('request_id') or str(uuid4()),
                        text=payload.get('text',''),language=payload.get('language',language),mime=mime,
                        audio_base64=base64.b64encode(audio).decode() if audio else None,
                        speak=payload.get('speak',False if modern else True))
                    await execute_turn(req,key,entry,send)
                elif event in ('playback.started','playback_started'):
                    ms = float(payload['ttfa_ms'])
                    if not 0<=ms<=300000:
                        raise ValueError('Некорректная задержка воспроизведения.')
                    await send({'event':'playback_metric','client_ttfa_ms':ms},wire_event(entry,'playback.metric',{'client_ttfa_ms':ms,'source':'client_reported'}))
                else:
                    raise ValueError('Неизвестное событие.')
            except HTTPException as e:
                await error(str(e.detail))
            except (ProviderError,ValueError,TypeError,KeyError) as e:
                await error(str(e))
    except WebSocketDisconnect:
        pass
