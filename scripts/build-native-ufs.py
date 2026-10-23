#!/usr/bin/env python3
"""Build read-only UFS and its existing root-binding helper with the kernel ABI."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import struct
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root-windows', action='store_true')
    parser.add_argument('--component', choices=('NativeUfs', 'NativeVirtioBlock', 'NativeRamBlock'), default='NativeUfs')
    args = parser.parse_args()
    if args.component != 'NativeUfs' and not args.root_windows:
        parser.error('The root-binding helper requires --root-windows')
    root = Path(__file__).resolve().parents[1]
    compile_command = runpy.run_path(str(root / 'scripts/build-arm-platform.py'))['compile_command']
    recipe = root / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
    record = json.loads(recipe.read_text().strip().rstrip(','))
    output = root / {'NativeUfs': 'build/native-ufs', 'NativeVirtioBlock': 'build/native-virtio-block',
                     'NativeRamBlock': 'build/native-ram-block'}[args.component]
    output.mkdir(parents=True, exist_ok=True)
    obj = output / (args.component + '.o')
    command = compile_command(record, root / 'drivers' / args.component / (args.component + '.cpp'), obj)
    command += ['-DNATIVE_UFS_SM8750=1', '-DNATIVE_UFS_READ_ONLY=1',
                '-Wno-unused-function']
    if args.root_windows:
        command += ['-I', str(root / 'build/storage-abi/include'),
                    '-I', str(root / 'kits/VerifiedRoot/include'),
                    '-I', str(root / 'drivers/NativeVirtioBlock'),
                    '-DNATIVE_VERIFIED_BLOCK=1', '-DNATIVE_VERIFIED_BLOCK_MULTI_POLICY=1',
                    '-mgeneral-regs-only']
    else:
        command += ['-DNATIVE_UFS_PROBE_ONLY=1']
    subprocess.run(command, cwd=record['directory'], check=True)
    if struct.unpack('<4I', obj.read_bytes()[:16]) != (0xfeedfacf, 0x100000c, 0, 1):
        raise SystemExit('NativeUfs: expected ordinary ARM64 Mach-O object')
    symbols = subprocess.check_output(['xcrun', 'nm', '-u', obj], text=True)
    if not args.root_windows and 'IOBlockStorageDevice' in symbols:
        raise SystemExit('Probe unexpectedly requires prelinked IOStorageFamily')
    if args.root_windows and 'IOBlockStorageDevice' not in symbols:
        raise SystemExit('Root-window build lacks the storage class')
    if args.component != 'NativeUfs':
        # Reuse the original storage imports already qualified and linked by NativeUfs.
        bindings = json.loads((root / 'build/native-ufs/bindings.json').read_text())['bindings']
        imports = subprocess.check_output(['xcrun', 'nm', '-u', '-j', obj], text=True).split()
        if any(name not in bindings for name in imports if 'IOBlockStorageDevice' in name):
            raise SystemExit('Root-binding helper has unqualified original storage imports')
        defined = subprocess.check_output(['xcrun', 'nm', '-U', '-j', obj], text=True).split()
        if args.component == 'NativeVirtioBlock' and ('_native_verified_block_root_authorized' not in defined or '_native_ufs_block_authenticates' not in imports):
            raise SystemExit('Root-binding helper lacks its mounted-device query or UFS callback')
        if args.component == 'NativeRamBlock' and '_native_ram_block_volume_seed' not in defined:
            raise SystemExit('RAM Data provider lacks its mounted-device query')
        (output / 'bindings.json').write_text(json.dumps({
            'compiled_object_sha256': hashlib.sha256(obj.read_bytes()).hexdigest(),
            'bindings': {name: bindings[name] for name in imports if 'IOBlockStorageDevice' in name},
        }, indent=2) + '\n')
    archive = output / ('lib' + args.component + '.a')
    archive.unlink(missing_ok=True)
    subprocess.run(['xcrun', 'ar', 'rcs', archive, obj], check=True)
    print(archive)


if __name__ == '__main__':
    main()
