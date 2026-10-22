"""Bootstrap helper sharing: same-ref fetch, old-stub compat, temp cleanup."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_inner_marker_and_outer_same_ref_logic() -> None:
    inner = (ROOT / "scripts/uninstall.sh").read_text()
    assert inner.count("# NAGA_SESSION_HELPER_REQUIRED") >= 1
    outer = (ROOT / "uninstall.sh").read_text()
    assert "# NAGA_SESSION_HELPER_REQUIRED" in outer
    # Same BOOTSTRAP_REF is used for both inner and helper raw URLs.
    assert outer.count("scripts/uninstall.sh") >= 1
    assert outer.count("scripts/session_service.sh") >= 1
    assert "${BOOTSTRAP_REF}/scripts/uninstall.sh" in outer
    assert "${BOOTSTRAP_REF}/scripts/session_service.sh" in outer
    # No exec abandoning the private temp trap; stdin inherited.
    assert 'exec bash "$tmp/uninstall.sh"' not in outer
    assert 'bash "$tmp/uninstall.sh"' in outer
    assert "trap 'rm -rf \"$tmp\"' EXIT" in outer


def _fake_curl_bin(tmp_path: Path, inner_text: str, helper_text: str | None, record: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/bin/bash\n"
        'echo "$@" >> "' + str(record) + '"\n'
        'out=""; url=""\n'
        'for a in "$@"; do case "$a" in -o) next=1;; *) if [ "${next:-}" = 1 ]; then out="$a"; next=""; else case "$a" in https://*) url="$a";; esac; fi;; esac; done\n'
        'case "$url" in *scripts/uninstall.sh) cat "'
        + str(tmp_path / "inner.sh")
        + '" > "$out";; *scripts/session_service.sh) if [ -f "'
        + str(tmp_path / "helper.sh")
        + '" ]; then cat "'
        + str(tmp_path / "helper.sh")
        + '" > "$out"; else echo "helper missing" >&2; exit 1; fi;; *) echo "unexpected $url" >&2; exit 1;; esac\n'
    )
    curl.chmod(0o755)
    (tmp_path / "inner.sh").write_text(inner_text)
    if helper_text is not None:
        (tmp_path / "helper.sh").write_text(helper_text)
    return bin_dir


def test_old_stub_without_marker_skips_helper_fetch(tmp_path: Path) -> None:
    old_inner = "#!/bin/bash\necho old-ok\n"
    assert "# NAGA_SESSION_HELPER_REQUIRED" not in old_inner
    record = tmp_path / "curl.log"
    record.write_text("")
    bin_dir = _fake_curl_bin(tmp_path, old_inner, None, record)
    # Isolate the dispatcher so its checkout path does not trigger.
    isolated = tmp_path / "isolated-old"
    isolated.mkdir()
    outer_copy = isolated / "uninstall.sh"
    outer_copy.write_text((ROOT / "uninstall.sh").read_text())
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    result = subprocess.run(
        ["/bin/bash", str(outer_copy), "--ref", "oldtag"],
        env=env,
        input="",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "old-ok" in result.stdout
    log = record.read_text()
    assert "scripts/uninstall.sh" in log
    assert "scripts/session_service.sh" not in log


def test_new_marker_fetches_same_ref_and_cleans_tmp(tmp_path: Path) -> None:
    helper_src = (ROOT / "scripts/session_service.sh").read_text()
    stub_inner = (
        "#!/bin/bash\n# NAGA_SESSION_HELPER_REQUIRED\n"
        'if [ ! -f "$(dirname "$0")/session_service.sh" ]; then echo "sibling missing" >&2; exit 1; fi\n'
        'read -r line || line=""\n'
        'echo "inner-ok stdin:$line"\n'
    )
    record = tmp_path / "curl.log"
    record.write_text("")
    bin_dir = _fake_curl_bin(tmp_path, stub_inner, helper_src, record)
    # Private TMPDIR proves temp cleanup: outer mktemp lives here.
    priv_tmp = tmp_path / "privtmp"
    priv_tmp.mkdir()
    isolated = tmp_path / "isolated-new"
    isolated.mkdir()
    outer_copy = isolated / "uninstall.sh"
    outer_copy.write_text((ROOT / "uninstall.sh").read_text())
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(priv_tmp)}
    result = subprocess.run(
        ["/bin/bash", str(outer_copy), "--ref", "sametag"],
        env=env,
        input="yes-stdin\n",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "inner-ok stdin:yes-stdin" in result.stdout
    log = record.read_text()
    assert log.count("sametag/scripts/uninstall.sh") == 1
    assert log.count("sametag/scripts/session_service.sh") == 1
    # Private temp is cleaned; no leftover bootstrap dirs.
    leftovers = [p for p in priv_tmp.iterdir()]
    assert leftovers == [], leftovers
