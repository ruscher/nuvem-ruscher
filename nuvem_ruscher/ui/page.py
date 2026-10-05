"""Página do painel: faixa de título (hero) e corpo centralizado, com rolagem própria."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from nuvem_ruscher.ui.common import label

BODY_MAX = 920
BODY_TIGHTEN = 760

# Cores dos ícones da barra lateral e das faixas (classes .tint-*, em style.css).
TINTS = ("blue", "teal", "green", "violet", "orange", "yellow", "red", "slate")


def icon_tile(icon_name: str, tint: str, size: int = 16, tile: str = "small") -> Gtk.Widget:
    """Ícone simbólico branco sobre um quadrado colorido (só decoração)."""
    # CenterBox: o ícone fica no meio sem pedir hexpand (que esticaria o quadrado).
    box = Gtk.CenterBox(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=False)
    box.add_css_class("icon-tile")
    box.add_css_class(f"icon-tile-{tile}")
    box.add_css_class(f"tint-{tint}")
    image = Gtk.Image.new_from_icon_name(icon_name)
    image.set_pixel_size(size)
    image.set_valign(Gtk.Align.CENTER)
    box.set_center_widget(image)
    box.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    return box


class Page(Gtk.Box):
    """Base das páginas. Subclasses põem o conteúdo em ``self.body`` (ou chamam ``add``)."""

    page_id = ""

    def __init__(
        self,
        title: str,
        description: str,
        icon_name: str,
        tint: str = "blue",
        scroll: bool = True,
        clamp: bool = True,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.page_title = title
        self.icon_name = icon_name
        self.tint = tint
        self.add_css_class("nr-page")

        self.hero = Gtk.Box(spacing=18)
        self.hero.add_css_class("page-hero")
        self.hero.add_css_class(f"hero-{tint}")
        self.hero_tile = icon_tile(icon_name, tint, size=26, tile="large")
        self.hero.append(self.hero_tile)
        # WrapBox: sem espaço, os botões descem para baixo do texto em vez de espremê-lo.
        wrap = Adw.WrapBox(
            child_spacing=18, line_spacing=14, hexpand=True, justify=Adw.JustifyMode.FILL, justify_last_line=True
        )
        wrap.set_valign(Gtk.Align.CENTER)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        self.hero_title = label(title, css=("title-1",))
        self.hero_title.set_accessible_role(Gtk.AccessibleRole.HEADING)
        self.hero_title.set_width_chars(1)
        texts.append(self.hero_title)
        self.hero_description = label(description, css=("hero-description",))
        self.hero_description.set_width_chars(1)
        self.hero_description.set_visible(bool(description))
        texts.append(self.hero_description)
        wrap.append(texts)
        self.hero_actions = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER, halign=Gtk.Align.END)
        wrap.append(self.hero_actions)
        self.hero.append(wrap)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.body.add_css_class("page-body")
        inner: Gtk.Widget = self.body
        if clamp:
            inner = Adw.Clamp(maximum_size=BODY_MAX, tightening_threshold=BODY_TIGHTEN, child=self.body)
        if scroll:
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            content.append(self.hero)
            content.append(inner)
            self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            self.scroller.set_child(content)
            self.append(self.scroller)
        else:
            self.scroller = None
            self.append(self.hero)
            inner.set_vexpand(True)
            self.append(inner)

    def add(self, widget: Gtk.Widget) -> Gtk.Widget:
        self.body.append(widget)
        return widget

    def add_hero_action(self, widget: Gtk.Widget) -> Gtk.Widget:
        self.hero_actions.append(widget)
        return widget

    def set_description(self, text: str) -> None:
        self.hero_description.set_text(text)
        self.hero_description.set_visible(bool(text))

    def on_shown(self) -> None:
        """A página ficou visível: atualiza o que for necessário (sem bloquear)."""

    def on_hidden(self) -> None:
        """A página saiu de vista."""

    def scroll_to_top(self) -> None:
        if self.scroller is not None:
            self.scroller.get_vadjustment().set_value(0)


def group(title: str = "", description: str = "") -> Adw.PreferencesGroup:
    widget = Adw.PreferencesGroup()
    if title:
        widget.set_title(title)
    if description:
        widget.set_description(description)
    return widget


def advanced_expander(title: str, subtitle: str = "") -> Adw.ExpanderRow:
    row = Adw.ExpanderRow(title=title, subtitle=subtitle)
    row.add_prefix(Gtk.Image.new_from_icon_name("emblem-system-symbolic"))
    return row
