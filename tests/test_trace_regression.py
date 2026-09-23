"""Regressions reproduced from the six-turn SC02 voice trace."""

import asyncio
from types import SimpleNamespace

from app.core.context import Dialogue, Frame
from app.core.engine import Engine
from app.core.executor import Executor, closing_reply, explicit_reply
from app.core.identifiers import extract_phones
from app.core.models import Candidate, RoutingDecision
from app.core.router import Router


class StubLLM:
    settings = SimpleNamespace(provider='openai')

    def __init__(self, decision):
        self.decision = decision

    async def structured(self, *_args):
        return self.decision


def decision(slots=None, *, continuation=False):
    return RoutingDecision(
        scenarios=[Candidate(scenario_id='SC02', confidence=.9, reason='Оформление ОГПО.', slots=slots or {})],
        language='ru', response_language='ru', reason='', is_continuation=continuation,
    )


def test_spoken_phone_must_be_complete_and_match_transcript():
    assert extract_phones('Плюс семь, семьсот один, ноль ноль ноль, ноль ноль ноль.') == []
    assert extract_phones('Плюс семь, семьсот один, ноль ноль ноль, ноль ноль ноль два.') == ['+77010000002']
    assert extract_phones('Мой телефон 8 701 000 00 02') == ['+77010000002']
    assert extract_phones('Номер 701 000 00 02') == ['+77010000002']
    assert extract_phones('Телефон +77010000002') == ['+77010000002']


def test_incomplete_phone_cannot_reach_policy_preview(catalog, backend):
    state = Dialogue(active=Frame('SC02', slots={
        'vehicle_plate': '482KMA02', 'drivers_iin': ['920607400233'], 'vehicle_type': 'car',
    }, waiting_slot='phone'))
    text = 'Плюс семь, семьсот один, ноль ноль ноль, ноль ноль ноль.'
    route = Router(catalog, StubLLM(decision({'phone': '+77710100000'}, continuation=True)))
    routed = asyncio.run(route.route(text, state))
    assert 'phone' not in routed.scenarios[0].slots
    result = Executor(catalog, backend).process(routed, state, text)
    assert result['status'] == 'collecting'
    assert state.active.waiting_slot == 'phone'
    assert not result['actions']
    assert len(backend.data['policies']) == len(catalog.raw['mock_backend']['policies'])


def test_complete_phone_links_existing_client_before_confirmation(catalog, backend):
    state = Dialogue(active=Frame('SC02', slots={
        'vehicle_plate': '482KMA02', 'drivers_iin': ['920607400233'], 'vehicle_type': 'car',
    }, waiting_slot='phone'))
    text = 'Плюс семь, семьсот один, ноль ноль ноль, ноль ноль ноль два.'
    route = Router(catalog, StubLLM(decision({'phone': '+77710100000'}, continuation=True)))
    routed = asyncio.run(route.route(text, state))
    assert routed.scenarios[0].slots['phone'] == '+77010000002'
    result = Executor(catalog, backend).process(routed, state, text)
    assert result['status'] == 'confirmation'
    assert state.client['client_id'] == 'C002'
    assert state.active.slots['client_id'] == 'C002'
    assert len(backend.data['policies']) == len(catalog.raw['mock_backend']['policies'])


def test_continuation_cannot_reopen_completed_purchase(catalog, backend):
    slots = {'vehicle_plate': '482KMA02', 'drivers_iin': ['920607400233'],
             'phone': '+77010000002', 'vehicle_type': 'car'}
    state = Dialogue(active=Frame('SC02', slots=slots.copy(), done=True))
    result = Executor(catalog, backend).process(decision(slots, continuation=True), state, 'Всё хорошо, спасибо.')
    assert result['status'] == 'completed'
    assert not result['actions']
    assert state.active.done
    assert len(backend.data['policies']) == len(catalog.raw['mock_backend']['policies'])


def test_refusal_after_preview_does_not_create_a_policy(catalog, backend):
    slots = {'vehicle_plate': '482KMA02', 'drivers_iin': ['920607400233'],
             'phone': '+77010000002', 'vehicle_type': 'car'}
    state = Dialogue()
    executor = Executor(catalog, backend)
    preview = executor.process(decision(slots), state, 'Хочу оформить ОГПО')
    assert preview['status'] == 'confirmation'
    before = len(backend.data['policies'])
    refused = executor.process(decision(continuation=True), state, 'Я не подтверждаю.')
    assert refused['status'] == 'cancelled'
    assert not refused['actions']
    assert len(backend.data['policies']) == before


def test_closing_gratitude_and_explicit_refusal_are_dialogue_rules(catalog):
    assert closing_reply('Всё хорошо, спасибо.')
    assert not closing_reply('Спасибо, а сколько стоит КАСКО?')
    assert explicit_reply('Я не подтверждаю.') == 'no'
    assert explicit_reply('Я не согласна.') == 'no'

    class NeverLLM:
        settings = SimpleNamespace(provider='openai')

        async def structured(self, *_args):
            raise AssertionError('A completed goodbye must not call the LLM')

    engine = Engine(catalog, NeverLLM())
    engine.state.active = Frame('SC02', done=True)

    async def collect():
        return [event async for event in engine.run('Всё хорошо, спасибо.', speak=False)]

    events = asyncio.run(collect())
    route = next(event for event in events if event['event'] == 'routing_decision')
    assert route['scenarios'][0]['scenario_id'] == 'SYS_GOODBYE'
    assert route['routing_source'] == 'dialogue_rule'
    assert not next(event for event in events if event['event'] == 'execution_trace')['execution']['actions']


def test_model_unclear_does_not_become_second_intent_during_slot_reply(catalog):
    state = Dialogue(active=Frame('SC02', waiting_slot='drivers_iin'))
    model = decision({'drivers_iin': ['920607400233']}, continuation=True)
    model.scenarios.append(Candidate(scenario_id='SYS_UNCLEAR', confidence=.7,
                                     reason='Digits were unclear.', slots={'drivers_iin': []}))
    routed = asyncio.run(Router(catalog, StubLLM(model)).route(
        'девяносто два ноль шесть ноль семь сорок ноль два тридцать три', state))
    assert [candidate.scenario_id for candidate in routed.scenarios] == ['SC02']
    assert routed.reason == 'Оформление ОГПО.'
