"""Pinned upstream appimagetool downloads, verified before execution."""

import hashlib
import shutil
from pathlib import Path
from urllib.request import urlopen

APPIMAGETOOL_VERSION = "1.9.1"
# x86_64 matches KeyRGB's verified pin. Both digests are also published at
# https://api.github.com/repos/AppImage/appimagetool/releases/tags/1.9.1
APPIMAGETOOL_SHA256 = {
    "x86_64": "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0",
    "aarch64": "f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158",
}


def download_appimagetool(*, work: Path, arch: str) -> Path:
    expected = APPIMAGETOOL_SHA256[arch]
    url = (
        "https://github.com/AppImage/appimagetool/releases/download/"
        f"{APPIMAGETOOL_VERSION}/appimagetool-{arch}.AppImage"
    )
    target = work / "appimagetool"
    temporary = work / "appimagetool.download"
    try:
        with urlopen(url, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        with temporary.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"appimagetool SHA256 mismatch: expected {expected}, got {actual}")
        temporary.chmod(0o755)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
