"""Linha do tempo do modo simulado: passos com atraso, no loop do GLib, canceláveis."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import GLib

from nuvem_ruscher.async_utils import Operation

Step = tuple[int, Callable[[], None]]


class Timeline(Operation):
    """Sequência de passos com atrasos.

    ``cancellable`` imita o helper de verdade: pedir para cancelar só vale enquanto a etapa
    permite (ex.: durante a cópia de uma migração); fora disso, o pedido é ignorado.
    """

    def __init__(
        self,
        steps: list[Step],
        on_cancel: Callable[[], None] | None = None,
        cancellable: bool = True,
        scale: float = 1.0,
    ) -> None:
        self._scale = scale  # testes aceleram o tempo
        self._steps = list(steps)
        self._source = 0
        self._running = True
        self._on_cancel = on_cancel
        self.cancellable = cancellable
        self._next()

    @property
    def running(self) -> bool:
        return self._running

    def _next(self) -> None:
        if not self._steps:
            self._running = False
            return
        delay, action = self._steps.pop(0)

        def fire() -> bool:
            self._source = 0
            action()
            if self._running:
                self._next()
            return GLib.SOURCE_REMOVE

        self._source = GLib.timeout_add(max(int(delay * self._scale), 1), fire)

    def cancel(self) -> None:
        if not self.cancellable:
            return
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0
        if self._running:
            self._running = False
            if self._on_cancel:
                self._on_cancel()
