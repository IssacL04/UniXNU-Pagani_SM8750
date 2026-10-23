#!/usr/bin/env python3
"""Build the existing software AES provider for the pinned prelinked kernel."""
import json
from pathlib import Path
import runpy
import struct
import subprocess

root = Path(__file__).resolve().parents[1]
compile_command = runpy.run_path(str(root / 'scripts/build-arm-platform.py'))['compile_command']
recipe = root / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
record = json.loads(recipe.read_text().strip().rstrip(','))
out = root / 'build/native-aes'
out.mkdir(parents=True, exist_ok=True)
obj = out / 'NativeAES.o'
command = compile_command(record, root / 'drivers/NativeAES/NativeAES.cpp', obj)
subprocess.run(command, cwd=record['directory'], check=True)
if struct.unpack('<4I', obj.read_bytes()[:16]) != (0xfeedfacf, 0x100000c, 0, 1):
    raise SystemExit('NativeAES: expected ordinary ARM64 Mach-O object')
subprocess.run(['python3', root / 'scripts/build-native-aes-bindings.py'], check=True)
