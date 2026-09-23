import asyncio
import base64
import binascii
import copy
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from time import monotonic
from uuid import uuid4
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .core.scenarios import Catalog
from .core.context import Dialogue
from .core.contracts import TurnRequest, TurnResponse, trace_from
from .core.engine import Engine
from .core.models import TextRequest
from .core.router import Router
from .services.llm import LLM, ProviderError
from .services.session_archive import SessionArchive, archive_value, archive_snapshot, timestamp

catalog = Catalog(settings.data_dir)
MAX_AUDIO = 12 * 1024 * 1024
sessions = {}
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app):
    app.state.archive = SessionArchive(settings.session_archive_dir)
    app.state.archive.interrupt_open_sessions()
    app.state.llm = LLM(settings)
    try:
        yield
    finally:
        for entry in list(sessions.values()):
            async with entry['lock']:
                if entry['archive']['status'] == 'active':
                    entry['archive'].update(status='interrupted', closed_at=timestamp(), close_reason='server_shutdown')
                try:
                    persist(entry)
                except HTTPException:
                    logger.error('Could not save session on shutdown: %s', entry['archive']['session_id'])
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

def persist(entry):
    engine = entry['engine']
    document = entry['archive']
    document['state'] = copy.deepcopy(engine.state.public())
    document['mock_backend'] = copy.deepcopy(engine.backend.data)
    document['action_audit'] = copy.deepcopy(engine.backend.audit)
    document['request_ids'] = list(entry['requests'])
    try:
        app.state.archive.save(document)
    except (OSError, ValueError):
        logger.exception('Session archive write failed: %s', document['session_id'])
        raise HTTPException(503, 'Не удалось сохранить разговор на диск. Проверьте доступ и свободное место; не повторяйте операцию вслепую.')

def saved_session(session_id):
    try:
        document = app.state.archive.read(session_id)
    except ValueError:
        raise HTTPException(404, 'Архив сессии не найден или повреждён.')
    except OSError:
        raise HTTPException(503, 'Не удалось прочитать архив сессии.')
    if document is None:
        raise HTTPException(404, 'Сессия не найдена.')
    return document

def session(session_id):
    now = monotonic()
    for key, value in list(sessions.items()):
        if now-value['at'] > 3600 and not value['lock'].locked():
            if value['archive']['status'] == 'active':
                value['archive'].update(status='closed', closed_at=timestamp(), close_reason='idle_timeout')
            persist(value)
            del sessions[key]
    if session_id:
        if session_id not in sessions:
            saved_session(session_id)
            raise HTTPException(409, 'Разговор завершён. Архив доступен для просмотра; начните новую сессию.')
        entry = sessions[session_id]
        if entry.get('closing') or entry['archive']['status'] != 'active':
            raise HTTPException(409, 'Разговор завершён. Начните новую сессию.')
        entry['at'] = now
        return session_id, entry
    if len(sessions) >= 100:
        raise HTTPException(503, 'Слишком много активных сессий.')
    key = str(uuid4())
    entry = {'engine':Engine(catalog, app.state.llm), 'lock':asyncio.Lock(), 'at':now,
             'requests':{}, 'traces':[], 'event_id':0, 'closing':False,
             'archive':{'schema_version':1, 'session_id':key, 'created_at':timestamp(),
                        'status':'active', 'closed_at':None, 'close_reason':None,
                        'as_of_date':str(catalog.as_of), 'provider':settings.provider,
                        'model':settings.model if settings.provider != 'mock' else None,
                        'turns':[], 'in_progress':None}}
    persist(entry)
    sessions[key] = entry
    return key, entry

def wire_event(entry, kind, payload, turn_id=None):
    entry['event_id'] += 1
    return {'type':kind, 'event_id':entry['event_id'], 'turn_id':turn_id, 'payload':payload}

