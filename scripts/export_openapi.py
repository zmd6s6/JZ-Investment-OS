"""Generate or verify the committed OpenAPI contract."""

import argparse
import json
from pathlib import Path

from investment_os.api.bootstrap import app

OUTPUT_PATH = Path("docs/schemas/openapi.json")


def render_openapi() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the contract is stale")
    args = parser.parse_args()
    rendered = render_openapi()

    if args.check:
        if not OUTPUT_PATH.is_file() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            raise SystemExit("OpenAPI contract is stale; run scripts/export_openapi.py")
        print("OpenAPI contract is current.")
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
