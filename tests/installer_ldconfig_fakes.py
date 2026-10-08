"""Private fixed-path substitutions and a read-only ldconfig cache query fake."""

import shlex
from pathlib import Path

from tests.installer_app_fakes import app_harness
from tests.openrazer_installer_fakes import InstallerHarness


def ldconfig_harness(
    tmp_path: Path, *, helper: str | None = None
) -> tuple[InstallerHarness, Path, tuple[Path, Path]]:
    fake, script = app_harness(tmp_path, helper=helper)
    fixed = (fake.root / "fixed-usr-sbin/ldconfig", fake.root / "fixed-sbin/ldconfig")
    source = script.read_text()
    for system_path, fixture_path in zip(
        ("/usr/sbin/ldconfig", "/sbin/ldconfig"), fixed, strict=True
    ):
        assert system_path in source
        source = source.replace(system_path, str(fixture_path))
    assert "/usr/sbin/ldconfig" not in source and "/sbin/ldconfig" not in source
    script.write_text(source)
    fake.environment["LC_ALL"] = "POSIX"
    return fake, script, fixed


def write_ldconfig(
    fake: InstallerHarness, path: Path, *, output: str | None = None, status: int = 0
) -> None:
    if output is None:
        output = f"libfuse.so.2 (libc6,x86-64) => {fake.root / 'libfuse.so.2'}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/bash\n"
        'printf \'%s\\n\' "$0" "$#" "$@" "${LC_ALL-unset}" > "$FAKE_ROOT/ldconfig-query"\n'
        '[ "$#" -eq 1 ] && [ "${1-}" = -p ] || exit 90\n'
        'printf \'["ldconfig", "-p"]\\n\' >> "$FAKE_ROOT/commands.jsonl"\n'
        f"printf '%s' {shlex.quote(output)}\n"
        f"exit {status}\n"
    )
    path.chmod(0o755)


def home_snapshot(fake: InstallerHarness) -> dict[Path, tuple[int, int, bytes | None]]:
    return {
        path.relative_to(fake.root / "home"): (
            path.stat().st_ino,
            path.stat().st_mode,
            path.read_bytes() if path.is_file() else None,
        )
        for path in (fake.root / "home").rglob("*")
    }


def assert_cache_query(fake: InstallerHarness, path: Path, commands: list[list[str]]) -> None:
    assert (fake.root / "ldconfig-query").read_text().splitlines() == [str(path), "1", "-p", "C"]
    assert [command for command in commands if command[0] == "ldconfig"] == [["ldconfig", "-p"]]
