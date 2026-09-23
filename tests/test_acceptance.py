"""Local acceptance of actions and dialogue transitions; no real-provider claims."""
import copy
import json
from pathlib import Path

import pytest

from app.core.context import Dialogue
from app.core.executor import Executor
from app.core.models import Candidate, RoutingDecision
from app.services.actions import ActionError


OGPO = {'product_type':'ogpo', 'region':'almaty', 'vehicle_type':'car',
        'vehicle_plate':'123ABC02', 'drivers_iin':['850314300121'], 'phone':'+77010000001', 'client_id':'C001'}
TRAVEL = {'trip_country':'Turkey', 'trip_start':'2026-10-10', 'trip_end':'2026-10-16',
          'travelers_count':2, 'traveler_max_age':40, 'phone':'+77010000001'}
ACTION_CASES = {
    'find_client': ({'phone':'+77010000001'}, {'client_id','full_name'}),
    'get_policies': ({'client_id':'C001'}, {'policies'}),
    'get_policy': ({'policy_number':'SQ-OGPO-104501'}, {'policy_number','status'}),
    'get_bm_class': ({'iin':'850314300121'}, {'bm_class'}),
    'calc_ogpo_price': (OGPO, {'price'}),
    'calc_casco_price': ({'car_value':12000000,'car_year':2019,'franchise':50000}, {'price'}),
    'calc_travel_price': (TRAVEL, {'price','zone','coverage'}),
    'calc_property_price': ({'property_type':'apartment','sum_insured':10000000}, {'price'}),
    'calc_accident_price': ({'sum_insured':1000000}, {'price'}),
    'create_policy': (OGPO, {'policy_number','status'}),
    'renew_policy': ({'policy_number':'SQ-OGPO-104501'}, {'policy_number','price'}),
    'update_policy': ({'policy_number':'SQ-OGPO-104501','new_driver_iin':'880126300907'}, {'extra_premium'}),
    'cancel_policy': ({'policy_number':'SQ-CASCO-204350','cancel_reason':'Продажа автомобиля'}, {'refund_amount'}),
    'create_claim': ({'policy_number':'SQ-CASCO-204118','client_id':'C001','product_type':'casco',
                      'incident_date':'2026-09-30','incident_description':'Повреждён бампер'}, {'claim_number','status'}),
    'get_claim': ({'claim_number':'CL-500287'}, {'claim_number','status','next_step'}),
    'create_dispute': ({'claim_number':'CL-500287','complaint_text':'Не согласен с суммой'}, {'ticket_id'}),
    'book_inspection': ({'claim_number':'CL-500198','city':'Almaty','preferred_date':'2026-10-02'}, {'slot_datetime','address'}),
    'book_appointment': ({'policy_number':'SQ-DMS-604220','doctor_specialty':'therapist','city':'Astana',
                          'preferred_date':'2026-10-02'}, {'clinic_name','slot_datetime'}),
    'check_coverage': ({'policy_number':'SQ-DMS-604220','service_name':'терапевт'}, {'package','coverage_rules'}),
    'list_clinics': ({'city':'Astana'}, {'clinics'}),
    'resend_documents': ({'policy_number':'SQ-OGPO-104501'}, {'sent_to','delivery'}),
    'check_payment': ({'client_id':'C003','payment_date':'2026-09-30'}, {'payments'}),
    'update_contact': ({'client_id':'C001','contact_field':'address','new_value':'Новый адрес'}, {'updated'}),
    'request_document': ({'policy_number':'SQ-OGPO-104501','document_type':'policy_copy','email':'test@mail.example'}, {'sent_to'}),
    'get_offices': ({'city':'Almaty'}, {'offices'}),
    'kb_lookup': ({'topic':'payments'}, {'facts'}),
    'send_sms': ({'phone':'+77010000001'}, {'status'}),
    'create_callback': ({'phone':'+77010000001','callback_time':'2026-10-02T10:00:00'}, {'status'}),
    'create_complaint': ({'complaint_text':'Долгое ожидание'}, {'ticket_id'}),
    'report_fraud': ({'fraud_details':'Запросили код SMS'}, {'ticket_id'}),
    'transfer_to_operator': ({'queue':'operator_general','summary':{'language':'ru'}}, {'real_transfer','summary'}),
}


