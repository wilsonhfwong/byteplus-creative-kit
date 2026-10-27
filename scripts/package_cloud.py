"""Build one cloud-executor plugin ZIP, excluding credentials and runtime state."""
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'plugins' / 'byteplus-creative-kit-cloud'


def build(destination: Path) -> Path:
    destination = destination.resolve()
    if destination.is_relative_to(SOURCE.resolve()):
        raise ValueError('Write the archive outside the plugin source directory.')
    # Explicit source roots prevent a local settings file or generated media
    # from being included merely because it exists in a checkout.
    roots = ['.gitignore', 'README.md', 'THIRD_PARTY_NOTICES.md', 'plugin.json',
             'mcp.json', 'pyproject.toml', 'uv.lock', 'byteplus_creative',
             'packages', 'licenses', 'scripts', 'skills', 'tests']
    excluded = {'.venv', '__pycache__', '.pytest_cache', '.git', '.runtime',
                '.byteplus-creative-kit', 'output', 'dist', '.env'}
    files = []
    for name in roots:
        path = SOURCE / name
        candidates = path.rglob('*') if path.is_dir() else [path]
        for item in candidates:
            relative = item.relative_to(SOURCE)
            if item.is_symlink():
                raise ValueError(f'Do not package symlinks: {relative}')
            if not item.is_file() or excluded.intersection(relative.parts):
                continue
            if item.suffix in {'.pyc', '.pyo'} or item.name.startswith('.env'):
                continue
            files.append(item)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            relative = path.relative_to(SOURCE).as_posix()
            entry = zipfile.ZipInfo(relative, date_time=(2026, 10, 27, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert {'plugin.json', 'mcp.json', 'scripts/run.py', 'uv.lock'} <= set(archive.namelist())
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / 'byteplus-creative-kit-cloud.zip')
    args = parser.parse_args()
    print(build(args.output))
