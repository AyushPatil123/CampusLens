from io import BytesIO
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app.config import Settings
from app.documents import chunk_pages, clean_text, extract_pages
from app.main import create_app
from app import ocr
from test_ingestion import FakeProvider, make_pdf


def test_cleanup_preserves_policy_values_and_paragraphs():
    raw = "\ufeffPolicy\u00a0AB-123\r\n\r\nDue October 15, 2026. Fee: $1,250.\u200b\x00\nPart-time stu\u00addents."
    cleaned = clean_text(raw)
    assert cleaned == "Policy AB-123\n\nDue October 15, 2026. Fee: $1,250.\nPart-time students."
    result = extract_pages("policy.txt", raw.encode("utf-8"))
    assert result.pages == [(1, cleaned)]
    assert "control characters" in result.warnings[0]


def test_fragmented_text_warns_without_guessing_words():
    text = " ".join("abcdefghijklmnopqrstuvwxyz")
    result = extract_pages("fragmented.txt", text.encode())
    assert result.pages[0][1] == text
    assert "fragmented" in result.warnings[0]


def test_paragraph_and_sentence_boundaries_and_page_identity():
    paragraphs = "Heading\n\nFirst policy sentence. Another policy sentence.\n\nSecond paragraph stays together."
    chunks = chunk_pages([(3, paragraphs), (7, "Other page.")], size=70, overlap=0)
    assert chunks == [(3, "Heading\n\nFirst policy sentence. Another policy sentence."),
                      (3, "Second paragraph stays together."), (7, "Other page.")]
    assert chunk_pages([(1, "First sentence. Second sentence. Third sentence.")], size=34, overlap=0) == [
        (1, "First sentence. Second sentence."), (1, "Third sentence.")]


@pytest.mark.parametrize("size,overlap", [(1, 0), (18, 6), (30, 29), (80, 12)])
def test_chunk_limits_progress_and_content_coverage(size, overlap):
    text = "Heading\n\n" + " ".join(f"word{i}" for i in range(30)) + "\n" + "".join(chr(0x400 + i) for i in range(160))
    chunks = chunk_pages([(2, text)], size=size, overlap=overlap)
    assert all(page == 2 and 0 < len(chunk) <= size for page, chunk in chunks)
    assert len(chunks) <= len(text)
    # Strip overlap by walking the source monotonically; every non-whitespace
    # character must be covered, even a token longer than the chunk limit.
    covered = set()
    search_start = 0
    for _, chunk in chunks:
        start = text.find(chunk, search_start)
        assert start >= 0
        covered.update(range(start, start + len(chunk)))
        search_start = start + 1
    assert all(i in covered for i, char in enumerate(text) if not char.isspace())


def test_ocr_only_empty_pages_preserves_citation_and_warnings(tmp_path, monkeypatch):
    calls = []

    def recognize(data, page, settings):
        calls.append(page)
        return "Tuition is due on August 15."

    monkeypatch.setattr("app.documents.recognize_page", recognize)
    settings = Settings(db_path=tmp_path / "ocr.sqlite3", ocr_enabled=True)
    result = extract_pages("mixed.pdf", make_pdf(), settings=settings)
    assert calls == [2]
    assert [page for page, _ in result.pages] == [1, 2, 3]
    assert "used OCR" in result.warnings[0]
    client = TestClient(create_app(settings, FakeProvider()))
    response = client.post("/documents", files={"file": ("mixed.pdf", make_pdf())})
    assert response.status_code == 201
    assert any("OCR" in warning for warning in client.get("/documents").json()[0]["extraction_warnings"])
    answer = client.post("/ask", json={"question": "When is tuition due?"})
    assert answer.status_code == 200
    assert answer.json()["citations"][0]["page"] in {2, 3}
    # OCR-enabled text files do not invoke the renderer.
    extract_pages("policy.txt", b"Policy text", settings=settings)
    assert calls == [2, 2]


def test_ocr_page_limit_rejects_before_work(tmp_path, monkeypatch):
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(612, 792)
    data = BytesIO()
    writer.write(data)
    monkeypatch.setattr("app.documents.recognize_page", lambda *args: pytest.fail("OCR must not start"))
    with pytest.raises(ValueError, match="exceeding"):
        extract_pages("scan.pdf", data.getvalue(), settings=Settings(ocr_enabled=True, ocr_max_pages=1))


