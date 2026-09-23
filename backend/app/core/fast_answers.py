"""Short factual answers for completed, single-action read-only turns."""

import re


CITY_NAMES = {
    'Almaty': ('Алматы', 'Алматы'),
    'Astana': ('Астане', 'Астанадағы'),
    'Shymkent': ('Шымкенте', 'Шымкенттегі'),
    'Karaganda': ('Караганде', 'Қарағандыдағы'),
    'Aktobe': ('Актобе', 'Ақтөбедегі'),
    'Atyrau': ('Атырау', 'Атыраудағы'),
    'Pavlodar': ('Павлодаре', 'Павлодардағы'),
    'Oskemen': ('Усть-Каменогорске', 'Өскемендегі'),
}


def factual_answer(result, state, user_text):
    """Return None whenever a response needs interpretation or dialogue control."""
    if result.get('status') != 'completed' or result.get('next_scenario'):
        return None
    actions = result.get('actions') or []
    if not actions or any(action.get('mode') != 'execute' for action in actions):
        return None
    action_names = [action.get('name') for action in actions]
    facts = result.get('facts') or {}
    language = state.language
    if action_names == ['get_bm_class', 'calc_ogpo_price']:
        quote = facts.get('calc_ogpo_price') or {}
        price = quote.get('price')
        if not isinstance(price, int) or price < 0:
            return None
        term = (state.active.slots if state.active else {}).get('term_months', 12)
        if term not in (6, 12):
            return None
        amount = f'{price:,}'.replace(',', ' ')
        return (f'ОГПО на {term} месяцев стоит {amount} тенге.' if language == 'ru'
                else f'ОГПО сақтандыруының {term} айға бағасы — {amount} теңге.')
    if action_names == ['get_offices']:
        rows = (facts.get('get_offices') or {}).get('offices') or []
        if len(rows) != 1:
            return None
        office = rows[0]
        names = CITY_NAMES.get(office.get('city'))
        if not names or not office.get('address'):
            return None
        if language == 'ru':
            answer = f'Офис в {names[0]}: {office["address"]}.'
        else:
            answer = f'{names[1]} кеңсенің мекенжайы: {office["address"]}.'
        if re.search(r'час|график|расписан|работа|откры|закры|когда|во сколько|уақыт|сағат|қашан|жұмыс|ашық|жабық|hours|open', user_text, re.I):
            hours = office.get('hours')
            if not hours:
                return None
            answer += (' Часы работы: ' if language == 'ru' else ' Жұмыс уақыты: ') + hours + '.'
        return answer
    return None
