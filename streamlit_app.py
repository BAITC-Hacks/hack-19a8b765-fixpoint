import base64
import hashlib
import json
import os
from uuid import uuid4
import httpx
import streamlit as st

API = os.getenv('VOICE_ROUTER_API', 'http://127.0.0.1:8000')
st.set_page_config(page_title='Saqta · Voice Router', page_icon='🎙️', layout='wide')
st.title('Saqta · Голосовой помощник')
st.caption('HackAlem AI · 40 страховых сценариев · Русский / Қазақша')

def api(method, path, **kwargs):
    response = httpx.request(method, API + path, timeout=180, **kwargs)
    response.raise_for_status()
    return response.json()

for key, default in [('session_id',None),('messages',[]),('traces',[]),('audio_hash',None),('recorder',0)]:
    if key not in st.session_state:
        st.session_state[key] = default

try:
    health = api('GET','/health')
except (httpx.HTTPError, ValueError):
    st.error('Сервер недоступен. Запустите проект командой python run.py из корня проекта.')
    st.stop()

with st.sidebar:
    st.subheader('Разговор')
    language = st.selectbox('Язык', ['auto','ru','kk'], format_func=lambda v:{'auto':'Автоматически','ru':'Русский','kk':'Қазақша'}[v])
    speak = st.toggle('Озвучивать ответы', value=True)
    st.caption(f"Дата данных: {health['as_of_date']}")
    st.caption('Все операции выполняются в синтетических данных. SMS и звонки не отправляются.')
    if st.button('Новый разговор', use_container_width=True):
        if st.session_state.session_id:
            try:
                api('DELETE', '/api/sessions/' + st.session_state.session_id)
            except httpx.HTTPError:
                pass
        st.session_state.update(session_id=None, messages=[], traces=[], audio_hash=None, recorder=st.session_state.recorder+1)
        st.rerun()
    if st.session_state.traces:
        st.download_button('Скачать трассировку', json.dumps(st.session_state.traces,ensure_ascii=False,indent=2),
                           'trace.json','application/json')

if not health['llm_ready']:
    st.warning('Демонстрационный режим: ключ Groq ещё не подключён. LLM и распознавание речи недоступны. Ручной выбор ниже проверяет интерфейс и исполнителя.')
else:
    st.success(f"Подключение настроено: {health['provider']} · {health['model']}. Доступность API проверяется при запросе.")

left, right = st.columns([1.15, 1], gap='large')
with left:
    st.subheader('Диалог')
    for item in st.session_state.messages:
        with st.chat_message(item['role']):
            st.write(item['text'])
            if item.get('audio'):
                st.audio(item['audio'], format='audio/mpeg')
    voice = st.audio_input('Записать голосовую реплику', sample_rate=16000,
                          key=f"voice_{st.session_state.recorder}", disabled=not health['llm_ready'])
    submitted = st.chat_input('Напишите запрос или ответ на вопрос робота', max_chars=5000)
    demo = None
    if not health['llm_ready']:
        with st.expander('Ручная демонстрация сценария'):
            catalog = api('GET','/api/scenarios')['scenarios']
            options = {s['scenario_id']:f"{s['scenario_id']} · {s['name']}" for s in catalog}
            selection = st.selectbox('Сценарий', list(options), format_func=options.get)
            if st.button('Показать первый шаг'):
                demo = selection

    audio_data = None
    if voice is not None:
        digest = hashlib.sha256(voice.getvalue()).hexdigest()
        if digest != st.session_state.audio_hash:
            audio_data = base64.b64encode(voice.getvalue()).decode()
            st.session_state.audio_hash = digest
    if submitted or audio_data or demo:
        payload = {'session_id':st.session_state.session_id,'text':submitted or ('Ручной запуск ' + demo if demo else ''),
                   'language':language,'audio_base64':audio_data,'mime':'audio/wav','speak':speak,
                   'demo_scenario':demo,'request_id':str(uuid4())}
        try:
            with st.spinner('Обрабатываю реплику…'):
                result = api('POST','/api/turn',json=payload)
            st.session_state.session_id = result['session_id']
            events = result['events']
            transcript = next((e['text'] for e in events if e['event']=='stt_transcript'), submitted or '')
            answer = next((e['text'] for e in events if e['event']=='assistant_response'), None)
            audio = b''.join(base64.b64decode(e['audio_base64']) for e in events if e['event']=='audio_chunk')
            if transcript:
                st.session_state.messages.append({'role':'user','text':transcript})
                with st.chat_message('user'):
                    st.write(transcript)
            if answer:
                st.session_state.messages.append({'role':'assistant','text':answer,'audio':audio})
                with st.chat_message('assistant'):
                    st.write(answer)
                    if audio:
                        st.audio(audio,format='audio/mpeg',autoplay=True)
            for e in events:
                if e['event'] == 'error':
                    st.error(e['message'])
                elif e['event'] == 'warning':
                    st.warning(e['message'])
            st.session_state.traces.append([{k:v for k,v in e.items() if k!='audio_base64'} for e in events])
        except (httpx.HTTPError, ValueError):
            st.error('Не удалось получить ответ сервера. Не повторяйте подтверждение вслепую; проверьте состояние разговора или начните новый.')

with right:
    st.subheader('Трассировка супервизора')
    if not st.session_state.traces:
        st.info('После первой реплики здесь появятся сценарии, параметры и действия.')
    else:
        index = st.selectbox('Реплика', range(len(st.session_state.traces)), index=len(st.session_state.traces)-1,
                             format_func=lambda i:f'Реплика {i+1}')
        events = st.session_state.traces[index]
        route = next((e for e in events if e['event']=='routing_decision'), None)
        metrics = next((e['metrics'] for e in events if e['event']=='turn_complete'), {})
        if route:
            st.write(route['reason'])
            st.caption(f"Язык: {route['language']} · Ответ: {route['response_language']} · {'Смена темы' if route['is_topic_switch'] else 'Текущий контекст'}")
            for s in route['scenarios']:
                st.markdown(f"**{s['scenario_id']}** · оценка уверенности {s['confidence']:.0%}")
                st.progress(s['confidence'])
                st.caption(s['reason'])
            if route['alternatives']:
                with st.expander('Альтернативы'):
                    st.json(route['alternatives'])
        if metrics:
            a,b,c = st.columns(3)
            a.metric('STT, мс', metrics.get('stt_ms') if metrics.get('stt_ms') is not None else '—')
            b.metric('Выбор, мс', metrics.get('routing_ms','—'))
            c.metric('Первое аудио на сервере',metrics.get('server_first_audio_ms','—'))
            st.caption('Streamlit получает готовый ответ. Время старта звука в браузере здесь не измеряется; это не итоговый TTFA для жюри.')
        execution = next((e for e in events if e['event']=='execution_trace'), None)
        if execution:
            st.write('Состояние:', execution['execution']['status'])
            with st.expander('Параметры, действия и контекст', expanded=True):
                st.json(execution)
        with st.expander('Все события'):
            st.json(events)
