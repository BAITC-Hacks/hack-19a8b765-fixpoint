"""Fixture-backed behavior checks for every business scenario.

These inject a routing decision, so they test the dialogue executor and mock
backend, not LLM classification or real speech providers.
"""

import copy

import pytest

from app.core.context import Dialogue
from app.core.executor import Executor
from app.core.models import Candidate, RoutingDecision


def decision(scenario_id, slots=None, *, continuation=False, needs_operator=False):
    return RoutingDecision(
        scenarios=[Candidate(scenario_id=scenario_id, confidence=0.95,
                             reason='fixture-backed scenario test', slots=slots or {})],
        language='ru', response_language='ru', reason='fixture-backed scenario test',
        is_continuation=continuation, needs_operator=needs_operator,
    )


# Each row supplies the data needed to reach a meaningful action or a known
# unsupported boundary. Expected actions are checked by name and mode below.
CASES = [
    ('SC01', {'region': 'almaty', 'vehicle_type': 'car', 'drivers_iin': ['920607400233']}, 'completed', 'calc_ogpo_price'),
    ('SC02', {'vehicle_plate': '482KMA02', 'drivers_iin': ['920607400233'], 'phone': '+77071234567', 'vehicle_type': 'car'}, 'confirmation', 'create_policy'),
    ('SC03', {'car_value': 7_800_000, 'car_year': 2022}, 'completed', 'calc_casco_price'),
    ('SC04', {'policy_number': 'SQ-OGPO-105120', 'new_driver_iin': '880126300907'}, 'confirmation', 'update_policy'),
    ('SC05', {'policy_number': 'SQ-OGPO-104501', 'vehicle_plate': '111AAA01'}, 'action_error', 'update_policy'),
    ('SC06', {'trip_country': 'Turkey', 'trip_start': '2026-10-10', 'trip_end': '2026-10-16', 'travelers_count': 2,
              'traveler_max_age': 40, 'phone': '+77071234567'}, 'confirmation', 'create_policy'),
    ('SC07', {'property_type': 'apartment', 'sum_insured': '5000000'}, 'completed', 'calc_property_price'),
    ('SC08', {'sum_insured': '3000000'}, 'completed', 'calc_accident_price'),
    ('SC09', {}, 'completed', 'kb_lookup'),
    ('SC10', {'company_name': 'Test LLP', 'employees_count': 20, 'phone': '+77071234567'}, 'handoff', 'transfer_to_operator'),
    ('SC11', {'injured': True, 'location': 'Almaty'}, 'handoff', 'transfer_to_operator'),
    ('SC12', {'culprit_vehicle_plate': '777ABC02', 'incident_date': '2026-09-28',
              'incident_description': 'Rear-end collision', 'phone': '+77010000005'}, 'confirmation', 'create_claim'),
    ('SC13', {'policy_number': 'SQ-CASCO-204300', 'incident_date': '2026-09-28',
              'incident_description': 'Windshield damaged'}, 'confirmation', 'create_claim'),
    ('SC14', {'policy_number': 'SQ-PROP-404077', 'incident_date': '2026-09-28',
              'incident_description': 'Water leak'}, 'confirmation', 'create_claim'),
    ('SC15', {'policy_number': 'SQ-TRVL-304552', 'location': 'Turkey',
              'incident_description': 'Medical assistance needed'}, 'handoff', 'transfer_to_operator'),
    # No accident policy exists in the fixture; a property policy must not create an accident claim.
    ('SC16', {'policy_number': 'SQ-PROP-404077', 'incident_date': '2026-09-28',
              'incident_description': 'Injury'}, 'action_error', 'create_claim'),
    ('SC17', {'claim_number': 'CL-500330'}, 'completed', 'get_claim'),
    ('SC18', {'product_type': 'casco'}, 'completed', 'kb_lookup'),
    ('SC19', {'claim_number': 'CL-500330', 'complaint_text': 'Disagree with payout'}, 'confirmation', 'create_dispute'),
    ('SC20', {'claim_number': 'CL-500330', 'city': 'Pavlodar', 'preferred_date': '2026-10-02'}, 'confirmation', 'book_inspection'),
    ('SC21', {'policy_number': 'SQ-DMS-604220', 'doctor_specialty': 'therapist',
              'city': 'Astana', 'preferred_date': '2026-10-02'}, 'confirmation', 'book_appointment'),
    ('SC22', {'policy_number': 'SQ-DMS-604220', 'service_name': 'consultation'}, 'completed', 'check_coverage'),
    ('SC23', {'city': 'Astana'}, 'completed', 'list_clinics'),
    ('SC24', {'phone': '+77010000002'}, 'completed', 'send_sms'),
    ('SC25', {'policy_number': 'SQ-OGPO-104501'}, 'completed', 'get_policy'),
    ('SC26', {'phone': '+77010000001', 'policy_number': 'SQ-OGPO-104501'}, 'completed', 'resend_documents'),
    ('SC27', {'policy_number': 'SQ-OGPO-102850'}, 'confirmation', 'renew_policy'),
    ('SC28', {'policy_number': 'SQ-CASCO-204350', 'cancel_reason': 'Sold car'}, 'confirmation', 'cancel_policy'),
    ('SC29', {'phone': '+77010000001', 'contact_field': 'address', 'new_value': 'New test address'}, 'confirmation', 'update_contact'),
    ('SC30', {'payment_date': '2026-09-30', 'phone': '+77010000003'}, 'handoff', 'check_payment'),
    ('SC31', {}, 'completed', 'kb_lookup'),
    ('SC32', {'iin': '850314300121'}, 'completed', 'get_bm_class'),
    ('SC33', {'city': 'Almaty'}, 'completed', 'get_offices'),
    ('SC34', {}, 'completed', 'kb_lookup'),
    ('SC35', {'complaint_text': 'No callback'}, 'completed', 'create_complaint'),
    ('SC36', {'phone': '+77071234567', 'callback_time': '2026-10-02 14:00'}, 'completed', 'create_callback'),
    ('SC37', {}, 'handoff', None),
    ('SC38', {'fraud_details': 'Suspicious call'}, 'completed', 'report_fraud'),
    ('SC39', {'policy_number': 'SQ-OGPO-104501', 'document_type': 'contract_copy',
              'email': 'test@example.com'}, 'completed', 'request_document'),
    ('SC40', {'topic': 'franchise'}, 'completed', 'kb_lookup'),
]


