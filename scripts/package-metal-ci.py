#!/usr/bin/env python3
"""Snapshot the seven GPU source checkouts and private firmware for an isolated CI build."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REPOS = ('UniXNU', 'UniXNU-Pagani_SM8750', 'UniXNU-sm8750-common', 'UniXNU-Pagani-Drivers',
         'UniXNU/drivers/Adreno740', 'UniXNU/drivers/AdrenoMetal', 'UniXNU/kits/AdrenoFirmware')


def git(path, *arguments):
    return subprocess.check_output(['git', '-C', str(path), *arguments])


def relative(name):
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or not path.parts or '.git' in path.parts:
        raise ValueError('Invalid bundle path: ' + name)
    return path


def create(output, sources_only=False):
    if output.exists():
        raise ValueError('Refuse to overwrite ' + str(output))
    files, manifest = {}, []
    for index, name in enumerate(REPOS):
        repo = ROOT.parent / name
        url = git(repo, 'remote', 'get-url', 'origin').decode().strip()
        if not re.fullmatch(r'https://github.com/[\w.-]+/[\w.-]+', url):
            raise ValueError('Require a public-source GitHub HTTPS origin: ' + name)
        patch = git(repo, 'diff', '--binary', '--ignore-submodules=dirty', 'HEAD')
        if patch:
            subprocess.run(['git', '-C', str(repo), 'apply', '--reverse', '--check', '-'], input=patch, check=True)
        patch_name = f'changes/{index}.patch'
        files[patch_name] = patch
        additions = []
        for raw in git(repo, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0'):
            if not raw:
                continue
            name_in_repo = raw.decode()
            source = repo / relative(name_in_repo)
            if source.is_symlink() or not source.is_file():
                raise ValueError('Untracked input must be a regular file: ' + str(source))
            archived = f'new/{index}/{name_in_repo}'
            files[archived] = source.read_bytes()
            additions.append({'path': name_in_repo, 'archive': archived, 'mode': source.stat().st_mode & 0o777})
        manifest.append({'path': name, 'repository': url, 'revision': git(repo, 'rev-parse', 'HEAD').decode().strip(),
                         'patch': patch_name, 'additions': additions})
    if not sources_only:
        pins = json.loads((ROOT / 'scripts/data/sm8750-gpu-inputs.json').read_text())['firmware']['files']
        for name, pin in pins.items():
            data = (ROOT / '.cache/firmware/pkx110-gpu' / name).read_bytes()
            if len(data) != pin['bytes'] or hashlib.sha256(data).hexdigest() != pin['sha256']:
                raise ValueError('Firmware pin differs: ' + name)
            files['inputs/firmware/' + name] = data
        dtb = (ROOT / 'sysinfo/live.dtb').read_bytes()
        if hashlib.sha256(dtb).hexdigest() != 'd00767f2068d0df73fc2a077de750bba66a5420c77414db1441ff09f6f3ec223':
            raise ValueError('Runtime DTB pin differs')
        files['inputs/live.dtb'] = dtb
    files['manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        for name, data in files.items():
            item = tarfile.TarInfo(name);item.size = len(data);item.mode = 0o600
            archive.addfile(item, io.BytesIO(data))
    output.chmod(0o600)
    with tarfile.open(output) as archive:
        assert set(archive.getnames()) == set(files)
        assert all(archive.extractfile(name).read() == data for name, data in files.items())
    print(f'PASS: {len(manifest)} source checkouts, {len(files)} entries, {output.stat().st_size} bytes; sources_only={sources_only}')
    print(hashlib.sha256(output.read_bytes()).hexdigest())


def restore(bundle, output):
    if output.exists():
        raise ValueError('Restore needs a new workspace: ' + str(output))
    with tarfile.open(bundle) as archive:
        members = archive.getmembers()
        if len(members) > 2000 or sum(p.size for p in members) > 64 << 20:
            raise ValueError('Unexpected bundle size')
        for member in members:
            relative(member.name)
            if not member.isfile():
                raise ValueError('Bundle entries must be regular files')
        manifest = json.load(archive.extractfile('manifest.json'))
        if tuple(item['path'] for item in manifest) != REPOS:
            raise ValueError('Unexpected source checkout set')
        for item in manifest:
            if not re.fullmatch(r'https://github.com/[\w.-]+/[\w.-]+', item['repository']) or \
                    not re.fullmatch('[0-9a-f]{40}', item['revision']):
                raise ValueError('Invalid source identity')
            repo = output / relative(item['path'])
            repo.mkdir(parents=True, exist_ok=True)
            if not (repo / '.git').exists():
                git(repo, 'init', '-q')
                git(repo, 'remote', 'add', 'origin', item['repository'])
            git(repo, 'fetch', '--depth', '1', 'origin', item['revision'])
            git(repo, 'checkout', '--detach', item['revision'])
            git(repo, 'submodule', 'update', '--init', '--recursive', '--depth', '1')
            patch = archive.extractfile(item['patch']).read()
            if patch:
                subprocess.run(['git', '-C', str(repo), 'apply', '--index', '-'], input=patch, check=True)
                git(repo, 'submodule', 'update', '--init', '--recursive', '--depth', '1')
            for extra in item['additions']:
                target = repo / relative(extra['path'])
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    raise ValueError('New source collides with checkout: ' + str(target))
                target.write_bytes(archive.extractfile(extra['archive']).read())
                target.chmod(extra['mode'] & 0o777)
        device = output / 'UniXNU-Pagani_SM8750'
        for member in members:
            if member.name.startswith('inputs/firmware/'):
                target = device / '.cache/firmware/pkx110-gpu' / relative(member.name).name
            elif member.name == 'inputs/live.dtb':
                target = device / 'sysinfo/live.dtb'
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('wb') as destination:
                shutil.copyfileobj(source, destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['create', 'restore'])
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--sources-only', action='store_true', help='Create a source bundle without firmware or runtime DTB')
    args = parser.parse_args()
    if args.operation == 'restore' and not args.workspace:
        parser.error('restore requires --workspace')
    try:
        create(args.bundle.resolve(), args.sources_only) if args.operation == 'create' else restore(args.bundle.resolve(), args.workspace.resolve())
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
