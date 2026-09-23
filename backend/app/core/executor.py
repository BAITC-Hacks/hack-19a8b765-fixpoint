import copy
import re
from uuid import uuid4
from .context import Frame
from .slots import validate_slots
from ..services.actions import ActionError

YES = {'да', 'да подтверждаю', 'подтверждаю', 'согласен', 'согласна', 'иә', 'растаймын', 'иә растаймын',
       'да верно', 'верно', 'да оформляйте', 'да регистрируйте', 'иә тіркеңіз', 'иә жазыңыз'}
NO = {'нет', 'не подтверждаю', 'я не подтверждаю', 'не согласен', 'не согласна',
      'я не согласен', 'я не согласна', 'отмена', 'жоқ', 'бас тартамын'}
CLOSING = {'всё хорошо спасибо', 'все хорошо спасибо', 'спасибо до свидания',
           'до свидания', 'пока', 'рақмет сау болыңыз', 'рахмет сау болыңыз', 'сау болыңыз'}

def closing_reply(text):
    return ' '.join(re.sub(r'[^\w\s]', '', text.lower()).split()) in CLOSING

def explicit_reply(text):
    value = ' '.join(re.sub(r'[^\w\s]', '', text.lower()).split())
    return 'yes' if value in YES else 'no' if value in NO else None

