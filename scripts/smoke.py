"""Verify the running PR-00 API without requiring third-party HTTP libraries."""

import argparse
import json
from typing import Any
from urllib.request import urlopen

from investment_os.api.smoke_contract import validate_health_payload


def fetch_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=5) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise TypeError("health payload must be an object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    args = parser.parse_args()

    live = fetch_json(f"{args.base_url}/health/live")
    ready = fetch_json(f"{args.base_url}/health/ready")
    validate_health_payload(live, expected_status="alive")
    validate_health_payload(ready, expected_status="ready")
    if ready.get("checks") != {"database": "database_ready"}:
        raise ValueError("readiness payload did not prove database availability")
    print("PR-00 smoke test passed: API and PostgreSQL are ready; live trading is disabled.")


if __name__ == "__main__":
    main()
