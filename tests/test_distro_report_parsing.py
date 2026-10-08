"""Conservative, bounded os-release DATA parsing with fixture files only."""

import os
from pathlib import Path

import pytest

from tests.distro_report_fakes import fields, harness


@pytest.mark.parametrize(
    "data,identity,version,family,provenance",
    [
        (b'ID=ubuntu\nVERSION_ID="22.04"\n', "ubuntu", "22.04", "ubuntu", "ID"),
        (b"ID='ubuntu'\nVERSION_ID='24.04'", "ubuntu", "24.04", "ubuntu", "ID"),
        (b"ID=arch\n", "arch", "UNKNOWN", "arch", "ID"),
        (
            b"ID=fixture\nID_LIKE=ubuntu debian\nVERSION_ID=Build-01.2+RC_3\n",
            "fixture",
            "Build-01.2+RC_3",
            "ubuntu",
            "ID_LIKE (hint only)",
        ),
        (
            b'ID=fixture\nID_LIKE="debian  ubuntu"\nVERSION_ID=01.02\n',
            "fixture",
            "01.02",
            "debian",
            "ID_LIKE (hint only)",
        ),
        (b"# comment\r\nID=ubuntu\r\nVERSION_ID=22.04\r\n", "ubuntu", "22.04", "ubuntu", "ID"),
        (b"ID=ubuntu\r\nVERSION_ID=22.04", "ubuntu", "22.04", "ubuntu", "ID"),
    ],
)
def test_valid_grammar_preserves_release_strings(
    tmp_path: Path, data: bytes, identity: str, version: str, family: str, provenance: str
) -> None:
    fake = harness(tmp_path, data)
    result = fake.run(strict=True)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    report = fields(result.stdout)
    assert report["Identity data"] == "PARSED"
    assert report["ID"] == identity
    assert report["VERSION_ID"] == version
    assert report["Family"] == family
    assert report["Family provenance"] == provenance
    assert report["Identity source"] == "/etc/os-release"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"# no ID\nVERSION_ID=22.04\n",
        b"ID\n",
        b"ID ubuntu\n",
        b"ID:ubuntu\n",
        b" ID=ubuntu\n",
        b"ID =ubuntu\n",
        b"ID=\n",
        b'ID=""\n',
        b"ID=Ubuntu\n",
        b"ID=ubuntu/debian\n",
        b"ID=ubuntu debian\n",
        b'ID="ubuntu\n',
        b"ID='ubuntu\"\n",
        b'ID="ubuntu"suffix\n',
        b'ID="ubun\\tu"\n',
        b"ID=ubuntu # comment\n",
        b"ID=ubuntu;curl\n",
        b"ID=$(curl)\n",
        b"ID=`wget`\n",
        b"ID=ubuntu\nVERSION_ID\n",
        b"ID=ubuntu\nVERSION_ID=\n",
        b'ID=ubuntu\nVERSION_ID="22.04\n',
        b"ID=ubuntu\nVERSION_ID=22.04/1\n",
        b"ID=ubuntu\nVERSION_ID=22 04\n",
        b"ID=ubuntu\nVERSION_ID=$(sudo)\n",
        b"ID=ubuntu\nID_LIKE\n",
        b"ID=ubuntu\nID_LIKE=\n",
        b"ID=ubuntu\nID_LIKE=Ubuntu\n",
        b"ID=ubuntu\nID_LIKE= debian\n",
        b'ID=ubuntu\nID_LIKE="debian "\n',
        b"ID=ubuntu\nID_LIKE=debian,arch\n",
        b"ID=ubuntu\nID_LIKE=debian\tarch\n",
        b"ID=ub\x01untu\n",
        b"ID=ubuntu\nVERSION_ID=22.\x1b04\n",
        b"ID=ubuntu\nIGNORED=private\x7fvalue\n",
        b"ID=ubuntu\rVERSION_ID=22.04\n",
        b"ID=ubuntu\nVERSION_ID=22.04\r",
        b"ID=ubuntu\nVERSION_ID=22.04\x00\n",
        b"ID=ub\x00untu\nVERSION_ID=22.04\n",
        b"\x00ID=ubuntu\n",
        b"ID=ubuntu\nVERSION_ID=22.04\n# trailing\x00",
        b"ID=ub\xffuntu\n",
    ],
)
def test_bad_relevant_data_controls_and_nul_are_explicit_unknown(
    tmp_path: Path, data: bytes
) -> None:
    fake = harness(tmp_path, data)
    result = fake.run(strict=True)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    report = fields(result.stdout)
    assert report["Identity data"] == "UNKNOWN"
    assert report["ID"] == report["VERSION_ID"] == report["Family"] == "UNKNOWN"
    assert report["Report status"] == "UNKNOWN"
    assert report["FUSE2 package reference"] == "UNKNOWN"
    assert "private" not in result.stdout
    assert "$(" not in result.stdout and "`" not in result.stdout


