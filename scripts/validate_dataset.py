"""Validate source data without a provider, predictions, or changes to the dataset."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.core.scenarios import Catalog

def validate(path):
    catalog=Catalog(path)
    utterances=json.loads((path/'dev_utterances.json').read_text(encoding='utf-8'))['utterances']
    ids=[u['id'] for u in utterances]
    if len(ids)!=len(set(ids)):
        raise ValueError('Duplicate dev utterance IDs')
    allowed=catalog.scenarios.keys() | catalog.system.keys()
    for u in utterances:
        if not u['text'].strip() or not u['expected'] or not set(u['expected'])<=allowed:
            raise ValueError(f"Invalid dev utterance {u['id']}")
        if u['lang'] not in ('ru','kk','mixed') or u['type'] not in ('single','multi_intent','out_of_scope','unclear'):
            raise ValueError(f"Invalid dev label {u['id']}")
    dialogs=json.loads((path/'dialogs_sample.json').read_text(encoding='utf-8'))['dialogs']
    for dialog in dialogs:
        for turn in dialog['turns']:
            if turn['role']=='client' and not set(turn.get('scenarios',[]))<=allowed:
                raise ValueError(f"Unknown scenario in {dialog['dialog_id']}")
    return {**catalog.summary(),'dev_utterances':len(utterances),'sample_dialogs':len(dialogs),
            'by_language':dict(Counter(u['lang'] for u in utterances)),
            'by_type':dict(Counter(u['type'] for u in utterances)),
            'sha256':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(path.glob('*.json'))},
            'validation':'passed','llm_accuracy':'not_measured'}

if __name__=='__main__':
    print(json.dumps(validate(ROOT/'case/voice_router_dataset'),ensure_ascii=False,indent=2))
