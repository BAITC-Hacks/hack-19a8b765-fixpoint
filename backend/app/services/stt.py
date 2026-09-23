from openai import APIError, APITimeoutError
from .llm import ProviderError


async def transcribe(audio, mime, language, llm):
    settings = llm.settings
    if settings.stt_provider != 'openai' or not settings.openai_api_key:
        raise ProviderError('Распознавание недоступно: укажите OPENAI_API_KEY в серверном .env.')
    formats = {'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/webm': 'webm',
               'audio/mp4': 'mp4', 'audio/mpeg': 'mp3'}
    ext = formats.get(mime.split(';')[0])
    if not ext:
        raise ProviderError('Формат записи не поддерживается. Нужен WebM, WAV, MP3 или MP4.')
    if not audio:
        raise ProviderError('Запись пуста. Попробуйте сказать фразу ещё раз.')
    try:
        response = await llm.client.audio.transcriptions.create(
            model=settings.stt_model,
            file=(f'recording.{ext}', audio, mime),
            prompt='Страховая компания Saqta Insurance. Русская и казахская речь, ОГПО, КАСКО, ИИН.',
        )
        text = response.text.strip()
        if not text:
            raise ProviderError('Речь не обнаружена. Попробуйте ещё раз.')
        return text
    except (APIError, APITimeoutError) as exc:
        raise ProviderError('Сервис распознавания недоступен. Проверьте сеть, ключ и лимиты.') from exc
