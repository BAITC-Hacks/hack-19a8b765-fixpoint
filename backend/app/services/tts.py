import asyncio
import re

async def sentences(text, language):
    """Yield complete MP3 sentence segments, safe to decode independently in Web Audio."""
    import edge_tts
    voice = 'kk-KZ-AigulNeural' if language == 'kk' else 'ru-RU-SvetlanaNeural'
    for sentence in re.split(r'(?<=[.!?])\s+', text.strip()):
        if not sentence:
            continue
        parts = []
        async with asyncio.timeout(20):
            async for item in edge_tts.Communicate(sentence, voice).stream():
                if item['type'] == 'audio':
                    parts.append(item['data'])
        if not parts:
            raise RuntimeError('TTS did not return audio')
        yield b''.join(parts)
