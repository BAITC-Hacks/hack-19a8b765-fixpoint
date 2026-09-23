# Контракт текстового и голосового хода

Сервер: `http://127.0.0.1:8000`, интерактивная схема: `/docs`.

## HTTP

`POST /api/sessions` → `{"session_id":"..."}`.
`POST /api/turn` принимает:

```json
{"session_id":"...","request_id":"уникальный UUID","text":"Сколько стоит ОГПО в Алматы?","language":"auto","speak":false}
```

`session_id` необязателен для первого хода. Для надёжного повтора сначала создавайте сессию.
Тот же request_id с теми же параметрами возвращает сохранённый ответ без исполнения;
с другими параметрами — 409. Полные ответы последних 20 запросов сохраняются. Старые
повторные запросы отклоняются; максимум 1000 запросов на сессию.

Ответ: `session_id`, `request_id`, `turn_id`, `text`, `state`, `trace`, `events`.

- `text`: ответ робота или null при ошибке провайдера.
- `state`: история, active_scenario, active_slots, waiting_slot, pending_operation,
  slot_sources, suspended, queued, language, client_identified.
- `trace`: turn, transcript, language, response_language, confidence, confidence_source, scenarios, alternatives,
  reason, slots, actions, latency_ms, status, mode, errors.
- `events`: подробные события, включая аудио при `speak=true`; используется Streamlit.

`scenarios` — список объектов `{scenario_id, confidence, reason, slots}`. `trace.slots`
разделены по scenario_id. Actions явно различают preview, execute и error.
`reason` — краткое объяснение выбора по данным, не скрытые рассуждения модели.
`trace.confidence` — оценка первого сценария только для маршрутизации LLM (`confidence_source=llm`),
иначе `null`: подтверждения по правилу диалога и ручной демо-выбор не выдают за уверенность модели.
Пороги Case: от 0,75 запуск, от 0,45 до 0,75 уточнение, ниже 0,45 низкая уверенность.

Снимок: `GET /api/sessions/{id}`. Трассировки: `GET /api/sessions/{id}/trace`.
Сброс: `DELETE /api/sessions/{id}`. Сессии изолированы, хранятся в памяти, удаляются после
часа простоя или перезапуска. Это локальное демо без системы аккаунтов.

## WebSocket существующего frontend

Поддерживается `WS /api/sessions/{id}/stream`:

```json
{"type":"text.submit","request_id":"uuid","payload":{"text":"...","language":"ru"}}
```

События: `session.ready`, `transcript.final`, `turn.status`, `assistant.text`,
`trace.updated`, `turn.completed`, `error`. Все имеют возрастающий `event_id`, `turn_id`
и `payload`. В `trace.updated.payload` находится объект trace непосредственно.
При повторе возвращаются исходные ID событий. Принятый ход завершается и сохраняется
при разрыве соединения; состояние доступно через snapshot. Сам frontend пока не восстанавливает соединение.

Frontend отправляет текст с `speak=false`. Для голоса он отправляет
`audio.start` с `payload.mime` и `language=auto`, затем `audio.chunk`
с base64 в `payload.data`, затем `audio.end` с постоянным `request_id` и
`payload.speak=true`. Сервер принимает запись до 12 МБ. STT вызывается после
окончания записи, промежуточной потоковой транскрипции нет. Ответ содержит
`transcript.final`, `assistant.text`, `audio.segment` с base64 MP3 и `mime=audio/mpeg`,
`trace.updated` и `turn.completed`. Ошибка TTS приходит как `turn.status`
с `code=tts_unavailable`: текст и выполненные операции при этом сохраняются.
Повтор `request_id` не исполняет операцию второй раз.

## Метрики и оценка

Браузер после начала воспроизведения посылает `playback.started` с
`payload.ttfa_ms` и `turn_id`. Сервер добавляет клиентское измерение
в `trace.latency_ms.total` и посылает новый `trace.updated`.
До этого `total=null`; для текстовых ходов он остаётся неизвестным.
`server_first_audio` измеряет готовность сегмента на сервере.
Триаж отдельно не измеряется, текстовые ходы имеют `stt=null`.

`POST /api/route` выполняет только маршрутизацию независимой реплики. Без ключа — 503.
`python scripts/evaluate_router.py` генерирует predictions для всех 104 реплик и вызывает
исходный evaluate.py. Ожидаемые ответы dev-набора не попадают в промпт маршрутизатора.
