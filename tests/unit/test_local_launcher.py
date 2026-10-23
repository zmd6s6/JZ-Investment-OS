import runpy

import pytest

choose_container = runpy.run_path("scripts/open_local_ui.py")["choose_container"]


def container(host_ip: str = "127.0.0.1", port: str = "18102") -> dict[str, object]:
    return {
        "Id": "synthetic-container",
        "Config": {
            "Labels": {"com.docker.compose.service": "investment-api"},
            "Env": [
                "INVESTMENT_OS_API_AUTH_MODE=local_session",
                "INVESTMENT_OS_LOCAL_ORIGIN=http://127.0.0.1:18102",
            ],
        },
        "NetworkSettings": {"Ports": {"8000/tcp": [{"HostIp": host_ip, "HostPort": port}]}},
    }


def test_local_launcher_selects_only_matching_loopback_deployment() -> None:
    assert choose_container([container()], None) == (
        "synthetic-container",
        "http://127.0.0.1:18102",
    )


@pytest.mark.parametrize("host_ip", ["0.0.0.0", "::", "192.168.1.2"])
def test_local_launcher_refuses_wildcard_or_remote_publish(host_ip: str) -> None:
    with pytest.raises(ValueError):
        choose_container([container(host_ip)], None)


def test_local_launcher_does_not_guess_between_multiple_deployments() -> None:
    with pytest.raises(ValueError):
        choose_container([container(), container()], None)
    with pytest.raises(ValueError):
        choose_container([container()], "http://127.0.0.1:9999")
