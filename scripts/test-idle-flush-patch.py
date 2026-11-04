#!/usr/bin/env python3
"""patches/xnu/pagani-idle-flush.patch: it touches only osfmk/arm64/cpu.c, removes nothing but the unconditional
platform_cache_idle_enter() call, its boot-arg defaults to XNU's behaviour (the idle-entry L1 flush), and
pagani-idle-flush=0 skips that flush and nothing else. The patched lines of cpu_idle run in a host harness (stubbed TUNABLE
and platform_cache_idle_enter) for both values, with wfi on and off, and compile away on Apple targets.
With --xnu <tree> (an XNU checkout with the earlier series applied; only read) the patch is also applied to a copy of
<tree>/osfmk/arm64/cpu.c.
Run: python3 scripts/test-idle-flush-patch.py [--xnu <tree>]"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PATCH = Path(__file__).resolve().parents[1] / 'patches/xnu/pagani-idle-flush.patch'
XNU = None


def hunks(text):
    """The new side (context and added lines, markers stripped) of each hunk."""
    result, current = [], None
    for line in text.splitlines():
        if line.startswith('@@'):
            current = []
            result.append(current)
        elif current is not None and line.startswith((' ', '+')) and not line.startswith('+++'):
            current.append(line[1:])
        elif current is not None and line == '':
            current.append('')
    return result


class IdleFlushPatchTest(unittest.TestCase):
    def setUp(self):
        self.text = PATCH.read_text()
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_touches_only_cpu_idle_flush(self):
        self.assertEqual(re.findall(r'^--- a/(\S+)', self.text, re.M), ['osfmk/arm64/cpu.c'])
        self.assertEqual(re.findall(r'^\+\+\+ b/(\S+)', self.text, re.M), ['osfmk/arm64/cpu.c'])
        removed = [line[1:].strip() for line in self.text.splitlines() if line.startswith('-') and not line.startswith('---')]
        self.assertEqual(removed, ['platform_cache_idle_enter();'])
        self.assertIn('static TUNABLE(unsigned int, idle_cache_flush, "pagani-idle-flush", 1);', self.text)
        self.assertEqual(len(hunks(self.text)), 2)

    def harness(self, apple):
        first, second = hunks(self.text)
        start = first.index('#if !defined(APPLE_ARM64_ARCH_FAMILY)')
        end = next(i for i in range(start, len(first)) if first[i].startswith('#endif'))
        tunable = '\n'.join(first[start:end + 1])
        begin = next(i for i, line in enumerate(second) if line.strip() == 'if (wfi) {')
        close = next(i for i in range(begin, len(second)) if second[i].startswith('#endif'))
        block = '\n'.join(second[begin:close + 1])
        source = r'''
#include <stdio.h>
#include <stdlib.h>
#define TUNABLE(type_t, var, boot_arg, default_value) type_t var = default_value
static unsigned flushes, waits, wfi = 1;
static __attribute__((unused)) void platform_cache_idle_enter(void) { flushes++; }
''' + tunable + r'''
static void idle_once(void)
{
''' + block + r'''
        waits++; /* stands for the rest of the block: dsb, WFI */
    }
}
int main(int argc, char **argv)
{
    if (argc != 3) return 2;
    wfi = (unsigned)atoi(argv[1]);
#if !defined(APPLE_ARM64_ARCH_FAMILY)
    if (idle_cache_flush != 1) return 3;    /* the boot-arg default keeps XNU's flush */
    idle_cache_flush = (unsigned)atoi(argv[2]);
#endif
    for (int i = 0; i < 5; i++) idle_once();
    printf("%u %u\n", flushes, waits);
    return 0;
}
'''
        binary = Path(self.temp.name) / ('harness-apple' if apple else 'harness')
        command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-x', 'c', '-', '-o', str(binary)]
        if apple:
            command.insert(1, '-DAPPLE_ARM64_ARCH_FAMILY=1')
        subprocess.run(command, input=source, text=True, check=True)
        return binary

    def run_harness(self, binary, wfi, flush):
        out = subprocess.run([str(binary), str(wfi), str(flush)], capture_output=True, text=True, check=True).stdout
        return tuple(int(x) for x in out.split())

    def test_flush_switch(self):
        binary = self.harness(False)
        self.assertEqual(self.run_harness(binary, 1, 1), (5, 5))    # default: flush before every WFI, as before
        self.assertEqual(self.run_harness(binary, 1, 0), (0, 5))    # pagani-idle-flush=0: WFI without the flush
        self.assertEqual(self.run_harness(binary, 0, 1), (0, 0))    # wfi=0 still bypasses the whole block
        self.assertEqual(self.run_harness(binary, 0, 0), (0, 0))

    def test_apple_targets_unchanged(self):
        binary = self.harness(True)
        self.assertEqual(self.run_harness(binary, 1, 0), (0, 5))    # no flush call compiled in, no tunable

    def test_applies_to_tree(self):
        if XNU is None:
            self.skipTest('no --xnu tree given')
        original = Path(XNU) / 'osfmk/arm64/cpu.c'
        copy = Path(self.temp.name) / 'xnu/osfmk/arm64/cpu.c'
        copy.parent.mkdir(parents=True)
        shutil.copyfile(original, copy)
        subprocess.run(['patch', '-p1', '--dry-run', '-i', str(PATCH)], cwd=copy.parents[2], check=True,
                       capture_output=True)
        subprocess.run(['patch', '-p1', '-i', str(PATCH)], cwd=copy.parents[2], check=True, capture_output=True)
        patched = copy.read_text()
        self.assertEqual(patched.count('platform_cache_idle_enter();'), 1)
        self.assertIn('if (idle_cache_flush) {\n\t\t\tplatform_cache_idle_enter();', patched)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--xnu')
    args, rest = parser.parse_known_args()
    XNU = args.xnu
    unittest.main(argv=[sys.argv[0]] + rest)
