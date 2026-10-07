from __future__ import annotations

import ast

_BASE_EXCEPTION_NAMES = {"BaseException", "builtins.BaseException"}
_BROAD_EXCEPTION_NAMES = {"Exception", "builtins.Exception"} | _BASE_EXCEPTION_NAMES


def handler_type_names(
    node: ast.expr | None,
    aliases: dict[str, ast.expr | str] | None = None,
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        if aliases is not None and node.id in aliases and node.id not in seen:
            alias = aliases[node.id]
            if isinstance(alias, str):
                return {alias}
            return handler_type_names(alias, aliases, seen | {node.id})
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {f"{prefix}.{node.attr}" for prefix in handler_type_names(node.value, aliases, seen)}
    if isinstance(node, ast.Tuple):
        names: set[str] = set()
        for element in node.elts:
            names.update(handler_type_names(element, aliases, seen))
        return names
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return handler_type_names(node.left, aliases, seen) | handler_type_names(
            node.right, aliases, seen
        )
    return set()


def collect_exception_aliases(tree: ast.AST) -> dict[str, ast.expr | str]:
    aliases: dict[str, ast.expr | str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name == "builtins" and imported.asname:
                    # Imported origins must not follow unrelated local assignments.
                    aliases[imported.asname] = "builtins"
        elif isinstance(node, ast.ImportFrom) and node.module == "builtins" and node.level == 0:
            for imported in node.names:
                if imported.asname:
                    aliases[imported.asname] = f"builtins.{imported.name}"
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases[target.id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            aliases[node.target.id] = node.value
    return aliases


def is_broad_handler(
    handler: ast.ExceptHandler, aliases: dict[str, ast.expr | str] | None = None
) -> bool:
    if handler.type is None:
        return True
    names = handler_type_names(handler.type, aliases)
    return bool(names & _BROAD_EXCEPTION_NAMES)
