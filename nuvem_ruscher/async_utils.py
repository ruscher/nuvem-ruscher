"""Trabalho em segundo plano sem travar a interface.

Regra do projeto: nada demorado roda na thread da interface. Funções bloqueantes vão
para ``run_async``; processos longos usam ``StreamingProcess``. Todo callback é
entregue na thread principal via ``GLib.idle_add``.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

from gi.repository import GLib


def _deliver(callback: Callable[..., Any] | None, *args: Any) -> bool:
    if callback is not None:
        callback(*args)
    return GLib.SOURCE_REMOVE


def run_async(
    func: Callable[..., Any],
    *args: Any,
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> threading.Thread:
    """Executa ``func(*args)`` numa thread e devolve o resultado na thread da interface."""

    def worker() -> None:
        try:
            result = func(*args)
        except BaseException as exc:  # repassado à interface, nunca engolido
            if on_error is None:
                GLib.idle_add(_print_error, exc)
            else:
                GLib.idle_add(_deliver, on_error, exc)
        else:
            GLib.idle_add(_deliver, on_done, result)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def _print_error(exc: BaseException) -> bool:
    import traceback

    traceback.print_exception(exc)
    return GLib.SOURCE_REMOVE


class Operation:
    """Algo em andamento que pode ser cancelado."""

    def cancel(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def running(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class StreamingProcess(Operation):
    """Processo cujas linhas chegam à interface em lotes (sem inundar o loop)."""

    def __init__(
        self,
        argv: Sequence[str],
        on_line: Callable[[str], None],
        on_exit: Callable[[int], None],
        env: dict[str, str] | None = None,
        interactive: bool = False,
    ) -> None:
        self._on_line = on_line
        self._on_exit = on_exit
        self._queue: deque[str] = deque()
        self._lock = threading.Lock()
        self._scheduled = False
        self._cancelled = False
        self._returncode: int | None = None
        try:
            self._proc: subprocess.Popen[str] | None = subprocess.Popen(
                list(argv),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if interactive else subprocess.DEVNULL,
                text=True,
                bufsize=1,
                env=env,
                start_new_session=True,
                errors="replace",
            )
        except OSError as exc:
            self._proc = None
            self._push(f"could not run {argv[0]}: {exc}")
            self._finish(127)
            return
        threading.Thread(target=self._reader, daemon=True).start()

    @property
    def running(self) -> bool:
        return self._proc is not None and self._returncode is None

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def send(self, line: str) -> bool:
        """Escreve uma linha no stdin do processo (só com ``interactive=True``)."""
        if not self.running or self._proc is None or self._proc.stdin is None:
            return False
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return False
        return True

    def cancel(self) -> None:
        if not self.running or self._proc is None:
            return
        self._cancelled = True
        try:
            os.killpg(self._proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            # Processos elevados (pkexec) não podem ser sinalizados pelo usuário;
            # nesses casos o helper termina sozinho e o cancelamento vale ao final.
            pass

    def _reader(self) -> None:
        if self._proc is None or self._proc.stdout is None:
            return
        for line in self._proc.stdout:
            self._push(line.rstrip("\n"))
        code = self._proc.wait()
        self._finish(code)

    def _push(self, line: str) -> None:
        with self._lock:
            self._queue.append(line)
            if self._scheduled:
                return
            self._scheduled = True
        GLib.timeout_add(40, self._flush)

    def _flush(self) -> bool:
        with self._lock:
            lines = list(self._queue)
            self._queue.clear()
            self._scheduled = False
        for line in lines:
            self._on_line(line)
        return GLib.SOURCE_REMOVE

    def _finish(self, code: int) -> None:
        def done() -> bool:
            self._flush()
            self._returncode = code
            self._on_exit(code)
            return GLib.SOURCE_REMOVE

        # Depois do último lote de linhas.
        GLib.timeout_add(60, done)


class Debouncer:
    """Agrupa chamadas repetidas (ex.: rajada de eventos do Docker)."""

    def __init__(self, delay_ms: int, callback: Callable[[], None]) -> None:
        self.delay_ms = delay_ms
        self.callback = callback
        self._source = 0

    def __call__(self) -> None:
        if self._source:
            GLib.source_remove(self._source)
        self._source = GLib.timeout_add(self.delay_ms, self._fire)

    def _fire(self) -> bool:
        self._source = 0
        self.callback()
        return GLib.SOURCE_REMOVE

    def cancel(self) -> None:
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0
