"""Trusted local-launch entry point; stdout is consumed privately by the launcher."""

import json

from investment_os.infrastructure.local_access import LocalAccessStore, local_origin
from investment_os.infrastructure.settings import get_settings


def main() -> None:
    settings = get_settings()
    if settings.api_auth_mode != "local_session":
        raise SystemExit("本部署未启用本机会话。")
    origin = local_origin(settings.local_origin)
    store = LocalAccessStore(settings.local_access_store_path)
    print(json.dumps({"origin": origin, "code": store.issue_pairing(origin)}))


if __name__ == "__main__":
    main()
