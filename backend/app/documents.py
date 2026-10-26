"""Resume text extraction with size, page and archive-expansion limits."""
import io, zipfile
from pypdf import PdfReader
from docx import Document

MAX_BYTES = 5_000_000
MAX_CHARS = 100_000

def resume_text(name: str, raw: bytes) -> str:
    """Raise ValueError with a user-safe message for unsupported or unsafe documents."""
    lower = name.lower()
    if lower.endswith('.pdf') and raw.startswith(b'%PDF-'):
        doc = PdfReader(io.BytesIO(raw))
        if doc.is_encrypted or len(doc.pages) > 20: raise ValueError('Encrypted or oversized PDF')
        content = '\n'.join(page.extract_text() or '' for page in doc.pages)
    elif lower.endswith('.docx') and raw.startswith(b'PK'):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if sum(x.file_size for x in z.infolist()) > 20_000_000 or len(z.infolist()) > 1000: raise ValueError('Expanded document too large')
            if 'word/document.xml' not in z.namelist(): raise ValueError('Invalid DOCX')
        doc = Document(io.BytesIO(raw))
        content = '\n'.join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for row in t.rows for c in row.cells])
    else: raise ValueError('Only PDF and DOCX files are accepted')
    if not content.strip() or len(content) > MAX_CHARS: raise ValueError('Document needs accessible text within 100,000 characters; OCR is not available')
    return content
