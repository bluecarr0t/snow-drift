"""Embedded FastAPI / uvicorn web server for live monitoring + tuning.

The server runs in a daemon thread alongside the main loop and shares
two thread-safe objects with it:

- :class:`SharedState` — the loop *publishes* a snapshot every tick,
  the web *reads* it.
- :class:`RuntimeSettings` — the web *mutates* knobs, the loop *reads*
  them every tick.

FastAPI / uvicorn / pydantic are imported lazily so a dev-mode install
without those packages still runs the rest of the system. If the
imports fail :meth:`WebServer.start` logs a warning and is a no-op.

Note: this module deliberately does NOT use ``from __future__ import
annotations``. FastAPI introspects route handler type hints at runtime
to decide where parameters come from (body vs. query); under PEP-563
string annotations it can't resolve the Pydantic models defined in
``_create_app``'s local scope, and silently treats them as query
params. Keeping eager annotations sidesteps that whole class of bug.
"""

import logging
import threading
from pathlib import Path
from typing import Any, List, Optional

from snow_drift.runtime_settings import RuntimeSettings
from snow_drift.web.shared_state import SharedState
from snow_drift.web.system_stats import read_pi_stats

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


def _create_app(state: SharedState, settings: RuntimeSettings) -> Any:
    """Build the FastAPI app. Imported lazily so missing deps don't crash."""
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse
    from pydantic import BaseModel, Field

    class FanOverrideRequest(BaseModel):
        # ``None`` means "release the override and return to algorithm".
        speeds: Optional[List[float]] = None

    class IntensityRequest(BaseModel):
        multiplier: float = Field(
            ge=RuntimeSettings.INTENSITY_MIN, le=RuntimeSettings.INTENSITY_MAX
        )

    class ForceAwakeRequest(BaseModel):
        enabled: bool

    class ConfigUpdateRequest(BaseModel):
        intensity_multiplier: Optional[float] = Field(
            default=None,
            ge=RuntimeSettings.INTENSITY_MIN,
            le=RuntimeSettings.INTENSITY_MAX,
        )
        force_awake: Optional[bool] = None
        manual_fan_speeds: Optional[List[float]] = None
        # Sentinel for "release manual override". JSON null on
        # manual_fan_speeds is ambiguous (untouched vs. clear), so we
        # use a separate flag.
        clear_manual_fan_speeds: bool = False

    app = FastAPI(title="Snow Drift", docs_url="/api/docs", redoc_url=None)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index():
        path = _STATIC_DIR / "index.html"
        if not path.exists():
            return HTMLResponse(
                "<h1>Snow Drift</h1><p>UI bundle missing.</p>", status_code=200
            )
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @app.get("/api/state")
    async def get_state():
        snap = state.latest()
        snap["system"] = read_pi_stats()
        snap["settings"] = settings.snapshot()
        return JSONResponse(snap)

    @app.get("/api/config")
    async def get_config():
        return JSONResponse(settings.snapshot())

    @app.post("/api/config")
    async def update_config(body: ConfigUpdateRequest):
        if body.intensity_multiplier is not None:
            settings.set_intensity_multiplier(body.intensity_multiplier)
        if body.force_awake is not None:
            settings.set_force_awake(body.force_awake)
        if body.clear_manual_fan_speeds:
            settings.set_manual_fan_speeds(None)
        elif body.manual_fan_speeds is not None:
            settings.set_manual_fan_speeds(body.manual_fan_speeds)
        return JSONResponse(settings.snapshot())

    @app.post("/api/control/fans")
    async def control_fans(body: FanOverrideRequest):
        result = settings.set_manual_fan_speeds(body.speeds)
        return JSONResponse({"manual_fan_speeds": result})

    @app.post("/api/control/intensity")
    async def control_intensity(body: IntensityRequest):
        result = settings.set_intensity_multiplier(body.multiplier)
        return JSONResponse({"intensity_multiplier": result})

    @app.post("/api/control/force-awake")
    async def control_force_awake(body: ForceAwakeRequest):
        result = settings.set_force_awake(body.enabled)
        return JSONResponse({"force_awake": result})

    @app.get("/api/health")
    async def health():
        snap = state.latest()
        age = snap.get("_age_s", float("inf"))
        return {"ok": age < 5.0, "loop_age_s": age}

    return app


class WebServer:
    """Run uvicorn in a daemon thread; safe to ``start()`` / ``stop()``."""

    def __init__(
        self,
        state: SharedState,
        settings: RuntimeSettings,
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        self.state = state
        self.settings = settings
        self.host = host
        self.port = port
        self._server: Optional[Any] = None  # uvicorn.Server
        self._thread: Optional[threading.Thread] = None
        self._available: bool = False

    @property
    def available(self) -> bool:
        """Whether the underlying web stack imported successfully."""
        return self._available

    def start(self) -> None:
        """Start serving. Idempotent; safe even if FastAPI isn't installed."""
        if self._thread is not None and self._thread.is_alive():
            return

        try:
            import uvicorn

            app = _create_app(self.state, self.settings)
            uv_config = uvicorn.Config(
                app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
                # We're running inside an existing process that already
                # owns SIGINT/SIGTERM via main.py's signal handlers.
                # Tell uvicorn not to install its own.
                reload=False,
            )
            self._server = uvicorn.Server(uv_config)
            # Defuse uvicorn's signal handlers so they don't fight ours.
            self._server.install_signal_handlers = lambda: None  # type: ignore[assignment]
        except Exception as exc:  # pragma: no cover - import / config errors
            logger.warning(
                "Web UI unavailable (FastAPI / uvicorn import failed): %s", exc
            )
            self._available = False
            return

        self._available = True
        self._thread = threading.Thread(
            target=self._run, name="snow-drift-web", daemon=True
        )
        self._thread.start()
        logger.info("Web UI listening on http://%s:%d/", self.host, self.port)

    def _run(self) -> None:
        try:
            assert self._server is not None
            self._server.run()
        except Exception:  # pragma: no cover
            logger.exception("Web server thread crashed")

    def stop(self, timeout: float = 3.0) -> None:
        """Ask uvicorn to exit and wait for the thread to join."""
        server = self._server
        if server is None:
            return
        server.should_exit = True
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("Web server did not stop within %.1fs", timeout)
        self._thread = None
        self._server = None
        self._available = False
