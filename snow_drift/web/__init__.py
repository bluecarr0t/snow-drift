"""Embedded local web UI for monitoring and tuning Snow Drift.

The web layer is optional: if FastAPI / uvicorn aren't installed it
logs a warning at startup and the rest of the system runs unchanged.
"""

from snow_drift.web.shared_state import SharedState
from snow_drift.web.server import WebServer

__all__ = ["SharedState", "WebServer"]
