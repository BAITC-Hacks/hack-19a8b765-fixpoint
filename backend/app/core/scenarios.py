import json
from datetime import date
from pathlib import Path

class Catalog:
    def __init__(self, path: Path):
        self.raw = {name: json.loads((path / f'{name}.json').read_text(encoding='utf-8-sig'))
                    for name in ['scenarios', 'slots', 'actions', 'knowledge_base', 'mock_backend']}
        for file, collection, key in [('scenarios','scenarios','scenario_id'),('scenarios','system_intents','id'),
                                      ('slots','slots','name'),('actions','actions','name')]:
            rows = self.raw[file].get(collection)
            if not isinstance(rows,list) or not rows:
                raise ValueError(f'{file}.json: {collection} must be a nonempty list')
            identifiers = [r.get(key) for r in rows]
            if None in identifiers or len(identifiers)!=len(set(identifiers)):
                raise ValueError(f'{file}.json: missing or duplicate {key}')
        self.scenarios = {s['scenario_id']: s for s in self.raw['scenarios']['scenarios']}
        self.system = {s['id']: s for s in self.raw['scenarios']['system_intents']}
        self.slots = {s['name']: s for s in self.raw['slots']['slots']}
        self.actions = {a['name']: a for a in self.raw['actions']['actions']}
        self.kb = self.raw['knowledge_base']
        self.as_of = date.fromisoformat(self.raw['scenarios']['meta']['as_of_date'])
        for name, content in self.raw.items():
            if content.get('meta',{}).get('as_of_date') != str(self.as_of):
                raise ValueError(f'{name}.json: inconsistent snapshot date')
        if len(self.scenarios) != 40:
            raise ValueError('Expected the 40 official scenarios')
        for s in self.scenarios.values():
            if any(r['use_instead'] not in self.scenarios.keys() | self.system.keys() for r in s['not_this_if']):
                raise ValueError(f"Unknown boundary target in {s['scenario_id']}")
            if any(a not in self.actions for a in s['actions']):
                raise ValueError(f"Unknown action in {s['scenario_id']}")
            irreversible = [a for a in s['actions'] if self.actions[a]['irreversible']]
            if irreversible and not s.get('requires_confirmation'):
                raise ValueError(f"{s['scenario_id']} includes irreversible actions without confirmation: {', '.join(irreversible)}")
            if any(k not in self.slots for k in s['slots']['required'] + s['slots']['optional']):
                raise ValueError(f"Unknown slot in {s['scenario_id']}")
            if s['handoff'] and s['handoff']['queue'] not in self.raw['actions']['queues']:
                raise ValueError(f"Unknown handoff queue in {s['scenario_id']}")
            if not all(s['examples'].get(lang) and s['responses'].get(lang) for lang in ('ru','kk')):
                raise ValueError(f"Missing bilingual examples in {s['scenario_id']}")
        for slot in self.slots.values():
            if slot['type'] not in ('string','enum','integer','date','boolean','list','text'):
                raise ValueError(f"Unknown type for {slot['name']}")
            if not all(slot['prompt'].get(lang) for lang in ('ru','kk')):
                raise ValueError(f"Missing question for {slot['name']}")
        for section in ('company','products','offices','clinics','claims','payments','cancellation'):
            if not self.kb.get(section):
                raise ValueError(f'knowledge_base.json: missing {section}')
        clients = {c['client_id'] for c in self.raw['mock_backend']['clients']}
        if any(p['client_id'] not in clients for p in self.raw['mock_backend']['policies']):
            raise ValueError('mock_backend.json: policy references unknown client')

    def summary(self):
        return {'scenarios':len(self.scenarios),'system_intents':len(self.system),'slots':len(self.slots),
                'actions':len(self.actions),'knowledge_sections':len(self.kb)-1,
                'clients':len(self.raw['mock_backend']['clients']),'as_of_date':str(self.as_of)}

    def routing_catalog(self):
        fields = ['scenario_id', 'name', 'description', 'not_this_if', 'priority', 'slots', 'handoff']
        return [{**{k: s[k] for k in fields}, 'examples': {l: v[:1] for l, v in s['examples'].items()}}
                for s in self.scenarios.values()]
