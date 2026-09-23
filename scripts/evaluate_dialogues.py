"""Evaluate the real router and controller through the ten labeled sample dialogues.

Run from the repository root after configuring a real LLM provider:
    python scripts/evaluate_dialogues.py
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import settings
from app.core.engine import Engine
from app.core.scenarios import Catalog
from app.services.llm import LLM, ProviderError


async def evaluate(limit):
    if settings.provider == 'mock' or not settings.key:
        raise SystemExit('LLM provider key is missing. No mock dialogue accuracy will be reported.')
    catalog = Catalog(settings.data_dir)
    source = json.loads((settings.data_dir / 'dialogs_sample.json').read_text(encoding='utf-8'))
    clients = {c['client_id']: c for c in catalog.raw['mock_backend']['clients']}
    llm = LLM(settings)
    records = []
    try:
        for dialog in source['dialogs'][:limit or None]:
            engine = Engine(catalog, llm)
            if dialog.get('client_id'):
                engine.state.client = clients.get(dialog['client_id'])
            for turn_no, turn in enumerate(dialog['turns'], 1):
                if turn['role'] != 'client':
                    continue
                started = time.perf_counter()
                events = []
                try:
                    async for event in engine.run(turn['text'], turn.get('lang', 'auto'), speak=False):
                        events.append(event)
                except ProviderError as exc:
                    raise SystemExit(
                        f"Evaluation stopped at {dialog['dialog_id']} turn {turn_no}; "
                        f"no complete metrics were produced: {exc}"
                    ) from exc
                route = next((e for e in events if e['event'] == 'routing_decision'), None)
                if not route:
                    raise SystemExit(f"No routing decision at {dialog['dialog_id']} turn {turn_no}.")
                got = [s['scenario_id'] for s in route.get('scenarios', [])]
                expected = turn.get('scenarios', [])
                records.append({
                    'dialog_id': dialog['dialog_id'], 'turn': turn_no,
                    'input_language': turn.get('lang'), 'text': turn['text'],
                    'expected': expected, 'predicted': got,
                    'primary_match': bool(got and expected and got[0] == expected[0]),
                    'full_match': set(got) == set(expected),
                    'reason': route.get('reason', ''),
                    'confidence': [s.get('confidence') for s in route.get('scenarios', [])],
                    'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
                    'actions': next((e.get('execution', {}).get('actions', []) for e in events
                                     if e['event'] == 'execution_trace'), []),
                })
                print(f"{dialog['dialog_id']} {turn_no}: expected={expected} predicted={got}", flush=True)
    finally:
        await llm.close()

    report = {
        'provider': settings.provider,
        'model': settings.model,
        'turns': len(records),
        'primary_accuracy': sum(r['primary_match'] for r in records) / len(records) if records else 0,
        'full_match': sum(r['full_match'] for r in records) / len(records) if records else 0,
        'records': records,
    }
    out = ROOT / 'reports'
    out.mkdir(exist_ok=True)
    (out / 'dialog_evaluation.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'dialog_evaluation.txt').write_text(
        f"Provider: {report['provider']}\nModel: {report['model']}\nTurns: {report['turns']}\n"
        f"Primary accuracy: {report['primary_accuracy']:.3f}\nFull match: {report['full_match']:.3f}\n",
        encoding='utf-8')
    print(f"\nPrimary accuracy: {report['primary_accuracy']:.3f}; full match: {report['full_match']:.3f}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0, help='evaluate only the first N sample dialogues')
    asyncio.run(evaluate(parser.parse_args().limit))
