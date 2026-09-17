"""Run detect-secrets against tracked and untracked repository files."""

import shutil
import subprocess


def repository_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main() -> None:
    hook = shutil.which("detect-secrets-hook")
    if hook is None:
        raise SystemExit("detect-secrets-hook is not installed; run uv sync --frozen --group dev")
    files = repository_files()
    if not files:
        raise SystemExit("no repository files found to scan")
    subprocess.run([hook, "--baseline", ".secrets.baseline", *files], check=True)
    print(f"Secret scan passed for {len(files)} repository files.")


if __name__ == "__main__":
    main()
