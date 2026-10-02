"""Optional local OCR: bounded PDF rendering and Tesseract, without model calls."""
from io import BytesIO
import math
import os
import re
import shutil
import subprocess
from threading import Lock

from .config import Settings


# PDFium is not thread-safe, even across different documents.
_render_lock = Lock()
MAX_RENDER_PIXELS = 12_000_000
OCR_DPI = 200


def validate_ocr_settings(settings: Settings) -> None:
    if not 1 <= settings.ocr_max_pages <= 100:
        raise ValueError("OCR page limit must be between 1 and 100")
    if not 1 <= settings.ocr_timeout_seconds <= 60:
        raise ValueError("OCR timeout must be between 1 and 60 seconds")
    if not re.fullmatch(r"[a-zA-Z0-9_]+(?:\+[a-zA-Z0-9_]+)*", settings.ocr_language):
        raise ValueError("OCR language must contain Tesseract language codes, e.g. eng or eng+hin")


def render_page(data: bytes, page_number: int) -> bytes:
    try:
        import pypdfium2 as pdfium
        from PIL import Image  # noqa: F401 -- verifies the optional image dependency
    except ImportError:
        raise ValueError("OCR requires the optional dependencies: run uv sync --extra dev --extra ocr") from None
    with _render_lock:
        try:
            with pdfium.PdfDocument(data) as document:
                page = document[page_number - 1]
                try:
                    scale = OCR_DPI / 72
                    width, height = page.get_size()
                    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                        raise ValueError("OCR page has invalid dimensions")
                    if math.ceil(width * scale) * math.ceil(height * scale) > MAX_RENDER_PIXELS:
                        raise ValueError("OCR page exceeds the 12 million pixel rendering limit")
                    bitmap = page.render(scale=scale)
                    try:
                        image = bitmap.to_pil()
                        try:
                            output = BytesIO()
                            image.save(output, format="PNG")
                            return output.getvalue()
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        except ValueError:
            raise
        except Exception:
            raise ValueError(f"Could not render page {page_number} for OCR") from None


def recognize_page(data: bytes, page_number: int, settings: Settings) -> str:
    validate_ocr_settings(settings)
    command = shutil.which(settings.ocr_command)
    if not command:
        raise ValueError("OCR is enabled but Tesseract is unavailable; install it or set CAMPUSLENS_OCR_COMMAND")
    image = render_page(data, page_number)
    try:
        result = subprocess.run(
            [command, "stdin", "stdout", "-l", settings.ocr_language, "--dpi", str(OCR_DPI)],
            input=image, capture_output=True, timeout=settings.ocr_timeout_seconds,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        raise ValueError(f"OCR timed out on page {page_number}; document was not indexed") from None
    except OSError:
        raise ValueError("Could not start Tesseract; check the OCR executable configuration") from None
    if result.returncode:
        raise ValueError(f"OCR failed on page {page_number}; check Tesseract and installed language data")
    return result.stdout.decode("utf-8", errors="replace")
