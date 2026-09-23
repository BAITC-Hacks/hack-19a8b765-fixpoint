"""Read-only project audit: isolated mock probes, existing metrics, archive aggregates.

No external API calls or writes to production sessions. Run from the repo root:
  .venv/Scripts/python.exe -X utf8 scripts/audit_compliance.py
"""
import collections
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.core.context import Dialogue
from app.core.contracts import trace_from
from app.core.executor import Executor
from app.core.models import Candidate, RoutingDecision
from app.core.scenarios import Catalog
from app.services.actions import ActionError, MockBackend

catalog = Catalog(ROOT / 'case/voice_router_dataset')


def decision(sid, slots=None, **kwargs):
    return RoutingDecision(scenarios=[Candidate(scenario_id=sid, confidence=.95,
        reason='Audit fixture; not LLM output.', slots=slots or {})],
        language='ru', response_language='ru', reason='Audit fixture.', **kwargs)


def fresh():
    backend = MockBackend(catalog)
    return backend, Dialogue(), Executor(catalog, backend)


probes = {}
b, s, e = fresh()
args = {'region': 'almaty', 'vehicle_type': 'car', 'drivers_iin': ['000000000000'], 'term_months': 6}
r = e.process(decision('SC01', args), s, 'Рассчитайте ОГПО на шесть месяцев.')
probes['ogpo_six_months'] = {'direct_price': b.price('ogpo', args)['price'],
    'dialogue_price': r['facts']['calc_ogpo_price']['price'], 'term_retained': 'term_months' in s.active.slots}

b, s, e = fresh()
args = {'car_value': 10_000_000, 'car_year': 2022, 'package': 'Lite'}
r = e.process(decision('SC03', args), s, 'Рассчитайте КАСКО Lite.')
probes['casco_lite'] = {'direct_price': b.price('casco', args)['price'],
    'dialogue_price': r['facts']['calc_casco_price']['price'], 'package_retained': 'package' in s.active.slots}

b, s, e = fresh()
r = e.process(decision('SC15', {'policy_number': 'SQ-TRVL-304552'}), s, 'Заболел за границей.')
probes['travel_emergency_missing_location'] = {'status': r['status'], 'waiting': s.active.waiting_slot,
    'safety_is_fraud_policy': r['facts'].get('safety') == catalog.kb['fraud_policy']}
b, s, e = fresh()
r = e.process(decision('SC15'), s, 'Заболел за границей.')
probes['travel_emergency_before_identification'] = {'status': r['status'], 'waiting': s.active.waiting_slot,
    'has_safety_facts': bool(r['facts'])}

b, s, e = fresh()
client = next(c for c in b.data['clients'] if c['client_id'] == 'C008')
args = {'phone': client['phone'], 'culprit_vehicle_plate': '777ABC02',
        'incident_date': '2026-09-28', 'incident_description': 'Потерпевший обратился по полису виновника.'}
r = e.process(decision('SC12', args), s, 'У виновника номер 777ABC02.')
claim = r.get('facts', {}).get('preview', {}).get('result', {})
probes['victim_policy_role'] = {'status': r['status'], 'expected_culprit_policy': 'SQ-OGPO-104501',
    'selected_policy': s.active.slots.get('policy_number'), 'preview_claim_policy': claim.get('policy_number')}

b, s, e = fresh()
e.process(decision('SC29', {'phone': '+77010000001', 'contact_field': 'address',
                          'new_value': 'Audit address'}), s, 'Смените адрес.')
d = decision('SC29', is_continuation=True)
d.scenarios.append(Candidate(scenario_id='SC33', confidence=.95, reason='Second request.', slots={'city': 'Almaty'}))
r = e.process(d, s, 'Да, подтверждаю. А где офис в Алматы?')
probes['confirmation_plus_question'] = {'status': r['status'],
    'address_changed': b.data['clients'][0]['address'] == 'Audit address', 'queued': [f.scenario_id for f in s.queue]}

b, s, e = fresh()
run = b.run
calls = []
def intermittent(name, slots, **kwargs):
    calls.append(name)
    if name == 'get_offices' and calls.count(name) == 1:
        raise ActionError('service_unavailable', 'Injected temporary failure')
    return run(name, slots, **kwargs)
