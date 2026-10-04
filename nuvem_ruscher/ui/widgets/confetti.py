"""Confete sutil para a celebração final. Respeita “reduzir animações”."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from gi.repository import Gdk, GLib, Graphene, Gtk

PALETTE = ("#3584e4", "#62a0ea", "#33d17a", "#f6d32d", "#ff7800", "#c061cb", "#e01b24")
DURATION = 2.8


@dataclass
class _Particle:
    x: float
    y: float
    vx: float
    vy: float
    angle: float
    spin: float
    w: float
    h: float
    color: Gdk.RGBA


class Confetti(Gtk.Widget):
    __gtype_name__ = "NuvemRuscherConfetti"

    def __init__(self) -> None:
        super().__init__()
        self.set_can_target(False)
        self.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self._particles: list[_Particle] = []
        self._tick_id = 0
        self._start_time = 0
        self._last = 0
        self._colors = []
        for hex_color in PALETTE:
            rgba = Gdk.RGBA()
            rgba.parse(hex_color)
            self._colors.append(rgba)

    def burst(self, count: int = 90) -> None:
        settings = self.get_settings()
        if not settings.get_property("gtk-enable-animations"):
            return
        width = max(self.get_width(), 400)
        self._particles = [
            _Particle(
                x=width / 2 + random.uniform(-60, 60),
                y=self.get_height() * 0.35,
                vx=random.uniform(-260, 260),
                vy=random.uniform(-620, -260),
                angle=random.uniform(0, math.tau),
                spin=random.uniform(-9, 9),
                w=random.uniform(6, 11),
                h=random.uniform(3, 6),
                color=random.choice(self._colors),
            )
            for _ in range(count)
        ]
        self._start_time = 0
        self._last = 0
        if not self._tick_id:
            self._tick_id = self.add_tick_callback(self._tick)

    def _tick(self, _widget: Gtk.Widget, clock: Gdk.FrameClock) -> bool:
        now = clock.get_frame_time() / 1_000_000
        if not self._start_time:
            self._start_time = now
            self._last = now
        dt = min(now - self._last, 0.05)
        self._last = now
        for p in self._particles:
            p.vy += 900 * dt
            p.vx *= 0.99
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.angle += p.spin * dt
        self.queue_draw()
        if now - self._start_time > DURATION:
            self._particles = []
            self._tick_id = 0
            self.queue_draw()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        if not self._particles:
            return
        elapsed = self._last - self._start_time
        alpha = 1.0 if elapsed < DURATION - 0.8 else max(0.0, (DURATION - elapsed) / 0.8)
        snapshot.push_opacity(alpha)
        for p in self._particles:
            snapshot.save()
            point = Graphene.Point()
            point.init(p.x, p.y)
            snapshot.translate(point)
            snapshot.rotate(math.degrees(p.angle))
            rect = Graphene.Rect().init(-p.w / 2, -p.h / 2, p.w, p.h)
            snapshot.append_color(p.color, rect)
            snapshot.restore()
        snapshot.pop()
