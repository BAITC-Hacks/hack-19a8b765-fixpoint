import asyncio
from types import SimpleNamespace

from app.core.context import Dialogue, Frame
from app.core.executor import Executor
from app.core.identifiers import (extract_claim_numbers, extract_iins,
                                  extract_plates, extract_policy_numbers)
from app.core.models import Candidate, RoutingDecision
from app.core.router import Router


def test_exact_user_transcript_becomes_twelve_digits():
    text = 'Девяносто один ноль пять двенадцать, тридцать ноль четыре пятьдесят шесть.'
    assert extract_iins(text) == ['910512300456']


def test_ru_kk_digit_words_and_digit_groups():
    assert extract_iins('девять один ноль пять один два три ноль ноль четыре пять шесть') == ['910512300456']
    assert extract_iins('тоғыз бір нөл бес бір екі үш нөл нөл төрт бес алты') == ['910512300456']
    assert extract_iins('тогуз бир нөл беш бир эки үч нөл нөл төрт беш алты') == ['910512300456']
    assert extract_iins('тоқсан бір нөл бес он екі отыз нөл төрт елу алты') == ['910512300456']
    assert extract_iins('ИИН 9105 1230 0456') == ['910512300456']


def test_missing_digit_is_never_padded_and_two_drivers_remain_separate():
    assert extract_iins('ИИН 91051230045') == []
    assert extract_iins('мой 910512300456 и супруги 930824400789') == ['910512300456', '930824400789']


def test_spoken_and_written_vehicle_plates():
    assert extract_plates('Четыреста восемьдесят два КМА ноль два.') == ['482KMA02']
    assert extract_plates('482KMA02') == ['482KMA02']
    assert extract_plates('Номер 482 К М А 02') == ['482KMA02']
    assert extract_plates('Номер 482 ка эм а 02') == ['482KMA02']
    assert extract_plates('Номер 482 KM A 02') == ['482KMA02']
    assert extract_plates('Госномер 777 АВС 02') == ['777ABC02']
    assert extract_plates('Көліктің нөмірі төрт жүз сексен екі KMA нөл екі') == ['482KMA02']
    assert extract_plates('482 КМА ноль') == []
    assert extract_plates('482 K ман 02') == []


def test_waiting_plate_uses_transcript_over_model_guess(catalog):
    state = Dialogue(active=Frame('SC02', waiting_slot='vehicle_plate'))
    route = Router(catalog, StubLLM('SC02', {'vehicle_plate': '777ABC02'}))
    decision = asyncio.run(route.route('Четыреста восемьдесят два КМА ноль два.', state))
    assert decision.scenarios[0].slots['vehicle_plate'] == '482KMA02'


def test_incomplete_plate_cannot_be_repaired_by_model(catalog):
    state = Dialogue(active=Frame('SC02', waiting_slot='vehicle_plate'))
    route = Router(catalog, StubLLM('SC02', {'vehicle_plate': '482KMA02'}))
    decision = asyncio.run(route.route('Четыреста восемьдесят два КМА ноль.', state))
    assert 'vehicle_plate' not in decision.scenarios[0].slots


def test_culprit_plate_keeps_its_distinct_role(catalog):
    state = Dialogue(active=Frame('SC12', waiting_slot='culprit_vehicle_plate'))
    route = Router(catalog, StubLLM('SC12', {'culprit_vehicle_plate': '777ABC02'}))
    decision = asyncio.run(route.route('Госномер виновника 482 КМА 02', state))
    assert decision.scenarios[0].slots == {'culprit_vehicle_plate': '482KMA02'}


