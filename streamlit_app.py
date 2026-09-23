import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))

# Streamlit Community Cloud injects secrets as environment variables for the
# existing Settings model; locally, the same value can come from .env.
try:
    if st.secrets.get('OPENAI_API_KEY'):
        os.environ['OPENAI_API_KEY'] = st.secrets['OPENAI_API_KEY']
except Exception:
    pass

from app.config import settings
from app.core.engine import Engine
from app.core.scenarios import Catalog
from app.services.llm import LLM, ProviderError

st.set_page_config(page_title='Saqta · Voice Router', page_icon='🎙️', layout='wide')
st.title('Saqta · Голосовой помощник')
st.caption('HackAlem AI · 40 страховых сценариев · Русский / Қазақша')

@st.cache_resource
def load_catalog():
    return Catalog(settings.data_dir)

try:
    catalog = load_catalog()
except Exception as exc:
    st.error(f'Не удалось загрузить набор сценариев: {exc}')
    st.stop()

for key, default in [('messages', []), ('traces', []), ('audio_hash', None), ('engine', None)]:
    if key not in st.session_state:
        st.session_state[key] = default
if st.session_state.engine is None:
    st.session_state.engine = Engine(catalog, None)

with st.sidebar:
    st.subheader('Разговор')
    language = st.selectbox('Язык', ['auto', 'ru', 'kk'], format_func=lambda v: {'auto':'Автоматически','ru':'Русский','kk':'Қазақша'}[v])
    speak = st.toggle('Озвучивать ответы', value=True)
    st.caption(f'Дата данных: {catalog.as_of}')
    st.caption('Все операции выполняются на синтетических данных. SMS и звонки не отправляются.')
    if st.button('Новый разговор', use_container_width=True):
        st.session_state.engine = Engine(catalog, None)
        st.session_state.messages = []
        st.session_state.traces = []
        st.session_state.audio_hash = None
        st.rerun()
    if st.session_state.traces:
        st.download_button('Скачать трассировки', json.dumps(st.session_state.traces, ensure_ascii=False, indent=2), 'traces.json', 'application/json')

ready = settings.provider == 'openai' and bool(settings.key)
if not ready:
    st.warning('Ключ OpenAI пока не подключён. Добавьте OPENAI_API_KEY в Secrets приложения Streamlit для обработки запросов. Пока можно проверить загрузку каталога и интерфейс.')
else:
    st.success(f'LLM, распознавание речи и озвучивание готовы · {settings.llm_model}')

left, right = st.columns([1.15, 1], gap='large')
with left:
    st.subheader('Диалог')
    for item in st.session_state.messages:
        with st.chat_message(item['role']):
            st.write(item['text'])
            if item.get('audio'):
                st.audio(item['audio'], format='audio/mpeg')
    voice = st.audio_input('Записать голосовую реплику', sample_rate=16000, disabled=not ready)
    submitted = st.chat_input('Напишите запрос или ответ на вопрос робота', max_chars=settings.max_text_chars, disabled=not ready)
    audio_data = None
    if voice is not None:
        raw = voice.getvalue()
        import hashlib
        digest = hashlib.sha256(raw).hexdigest()
        if digest != st.session_state.audio_hash:
            audio_data = raw
            st.session_state.audio_hash = digest
    if submitted or audio_data:
        engine = st.session_state.engine
        # Async clients are created and closed on the same event loop for every turn.
        llm = LLM(settings)
        engine.llm = llm
        engine.router.llm = llm
        async def process_turn():
            events = []
            try:
                async for event in engine.run(
                    text=submitted or '', language=language,
                    audio=audio_data, mime='audio/wav', speak=speak,
                ):
                    events.append(event)
            finally:
                await llm.close()
            return events
        try:
            with st.spinner('Обрабатываю реплику…'):
                events = asyncio.run(process_turn())
            transcript = next((e['text'] for e in events if e['event'] == 'stt_transcript'), submitted or '')
            answer = next((e['text'] for e in events if e['event'] == 'assistant_response'), None)
            audio = b''.join(base64.b64decode(e['audio_base64']) for e in events if e['event'] == 'audio_chunk')
            if transcript:
                st.session_state.messages.append({'role':'user', 'text':transcript})
            if answer:
                st.session_state.messages.append({'role':'assistant', 'text':answer, 'audio':audio})
            st.session_state.traces.append([{k:v for k,v in e.items() if k != 'audio_base64'} for e in events])
            st.rerun()
        except (ProviderError, ValueError, RuntimeError) as exc:
            st.error(str(exc))

with right:
    st.subheader('Трассировка супервизора')
    if not st.session_state.traces:
        st.info('После первой реплики здесь появятся выбранные сценарии, уверенность, параметры и действия.')
    else:
        index = st.selectbox('Реплика', range(len(st.session_state.traces)), index=len(st.session_state.traces)-1, format_func=lambda i:f'Реплика {i+1}')
        events = st.session_state.traces[index]
        route = next((e for e in events if e['event'] == 'routing_decision'), None)
        metrics = next((e.get('metrics', {}) for e in events if e['event'] == 'turn_complete'), {})
        if route:
            st.write(route['reason'])
            st.caption(f"Язык: {route['language']} · Ответ: {route['response_language']}")
            for scenario in route['scenarios']:
                confidence = scenario['confidence']
                st.markdown(f"**{scenario['scenario_id']}** · уверенность {confidence:.0%}")
                st.progress(confidence)
                st.caption(scenario['reason'])
            if route.get('alternatives'):
                with st.expander('Альтернативы'):
                    st.json(route['alternatives'])
        if metrics:
            a, b, c = st.columns(3)
            a.metric('Распознавание, мс', metrics.get('stt_ms') if metrics.get('stt_ms') is not None else '—')
            b.metric('Выбор сценария, мс', metrics.get('routing_ms', '—'))
            c.metric('Первое аудио, мс', metrics.get('server_first_audio_ms', '—'))
            st.caption('Streamlit показывает серверные замеры. Время начала воспроизведения в браузере отдельно не измеряется.')
        execution = next((e for e in events if e['event'] == 'execution_trace'), None)
        if execution:
            with st.expander('Параметры, действия и контекст', expanded=True):
                st.json(execution)
        with st.expander('Все события'):
            st.json(events)
