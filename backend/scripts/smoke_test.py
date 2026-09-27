"""Live Gemini/OpenAI check using Berkeley's exam proctoring policy PDF."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


SOURCE_URL = "https://asc.berkeley.edu/sites/default/files/proctoring_guidlines_2024-10-08.pdf"


def run(pdf_path: Path) -> dict:
    with TemporaryDirectory() as temporary:
        settings = Settings(db_path=Path(temporary) / "smoke.sqlite3")
        app = create_app(settings)
        with TestClient(app) as client:
            upload = client.post(
                "/documents",
                data={
                    "title": "Exam Proctoring Policies & Guidelines for Student Athletes",
                    "source_url": SOURCE_URL,
                    "institution": "UC Berkeley",
                },
                files={"file": (pdf_path.name, pdf_path.read_bytes(), "application/pdf")},
            )
            upload.raise_for_status()
            answerable = client.post(
                "/ask",
                json={"question": "By when must student athletes meet professors about exam conflicts?"},
            )
            answerable.raise_for_status()
            unanswerable = client.post(
                "/ask",
                json={"question": "What is the campus rule for bringing pet iguanas into dormitories?"},
            )
            unanswerable.raise_for_status()
            result = {
                "provider": settings.model_provider,
                "uploaded_pages_with_warnings": upload.json()["extraction_warnings"],
                "answerable": {
                    "answer": answerable.json()["answer"],
                    "citations": [
                        {key: citation[key] for key in ("title", "page", "source_url")}
                        for citation in answerable.json()["citations"]
                    ],
                },
                "unanswerable": unanswerable.json(),
            }
            if not result["answerable"]["citations"]:
                raise AssertionError("Answerable question returned no citation")
            if not any(citation["page"] == 1 and citation["source_url"] == SOURCE_URL
                       for citation in result["answerable"]["citations"]):
                raise AssertionError("Answerable question did not cite the policy page")
            if result["unanswerable"]["citations"]:
                raise AssertionError("Unanswerable question returned a citation")
            if "could not find that in the uploaded documents" not in result["unanswerable"]["answer"].lower():
                raise AssertionError("Unanswerable question did not explicitly refuse")
            return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Local Berkeley exam proctoring policy PDF")
    args = parser.parse_args()
    print(json.dumps(run(args.pdf), indent=2))
