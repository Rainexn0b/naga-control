"""Two-layer Desktop Entry Exec encoding (private GUI helper).

Layer 1 (Exec quoting): per Desktop Entry Spec, escape backslash, double
quote, backquote and dollar with a backslash, double literal percent as %%,
then enclose in double quotes when reserved characters appear.
Layer 2 (desktop string): double every backslash for file storage so GLib
key-file parsing restores layer 1 exactly. Decoding reverses both layers.
No shell quoting is used here.
"""

from collections.abc import Sequence

_RESERVED = frozenset(
    [
        " ",
        "\t",
        '"',
        "'",
        "\\",
        "$",
        "`",
        "%",
        "<",
        ">",
        "~",
        "|",
        "&",
        ";",
        "*",
        "?",
        "#",
        "(",
        ")",
    ]
)


def _reject(arg: str, what: str) -> None:
    if "\0" in arg or "\n" in arg or "\r" in arg:
        raise ValueError(f"{what} contains an unsupported control character")
    if what == "executable" and not arg:
        raise ValueError("executable path is empty")


def quote_exec_arg(arg: str) -> str:
    """Quote one argv token for the Exec layer (single layer)."""
    _reject(arg, "argument")
    escaped = arg.replace("%", "%%").replace("\\", "\\\\")
    escaped = escaped.replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    if escaped == "":
        return '""'
    if any(c in escaped for c in _RESERVED):
        return f'"{escaped}"'
    return escaped


def format_exec_line(argv: Sequence[str]) -> str:
    """Format argv as the parsed Exec string (layer 1, what GLib returns)."""
    items = list(argv)
    if not items or not items[0]:
        raise ValueError("argv is empty")
    for i, item in enumerate(items):
        _reject(item, "executable" if i == 0 else "argument")
    return " ".join(quote_exec_arg(a) for a in items)


def escape_value(value: str) -> str:
    """Apply desktop-string escaping (layer 2) for file storage."""
    return value.replace("\\", "\\\\")


def unescape_value(value: str) -> str | None:
    """Reverse layer 2; None when the file escaping is invalid."""
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= len(value):
            return None
        nxt = value[i + 1]
        if nxt == "\\":
            out.append("\\")
        elif nxt == "s":
            out.append(" ")
        elif nxt == "n":
            out.append("\n")
        elif nxt == "t":
            out.append("\t")
        elif nxt == "r":
            out.append("\r")
        else:
            return None
        i += 2
    return "".join(out)


def split_exec(parsed: str) -> list[str] | None:
    """Decode a layer-1 Exec string to argv; None when invalid."""
    argv: list[str] = []
    cur: list[str] = []
    has_token = False
    in_quote = False
    escaped = False
    i = 0
    while i < len(parsed):
        ch = parsed[i]
        if escaped:
            if ch in ('"', "`", "$", "\\"):
                cur.append(ch)
                has_token = True
            else:
                return None
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            in_quote = not in_quote
            has_token = True
        elif ch in (" ", "\t") and not in_quote:
            if has_token:
                argv.append("".join(cur))
                cur = []
                has_token = False
        elif ch == "%":
            if i + 1 >= len(parsed):
                return None
            nxt = parsed[i + 1]
            if nxt == "%":
                cur.append("%")
                has_token = True
                i += 1
            elif nxt in "fFuUdDnNickvm":
                return None
            else:
                return None
        else:
            cur.append(ch)
            has_token = True
        i += 1
    if escaped or in_quote:
        return None
    if has_token:
        argv.append("".join(cur))
    return argv


def file_value_to_argv(raw: str) -> list[str] | None:
    """Decode a raw Exec file value (layer 2) fully to argv."""
    parsed = unescape_value(raw)
    if parsed is None:
        return None
    return split_exec(parsed)


def first_token_from_file_value(raw: str) -> str | None:
    """Extract the executable from a raw file Exec value."""
    argv = file_value_to_argv(raw)
    if not argv:
        return None
    return argv[0] or None


# Backwards-compatible aliases kept for existing GUI/tests.
def quote_desktop_arg(arg: str) -> str:
    return quote_exec_arg(arg)


def format_desktop_exec(argv: Sequence[str]) -> str:
    return format_exec_line(argv)


def parse_desktop_exec_first_token(exec_line: str) -> str | None:
    # Legacy single-layer helper: best effort on an already-parsed line.
    argv = split_exec(exec_line)
    if not argv:
        return None
    return argv[0] or None
