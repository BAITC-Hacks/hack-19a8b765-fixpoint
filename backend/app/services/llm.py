import asyncio
import json

from openai import AsyncOpenAI, APIError, APITimeoutError


class ProviderError(RuntimeError):
    pass


class LLM:
    def __init__(self, settings):
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.openai_api_key or 'unconfigured', timeout=settings.request_timeout)

    async def close(self):
        await self.client.close()

    async def structured(self, system, payload, schema):
        if self.settings.provider != 'openai' or not self.settings.key:
            raise ProviderError('LLM не подключена. Добавьте OPENAI_API_KEY в серверный .env и перезапустите сервер.')
        for attempt in range(2):
            try:
                response = await self.client.responses.parse(
                    model=self.settings.llm_model,
                    input=[{'role': 'system', 'content': system},
                           {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
                    text_format=schema,
                    store=False,
                )
                if response.output_parsed is None:
                    raise ProviderError('LLM не вернула структурированный ответ; действие не выполнялось.')
                return response.output_parsed
            except (APIError, APITimeoutError) as exc:
                if attempt == 0 and getattr(exc, 'status_code', None) in (429, 502, 503):
                    await asyncio.sleep(.4)
                    continue
                raise ProviderError('LLM недоступна. Проверьте серверный ключ, модель, сеть и лимиты.') from exc
        raise ProviderError('LLM недоступна после повторной попытки.')
