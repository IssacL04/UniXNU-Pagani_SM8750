#!/usr/bin/env python3
"""Source-kernel publication and compile-record regression checks (no Xcode)."""
import importlib.util
import hashlib
import json
import os
import runpy
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from unixnu import cli, kernel
from unixnu.config import ROOT
from unixnu.util import Error

spec = importlib.util.spec_from_file_location('arm_platform', ROOT / 'scripts/build-arm-platform.py')
arm_platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arm_platform)


class SourceKernelTest(unittest.TestCase):
    def test_ram_object_follows_the_selected_archive_directory(self):
        script = (ROOT / 'scripts/build-xnu-4k-baseline.sh').read_text()
        section = script.split('  if [ "$NATIVE_RAM_BLOCK" = 1 ]; then', 1)[1].split('  if [ "${XNU_SOURCE_PTHREAD:-0}" = 1 ]; then', 1)[0]
        archives = []
        for component in ('NativeVirtioBlock', 'NativeRamBlock'):
            directory = Path(self.temp.name) / component
            directory.mkdir()
            obj = directory / (component + '.o')
            obj.write_bytes(component.encode())
            archive = directory / ('lib' + component + '.a')
            archive.touch()
            archive.with_name('bindings.json').write_text(json.dumps({
                'compiled_object_sha256': hashlib.sha256(obj.read_bytes()).hexdigest(),
                'bindings': {'original_method': '0x1234'}}))
            archives.append(archive)
        env = dict(os.environ, ROOT=str(self.ctx.tree), NATIVE_RAM_BLOCK='1', XNU_NATIVE_VIRTIO_BLOCK='1',
                   VIRTIO_ARCHIVE=str(archives[0]), XNU_NATIVE_RAM_BLOCK_ARCHIVE=str(archives[1]),
                   KERNEL_EXTRA_ARCHIVES='', KERNEL_ARCHIVE_DEPENDENCIES='')
        command = 'set -eu\nif true; then\n' + section + '\nprintf "%s\\n" "$KERNEL_EXTRA_ARCHIVES"\n'
        result = subprocess.check_output(['bash'], input=command, text=True, env=env)
        self.assertEqual(result.strip(), str(archives[1].with_name('NativeRamBlock.o')))

    def test_early_framebuffer_page_tables_cover_vm_bootstrap(self):
        path = Path(__file__).resolve().parents[1] / 'patches/xnu/zzzzzzz-early-framebuffer-page-tables.patch'
        body = '\n'.join(line[1:] for line in path.read_text().splitlines()
                         if line.startswith((' ', '+')) and not line.startswith('+++'))
        calculation = body[body.index('\tmem_segments ='):body.index('\tcpu_l1_tte =')]
        source = r'''
#include <assert.h>
#include <stdint.h>
#define round_page(x) (((x) + 4095ULL) & ~4095ULL)
static uint64_t limit(uint64_t dynamic_memory_begin, uint64_t height, uint64_t pitch) {
    struct { struct { uint64_t v_height, v_rowBytes; } Video; } boot = {{height, pitch}}, *args = &boot;
    uint64_t mem_size = 256ULL << 20, mem_segments, va_l1, va_l1_end;
''' + calculation + r'''
    return va_l1_end;
}
int main(void) {
    const uint64_t base = 0xfffffff021600000ULL, fb = round_page(0xa50ULL * 0x1300);
    const uint64_t array = base + 2 * fb + 0x50000;
    assert(array == 0xfffffff022ece000ULL);
    const uint64_t old_end = (base + (12ULL << 20) + fb + 0x7fffff) & ~0x7fffffULL;
    assert(old_end == array + 306 * 4096); /* Observed run-13 L3 allocation. */
    for (uint64_t slide = 0; slide < (8ULL << 20); slide += 2ULL << 20) {
        const uint64_t start = base + slide;
        const uint64_t fb_count = XNU_EARLY_BOOT_PROGRESS ? 2 : 1;
        assert(start + fb_count * fb + 0x50000 + round_page(0x2b3bc0) <= limit(start, 0xa50, 0x1300));
        assert(limit(start, 0, 0) == ((start + (12ULL << 20) + 0x7fffff) & ~0x7fffffULL));
    }
    if (!XNU_EARLY_BOOT_PROGRESS) assert(limit(base, 0xa50, 0x1300) == old_end);
}
'''
        for mode in (0, 1):
            with self.subTest(mode=mode):
                binary = Path(self.temp.name) / f'page-tables-{mode}'
                subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                f'-DXNU_EARLY_BOOT_PROGRESS={mode}', '-x', 'c', '-', '-o', str(binary)],
                               input=source, text=True, check=True)
                subprocess.run([str(binary)], check=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.ctx = SimpleNamespace(tree=root / 'tree', work=root, board={'kernel': {'source_only': True}})
        self.source = root / 'tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf'
        self.source.parent.mkdir(parents=True)
        self.image = struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 0, 0, 0, 0)
        self.source.write_bytes(self.image)

    def test_source_publication_removes_stale_prelink_record(self):
        out = self.ctx.work / 'kernel'
        out.mkdir()
        (out / 'kernel.json').write_text('old prelink')
        result = kernel.export_source(self.ctx)
        self.assertEqual(result.read_bytes(), self.image)
        self.assertFalse((out / 'kernel.json').exists())
        self.assertFalse((out / 'kernel.macho.tmp').exists())

    def test_invalid_image_preserves_previous_kernel(self):
        old = kernel.export_source(self.ctx)
        for image in (b'', b'\xcf\xfa\xed\xfe', struct.pack('<8I', 0xfeedfacf, 0x100000c, 2, 2, 0, 0, 0, 0)):
            self.source.write_bytes(image)
            with self.assertRaises(Error):
                kernel.export_source(self.ctx)
            self.assertEqual(old.read_bytes(), self.image)

    def test_conflicting_config(self):
        self.ctx.board['kernel']['prelink'] = {'tool': 'something.py'}
        with self.assertRaises(Error):
            kernel.export_source(self.ctx)

    def test_source_build_never_calls_prelink(self):
        self.ctx.args = SimpleNamespace(steps=['kernel'])
        self.ctx.refuse_example = lambda: None
        self.ctx.need_config = lambda: {}
        for source_only in (True, False):
            self.ctx.board['kernel']['source_only'] = source_only
            with patch.object(cli, 'prepare', return_value={}), patch.object(kernel, 'build'), \
                    patch.object(kernel, 'prelink') as prelink, patch.object(kernel, 'export_source') as export:
                cli.cmd_build(self.ctx)
                self.assertEqual(export.call_count, int(source_only))
                self.assertEqual(prelink.call_count, int(not source_only))

    def test_driver_flags_keep_abi_and_do_not_overwrite_xnu_records(self):
        record = {'file': 'IOPlatformExpert.cpp', 'arguments': [
            'clang++', '-target', 'arm64-apple-ios17.0', '-mkernel', '-Werror', '-MMD', '-MP',
            '-MF', 'original.d', '-MJ', 'original.json', '-MT', 'original.o',
            '-c', 'IOPlatformExpert.cpp', '-o', 'original.o']}
        command = arm_platform.compile_command(record, Path('ArmCpu.cpp'), Path('ArmCpu.o'))
        self.assertEqual(command, ['clang++', '-target', 'arm64-apple-ios17.0', '-mkernel', '-Werror',
                                   '-c', 'ArmCpu.cpp', '-o', 'ArmCpu.o'])
        with self.assertRaises(ValueError):
            arm_platform.compile_command({'file': 'missing', 'arguments': record['arguments']}, Path('a'), Path('b'))

    def test_disabled_legacy_display_has_no_link_reference(self):
        path = ROOT / 'patches/xnu/offline-component-load-probes.patch'
        bsd_patch = path.read_text().split('--- a/iokit/')[0]
        source = '\n'.join(line[1:] for line in bsd_patch.splitlines()
                           if line.startswith('+') and not line.startswith('+++'))
        for mode in (None, 0, 1):
            with self.subTest(mode=mode):
                flags = [] if mode is None else [f'-DXNU_NATIVE_LEGACY_DISPLAY={mode}']
                output = subprocess.check_output(
                    ['cc', '-E', '-P', '-x', 'c', '-DDEVELOPMENT=1', *flags, '-'], input=source, text=True)
                self.assertEqual(output.count('native_legacy_display_probe'), 2 if mode == 1 else 0)


if __name__ == '__main__':
    unittest.main()
