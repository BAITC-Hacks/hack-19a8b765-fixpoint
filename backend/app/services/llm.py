import asyncio
import json
import httpx
from pydantic import ValidationError

class ProviderError(RuntimeError):
    pass

class LLM:
    def __init__(self, settings):
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=settings.request_timeout)

    async def close(self):
        await self.client.aclose()

    async def structured(self, system, payload, schema):
        if self.settings.provider == 'mock' or not self.settings.key:
            raise ProviderError('LLM не подключена. Добавьте API-ключ в .env и перезапустите сервер.')
        messages = [{'role': 'system', 'content': system + '\nReturn ONLY a JSON object matching this schema:\n' + json.dumps(schema.model_json_schema(), ensure_ascii=False)},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
        for attempt in range(2):
            try:
                r = await self.client.post(self.settings.api_base + '/chat/completions',
                    headers={'Authorization': f'Bearer {self.settings.key}'},
                    json={'model': self.settings.model, 'messages': messages, 'temperature': 0,
                          'max_tokens': 1600, 'response_format': {'type': 'json_object'}})
                if r.status_code in (429, 502, 503) and attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                if r.is_error:
                    raise ProviderError(f'LLM: HTTP {r.status_code}. Проверьте ключ, модель и лимиты провайдера.')
                try:
                    content = r.json()['choices'][0]['message']['content']
                except (KeyError,IndexError,ValueError,TypeError) as e:
                    raise ProviderError('LLM вернула некорректный ответ API.') from e
                try:
                    return schema.model_validate_json(content)
                except (ValidationError, ValueError):
                    if attempt:
                        raise ProviderError('LLM вернула ответ, не соответствующий схеме.')
                    messages.append({'role': 'assistant', 'content': content})
                    messages.append({'role': 'user', 'content': 'Fix the JSON to strictly match the supplied schema. No extra properties.'})
            except httpx.HTTPError as e:
                raise ProviderError('Не удалось связаться с LLM. Проверьте сеть и настройки.') from e
        raise ProviderError('LLM недоступна после повторной попытки.')
