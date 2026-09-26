"""A minimal Excel 97-2003 workbook (.xls, BIFF8 in an OLE2 compound file),
written byte by byte for tests: text, number and date cells on one or more
sheets. It follows Microsoft's published formats ([MS-XLS] records BOF,
XF, BOUNDSHEET, DIMENSIONS, NUMBER, LABEL, EOF; [MS-CFB] version 3 with
512-byte sectors), so no third-party file is needed."""

from __future__ import annotations

import struct
from datetime import datetime

EXCEL_EPOCH = datetime(1899, 12, 30)
SECTOR = 512
END = 0xFFFFFFFE
FREE = 0xFFFFFFFF
FAT_SECTOR = 0xFFFFFFFD
NO_STREAM = 0xFFFFFFFF
#: Cell formats: 0 is General, 1 shows dates and times (built-in format 22).
GENERAL, DATE = 0, 1


def _record(kind: int, body: bytes) -> bytes:
    return struct.pack("<HH", kind, len(body)) + body


def _bof(stream_type: int) -> bytes:
    return _record(0x0809, struct.pack("<HHHHII", 0x0600, stream_type, 0x0DBB, 0x07CC, 0, 6))


def _xf(format_index: int) -> bytes:
    # font 0, the format, a cell style (not a style XF), the rest blank.
    return _record(
        0x00E0, struct.pack("<HHHBBBBIIH", 0, format_index, 0x0001, 0x20, 0, 0, 0, 0, 0, 0x20C0)
    )


def _unicode(text: str, length_bytes: int) -> bytes:
    size = struct.pack("<H" if length_bytes == 2 else "<B", len(text))
    return size + b"\x01" + text.encode("utf-16-le")


def _cell(row: int, column: int, value: object) -> bytes:
    if isinstance(value, datetime):
        serial = (value - EXCEL_EPOCH).total_seconds() / 86_400
        return _record(0x0203, struct.pack("<HHHd", row, column, 16 + DATE, serial))
    if isinstance(value, int | float):
        return _record(0x0203, struct.pack("<HHHd", row, column, 16 + GENERAL, float(value)))
    return _record(0x0204, struct.pack("<HHH", row, column, 16 + GENERAL) + _unicode(str(value), 2))


def _sheet(rows: list[list[object]]) -> bytes:
    width = max((len(row) for row in rows), default=0)
    body = _bof(0x0010) + _record(0x0200, struct.pack("<IIHHH", 0, len(rows), 0, width, 0))
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            if value is not None:
                body += _cell(row_index, column, value)
    return body + _record(0x000A, b"")


def workbook_stream(sheets: dict[str, list[list[object]]]) -> bytes:
    """The BIFF8 ``Workbook`` stream holding these sheets."""
    # 16 style XFs are expected before the cell XFs; the cell XFs 16 and 17
    # are General and a date-time format.
    xfs = b"".join(_xf(0) for _ in range(16)) + _xf(0) + _xf(22)
    head = (
        _bof(0x0005)
        + _record(0x0042, struct.pack("<H", 1200))
        + _record(0x0022, struct.pack("<H", 0))
        + xfs
    )
    bodies = [_sheet(rows) for rows in sheets.values()]
    names = list(sheets)
    bound_sizes = [4 + 6 + len(_unicode(name, 1)) for name in names]
    offset = len(head) + sum(bound_sizes) + 4
    bounds = b""
    for name, body in zip(names, bodies, strict=True):
        bounds += _record(0x0085, struct.pack("<IBB", offset, 0, 0) + _unicode(name, 1))
        offset += len(body)
    return head + bounds + _record(0x000A, b"") + b"".join(bodies)


def _entry(name: str, kind: int, child: int, start: int, size: int) -> bytes:
    encoded = (name + "\0").encode("utf-16-le") if name else b""
    return (
        encoded.ljust(64, b"\0")
        + struct.pack("<HBB", len(encoded), kind, 1)
        + struct.pack("<III", NO_STREAM, NO_STREAM, child)
        + b"\0" * 16
        + b"\0" * 4
        + b"\0" * 16
        + struct.pack("<IQ", start, size)
    )


def compound_file(stream: bytes) -> bytes:
    """An OLE2 compound file holding ``stream`` as ``Workbook``."""
    stream = stream.ljust(4096, b"\0")  # a regular stream, not the mini stream
    sectors = -(-len(stream) // SECTOR)
    fat = [FAT_SECTOR, END] + [2 + i + 1 for i in range(sectors - 1)] + [END]
    fat += [FREE] * (SECTOR // 4 - len(fat))
    assert len(fat) == SECTOR // 4, "the test workbook fits one FAT sector"
    header = (
        bytes.fromhex("d0cf11e0a1b11ae1")
        + b"\0" * 16
        + struct.pack("<HHHHH", 0x003E, 0x0003, 0xFFFE, 9, 6)
        + b"\0" * 6
        + struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, END, 0, END, 0)
        + struct.pack("<I", 0)
        + struct.pack("<I", FREE) * 108
    )
    directory = (
        _entry("Root Entry", 5, 1, END, 0)
        + _entry("Workbook", 2, NO_STREAM, 2, len(stream))
        + _entry("", 0, NO_STREAM, 0, 0) * 2
    )
    return (
        header
        + struct.pack(f"<{len(fat)}I", *fat)
        + directory
        + stream.ljust(sectors * SECTOR, b"\0")
    )


def xls(sheets: dict[str, list[list[object]]]) -> bytes:
    """An .xls file with these sheets (text, numbers and datetimes)."""
    return compound_file(workbook_stream(sheets))
