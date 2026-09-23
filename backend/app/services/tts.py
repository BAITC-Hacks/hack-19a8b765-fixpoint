from openai import APIError, APITimeoutError
from .llm import ProviderError


async def sentences(text, language, llm):
    settings = llm.settings
    if settings.tts_provider != 'openai' or not settings.openai_api_key:
        raise ProviderError('Озвучивание недоступно: укажите OPENAI_API_KEY в серверном .env.')
    try:
        response = await llm.client.audio.speech.create(
            model=settings.tts_model,
            voice=settings.tts_voice,
            input=text,
            instructions=('Говори естественно и ясно на казахском языке.' if language == 'kk'
                          else 'Говори естественно и ясно на русском языке.'),
            response_format='mp3',
        )
        yield response.content
    except (APIError, APITimeoutError) as exc:
        raise ProviderError('Сервис озвучивания недоступен. Проверьте сеть, ключ и лимиты.') from exc