def route(sid, slots=None, confidence=.95, **kwargs):
    return RoutingDecision(scenarios=[Candidate(scenario_id=sid, confidence=confidence, reason='fixture', slots=slots or {})],
                           language='ru', response_language='ru', reason='fixture', **kwargs)


def test_action_cases_cover_entire_dataset(catalog):
    assert set(ACTION_CASES) == set(catalog.actions)


@pytest.mark.parametrize('name', ACTION_CASES)
def test_action_success_preview_and_replay(name, catalog, backend):
    args, outputs = copy.deepcopy(ACTION_CASES[name])
    irreversible = catalog.actions[name]['irreversible']
    if irreversible:
        before = copy.deepcopy((backend.data, backend.bookings, backend.audit, backend.operations))
        with pytest.raises(ActionError, match='подтверждение'):
            backend.run(name, args)
        preview = backend.run(name, args, preview=True)
        assert outputs <= preview['result'].keys()
        assert (backend.data, backend.bookings, backend.audit, backend.operations) == before
    result = backend.run(name, args, confirmed=irreversible, operation_id='acceptance-operation')
    assert outputs <= result.keys()
    after = copy.deepcopy((backend.data, backend.bookings, backend.audit))
    assert backend.run(name, args, confirmed=irreversible, operation_id='acceptance-operation') == result
    assert (backend.data, backend.bookings, backend.audit) == after


@pytest.mark.parametrize('sid,slots', [
    ('SC02', OGPO), ('SC06', TRAVEL), ('SC27', {'phone':'+77010000001','policy_number':'SQ-OGPO-104501'}),
])
def test_confirmed_purchase_and_renewal_reach_sms(sid, slots, catalog, backend):
    executor, state = Executor(catalog, backend), Dialogue()
    assert executor.process(route(sid, slots), state, 'оформить')['status'] == 'confirmation'
    count = len(backend.data['policies'])
    result = executor.process(route(sid), state, 'да')
    assert result['status'] == 'completed'
    assert len(backend.data['policies']) == count + 1
    assert result['actions'][-1]['name'] == 'send_sms'
    assert not any(a['mode'] == 'error' for a in result['actions'])


def test_victim_policy_does_not_become_callers_policy(catalog, backend):
    executor, state = Executor(catalog, backend), Dialogue()
    slots = {'phone':'+77010000002', 'culprit_vehicle_plate':'101AAA02',
             'incident_date':'2026-09-30','incident_description':'ДТП, я пострадавший'}
    first = executor.process(route('SC12', slots), state, 'заявление')
    assert first['status'] == 'confirmation'
    assert state.client['client_id'] == 'C002'
    assert state.active.slots['policy_number'] == 'SQ-OGPO-103990'
    result = executor.process(route('SC12'), state, 'да')
    assert result['status'] == 'completed'
    claim = backend.data['claims'][-1]
    assert claim['client_id'] == 'C002' and claim['policy_number'] == 'SQ-OGPO-103990'


def test_conflicting_identity_is_rejected(backend):
    with pytest.raises(ActionError, match='разным клиентам'):
        backend.identify({'phone':'+77010000001', 'iin':'920607400233'})


def test_urgent_injury_interrupts_pending_write_without_collecting_location(catalog, backend):
    executor, state = Executor(catalog, backend), Dialogue()
    executor.process(route('SC29', ACTION_CASES['update_contact'][0] | {'phone':'+77010000001'}), state, 'сменить адрес')
    before = copy.deepcopy(backend.data)
    result = executor.process(route('SC11', {'injured':True}), state, 'ДТП, есть раненый')
    assert result['status'] == 'handoff' and state.closed
    assert result['facts']['safety'] == catalog.kb['claims']['road_accident_now']
    assert result['actions'][-1]['result']['queue'] == 'claims_team'
    assert state.suspended[-1].pending is None and backend.data == before


