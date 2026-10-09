"""Bounded, memory-only social preview images for validated reader figures."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping
from threading import Lock
from xml.etree import ElementTree as ET

from quant_trade.audit import raster
from quant_trade.audit.reading import FIELDS

_SVG_NS = "http://www.w3.org/2000/svg"


def _social_svg(svg: str) -> str:
    """Fit the complete 1200x675 card into 1120x630, with 40px side padding.

    The nested SVG's viewBox keeps the original proportions and all text.
    Input is a trusted, server-generated card (the reader's or the calculator's),
    never uploaded SVG.
    """
    card = ET.fromstring(svg)
    card.attrib.update(
        x="40", y="0", width="1120", height="630", preserveAspectRatio="xMidYMid meet"
    )
    wrapper = ET.Element(
        f"{{{_SVG_NS}}}svg",
        {"width": "1200", "height": "630", "viewBox": "0 0 1200 630"},
    )
    ET.SubElement(
        wrapper,
        f"{{{_SVG_NS}}}rect",
        {"width": "1200", "height": "630", "fill": "#f7f6f2"},
    )
    wrapper.append(card)
    return ET.tostring(wrapper, encoding="unicode")


class ReadingPNGCache:
    """Keep at most ``max_entries`` successful PNGs under parameter hashes.

    Locales and the numeric strings named in ``fields`` determine the image:
    by default the reader's eight, and the calculator passes its own four.
    Extra query parameters, including referral tags, do not create cache
    entries. Failed renders are retried on the next request so recovery needs
    no reset.
    """

    def __init__(self, max_entries: int = 256, fields: tuple[str, ...] = FIELDS) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._fields = fields
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._lock = Lock()

    def get(self, locale: str, values: Mapping[str, str], svg: str) -> bytes | None:
        """Return the existing bytes object or render a validated card once."""
        parameters = [locale, [values.get(name, "").strip() for name in self._fields]]
        key = hashlib.sha256(
            json.dumps(parameters, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]
            png = raster.card_png(_social_svg(svg))
            if png is not None:
                self._entries[key] = png
                if len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)
            return png

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
