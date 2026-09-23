from collections import deque
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

@dataclass
class Frame:
    scenario_id: str
    slots: dict[str, Any] = field(default_factory=dict)
    completed_actions: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    waiting_slot: str | None = None
    pending: dict | None = None
    done: bool = False
    slot_sources: dict[str, str] = field(default_factory=dict)

@dataclass
class Dialogue:
    id: str = field(default_factory=lambda: str(uuid4()))
    # Ten client turns plus their responses.
    history: deque = field(default_factory=lambda: deque(maxlen=20))
    active: Frame | None = None
    suspended: list[Frame] = field(default_factory=list)
    queue: list[Frame] = field(default_factory=list)
    client: dict | None = None
    language: str = 'ru'
    low_confidence: int = 0
    turn: int = 0

    def public(self):
        return {'history': list(self.history), 'active_scenario': self.active.scenario_id if self.active else None,
                'active_slots': self.active.slots if self.active else {},
                'waiting_slot': self.active.waiting_slot if self.active else None,
                'slot_sources': self.active.slot_sources if self.active else {},
                'pending_operation': self.active.pending if self.active else None,
                'suspended': [f.scenario_id for f in self.suspended],
                'queued': [f.scenario_id for f in self.queue], 'language': self.language,
                'client_identified': self.client is not None}
