"""Pequenos utilitários de interface compartilhados."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gio, Gtk, Pango

from nuvem_ruscher.core.helper_protocol import human_error
from nuvem_ruscher.i18n import N_, _

STATUS_ICONS = {
    "ok": ("nr-status-ok-symbolic", N_("Concluído")),
    "warning": ("nr-status-warning-symbolic", N_("Atenção")),
    "error": ("nr-status-error-symbolic", N_("Problema")),
    "info": ("nr-status-info-symbolic", N_("Informação")),
    "skip": ("nr-status-pending-symbolic", N_("Aguardando")),
    "pending": ("nr-status-pending-symbolic", N_("Aguardando")),
}


def label(
    text: str = "",
    css: tuple[str, ...] = (),
    wrap: bool = True,
    xalign: float = 0.0,
    selectable: bool = False,
    markup: bool = False,
) -> Gtk.Label:
    widget = Gtk.Label(xalign=xalign, wrap=wrap, selectable=selectable)
    if wrap:
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if markup:
        widget.set_markup(text)
    else:
        widget.set_text(text)
    for name in css:
        widget.add_css_class(name)
    return widget


def status_icon(status: str, size: int = 16) -> Gtk.Image:
    name, desc = STATUS_ICONS.get(status, STATUS_ICONS["info"])
    image = Gtk.Image.new_from_icon_name(name)
    image.set_pixel_size(size)
    image.add_css_class("status-icon")
    image.add_css_class(status)
    image.update_property([Gtk.AccessibleProperty.LABEL], [_(desc)])
    return image


def set_status_icon(image: Gtk.Image, status: str) -> None:
    name, desc = STATUS_ICONS.get(status, STATUS_ICONS["info"])
    image.set_from_icon_name(name)
    for cls in STATUS_ICONS:
        image.remove_css_class(cls)
    image.add_css_class(status)
    image.update_property([Gtk.AccessibleProperty.LABEL], [_(desc)])


def icon_button(icon: str, tooltip: str, callback: Callable[[Gtk.Button], None], flat: bool = True) -> Gtk.Button:
    button = Gtk.Button.new_from_icon_name(icon)
    button.set_tooltip_text(tooltip)
    button.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
    button.set_valign(Gtk.Align.CENTER)
    if flat:
        button.add_css_class("flat")
    button.connect("clicked", callback)
    return button


def pill_button(text: str, callback: Callable[[Gtk.Button], None], suggested: bool = False) -> Gtk.Button:
    button = Gtk.Button(label=text, halign=Gtk.Align.CENTER, width_request=160)
    button.add_css_class("pill")
    if suggested:
        button.add_css_class("suggested-action")
    button.connect("clicked", callback)
    return button


def illustration(name: str, size: int = 240) -> Gtk.Image:
    image = Gtk.Image.new_from_icon_name(name)
    image.set_pixel_size(size)
    image.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    return image


def open_uri(widget: Gtk.Widget, uri: str) -> None:
    launcher = Gtk.UriLauncher.new(uri)
    launcher.launch(widget.get_root(), None, None)


def open_folder(widget: Gtk.Widget, path: str) -> None:
    launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(path))
    launcher.launch(widget.get_root(), None, None)


def show_in_folder(widget: Gtk.Widget, path: str) -> None:
    launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(path))
    launcher.open_containing_folder(widget.get_root(), None, None)


def copy_text(widget: Gtk.Widget, text: str) -> None:
    widget.get_clipboard().set(text)


def toast(widget: Gtk.Widget, text: str, timeout: int = 3) -> None:
    root = widget.get_root()
    if root is not None and hasattr(root, "toast"):
        root.toast(text, timeout)


def details_expander(text: str, title: str | None = None) -> Gtk.Expander:
    expander = Gtk.Expander(label=title or _("Detalhes técnicos"))
    content = label(text, css=("monospace", "caption"), selectable=True)
    content.set_margin_top(6)
    scroller = Gtk.ScrolledWindow(
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        propagate_natural_height=True,
        max_content_height=220,
    )
    scroller.set_child(content)
    expander.set_child(scroller)
    return expander


def show_error(
    widget: Gtk.Widget,
    code: str,
    detail: str = "",
    log: list[str] | None = None,
    retry: Callable[[], None] | None = None,
    alternative: tuple[str, Callable[[], None]] | None = None,
) -> None:
    """Erro humano: o que aconteceu, o que fazer, e os detalhes técnicos recolhidos."""
    title, hint = human_error(code)
    dialog = Adw.AlertDialog(heading=title, body=hint)
    technical = "\n".join(([f"código: {code}", detail] if detail else [f"código: {code}"]) + (log or [])[-40:])
    dialog.set_extra_child(details_expander(technical))
    dialog.add_response("close", _("Fechar"))
    if alternative:
        dialog.add_response("alternative", alternative[0])
    if retry:
        dialog.add_response("retry", _("Tentar novamente"))
        dialog.set_response_appearance("retry", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("retry")

    def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
        if response == "retry" and retry:
            retry()
        elif response == "alternative" and alternative:
            alternative[1]()

    dialog.connect("response", on_response)
    dialog.present(widget.get_root())


def confirm(
    widget: Gtk.Widget,
    heading: str,
    body: str,
    confirm_label: str,
    on_confirm: Callable[[], None],
    destructive: bool = False,
    extra: Gtk.Widget | None = None,
    body_markup: bool = False,
) -> Adw.AlertDialog:
    dialog = Adw.AlertDialog(heading=heading, body=body, body_use_markup=body_markup)
    if extra is not None:
        dialog.set_extra_child(extra)
    dialog.add_response("cancel", _("Cancelar"))
    dialog.add_response("confirm", confirm_label)
    dialog.set_response_appearance(
        "confirm", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED
    )
    dialog.set_default_response("cancel" if destructive else "confirm")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, r: on_confirm() if r == "confirm" else None)
    dialog.present(widget.get_root())
    return dialog


def animations_enabled(widget: Gtk.Widget) -> bool:
    settings = widget.get_settings()
    return bool(settings.get_property("gtk-enable-animations"))


def clamp(child: Gtk.Widget, size: int = 600) -> Adw.Clamp:
    return Adw.Clamp(maximum_size=size, tightening_threshold=int(size * 0.7), child=child)
