import asyncio
import copy
import json
from pathlib import Path
import pytest
from app.core.context import Dialogue
from app.core.executor import Executor
from app.core.models import Candidate, RoutingDecision
from app.core.slots import validate_slots
from app.services.actions import ActionError, MockBackend

def decision(sid, slots=None, confidence=.95, **kw):
    return RoutingDecision(scenarios=[Candidate(scenario_id=sid, confidence=confidence, reason='test',slots=slots or {})],
                           language='ru',response_language='ru',reason='test',**kw)

def test_catalog_references(catalog):
    assert len(catalog.scenarios)==40 and len(catalog.actions)==31 and len(catalog.slots)==43
    assert str(catalog.as_of)=='2026-10-01'
    for s in catalog.scenarios.values():
        assert all(r['use_instead'] in catalog.scenarios.keys() | catalog.system.keys() for r in s['not_this_if'])

def test_reference_prices(backend):
    assert backend.price('ogpo',{'region':'almaty','vehicle_type':'car','drivers_iin':['000000000000']})['price']==38000
    assert backend.price('travel',{'trip_country':'Turkey','trip_start':'2026-10-10','trip_end':'2026-10-16','travelers_count':2,'traveler_max_age':40})['price']==15400
    assert backend.run('cancel_policy',{'policy_number':'SQ-CASCO-204350','cancel_reason':'test'},preview=True)['result']['refund_amount']==163800

def test_preview_confirmation_and_idempotency(backend):
    s={'client_id':'C001','contact_field':'address','new_value':'New address'}
    before=copy.deepcopy(backend.data)
    with pytest.raises(ActionError,match='подтверждение'):
        backend.run('update_contact',s)
    preview=backend.run('update_contact',s,preview=True)
    assert preview['preview'] and backend.data==before
    first=backend.run('update_contact',s,confirmed=True,operation_id='one')
    assert backend.run('update_contact',s,confirmed=True,operation_id='one')==first
    assert len(backend.audit)==1
    with pytest.raises(ActionError):
        backend.run('update_contact',{**s,'new_value':'Different'},confirmed=True,operation_id='one')

def test_session_isolation(catalog,backend):
    other=MockBackend(catalog)
    backend.run('update_contact',{'client_id':'C001','contact_field':'address','new_value':'Changed'},confirmed=True)
    assert other.data['clients'][0]['address']!=backend.data['clients'][0]['address']

def test_slot_validation(catalog):
    slots,invalid=validate_slots({'phone':'8 (701) 000-00-01','iin':'123','injured':'false','car_year':True,'city':'astana','trip_start':'2026-02-31'},catalog)
    assert slots=={'phone':'+77010000001','city':'Astana'}
    assert set(invalid)=={'iin','injured','car_year','trip_start'}

def test_dataset_loader_rejects_duplicate_ids(tmp_path,catalog):
    for name,value in catalog.raw.items():
        content=copy.deepcopy(value)
        if name=='slots':
            content['slots'].append(content['slots'][0])
        (tmp_path/f'{name}.json').write_text(json.dumps(content),encoding='utf-8')
    from app.core.scenarios import Catalog
    with pytest.raises(ValueError,match='duplicate'):
        Catalog(tmp_path)

def test_quote_to_purchase_preserves_related_parameters(catalog,backend):
    state=Dialogue()
    executor=Executor(catalog,backend)
    executor.process(decision('SC01',{'region':'almaty','vehicle_type':'car','drivers_iin':['000000000000']}),state,'quote')
    result=executor.process(decision('SC02'),state,'buy')
    assert state.active.slots['drivers_iin']==['000000000000']
    assert result['question']==catalog.slots['vehicle_plate']['prompt']['ru']

def test_changed_parameters_require_fresh_confirmation(catalog,backend):
    e,state=Executor(catalog,backend),Dialogue()
    d=decision('SC29',{'phone':'+77010000001','contact_field':'address','new_value':'Address one'})
    assert e.process(d,state,'сменить адрес')['status']=='confirmation'
    original=backend.data['clients'][0]['address']
    changed=e.process(decision('SC29',{'new_value':'Address two'},is_continuation=True),state,'нет, другой адрес')
    assert changed['status']=='confirmation' and backend.data['clients'][0]['address']==original
    assert e.process(decision('SC29',is_continuation=True),state,'да')['status']=='completed'
    assert backend.data['clients'][0]['address']=='Address two'

