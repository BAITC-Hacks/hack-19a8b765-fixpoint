"""Smoke-check synthetic RU/KK spoken identifiers with the configured STT.

Generated speech is not a substitute for a real microphone recording.
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.config import settings
from app.services.llm import LLM
from app.services.stt import transcribe
from app.core.identifiers import extract_iins


PHRASES = [
    ('ru', 'Девяносто один ноль пять двенадцать, тридцать ноль четыре пятьдесят шесть.'),
    ('ru', 'Мой ИИН: девять один ноль пять один два три ноль ноль четыре пять шесть.'),
    ('ru', 'ИИН: девяносто один, ноль пять, двенадцать, триста, четыреста пятьдесят шесть.'),
    ('kk', 'Менің ЖСН: тоғыз бір нөл бес бір екі үш нөл нөл төрт бес алты.'),
]


async def main():
    if not settings.key:
        raise SystemExit('OPENAI_API_KEY is required')
    llm = LLM(settings)
    try:
        for language, phrase in PHRASES:
            speech = await llm.client.audio.speech.create(
                model=settings.tts_model, voice=settings.tts_voice, input=phrase,
                instructions='Произнеси точно написанные слова и цифры, в естественном темпе.',
                response_format='mp3',
            )
            transcript = await transcribe(speech.content, 'audio/mpeg', language, llm)
            print(f'{language} input: {phrase}')
            print(f'{language} STT:   {transcript}')
            print(f'{language} IIN:   {extract_iins(transcript)}')
    finally:
        await llm.close()


if __name__ == '__main__':
    asyncio.run(main())
