#!/usr/bin/env python3
"""Exercise the patched production UFS code without accessing a device."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path)
    parser.add_argument('--openssl-prefix', type=Path, default=Path('/usr'))
    parser.add_argument('--captured', type=Path, help='Directory with locally captured GPT and first block')
    args = parser.parse_args()
    device = Path(__file__).resolve().parents[1]
    tree = args.tree or Path(subprocess.check_output([str(device / 'unixnu'), '--prepare'], text=True).strip())
    sys.path.insert(0, str(tree / 'scripts'))
    from unixnu import userdata
    from unixnu.util import Error
    assert userdata.target_partition({}) == 'userdata'
    assert userdata.target_partition({'partition': 'unixnu'}) == 'unixnu'
    for bad in ('', 'unixnu/../userdata', 'unixnu userdata', 'x' * 36, None, 4):
        try:
            userdata.target_partition({'partition': bad})
        except Error:
            pass
        else:
            raise AssertionError(f'Invalid partition accepted: {bad!r}')
    # Exercise the actual report emitter without macOS, a phone or an IPSW.
    with tempfile.TemporaryDirectory(prefix='stage6-image-') as directory:
        work = Path(directory)
        raw = work / 'source.raw'
        raw.write_bytes(bytes(4096))
        ctx = SimpleNamespace(work=work, board={'userdata': {'partition': 'unixnu', 'first_lba': 44928768,
            'last_lba': 61705983, 'windows': [{'name': 'OS', 'component': 'OS'}, {'name': 'SystemOS', 'component': 'Cryptex1,SystemOS'}]}})
        source = SimpleNamespace(remote=False, extract=lambda _: raw)
        with patch.object(userdata, 'tool'), patch.object(userdata, 'Ipsw', return_value=source), \
                patch.object(userdata, 'image_size', return_value=4096), patch.object(userdata, 'attach', return_value=str(raw)), \
                patch.object(userdata.subprocess, 'run'):
            image = userdata.build(ctx)
        import json
        report = json.loads(image.with_suffix('.json').read_text())
        assert report['partition'] == 'unixnu' and report['userdata_bytes'] == 64 * 1024**3
        assert report['flash_command'] == f'fastboot flash unixnu {image}'
    print('PASS: image report targets unixnu, partition validation, legacy default')
    source = tree / 'drivers/NativeUfs/tests'
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0')
    with tempfile.TemporaryDirectory(prefix='stage6-') as directory:
        for name in ('Sm8750', 'LunDiscovery', 'RootCommands', 'RootLayout', 'SmmuTakeover', 'RootWindowRead', 'TransferPoll'):
            binary = Path(directory) / name
            command = [os.environ.get('CXX', 'c++'), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                       '-fsanitize=address,undefined', '-g', '-DNATIVE_UFS_SM8750=1', '-DNATIVE_UFS_READ_ONLY=1',
                       str(source / (name + '.cpp')), '-o', str(binary)]
            if name == 'RootLayout':
                command += ['-I' + str(args.openssl_prefix / 'include'), '-L' + str(args.openssl_prefix / 'lib'), '-lcrypto']
            subprocess.run(command, check=True, timeout=60)
            subprocess.run([str(binary)], check=True, env=env, timeout=30)
            if name == 'RootLayout' and args.captured:
                subprocess.run([str(binary), str(args.captured / 'sda-primary-gpt.bin'),
                                str(args.captured / 'unixnu-block0.bin')], check=True, env=env, timeout=30)


if __name__ == '__main__':
    main()
