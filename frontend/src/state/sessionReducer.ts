import type { Message, ServerEvent, Trace } from '../types.ts';
export type State = { messages: Message[]; traces: Trace[]; busy: boolean; closed: boolean; lastEvent: number; error: string; waitingSlot: string | null };
export const initialState: State = { messages: [], traces: [], busy: false, closed: false, lastEvent: -1, error: '', waitingSlot: null };
type Action = { type: 'reset' } | { type: 'error'; error: string } | { type: 'user'; message: Message } | { type: 'event'; event: ServerEvent };
export function sessionReducer(state: State, action: Action): State {
  if (action.type === 'reset') return initialState;
  if (action.type === 'error') return { ...state, busy: false, error: action.error };
  if (action.type === 'user') {
    if (state.busy || state.closed || state.messages.some(m => m.id === action.message.id)) return state;
    return { ...state, messages: [...state.messages, action.message], busy: true, error: '' };
  }
  const event = action.event;
  if (!Number.isInteger(event.event_id) || event.event_id <= state.lastEvent) return state;
  const next = { ...state, lastEvent: event.event_id };
  if (event.type === 'transcript.final' && event.payload.source === 'audio' && typeof event.payload.text === 'string') {
    const message: Message = { id: `user-${event.turn_id ?? event.event_id}`, role: 'user', text: event.payload.text };
    next.messages = [...state.messages.filter(m => m.id !== message.id), message];
  }
  if (event.type === 'assistant.text' && typeof event.payload.text === 'string') {
    const message: Message = { id: `assistant-${event.turn_id ?? event.event_id}`, role: 'assistant', text: event.payload.text, language: typeof event.payload.language === 'string' ? event.payload.language : undefined };
    next.messages = [...state.messages.filter(m => m.id !== message.id), message];
  }
  if (event.type === 'turn.status' && event.payload.event === 'execution_trace') {
    const context = event.payload.context;
    if (context && typeof context === 'object' && 'waiting_slot' in context) {
      next.waitingSlot = typeof context.waiting_slot === 'string' ? context.waiting_slot : null;
    }
  }
  if (event.type === 'trace.updated') {
    const trace = event.payload as unknown as Trace;
    if (Number.isInteger(trace.turn) && Array.isArray(trace.scenarios) && Array.isArray(trace.alternatives) && typeof trace.reason === 'string' && trace.latency_ms) {
      next.traces = [...state.traces.filter(t => t.turn !== trace.turn), trace];
    }
  }
  if (event.type === 'turn.completed') { next.busy = false; next.closed = event.payload.closed === true; }
  if (event.type === 'error') { next.busy = false; next.error = typeof event.payload.message === 'string' ? event.payload.message : 'Сервер не смог обработать реплику.'; }
  return next;
}
