# Контракт текстового хода

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
повторные запросы отклоняются; максимум ходов задаётся через `MAX_SESSION_TURNS`.
Текст ограничен `MAX_TEXT_CHARS` (по умолчанию 4000 символов).

Ответ: `session_id`, `request_id`, `turn_id`, `text`, `state`, `trace`, `events`.

- `text`: ответ робота или null при ошибке провайдера.
- `state`: история, active_scenario, active_slots, waiting_slot, pending_operation,
  slot_sources, suspended, queued, language, client_identified.
- `trace`: turn, turn_id, transcript, input_source, language, response_language,
  scenarios, alternatives, reason, slots, actions, latency_ms, playback, status, mode,
  warnings and errors.
- `events`: подробные события, включая аудио при `speak=true`; используется Streamlit.

`scenarios` — список объектов `{scenario_id, confidence, reason, slots}`. `trace.slots`
разделены по scenario_id. Actions явно различают preview, execute и error.
`reason` — краткое объяснение выбора по данным, не скрытые рассуждения модели.

Снимок: `GET /api/sessions/{id}`. Трассировки: `GET /api/sessions/{id}/trace`.
Поле `state.closed` обозначает завершение после прощания или успешного мок-перевода.
Новый ход закрытой сессии получает 409; повтор прежнего request_id возвращает сохранённый
ответ. Для продолжения создайте новую сессию.
Сброс: `DELETE /api/sessions/{id}`. Сессии изолированы, хранятся в памяти, удаляются после
30 минут бездействия (настраивается через `SESSION_TTL_SECONDS`) или перезапуска.
Это локальное демо без системы аккаунтов.

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

Для текстового пути `speak=false` по умолчанию. Streamlit может получать MP3 в events.
Голосовой протокол: `audio.start` с MIME → binary или `audio.chunk` → `audio.end`.
STT вызывается после окончания записи, промежуточной потоковой транскрипции нет.
Лимит записи — 12 МБ (`MAX_AUDIO_BYTES`), длительность — 60 секунд
(`MAX_RECORDING_SECONDS`). Длительность WAV проверяется по заголовку;
для остальных форматов клиент передаёт `duration_ms` в `audio.end`. При повреждённом
или слишком большом чанке текущая запись
сбрасывается и не отправляется в STT как частичное аудио. Для следующей записи отправьте
новое `audio.start`.
Один `audio.segment` — полный MP3 одного предложения. Первоначальный `/ws/voice`
принимает поле `event`: `audio_start`, `audio_chunk`, `speech_end`, `text_input`.

## Метрики и оценка

`latency_ms.total=null`, пока клиент не пришлёт `playback.started` с `turn_id` и
фактическим `ttfa_ms`. После этого замер сохраняется в трассировке. `server_first_audio`
измеряет готовность первого сегмента на сервере. Триаж включён в маршрутизатор; отдельно
не измеряется. Текстовые ходы имеют `stt=null`.

`POST /api/route` выполняет только маршрутизацию независимой реплики. Без ключа — 503.
`python scripts/evaluate_router.py` генерирует predictions для всех 104 реплик и вызывает
исходный evaluate.py. `python scripts/evaluate_dialogues.py` прогоняет 10 многошаговых
примеров через настоящий движок и локальные мок-действия. Ожидаемые ответы dev-набора
не попадают в промпт маршрутизатора.
