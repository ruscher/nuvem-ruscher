"""QR code desenhado com Gtk.Snapshot: nítido em qualquer escala e sem arquivos temporários."""

from __future__ import annotations

from gi.repository import Gdk, Graphene, Gtk

from nuvem_ruscher.i18n import _

BLACK = Gdk.RGBA()
BLACK.parse("#000000")


def qr_matrix(text: str) -> list[list[bool]]:
    import qrcode  # importação tardia: só quando a tela do celular aparece

    qr = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    return [[bool(cell) for cell in row] for row in qr.get_matrix()]


class QrCode(Gtk.Widget):
    __gtype_name__ = "NuvemRuscherQrCode"

    def __init__(self, text: str = "", size: int = 176, description: str = "") -> None:
        super().__init__()
        self._size = size
        self._matrix: list[list[bool]] = []
        self.text = ""
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_accessible_role(Gtk.AccessibleRole.IMG)
        if text:
            self.set_text(text, description)

    def set_text(self, text: str, description: str = "") -> None:
        """``description`` diz para que serve o código (leitores de tela); o texto vai junto."""
        self.text = text
        self._matrix = qr_matrix(text)
        label = _("QR code for {text}").format(text=text)
        if description:
            label = _("{description}: {text}").format(description=description, text=text)
        self.update_property([Gtk.AccessibleProperty.LABEL], [label])
        self.queue_draw()

    def do_measure(self, orientation: Gtk.Orientation, for_size: int) -> tuple[int, int, int, int]:
        return self._size, self._size, -1, -1

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        if not self._matrix:
            return
        count = len(self._matrix)
        width = self.get_width()
        height = self.get_height()
        side = min(width, height)
        module = side / count
        x0 = (width - module * count) / 2
        y0 = (height - module * count) / 2
        for row_index, row in enumerate(self._matrix):
            start = None
            for col_index, dark in enumerate([*row, False]):
                if dark and start is None:
                    start = col_index
                elif not dark and start is not None:
                    rect = Graphene.Rect().init(
                        x0 + start * module,
                        y0 + row_index * module,
                        (col_index - start) * module + 0.4,  # evita frestas por arredondamento
                        module + 0.4,
                    )
                    snapshot.append_color(BLACK, rect)
                    start = None


def qr_frame(qr: QrCode) -> Gtk.Widget:
    """Moldura branca arredondada (zona de silêncio que as câmeras precisam)."""
    frame = Gtk.Box(halign=Gtk.Align.CENTER)
    frame.add_css_class("qr-frame")
    frame.append(qr)
    return frame