def test_matrix_covers_catalog(catalog):
    ids = [scenario_id for scenario_id, *_ in CASES]
    assert len(ids) == len(set(ids)) == 40
    assert set(ids) == set(catalog.scenarios)


@pytest.mark.parametrize('scenario_id,slots,expected_status,expected_action', CASES,
                         ids=[row[0] for row in CASES])
def test_scenario_path(scenario_id, slots, expected_status, expected_action, catalog, backend):
    state = Dialogue()
    executor = Executor(catalog, backend)
    before = copy.deepcopy(backend.data)
    result = executor.process(decision(scenario_id, slots, needs_operator=scenario_id == 'SC11'), state, 'fixture request')

    if scenario_id != 'SC37':
        assert state.active.scenario_id == scenario_id
    assert result['status'] == expected_status
    if expected_action:
        assert any(a['name'] == expected_action for a in result['actions']), result
    if expected_status == 'collecting':
        assert result['question'] and state.active.waiting_slot
    if expected_status == 'action_error':
        assert result['actions'][-1]['mode'] == 'error'
        assert backend.data == before
    if scenario_id == 'SC16':
        assert result['actions'][-1]['error']['code'] == 'not_covered'
    if scenario_id == 'SC05':
        assert result['actions'][-1]['error']['code'] == 'not_eligible'
    if expected_status == 'confirmation':
        assert result['actions'][-1]['mode'] == 'preview'
        assert backend.data == before, 'preview must not change session data'
        assert backend.bookings == set(), 'preview must not reserve an appointment'
        assert not any(a['action'] == expected_action for a in backend.audit)
        confirmed = executor.process(decision(scenario_id, continuation=True), state, 'да')
        assert confirmed['status'] == 'completed', confirmed
        assert any(a['name'] == expected_action and a['mode'] == 'execute' for a in confirmed['actions'])
        assert sum(a['action'] == expected_action for a in backend.audit) == 1
        outcome = confirmed['facts'][expected_action]
        if expected_action in ('create_policy', 'renew_policy'):
            assert sum(p['policy_number'] == outcome['policy_number'] for p in backend.data['policies']) == 1
        if expected_action == 'create_claim':
            assert sum(c['claim_number'] == outcome['claim_number'] for c in backend.data['claims']) == 1
        if expected_action in ('book_inspection', 'book_appointment'):
            assert len(backend.bookings) == 1
            assert outcome['slot_datetime'].startswith('2026-10-02T')
        if expected_action == 'update_contact':
            assert backend.data['clients'][0]['address'] == 'New test address'
        if expected_action == 'update_policy':
            policy = next(p for p in backend.data['policies'] if p['policy_number'] == 'SQ-OGPO-105120')
            assert '880126300907' in policy['details']['drivers_iin']
    if scenario_id == 'SC01':
        assert result['facts']['calc_ogpo_price']['price'] == 38000
    if scenario_id == 'SC28':
        assert confirmed['facts']['cancel_policy']['refund_amount'] == 163800
    if scenario_id == 'SC30':
        assert result['facts']['handoff']['real_transfer'] is False
    if scenario_id == 'SC37':
        assert result['facts']['real_transfer'] is False
    if scenario_id in ('SC10', 'SC15'):
        assert result['facts']['transfer_to_operator']['real_transfer'] is False
        expected_queue = 'corporate_sales' if scenario_id == 'SC10' else 'medical_assistance_24_7'
        assert result['facts']['transfer_to_operator']['queue'] == expected_queue
    if scenario_id == 'SC11':
        assert result['facts']['transfer_to_operator']['queue'] == 'claims_team'
        assert 'kb_lookup' in result['facts']


@pytest.mark.parametrize('intent', ['SYS_OUT_OF_SCOPE', 'SYS_UNCLEAR', 'SYS_GOODBYE'])
def test_system_intent_does_not_run_business_action(intent, catalog, backend):
    result = Executor(catalog, backend).process(decision(intent), Dialogue(), 'test')
    assert result['status'] == 'system'
    assert result['question']
    assert result['actions'] == []
    assert backend.audit == []
