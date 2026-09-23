"""Probe configured TTS -> STT -> conservative identifier extraction.

Synthetic speech checks the provider path, not a person's microphone.
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.config import settings
from app.core.identifiers import (extract_claim_numbers, extract_phones,
                                  extract_iins, extract_plates, extract_policy_numbers)
from app.services.llm import LLM
from app.services.stt import transcribe


CASES = [
    ('ru', 'Плюс семь, семьсот один, ноль ноль ноль, ноль ноль ноль.', extract_phones, []),
    ('ru', 'Плюс семь, семьсот один, ноль ноль ноль, ноль ноль ноль два.', extract_phones, ['+77010000002']),
    ('ru', 'Четыреста восемьдесят два КМА ноль два.', extract_plates, ['482KMA02']),
    ('kk', 'Төрт жүз сексен екі КМА нөл екі.', extract_plates, ['482KMA02']),
    ('kk', 'Төрт жүз сексен екі ка эм а нөл екі.', extract_plates, ['482KMA02']),
    ('ru', 'Полис эс кью огпо один ноль четыре пять ноль один.', extract_policy_numbers, ['SQ-OGPO-104501']),
    ('ru', 'Полис эс кью о гэ пэ о один ноль четыре пять ноль один.', extract_policy_numbers, ['SQ-OGPO-104501']),
    ('ru', 'Заявление си эл пять ноль ноль два восемь семь.', extract_claim_numbers, ['CL-500287']),
    ('ru', 'Девяносто один ноль пять двенадцать, тридцать ноль четыре пятьдесят шесть.', extract_iins, ['910512300456']),
]


async def main():
    if not settings.key:
        raise SystemExit('OPENAI_API_KEY is required')
    llm = LLM(settings)
    failures = 0
    try:
        for language, phrase, extractor, expected in CASES:
            speech = await llm.client.audio.speech.create(
                model=settings.tts_model, voice=settings.tts_voice, input=phrase,
                instructions=('Қазақша анық және табиғи сөйле.' if language == 'kk'
                              else 'Произнеси точно написанные слова на русском языке.'),
                response_format='mp3',
            )
            transcript = await transcribe(speech.content, 'audio/mpeg', 'auto', llm)
            actual = extractor(transcript)
            passed = actual == expected
            failures += not passed
            print(f'{"PASS" if passed else "FAIL"} [{language}] {phrase}')
            print(f'  STT: {transcript}')
            print(f'  extracted={actual}; expected={expected}')
    finally:
        await llm.close()
    if failures:
        raise SystemExit(f'{failures} synthetic speech probes failed')


if __name__ == '__main__':
    asyncio.run(main())
