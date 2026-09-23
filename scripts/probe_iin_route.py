"""Route the reproduced IIN turn through the configured LLM and dialogue state."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.config import settings
from app.core.context import Dialogue, Frame
from app.core.router import Router
from app.core.scenarios import Catalog
from app.services.llm import LLM


TEXT = 'Девяносто один ноль пять двенадцать, тридцать ноль четыре пятьдесят шесть.'


async def main():
    if not settings.key:
        raise SystemExit('OPENAI_API_KEY is required')
    llm = LLM(settings)
    try:
        state = Dialogue(active=Frame('SC01', waiting_slot='drivers_iin'))
        decision = await Router(Catalog(settings.data_dir), llm).route(TEXT, state)
        print(decision.model_dump_json(indent=2))
    finally:
        await llm.close()


if __name__ == '__main__':
    asyncio.run(main())
