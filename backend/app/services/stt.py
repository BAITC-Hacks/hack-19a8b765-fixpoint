from .llm import ProviderError

async def transcribe(audio, mime, language, llm):
    if llm.settings.provider == 'mock' or not llm.settings.key:
        raise ProviderError('Для распознавания речи добавьте API-ключ выбранного провайдера в .env. Пока доступны текстовый ввод и ручная демонстрация.')
    formats = {'audio/wav':'wav','audio/x-wav':'wav','audio/webm':'webm','audio/ogg':'ogg','audio/mp4':'m4a','audio/mpeg':'mp3'}
    ext = formats.get(mime.split(';')[0])
    if not ext:
        raise ProviderError('Поддерживаются WAV, WebM, OGG, MP3 и M4A. Для PCM сначала создайте WAV-контейнер.')
    data = {'model': 'whisper-large-v3-turbo' if llm.settings.provider == 'groq' else 'whisper-1', 'response_format':'json'}
    if language in ('ru','kk'):
        data['language'] = language
    try:
        r = await llm.client.post(llm.settings.api_base + '/audio/transcriptions',
            headers={'Authorization':f'Bearer {llm.settings.key}'}, data=data,
            files={'file': (f'recording.{ext}', audio, mime)})
        if r.is_error:
            raise ProviderError(f'Распознавание речи: HTTP {r.status_code}. Проверьте ключ и лимиты.')
        text = r.json().get('text','').strip()
        if not text:
            raise ProviderError('Речь не обнаружена. Попробуйте записать фразу ещё раз.')
        return text
    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError('Сервис распознавания речи недоступен.') from e
