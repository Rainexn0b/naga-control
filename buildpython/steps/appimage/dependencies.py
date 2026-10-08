"""Static DT_NEEDED/provider closure for Naga AppImages; no execution or ldconfig."""

from __future__ import annotations

from pathlib import Path

from . import abi
from .baseline import BASELINE_DIRS, BaselineStore, Provider
from .elf import ElfInfo, Inspector

MAX_CLOSURE = 2000
MAX_DEPTH = 64


def validate_needed(name: str) -> None:
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"unsupported DT_NEEDED name: {name!r}")
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError(f"unsupported DT_NEEDED name: {name!r}")
    if name.startswith((".", "-")) or not name.strip() or len(name) > 255:
        raise ValueError(f"unsupported DT_NEEDED name: {name!r}")


def expand_rpath(entry: str, obj_dir: str) -> str:
    if entry == "" or entry in (".", ".."):
        raise ValueError(f"unsupported RPATH entry: {entry!r}")
    if entry.startswith(("./", "../")) or entry.endswith(("/.", "/..")):
        raise ValueError(f"unsupported RPATH entry: {entry!r}")
    if any(ord(c) < 32 or ord(c) == 127 for c in entry):
        raise ValueError(f"unsupported RPATH entry: {entry!r}")
    if entry.startswith("/"):
        raise ValueError(f"unsafe absolute RPATH entry: {entry!r}")
    if "$ORIGIN" not in entry:
        raise ValueError(f"unsupported RPATH entry (need $ORIGIN-relative): {entry!r}")
    if "$" in entry.replace("$ORIGIN", ""):
        raise ValueError(f"unsupported RPATH variable: {entry!r}")
    if entry.count("$ORIGIN") > 4:
        raise ValueError(f"unsupported RPATH entry: {entry!r}")
    expanded = entry.replace("$ORIGIN", obj_dir if obj_dir else ".")
    if "$" in expanded:
        raise ValueError(f"unsupported RPATH variable: {entry!r}")
    if expanded.startswith("/"):
        raise ValueError(f"unsafe absolute RPATH entry: {entry!r}")
    parts: list[str] = []
    for part in expanded.split("/"):
        if part in ("", "."):
            if part == "" and expanded != "":
                raise ValueError(f"unsupported RPATH entry: {entry!r}")
            continue
        if part == "..":
            if not parts:
                raise ValueError(f"RPATH escapes bundle: {entry!r}")
            parts.pop()
            continue
        if any(ord(c) < 32 for c in part):
            raise ValueError(f"unsupported RPATH entry: {entry!r}")
        parts.append(part)
    if not parts:
        raise ValueError(f"unsupported RPATH entry: {entry!r}")
    return "/".join(parts)


def bundled_qt_dirs(payloads: tuple[abi.Payload, ...]) -> list[str]:
    found: set[str] = set()
    for payload in payloads:
        for path in payload.paths:
            if "PySide6/Qt/lib" in path:
                idx = path.find("PySide6/Qt/lib")
                found.add(path[: idx + len("PySide6/Qt/lib")])
    return sorted(found)


def _check_arch(info: ElfInfo, relative: str, need: str) -> str | None:
    if (
        info.elf_class != "ELF64"
        or info.endianness != "2's complement, little endian"
        or info.machine != "Advanced Micro Devices X86-64"
        or info.elf_type not in ("DYN", "EXEC")
    ):
        return f"{relative}: provider for {need} has wrong class/machine/type"
    return None


def _check_soname(info: ElfInfo, need: str, relative: str) -> str | None:
    if info.soname is not None and info.soname != need:
        return f"{relative}: SONAME {info.soname!r} mismatches need {need!r}"
    return None


def _check_versions(
    requester: str, need: str, names: tuple[str, ...], provider: Provider
) -> list[str]:
    provided = {d.name for d in provider.info.version_defs}
    return [
        f"{requester}: {need} needs {name} missing in {provider.relative}"
        for name in names
        if name != "GLIBC_PRIVATE" and name not in provided
    ]


