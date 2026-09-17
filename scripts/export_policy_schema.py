"""Generate or verify the committed Investment Policy JSON Schema."""

import argparse
import json
from pathlib import Path

from investment_os.application.policy_schema import InvestmentPolicySchema

OUTPUT = Path("docs/schemas/investment-policy-v1.json")


def rendered_schema() -> str:
    return json.dumps(InvestmentPolicySchema.model_json_schema(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered_schema()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"{OUTPUT} is stale; run this script without --check")
        print(f"{OUTPUT} is current")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
