import asyncio
from types import SimpleNamespace

from app.core.context import Dialogue, Frame
from app.core.executor import Executor
from app.core.identifiers import extract_iins
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
