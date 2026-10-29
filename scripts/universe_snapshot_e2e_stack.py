"""Production API on a disposable, explicitly named loopback source-intake database.

No Worker, model fixture or external source is started: this slice only imports explicit files
and performs local deterministic reads. Never accepts an Owner database or port.
"""

import argparse
import base64
import os
import secrets
import tempfile
from pathlib import Path
from urllib.parse import urlparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database-url", required=True)
parser.add_argument("--port", type=int, default=18113)
args = parser.parse_args()
url = urlparse(args.database_url)
if (
    url.scheme != "postgresql+asyncpg"
    or url.hostname not in {"127.0.0.1", "localhost"}
    or url.port != 15441
    or not url.path.endswith("_universe_synthetic")
    or args.port != 18113
):
    raise SystemExit(
        "Only the MVP402 disposable loopback universe synthetic database/ports are allowed"
    )
root = Path(__file__).resolve().parents[1]
os.chdir(root)
for key in list(os.environ):
    if key.startswith("INVESTMENT_OS_"):
        del os.environ[key]
temporary = tempfile.TemporaryDirectory(prefix="mvp402-universe-synthetic-")
os.environ.update(
    {
        "INVESTMENT_OS_DATABASE_URL": args.database_url,
        "INVESTMENT_OS_SECRET_STORE_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode(),
        "INVESTMENT_OS_SECRET_STORE_PATH": str(Path(temporary.name) / "secrets.json"),
        "INVESTMENT_OS_API_WRITE_TOKEN": "synthetic-mvp402-only",
    }
)
from alembic import command  # noqa: E402 - isolate inherited settings before application imports
from alembic.config import Config  # noqa: E402

command.upgrade(Config(str(root / "alembic.ini")), "head")
try:
    import uvicorn

    uvicorn.run(
        "investment_os.api.bootstrap:app",
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level="warning",
    )
finally:
    temporary.cleanup()
