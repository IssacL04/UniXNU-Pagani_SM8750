#!/usr/bin/env python3
"""Build the SM8750 read-only UFS driver with the source kernel's IOKit ABI."""
import argparse
import json
from pathlib import Path
import runpy
import struct
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root-windows', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    compile_command = runpy.run_path(str(root / 'scripts/build-arm-platform.py'))['compile_command']
    recipe = root / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
    record = json.loads(recipe.read_text().strip().rstrip(','))
    output = root / 'build/native-ufs'
    output.mkdir(parents=True, exist_ok=True)
    obj = output / 'NativeUfs.o'
    command = compile_command(record, root / 'drivers/NativeUfs/NativeUfs.cpp', obj)
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
    archive = output / 'libNativeUfs.a'
    archive.unlink(missing_ok=True)
    subprocess.run(['xcrun', 'ar', 'rcs', archive, obj], check=True)
    print(archive)


if __name__ == '__main__':
    main()