@pytest.mark.parametrize(
    "key,value", [("ID", "ubuntu"), ("ID_LIKE", "debian"), ("VERSION_ID", "22.04")]
)
@pytest.mark.parametrize("identical", [True, False])
def test_duplicate_relevant_keys_are_unknown_even_when_identical(
    tmp_path: Path, key: str, value: str, identical: bool
) -> None:
    first = "ID=ubuntu\nID_LIKE=debian\nVERSION_ID=22.04\n"
    data = (first + key + "=" + (value if identical else "different") + "\n").encode()
    result = harness(tmp_path, data).run()
    assert result.returncode == 0
    assert fields(result.stdout)["Identity data"] == "UNKNOWN"
    assert "duplicate" in fields(result.stdout)["Identity note"]


def test_irrelevant_executable_looking_data_is_ignored_without_execution(tmp_path: Path) -> None:
    data = b"""PATH=/live/path
HOME=/host/home
NAGA_CONTROL_INSTALL_OPENRAZER=1
OS_RELEASE_PATH=/another/host/path
PRETTY_NAME="$(curl forbidden || true)"
SHELL=`wget forbidden`
IGNORED='unterminated
evil=$(sudo forbidden || true)
curl forbidden || true
sudo forbidden || true
source executable-looking-configuration
export ID=not-an-assignment
ID_BAD=not-relevant
VERSION_ID_EXTRA=not-relevant
ID=ubuntu
VERSION_ID=22.04
"""
    fake = harness(tmp_path, data)
    result = fake.run()
    assert result.returncode == 0 and result.stderr == ""
    assert fields(result.stdout)["Report status"] == "CONDITIONAL"
    assert "forbidden" not in result.stdout and "host/home" not in result.stdout
    assert fake.uname_calls() == ["-s", "-m"]


def _sized_data(size: int) -> bytes:
    prefix = b"ID=ubuntu\nVERSION_ID=22.04\n"
    count, remainder = divmod(size - len(prefix), 1001)
    return prefix + (b"#" * 1000 + b"\n") * count + b"#" * remainder


@pytest.mark.parametrize(
    "size,expected",
    [(65535, "PARSED"), (65536, "PARSED"), (65537, "UNKNOWN"), (2 * 1024 * 1024, "UNKNOWN")],
)
def test_input_is_bounded_without_stripping_nul(tmp_path: Path, size: int, expected: str) -> None:
    data = _sized_data(size)
    assert len(data) == size
    result = harness(tmp_path, data).run()
    assert result.returncode == 0 and result.stderr == ""
    assert fields(result.stdout)["Identity data"] == expected


@pytest.mark.parametrize("width,expected", [(4096, "PARSED"), (4097, "UNKNOWN")])
@pytest.mark.parametrize("newline", [b"\n", b""])
def test_line_bound_including_ignored_lines(
    tmp_path: Path, width: int, expected: str, newline: bytes
) -> None:
    data = b"ID=ubuntu\nVERSION_ID=22.04\n" + b"#" * width + newline
    result = harness(tmp_path, data).run()
    assert result.returncode == 0 and result.stderr == ""
    assert fields(result.stdout)["Identity data"] == expected


def test_fallback_only_when_etc_path_is_absent(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.etc.unlink()
    result = fake.run()
    report = fields(result.stdout)
    assert result.returncode == 0 and result.stderr == ""
    assert report["Identity source"] == "/usr/lib/os-release"
    assert report["VERSION_ID"] == "24.04"
    fake.vendor.unlink()
    result = fake.run()
    assert fields(result.stdout)["Identity source"] == "UNKNOWN"
    assert fields(result.stdout)["Identity data"] == "UNKNOWN"


@pytest.mark.parametrize(
    "problem", ["malformed", "unreadable", "directory", "fifo", "symlink-fifo", "dangling-symlink"]
)
def test_present_bad_etc_file_never_falls_back_or_reads_special_files(
    tmp_path: Path, problem: str
) -> None:
    fake = harness(tmp_path)
    hook = ""
    if problem == "malformed":
        fake.etc.write_bytes(b"ID=ubuntu\nID=ubuntu\n")
    elif problem == "unreadable":
        # Deterministic even if a test runner has elevated file-read rights.
        hook = "_dr_readable() { return 1; }"
    else:
        fake.etc.unlink()
        if problem == "directory":
            fake.etc.mkdir()
        elif problem == "fifo":
            os.mkfifo(fake.etc)
        elif problem == "symlink-fifo":
            fifo = tmp_path / "fixture-fifo"
            os.mkfifo(fifo)
            fake.etc.symlink_to(fifo)
        else:
            fake.etc.symlink_to(tmp_path / "missing-target")
    result = fake.run(hook=hook)
    assert result.returncode == 0 and result.stderr == ""
    report = fields(result.stdout)
    assert report["Identity source"] == "/etc/os-release"
    assert report["Identity data"] == "UNKNOWN"
    assert report["VERSION_ID"] == "UNKNOWN"


def test_ordinary_symlink_resolving_to_regular_file_is_allowed(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.etc.unlink()
    fake.etc.symlink_to(fake.vendor)
    result = fake.run()
    assert result.returncode == 0 and result.stderr == ""
    assert fields(result.stdout)["Identity source"] == "/etc/os-release"
    assert fields(result.stdout)["VERSION_ID"] == "24.04"


def test_unsafe_vendor_fallback_is_not_opened(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.etc.unlink()
    fake.vendor.unlink()
    os.mkfifo(fake.vendor)
    result = fake.run()
    assert result.returncode == 0 and result.stderr == ""
    assert fields(result.stdout)["Identity data"] == "UNKNOWN"