def test_no_declines_write(catalog,backend):
    e,state=Executor(catalog,backend),Dialogue()
    e.process(decision('SC29',{'phone':'+77010000001','contact_field':'address','new_value':'Address'}),state,'update')
    original=copy.deepcopy(backend.data)
    assert e.process(decision('SC29'),state,'нет')['status']=='cancelled'
    assert original==backend.data

def test_unclear_interruption_cannot_confirm_old_operation(catalog,backend):
    executor,state=Executor(catalog,backend),Dialogue()
    executor.process(decision('SC29',{'phone':'+77010000001','contact_field':'address','new_value':'Changed'}),state,'change')
    original=copy.deepcopy(backend.data)
    executor.process(decision('SYS_UNCLEAR',confidence=.5),state,'а это?')
    assert state.active.pending is None
    result=executor.process(decision('SC29'),state,'да')
    assert result['status']=='confirmation'
    assert backend.data==original

def test_low_confidence_handoff(catalog,backend):
    e,state=Executor(catalog,backend),Dialogue()
    assert e.process(decision('SYS_UNCLEAR',confidence=.2),state,'?')['status']=='system'
    assert e.process(decision('SYS_UNCLEAR',confidence=.2),state,'?')['status']=='handoff'

def test_multitopic_and_resume(catalog,backend):
    e,state=Executor(catalog,backend),Dialogue()
    d=decision('SC01')
    d.scenarios.append(Candidate(scenario_id='SC33',confidence=.9,reason='second',slots={'city':'Astana'}))
    e.process(d,state,'price and offices')
    assert [f.scenario_id for f in state.queue]==['SC33']
    e.process(decision('SC31',is_topic_switch=True),state,'payment methods')
    assert state.suspended[-1].scenario_id=='SC01'
    e.process(decision('SC01',resume_previous=True),state,'return')
    assert state.active.scenario_id=='SC01'

def test_policy_ambiguity_and_historical_claim(backend):
    with pytest.raises(ActionError):
        backend.policy({'vehicle_plate':'777ABC02'})
    assert backend.policy({'vehicle_plate':'777ABC02','product_type':'ogpo'})['product']=='ogpo'
    s={'policy_number':'SQ-OGPO-102850','product_type':'ogpo','incident_date':'2026-09-01','incident_description':'event'}
    assert backend.run('create_claim',s,preview=True)['result']['claim_number']

def test_unpriced_cases_do_not_invent_financial_results(backend):
    with pytest.raises(ActionError):
        backend.price('casco',{'car_year':2013,'car_value':1000000,'package':'Lite'})
    before=copy.deepcopy(backend.data)
    with pytest.raises(ActionError):
        backend.run('update_policy',{'policy_number':'SQ-OGPO-104501','vehicle_plate':'111AAA01'},confirmed=True)
    assert before==backend.data

@pytest.mark.parametrize('sid',[f'SC{i:02}' for i in range(1,41)])
def test_every_scenario_enters_executor(sid,catalog,backend):
    result=Executor(catalog,backend).process(decision(sid),Dialogue(),'test')
    assert result['status'] in ('collecting','completed','handoff','confirmation','action_error')

@pytest.mark.parametrize('dialog_index',range(10))
def test_sample_dialogs_with_recorded_decisions_do_not_crash(dialog_index,catalog,backend):
    # Fixture-driven controller smoke test, NOT an LLM accuracy or full dialogue acceptance test.
    path=Path(__file__).resolve().parents[1]/'case/voice_router_dataset/dialogs_sample.json'
    sample=json.loads(path.read_text(encoding='utf-8'))['dialogs'][dialog_index]
    e,state=Executor(catalog,backend),Dialogue()
    for turn in sample['turns']:
        if turn['role']!='client':
            continue
        ids=turn.get('scenarios') or ['SYS_UNCLEAR']
        d=decision(ids[0],turn.get('slots',{}))
        d.scenarios += [Candidate(scenario_id=x,confidence=.9,reason='fixture') for x in ids[1:]]
        result=e.process(d,state,turn['text'])
        assert 'status' in result
