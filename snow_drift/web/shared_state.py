"""Thread-safe latest-snapshot publisher.

The main loop calls :meth:`SharedState.publish` every tick with a dict
describing the current state of the piece (fan speeds, sensor values,
mood, presence, uptime). Web requests call :meth:`SharedState.latest`
to read whatever was most recently published. Lock-protected, copy on
both sides, no async required.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict


class SharedState:
    """Single-slot publisher for the latest main-loop snapshot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: Dict[str, Any] = {}
        self._published_at: float = 0.0

    def publish(self, snapshot: Dict[str, Any]) -> None:
        """Replace the published snapshot with a deep-ish copy of ``snapshot``."""
        with self._lock:
            # Shallow copy is enough; main loop produces fresh dicts each tick.
            self._snapshot = dict(snapshot)
            self._published_at = time.monotonic()

    def latest(self) -> Dict[str, Any]:
        """Return a copy of the most recently published snapshot.

        Includes a synthetic ``_age_s`` field so consumers can spot
        a stalled main loop.
        """
        with self._lock:
            snap = dict(self._snapshot)
            age = (
                time.monotonic() - self._published_at
                if self._published_at > 0
                else float("inf")
            )
        snap["_age_s"] = age
        return snap