def test_spoken_policy_and_claim_references_are_complete():
    assert extract_policy_numbers('Полис SQ-OGPO-104501') == ['SQ-OGPO-104501']
    assert extract_policy_numbers('Полис эс кью огпо один ноль четыре пять ноль один') == ['SQ-OGPO-104501']
    assert extract_policy_numbers('Полис S Q ОГПО один ноль четыре пять ноль один') == ['SQ-OGPO-104501']
    assert extract_policy_numbers('Полис S Q O G P O один ноль четыре пять ноль один') == ['SQ-OGPO-104501']
    assert extract_policy_numbers('Полис эс кью о гэ пэ о один ноль четыре пять ноль один') == ['SQ-OGPO-104501']
    assert extract_policy_numbers('Полис SQ OGP O один ноль четыре пять ноль один') == ['SQ-OGPO-104501']
    assert extract_policy_numbers('Полис SQ-OGPO-10450') == []
    assert extract_policy_numbers('Полис SQ ОГПА 104501') == []
    assert extract_claim_numbers('Заявление CL-500287') == ['CL-500287']
    assert extract_claim_numbers('Заявление си эл пять ноль ноль два восемь семь') == ['CL-500287']
    assert extract_claim_numbers('Заявление C L пять ноль ноль два восемь семь') == ['CL-500287']
    assert extract_claim_numbers('Номер заявления 500287', allow_bare=True) == ['CL-500287']
    assert extract_claim_numbers('Номер заявления 50028', allow_bare=True) == []


def test_waiting_claim_cannot_accept_a_guessed_final_digit(catalog):
    state = Dialogue(active=Frame('SC17', waiting_slot='claim_number'))
    route = Router(catalog, StubLLM('SC17', {'claim_number': 'CL-500287'}))
    decision = asyncio.run(route.route('Номер заявления пять ноль ноль два восемь', state))
    assert 'claim_number' not in decision.scenarios[0].slots


def test_waiting_policy_uses_spelled_prefix_and_product(catalog):
    state = Dialogue(active=Frame('SC04', waiting_slot='policy_number'))
    route = Router(catalog, StubLLM('SC04', {'policy_number': 'SQ-OGPO-104502'}))
    decision = asyncio.run(route.route('Полис S Q O G P O один ноль четыре пять ноль один', state))
    assert decision.scenarios[0].slots['policy_number'] == 'SQ-OGPO-104501'


class StubLLM:
    settings = SimpleNamespace(provider='openai')

    def __init__(self, scenario, slots):
        self.scenario = scenario
        self.slots = slots

    async def structured(self, _prompt, _payload, _schema):
        return RoutingDecision(
            scenarios=[Candidate(scenario_id=self.scenario, confidence=.95, reason='test', slots=self.slots)],
            language='ru', response_language='ru', reason='test',
        )


def test_waiting_iin_uses_exact_transcript_over_model_guess(catalog):
    state = Dialogue(active=Frame('SC01', waiting_slot='drivers_iin'))
    text = 'Девяносто один ноль пять двенадцать, тридцать ноль четыре пятьдесят шесть.'
    route = Router(catalog, StubLLM('SC01', {'drivers_iin': ['910512300455']}))
    decision = asyncio.run(route.route(text, state))
    assert decision.scenarios[0].slots['drivers_iin'] == ['910512300456']


def test_spoken_iin_completes_existing_ogpo_quote(catalog, backend):
    state = Dialogue(active=Frame('SC01', slots={'region': 'almaty', 'vehicle_type': 'car'},
                                  waiting_slot='drivers_iin'))
    text = 'Девяносто один ноль пять двенадцать, тридцать ноль четыре пятьдесят шесть.'
    route = Router(catalog, StubLLM('SC01', {}))
    decision = asyncio.run(route.route(text, state))
    result = Executor(catalog, backend).process(decision, state, text)
    assert result['status'] == 'completed'
    assert result['facts']['calc_ogpo_price']['price'] == 38000
    assert state.active.slots['drivers_iin'] == ['910512300456']


def test_incomplete_transcript_cannot_be_repaired_by_model(catalog):
    state = Dialogue(active=Frame('SC01', waiting_slot='drivers_iin'))
    route = Router(catalog, StubLLM('SC01', {'drivers_iin': ['910512300456']}))
    decision = asyncio.run(route.route('ИИН 91051230045', state))
    assert 'drivers_iin' not in decision.scenarios[0].slots


def test_explicit_iin_on_first_turn_is_available_to_matching_scenario(catalog):
    route = Router(catalog, StubLLM('SC32', {}))
    decision = asyncio.run(route.route('Мой ИИН 910512300456, какой у меня класс?', Dialogue()))
    assert decision.scenarios[0].slots['iin'] == '910512300456'
