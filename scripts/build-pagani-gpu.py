#!/usr/bin/env python3
"""Build the A830 board/backend archive from the prepared XNU compilation records."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile


def build(tree, kernelcache):
    board = (tree / 'kits/oneplus13t').resolve()
    device = board.parent
    sys.path.insert(0, str(tree / 'scripts'))
    sys.path.insert(0, str(tree / 'kits/NativePrelink'))
    from original_stage7 import OriginalImage
    original = OriginalImage(kernelcache)
    abi = json.loads((tree / 'scripts/data/ioaccelerator-base-abi.json').read_text())
    original.family_text('com.apple.iokit.IOGPUFamily', abi['original_iogpu_text_sha256'])
    for address, digest in abi['original_entry_sha256'].items():
        if hashlib.sha256(original.read(int(address, 16), 32)).hexdigest() != digest:
            raise ValueError('IOAcceleratorES original entry differs: ' + address)
    records = tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
    recipes = {}
    for suffix, name in (('.c', 'bsd/DEVELOPMENT/bsd_init.o.json'),
                         ('.cpp', 'iokit/DEVELOPMENT/IOPlatformExpert.cpo.json')):
        path = records / name
        if not path.is_file():
            raise ValueError('Prepare the production XNU compile records first: ' + str(path))
        recipes[suffix] = json.loads(path.read_text().strip().rstrip(','))
    subprocess.run([sys.executable, device / 'scripts/prepare-gpu-opps.py', '--check'], check=True)
    out = tree / 'build/adreno740'
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, device / 'scripts/prepare-gpu-firmware.py', '--output', out / 'firmware'], check=True)
    compile_command = runpy.run_path(str(tree / 'scripts/build-arm-platform.py'))['compile_command']
    check_object = runpy.run_path(str(device / 'scripts/build-gmu.py'))['check_object']
    gpu, soc = tree / 'drivers/Adreno740', tree / 'kits/Sm8750Platform'
    firmware, pm4, smmu = [tree / 'kits' / name for name in ('AdrenoFirmware', 'AdrenoPM4', 'ArmSmmu4K')]
    sources = [gpu / ('NativeAdreno' + name + '.cpp') for name in (
        'A830HwInit', 'CpInit', 'Cpu', 'GmuContext', 'GmuMemory', 'GpuContext', 'Irq', 'Memory',
        'Publish', 'Pwrup', 'Ring', 'Sha256', 'SmmuContext', 'SmmuMemory', 'Submit', 'Timer', 'UserClient', 'Vm')]
    sources += [soc / name for name in ('Sm8750Gmu.c', 'Sm8750GmuCommandDb.c', 'Sm8750GpuPower.c',
                                       'Sm8750GpuZap.c', 'Sm8750SocInfo.c', 'Sm8750GpuSmmu.c')]
    sources += [firmware / name for name in ('AdrenoFirmware.c', 'AdrenoHfi.c', 'AdrenoHfiStartup.c', 'AdrenoHfiVotes.c')]
    sources += sorted(smmu.glob('ArmSmmu4K*.c'))
    sources += [pm4 / 'AdrenoPM4.c', board / 'PaganiGpuVotes.c', board / 'PaganiGpu.cpp']
    includes = [gpu, soc, firmware, pm4, smmu, board, out / 'firmware', tree / '.cache/xnu-work/osfmk',
                tree / 'drivers/BootProgress']
    with tempfile.TemporaryDirectory(prefix='a830-', dir=out) as directory:
        work = Path(directory)
        objects = []
        failures = []
        for source in sources:
            record = recipes[source.suffix]
            obj = work / (source.stem + '.o')
            args = iter(compile_command(record, source, obj)); command = []
            for value in args:
                if value == '-Xclang':
                    option = next(args)
                    if not option.startswith('-W'):
                        command += [value, option]
                elif not value.startswith('-W'):
                    command.append(value)
            command += ['-mgeneral-regs-only', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                        '-Wno-c99-designator', '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion']
            for include in includes:
                command += ['-I', str(include)]
            if subprocess.run(command, cwd=record['directory']).returncode:
                failures.append(source.name)
                continue
            check_object(obj)
            objects.append(obj)
        if failures:
            raise ValueError('A830 compilation failed: ' + ', '.join(failures))
        obj = work / 'firmware.o'
        subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-c', out / 'firmware/firmware.S', '-o', obj], check=True)
        check_object(obj); objects.append(obj)
        archive = work / 'libAdreno740.a'
        subprocess.run(['xcrun', 'ar', 'rcs', archive, *objects], check=True)
        archive.replace(out / archive.name)
    # Reuses the qualified original base ABI; the initializer is explicitly staged.
    subprocess.run([sys.executable, tree / 'scripts/build-adreno740-accelerator.py'], check=True)
    defined = subprocess.check_output(['xcrun', 'nm', '-g', out / 'libAdreno740.a'], text=True)
    for name in ('pagani_gpu_start', 'Sm8750GmuColdStart', 'native_adreno_publish', 'native_adreno_accelerator_allocate'):
        if ' T _' + name not in defined:
            raise ValueError('Required archive definition absent: ' + name)
    print('PASS: A830 board/backend and staged accelerator compiled; device execution remains untested')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--kernelcache', type=Path, required=True)
    args = parser.parse_args()
    try:
        build(args.tree.resolve(), args.kernelcache.resolve())
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
