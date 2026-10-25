#!/usr/bin/env python3
"""Exercise the patched production UFS code without accessing a device."""
import argparse
import ast
from collections import Counter
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


def check_arm64_asm(device, tree, work):
    """Compile the actual multi-instruction templates with Apple's assembler syntax."""
    functions, expected = [], Counter()
    sources = (tree / 'drivers/PaganiArmCpu/ArmCpu.cpp', tree / 'drivers/NativeUfs/NativeUfs.cpp',
               device / 'drivers/BootProgress/BootProgress.c')

    def instruction(text):
        op, *args = text.lower().split(None, 1)
        arg = args[0] if args else ''
        if op == 'mrs':
            arg = arg.split(',')[-1].strip()
        elif op == 'msr':
            arg = arg.split(',')[0].strip()
        return op + ' ' + arg

    for source in sources:
        for match in re.finditer(r'(__asm__ volatile\s*\(("(?:\\.|[^"\\])*")[^;]*\);)', source.read_text()):
            statement, template = match.groups()
            template = ast.literal_eval(template)
            assert ';' not in template, f'Apple assembler treats semicolon as a comment: {source}'
            if '\n' not in template:
                continue
            operands = sorted(set(re.findall(r'"[=+&]*r"\s*\(\s*(\w+)\s*\)', statement)))
            declarations = ''.join(f'unsigned long long {name}=input;' for name in operands)
            stores = ''.join(f'out[{i}]={name};' for i, name in enumerate(operands))
            functions.append(f'extern "C" void test{len(functions)}(unsigned long long input, '
                             f'unsigned long long *out){{{declarations}{statement}{stores}}}')
            expected.update(instruction(line.strip()) for line in template.splitlines() if line.strip())
    assert len(functions) >= 20, 'Missing production assembly templates'
    source, binary = work / 'asm.cpp', work / 'asm.o'
    source.write_text('\n'.join(functions))
    subprocess.run([os.environ.get('CLANG', 'clang++'), '--target=arm64-apple-darwin',
                    '-O2', '-c', str(source), '-o', str(binary)], check=True, timeout=60)
    decoded = subprocess.check_output([os.environ.get('LLVM_OBJDUMP', 'llvm-objdump'),
                                      '--no-show-raw-insn', '-d', str(binary)], text=True)
    actual = Counter(instruction(line) for line in re.findall(r'\t((?:mrs|msr|isb|dsb)\b[^\n]*)', decoded))
    assert actual == expected, (expected - actual, actual - expected)
    print(f'PASS: {len(functions)} production ARM64 asm blocks retain every system instruction in Mach-O')


def check_gpu_addon(tree, work):
    source = (tree / 'drivers/NativeRamBlock/NativeRamBlock.cpp').read_text()
    body = source.split('extern "C" int native_ram_block_gpu_addon', 1)[1].split('extern "C" int native_ram_block_volume_seed', 1)[0]
    harness = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
static unsigned long gPhysBase=0x10000, gPhysSize=0x8000000;
static int gIODTPlane;
static bool present=true, property=true, mapped=true;
struct OSData {
  uint64_t range[2]={0x11000,4096}; unsigned length=16;
  unsigned getLength(){return length;} const void *getBytesNoCopy(){return range;}
} dataRange;
struct IORegistryEntry {
  static IORegistryEntry *fromPath(const char *,int){static IORegistryEntry entry;return present?&entry:nullptr;}
  void *getProperty(const char *){return property?&dataRange:nullptr;} void release(){}
};
#define OSDynamicCast(T,v) static_cast<T *>(v)
static uintptr_t ml_static_ptovirt(uint64_t p){return mapped?p:0;}
'''
    harness += 'extern "C" int native_ram_block_gpu_addon' + body
    harness += r'''
int main(){
  const uint8_t *data=nullptr; uint64_t bytes=0;
  auto invalid=[&](){data=reinterpret_cast<const uint8_t *>(1);bytes=1;
    assert(!native_ram_block_gpu_addon(&data,&bytes));assert(!data&&!bytes);};
  assert(native_ram_block_gpu_addon(&data,&bytes)&&bytes==4096&&reinterpret_cast<uintptr_t>(data)==0x11000);
  assert(!native_ram_block_gpu_addon(nullptr,&bytes));assert(!native_ram_block_gpu_addon(&data,nullptr));
  present=false;invalid();present=true;property=false;invalid();property=true;
  dataRange.length=8;invalid();dataRange.length=16;
  for(uint64_t size:{UINT64_C(0),UINT64_C(0x4000001),UINT64_MAX}){dataRange.range[1]=size;invalid();}
  dataRange.range[1]=4096;
  for(uint64_t base:{UINT64_C(0xf000),UINT64_C(0x11001),UINT64_C(0x8010000),UINT64_MAX}){dataRange.range[0]=base;invalid();}
  dataRange.range[0]=gPhysBase+gPhysSize-4096;dataRange.range[1]=8192;invalid();
  dataRange.range[0]=0x11000;dataRange.range[1]=4096;mapped=false;invalid();
}
'''
    path = work / 'gpu-addon.cpp'
    path.write_text('#include <initializer_list>\n' + harness)
    binary = work / 'gpu-addon'
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(path), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--openssl-prefix', type=Path, default=Path('/usr'))
    parser.add_argument('--captured', type=Path, help='Directory with locally captured GPT and first block')
    args = parser.parse_args()
    device = Path(__file__).resolve().parents[1]
    tree = args.tree
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
        check_arm64_asm(device, tree, Path(directory))
        check_gpu_addon(tree, Path(directory))
        for name in ('Sm8750', 'LunDiscovery', 'RootCommands', 'RootDiagnostics', 'RootLayout', 'SmmuTakeover', 'RootWindowRead', 'TransferPoll'):
            binary = Path(directory) / name
            command = [os.environ.get('CXX', 'c++'), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                       '-fsanitize=address,undefined', '-g', '-I' + str(tree / 'kits'), '-DNATIVE_UFS_SM8750=1', '-DUFS_ROOT_PARTITION=\"unixnu\"', '-DNATIVE_UFS_READ_ONLY=1',
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
