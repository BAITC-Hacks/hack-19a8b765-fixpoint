from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict

class Candidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scenario_id: str
    confidence: float = Field(ge=0, le=1)
    reason: str
    slots: dict[str, Any] = Field(default_factory=dict)

class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scenarios: list[Candidate] = Field(min_length=1, max_length=6)
    alternatives: list[Candidate] = Field(default_factory=list, max_length=4)
    language: Literal['ru', 'kk', 'mixed']
    response_language: Literal['ru', 'kk']
    slots: dict[str, Any] = Field(default_factory=dict)
    is_continuation: bool = False
    is_topic_switch: bool = False
    resume_previous: bool = False
    needs_operator: bool = False
    reason: str
    clarification: str = ''

class Answer(BaseModel):
    text: str = Field(min_length=1, max_length=1800)

class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    language: Literal['auto', 'ru', 'kk'] = 'auto'
