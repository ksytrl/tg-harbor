"""Collect dependency notices and package only release/source files."""
from importlib import metadata
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import zipfile


ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / 'dist' / 'TG-Harbor'


def notices():
    if not (RELEASE / 'TG-Harbor.exe').is_file():
        raise SystemExit('Build TG-Harbor.exe first.')
    shutil.copy2(ROOT / 'README.md', RELEASE / '使用说明.md')
    shutil.copy2(ROOT / 'THIRD_PARTY_NOTICES.md', RELEASE / 'THIRD_PARTY_NOTICES.md')
    target = RELEASE / 'licenses'
    target.mkdir(exist_ok=True)
    for dist in metadata.distributions():
        name = dist.metadata.get('Name', 'unknown').replace('/', '_').replace('\\', '_')
        if name.lower() in {'pip', 'setuptools'}:
            continue
        for file in dist.files or []:
            basename = Path(str(file)).name
            if '.dist-info' not in str(file) or not any(s in basename.lower() for s in ('license', 'copying', 'notice')):
                continue
            source = Path(dist.locate_file(file))
            if source.is_file():
                out = target / name
                out.mkdir(exist_ok=True)
                shutil.copy2(source, out / basename)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, target / 'Python-LICENSE.txt')
    # proxy-tools' wheel omits its text; its metadata declares MIT licensing.
    proxy = metadata.metadata('proxy_tools')
    (target / 'proxy-tools-metadata.txt').write_text(
        '\n'.join(f'{k}: {proxy.get(k, "")}' for k in ('Name', 'Version', 'Home-page', 'Author', 'License')) + '\n',
        encoding='utf-8')
    shutil.copy2(ROOT / 'third_party' / 'proxy_tools_LICENSE.txt', target / 'proxy-tools-LICENSE.txt')


def add_tree(archive, base, prefix):
    for file in sorted(base.rglob('*')):
        if file.is_file() and '__pycache__' not in file.parts:
            archive.write(file, str(Path(prefix) / file.relative_to(base)))


def bundles():
    out = ROOT / '发布包'
    out.mkdir(exist_ok=True)
    windows = out / '星港_TG-Harbor_Windows.zip'
    source = out / '星港_TG-Harbor_源码.zip'
    with zipfile.ZipFile(windows, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name in ('TG-Harbor.exe', '使用说明.md', 'THIRD_PARTY_NOTICES.md'):
            z.write(RELEASE / name, 'TG-Harbor/' + name)
        for folder in ('_internal', 'licenses'):
            add_tree(z, RELEASE / folder, 'TG-Harbor/' + folder)
    with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name in ('app.py', 'make_assets.py', 'package_release.py', 'build.ps1',
                     'requirements.txt', 'README.md', 'THIRD_PARTY_NOTICES.md',
                     '.gitignore', '验证报告.json'):
            if (ROOT / name).is_file():
                z.write(ROOT / name, 'tg-harbor/' + name)
        add_tree(z, ROOT / 'web', 'tg-harbor/web')
        add_tree(z, ROOT / 'tests', 'tg-harbor/tests')
        add_tree(z, ROOT / 'third_party', 'tg-harbor/third_party')
    manifest = []
    for file in (windows, source):
        digest = hashlib.sha256()
        with file.open('rb') as fp:
            for block in iter(lambda: fp.read(1024 * 1024), b''):
                digest.update(block)
        manifest.append({'file': file.name, 'bytes': file.stat().st_size, 'sha256': digest.hexdigest()})
    (out / 'SHA256.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--zip', action='store_true')
    args = parser.parse_args()
    notices()
    if args.zip:
        bundles()
