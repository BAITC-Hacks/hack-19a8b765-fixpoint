"""Generate predictions through the actual LLM API, then run the unmodified evaluator."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.config import settings
from app.core.context import Dialogue
from app.core.router import Router
from app.core.scenarios import Catalog
from app.services.llm import LLM, ProviderError

async def main(args):
    if settings.provider=='mock' or not settings.key:
        raise SystemExit('LLM provider key is missing. No mock accuracy will be reported.')
    catalog=Catalog(settings.data_dir)
    records=json.loads((settings.data_dir/'dev_utterances.json').read_text(encoding='utf-8'))['utterances']
    llm=LLM(settings)
    router=Router(catalog,llm)
    predictions,trace={},[]
    try:
        for i,u in enumerate(records[:args.limit] if args.limit else records):
            start=time.perf_counter()
            try:
                d=await router.route(u['text'],Dialogue())
                predictions[u['id']]=[s.scenario_id for s in d.scenarios]
                trace.append({'id':u['id'],'decision':d.model_dump(),'ms':round((time.perf_counter()-start)*1000,1)})
            except ProviderError as e:
                raise SystemExit(f"Evaluation stopped at {u['id']}; no complete metrics were produced: {e}") from e
            print(f"{i+1}/{len(records)} {u['id']} {predictions[u['id']]}",flush=True)
            await asyncio.sleep(args.delay)
    finally:
        await llm.close()
    out=ROOT/'reports'
    out.mkdir(exist_ok=True)
    p=out/'predictions.json'
    p.write_text(json.dumps(predictions,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'routing_trace.json').write_text(json.dumps({'provider':settings.provider,'model':settings.model,'records':trace},ensure_ascii=False,indent=2),encoding='utf-8')
    if args.limit:
        print('Partial smoke run only; full-set accuracy is not computed.')
        return
    result=subprocess.run([sys.executable,str(settings.data_dir/'evaluate.py'),str(p),str(settings.data_dir/'dev_utterances.json')],capture_output=True,text=True,encoding='utf-8')
    print(result.stdout)
    (out/'evaluation.txt').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:
        raise SystemExit(result.returncode)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--delay',type=float,default=1.0)
    asyncio.run(main(parser.parse_args()))
