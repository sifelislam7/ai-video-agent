#!/usr/bin/env python3
"""Download extra Arabic/Latin fonts into assets/fonts/.

The repository already bundles Cairo and Noto Sans Arabic (SIL Open Font
License), so this script is optional — use it to add more typefaces, or to
restore the bundled ones if they were removed.

    python scripts/fetch_fonts.py                 # cairo + noto sans arabic
    python scripts/fetch_fonts.py --font tajawal --font amiri
    python scripts/fetch_fonts.py --list

Fonts are pulled from the @expo-google-fonts npm mirrors of Google Fonts
(plain .ttf files, no API key required).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
REGISTRY = "https://registry.npmjs.org"

# family -> (npm package, weight folder, saved filename)
FAMILIES: dict[str, tuple[str, str, str]] = {
    "cairo": ("@expo-google-fonts/cairo", "700Bold", "Cairo_700Bold.ttf"),
    "cairo-black": ("@expo-google-fonts/cairo", "900Black", "Cairo_900Black.ttf"),
    "noto-sans-arabic": (
        "@expo-google-fonts/noto-sans-arabic", "700Bold", "NotoSansArabic_700Bold.ttf",
    ),
    "tajawal": ("@expo-google-fonts/tajawal", "700Bold", "Tajawal_700Bold.ttf"),
    "amiri": ("@expo-google-fonts/amiri", "700Bold", "Amiri_700Bold.ttf"),
    "almarai": ("@expo-google-fonts/almarai", "700Bold", "Almarai_700Bold.ttf"),
    "readex-pro": ("@expo-google-fonts/readex-pro", "600SemiBold", "ReadexPro_600SemiBold.ttf"),
}

DEFAULTS = ["cairo", "noto-sans-arabic"]


def _tarball_url(package: str) -> str:
    with urllib.request.urlopen(f"{REGISTRY}/{package}", timeout=60) as response:
        meta = json.load(response)
    latest = meta["dist-tags"]["latest"]
    return meta["versions"][latest]["dist"]["tarball"]


def fetch(family: str, force: bool = False) -> bool:
    package, weight, filename = FAMILIES[family]
    target = FONTS / filename
    if target.exists() and not force:
        print(f"✓ {filename} already present")
        return True
    print(f"↓ {family} ({package} · {weight}) …")
    try:
        url = _tarball_url(package)
        with urllib.request.urlopen(url, timeout=120) as response:
            payload = response.read()
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            wanted = f"package/{weight}/"
            member = next(
                (m for m in archive.getmembers()
                 if m.name.startswith(wanted) and m.name.endswith(".ttf")),
                None,
            )
            if member is None:  # fall back to any ttf in the package
                member = next(
                    (m for m in archive.getmembers() if m.name.endswith(".ttf")), None
                )
            if member is None:
                raise FileNotFoundError(f"no .ttf inside {package}")
            data = archive.extractfile(member)
            assert data is not None
            target.write_bytes(data.read())
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {family}: {exc}", file=sys.stderr)
        return False
    print(f"✓ saved {target.relative_to(ROOT)} ({target.stat().st_size // 1024} KB)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--font", choices=sorted(FAMILIES), action="append",
                        help=f"font family (default: {', '.join(DEFAULTS)})")
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    parser.add_argument("--list", action="store_true", help="list available families")
    args = parser.parse_args()

    if args.list:
        for name, (package, weight, filename) in sorted(FAMILIES.items()):
            print(f"{name:<18} {package:<42} {weight:<12} -> {filename}")
        return 0

    FONTS.mkdir(parents=True, exist_ok=True)
    ok = all(fetch(family, args.force) for family in (args.font or DEFAULTS))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
