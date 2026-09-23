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
    if len(data) > settings.max_audio_bytes:
        raise ValueError(f'Запись слишком большая: максимум {settings.max_audio_bytes // (1024 * 1024)} МБ.')
    return data

def session(session_id):
    now = monotonic()
    for key, value in list(sessions.items()):
        if now-value['at'] > settings.session_ttl_seconds and not value['lock'].locked():
            del sessions[key]
    if session_id:
        if session_id not in sessions:
            raise HTTPException(404, 'Сессия истекла. Начните новый разговор.')
        entry = sessions[session_id]
        entry['at'] = now
        return session_id, entry
    if len(sessions) >= settings.max_sessions:
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
        if entry['engine'].state.closed:
            raise HTTPException(409, 'Разговор завершён. Начните новую сессию.')
        if entry['engine'].state.turn >= settings.max_session_turns:
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
            duration_ms = req.audio_duration_ms
            is_wav = req.mime.split(';')[0] in ('audio/wav', 'audio/x-wav')
            if audio and is_wav:
                import io
                import wave
                try:
                    with wave.open(io.BytesIO(audio), 'rb') as wav:
                        duration_ms = wav.getnframes() * 1000 / wav.getframerate()
                except (wave.Error, EOFError, ZeroDivisionError) as exc:
                    raise ValueError('Некорректный WAV файл.') from exc
            if audio and not is_wav and duration_ms is None:
                raise ValueError('Для аудио не в WAV передайте duration_ms.')
            if duration_ms is not None and duration_ms > settings.max_recording_seconds * 1000:
                raise ValueError(f'Запись длиннее {settings.max_recording_seconds:g} секунд.')
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
        trace.turn_id = turn_id
        result = TurnResponse(session_id=key,request_id=req.request_id,turn_id=turn_id,
            text=next((e['text'] for e in events if e['event']=='assistant_response'),None),
            state=copy.deepcopy(engine.state.public()),trace=trace,events=events).model_dump()
        record['result'] = result
        entry['traces'].append(trace.model_dump())
        entry['traces'] = entry['traces'][-20:]
        await emit(None,wire_event(entry,'trace.updated',trace.model_dump(),turn_id))
        complete = next((e for e in events if e['event']=='turn_complete'),None)
        await emit(complete,wire_event(entry,'turn.completed',{
            'closed':engine.state.closed,
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
    audio_invalid = False
    mime,language = 'audio/wav','auto'
    audio_started_at = None
    try:
        while True:
            message = await ws.receive()
            if message['type']=='websocket.disconnect':
                break
            if key not in sessions:
                await error('Сессия закрыта.')
                break
            entry['at'] = monotonic()
            if len((message.get('text') or '').encode('utf-8')) > settings.max_ws_message_bytes:
                await error('Сообщение превышает допустимый размер.')
                continue
            if message.get('bytes') is not None:
                if audio_invalid:
                    continue
                buffer.extend(message['bytes'])
                if len(buffer)>settings.max_audio_bytes:
                    buffer.clear()
                    audio_invalid = True
                    await error(f"Запись превышает {settings.max_audio_bytes // (1024 * 1024)} МБ.")
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
                    audio_invalid = False
                    mime,language = payload.get('mime','audio/wav'),payload.get('language','auto')
                    audio_started_at = monotonic()
                elif event in ('audio.chunk','audio_chunk'):
                    if audio_invalid:
                        continue
                    try:
                        chunk = decode_audio(payload.get('data',''))
                    except ValueError:
                        buffer.clear()
                        audio_invalid = True
                        raise
                    buffer.extend(chunk)
                    if len(buffer)>settings.max_audio_bytes:
                        buffer.clear()
                        audio_invalid = True
                        raise ValueError(f"Запись превышает {settings.max_audio_bytes // (1024 * 1024)} МБ.")
                elif event in ('text.submit','text_input','audio.end','speech_end'):
                    if event in ('audio.end','speech_end') and audio_invalid:
                        buffer.clear()
                        audio_invalid = False
                        continue
                    audio = bytes(buffer) if event in ('audio.end','speech_end') else None
                    buffer.clear()
                    duration_ms = payload.get('duration_ms')
                    if audio and duration_ms is None and audio_started_at is not None:
                        duration_ms = (monotonic() - audio_started_at) * 1000
                    if event in ('audio.end','speech_end'):
                        audio_started_at = None
                    req = TurnRequest(session_id=key,request_id=data.get('request_id') or str(uuid4()),
                        text=payload.get('text',''),language=payload.get('language',language),mime=mime,
                        audio_base64=base64.b64encode(audio).decode() if audio else None,
                        audio_duration_ms=duration_ms,
                        speak=payload.get('speak',False if modern else True))
                    await execute_turn(req,key,entry,send)
                elif event in ('playback.started','playback_started'):
                    ms = float(payload['ttfa_ms'])
                    if not 0<=ms<=300000:
                        raise ValueError('Некорректная задержка воспроизведения.')
                    turn_id = payload.get('turn_id') or data.get('turn_id')
                    trace = next((item for item in entry['traces'] if item.get('turn_id') == turn_id), None)
                    if trace is not None:
                        trace.setdefault('playback', {}).update({'started':True, 'ttfa_ms':round(ms,1)})
                        trace.setdefault('latency_ms', {})['total'] = round(ms,1)
                        for record in entry['requests'].values():
                            result = record.get('result')
                            if result and result.get('turn_id') == turn_id:
                                result['trace'] = copy.deepcopy(trace)
                            for raw, wire in record.get('emitted', []):
                                if wire and wire.get('type') == 'trace.updated' and wire.get('turn_id') == turn_id:
                                    wire['payload'] = copy.deepcopy(trace)
                    elif turn_id:
                        raise ValueError('Ход для метрики воспроизведения не найден.')
                    await send({'event':'playback_metric','client_ttfa_ms':ms},wire_event(entry,'playback.metric',{'client_ttfa_ms':ms,'source':'client_reported'}))
                else:
                    raise ValueError('Неизвестное событие.')
            except HTTPException as e:
                await error(str(e.detail))
            except (ProviderError,ValueError,TypeError,KeyError) as e:
                await error(str(e))
    except WebSocketDisconnect:
        pass
