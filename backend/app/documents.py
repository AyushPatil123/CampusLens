from io import BytesIO
from pathlib import Path
from dataclasses import dataclass

from pypdf import PdfReader


@dataclass(frozen=True)
class ExtractionResult:
    pages: list[tuple[int, str]]
    warnings: list[str]


def extract_pages(filename: str, data: bytes) -> ExtractionResult:
    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        try:
            return ExtractionResult([(1, data.decode("utf-8-sig"))], [])
        except UnicodeDecodeError as exc:
            raise ValueError("Text files must be UTF-8 encoded") from exc
    if suffix == ".pdf":
        try:
            reader = PdfReader(BytesIO(data))
            pages = [(number, page.extract_text() or "") for number, page in enumerate(reader.pages, 1)]
        except Exception as exc:
            raise ValueError("Could not read this PDF") from exc
        warnings = [
            f"Page {number} has no extractable text; it may need OCR."
            for number, text in pages if not text.strip()
        ]
        return ExtractionResult(pages, warnings)
    raise ValueError("Only .pdf and .txt files are supported")


def chunk_pages(pages: list[tuple[int, str]], size: int = 900, overlap: int = 120) -> list[tuple[int, str]]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Chunk size must be positive and overlap must be smaller than size")
    chunks = []
    for page, raw in pages:
        words = raw.split()
        current = []
        length = 0
        for word in words:
            if current and length + len(word) + 1 > size:
                chunks.append((page, " ".join(current)))
                tail = []
                tail_length = 0
                for previous in reversed(current):
                    if tail_length + len(previous) + 1 > overlap:
                        break
                    tail.insert(0, previous)
                    tail_length += len(previous) + 1
                current = tail
                length = len(" ".join(current))
            current.append(word)
            length += len(word) + 1
        if current:
            chunks.append((page, " ".join(current)))
    return chunks
