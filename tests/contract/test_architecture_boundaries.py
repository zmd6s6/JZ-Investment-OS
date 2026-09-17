import ast
import sys
from pathlib import Path


def test_domain_has_no_outward_dependencies() -> None:
    domain_root = Path("src/investment_os/domain")
    violations: list[str] = []

    for path in domain_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for name in names:
                top_level = name.partition(".")[0]
                is_domain_import = name == "investment_os.domain" or name.startswith(
                    "investment_os.domain."
                )
                if top_level not in sys.stdlib_module_names and not is_domain_import:
                    violations.append(f"{path}:{node.lineno} imports {name}")

    assert violations == []
