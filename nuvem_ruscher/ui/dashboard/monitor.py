"""Estado ao vivo do servidor, guiado por eventos (sem polling agressivo).

* ``docker events`` fica aberto: cada evento de container dispara uma atualização
  (agrupada em 400 ms).
* Um tique leve a cada 20 s confere o serviço systemd e o ping da API.
* CPU/RAM (``docker stats``) só a cada 5 s, e só com a visão geral à mostra e a janela ativa.
* Estatísticas do Immich (contagem de fotos) a cada 60 s.
"""

from __future__ import annotations

import os

from gi.repository import GLib, GObject

from nuvem_ruscher.async_utils import Debouncer, Operation, run_async
from nuvem_ruscher.backend.base import Backend
from nuvem_ruscher.core.config import AppConfig
from nuvem_ruscher.core.docker import ContainerState, ContainerStats, Health
from nuvem_ruscher.core.immich_api import ServerStats


class ServerMonitor(GObject.Object):
    __gsignals__ = {  # noqa: RUF012 — formato exigido pelo PyGObject
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "stats-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self.backend = backend
        self.conf: AppConfig = backend.load_config()
        self.service = "unknown"
        self.containers: list[ContainerState] = []
        self.stats: dict[str, ContainerStats] = {}
        self.healthy = False
        self.mounted = True
        self.disk: tuple[int, int, int] = (0, 0, 0)
        self.statistics: ServerStats | None = None
        self.busy_action = ""  # "start" | "stop" | "restart" enquanto o helper trabalha
        self.loaded = False
        self.want_stats = False
        self._active = False
        self._events: Operation | None = None
        self._debounced = Debouncer(400, self.refresh)
        self._timers: list[int] = []
        self._refreshing = False
        self._pending = False

    # --- ciclo de vida --------------------------------------------------------------
    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._watch()
        self.refresh()
        self.refresh_statistics()
        self._timers = [
            GLib.timeout_add_seconds(20, self._tick_slow),
            GLib.timeout_add_seconds(5, self._tick_stats),
            GLib.timeout_add_seconds(60, self._tick_statistics),
        ]

    def stop(self) -> None:
        self._active = False
        for source in self._timers:
            GLib.source_remove(source)
        self._timers = []
        self._debounced.cancel()
        if self._events is not None:
            self._events.cancel()
            self._events = None

    def _watch(self) -> None:
        def on_event(_line: str) -> None:
            self._debounced()

        def on_exit(_code: int) -> None:
            self._events = None
            if self._active:  # o Docker reiniciou? Tenta de novo daqui a pouco.
                GLib.timeout_add_seconds(5, lambda: (self._watch() if self._active else None) or False)

        try:
            self._events = self.backend.watch_events(on_event, on_exit)
        except OSError:
            self._events = None

    # --- coleta ------------------------------------------------------------------------
    def refresh(self) -> None:
        if self._refreshing:
            self._pending = True
            return
        self._refreshing = True
        backend = self.backend

        def collect() -> tuple:
            conf = backend.load_config()
            service = backend.service_state()
            containers = backend.containers()
            server_up = any(c.name == "immich_server" and c.running for c in containers)
            healthy = backend.ping() if server_up else False
            mounted = backend.is_mounted(conf.mount_point) if conf.mount_point not in ("", "/") else True
            target = conf.upload_location if conf.upload_location and os.path.isdir(conf.upload_location) else ""
            disk = backend.disk_usage(target) if target or backend.simulated else (0, 0, 0)
            return conf, service, containers, healthy, mounted, disk

        def done(result: tuple) -> None:
            self._refreshing = False
            self.conf, self.service, self.containers, self.healthy, self.mounted, self.disk = result
            self.loaded = True
            self.emit("changed")
            if self._pending:
                self._pending = False
                self.refresh()

        def failed(_exc: BaseException) -> None:
            self._refreshing = False

        run_async(collect, on_done=done, on_error=failed)

    def refresh_stats(self) -> None:
        def done(stats: dict[str, ContainerStats]) -> None:
            self.stats = stats
            self.emit("stats-changed")

        run_async(self.backend.stats, on_done=done, on_error=lambda _e: None)

    def refresh_statistics(self) -> None:
        def done(stats: ServerStats | None) -> None:
            self.statistics = stats
            self.emit("changed")

        run_async(self.backend.statistics, on_done=done, on_error=lambda _e: None)

    def _tick_slow(self) -> bool:
        if self._active:
            self.refresh()
        return GLib.SOURCE_CONTINUE

    def _tick_stats(self) -> bool:
        if self._active and self.want_stats and self.service == "active":
            self.refresh_stats()
        return GLib.SOURCE_CONTINUE

    def _tick_statistics(self) -> bool:
        if self._active and self.healthy:
            self.refresh_statistics()
        return GLib.SOURCE_CONTINUE

    # --- estado agregado ------------------------------------------------------------------
    @property
    def overall(self) -> str:
        """ok | starting | stopping | stopped | problem | disk-missing | failed | loading"""
        if not self.loaded:
            return "loading"
        if self.busy_action == "stop":
            return "stopping"
        if self.busy_action in ("start", "restart"):
            return "starting"
        if not self.mounted:
            return "disk-missing"
        if self.service == "failed":
            return "failed"
        if self.service in ("inactive", "unknown", "deactivating") and not any(c.running for c in self.containers):
            return "stopped"
        if self.healthy and all(c.ok for c in self.containers if c.running):
            return "ok"
        if any(c.health is Health.UNHEALTHY for c in self.containers):
            return "problem"
        return "starting"