def test_ocr_failure_preserves_old_index_before_embedding(tmp_path, monkeypatch):
    class CountingProvider(FakeProvider):
        calls = 0

        def embed_documents(self, texts):
            self.calls += 1
            return super().embed_documents(texts)

    provider = CountingProvider()
    client = TestClient(create_app(Settings(db_path=tmp_path / "rollback.sqlite3", ocr_enabled=True), provider))
    first = client.post("/documents", files={"file": ("policy.txt", b"Original tuition policy")}).json()

    def fail(*args):
        raise ValueError("OCR timed out on page 2; document was not indexed")

    monkeypatch.setattr("app.documents.recognize_page", fail)
    response = client.put(f"/documents/{first['id']}", files={"file": ("mixed.pdf", make_pdf())})
    assert response.status_code == 422
    assert provider.calls == 1
    assert client.get("/documents").json()[0]["sha256"] == first["sha256"]


def test_ocr_missing_engine_and_timeout_are_clear(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="Tesseract is unavailable"):
        ocr.recognize_page(b"pdf", 1, Settings())
    monkeypatch.setattr(ocr.shutil, "which", lambda _: "tesseract")
    monkeypatch.setattr(ocr, "render_page", lambda *args: b"png")

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 10
        raise subprocess.TimeoutExpired(args[0], 10)

    monkeypatch.setattr(ocr.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="timed out on page 4"):
        ocr.recognize_page(b"pdf", 4, Settings())


def test_ocr_output_and_errors_do_not_leak_engine_messages(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda _: "tesseract")
    monkeypatch.setattr(ocr, "render_page", lambda *args: b"png")
    monkeypatch.setattr(ocr.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, b"Policy\n", b""))
    assert ocr.recognize_page(b"pdf", 1, Settings()) == "Policy\n"
    monkeypatch.setattr(ocr.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, b"", b"private/path"))
    with pytest.raises(ValueError, match="installed language data") as exc:
        ocr.recognize_page(b"pdf", 1, Settings())
    assert "private" not in str(exc.value)


def test_missing_optional_renderer_has_setup_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    with pytest.raises(ValueError, match="optional dependencies"):
        ocr.render_page(b"pdf", 1)


def test_ocr_empty_result_and_image_only_rejection(tmp_path, monkeypatch):
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    output = BytesIO()
    writer.write(output)
    monkeypatch.setattr("app.documents.recognize_page", lambda *args: " \n")
    settings = Settings(db_path=tmp_path / "empty.sqlite3", ocr_enabled=True)
    result = extract_pages("blank.pdf", output.getvalue(), settings=settings)
    assert result.pages == [(1, "")]
    assert any("no extractable text" in warning for warning in result.warnings)
    client = TestClient(create_app(settings, FakeProvider()))
    assert client.post("/documents", files={"file": ("blank.pdf", output.getvalue())}).status_code == 422
    assert client.get("/documents").json() == []


def image_pdf():
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    ImageFont = pytest.importorskip("PIL.ImageFont")
    image = Image.new("RGB", (1400, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.text((60, 100), "Tuition is due on August 15.", fill="black", font=ImageFont.load_default(size=52))
    output = BytesIO()
    image.save(output, "PDF", resolution=150)
    image.close()
    return output.getvalue()


def test_real_renderer_and_pixel_limit():
    pytest.importorskip("pypdfium2")
    data = image_pdf()
    assert not PdfReader(BytesIO(data)).pages[0].extract_text().strip()
    assert ocr.render_page(data, 1).startswith(b"\x89PNG")
    writer = PdfWriter()
    writer.add_blank_page(20000, 20000)
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match="pixel"):
        ocr.render_page(output.getvalue(), 1)


def test_real_tesseract_image_only_pdf():
    if not shutil.which(Settings().ocr_command):
        pytest.skip("Tesseract engine unavailable; CI installs it")
    pytest.importorskip("pypdfium2")
    result = extract_pages("scan.pdf", image_pdf(), settings=Settings(ocr_enabled=True))
    assert "August 15" in result.pages[0][1]
    assert "used OCR" in result.warnings[0]


@pytest.mark.parametrize("kwargs", [{"ocr_max_pages": 0}, {"ocr_timeout_seconds": 0}, {"ocr_language": "--evil"}])
def test_invalid_ocr_settings(kwargs):
    with pytest.raises(ValueError):
        ocr.validate_ocr_settings(Settings(**kwargs))
