#!/usr/bin/env python3
"""Compile the 13T early screen console with the actual XNU C ABI."""
import json
import os
from pathlib import Path
import runpy
import re
import struct
import subprocess


def main():
    if any(os.environ.get(name) != '1' for name in
           ('XNU_EARLY_BOOT_PROGRESS', 'XNU_ARM_DT_PLATFORM', 'XNU_ARMCPU')):
        raise SystemExit('13T boot progress requires early progress, ArmDTPlatform and ArmCpu')
    root = Path(__file__).resolve().parents[1]
    compile_command = runpy.run_path(str(root / 'scripts/build-arm-platform.py'))['compile_command']
    recipe = root / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/startup.o.json'
    record = json.loads(recipe.read_text().strip().rstrip(','))
    output = root / 'build/boot-progress'
    output.mkdir(parents=True, exist_ok=True)
    source = root / 'drivers/BootProgress'
    obj = output / 'BootProgress.o'
    command = compile_command(record, source / 'BootProgress.c', obj)
    # Bootstrap records disable the hooks; this object supplies their enabled implementation.
    args = iter(command)
    command = []
    for value in args:
        if value == '-D':
            define = next(args)
            if not define.startswith(('XNU_BOOT_PROGRESS=', 'XNU_EARLY_BOOT_PROGRESS=')):
                command += [value, define]
        elif not value.startswith(('-DXNU_BOOT_PROGRESS=', '-DXNU_EARLY_BOOT_PROGRESS=')):
            command.append(value)
    command += ['-DXNU_BOOT_PROGRESS=1', '-DXNU_EARLY_BOOT_PROGRESS=1',
                '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-mgeneral-regs-only', '-fno-jump-tables',
                '-I' + str(root / 'drivers/DarwinBoot/DarwinBootPkg/Driver')]
    subprocess.run(command, cwd=record['directory'], check=True)
    entry = output / 'Entry.o'
    subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-c', source / 'Entry.S', '-o', entry], check=True)
    for path in (obj, entry):
        if struct.unpack('<4I', path.read_bytes()[:16]) != (0xfeedfacf, 0x100000c, 0, 1):
            raise SystemExit(f'{path}: expected ordinary ARM64 Mach-O object')
    undefined = subprocess.check_output(['xcrun', 'nm', '-u', obj], text=True)
    if any(name in undefined for name in ('_memset', '_memcpy', '_bzero', 'stack_chk', 'chkstk')):
        raise SystemExit('Early console unexpectedly depends on a compiler runtime helper: ' + undefined)
    assembly = subprocess.check_output(['llvm-objdump', '-d', '--no-show-raw-insn', '--no-leading-addr', obj], text=True)
    if re.search(r'\b(?:[qds][0-9]+|v[0-9]+\.[0-9a-z]+)\b', assembly):
        raise SystemExit('Early/IRQ console unexpectedly uses FP/SIMD registers')
    archive = output / 'libBootProgress.a'
    archive.unlink(missing_ok=True)
    subprocess.run(['xcrun', 'ar', 'rcs', archive, obj, entry], check=True)
    print(archive)


if __name__ == '__main__':
    main()