class Executor:
    def __init__(self, catalog, backend):
        self.c, self.backend = catalog, backend

    def question(self, key, lang):
        return self.c.slots[key]['prompt'][lang]

    def run_action(self, name, slots, **kwargs):
        for attempt in range(2):
            try:
                return self.backend.run(name, slots, **kwargs)
            except ActionError as exc:
                if exc.code != 'service_unavailable' or attempt:
                    raise

    def handoff(self, state, queue='operator_general'):
        summary = {**state.public(), 'client_id':state.client['client_id'] if state.client else None}
        return self.run_action('transfer_to_operator', {'queue': queue, 'summary': summary})

    def finish_handoff(self, state, out, queue='operator_general'):
        try:
            result = self.handoff(state, queue)
        except ActionError as exc:
            out['status'] = 'action_error'
            out['actions'].append({'name':'transfer_to_operator','mode':'error','error':{'code':exc.code,'message':exc.message}})
            out['facts']['handoff_error'] = {'code':exc.code,'message':exc.message}
            out['instruction'] = 'Честно сообщи: передача оператору сейчас недоступна. Не обещай соединение.'
            return out
        out['actions'].append({'name':'transfer_to_operator', 'mode':'execute', 'result':result})
        out['facts']['handoff'] = result
        out['facts']['transfer_to_operator'] = result
        out['facts']['real_transfer'] = result.get('real_transfer', False)
        out['status'] = 'handoff'
        state.closed = True
        if state.active:
            state.active.pending = None
            state.active.done = True
        return out

    def process(self, decision, state, text):
        lang = decision.response_language
        state.language = lang
        state.current_request = text
        state.requested_scenarios = [s.scenario_id for s in decision.scenarios]
        reply = explicit_reply(text) or decision.confirmation
        out = {'status': 'collecting', 'actions': [], 'facts': {}, 'instruction': '', 'question': ''}
        top = decision.scenarios[0]
        # An intervening question/unclear turn invalidates the old confirmation context.
        if state.active and state.active.pending and reply is None:
            state.active.pending = None
        if top.scenario_id == 'SC37' and (top.confidence >= .75 or decision.needs_operator):
            spec = self.c.scenarios.get(top.scenario_id, {})
            active_spec = self.c.scenarios.get(state.active.scenario_id, {}) if state.active else {}
            queue = (active_spec.get('handoff') or spec.get('handoff') or {}).get('queue', 'operator_general')
            supplied, _ = validate_slots({**decision.slots, **top.slots}, self.c)
            try:
                caller = self.backend.identify({k:v for k,v in supplied.items() if k in ('phone','iin')})
                if caller and (not state.client or state.client['client_id']==caller['client_id']):
                    state.client = caller
            except ActionError:
                pass  # Transfer still proceeds with the contradictory request in its summary.
            if state.active and state.active.scenario_id=='SC35' and state.active.slots.get('complaint_text') and 'create_complaint' not in state.active.completed_actions:
                result = self.backend.run('create_complaint', {**state.active.slots, **supplied})
                state.active.completed_actions['create_complaint'] = result
                out['actions'].append({'name':'create_complaint','mode':'execute','result':result})
                out['facts']['complaint'] = result
            out['instruction'] = 'Объясни, что подготовлена передача оператору; в демо реального звонка нет.'
            return self.finish_handoff(state, out, queue)
        if top.confidence < .45:
            state.low_confidence += 1
        elif top.confidence >= .75:
            state.low_confidence = 0
        if state.low_confidence >= 2:
            out['instruction'] = 'Дважды не удалось понять запрос; подготовлена передача оператору с контекстом.'
            return self.finish_handoff(state, out)
        if top.scenario_id in self.c.system:
            spec = self.c.system[top.scenario_id]
            if top.scenario_id != 'SYS_UNCLEAR' and top.confidence < .75:
                out.update(status='clarify', question=decision.clarification or self.c.system['SYS_UNCLEAR']['response'][lang])
                return out
            if top.scenario_id == 'SYS_GOODBYE' and top.confidence >= .75:
                state.closed = True
            out.update(status='system', question=decision.clarification or spec.get('response', {}).get(lang, ''), instruction=spec['behavior'])
            return out
        if top.confidence < .75:
            out.update(status='clarify', question=decision.clarification or self.c.system['SYS_UNCLEAR']['response'][lang], instruction='Задай один уточняющий вопрос между двумя ближайшими сценариями. Ничего не выполняй.')
            return out
        if decision.resume_previous and state.suspended:
            if state.active and not state.active.done:
                state.queue.insert(0, state.active)
            state.active = state.suspended.pop()
        elif not state.active or state.active.scenario_id != top.scenario_id or (state.active.done and not decision.is_continuation):
            previous = state.active
            if state.active and not state.active.done:
                state.active.pending = None
                state.suspended.append(state.active)
            queued = next((f for f in state.queue if f.scenario_id == top.scenario_id), None)
            state.active = queued or Frame(top.scenario_id)
            if queued:
                state.queue.remove(queued)
            if previous and previous.scenario_id=='SC01' and top.scenario_id=='SC02':
                for key in ('region','vehicle_type','drivers_iin','vehicle_plate'):
                    if key in previous.slots:
                        state.active.slots[key] = copy.deepcopy(previous.slots[key])
                        state.active.slot_sources[key] = 'previous_ogpo_quote'
        for extra in decision.scenarios[1:]:
            if extra.scenario_id in self.c.scenarios and extra.confidence >= .75 and extra.scenario_id not in [f.scenario_id for f in state.queue]:
                slots, _ = validate_slots(extra.slots, self.c)
                state.queue.append(Frame(extra.scenario_id, slots))
        f = state.active
        spec = self.c.scenarios[f.scenario_id]
        if f.done and decision.is_continuation and not (state.queue or state.suspended):
            out.update(status='completed', question=('Этот запрос уже обработан. Чем ещё помочь?'
                       if lang == 'ru' else 'Бұл сұрау өңделді. Тағы қалай көмектесе аламын?'))
            return out
        if spec['priority'] == 'urgent':
            out['facts']['safety'] = {'SC11':self.c.kb['claims']['road_accident_now'],
                'SC15':self.c.kb['products']['travel']['notes'], 'SC38':self.c.kb['fraud_policy']}[f.scenario_id]
            out['instruction'] = 'Сначала короткая срочная рекомендация из safety, затем вопрос.'
        shared = {k:v for k,v in decision.slots.items() if k in ('phone','iin')}
        selected = next((s for s in decision.scenarios if s.scenario_id==f.scenario_id),top)
        received, invalid = validate_slots({**shared, **selected.slots}, self.c)
        if received and any(f.slots.get(k) != v for k,v in received.items()):
            if any(self.c.actions[a]['irreversible'] for a in f.completed_actions):
                out['facts']['completed_actions'] = copy.deepcopy(f.completed_actions)
                out['instruction'] = 'Операция уже выполнена в демо; изменение параметров передано оператору без повторного исполнения.'
                return self.finish_handoff(state, out)
            f.pending = None
            f.completed_actions = {}
        f.slots.update(received)
        f.slot_sources.update({k:'current_utterance' for k in received})
        for key in received:
            f.errors.pop('slot:'+key, None)
        if invalid:
            f.waiting_slot = invalid[0]
            error_key = 'slot:'+invalid[0]
            f.errors[error_key] = f.errors.get(error_key,0)+1
            if f.errors[error_key] >= 2:
                out['instruction'] = 'Не удалось уточнить параметр после повторного вопроса; подготовлена передача оператору.'
                return self.finish_handoff(state, out)
            out.update(question=self.question(invalid[0], lang), instruction='Параметр имеет неверный формат. Переспроси один параметр.')
            return out
        s = f.slots
        if any(k in s for k in ('phone','iin','policy_number','claim_number')):
            identifiers = {k:v for k,v in s.items() if f.scenario_id != 'SC12' or k not in ('policy_number','claim_number')}
            try:
                found = self.backend.identify(identifiers)
            except ActionError as e:
                out.update(status='clarify', facts={'error':{'code':e.code,'message':e.message}},
                           question=self.question('phone', lang), instruction='Идентификаторы противоречат друг другу. Уточни телефон заявителя; ничего не выполняй.')
                return out
            if found:
                if state.client and state.client['client_id'] != found['client_id']:
                    out.update(status='clarify', instruction='Идентификатор относится к другому клиенту. Предложи начать новый диалог; ничего не выполняй.')
                    return out
                state.client = found
        if spec['requires_identification'] and not state.client:
            key = 'phone'
            f.errors['identify'] = f.errors.get('identify', 0) + int(bool(s.get('phone') or s.get('iin')))
            if f.errors['identify'] >= 2:
                out['instruction'] = 'Клиент не найден после повторного запроса; предложена передача оператору.'
                return self.finish_handoff(state, out)
            else:
                f.waiting_slot = key
                out['question'] = self.question(key, lang)
            return out
        if state.client:
            s['client_id'] = state.client['client_id']
            for key in ('phone', 'iin', 'email', 'city'):
                if key not in s:
                    f.slot_sources[key] = 'identified_profile'
                s.setdefault(key, state.client[key])
            policies = [p for p in self.backend.data['policies'] if p['client_id'] == state.client['client_id']]
            product_hint = {'SC13':'casco','SC14':'property','SC15':'travel','SC16':'accident','SC21':'dms','SC22':'dms','SC24':'dms','SC04':'ogpo','SC05':'ogpo'}.get(f.scenario_id)
            relevant = [p for p in policies if not product_hint or p['product'] == product_hint]
            if len(relevant) == 1 and f.scenario_id != 'SC12':
                s.setdefault('policy_number', relevant[0]['policy_number'])
            claims = [c for c in self.backend.data['claims'] if c['client_id'] == state.client['client_id']]
            if len(claims) == 1 and f.scenario_id != 'SC12':
                s.setdefault('claim_number', claims[0]['claim_number'])
        product = {'SC01':'ogpo','SC02':'ogpo','SC03':'casco','SC06':'travel','SC07':'property','SC08':'accident','SC12':'ogpo','SC13':'casco','SC14':'property','SC15':'travel','SC16':'accident'}.get(f.scenario_id)
        if product:
            s.setdefault('product_type', product)
        if f.scenario_id == 'SC18' and s.get('claim_number'):
            try:
                claim = self.backend.run('get_claim', s)
            except ActionError as e:
                out.update(status='action_error', question=self.question('claim_number',lang),
                           facts={'error':{'code':e.code,'message':e.message}})
                out['actions'].append({'name':'get_claim','mode':'error','error':{'code':e.code,'message':e.message}})
                return out
            s.setdefault('product_type', 'ogpo' if claim['claim_type']=='ogpo_victim' else claim['claim_type'])
            out['facts']['claim'] = claim
            out['actions'].append({'name':'get_claim','mode':'execute','result':claim})
        if f.scenario_id == 'SC02' and s.get('vehicle_plate'):
            s.setdefault('region', self.c.kb['products']['ogpo']['pricing']['region_by_plate_code'].get(s['vehicle_plate'][-2:], 'other'))
        if s.get('policy_number') and f.scenario_id in ('SC04','SC05','SC27','SC28'):
            try:
                p = self.backend.policy(s)
                for key, value in p['details'].items():
                    s.setdefault(key, value)
                s.setdefault('product_type', p['product'])
            except ActionError:
                pass
        s.setdefault('franchise', 0)
        if f.scenario_id == 'SC11' and (s.get('injured') is True or decision.needs_operator):
            out['facts']['safety'] = self.c.kb['claims']['road_accident_now']
            out['facts']['kb_lookup'] = {'section':'claims', 'key':'road_accident_now'}
            out['instruction'] = 'Сначала срочная инструкция из safety, затем сообщи о подготовке передачи оператору в демо.'
            return self.finish_handoff(state, out, 'claims_team')
        required = list(spec['slots']['required'])
        if f.scenario_id == 'SC02':
            required += ['region','vehicle_type']
        if f.scenario_id == 'SC06':
            required += ['phone']
        for key in required:
            if key not in s or s[key] is None or s[key] == '':
                f.waiting_slot = key
                out['question'] = self.question(key, lang)
                out['instruction'] = 'Задай только этот вопрос. Если есть другие запросы, кратко подтверди, что они сохранены.'
                if spec['priority'] == 'urgent':
                    out['instruction'] += ' Сначала короткая срочная рекомендация из переданных фактов.'
                return out
        f.waiting_slot = None
        if f.pending and reply == 'no':
            f.pending = None
            f.done = True
            out.update(status='cancelled', instruction='Подтверди отмену запрошенного действия. Оно не выполнялось.')
            return out
        confirmed = bool(f.pending and reply == 'yes' and f.pending['slots'] == s)
        if f.pending and not confirmed:
            out.update(status='confirmation', facts=f.pending, instruction='Повтори кратко параметры ожидающего действия и попроси явное подтверждение. Ничего не выполнено.')
            return out
        for action in spec['actions']:
            if action in f.completed_actions:
                out['facts'][action] = f.completed_actions[action]
                continue
            # Conditional handoffs are triggered above by the LLM with catalog evidence.
            if action == 'transfer_to_operator' and not (decision.needs_operator or (spec['handoff'] and spec['handoff']['when'].startswith('always'))):
                continue
            if action == 'send_sms' and not s.get('phone'):
                continue
            args = {**s, 'queue': (spec['handoff'] or {}).get('queue', 'operator_general'), 'summary': state.public()}
            args['summary']['client_id'] = state.client['client_id'] if state.client else None
            if f.scenario_id == 'SC12' and action == 'get_policy':
                if not s.get('policy_number'):
                    args['vehicle_plate'] = s.get('culprit_vehicle_plate')
                args.pop('client_id', None)
            if action == 'resend_documents' and not args.get('policy_number'):
                f.waiting_slot = 'policy_number'
                out['question'] = self.question('policy_number', lang)
                return out
            try:
                action_confirmed = bool(confirmed and f.pending and f.pending['action'] == action)
                if self.c.actions[action]['irreversible'] and not action_confirmed:
                    preview = self.run_action(action, args, preview=True)
                    f.pending = {'operation_id':str(uuid4()), 'action': action, 'slots': copy.deepcopy(s), 'preview': preview}
                    out['actions'].append({'name': action, 'mode': 'preview', 'result': preview})
                    out.update(status='confirmation', facts=f.pending, instruction='Кратко озвучь изменение и значимые параметры (без полных персональных данных), задай один вопрос: подтверждаете? Действие ещё не выполнено.')
                    return out
                if action == 'transfer_to_operator' and decision.needs_operator:
                    args['queue'] = (spec['handoff'] or {}).get('queue','operator_general')
                result = self.run_action(action, args, confirmed=action_confirmed,
                    operation_id=f.pending['operation_id'] if action_confirmed else None)
                if action_confirmed:
                    f.pending = None
                    confirmed = False
                f.completed_actions[action] = result
                out['actions'].append({'name': action, 'mode': 'execute', 'result': result})
                out['facts'][action] = result
                if action == 'transfer_to_operator':
                    f.done = True
                    state.closed = True
                    out.update(status='handoff', instruction='Передача оператору подготовлена в демо; реального соединения нет.')
                    return out
                if action == 'update_contact' and state.client:
                    state.client = copy.deepcopy(next(c for c in self.backend.data['clients'] if c['client_id'] == state.client['client_id']))
                if action == 'get_policy' and f.scenario_id == 'SC12':
                    s['policy_number'] = result['policy_number']
                if action == 'check_payment' and any(not p.get('policy_number') for p in result['payments']):
                    out.update(status='handoff', instruction='Платёж найден без оформленного полиса. Подготовь передачу оператору.')
                    return self.finish_handoff(state, out)
            except ActionError as e:
                f.pending = None
                f.errors[action] = f.errors.get(action, 0) + 1
                out['actions'].append({'name':action,'mode':'error','error':{'code':e.code,'message':e.message}})
                out.update(status='action_error', facts={'error': {'code': e.code, 'message': e.message}},
                           instruction='Кратко объясни ошибку из facts. Не сообщай об успехе. Предложи уточнить данные или обратиться к оператору.')
                if e.code == 'service_unavailable':
                    if action == 'transfer_to_operator':
                        out['instruction'] = 'Передача оператору недоступна после повторной попытки; честно сообщи об этом.'
                        return out
                    return self.finish_handoff(state, out)
                if f.errors[action] >= 2:
                    return self.finish_handoff(state, out)
                return out
        f.pending = None
        f.done = True
        out.update(status='completed', instruction='Ответь по результатам действий, кратко. Не выдавай simulated_only или handoff_prepared за реальную отправку или соединение.')
        if state.queue:
            out['next_scenario'] = state.queue[0].scenario_id
            out['instruction'] += ' Предложи перейти к следующему сохранённому вопросу.'
        elif state.suspended:
            out['next_scenario'] = state.suspended[-1].scenario_id
            out['instruction'] += ' Предложи вернуться к прерванному вопросу.'
        return out
