export type Language = 'ru' | 'kk';
export type Message = { id: string; role: 'user' | 'assistant'; text: string; local?: boolean };
export type Trace = {
  turn: number; transcript: string; language: string;
  scenarios: { scenario_id: string; name?: string; confidence: number }[];
  alternatives: { scenario_id: string; confidence: number }[];
  reason: string; slots: Record<string, unknown>; actions: unknown[];
  latency_ms: Record<string, number | null>;
};
export type ServerEvent = { type: string; event_id: number; turn_id?: string; payload: Record<string, unknown> };
