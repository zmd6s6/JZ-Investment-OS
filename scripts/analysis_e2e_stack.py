"""Disposable MVP203 API/Worker plus explicit loopback synthetic model fixture."""

import argparse
import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database-url", required=True)
parser.add_argument("--port", type=int, default=18114)
args = parser.parse_args()
url = urlparse(args.database_url)
if (
    url.scheme != "postgresql+asyncpg"
    or url.hostname not in {"127.0.0.1", "localhost"}
    or not url.path.endswith(("_analysis_synthetic", "_mvp203_browser"))
):
    raise SystemExit(
        "Only explicitly named disposable loopback analysis synthetic databases are allowed"
    )
root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root))
from scripts.analysis_fixture import model_output  # noqa: E402 - explicit project path above

for key in list(os.environ):
    if key.startswith("INVESTMENT_OS_"):
        del os.environ[key]
runtime = tempfile.TemporaryDirectory(prefix="mvp203-browser-synthetic-")
os.environ.update(
    {
        "INVESTMENT_OS_DATABASE_URL": args.database_url,
        "INVESTMENT_OS_SECRET_STORE_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode(),
        "INVESTMENT_OS_SECRET_STORE_PATH": str(Path(runtime.name) / "provider-secrets.json"),
        "INVESTMENT_OS_API_WRITE_TOKEN": "synthetic-mvp203-only",
        "INVESTMENT_OS_WORKER_POLL_SECONDS": "1",
        "INVESTMENT_OS_WORKER_READY_FILE": str(Path(runtime.name) / "worker-ready"),
    }
)
release = threading.Event()
release.set()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if self.path == "/control/hold":
            release.clear()
            output = {"held": True}
        elif self.path == "/control/release":
            release.set()
            output = {"released": True}
        else:
            release.wait(25)
            wrapper = json.loads(data["messages"][1]["content"])
            value = (
                {"invalid": True}
                if data.get("model") == "synthetic-invalid-cio" and wrapper["role"] == "CIO"
                else model_output(wrapper)
            )
            output = {
                "choices": [{"message": {"content": json.dumps(value)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }
        body = json.dumps(output).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


(root / ".runtime").mkdir(exist_ok=True)
server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
(root / ".runtime" / "mvp203-model-fixture.json").write_text(
    json.dumps(
        {
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "control_url": f"http://127.0.0.1:{server.server_port}",
            "fixture": "explicit-synthetic-no-paid-calls",
        }
    )
)
from alembic import command  # noqa: E402 - clear inherited runtime settings first
from alembic.config import Config  # noqa: E402

command.upgrade(Config("alembic.ini"), "head")
log = (root / ".runtime" / "mvp203-browser-worker.log").open("w", encoding="utf-8")
worker = subprocess.Popen(
    [sys.executable, "-m", "investment_os.worker"],
    env=os.environ.copy(),
    stdout=log,
    stderr=subprocess.STDOUT,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
)
try:
    import uvicorn

    uvicorn.run(
        "investment_os.api.bootstrap:app",
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
    )
finally:
    release.set()
    worker.terminate()
    worker.wait(timeout=10)
    server.shutdown()
    log.close()
    runtime.cleanup()