b.run = intermittent
r = e.process(decision('SC33', {'city': 'Almaty'}), s, 'Где офис?')
probes['temporary_action_failure'] = {'status': r['status'], 'get_offices_calls': calls.count('get_offices')}

b, s, e = fresh()
r = e.process(decision('SC37'), s, 'Соедините с оператором.')
engine = SimpleNamespace(state=s, llm=SimpleNamespace(settings=SimpleNamespace(provider='mock')))
trace = trace_from([{'event': 'execution_trace', 'execution': r}], engine)
probes['operator_trace'] = {'status': r['status'], 'audit_actions': [a['action'] for a in b.audit],
    'trace_actions': trace.actions}

b, s, e = fresh()
r = e.process(decision('SC18', {'claim_number': 'CL-500330', 'product_type': 'casco'}), s,
              'Каких документов не хватает по моему заявлению?')
probes['claim_specific_documents'] = {'status': r['status'], 'actions': [a['name'] for a in r['actions']],
    'read_claim': any(a['action'] == 'get_claim' for a in b.audit)}

b, s, e = fresh()
e.process(decision('SC25', {'policy_number': 'SQ-OGPO-104501'}), s, 'Проверьте полис.')
b.audit.clear()
r = e.process(decision('SC33', {'city': 'Almaty'}), s, 'Где офис в Алматы?')
probes['unsolicited_sms'] = {'status': r['status'], 'actions': [a['action'] for a in b.audit]}

b, s, e = fresh()
args = {'policy_number': 'SQ-DMS-604220', 'doctor_specialty': 'therapist', 'city': 'Astana', 'preferred_date': '2026-10-02'}
r = e.process(decision('SC21', args), s, 'Запишите к терапевту.')
prepared = r['facts']['preview']['result']['slot_datetime']
trial = MockBackend(catalog)
trial.run('book_appointment', s.active.slots, confirmed=True)
b.bookings.update(trial.bookings)
r = e.process(decision('SC21', is_continuation=True), s, 'да')
actual = r.get('facts', {}).get('book_appointment', {}).get('slot_datetime')
probes['appointment_changed_after_preview'] = {'status': r['status'], 'prepared_time': prepared, 'executed_time': actual}

counts, languages, statuses = collections.Counter(), collections.Counter(), collections.Counter()
totals = []
for path in sorted((ROOT / 'runtime/sessions').glob('*.json')):
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        continue
    counts['sessions'] += 1
    for turn in document.get('turns', []):
        counts['turns'] += 1
        if turn.get('input', {}).get('source') != 'audio':
            continue
        counts['audio_turns'] += 1
        trace = turn.get('trace', {})
        languages[trace.get('language') or 'unknown'] += 1
        statuses[trace.get('status') or 'unknown'] += 1
        total = trace.get('latency_ms', {}).get('total')
        if isinstance(total, (int, float)):
            totals.append(total)

paths = ['backend/app/core/executor.py', 'backend/app/core/router.py', 'backend/app/core/slots.py',
         'backend/app/services/actions.py', 'backend/app/core/contracts.py', 'backend/app/main.py',
         'frontend/src/App.tsx', 'frontend/src/hooks/useSession.ts', 'frontend/src/voiceActivity.ts',
         'reports/predictions.json', 'reports/routing_trace.json']
output = {'method': 'Injected routing decisions; isolated mock state; no external API requests.',
    'captured_at': datetime.now(timezone.utc).isoformat(),
    'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    'sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths},
    'catalog': catalog.summary(), 'probes': probes,
    'archive': {'counts': dict(counts), 'audio_languages': dict(languages), 'audio_statuses': dict(statuses),
                'measured_voice_turns': len(totals), 'median_ms': statistics.median(totals) if totals else None,
                'min_ms': min(totals) if totals else None, 'max_ms': max(totals) if totals else None,
                'limitation': 'Historical, client-reported, non-controlled sample; no microphone playback verified by this audit.'}}
destination = ROOT / 'reports/compliance-audit-2026-09-23.json'
destination.parent.mkdir(exist_ok=True)
destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(output, ensure_ascii=False, indent=2))