async def execute_turn(req, key, entry, send=None):
    async with entry['lock']:
        if entry.get('closing') or entry['archive']['status'] != 'active':
            raise HTTPException(409, 'Разговор завершён; действие не выполнялось.')
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
        input_record = {'source':'audio' if req.audio_base64 else 'text', 'text':req.text,
                        'language':req.language, 'mime':req.mime if req.audio_base64 else None,
                        'speak':req.speak, 'capture':req.capture.model_dump() if req.capture else None}
        entry['archive']['in_progress'] = {'request_id':req.request_id, 'turn_id':turn_id,
                                           'started_at':timestamp(), 'input':input_record}
        try:
            persist(entry)  # Check persistence before allowing any business action.
        except HTTPException:
            entry['requests'].pop(req.request_id)
            entry['archive']['in_progress'] = None
            raise
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
        except Exception:
            logger.exception('Unexpected turn failure: %s / %s', key, turn_id)
            event = {'event':'error', 'message':'Внутренняя ошибка обработки. Проверьте результат в архиве; не повторяйте операцию вслепую.'}
            events.append(event)
            await emit(event,wire_event(entry,'error',{'message':event['message']},turn_id))
        # Rejected audio can fail before Engine increments the dialogue counter.
        engine.state.turn = max(engine.state.turn, int(turn_id.removeprefix('turn-')))
        trace = trace_from(events,engine)
        trace.capture = req.capture if req.audio_base64 else None
        result = TurnResponse(session_id=key,request_id=req.request_id,turn_id=turn_id,
            text=next((e['text'] for e in events if e['event']=='assistant_response'),None),
            state=copy.deepcopy(engine.state.public()),trace=trace,events=events).model_dump()
        record['result'] = result
        entry['traces'].append(trace.model_dump())
        entry['traces'] = entry['traces'][-20:]
        saved_turn = archive_value({**result, 'input':input_record,
                                   'started_at':entry['archive']['in_progress']['started_at'],
                                   'completed_at':timestamp()})
        entry['archive']['turns'].append(saved_turn)
        entry['archive']['in_progress'] = None
        closed = trace.status=='handoff' or any(s['scenario_id']=='SYS_GOODBYE' for s in trace.scenarios)
        if closed:
            entry['archive'].update(status='closed', closed_at=timestamp(),
                                    close_reason='handoff' if trace.status=='handoff' else 'goodbye')
        try:
            persist(entry)
        except HTTPException as exc:
            # The operation may already be committed. Keep the cached result and
            # expose the storage failure without encouraging another execution.
            message = str(exc.detail)
            trace.errors.append(message)
            result['trace']['errors'].append(message)
            saved_turn['trace']['errors'].append(message)
            entry['traces'][-1]['errors'].append(message)
            await emit({'event':'error','message':message}, wire_event(entry,'error',{'message':message},turn_id))
        await emit(None,wire_event(entry,'trace.updated',trace.model_dump(),turn_id))
        complete = next((e for e in events if e['event']=='turn_complete'),None)
        await emit(complete,wire_event(entry,'turn.completed',{
            'closed':closed,
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
            'stt_ready':settings.stt_provider=='openai' and bool(settings.key),
            'tts_ready':settings.tts_provider=='openai' and bool(settings.key),
            'dataset':catalog.summary(),'scenarios':len(catalog.scenarios),'as_of_date':str(catalog.as_of)}

@app.get('/api/scenarios')
def scenarios():
    return {'scenarios':list(catalog.scenarios.values()),'system_intents':list(catalog.system.values())}

@app.post('/api/sessions')
async def create_session():
    key,_ = session(None)
    return {'session_id':key}

@app.get('/api/sessions')
async def list_sessions(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return app.state.archive.listing(limit, offset)

@app.get('/api/sessions/{session_id}')
async def snapshot(session_id: str):
    entry = sessions.get(session_id)
    if not entry:
        return archive_snapshot(saved_session(session_id))
    async with entry['lock']:
        return archive_snapshot(copy.deepcopy(entry['archive']))

@app.get('/api/sessions/{session_id}/trace')
async def traces(session_id: str):
    return (await snapshot(session_id))['traces']

@app.get('/api/sessions/{session_id}/export')
async def export_session(session_id: str):
    document = await snapshot(session_id)
    return JSONResponse(archive_value(document), headers={
        'Content-Disposition':f'attachment; filename="saqta-session-{document["session_id"]}.json"'})

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

@app.post('/api/sessions/{session_id}/close')
async def close_session(session_id: str):
    entry = sessions.get(session_id)
    if entry:
        entry['closing'] = True
        async with entry['lock']:
            if entry['archive']['status'] == 'active':
                entry['archive'].update(status='closed', closed_at=timestamp(), close_reason='user')
            persist(entry)
            sessions.pop(session_id,None)
    else:
        saved_session(session_id)
    return {'session_id':session_id, 'archived':True}

@app.delete('/api/sessions/{session_id}')
async def delete_session(session_id: str):
    # Compatibility with older clients: finish the live session, retain history.
    await close_session(session_id)
    return {'deleted':True, 'archived':True}

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
                        speak=payload.get('speak',False if modern else True),
                        capture=payload.get('capture') if audio else None)
                    await execute_turn(req,key,entry,send)
                elif event in ('playback.started','playback_started'):
                    ms = float(payload['ttfa_ms'])
                    if not 0<=ms<=300000:
                        raise ValueError('Некорректная задержка воспроизведения.')
                    turn_id = payload.get('turn_id')
                    if modern and turn_id:
                        async with entry['lock']:
                            saved = next((turn for turn in entry['archive']['turns'] if turn['turn_id'] == turn_id), None)
                            if saved and saved['input']['source'] == 'audio':
                                saved['trace']['latency_ms']['total'] = ms
                                for trace_item in entry['traces']:
                                    if trace_item['turn'] == saved['trace']['turn']:
                                        trace_item['latency_ms']['total'] = ms
                                cached = entry['requests'].get(saved['request_id'], {}).get('result')
                                if cached:
                                    cached['trace']['latency_ms']['total'] = ms
                                persist(entry)
                                await send(None, wire_event(entry,'trace.updated',saved['trace'],turn_id))
                    await send({'event':'playback_metric','client_ttfa_ms':ms},wire_event(entry,'playback.metric',{'client_ttfa_ms':ms,'source':'client_reported'}))
                else:
                    raise ValueError('Неизвестное событие.')
            except HTTPException as e:
                await error(str(e.detail))
            except (ProviderError,ValueError,TypeError,KeyError) as e:
                await error(str(e))
    except WebSocketDisconnect:
        pass
