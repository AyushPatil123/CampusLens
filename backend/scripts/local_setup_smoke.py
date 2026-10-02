"""Check README's local server path with a fresh temporary database, without model calls."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx


def main():
    with tempfile.TemporaryDirectory(prefix="campuslens-setup-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, CAMPUSLENS_DB=str(Path(directory) / "index.sqlite3"),
                   CAMPUSLENS_MODE="local", CAMPUSLENS_AUTH_USERNAME="", CAMPUSLENS_AUTH_PASSWORD="")
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Fresh backend failed to start")
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Fresh backend did not become healthy")
                assert client.get("/documents").json() == []
                answer = client.post("/ask", json={"question": "When is tuition due?"})
                assert answer.status_code == 200 and answer.json()["citations"] == []
                assert Path(env["CAMPUSLENS_DB"]).is_file()
                print("Fresh local server: health, empty documents, no-evidence answer, and database creation passed. No model calls.")
        finally:
            process.terminate()
            process.wait(timeout=15)


if __name__ == "__main__":
    main()