class Closure:
    def __init__(
        self,
        extract_root: Path,
        bundled: tuple[abi.Payload, ...],
        baseline_root: Path,
        inspector: Inspector,
    ) -> None:
        self.extract_root = extract_root
        self.bundled = bundled
        self.baseline_root = baseline_root
        self.inspector = inspector
        self.errors: list[str] = []
        self.by_path: dict[str, abi.Payload] = {}
        for payload in bundled:
            for path in payload.paths:
                self.by_path[path] = payload
        self.bundled_dirs = ["usr/lib", *bundled_qt_dirs(bundled)]
        self.store = BaselineStore(baseline_root, inspector)
        self.visited: set[tuple[str, str, str]] = set()
        self.count = 0

    def _load_baseline(self, relative: str) -> Provider | None:
        provider = self.store.load(relative)
        if self.store.errors:
            self.errors.extend(self.store.errors)
            self.store.errors.clear()
        return provider

    def _find_bundled(self, directory: str, need: str) -> abi.Payload | None:
        candidate = f"{directory}/{need}" if directory else need
        return self.by_path.get(candidate)

    def _resolve(
        self, requester: str, info: ElfInfo, obj_dir: str, need: str, depth: int
    ) -> Provider | None:
        if depth > MAX_DEPTH or self.count > MAX_CLOSURE:
            self.errors.append(f"{requester}: dependency closure limit exceeded for {need}")
            return None
        try:
            validate_needed(need)
        except ValueError as exc:
            self.errors.append(f"{requester}: {exc}")
            return None
        rpath_dirs: list[str] = []
        runpath_dirs: list[str] = []
        try:
            for entry in info.rpath:
                rpath_dirs.append(expand_rpath(entry, obj_dir))
            for entry in info.runpath:
                runpath_dirs.append(expand_rpath(entry, obj_dir))
        except ValueError as exc:
            self.errors.append(f"{requester}: {exc}")
            return None
        use_rpath = not info.runpath
        candidates: list[tuple[str, str]] = []
        if use_rpath:
            candidates.extend(("bundled-rpath", d) for d in rpath_dirs)
        candidates.extend(("bundled", d) for d in self.bundled_dirs)
        if info.runpath:
            candidates.extend(("bundled-runpath", d) for d in runpath_dirs)
        candidates.extend(("baseline", d) for d in BASELINE_DIRS)
        # Detect ambiguous distinct bundled providers at same bundled priority.
        bundled_hits: dict[str, list[abi.Payload]] = {}
        for scope, directory in candidates:
            if scope.startswith("bundled"):
                hit = self._find_bundled(directory, need)
                if hit is not None and hit.elf is not None:
                    bundled_hits.setdefault(scope, []).append(hit)
        for scope, hits in bundled_hits.items():
            distinct = {h.sha256 for h in hits}
            if len(distinct) > 1:
                self.errors.append(f"{requester}: ambiguous providers for {need} in {scope}")
                return None
        for scope, directory in candidates:
            if scope.startswith("bundled"):
                hit = self._find_bundled(directory, need)
                if hit is not None:
                    if hit.elf is None:
                        self.errors.append(f"{requester}: bundled provider unreadable for {need}")
                        return None
                    err = _check_arch(hit.elf, directory + "/" + need, need)
                    if err is not None:
                        self.errors.append(f"{requester}: {err}")
                        return None
                    err = _check_soname(hit.elf, need, directory + "/" + need)
                    if err is not None:
                        self.errors.append(f"{requester}: {err}")
                        return None
                    provider = Provider(directory + "/" + need, "bundled", hit.sha256, hit.elf)
                    return provider
            else:
                rel = f"{directory}/{need}"
                provider = self._load_baseline(rel)
                if provider is not None:
                    err = _check_arch(provider.info, "baseline:" + rel, need)
                    if err is not None:
                        self.errors.append(f"{requester}: {err}")
                        return None
                    err = _check_soname(provider.info, need, "baseline:" + rel)
                    if err is not None:
                        self.errors.append(f"{requester}: {err}")
                        return None
                    return provider
        self.errors.append(f"{requester}: missing provider for {need}")
        return None

    def check_object(self, requester: str, info: ElfInfo, obj_dir: str, depth: int) -> None:
        if self.count > MAX_CLOSURE:
            self.errors.append(f"{requester}: dependency closure limit exceeded")
            return
        self.count += 1
        for lib in info.needed_libraries:
            provider = self._resolve(requester, info, obj_dir, lib, depth)
            if provider is None:
                continue
            names = tuple(need.names for need in info.version_needs if need.provider_name == lib)
            wanted: tuple[str, ...] = names[0] if names else ()
            for err in _check_versions(requester, lib, wanted, provider):
                self.errors.append(err)
            key = (provider.scope, provider.relative, provider.sha256)
            if key in self.visited:
                continue
            self.visited.add(key)
            provider_dir = provider.relative.rpartition("/")[0]
            self.check_object(provider.relative, provider.info, provider_dir, depth + 1)

    def run(self) -> list[str]:
        for payload in self.bundled:
            if payload.elf is None:
                continue
            requester = payload.paths[0]
            obj_dir = requester.rpartition("/")[0]
            self.check_object(requester, payload.elf, obj_dir, 0)
        return sorted(set(self.errors))


def check_closure(
    extract_root: Path,
    bundled: tuple[abi.Payload, ...],
    baseline_root: Path,
    inspector: Inspector,
) -> list[str]:
    closure = Closure(extract_root, bundled, baseline_root, inspector)
    return closure.run()
