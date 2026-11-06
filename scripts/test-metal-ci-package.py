#!/usr/bin/env python3
"""Verify that unpublished commits and working-tree edits survive source packaging."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

spec = importlib.util.spec_from_file_location('package', Path(__file__).with_name('package-metal-ci.py'))
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)

with tempfile.TemporaryDirectory(prefix='pagani-source-package-') as directory:
    root = Path(directory)
    repo = root / 'source'
    repo.mkdir()
    git = lambda *args: package.git(repo, *args)
    git('init', '-q')
    git('config', 'user.name', 'Source package test')
    git('config', 'user.email', 'test@example.invalid')
    git('remote', 'add', 'origin', 'https://github.com/example/source')
    (repo / 'tracked').write_text('published\n')
    git('add', '.')
    git('commit', '-qm', 'Published base')
    base = git('rev-parse', 'HEAD').decode().strip()
    git('update-ref', 'refs/remotes/origin/main', base)
    (repo / 'committed').write_text('local commit\n')
    git('add', '.')
    git('commit', '-qm', 'Unpublished change')
    (repo / 'tracked').write_text('working tree\n')
    (repo / 'new').write_text('untracked\n')
    package.ROOT, package.REPOS = root / 'device', ('source',)
    bundle = root / 'sources.tar.gz'
    package.create(bundle, sources_only=True)
    restored = root / 'restored'
    subprocess.run(['git', 'clone', '-q', str(repo), str(restored)], check=True)
    package.git(restored, 'checkout', '-q', '--detach', base)
    with tarfile.open(bundle) as archive:
        item, = json.load(archive.extractfile('manifest.json'))
        assert item['revision'] == base
        subprocess.run(['git', '-C', str(restored), 'apply', '--index', '-'],
                       input=archive.extractfile(item['patch']).read(), check=True)
        for extra in item['additions']:
            (restored / extra['path']).write_bytes(archive.extractfile(extra['archive']).read())
    for name in ('tracked', 'committed', 'new'):
        assert (restored / name).read_bytes() == (repo / name).read_bytes()
print('PASS: published base with committed, uncommitted and new source changes')
