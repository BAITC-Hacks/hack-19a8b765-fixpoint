from contextlib import contextmanager
from time import perf_counter

class LatencyTracker:
    def __init__(self):
        self.started = perf_counter()
        self.metrics = {'stt_ms': None, 'routing_ms': None, 'scenario_ms': None, 'response_ms': None}

    def elapsed(self):
        return round((perf_counter() - self.started) * 1000, 1)

    @contextmanager
    def stage(self, name):
        start = perf_counter()
        try:
            yield
        finally:
            self.metrics[name] = round((perf_counter() - start) * 1000, 1)
