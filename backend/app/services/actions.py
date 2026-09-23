"""Session-local synthetic backend. Never contacts a bank or sends real messages."""
import copy
import json
from pathlib import Path
import re
from datetime import date, timedelta
from uuid import uuid4

class ActionError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)

def fail(code, message):
    raise ActionError(code, message)

class MockBackend:
    def __init__(self, catalog):
        self.catalog = catalog
        self.data = copy.deepcopy(catalog.raw['mock_backend'])
        self.kb, self.today = catalog.kb, catalog.as_of
        self.audit = []
        self.operations = {}
        self.schedule = json.loads((Path(__file__).resolve().parents[2] / 'fixtures' / 'schedule.json').read_text(encoding='utf-8'))
        self.bookings = set()

    def identify(self, slots):
        owners = {c['client_id'] for c in self.data['clients']
                  if any(slots.get(k) == c[k] for k in ('phone','iin'))}
        policy = next((p for p in self.data['policies'] if p['policy_number'] == slots.get('policy_number')), None)
        claim = next((c for c in self.data['claims'] if c['claim_number'] == slots.get('claim_number')), None)
        owners.update(x['client_id'] for x in (policy, claim) if x and x.get('client_id'))
        if len(owners) > 1:
            fail('invalid_input', 'Идентификаторы относятся к разным клиентам. Уточните данные заявителя.')
        owner = next(iter(owners), None)
        return next((copy.deepcopy(c) for c in self.data['clients'] if c['client_id'] == owner), None)

    def policy(self, s, active=False):
        matches = [p for p in self.data['policies'] if (s.get('policy_number') and p['policy_number'] == s['policy_number'])
                   or (not s.get('policy_number') and s.get('vehicle_plate') and p['details'].get('vehicle_plate') == s['vehicle_plate'])]
        if not s.get('policy_number') and s.get('product_type'):
            matches = [p for p in matches if p['product'] == s['product_type']]
        if not matches:
            fail('not_found', 'Полис не найден.')
        if len(matches) > 1:
            fail('invalid_input', 'На автомобиль найдено несколько полисов; уточните номер полиса.')
        p = matches[0]
        if s.get('client_id') and p['client_id'] != s['client_id']:
            fail('not_found', 'Полис не принадлежит выбранному клиенту.')
        if active and (p.get('status') == 'cancelled' or not p['start_date'] <= str(self.today) <= p['end_date']):
            fail('policy_inactive', 'Полис не действует на дату среза данных.')
        return p

    def claim(self, s):
        rows = [c for c in self.data['claims'] if c['claim_number'] == s.get('claim_number') or
                (not s.get('claim_number') and s.get('client_id') and c['client_id'] == s['client_id'])]
        if len(rows) != 1:
            fail('not_found', 'Уточните номер страхового случая.')
        if s.get('client_id') and rows[0]['client_id'] != s['client_id']:
            fail('not_found', 'Страховой случай не принадлежит выбранному клиенту.')
        return rows[0]

    def bm(self, iin):
        if not re.fullmatch(r'\d{12}', str(iin)):
            fail('invalid_input', 'ИИН должен содержать 12 цифр.')
        return next((c['bm_class'] for c in self.data['clients'] if c['iin'] == iin), self.data['defaults']['unknown_iin_bm_class'])

    def price(self, product, s):
        k = self.kb['products'][product]
        if product == 'ogpo':
            p = k['pricing']
            coef = max(p['bm_coef'][str(self.bm(i))] for i in s['drivers_iin'])
            return {'price': round(p['base_by_region_kzt'][s['region']] * p['vehicle_type_coef'][s['vehicle_type']] * coef * p['term_coef'][str(s.get('term_months', 12))])}
        if product == 'casco':
            p, age = k['pricing'], self.today.year - s['car_year']
            package = s.get('package', 'Standard')
            if age < 0 or age > p['max_car_age'][package]:
                fail('not_eligible', 'Возраст автомобиля не подходит для выбранного пакета.')
            if age > 10:
                fail('not_eligible', 'В наборе нет ставки для автомобиля старше 10 лет; нужен оператор.')
            rate = p['rate_by_car_age']['0-3' if age <= 3 else '4-7' if age <= 7 else '8-10']
            return {'price': round(s['car_value'] * rate * p['franchise_coef'][str(s.get('franchise', 0))] * p['package_coef'][package])}
        if product in ('property', 'accident'):
            price = k['price_per_year_kzt'].get(str(s['sum_insured']))
            if price is None:
                fail('invalid_input', 'Для этого продукта выберите сумму из доступных в базе знаний.')
            return {'price': round(price * (k['house_coef'] if product == 'property' and s['property_type'] == 'house' else 1))}
        if product == 'travel':
            countries = {'russia':'A','россия':'A','ресей':'A','georgia':'A','грузия':'A','uzbekistan':'A','узбекистан':'A',
                         'germany':'B','германия':'B','france':'B','франция':'B','italy':'B','италия':'B','spain':'B','испания':'B','uk':'B','великобритания':'B',
                         'turkey':'C','турция':'C','түркия':'C','uae':'C','оаэ':'C','баә':'C','thailand':'C','таиланд':'C','egypt':'C','египет':'C',
                         'usa':'D','сша':'D','ақш':'D','canada':'D','канада':'D'}
            zone = countries.get(s['trip_country'].strip().lower())
            if zone is None:
                fail('not_eligible', 'Для этой страны зону покрытия должен уточнить оператор.')
            age = s['traveler_max_age']
            if age > 75:
                fail('not_eligible', 'Страхование путешественника старше 75 лет оформляет оператор.')
            days = (date.fromisoformat(s['trip_end']) - date.fromisoformat(s['trip_start'])).days + 1
            if days < 1 or s['travelers_count'] < 1 or age < 0:
                fail('invalid_input', 'Проверьте даты, возраст и количество путешественников.')
            z = k['zones'][zone]
            return {'price': round(z['rate_per_day_kzt'] * days * s['travelers_count'] * (2 if age >= 65 else 1)), 'zone': zone, 'coverage': z['coverage']}
        fail('not_eligible', 'Для расчёта этого продукта нужен оператор.')

    def run(self, name, s, *, confirmed=False, preview=False, operation_id=None):
        definition = self.catalog.actions[name]
        if definition['irreversible'] and not (confirmed or preview):
            fail('confirmation_required', 'Требуется явное подтверждение клиента.')
        if operation_id and operation_id in self.operations:
            prior = self.operations[operation_id]
            if prior['name'] != name or prior['slots'] != s:
                fail('invalid_input', 'Параметры уже выполненной операции изменились.')
            return copy.deepcopy(prior['result'])
        if preview:
            trial = copy.deepcopy(self)
            result = trial.run(name, s, confirmed=True)
            return {'preview': True, 'action': name, 'result': result}
        try:
            result = self._dispatch(name, s)
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as e:
            raise ActionError('invalid_input', 'Недостаточно или неверно заполнены параметры действия.') from e
        self.audit.append({'action': name, 'result': copy.deepcopy(result)})
        if operation_id:
            self.operations[operation_id] = {'name':name,'slots':copy.deepcopy(s),'result':copy.deepcopy(result)}
        return result

    def _dispatch(self, name, s):
        if name == 'find_client':
            c = self.identify(s)
            if not c:
                fail('not_found', 'Клиент не найден.')
            return {'client_id': c['client_id'], 'full_name': c['full_name']}
        if name == 'get_policies':
            return {'policies': [copy.deepcopy(p) for p in self.data['policies'] if p['client_id'] == s['client_id']]}
        if name == 'get_policy':
            p = copy.deepcopy(self.policy(s))
            p['status'] = p.get('status', 'active' if p['start_date'] <= str(self.today) <= p['end_date'] else 'inactive')
            return p
        if name == 'get_bm_class':
            return {'bm_class': self.bm(s.get('new_driver_iin') or s.get('iin') or s['drivers_iin'][0])}
        if name.startswith('calc_'):
            return self.price(name.removeprefix('calc_').removesuffix('_price'), s)
        if name == 'kb_lookup':
            return {'facts': self.kb, 'topic': s.get('topic', s.get('product_type', 'company'))}
        if name in ('get_offices', 'list_clinics'):
            key = 'offices' if name == 'get_offices' else 'clinics'
            rows = [r for r in self.kb[key] if r['city'].lower() == s['city'].lower()]
            if not rows:
                fail('not_found', 'Для этого города нет записей в базе знаний.')
            return {key: rows}
        if name == 'get_claim':
            return copy.deepcopy(self.claim(s))
        if name == 'check_payment':
            rows = [p for p in self.data['payments'] if p['client_id'] == s['client_id'] and p['date'] == s['payment_date']]
            if not rows:
                fail('not_found', 'Платёж за указанную дату не найден.')
            return {'payments': rows}
        if name == 'check_coverage':
            p = self.policy(s, active=True)
            if p['product'] != 'dms':
                fail('invalid_input', 'Нужен полис ДМС.')
            # Natural-language interpretation belongs to the response LLM, bounded by these facts.
            return {'package': p['details']['package'], 'requested_service': s['service_name'],
                    'coverage_rules': self.kb['products']['dms']['packages'][p['details']['package']]}
        if name == 'create_policy':
            product = s['product_type']
            prefixes = {'ogpo':'OGPO','casco':'CASCO','travel':'TRVL','property':'PROP','accident':'NS','dms':'DMS'}
            number = self.new_id('SQ-' + prefixes[product] + '-', 'policies', 'policy_number')
            price = self.price(product, s)
            p = {'policy_number': number, 'client_id': s.get('client_id'), 'product': product,
                 'status': 'awaiting_payment', 'start_date': str(self.today), 'end_date': str(self.today + timedelta(days=364)),
                 'premium': price['price'], 'details': copy.deepcopy(s)}
            if product == 'travel':
                p.update(start_date=s['trip_start'], end_date=s['trip_end'])
            self.data['policies'].append(p)
            return {'policy_number': number, **price, 'status': 'awaiting_payment', 'delivery': 'mock_sms'}
        if name == 'renew_policy':
            p = self.policy(s)
            values = {**p['details'], 'product_type': p['product']}
            values.setdefault('region', self.kb['products']['ogpo']['pricing']['region_by_plate_code'].get(values.get('vehicle_plate','')[-2:], 'other'))
            price = self.price(p['product'], values)
            new = copy.deepcopy(p)
            new['policy_number'] = self.new_id('-'.join(p['policy_number'].split('-')[:2]) + '-', 'policies', 'policy_number')
            start = max(self.today, date.fromisoformat(p['end_date']) + timedelta(days=1))
            new.update(start_date=str(start), end_date=str(start + timedelta(days=364)), premium=price['price'], status='awaiting_payment')
            self.data['policies'].append(new)
            return {'policy_number': new['policy_number'], **price, 'status': 'awaiting_payment'}
        if name == 'update_policy':
            p = self.policy(s, active=True)
            if s.get('new_driver_iin'):
                drivers = list(dict.fromkeys(p['details'].get('drivers_iin', []) + [s['new_driver_iin']]))
                pricing = self.kb['products']['ogpo']['pricing']['bm_coef']
                old_coef = max(pricing[str(self.bm(i))] for i in p['details'].get('drivers_iin', [])) if p['product']=='ogpo' else None
                new_coef = max(pricing[str(self.bm(i))] for i in drivers)
                if old_coef is None or new_coef != old_coef:
                    fail('not_eligible', 'Изменение тарифа требует перерасчёта оператором: правило доплаты в наборе не задано.')
                p['details']['drivers_iin'] = drivers
                return {'extra_premium': 0, 'note':'Тарифный коэффициент не изменился.'}
            if s.get('vehicle_plate'):
                fail('not_eligible', 'Для смены автомобиля нужен перерасчёт оператором: правила изменения премии в наборе не заданы.')
            fail('invalid_input', 'Не указано изменение полиса.')
        if name == 'cancel_policy':
            p = self.policy(s)
            if p.get('status') == 'cancelled':
                fail('already_done', 'Полис уже расторгнут.')
            self.policy(s, active=True)
            if any(c['policy_number'] == p['policy_number'] and c['status'] == 'paid' for c in self.data['claims']):
                fail('not_eligible', 'По полису уже была выплата; возврат не предусмотрен.')
            end = date.fromisoformat(p['end_date']) + timedelta(days=1)
            months = max(0, (end.year-self.today.year)*12 + end.month-self.today.month - (end.day < self.today.day))
            refund = round((p['premium'] or 0) * min(months,12) / 12 * .9)
            p['status'] = 'cancelled'
            return {'refund_amount': refund, 'refund_time': self.kb['cancellation']['refund_time']}
        if name == 'create_claim':
            lookup = {k:v for k,v in s.items() if k != 'client_id'} if s.get('culprit_vehicle_plate') else s
            policy = self.policy(lookup) if s.get('policy_number') else None
            if policy and policy['product'] != s['product_type']:
                fail('not_covered', 'Тип полиса не соответствует заявленному страховому случаю.')
            if policy and not policy['start_date'] <= s['incident_date'] <= policy['end_date']:
                fail('policy_inactive', 'Полис не действовал на дату происшествия.')
            number = self.new_id('CL-', 'claims', 'claim_number')
            claim = {'claim_number': number, 'client_id': s.get('client_id'), 'policy_number': policy['policy_number'] if policy else None,
                     'claim_type': 'ogpo_victim' if s.get('culprit_vehicle_plate') else s['product_type'], 'incident_date': s['incident_date'], 'status': 'registered',
                     'description': s['incident_description'], 'next_step': self.kb['claims']['submission']}
            self.data['claims'].append(claim)
            return copy.deepcopy(claim)
        if name == 'create_dispute':
            self.claim(s)
            return {'ticket_id': 'DS-' + uuid4().hex[:8], 'status': 'registered', 'review': self.kb['claims']['dispute']}
        if name in ('book_inspection', 'book_appointment'):
            if name == 'book_inspection':
                self.claim(s)
                candidates = [r for r in self.kb['inspection_points'] if r['city'] in (s['city'], 'other')]
            else:
                p = self.policy(s, active=True)
                if p['product'] != 'dms':
                    fail('not_covered', 'Запись доступна по ДМС.')
                specialty = s['doctor_specialty'].lower()
                if specialty != 'therapist':
                    # Dataset has no referral records. Never fabricate eligibility.
                    fail('not_eligible', 'Для проверки направления и покрытия выбранного специалиста нужен оператор.')
                candidates = [c for c in self.kb['clinics'] if c['city'] == s['city'] and specialty in c['specialties']]
            if not candidates:
                fail('no_availability', 'В наборе нет подходящей записи; предложите оператора.')
            c = candidates[0]
            resource = c.get('name', c['address']) + ':' + s.get('doctor_specialty','inspection')
            available = [f'{day}T{time}' for day in self.schedule['dates'] for time in self.schedule['times']
                         if (resource,f'{day}T{time}') not in self.bookings]
            selected = next((slot for slot in available if slot.startswith(s['preferred_date']+'T')), None)
            if not selected:
                fail('no_availability', 'Нет записи на эту дату. Свободные варианты демо: ' + ', '.join(available[:3]))
            self.bookings.add((resource,selected))
            return {'slot_datetime':selected, 'address': c['address'], 'clinic_name': c.get('name'), 'mock_schedule': True}
        if name == 'update_contact':
            client = next((c for c in self.data['clients'] if c['client_id'] == s['client_id']), None)
            if not client:
                fail('not_found', 'Клиент не найден.')
            key, value = s['contact_field'], s['new_value']
            if key not in ('phone','email','address'):
                fail('invalid_input', 'Неизвестное поле контакта.')
            pattern = self.catalog.slots.get(key, {}).get('pattern')
            if pattern and not re.fullmatch(pattern, value):
                fail('invalid_input', 'Неверный формат новых контактных данных.')
            client[key] = value
            return {'updated': key}
        if name in ('resend_documents', 'request_document'):
            p = self.policy(s)
            c = next((c for c in self.data['clients'] if c['client_id'] == p['client_id']), {})
            return {'sent_to': s.get('email') or c.get('email') or s.get('phone'), 'delivery': 'simulated_only'}
        if name in ('send_sms', 'create_callback'):
            if not re.fullmatch(r'\+7\d{10}', s['phone']):
                fail('invalid_input', 'Неверный номер телефона.')
            return {'status': 'simulated_only', 'callback_time': s.get('callback_time')}
        if name in ('create_complaint','report_fraud'):
            return {'ticket_id': 'TK-' + uuid4().hex[:8], 'status': 'registered_in_demo'}
        if name == 'transfer_to_operator':
            if s['queue'] not in self.catalog.raw['actions']['queues']:
                fail('invalid_input', 'Неизвестная очередь оператора.')
            return {'queue': s['queue'], 'summary': s.get('summary', {}), 'status': 'handoff_prepared', 'real_transfer': False}
        fail('invalid_input', 'Действие не поддерживается.')

    def new_id(self, prefix, collection, key):
        existing = {r[key] for r in self.data[collection]}
        for n in range(900000, 1000000):
            value = prefix + str(n)
            if value not in existing:
                return value
        fail('service_unavailable', 'Закончился диапазон тестовых идентификаторов.')
