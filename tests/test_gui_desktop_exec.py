"""Independent Exec roundtrip: spec decoder plus in-memory GLib, no launch."""

import ctypes

import pytest

from naga_control.gui import desktop_exec as dx

CASES = [
    "/tmp/Naga Control.AppImage",
    '/tmp/Naga"quote.AppImage',
    "/tmp/Naga$money.AppImage",
    "/tmp/back\\slash.AppImage",
    "/tmp/tick`x.AppImage",
    "/tmp/100%.AppImage",
    "/tmp/semi;colon.AppImage",
    "/tmp/a&b.AppImage",
    "/tmp/par(en).AppImage",
    "/tmp/hash#x.AppImage",
    "/tmp/star*.AppImage",
    "/tmp/q?x.AppImage",
    "/tmp/lt<gt>.AppImage",
    "/tmp/tilde~x.AppImage",
    "/tmp/pipe|x.AppImage",
    "/tmp/sq'quote.AppImage",
]


def _glib_get_exec(text: str) -> tuple[bool, str | None]:
    try:
        lib = ctypes.CDLL("libglib-2.0.so.0")
    except OSError:
        pytest.skip("glib not available")
        return False, None
    lib.g_key_file_new.restype = ctypes.c_void_p
    lib.g_key_file_new.argtypes = []
    lib.g_key_file_load_from_data.restype = ctypes.c_int
    lib.g_key_file_load_from_data.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.g_key_file_get_string.restype = ctypes.c_void_p
    lib.g_key_file_get_string.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.g_key_file_free.argtypes = [ctypes.c_void_p]
    lib.g_free.argtypes = [ctypes.c_void_p]
    kf = lib.g_key_file_new()
    err = ctypes.c_void_p(None)
    data = text.encode("utf-8")
    ok = lib.g_key_file_load_from_data(kf, data, len(data), 0, ctypes.byref(err))
    if not ok:
        lib.g_key_file_free(kf)
        return False, None
    ptr = lib.g_key_file_get_string(kf, b"Desktop Entry", b"Exec", ctypes.byref(err))
    lib.g_key_file_free(kf)
    if not ptr:
        return False, None
    val = ctypes.string_at(ptr).decode("utf-8")
    lib.g_free(ptr)
    return True, val


def _render(single: str) -> str:
    stored = dx.escape_value(single)
    return (
        "[Desktop Entry]\nType=Application\nName=Naga Control\n"
        f"Icon=org.nagacontrol.NagaControl\nExec={stored}\n"
        "Hidden=false\nX-NagaControl-Owned=true\n"
    )


@pytest.mark.parametrize("path", CASES)
def test_roundtrip_via_glib_and_spec_decoder(path: str) -> None:
    argv = [path, "gui", "--start-hidden"]
    single = dx.format_exec_line(argv)
    text = _render(single)
    ok, parsed = _glib_get_exec(text)
    assert ok, f"GLib rejected file for {path!r}"
    assert parsed is not None and parsed == single
    decoded = dx.file_value_to_argv(text.split("Exec=", 1)[1].splitlines()[0])
    assert decoded == argv


def test_reserved_chars_are_quoted() -> None:
    for token in ["a;b", "a&b", "a(b)", "a#b", "a*b", "a?b", "a<b", "a|b", "a~b"]:
        line = dx.format_exec_line(["/bin/x", token])
        assert line.startswith('/bin/x "'), token


def test_percent_preserved_and_rejected() -> None:
    assert "%%" in dx.format_exec_line(["/bin/x", "100%"])
    with pytest.raises(ValueError):
        dx.format_exec_line(["/bin/x", "a\0b"])


def test_backslash_needs_four_in_file() -> None:
    argv = ["/tmp/back\\slash.AppImage", "gui", "--start-hidden"]
    single = dx.format_exec_line(argv)
    assert single.count("\\") == 2
    stored = dx.escape_value(single)
    assert stored.count("\\") == 4
    assert dx.file_value_to_argv(stored) == argv


def test_venv_identity_preserved() -> None:
    argv = ["/tmp/venv/bin/python", "-m", "naga_control.gui.app", "--start-hidden"]
    assert dx.format_exec_line(argv) == (
        "/tmp/venv/bin/python -m naga_control.gui.app --start-hidden"
    )
