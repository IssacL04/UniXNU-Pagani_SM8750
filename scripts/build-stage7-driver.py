#!/usr/bin/env python3
"""Compile Stage 7 components with the kernel's own ABI and compiler flags."""
import argparse
import json
import runpy
from pathlib import Path
import struct
import subprocess

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('component', choices=['NativeLegacyDisplay', 'NativeKeyStoreEvents', 'Stage7Probe'])
component = parser.parse_args().component
directory = root / 'build' / ('native-keystore-events' if component == 'NativeKeyStoreEvents' else 'native-legacy-display')
directory.mkdir(parents=True, exist_ok=True)
source = (root / 'drivers/Stage7Probe/Stage7Probe.cpp' if component == 'Stage7Probe' else
          root / 'drivers' / ('NativeMobileDisplay' if component == 'NativeLegacyDisplay' else component) / (component + '.cpp'))
record = json.loads((root / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
obj = directory / (component + '.o')
compile_command = runpy.run_path(str(root / 'scripts/build-arm-platform.py'))['compile_command']
arguments = iter(compile_command(record, source, obj))
command = []
# Keep XNU's ABI; use the reference driver's warning policy instead of -Weverything.
for value in arguments:
    if value == '-Xclang':
        option = next(arguments)
        if not option.startswith('-W'):
            command += [value, option]
    elif not value.startswith('-W'):
        command.append(value)
command += ['-mgeneral-regs-only', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
            '-Wno-c99-designator', '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion',
            '-I', str(directory), '-I', str(root / '.cache/xnu-work/osfmk')]
subprocess.run(command, cwd=record['directory'], check=True)
data = obj.read_bytes()
assert struct.unpack_from('<4I', data) == (0xfeedfacf, 0x100000c, 0, 1), 'Require ARM64 Mach-O object'
offset, deployment = 32, None
for _ in range(struct.unpack_from('<I', data, 16)[0]):
    cmd, size = struct.unpack_from('<II', data, offset)
    if cmd == 0x32:
        deployment = struct.unpack_from('<II', data, offset + 8)
    offset += size
assert deployment == (2, 0x110000), 'Require iOS 17 target'
print(component + ': compile and object ABI checks passed')
