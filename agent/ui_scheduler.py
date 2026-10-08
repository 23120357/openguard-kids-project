"""Thread-safe UI callbacks scheduled independently of the Windows wall clock."""

import heapq
import itertools
import logging
import threading
import time


class MonotonicScheduler:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._pending = []
        self._sequence = itertools.count()
        self._lock = threading.Lock()

    def after(self, milliseconds, callback, *args):
        with self._lock:
            heapq.heappush(
                self._pending,
                (self._clock() + milliseconds / 1000, next(self._sequence), callback, args),
            )

    def run_due(self):
        # Take a batch so callbacks cannot starve the Windows event pump.
        due = []
        with self._lock:
            now = self._clock()
            while self._pending and self._pending[0][0] <= now:
                due.append(heapq.heappop(self._pending))
        for _, _, callback, args in due:
            try:
                callback(*args)
            except Exception:
                logging.getLogger(__name__).exception("Scheduled UI callback failed")
