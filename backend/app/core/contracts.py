"""Public HTTP turn contract, also used for frontend WebSocket events."""
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field

class TurnRequest(BaseModel):
    session_id: str | None = None
    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=100)
    text: str = Field(default='', max_length=5000)
    language: Literal['auto', 'ru', 'kk'] = 'auto'
    speak: bool = False
    audio_base64: str | None = Field(default=None, max_length=17_000_000)
    mime: str = 'audio/wav'
    demo_scenario: str | None = None

class TurnTrace(BaseModel):
    turn: int
    transcript: str
    language: str | None = None
    response_language: str | None = None
    scenarios: list[dict[str, Any]] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    reason: str = ''
    slots: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: dict[str, float | None] = Field(default_factory=dict)
    status: str = 'error'
    mode: str
    errors: list[str] = Field(default_factory=list)

class TurnResponse(BaseModel):
    session_id: str
    request_id: str
    turn_id: str
    text: str | None
    state: dict[str, Any]
    trace: TurnTrace
    events: list[dict[str, Any]]

def trace_from(events, engine):
    by_event = {e['event']:e for e in events}
    routing = by_event.get('routing_decision', {})
    execution = by_event.get('execution_trace', {}).get('execution', {})
    timings = by_event.get('turn_complete', {}).get('metrics', {})
    return TurnTrace(turn=engine.state.turn,
        transcript=by_event.get('stt_transcript', {}).get('text', ''),
        language=routing.get('language'), response_language=routing.get('response_language'),
        scenarios=routing.get('scenarios', []), alternatives=routing.get('alternatives', []),
        reason=routing.get('reason', ''),
        slots={s['scenario_id']:s.get('slots', {}) for s in routing.get('scenarios', [])},
        actions=execution.get('actions', []), status=execution.get('status', 'error'), mode=engine.llm.settings.provider,
        errors=[e['message'] for e in events if e['event']=='error'],
        latency_ms={'stt':timings.get('stt_ms'), 'triage':None, 'router':timings.get('routing_ms'),
                    'scenario':timings.get('scenario_ms'), 'response':timings.get('response_ms'),
                    'tts_first_audio':timings.get('tts_first_segment_ms'),
                    'server_first_audio':timings.get('server_first_audio_ms'),
                    'server_total':timings.get('server_total_ms'), 'total':None})