def test_conditional_handoff_closes_session_and_is_traced(catalog, backend):
    result = Executor(catalog, backend).process(route('SC38', {'fraud_details':'Передал SMS код'}, needs_operator=True), state := Dialogue(), 'передал код')
    assert result['status'] == 'handoff' and state.closed
    assert result['actions'][-1]['result']['queue'] == 'security_team'


def test_only_confident_understanding_resets_unclear_counter(catalog, backend):
    executor, state = Executor(catalog, backend), Dialogue()
    executor.process(route('SYS_UNCLEAR', confidence=.2), state, '?')
    executor.process(route('SC01', confidence=.6), state, 'может быть')
    assert state.low_confidence == 1
    executor.process(route('SC33', {'city':'Almaty'}), state, 'адрес офиса')
    assert state.low_confidence == 0


def test_parameter_change_after_write_does_not_repeat_purchase(catalog, backend, monkeypatch):
    executor, state = Executor(catalog, backend), Dialogue()
    executor.process(route('SC02', OGPO), state, 'оформить')
    original_run = backend.run
    def failed_sms(name, *args, **kwargs):
        if name == 'send_sms':
            raise ActionError('invalid_input', 'Номер доставки не подтверждён')
        return original_run(name, *args, **kwargs)
    monkeypatch.setattr(backend, 'run', failed_sms)
    assert executor.process(route('SC02'), state, 'да')['status'] == 'action_error'
    count = len(backend.data['policies'])
    result = executor.process(route('SC02', {'phone':'+77010000009'}), state, 'другой телефон')
    assert result['status'] == 'handoff'
    assert len(backend.data['policies']) == count


def test_confirmation_is_scoped_to_one_irreversible_action(catalog, backend):
    # Exercise a future scenario with two writes: consent must never authorize both.
    catalog.scenarios['SC29']['actions'].append('create_dispute')
    executor, state = Executor(catalog, backend), Dialogue()
    slots = {'phone':'+77010000001','contact_field':'address','new_value':'Новый адрес',
             'claim_number':'CL-500198','complaint_text':'Не согласен'}
    executor.process(route('SC29', slots), state, 'запрос')
    result = executor.process(route('SC29'), state, 'да')
    assert result['status'] == 'confirmation'
    assert result['actions'][-1]['name'] == 'create_dispute' and result['actions'][-1]['mode'] == 'preview'
    assert not any(a['action'] == 'create_dispute' for a in backend.audit)
    assert executor.process(route('SC29'), state, 'да')['status'] == 'completed'


def test_handoff_contains_current_utterance_and_all_requested_scenarios(catalog, backend):
    request = route('SC37')
    request.scenarios.append(Candidate(scenario_id='SC33',confidence=.9,reason='second'))
    result = Executor(catalog, backend).process(request, Dialogue(), 'Оператор и адрес офиса')
    summary = result['actions'][-1]['result']['summary']
    assert summary['current_request'] == 'Оператор и адрес офиса'
    assert summary['requested_scenarios'] == ['SC37','SC33']


def test_travel_emergency_never_uses_fraud_instructions(catalog, backend):
    result = Executor(catalog, backend).process(route('SC15'), Dialogue(), 'Заболел за границей')
    assert result['facts']['safety'] == catalog.kb['products']['travel']['notes']


