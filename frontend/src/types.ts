export type Language = 'auto' | 'ru' | 'kk';
export type Message = { id: string; role: 'user' | 'assistant'; text: string; language?: string };
export type Trace = {
  turn: number; transcript: string; language: string; response_language?: string;
  confidence: number | null; confidence_source: string;
  scenarios: { scenario_id: string; name?: string; confidence: number }[];
  alternatives: { scenario_id: string; confidence: number }[];
  reason: string; slots: Record<string, unknown>; actions: unknown[];
  latency_ms: Record<string, number | null>;
  status?: string;
};
export type ServerEvent = { type: string; event_id: number; turn_id?: string; payload: Record<string, unknown> };
