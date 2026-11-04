#!/usr/bin/env python3
"""patches/xnu/phone-vm-page-limits.patch: the pageout watermarks of the native 4 KiB kernel at the bytes of a 16 KiB iPhone. XNU writes them down as page
counts (VM_PAGE_FREE_MIN_LIMIT and the like), and in this configuration they are what counts: at 6 GiB the formulas below the limits give 7504 and 15004
pages, so both limits win. Run 20261101-110201 sat on the old floor, 127 and 128 pages free in 33 seconds.
With --inputs <xnu-inputs.json> (of a kernel build) the whole series as this checkout has it now goes on a fresh clone in order, with this patch last where
the series lacks it, with git apply as the build does; then vm_page_free_reserve as that tree has it runs in a host harness, in the order the boot calls it,
before and after this patch, for the 4 KiB kernel at several window sizes, with and without a compressor, and for a 16 KiB and a macOS configuration, which
have to stay as they were.
With --tree <kernel build tree> too (only read: the compile record of vm_pageout.o) vm_pageout.c of that clone is compiled as the kernel build compiles it,
into a temporary directory, and vm_page_free_reserve's immediates are checked: this is what says which branch of the macros this configuration takes.
Run: python3 scripts/test-vm-page-limits-patch.py [--inputs <xnu-inputs.json>] [--tree <tree>]"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PATCHES = Path(__file__).resolve().parents[1] / 'patches/xnu'
PATCH = PATCHES / 'phone-vm-page-limits.patch'
NEW = ['phone-vm-page-limits.patch']
INPUTS = None
TREE = None
PAGES_4K_6G = 1450000       # about what vm_page_free_count is when vm_pageout starts in a 6 GiB window (1499090 at vm_page_bootstrap)
HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
static struct { int vm_page_free_count_init; } vm_pageout_state;
static int compressor_present;
#define VM_CONFIG_COMPRESSOR_IS_PRESENT compressor_present
static unsigned int vm_page_free_reserved, vm_page_free_min, vm_page_free_target, vm_page_throttle_limit;
%(macros)s
%(function)s
int main(int argc, char **argv)
{
	(void)argc;
	compressor_present = atoi(argv[1]);
	/* thread_call_initialize, a VM-privileged thread, then vm_pageout with vm_page_free_count_init; a thread made privileged later. */
	vm_page_free_reserve(2);
	vm_page_free_reserve(1);
	vm_pageout_state.vm_page_free_count_init = atoi(argv[2]);
	if (vm_page_free_reserved < VM_PAGE_FREE_RESERVED(8)) {
		vm_page_free_reserve((VM_PAGE_FREE_RESERVED(8)) - vm_page_free_reserved);
	} else {
		vm_page_free_reserve(0);
	}
	vm_page_free_reserve(1);
	printf("%%u %%u %%u %%u\n", vm_page_free_reserved, vm_page_free_min, vm_page_free_target, vm_page_throttle_limit);
	return 0;
}
'''


def added(text):
    return [line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++')]


def block(text, begin, end):
    start = text.index(begin)
    return text[start:text.index(end, start) + len(end)]


def harness_source(root):
    """The macros and the function as that tree has them."""
    pageout = (root / 'osfmk/vm/vm_pageout.c').read_text()
    compressor = (root / 'osfmk/vm/vm_compressor.h').read_text()
    # From the #if that holds the first definition of the limit to its #endif, a nested one included.
    limit = compressor.index('#define COMPRESSOR_FREE_RESERVED_LIMIT')
    start = compressor.rindex('#if !XNU_TARGET_OS_OSX', 0, limit)
    end = compressor.index('#endif /* !XNU_TARGET_OS_OSX */', limit)
    macros = [block(pageout, '#ifndef VM_PAGE_LAUNDRY_MAX', '#endif'),
              block(pageout, '#ifndef VM_PAGE_FREE_TARGET\n', '#endif  /* VM_PAGE_FREE_RESERVED */'),
              compressor[start:end] + '#endif\n']
    function = block(pageout, 'void\nvm_page_free_reserve(\n', '\n}\n')
    return HARNESS % {'macros': '\n'.join(macros), 'function': 'static ' + function}


class VmPageLimitsPatchTest(unittest.TestCase):
    def setUp(self):
        self.text = PATCH.read_text()
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_touches_the_two_files_and_removes_nothing(self):
        self.assertEqual(re.findall(r'^\+\+\+ b/(\S+)', self.text, re.M), ['osfmk/vm/vm_compressor.h', 'osfmk/vm/vm_pageout.c'])
        self.assertEqual([line for line in self.text.splitlines() if line.startswith('-') and not line.startswith('---')], [])

    def test_no_build_switch(self):
        # On in every build. It may not hang on XNU_BOOT_PROGRESS: vm_pageout.o is not among the objects the kernel build's second pass rebuilds.
        self.assertNotIn('XNU_BOOT_PROGRESS', self.text)
        self.assertNotIn('PE_parse_boot', self.text)

    def test_only_the_native_4k_branch_changes(self):
        guards = [line for line in added(self.text) if line.startswith('#if')]
        self.assertEqual(guards, ['#if !defined(APPLE_ARM64_ARCH_FAMILY) && !__ARM_16K_PG__'] * 2)
        defines = dict(re.findall(r'^#define (\S+)\s+(\d+)', '\n'.join(added(self.text)), re.M))
        # The old numbers come back in the #else: four times them, and the sum stays four times 128.
        self.assertEqual(defines, {'COMPRESSOR_FREE_RESERVED_LIMIT': '112', 'VM_PAGE_FREE_RESERVED_LIMIT': '400', 'VM_PAGE_FREE_MIN_LIMIT': '6000',
                                   'VM_PAGE_FREE_TARGET_LIMIT': '8000'})

    def clone(self, patches):
        inputs = json.loads(Path(INPUTS).read_text())
        root = self.work / 'clone'
        subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', inputs['source'], str(root)], check=True)
        subprocess.run(['git', '-C', str(root), 'checkout', '--quiet', '--detach', inputs['commit']], check=True)
        for patch in patches:
            result = subprocess.run(['git', '-C', str(root), 'apply', str(patch)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f'{patch.name}: {result.stderr[-400:]}')
        return root

    def series(self):
        inputs = json.loads(Path(INPUTS).read_text())
        before = [Path(patch['path']) for patch in inputs['patches'] if Path(patch['path']).parent != PATCHES]
        lines = [line.strip() for line in (PATCHES / 'series').read_text().splitlines()]
        patches = before + [PATCHES / name for name in lines if name and not name.startswith('#') and name not in NEW]
        return patches

    def run_harness(self, name, root, flags=()):
        source = self.work / (name + '.c')
        source.write_text(harness_source(root))
        binary = self.work / name
        subprocess.run(['xcrun', 'clang', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', *flags, str(source), '-o', str(binary)], check=True)

        def limits(compressor, free):
            out = subprocess.run([str(binary), str(compressor), str(free)], capture_output=True, text=True, check=True).stdout
            return tuple(int(value) for value in out.split())
        return limits

    def test_series_and_the_limits(self):
        if INPUTS is None:
            self.skipTest('no --inputs xnu-inputs.json given')
        root = self.clone(self.series())
        before = self.run_harness('before', root)
        self.assertEqual(before(1, PAGES_4K_6G), (128, 1500, 2000, 1000))
        others = (('apple', ['-DAPPLE_ARM64_ARCH_FAMILY=1'], 380000), ('page16k', ['-D__ARM_16K_PG__=1'], 380000), ('macos', ['-DXNU_TARGET_OS_OSX=1'], 2000000))
        unchanged = {name: self.run_harness(name + '-before', root, flags)(1, free) for name, flags, free in others}
        self.assertEqual(unchanged['apple'], (128, 1500, 2000, 1000))
        self.assertEqual(unchanged['page16k'], (128, 1500, 2000, 1000))
        result = subprocess.run(['git', '-C', str(root), 'apply', str(PATCH)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        after = self.run_harness('after', root)
        # 6 GiB, what this phone has and the compressor present as mode 8 and mode 2 both have it: 2 MiB, 23.4 MiB, 31.2 MiB, as 16 KiB pages give them.
        self.assertEqual(after(1, PAGES_4K_6G), (512, 6000, 8000, 4000))
        self.assertEqual(after(0, PAGES_4K_6G), (400, 6000, 8000, 4000))
        # 8 GiB and 12 GiB: the limits still win.
        self.assertEqual(after(1, 2 * PAGES_4K_6G), (512, 6000, 8000, 4000))
        # 4 GiB: the formula is below the first limit and takes over, the target below it stays above min + 5.
        self.assertEqual(after(1, 950000), (512, 5269, 8000, 4000))
        reserved, low, target, throttle = after(1, 200000)
        self.assertEqual((reserved, low, target, throttle), (512, 1519, 2521, 1261))
        self.assertGreaterEqual(target, low + 5)
        # What must stay: a 16 KiB kernel and macOS.
        for name, flags, free in others:
            self.assertEqual(self.run_harness(name, root, flags)(1, free), unchanged[name], name)
        if TREE is not None:
            self.check_object(root)

    def check_object(self, root):
        tree = Path(TREE)
        directory = tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT'
        record = json.loads((directory / 'vm_pageout.o.json').read_text().strip().rstrip(','))
        original = str(tree / '.cache/xnu-work')
        output = self.work / 'vm_pageout.o'
        arguments, words = [], iter(record['arguments'])
        for word in words:
            if word in ('-MD', '-MP'):
                continue
            if word in ('-MF', '-MT', '-MQ'):
                next(words)
                continue
            if word == '-o':
                next(words)
                arguments += ['-o', str(output)]
                continue
            arguments.append(word.replace(original, str(root)))
        result = subprocess.run(arguments, cwd=record['directory'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        disassembly = subprocess.run(['xcrun', 'llvm-objdump', '-d', '--no-show-raw-insn', '--disassemble-symbols=_vm_page_free_reserve', str(output)],
                                     capture_output=True, text=True, check=True).stdout
        immediates = {int(value, 0) for value in re.findall(r'#(0x[0-9a-f]+|\d+)', disassembly)}
        self.assertTrue({512, 400, 112, 6000, 8000} <= immediates, sorted(immediates))
        self.assertFalse({128, 100, 1500, 2000, 28} & immediates, sorted(immediates))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs')
    parser.add_argument('--tree')
    args, rest = parser.parse_known_args()
    INPUTS = args.inputs
    TREE = args.tree
    unittest.main(argv=[sys.argv[0]] + rest)
