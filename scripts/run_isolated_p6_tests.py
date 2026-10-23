"""Run destructive integration fixtures only against the named disposable P6 DB."""

import os
import sys
from urllib.parse import urlsplit


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("请明确提供隔离测试库 URL")
    database = sys.argv[1]
    parsed = urlsplit(database)
    if (
        parsed.scheme != "postgresql+asyncpg"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 15433
        or parsed.path != "/investment_os_uxreg_20261015_1046"
    ):
        raise SystemExit("拒绝对非命名隔离库运行清表夹具")
    os.environ["INVESTMENT_OS_TEST_DATABASE_URL"] = database
    os.environ["INVESTMENT_OS_DATABASE_URL"] = database
    os.environ["INVESTMENT_OS_API_AUTH_MODE"] = "bearer"
    print(f"隔离测试目标: {parsed.hostname}:{parsed.port}{parsed.path}", flush=True)
    import pytest

    return pytest.main(sys.argv[2:] or ["-q"])


if __name__ == "__main__":
    raise SystemExit(main())
