"""Prepare a read-only chroot runtime from the existing SandboxFusion Python."""
import concurrent.futures
import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'workspace/strict-reproduction/sandbox-deployment/conda-envs/sandbox-runtime'
DEST = ROOT / 'workspace/strict-reproduction/sandbox-isolated/rootfs'
PACKAGES = ('numpy', 'numpy.libs', 'pandas', 'scipy', 'scipy.libs', 'sympy', 'mpmath',
            'pytz', 'dateutil', 'six.py', 'tzdata', 'packaging', 'bs4', 'soupsieve',
            'lxml', 'lxml.libs', 'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna',
            'matplotlib', 'matplotlib.libs', 'contourpy', 'cycler', 'fontTools', 'kiwisolver',
            'PIL', 'pillow.libs', 'pyparsing')


def copy(src, dst):
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst, follow_symlinks=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--extend', action='store_true', help='add missing packages to an existing runtime')
    args = parser.parse_args()
    if DEST.exists() and not args.extend:
        raise RuntimeError(f'{DEST} exists; refusing to overwrite')
    runtime = DEST / 'opt/python'
    if not args.extend:
        (runtime / 'bin').mkdir(parents=True)
        copy(SOURCE / 'bin/python3.10', runtime / 'bin/python3.10')
        shutil.copytree(SOURCE / 'lib/python3.10', runtime / 'lib/python3.10',
                        ignore=shutil.ignore_patterns('site-packages', '__pycache__', '*.pyc'), symlinks=True)
    elif not (runtime / 'bin/python3.10').exists():
        raise RuntimeError('existing sandbox runtime not found')
    site = runtime / 'lib/python3.10/site-packages'
    site.mkdir(exist_ok=True)
    source_site = SOURCE / 'lib/python3.10/site-packages'
    for name in PACKAGES:
        src = source_site / name
        if (site / name).exists():
            continue
        if src.is_dir():
            shutil.copytree(src, site / name, symlinks=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        elif src.is_file():
            copy(src, site / name)
    for src in (SOURCE / 'lib').iterdir():
        if '.so' in src.name and src.is_file():
            copy(src, runtime / 'lib' / src.name)
    # Copy libraries used by the trusted interpreter and extension modules.
    binaries = [SOURCE / 'bin/python3.10'] + list((runtime / 'lib/python3.10').rglob('*.so'))
    def dependencies(binary):
        result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, check=False)
        paths = []
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            for item in parts:
                if item.startswith('/lib/') or item.startswith('/lib64/') or item.startswith('/usr/lib/'):
                    paths.append(item)
        return paths
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        paths = {p for group in pool.map(dependencies, binaries) for p in group}
    paths.update(['/lib64/ld-linux-x86-64.so.2', '/usr/lib/x86_64-linux-gnu/libseccomp.so.2'])
    for name in sorted(paths):
        src = Path(name)
        if src.is_file():
            copy(src, DEST / name.lstrip('/'))
    (DEST / 'tmp').mkdir(mode=0o711, exist_ok=True)
    os.chmod(DEST / 'tmp', 0o711)
    print(f'Prepared isolated Python runtime: {DEST}; packages: {", ".join(PACKAGES)}')


if __name__ == '__main__':
    main()
