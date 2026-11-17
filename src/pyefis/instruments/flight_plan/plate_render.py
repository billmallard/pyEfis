#  SPDX-License-Identifier: GPL-2.0-or-later
"""Draws a d-TPP plate's page to a ``QImage`` (PA12, billmallard/pyEfis#241,
AER-1611).

A d-TPP plate is a single-page vector PDF (makerplane-data
``docs/dtpp_plates_spike.md``), so this is a page renderer, not a tile
reprojector: Qt's own PDF module (``PyQt6.QtPdf``, Qt PDF over PDFium)
rasterises the page at the size the pane asks for. That module ships in
the PyQt6 wheel; Debian packages it apart, as ``python3-pyqt6.qtpdf``. When
it is missing, ``available`` is False and ``unavailable_reason`` says what
to install -- the viewer shows that, and nothing raises
(construct-never-raises, CLAUDE.md).

The page comes back on white paper: a d-TPP PDF paints no background,
so its unpainted area would otherwise be transparent and show the pane's
black through it, under black ink. Rendering a plate costs about 0.1 s on the bench's x86 and more on a Pi,
so the last few images are kept, keyed by chart and pixel size.
"""

import logging
from collections import OrderedDict

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QSize, Qt
from PyQt6.QtGui import QImage, QPainter

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtPdf import QPdfDocument
except ImportError:  # Debian: python3-pyqt6.qtpdf is a separate package
    QPdfDocument = None

#: How many rendered images to keep (fit and zoomed sizes of recent charts).
CACHE_SIZE = 4


class PlateRenderer:
    """Renders page 1 of one PDF at a time; switching charts reloads."""

    def __init__(self):
        self._doc = None
        self._buf = None
        self._doc_key = None
        self._images = OrderedDict()

    @property
    def available(self):
        return QPdfDocument is not None

    @property
    def unavailable_reason(self):
        if self.available:
            return ""
        return "PLATE RENDERER NOT INSTALLED (python3-pyqt6.qtpdf)"

    def _load(self, key, fetch):
        if self._doc_key == key:
            return self._doc
        self._doc = self._buf = None
        self._doc_key = key
        data = fetch()
        if not data:
            return None
        buf = QBuffer()
        buf.setData(QByteArray(data))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        doc = QPdfDocument(None)
        doc.load(buf)
        if doc.status() != QPdfDocument.Status.Ready or doc.pageCount() < 1:
            logger.warning("plate %s: cannot load (%s)", key, doc.error())
            return None
        # The document reads from the buffer for as long as it is open.
        self._doc, self._buf = doc, buf
        return doc

    def page_size(self, key, fetch):
        """The page's size in points as ``(width, height)``, or None when the
        PDF cannot be read. *fetch()* returns the PDF named *key* as bytes;
        it is called only when that PDF is not the one already open."""
        if not self.available:
            return None
        try:
            doc = self._load(key, fetch)
            if doc is None:
                return None
            size = doc.pagePointSize(0)
            if size.width() <= 0 or size.height() <= 0:
                return None
            return size.width(), size.height()
        except Exception:
            logger.warning("plate %s: page size failed", key, exc_info=True)
            return None

    def render(self, key, fetch, width, height):
        """Page 1 of the PDF named *key* drawn at *width* x *height* pixels,
        or None when it cannot be drawn. *fetch* is as for :meth:`page_size`."""
        width, height = int(width), int(height)
        if not self.available or width <= 0 or height <= 0:
            return None
        cache_key = (key, width, height)
        image = self._images.get(cache_key)
        if image is not None:
            self._images.move_to_end(cache_key)
            return image
        try:
            doc = self._load(key, fetch)
            if doc is None:
                return None
            ink = doc.render(0, QSize(width, height))
            if ink is None or ink.isNull():
                return None
            # A d-TPP page paints no paper: what it leaves unpainted comes
            # back transparent, and on the pane's black that hides the
            # black ink. Lay it on white.
            image = QImage(ink.size(), QImage.Format.Format_RGB32)
            image.fill(Qt.GlobalColor.white)
            p = QPainter(image)
            p.drawImage(QPoint(0, 0), ink)
            p.end()
        except Exception:
            logger.warning("plate %s: render failed", key, exc_info=True)
            return None
        self._images[cache_key] = image
        while len(self._images) > CACHE_SIZE:
            self._images.popitem(last=False)
        return image
