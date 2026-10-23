"""从已验证的本机 Docker 部署打开工作台, 不读取任何长效密钥。"""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
import webbrowser
from urllib.parse import urlsplit


def _docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=20,
    )
    return result.stdout


def choose_container(containers: list[dict[str, object]], url: str | None) -> tuple[str, str]:
    candidates: list[tuple[str, str]] = []
    for item in containers:
        config = item.get("Config")
        network = item.get("NetworkSettings")
        if not isinstance(config, dict) or not isinstance(network, dict):
            continue
        labels = config.get("Labels") or {}
        if labels.get("com.docker.compose.service") != "investment-api":
            continue
        environment = dict(
            value.split("=", 1)
            for value in config.get("Env", [])
            if isinstance(value, str) and "=" in value
        )
        if environment.get("INVESTMENT_OS_API_AUTH_MODE") != "local_session":
            continue
        origin = environment.get("INVESTMENT_OS_LOCAL_ORIGIN", "")
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            continue
        bindings = (network.get("Ports") or {}).get("8000/tcp") or []
        if not bindings:
            continue
        # Refuse even one wildcard/remote mapping, including an extra IPv6 mapping.
        if any(not ipaddress.ip_address(binding["HostIp"]).is_loopback for binding in bindings):
            continue
        if not any(int(binding["HostPort"]) == (parsed.port or 80) for binding in bindings):
            continue
        if url is None or url.rstrip("/") == origin:
            candidates.append((str(item["Id"]), origin))
    if len(candidates) != 1:
        raise ValueError(
            "未找到唯一本机部署。请启动 Docker / 本机会话服务; 多部署请用 --url 指定。"
        )
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="打开本机投资工作台, 无需复制开发令牌。")
    parser.add_argument("--url", help="多个部署时指定 http://127.0.0.1:端口")
    parser.add_argument(
        "--no-browser", action="store_true", help="程序集成专用, 输出短效链接; 勿记录。"
    )
    args = parser.parse_args()
    try:
        ids = _docker(
            "ps", "--filter", "label=com.docker.compose.service=investment-api", "-q"
        ).split()
        if not ids:
            raise ValueError("没有运行中的投资工作台, 请先启动 Docker 服务。")
        # Project only non-secret deployment metadata; do not read Config.Env wholesale.
        template = (
            '{"Id":{{json .Id}},"Config":{"Labels":{"com.docker.compose.service":'
            '{{json (index .Config.Labels "com.docker.compose.service")}}},"Env":['
            "{{range .Config.Env}}{{if or "
            '(eq (index (split . "=") 0) "INVESTMENT_OS_API_AUTH_MODE") '
            '(eq (index (split . "=") 0) "INVESTMENT_OS_LOCAL_ORIGIN")}}'
            '{{json .}},{{end}}{{end}}null]},"NetworkSettings":{"Ports":'
            "{{json .NetworkSettings.Ports}}}}"
        )
        containers = [
            json.loads(line) for line in _docker("inspect", "--format", template, *ids).splitlines()
        ]
        container, origin = choose_container(containers, args.url)
        issued = json.loads(
            _docker("exec", container, "python", "-m", "investment_os.api.local_access")
        )
        if issued.get("origin") != origin:
            raise ValueError("本机地址配置不一致, 拒绝配对。")
        code = issued.get("code")
        if (
            not isinstance(code, str)
            or len(code) != 43
            or not all(char.isascii() and (char.isalnum() or char in "-_") for char in code)
        ):
            raise ValueError("未取得有效的一次性配对码。")
        launch_url = f"{origin}/#local-pair={code}"
        if args.no_browser:
            print(json.dumps({"url": launch_url}))
        elif webbrowser.open(launch_url):
            print("已打开本机工作台。浏览器会自动建立会话, 无需填写令牌。")
        else:
            raise ValueError("无法打开默认浏览器, 请检查本机默认浏览器配置。")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
    except (OSError, subprocess.SubprocessError, KeyError, TypeError):
        print("本地启动未完成。请确认 Docker 正在运行、端口仅绑定本机, 再重试。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
