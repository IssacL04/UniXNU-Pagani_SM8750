#!/usr/bin/env python3
"""Bind read-only NativeUfs to the pinned original IOBlockStorageDevice ABI.

Adapted from Allenwdk/UniXNU-uke 0fde2b1b53b871e9b33b1b242a7034f56e2c71c4,
scripts/build-ufs-original-bindings.py. Qualifies the original image directly,
then applies the same fixed slide as NativePrelink. Runtime remains untested.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kits/NativePrelink'))
import native_prelink as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--kernelcache', type=Path, required=True)
args = parser.parse_args()
component = 'NativeUfs'
args.objects_dir = ROOT / 'build/native-ufs'
SLIDE = -0x1000000

KERNELCACHE_SHA256 = 'f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7'
SOURCE_REVISION = 'e45fbe30a7879e0b16e26dddb78538f1b00e0bff'


def require(value, message):
    if not value:
        raise SystemExit(message)


def read(image, data, va, length):
    at = np.backed_offset(image['segments'], va, length, len(data))
    return data[at:at + length]


def returned_address(image, data, va):
    a, add, ret = struct.unpack('<3I', read(image, data, va, 12))
    if a & 0x9f00001f != 0x90000000 or add & 0xffc003ff != 0x91000000 or ret != 0xd65f03c0:
        return None
    immediate = ((a >> 5 & 0x7ffff) << 2) | (a >> 29 & 3)
    if immediate & 0x100000:
        immediate -= 0x200000
    return (va & ~4095) + immediate * 4096 + (add >> 10 & 4095)


# The reference object supplies the public class dispatch order. It is compiled
# against the same kernel headers as the driver and never linked or executed.
source = ROOT / 'refer/IOStorageFamily'
revision = subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD'], text=True).strip()
require(revision == SOURCE_REVISION, f'Unexpected public IOStorageFamily revision: {revision}')
headers = ROOT / 'build/storage-abi/include/IOKit/storage'
require((headers / 'IOBlockStorageDevice.h').is_file(),
        'Run prepare-storage-headers.py before this binder')
out = args.objects_dir.resolve()
out.mkdir(parents=True, exist_ok=True)
recipe = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/'
                     'IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
reference = out / 'IOBlockStorageDevice-reference.o'
arguments = recipe['arguments']
command, index = [], 0
while index < len(arguments):
    value = arguments[index]
    if value == recipe['file']:
        command.append(str(source / 'IOBlockStorageDevice.cpp'))
    elif value == '-o':
        command += ['-o', str(reference)]
        index += 1
    elif value in ('-MF', '-MJ'):
        index += 1
    elif value == '-Xclang' and arguments[index + 1].startswith('-W'):
        index += 1
    elif not value.startswith('-W') and value not in ('-MD', '-MP'):
        command.append(value)
    index += 1
command += ['-I', str(ROOT / 'build/storage-abi/include'), '-I', str(ROOT / '.cache/xnu-work/osfmk'),
            '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-deprecated-declarations',
            '-Wno-c99-designator', '-Wno-reorder-init-list',
            '-Wno-deprecated-enum-enum-conversion']
result = subprocess.run(command, cwd=recipe['directory'], capture_output=True, text=True)
(reference.with_suffix('.log')).write_text(result.stdout + result.stderr)
require(result.returncode == 0, (result.stdout + result.stderr)[-3500:])

obj = reference.read_bytes()
om = np.macho(obj)
require(om['kind'] == 1, 'Expected an ordinary ARM64 reference object')
sycmd = next(at for cmd, at, size in om['commands'] if cmd == 2)
symoff, count, stroff, _ = struct.unpack_from('<4I', obj, sycmd + 8)
symbols = []
for i in range(count):
    ix, kind, _, _, value = struct.unpack_from('<IBBHQ', obj, symoff + i * 16)
    symbols.append(dict(name=obj[stroff + ix:obj.index(b'\0', stroff + ix)].decode(), value=value, kind=kind))
vtable = next(s['value'] for s in symbols if s['name'] == '__ZTV20IOBlockStorageDevice')
end = min(s['value'] for s in symbols
          if not s['kind'] & 0xe0 and s['kind'] & 0xe == 0xe and s['value'] > vtable)
relocations = {}
for segment in om['segments']:
    for section in segment['sections']:
        if section['va'] <= vtable < section['va'] + section['size']:
            ro, rc = struct.unpack_from('<II', obj, section['command_offset'] + 56)
            for i in range(rc):
                address, word = struct.unpack_from('<II', obj, ro + i * 8)
                if word >> 27 & 1 and word >> 28 == 0 and word >> 25 & 3 == 3:
                    relocations[section['va'] + address] = symbols[word & 0xffffff]['name']
methods = []
for at in range(vtable + 16, end, 8):
    if at not in relocations:
        break
    methods.append(relocations[at])
require(len(methods) == 190 and methods.count('___cxa_pure_virtual') == 14,
        'Public iOS IOBlockStorageDevice dispatch shape changed')

# Qualify original pointers before applying the prelink slide.
candidate = args.kernelcache.read_bytes()
require(hashlib.sha256(candidate).hexdigest() == KERNELCACHE_SHA256, 'Unexpected kernelcache')
native = np.macho(candidate)
exports = np.exports(candidate, native)
by_name = {name: va for va, names in exports.items() for name in names}
info = next(segment for segment in native['segments'] if segment['name'] == '__PRELINK_INFO')
metadata = np.unserialize_xml(read(native, candidate, info['va'], info['filesize']))
entry, = [entry for entry in metadata['_PrelinkInfoDictionary']
          if entry['CFBundleIdentifier'] == 'com.apple.iokit.IOStorageFamily']
at = np.backed_offset(native['segments'], entry['_PrelinkExecutableLoadAddr'], 32, len(candidate))
storage = np.macho(candidate, at)
const = next(segment for segment in storage['segments'] if segment['name'] == '__DATA_CONST')
text = next(segment for segment in storage['segments'] if segment['name'] == '__TEXT_EXEC')
blob = read(native, candidate, const['va'], const['size'])
found = []
for at in range(0, len(blob) - (len(methods) + 2) * 8 + 1, 8):
    if blob[at:at + 16] != bytes(16):
        continue
    pointers = struct.unpack_from('<' + 'Q' * len(methods), blob, at + 16)
    if all(pointers[i] == by_name[name] for i, name in enumerate(methods) if name in by_name):
        found.append((const['va'] + at, pointers))
require(len(found) == 1, 'Cannot uniquely identify the original block-storage class dispatch')
table, pointers = found[0]
matched = sum(name in by_name for name in methods)
require(matched == 176, f'Unexpected original/native kernel binding count: {matched}')

constructors = []
for address in range(text['va'], text['va'] + text['size'] - 32, 4):
    words = struct.unpack('<8I', read(native, candidate, address, 32))
    if (words[:2] != (0xa9bf7bfd, 0x910003fd) or words[2] & 0xfc000000 != 0x94000000 or
        words[3] & 0x9f00001f != 0x90000008 or words[4] & 0xffc003ff != 0x91000108 or
        words[5:] != (0xf9000008, 0xa8c17bfd, 0xd65f03c0)):
        continue
    immediate = ((words[3] >> 5 & 0x7ffff) << 2) | (words[3] >> 29 & 3)
    if immediate & 0x100000:
        immediate -= 0x200000
    stored = ((address + 12) & ~4095) + immediate * 4096 + (words[4] >> 10 & 4095)
    if stored == table + 16:
        constructors.append(address)
require(len(constructors) == 1, 'Cannot uniquely qualify the original protected constructor')
meta = returned_address(native, candidate, pointers[7])
require(meta is not None, 'Unqualified original metaclass getter')
destructor = pointers[0] - 4
def tail_target(address):
    word, = struct.unpack('<I', read(native, candidate, address, 4))
    require(word & 0xfc000000 == 0x14000000, 'Destructor is not a tail branch')
    immediate = word & 0x3ffffff
    if immediate & 0x2000000:
        immediate -= 0x4000000
    return address + immediate * 4
# Abstract-class D1/D0 trap; its callable D2 tail-calls the imported IOService D2.
require(all(read(native, candidate, address, 4) == struct.pack('<I', 0xd4200020)
            for address in pointers[:2]), 'Unexpected abstract destructor entries')
stub = tail_target(destructor)
adrp, ldr, branch = struct.unpack('<3I', read(native, candidate, stub, 12))
require(adrp & 0x9f00001f == 0x90000010 and ldr & 0xffc003ff == 0xf9400210 and
        branch == 0xd61f0200, 'Unqualified base-destructor import stub')
immediate = ((adrp >> 5 & 0x7ffff) << 2) | (adrp >> 29 & 3)
if immediate & 0x100000:
    immediate -= 0x200000
slot = (stub & ~4095) + immediate * 4096 + (ldr >> 10 & 4095) * 8
target, = struct.unpack('<Q', read(native, candidate, slot, 8))
require(target == by_name['__ZN9IOServiceD2Ev'], 'Unexpected base-destructor target')


possible = {name: pointers[i] for i, name in enumerate(methods)}
possible.update({'__ZN20IOBlockStorageDeviceC2EPK11OSMetaClass': constructors[0],
                 '__ZN20IOBlockStorageDeviceD2Ev': destructor,
                 '__ZN20IOBlockStorageDevice10gMetaClassE': meta,
                 '__ZTV20IOBlockStorageDevice': table})

object_path = out / (component + '.o')
require(object_path.is_file(), f'Build {component}.o before this binder')
undefined = subprocess.check_output(['xcrun', 'nm', '-u', '-j', object_path], text=True).split()
undefined = [name for name in undefined if 'IOBlockStorageDevice' in name]
require(undefined, f'No original block-storage imports found in {component}.o')
missing = [name for name in undefined if name not in possible]
require(not missing, 'Unqualified original storage import: ' + ', '.join(missing))
bindings = {name: possible[name] + SLIDE for name in undefined}
assembly = out / 'original-bindings.S'
assembly.write_text(''.join(f'.globl {name}\n.set {name}, {value:#x}\n' for name, value in sorted(bindings.items())))
subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-Werror', '-Wno-incompatible-sysroot',
                '-c', assembly, '-o', out / 'original-bindings.o'], check=True)
archive = out / ('lib' + component + '.a')
archive.unlink(missing_ok=True)
subprocess.run(['xcrun', 'ar', 'rcs', archive, object_path, out / 'original-bindings.o'], check=True)
(out / 'bindings.json').write_text(json.dumps(dict(
    component=component,
    original_sha256=KERNELCACHE_SHA256, slide=hex(SLIDE),
    vtable=hex(table), original_metaclass=hex(meta), protected_constructor=hex(constructors[0]),
    original_base_destructor=hex(destructor), virtual_methods_checked=len(methods),
    kernel_bindings=matched, unresolved_original_imports=0,
    bindings={name: hex(value) for name, value in bindings.items()},
    live_qualified=False, actual_io_qualified=False), indent=2) + '\n')
print(f'PASS: {len(bindings)} {component} bindings from the pinned kernelcache '
      f'({matched} kernel method bindings, {len(methods)} slots)')
