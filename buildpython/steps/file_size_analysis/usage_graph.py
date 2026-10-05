"""Static import dependency graph and reachability for the src-layout project."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .usage_roots import entrypoint_modules, launched_module_names


@dataclass(frozen=True)
class UsageGraph:
    reverse_adjacency: dict[Path, set[Path]]
    reachable: frozenset[Path]
    external_inbound_counts: dict[Path, int]
    root_paths: frozenset[Path]


def build_usage_graph(root: Path, *, roots: tuple[str, ...]) -> UsageGraph:
    files = sorted(
        path
        for name in roots
        for path in (root / name).rglob("*.py")
        if "__pycache__" not in path.parts
    )
    module_index = {module_name_for_path(root, path): path for path in files}
    adjacency: dict[Path, set[Path]] = {}
    reverse_adjacency: dict[Path, set[Path]] = {}
    for path in files:
        dependencies = _scan_dependencies(root, path, module_index)
        adjacency[path] = dependencies
        for dependency in dependencies:
            reverse_adjacency.setdefault(dependency, set()).add(path)

    root_paths = {module_index[name] for name in entrypoint_modules(root) if name in module_index}
    root_paths.update(
        path
        for path in files
        if path.name == "__main__.py"
        or path.name == "conftest.py"
        or path.name.startswith("test_")
        or path.relative_to(root).parts[0] in {"scripts", "tests"}
    )

    # Script/test roots outside the requested corpus still supply real inbound edges.
    external_inbound_counts: dict[Path, int] = {}
    external_files = sorted(
        path
        for name in ("scripts", "tests")
        for path in (root / name).rglob("*.py")
        if path not in adjacency and "__pycache__" not in path.parts
    )
    for path in external_files:
        for dependency in _scan_dependencies(root, path, module_index):
            root_paths.add(dependency)
            external_inbound_counts[dependency] = external_inbound_counts.get(dependency, 0) + 1

    reachable = _reachable_paths(adjacency, root_paths)
    inspected: set[Path] = set()
    while pending := (set(reachable) | set(external_files)) - inspected:
        for path in sorted(pending):
            package = _package_name_for_module(module_name_for_path(root, path), path)
            for name in launched_module_names(path, package_name=package):
                if name in module_index:
                    root_paths.add(module_index[name])
        inspected.update(pending)
        reachable = _reachable_paths(adjacency, root_paths)

    return UsageGraph(
        reverse_adjacency=reverse_adjacency,
        reachable=reachable,
        external_inbound_counts=external_inbound_counts,
        root_paths=frozenset(root_paths),
    )


def inbound_import_count(graph: UsageGraph, path: Path) -> int:
    return len(graph.reverse_adjacency.get(path, set())) + graph.external_inbound_counts.get(
        path, 0
    )


def module_name_for_path(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root).parts)
    if parts[:1] == ["src"]:
        parts = parts[1:]
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts)


def _scan_dependencies(root: Path, path: Path, module_index: dict[str, Path]) -> set[Path]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return set()

    dependencies: set[Path] = set()
    package_name = _package_name_for_module(module_name_for_path(root, path), path)
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = _from_import_base_module_name(node, package_name=package_name)
            if base is not None:
                names = [
                    base,
                    *(f"{base}.{alias.name}" for alias in node.names if alias.name != "*"),
                ]
        for name in names:
            if name in module_index:
                dependencies.add(module_index[name])
            # Importing a leaf executes every parent package's __init__ too.
            parts = name.split(".")
            for length in range(1, len(parts)):
                parent = module_index.get(".".join(parts[:length]))
                if parent is not None and parent.name == "__init__.py":
                    dependencies.add(parent)
    return dependencies


def _package_name_for_module(module_name: str, path: Path) -> str:
    return module_name if path.name == "__init__.py" else module_name.rpartition(".")[0]


def _from_import_base_module_name(node: ast.ImportFrom, *, package_name: str) -> str | None:
    if not node.level:
        return node.module
    package_parts = package_name.split(".") if package_name else []
    if node.level > len(package_parts):
        return None
    prefix = package_parts[: len(package_parts) - node.level + 1]
    return ".".join([*prefix, *([node.module] if node.module else [])])


def _reachable_paths(adjacency: dict[Path, set[Path]], root_paths: set[Path]) -> frozenset[Path]:
    reachable: set[Path] = set()
    queue = list(root_paths)
    while queue:
        current = queue.pop()
        if current in reachable:
            continue
        reachable.add(current)
        queue.extend(adjacency.get(current, set()) - reachable)
    return frozenset(reachable)
