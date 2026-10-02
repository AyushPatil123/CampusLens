from io import BytesIO
from pathlib import Path
from dataclasses import dataclass
import re
import unicodedata

from pypdf import PdfReader
from .config import Settings
from .ocr import recognize_page


@dataclass(frozen=True)
class ExtractionResult:
    pages: list[tuple[int, str]]
    warnings: list[str]


def clean_text(text: str) -> str:
    """Normalize formatting without guessing words, numbers, or ordinary hyphens."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.translate(str.maketrans({"\u00a0": " ", "\u200b": None, "\ufeff": None, "\u00ad": None}))
    text = "".join(char for char in text if char in "\n\t" or unicodedata.category(char) != "Cc")
    text = "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def quality_warnings(number: int, raw: str) -> list[str]:
    warnings = []
    bad = sum(char == "\ufffd" or (unicodedata.category(char) == "Cc" and char not in "\n\r\t") for char in raw)
    if bad:
        warnings.append(f"Page {number} contains unrecognized or control characters; verify the original source.")
    words = raw.split()
    if len(words) >= 20 and sum(len(word) == 1 and word.isalpha() for word in words) / len(words) > 0.35:
        warnings.append(f"Page {number} may contain fragmented text; verify the original source.")
    return warnings


def extract_pages(filename: str, data: bytes, *, settings: Settings | None = None) -> ExtractionResult:
    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        try:
            raw = data.decode("utf-8-sig")
            return ExtractionResult([(1, clean_text(raw))], quality_warnings(1, raw))
        except UnicodeDecodeError as exc:
            raise ValueError("Text files must be UTF-8 encoded") from exc
    if suffix == ".pdf":
        try:
            reader = PdfReader(BytesIO(data))
            pages = [(number, page.extract_text() or "") for number, page in enumerate(reader.pages, 1)]
        except Exception as exc:
            raise ValueError("Could not read this PDF") from exc
        warnings = []
        empty = [number for number, text in pages if not clean_text(text)]
        if settings and settings.ocr_enabled and len(empty) > settings.ocr_max_pages:
            raise ValueError(f"PDF needs OCR on {len(empty)} pages, exceeding the configured limit of {settings.ocr_max_pages}")
        cleaned = []
        for number, raw in pages:
            if not clean_text(raw) and settings and settings.ocr_enabled:
                raw = recognize_page(data, number, settings)
                warnings.append(f"Page {number} used OCR; verify names, dates, numbers, and table relationships against the original.")
            warnings.extend(quality_warnings(number, raw))
            text = clean_text(raw)
            if not text:
                warnings.append(f"Page {number} has no extractable text; it may need OCR.")
            cleaned.append((number, text))
        return ExtractionResult(cleaned, warnings)
    raise ValueError("Only .pdf and .txt files are supported")


def chunk_pages(pages: list[tuple[int, str]], size: int = 900, overlap: int = 120) -> list[tuple[int, str]]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Chunk size must be positive and overlap must be smaller than size")
    chunks = []
    for page, raw in pages:
        text = clean_text(raw)
        start = 0
        covered_end = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                window = text[start:end + 1]
                # Prefer paragraph, sentence, then word boundaries. Existing
                # newlines are retained so headings and lists remain visible.
                boundary = 0
                for pattern in (r"\n\s*\n", r"(?<=[.!?])\s+(?=[A-Z0-9])", r"\s+"):
                    candidates = [match.start() for match in re.finditer(pattern, window) if start + match.start() > covered_end]
                    if candidates:
                        boundary = candidates[-1]
                        break
                if boundary:
                    end = start + boundary
            chunk = text[start:end].strip()
            if chunk:
                chunks.append((page, chunk))
            if end == len(text):
                break
            covered_end = end
            # Reuse complete words from the previous chunk, with a boundary
            # beyond the already covered text to guarantee forward progress.
            tail = list(re.finditer(r"\S+", text[start:end]))
            next_start = end
            for word in reversed(tail):
                candidate = start + word.start()
                if end - candidate > overlap or candidate <= start:
                    break
                next_start = candidate
            start = max(start + 1, next_start)
            while start < len(text) and text[start].isspace():
                start += 1
    return chunks
