"""Bounded text extraction for owner-scoped knowledge documents."""
import base64
import binascii
import hashlib
import io
import re
import zipfile
from xml.etree import ElementTree

MAX_BYTES = 128_000
MAX_TEXT = 80_000


def extract(filename, encoded):
    if not isinstance(filename, str) or not 1 <= len(filename) <= 160 or '\x00' in filename or '/' in filename or '\\' in filename:
        raise ValueError('Invalid document name')
    suffix = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if suffix not in ('txt', 'md', 'docx') or not isinstance(encoded, str) or len(encoded) > 180_000:
        raise ValueError('Choose a .txt, .md or .docx document under 128 KB')
    try:
        raw = base64.b64decode(encoded, validate=True)
        if not 1 <= len(raw) <= MAX_BYTES:
            raise ValueError('Document is too large')
        if suffix == 'docx':
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = archive.namelist()
                if len(names) > 100 or '[Content_Types].xml' not in names or 'word/document.xml' not in names:
                    raise ValueError('Invalid DOCX document')
                part = archive.getinfo('word/document.xml')
                if part.file_size > 1_000_000 or part.file_size > 100 * max(part.compress_size, 1):
                    raise ValueError('DOCX text is too large')
                xml = archive.read(part)
                if b'\x00' in xml or re.search(rb'<!\s*(DOCTYPE|ENTITY)', xml, re.I):
                    raise ValueError('DOCX contains unsupported XML declarations')
                root = ElementTree.fromstring(xml)
                paragraphs = []
                for paragraph in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                    line = ''.join(node.text or '' for node in paragraph.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
                    if line.strip(): paragraphs.append(line)
                text = '\n'.join(paragraphs)
        else:
            text = raw.decode('utf-8-sig')
    except (binascii.Error, UnicodeError, zipfile.BadZipFile, RuntimeError, KeyError, ElementTree.ParseError) as exc:
        raise ValueError('Document could not be read as plain text or DOCX') from exc
    text = text.strip()
    if not text or len(text) > MAX_TEXT or '\x00' in text:
        raise ValueError('Document needs readable text under 80,000 characters')
    return text, {'filename': filename, 'kind': suffix, 'sha256': hashlib.sha256(raw).hexdigest(),
                  'bytes': len(raw)}
