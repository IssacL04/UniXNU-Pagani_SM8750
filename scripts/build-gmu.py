#!/usr/bin/env python3
"""Build the freestanding iOS 17 A830 GMU/HFI kit; this does not link a GPU driver."""
import argparse
import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('gpu_firmware', ROOT / 'scripts/prepare-gpu-firmware.py')
FIRMWARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIRMWARE)


def check_object(path):
    data = path.read_bytes()
    if struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 1):
        raise ValueError(f'{path}: expected ordinary arm64 Mach-O object')
    at = 32
    ios17 = False
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        command, size = struct.unpack_from('<II', data, at)
        if size < 8 or at + size > len(data):
            raise ValueError(f'{path}: invalid load command')
        if command == 0x32:
            ios17 = struct.unpack_from('<II', data, at + 8) == (2, 0x110000)
        at += size
    if not ios17:
        raise ValueError(f'{path}: expected iOS 17 build version')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clang', type=Path, required=True, help='clang with the arm64 Apple target; llvm-ar must be beside it')
    args = parser.parse_args()
    clang = args.clang.resolve()
    ar = clang.with_name('llvm-ar')
    output = ROOT / 'out/oneplus13t/gpu'
    FIRMWARE.prepare(ROOT / '.cache/firmware/pkx110-gpu', output)
    kit = ROOT.parent / 'UniXNU/kits/AdrenoFirmware'
    soc = ROOT.parent / 'UniXNU-sm8750-common/kits/Sm8750Platform'
    subprocess.run(['python3', ROOT / 'scripts/prepare-gpu-opps.py', '--check'], check=True)
    sources = [soc / 'Sm8750Gmu.c', soc / 'Sm8750GmuCommandDb.c', soc / 'Sm8750SocInfo.c', soc / 'Sm8750GpuZap.c', soc / 'Sm8750GpuPower.c', ROOT / 'package/PaganiGpuVotes.c',
               *[kit / name for name in ('AdrenoFirmware.c', 'AdrenoHfi.c', 'AdrenoHfiStartup.c', 'AdrenoHfiVotes.c')],
               output / 'firmware.S']
    with tempfile.TemporaryDirectory(prefix='gmu-build-', dir=output) as directory:
        work = Path(directory)
        objects = []
        for source in sources:
            obj = work / (source.stem + '.o')
            subprocess.run([clang, '-target', 'arm64-apple-ios17.0', '-O2', '-ffreestanding',
                            '-mgeneral-regs-only', '-Wall', '-Wextra', '-Werror',
                            '-I', kit, '-I', soc, '-c', source, '-o', obj], check=True)
            check_object(obj)
            objects.append(obj)
        archive = work / 'libSm8750Gmu.a'
        subprocess.run([ar, 'rcs', archive, *objects], check=True)
        members = subprocess.check_output([ar, 't', archive], text=True).splitlines()
        if members != [obj.name for obj in objects]:
            raise ValueError('GMU archive member mismatch')
        archive.replace(output / archive.name)
    print(f'PASS: iOS 17 arm64 GMU/HFI kit at {output / archive.name}; not a linked kernel or Metal plugin')


if __name__ == '__main__':
    main()
