"""Keep an offline source recovery bundle inside the setup skill's resources."""
from __future__ import annotations
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile


def bundle(source: Path) -> Path:
    target = source / 'skills/byteplus-creative-setup/references'
    target.mkdir(parents=True, exist_ok=True)
    roots = ['scripts/run.py', 'byteplus_creative', 'packages', 'pyproject.toml', 'uv.lock', 'THIRD_PARTY_NOTICES.md', 'licenses']
    files = []
    for name in roots:
        path = source / name
        for item in path.rglob('*') if path.is_dir() else [path]:
            if item.is_symlink():
                raise ValueError('Runtime bundle must not contain symlinks')
            if not item.is_file() or {'__pycache__', '.venv', '.runtime', '.git', 'output'}.intersection(item.relative_to(source).parts):
                continue
            if item.suffix in {'.pyc', '.pyo', '.sqlite3'} or item.name.startswith('.env'):
                continue
            files.append(item)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            entry = zipfile.ZipInfo(path.relative_to(source).as_posix(), date_time=(2026,10,27,0,0,0))
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())
    raw = payload.getvalue()
    encoded = base64.b64encode(raw).decode('ascii')
    parts = []
    for old in target.glob('runtime-part-*.b64*'):
        old.unlink()
    for i, offset in enumerate(range(0,len(encoded),10000),1):
        name = f'runtime-part-{i:02d}.b64.txt'
        (target/name).write_text(encoded[offset:offset+10000]+'\n', encoding='ascii')
        parts.append('references/'+name)
    manifest = {'format':'base64-zip','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'parts':parts}
    (target/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return target/'runtime-manifest.json'


if __name__ == '__main__':
    print(bundle(Path(__file__).resolve().parents[1]/'plugins/byteplus-creative-kit-cloud'))
