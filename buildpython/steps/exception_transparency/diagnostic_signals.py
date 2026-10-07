from __future__ import annotations

import ast

TRACEBACK_SIGNAL_NAMES = {"log_exception", "_log_exception"}
SIGNAL_NAME_CALLS = {
    "print",
    "log_exception",
    "_log_exception",
}
SIGNAL_ATTRS = {
    "debug",
    "info",
    "warning",
    "warn",
    "error",
    "exception",
    "critical",
    "log",
    "log_exception",
    "_log_exception",
}


def contains_reraise(body: list[ast.stmt]) -> bool:
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Raise):
                return True
    return False


def has_exc_info_keyword(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg != "exc_info":
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and value.value is True:
            return True
        if isinstance(value, ast.NameConstant) and value.value is True:
            return True
    return False


def is_traceback_logging_call(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Attribute):
        attr_name = call.func.attr.lower()
        if attr_name == "exception":
            return True
        if attr_name in {"error", "critical", "log"} and has_exc_info_keyword(call):
            return True
        return attr_name in TRACEBACK_SIGNAL_NAMES

    if isinstance(call.func, ast.Name):
        func_name = call.func.id.lower()
        return func_name in TRACEBACK_SIGNAL_NAMES

    return False


def is_signal_call(call: ast.Call) -> bool:
    if is_traceback_logging_call(call):
        return True

    if isinstance(call.func, ast.Attribute):
        return call.func.attr.lower() in SIGNAL_ATTRS

    if isinstance(call.func, ast.Name):
        return call.func.id.lower() in SIGNAL_NAME_CALLS

    return False


def contains_traceback_logging(body: list[ast.stmt]) -> bool:
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call) and is_traceback_logging_call(node):
                return True
    return False


def contains_signal(body: list[ast.stmt]) -> bool:
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call) and is_signal_call(node):
                return True
    return False
