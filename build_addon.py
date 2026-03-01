from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from buildVars import ADDON_INFO


PROJECT_ROOT = Path(__file__).resolve().parent
ADDON_DIR = PROJECT_ROOT / "addon"
MANIFEST_TEMPLATE = PROJECT_ROOT / "manifest.ini.tpl"
DIST_DIR = PROJECT_ROOT / "dist"
OUTPUT_NAME = f"{ADDON_INFO['name']}-{ADDON_INFO['version']}.nvda-addon"
EXCLUDED_DIR_NAMES = {"__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def _ignore_copy_entries(_, names):
    ignored = []
    for name in names:
        if name in EXCLUDED_DIR_NAMES:
            ignored.append(name)
            continue
        if Path(name).suffix in EXCLUDED_SUFFIXES:
            ignored.append(name)
    return ignored


def build_manifest() -> str:
    template = MANIFEST_TEMPLATE.read_text(encoding="utf-8")
    return template.format(**ADDON_INFO)


def main() -> int:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DIST_DIR / OUTPUT_NAME
    with tempfile.TemporaryDirectory(prefix="nvda-addon-build-") as temp_dir:
        temp_root = Path(temp_dir)
        staging_dir = temp_root / ADDON_INFO["name"]
        staging_dir.mkdir(parents=True, exist_ok=True)
        for source_path in sorted(ADDON_DIR.iterdir()):
            destination_path = staging_dir / source_path.name
            if source_path.is_dir():
                shutil.copytree(
                    source_path,
                    destination_path,
                    ignore=_ignore_copy_entries,
                )
            else:
                shutil.copy2(source_path, destination_path)
        (staging_dir / "manifest.ini").write_text(build_manifest(), encoding="utf-8")

        if output_path.exists():
            output_path.unlink()

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging_dir.rglob("*")):
                if path.is_dir():
                    continue
                if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
                    continue
                if path.suffix in EXCLUDED_SUFFIXES:
                    continue
                archive.write(path, path.relative_to(staging_dir).as_posix())

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
