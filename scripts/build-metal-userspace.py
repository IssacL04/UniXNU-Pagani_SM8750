#!/usr/bin/env python3
"""Build pinned A830 Turnip/Metal and stage a separate Data/trust pair on macOS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run(*command, **kwargs):
    return subprocess.run([str(x) for x in command], check=True, **kwargs)


def checkout(path, url, revision, directories=()):
    if not path.exists():
        path.mkdir(parents=True)
        run('git', 'init', '-q', path)
        run('git', '-C', path, 'remote', 'add', 'origin', url)
        run('git', '-C', path, 'fetch', '--depth', '1', 'origin', revision)
        if directories:
            run('git', '-C', path, 'sparse-checkout', 'init', '--cone')
            run('git', '-C', path, 'sparse-checkout', 'set', *directories)
        run('git', '-C', path, 'checkout', '--detach', 'FETCH_HEAD')
    actual = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != revision:
        raise ValueError('Source pin differs: ' + str(path))


def build(tree, data, trust, output):
    if sys.platform != 'darwin':
        raise ValueError('The iOS SDK, codesign and hdiutil require a macOS build host')
    if output.exists():
        raise ValueError('Refuse to overwrite candidate output: ' + str(output))
    if not data.is_file() or hashlib.sha256(trust.read_bytes()).hexdigest() != \
            '7416ca4f8377146626bb284e2133c76bee6cb4e3ee0af5d648b186235a7323a7':
        raise ValueError('Require the base Data seed and unchanged original 21H461 trust bundle')
    for tool in ('git', 'xcrun', 'codesign', 'hdiutil', 'glslangValidator', 'glslc', 'spirv-val',
                 'rustup', 'cargo', 'llvm-as', 'bison', 'flex', 'ninja'):
        if not shutil.which(tool):
            raise ValueError('Missing build tool: ' + tool)
    run('xcrun', '--sdk', 'iphoneos', '--show-sdk-path')
    scripts = tree / 'scripts'
    pins = json.loads((scripts / 'data/adreno-compiler-inputs.json').read_text())
    mesa = tree / '.cache/mesa-work'
    checkout(mesa, pins['mesa']['mirror'], pins['mesa']['commit'], pins['mesa']['sparse_directories'])
    dirty = subprocess.check_output(['git', '-C', str(mesa), 'status', '--porcelain'], text=True)
    if not dirty:
        for patch in pins['patches']:
            run('git', '-C', mesa, 'apply', tree / patch)
    sys.path.insert(0, str(scripts))
    from mesa_patch_identity import validate_recorded_patches
    validate_recorded_patches(tree, mesa, pins)
    translator = json.loads((scripts / 'data/gpu-metal-vulkan-inputs.json').read_text())['translator']
    checkout(tree / '.cache/gpu-reference/metal2vulkan', translator['repository'], translator['commit'])
    venv = tree / '.cache/mesa-venv'
    if not (venv / 'bin/python').is_file():
        run(sys.executable, '-m', 'venv', venv)
    run(venv / 'bin/python', '-m', 'pip', 'install', '-r', scripts / 'requirements-adreno-compiler.txt')
    run('rustup', 'toolchain', 'install', '1.98.0', '--profile', 'minimal', '--target', 'aarch64-apple-ios')
    run(sys.executable, scripts / 'build-turnip-darwin.py', '--target', 'ios')
    run(sys.executable, scripts / 'build-adreno-metal-plugin.py', '--chip', 'a830')
    original = tree / 'build/original-static-system-trust/original-static-system.bundle'
    original.parent.mkdir(parents=True, exist_ok=True)
    if original.exists() and original.read_bytes() != trust.read_bytes():
        raise ValueError('Existing original trust input differs')
    original.write_bytes(trust.read_bytes())
    run(sys.executable, scripts / 'make-owner-trust-bundle.py')
    output.mkdir(parents=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        [str(tree / 'drivers/PaganiDarwinBoot/Test'), os.environ.get('PYTHONPATH', '')]))
    run(sys.executable, scripts / 'add-gpu-plugin-data.py', '--publish', '--clients',
        'iconservicesagent,WidgetRenderer_Default,PosterBoard', data, output / 'data.dbrdisk', env=env)
    shutil.copyfile(tree / 'build/adreno-metal-plugin/owner-trust.bundle', output / 'owner-trust.bundle')
    print('PASS: A830 plugin built and staged; rendering and presentation require device verification')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--original-trust', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        build(args.tree.resolve(), args.data.resolve(), args.original_trust.resolve(), args.output.resolve())
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
