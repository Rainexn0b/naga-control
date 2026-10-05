"""Discover console and dynamically launched modules without importing them."""

from __future__ import annotations

import ast
import importlib.util
import tomllib
from pathlib import Path


def entrypoint_modules(root: Path) -> set[str]:
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get(
            "project", {}
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return set()
    return {
        value.split(":", 1)[0].strip()
        for section in ("scripts", "gui-scripts")
        for value in project.get(section, {}).values()
        if isinstance(value, str)
    }


def launched_module_names(path: Path, *, package_name: str) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            (isinstance(function, ast.Name) and function.id in {"import_module", "__import__"})
            or (isinstance(function, ast.Attribute) and function.attr == "import_module")
        ) and node.args:
            name = _module_string(node.args[0], package_name=package_name)
            if name:
                if name.startswith("."):
                    package = package_name
                    if len(node.args) >= 2:
                        package = _module_string(node.args[1], package_name=package_name) or package
                    for keyword in node.keywords:
                        if keyword.arg == "package":
                            package = (
                                _module_string(keyword.value, package_name=package_name) or package
                            )
                    try:
                        name = importlib.util.resolve_name(name, package)
                    except (ImportError, ValueError):
                        continue
                names.add(name)
        for expression in (*node.args, *(keyword.value for keyword in node.keywords)):
            if not isinstance(expression, (ast.List, ast.Tuple)):
                continue
            # Retain positions so nonliteral tokens cannot fabricate a '-m' pair.
            tokens = [_module_string(item, package_name=package_name) for item in expression.elts]
            for index, token in enumerate(tokens[:-1]):
                if token == "-m" and tokens[index + 1]:
                    names.add(str(tokens[index + 1]))
    return names


def _module_string(expression: ast.expr, *, package_name: str) -> str | None:
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value
    if isinstance(expression, ast.Name) and expression.id == "__package__":
        return package_name
    if isinstance(expression, ast.JoinedStr):
        parts: list[str] = []
        for value in expression.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif (
                isinstance(value, ast.FormattedValue)
                and isinstance(value.value, ast.Name)
                and value.value.id == "__package__"
                and value.conversion == -1
                and value.format_spec is None
            ):
                parts.append(package_name)
            else:
                return None
        return "".join(parts)
    return None
