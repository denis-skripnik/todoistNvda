"""Compile this add-on's singular UTF-8 PO catalogs without build dependencies.

Supports msgid/msgstr and continuation lines. Unsupported PO constructs fail the
build rather than silently producing an incomplete translation. For plurals or
contexts, replace this small compiler with GNU msgfmt.
"""
from __future__ import annotations

import ast
from pathlib import Path
import struct


def read_catalog(path: Path) -> dict[str, str]:
    messages: dict[str, str] = {}
    entry: dict[str, str] = {}
    field = None

    def finish():
        if not entry:
            return
        if set(entry) != {'msgid', 'msgstr'} or not entry['msgstr']:
            raise ValueError(f'{path}: incomplete or empty translation')
        key = entry['msgid']
        if key in messages:
            raise ValueError(f'{path}: duplicate msgid {key!r}')
        messages[key] = entry['msgstr']
        entry.clear()

    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line:
            finish()
            field = None
            continue
        if line.startswith('#'):
            if line.startswith('#,') and 'fuzzy' in line:
                raise ValueError(f'{path}:{number}: fuzzy translation')
            continue
        if line.startswith(('msgid ', 'msgstr ')):
            field, literal = line.split(' ', 1)
            if field == 'msgid' and entry:
                finish()
            if field in entry:
                raise ValueError(f'{path}:{number}: duplicate {field}')
            entry[field] = ''
        elif line.startswith('"') and field:
            literal = line
        else:
            raise ValueError(f'{path}:{number}: unsupported PO syntax')
        value = ast.literal_eval(literal)
        if not isinstance(value, str) or '\0' in value:
            raise ValueError(f'{path}:{number}: invalid catalog string')
        entry[field] += value
    finish()
    return messages


def compile_catalog(path: Path) -> bytes:
    messages = read_catalog(path)
    keys = sorted(messages)
    originals = [key.encode('utf-8') for key in keys]
    translations = [messages[key].encode('utf-8') for key in keys]
    count = len(keys)
    offset = 28 + 16 * count
    tables = bytearray()
    strings = bytearray()
    for group in (originals, translations):
        for value in group:
            tables.extend(struct.pack('<II', len(value), offset + len(strings)))
            strings.extend(value + b'\0')
    return struct.pack('<7I', 0x950412DE, 0, count, 28, 28 + 8 * count, 0, 0) + tables + strings


def build_translations(staging_dir: Path) -> None:
    for source in sorted((staging_dir / 'locale').glob('*/LC_MESSAGES/nvda.po')):
        source.with_suffix('.mo').write_bytes(compile_catalog(source))
