# FixPoint / Saqta Voice Agent

Голосовое демо вымышленной Saqta Insurance на данных `case/voice_router_dataset`.
Актуальный порядок работ — `docs/roadmap.md`, фактическое состояние — `docs/progress.md`.

## Запуск сайта

Нужны Python 3.12+ и Node.js 22.12+ с pnpm. Из корня проекта:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
```

Впишите `OPENAI_API_KEY` только в серверный `.env`. Три адаптера настраиваются
отдельно: `LLM_MODEL`, `STT_MODEL`, `TTS_MODEL`, `TTS_VOICE`. Дата Case фиксирована
как 2026-10-01. Если ключа нет, API запустится, но реальные реплики не будут
обрабатываться; для локальных тестов доступен явно обозначенный `MOCK_MODE=true`.

Терминал 1:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Терминал 2:

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Откройте http://127.0.0.1:4173. Основной экран запускает разговор одной кнопкой:
запись заканчивается после паузы, аудио идёт в FastAPI, ответ озвучивается серверным
TTS, затем микрофон включается снова. Используйте `?dev=1` для текстового ввода
и трассировки, `?jury=1` для постоянной трассировки без текстового ввода.
Распознанная реплика и текст ответа видны на основном экране.
После каждого обработанного хода там же отображается confidence первого сценария;
подробные оценки всех сценариев доступны в трассировке.
Микрофон требует localhost или HTTPS. При удалённом запуске настройте HTTPS/WSS.

## Проверки

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/validate_dataset.py
cd frontend
pnpm test
pnpm run build
```

`python scripts/evaluate_router.py` вызывает реальный OpenAI API для dev-набора
и требует ключ. Результаты пишутся в `reports/`. Данные Case не меняются;
изменения клиентов и полисов живут в памяти сессии и исчезают при перезапуске.
Реальные SMS, платежи и звонки оператору не выполняются.

HTTP и WebSocket события описаны в [контракте](docs/backend-api.md). Реальные
RU/KK/mixed голосовые прогоны и полная приёмка сценариев ещё не выполнены.