@pytest.mark.parametrize('dialog_index', range(10))
def test_sample_dialogue_outcomes(dialog_index, catalog, backend):
    # Ground-truth fixture routing exercises the controller only, not model quality.
    data = json.loads((Path(__file__).resolve().parents[1]/'case/voice_router_dataset/dialogs_sample.json').read_text(encoding='utf-8'))
    sample = data['dialogs'][dialog_index]
    executor, state = Executor(catalog, backend), Dialogue()
    results=[]
    for turn in sample['turns']:
        if turn['role'] != 'client':
            continue
        ids = turn.get('scenarios') or ['SYS_UNCLEAR']
        slots = turn.get('slots',{})
        candidates=[]
        for sid in ids:
            spec = catalog.scenarios.get(sid,{}).get('slots',{})
            allowed = set(spec.get('required',[])+spec.get('optional',[])) | {'phone','iin'}
            candidates.append(Candidate(scenario_id=sid,confidence=.95,reason='fixture',slots={k:v for k,v in slots.items() if k in allowed}))
        language = turn['lang'] if turn['lang'] in ('ru','kk') else 'kk'
        decision = RoutingDecision(scenarios=candidates,language=turn['lang'],response_language=language,reason='fixture',
            is_continuation=bool(state.active and state.active.scenario_id==ids[0]),
            confirmation='yes' if sample['dialog_id']=='D04' and len(ids)>1 else None)
        result = executor.process(decision,state,turn['text'])
        assert result['status'] != 'action_error', (sample['dialog_id'], result)
        results.append(result)
    names=[a['action'] for a in backend.audit]
    sid=sample['dialog_id']
    if sid=='D01':
        assert names.count('create_policy')==1 and names.count('send_sms')==1
        assert backend.data['policies'][-1]['premium']==38000
    elif sid=='D02':
        assert names.count('create_claim')==1
        assert backend.data['claims'][-1]['policy_number']=='SQ-OGPO-104501'
        assert backend.data['claims'][-1]['claim_type']=='ogpo_victim' and state.closed
    elif sid=='D03':
        assert 'renew_policy' not in names
        assert results[-2]['facts']['claim']['claim_number']=='CL-500330'
    elif sid=='D04':
        assert names.count('book_appointment')==1 and len(backend.bookings)==1
        assert any(f.scenario_id=='SC22' and f.slots['service_name']=='lab tests' for f in state.queue)
    elif sid=='D05':
        assert names.count('resend_documents')==1
        assert results[-1]['facts']['resend_documents']['sent_to']=='rustem.i@mail.example'
    elif sid=='D06':
        assert names.count('create_complaint')==1 and state.closed
        assert results[-1]['facts']['handoff']['queue']=='complaints_team'
        assert results[-1]['facts']['handoff']['summary']['client_id']=='C004'
    elif sid=='D07':
        assert results[-1]['facts']['cancel_policy']['refund_amount']==163800
        assert backend.policy({'policy_number':'SQ-CASCO-204350'})['status']=='cancelled'
    elif sid=='D08':
        assert results[-2]['facts']['claim']['missing_documents']
    elif sid=='D09':
        assert names.count('report_fraud')==1
        assert results[-1]['facts']['get_policy']['policy_number']=='SQ-OGPO-103990'
    elif sid=='D10':
        assert names.count('create_policy')==1
        policy=backend.data['policies'][-1]
        assert policy['premium']==15400 and policy['start_date']=='2026-10-10' and policy['end_date']=='2026-10-16'


@pytest.mark.parametrize('recover', [True,False])
def test_service_failure_retries_once_then_recovers_or_hands_off(recover,catalog,backend,monkeypatch):
    original=backend.run
    attempts=[]
    def flaky(name,*args,**kwargs):
        if name=='calc_ogpo_price':
            attempts.append(name)
            if not recover or len(attempts)==1:
                raise ActionError('service_unavailable','Временный сбой')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(backend,'run',flaky)
    result=Executor(catalog,backend).process(route('SC01',OGPO),Dialogue(),'рассчитать')
    assert len(attempts)==2
    assert result['status']==('completed' if recover else 'handoff')


def test_unavailable_handoff_is_not_claimed_as_success(catalog,backend,monkeypatch):
    attempts=[]
    def unavailable(*args,**kwargs):
        attempts.append(args[0])
        raise ActionError('service_unavailable','Оператор недоступен')
    monkeypatch.setattr(backend,'run',unavailable)
    state=Dialogue()
    result=Executor(catalog,backend).process(route('SC37'),state,'оператор')
    assert result['status']=='action_error' and not state.closed
    assert attempts==['transfer_to_operator','transfer_to_operator']
