#!/usr/bin/env python3
"""patches/xnu/phone-bootstrap-tables.patch: the pool of bootstrap page tables grows from 16 to 34 pages, for windows above 6 GiB, and the
two dead ends of start.s's table setup (the Lbootstrap_tables_exhausted spin, brk #0xe01 after early_boot_progress_map) become a PSCI
SYSTEM_RESET, so a window that does not fit takes the phone back to Android instead of leaving it to the buttons.

1. The patch as text: what it touches, the reset's calls against the values RamoopsLog.c, GunyahWdog.h and the device tree use, and no
   memory access, stack or call in code that runs with the MMU and the caches off. Each criterion has a mutation of the patch it must catch.
2. The reset as code, on this arm64 host: the patch's own instructions with smc #0 turned into a call that records x0-x3 and destroys
   x4-x17: SYSTEM_RESET first, the watchdog only if it returns, then the reset once a second.
3. The tables as code, on this arm64 host: the macros and the set-up lines of the patched start.s (from --xnu or --inputs, else the build's
   tree if it is there) over a real pool with a guard behind it, with the kernel's own offsets. How many pages each window takes, where the
   pool stops it, that 6 GiB writes byte for byte the same tables as before with the rest of the pool empty, and that no write
   leaves the pool.
With --xnu <tree> (an XNU checkout with the earlier series applied; only read) the patch is also applied to a copy of its two files.
With --inputs <xnu-inputs.json> (of a kernel build) the whole series as this checkout has it, then this patch when the series does not
list it yet, goes on a fresh clone with git apply as the build does, and patched start.s is assembled with the build's own compile record.
Run: python3 scripts/test-bootstrap-tables-patch.py [--xnu <tree>] [--inputs <xnu-inputs.json>]"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = ROOT.parent
PATCHES = ROOT / 'patches/xnu'
PATCH = PATCHES / 'phone-bootstrap-tables.patch'
DTSI = TOP / 'UniXNU-sm8750-common/dts/sm8750.dtsi'
RAMOOPS = TOP / 'UniXNU-Pagani-Drivers/drivers/BootProgress/RamoopsLog.c'
WDOG_H = TOP / 'UniXNU-Pagani-Drivers/drivers/BootProgress/GunyahWdog.h'
BUILD = TOP / 'UniXNU/out-gpu/oneplus13t/ipados-17.7.11-21H461/oneplus13t/tree'
FILES = ['osfmk/arm/pmap/pmap.h', 'osfmk/arm64/start.s']
XNU = None
INPUTS = None

PSCI_SYSTEM_RESET = 0x84000009
PSCI_SYSTEM_RESET2 = 0xc4000012
PSCI_SYSTEM_OFF = 0x84000008
WDOG_SET_TIME = 0x86000008
WDOG_CONTROL = 0x86000005

# The kernel's layout (kernel.macho 75e75d4e): __PRELINK_TEXT, DarwinBoot's Kernel.Base, starts the image and _mh_execute_header follows
# 0x2d88000 later, so with the first free run at 0x8c0000000 the window starts at 0x8c007c000 (the run's log: xnu ram=0x8c007c000).
PHYS_BASE = 0x8c007c000
VIRT_BASE = 0xfffffff00427c000
HEADER_OFFSET = 0x2d88000
GIB = 1 << 30

# 4 KiB constants of osfmk/arm64/proc_reg.h as this kernel assembles them (__ARM64_PMAP_SUBPAGE_L1__: 256 entries in L1, start.o's
# "and x10, x0, #0x3fc0000000"; mov #0x601 and #3 are ARM_TTE_BOOT_BLOCK and ARM_TTE_BOOT_TABLE).
CONSTANTS = {
    'ARM_TT_L1_SHIFT': '30', 'ARM_TT_L1_INDEX_MASK': '0x0000003fc0000000', 'ARM_TT_L2_SHIFT': '21', 'ARM_TT_L2_SIZE': '0x200000',
    'ARM_TT_L2_INDEX_MASK': '0x000000003fe00000', 'ARM_TTE_BLOCK_L2_SHIFT': '21', 'ARM_TTE_BLOCK_L2_MASK': '0x0000ffffffe00000',
    'ARM_TTE_TABLE_MASK': '0x0000fffffffff000', 'ARM_TTE_BOOT_TABLE': '3', 'ARM_TTE_BOOT_BLOCK': '0x601', 'TTE_SHIFT': '3',
    'TTE_PGENTRIES': '512', 'PGBYTES': '4096',
}


def new_side(text, path):
    """The new side of the patch's hunks for one file, markers stripped."""
    start = text.index(f'+++ b/{path}')
    following = text.find('\n--- a/', start)
    body = text[start:following if following >= 0 else len(text)]
    return [line[1:] for line in body.splitlines()[1:] if line[:1] in (' ', '+')]


def added(text):
    return [line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++')]


def removed(text):
    return [line[1:] for line in text.splitlines() if line.startswith('-') and not line.startswith('---')]


def stub_lines(text):
    """(the macro's definition, the instructions from the label up to Lbootstrap_tables_ready), with their comments gone."""
    lines = new_side(text, 'osfmk/arm64/start.s')
    begin = next(i for i, line in enumerate(lines) if line.startswith('.macro bootstrap_smc'))
    end = next(i for i in range(begin, len(lines)) if lines[i].startswith('.endmacro'))
    label = next(i for i, line in enumerate(lines) if line.startswith('Lbootstrap_tables_exhausted:'))
    ready = next(i for i, line in enumerate(lines) if line.startswith('Lbootstrap_tables_ready:'))
    return lines[begin:end + 1], lines[label + 1:ready]


def calls_of(stub):
    """The bootstrap_smc lines of the stub as numbers."""
    result = []
    for line in stub:
        match = re.fullmatch(r'\s*bootstrap_smc\s+(0x[0-9a-f]+),\s*(\d+),\s*(\d+)', line)
        if match:
            result.append(tuple(int(value, 0) for value in match.groups()))
    return result


def problems(text):
    """Every way the patch text misses a criterion, as sentences; empty when it meets all of them."""
    found = []
    if re.findall(r'^\+\+\+ b/(\S+)', text, re.M) != FILES:
        found.append('touches other files')
    if '#define BOOTSTRAP_TABLE_SIZE (ARM_PGBYTES * 34)' not in added(text):
        found.append('the pool is not 34 pages')
    if '#define BOOTSTRAP_TABLE_SIZE (ARM_PGBYTES * 16)' not in removed(text):
        found.append('the 16-page pool stays')
    start = new_side(text, 'osfmk/arm64/start.s')
    if any('brk #0xe01' in line for line in start):
        found.append('brk #0xe01 stays: that is the EARLY EXCEPTION screen, and it halts')
    after_map = start[next(i for i, line in enumerate(start) if 'bl EXT(early_boot_progress_map)' in line):]
    if [line.strip() for line in after_map[1:3]] != ['cbnz x0, 1f', 'b Lbootstrap_tables_exhausted']:
        found.append('a failed framebuffer map does not reset')
    try:
        macro, stub = stub_lines(text)
    except StopIteration:
        return found + ['no reset path']
    body = '\n'.join(macro + stub)
    if 'b Lbootstrap_tables_exhausted' in body:
        found.append('the label still spins on itself')
    if 'smc\t\t#0' not in body or 'hvc' in body:
        found.append('the conduit is not SMC #0')
    # Only registers: the MMU and the caches are off and there is no stack; a load, a store or a call would be a bug.
    for line in macro[1:-1] + stub:
        words = line.split()
        if not words or words[0].endswith(':'):
            continue
        if words[0] not in ('movz', 'movk', 'mov', 'smc', 'mrs', 'isb', 'add', 'cmp', 'b.lo', 'b', 'bootstrap_smc'):
            found.append(f'{words[0]} in the reset path: registers only')
    calls = calls_of(stub)
    if calls[:1] != [(PSCI_SYSTEM_RESET, 0, 0)]:
        found.append('SYSTEM_RESET is not the first call')
    if any(call[0] in (PSCI_SYSTEM_RESET2, PSCI_SYSTEM_OFF) for call in calls):
        found.append('a call this phone refuses, or a power off')
    if calls[1:3] != [(WDOG_SET_TIME, 2000, 4000), (WDOG_CONTROL, 3, 0)]:
        found.append('the watchdog is not armed after a returned reset')
    if calls[3:] != [(PSCI_SYSTEM_RESET, 0, 0)]:
        found.append('no retry')
    if not stub or stub[-1].split() != ['b', '1b']:
        found.append('the retry does not loop')
    return found


class PatchText(unittest.TestCase):
    def setUp(self):
        self.text = PATCH.read_text()

    def test_meets_every_criterion(self):
        self.assertEqual(problems(self.text), [])

    def test_only_the_size_and_the_dead_ends_change(self):
        self.assertEqual(sorted(line.strip() for line in removed(self.text) if 'BOOTSTRAP' in line or 'brk' in line or line.startswith('\tb ')),
                         ['#define BOOTSTRAP_TABLE_SIZE (ARM_PGBYTES * 16)', 'b Lbootstrap_tables_exhausted', 'brk #0xe01'])
        # The old comments and the three words of the spin are all it takes away.
        self.assertEqual(len(removed(self.text)), 7)

    def test_values_match_the_kernels_own(self):
        """The patch cannot read the device tree or call these drivers: its numbers have to be theirs."""
        self.assertIn('method = "smc"', re.search(r'psci \{.*?\};', DTSI.read_text(), re.S).group(0))
        ramoops = RAMOOPS.read_text()
        self.assertIn(f'#define PSCI_SYSTEM_RESET {PSCI_SYSTEM_RESET:#x}u', ramoops)
        wdog = WDOG_H.read_text()
        self.assertIn(f'#define GUNYAH_WDOG_FN_SET_TIME {WDOG_SET_TIME:#x}u', wdog)
        self.assertIn(f'#define GUNYAH_WDOG_FN_CONTROL {WDOG_CONTROL:#x}u', wdog)
        self.assertIn('#define GUNYAH_WDOG_CTRL_ENABLE 3u', wdog)
        self.assertIn('#define GUNYAH_WDOG_MIN_SECONDS 4u', wdog)     # bite 4000 ms, bark half of it: gunyah_wdog_after_failed_reset

    def test_mutations_are_caught(self):
        mutations = {
            'pool stays 16': ('+#define BOOTSTRAP_TABLE_SIZE (ARM_PGBYTES * 34)', '+#define BOOTSTRAP_TABLE_SIZE (ARM_PGBYTES * 16)'),
            'hvc': ('+\tsmc\t\t#0', '+\thvc\t\t#0'),
            'power off': ('+\tbootstrap_smc 0x84000009, 0, 0\n+\tbootstrap_smc 0x86000008', '+\tbootstrap_smc 0x84000008, 0, 0\n+\tbootstrap_smc 0x86000008'),
            'SYSTEM_RESET2 first': ('+\tbootstrap_smc 0x84000009, 0, 0\n+\tbootstrap_smc 0x86000008', '+\tbootstrap_smc 0xc4000012, 0, 0\n+\tbootstrap_smc 0x86000008'),
            'a stack push': ('+\tmrs\t\tx4, CNTFRQ_EL0', '+\tstr\t\tx0, [sp, #-16]!\n+\tmrs\t\tx4, CNTFRQ_EL0'),
            'a call': ('+\tmrs\t\tx4, CNTFRQ_EL0', '+\tbl\t\t_printf\n+\tmrs\t\tx4, CNTFRQ_EL0'),
            'no watchdog': ('+\tbootstrap_smc 0x86000005, 3, 0\n', ''),
            'bite off': ('2000, 4000', '2000, 0'),
            'spin kept': ('+\tb\t\t1b', '+\tb Lbootstrap_tables_exhausted'),
            'no retry': ('+\tb.lo\t2b\n+\tbootstrap_smc 0x84000009, 0, 0\n', '+\tb.lo\t2b\n'),
            'brk kept': ('+\tb Lbootstrap_tables_exhausted\n 1:', '+\tbrk #0xe01\n 1:'),
        }
        for name, (old, new) in mutations.items():
            self.assertEqual(self.text.count(old), 1, name)
            self.assertNotEqual(problems(self.text.replace(old, new)), [], name)


HARNESS = r'''
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
void run_stub(void);
static jmp_buf out;
static int count, stop;
static uint64_t last;
static uint64_t now(void) { uint64_t v; __asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(v)); return v; }
static uint64_t hz(void) { uint64_t v; __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(v)); return v; }
void fake_smc(uint64_t x0, uint64_t x1, uint64_t x2, uint64_t x3)
{
    uint64_t t = now();
    printf("%llx %llu %llu %llu %llu\n", (unsigned long long)x0, (unsigned long long)x1, (unsigned long long)x2, (unsigned long long)x3,
           (unsigned long long)(count ? (t - last) * 1000 / hz() : 0));
    last = t;
    if (++count == stop) longjmp(out, 1);
    /* x4..x17 mean nothing across the call. */
    __asm__ volatile("mov x4, #-1\n\tmov x5, #-1\n\tmov x6, #-1\n\tmov x7, #-1\n\tmov x8, #-1\n\tmov x9, #-1\n\tmov x10, #-1\n\tmov x11, #-1\n\t"
                     "mov x12, #-1\n\tmov x13, #-1\n\tmov x14, #-1\n\tmov x15, #-1\n\tmov x16, #-1\n\tmov x17, #-1"
                     : : : "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17");
}
int main(int argc, char **argv)
{
    stop = argv[1][0] - '0';
    if (!setjmp(out)) run_stub();
    return 0;
}
'''

STUB_ENTRY = '''
.text
.p2align 2
.globl _run_stub
_run_stub:
\tstp\tx29, x30, [sp, #-16]!
\tb\tLbootstrap_tables_exhausted
'''


@unittest.skipUnless(platform.machine() == 'arm64' and sys.platform == 'darwin', 'needs an arm64 Mac')
class ResetCode(unittest.TestCase):
    """The patch's own instructions, run."""

    def run_stub(self, text, stop, fast):
        macro, stub = stub_lines(text)
        code = '\n'.join(stub).replace('bootstrap_smc', 'bootstrap_smc')
        definition = '\n'.join(macro).replace('smc\t\t#0', 'bl\t\t_fake_smc')
        if fast:    # a millisecond instead of a second, to go through the retries quickly
            code = code.replace('mrs\t\tx4, CNTFRQ_EL0', 'mov\t\tx4, #24000')
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / 'stub.s').write_text(definition + STUB_ENTRY + 'Lbootstrap_tables_exhausted:\n' + code + '\n')
            (directory / 'main.c').write_text(HARNESS)
            subprocess.run(['clang', '-arch', 'arm64', '-O1', '-Wno-everything', str(directory / 'main.c'), str(directory / 'stub.s'),
                            '-o', str(directory / 'run')], check=True, capture_output=True, text=True)
            result = subprocess.run([str(directory / 'run'), str(stop)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [tuple(int(word, 16) if i == 0 else int(word) for i, word in enumerate(line.split())) for line in result.stdout.splitlines()]

    def test_sequence_and_pace(self):
        calls = self.run_stub(PATCH.read_text(), 5, False)
        self.assertEqual([call[:4] for call in calls],
                         [(PSCI_SYSTEM_RESET, 0, 0, 0), (WDOG_SET_TIME, 2000, 4000, 0), (WDOG_CONTROL, 3, 0, 0),
                          (PSCI_SYSTEM_RESET, 0, 0, 0), (PSCI_SYSTEM_RESET, 0, 0, 0)])
        # Nothing between the first three calls, then one retry a second.
        self.assertLess(calls[1][4], 100)
        self.assertLess(calls[2][4], 100)
        self.assertTrue(900 <= calls[3][4] <= 1300, calls[3])
        self.assertTrue(900 <= calls[4][4] <= 1300, calls[4])

    def test_arguments_stay_clean_on_every_retry(self):
        calls = self.run_stub(PATCH.read_text(), 9, True)
        self.assertTrue(all(call[:4] == (PSCI_SYSTEM_RESET, 0, 0, 0) for call in calls[3:]), calls)

    def test_a_mutated_order_is_seen(self):
        text = PATCH.read_text().replace('2000, 4000', '4000, 2000')
        calls = self.run_stub(text, 3, True)
        self.assertNotEqual(calls[1][:3], (WDOG_SET_TIME, 2000, 4000))


TABLES_MAIN = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define PAGES 64
#define GUARD 16
uint64_t build_tables(uint64_t header_pa, uint64_t virt, uint64_t phys, uint64_t size, void *pool);
int main(int argc, char **argv)
{
    /* The first argument is the size of the pool the code was assembled with; the same pool address for every window, so the tables
       of two builds compare byte for byte. */
    unsigned pool_pages = atoi(argv[1]);
    static uint8_t pool[(PAGES + GUARD) * 4096] __attribute__((aligned(4096)));
    for (int i = 2; i < argc; i++) {
        uint64_t size = strtoull(argv[i], NULL, 0);
        memset(pool, 0, sizeof(pool));
        memset(pool + pool_pages * 4096, 0xa5, sizeof(pool) - pool_pages * 4096);
        uint64_t last = build_tables(HEADER_PA, VIRT_BASE, PHYS_BASE, size, pool);
        int spilled = 0;
        for (size_t at = pool_pages * 4096; at < sizeof(pool); at++) spilled |= pool[at] != 0xa5;
        unsigned used = 0;
        for (unsigned page = 0; page < pool_pages; page++) {
            for (unsigned word = 0; word < 512; word++) if (((uint64_t *)(pool + page * 4096))[word]) { used = page + 1; break; }
        }
        /* early_boot_progress_map's test for its page: x1 = x2 + PGBYTES, x2 = the pool's end. */
        uint64_t free_page = last + 4096, end = (uint64_t)pool + pool_pages * 4096;
        int screen = last && !(free_page > end || end - free_page < 4096);
        /* The two roots point into the pool: relative to it, the bytes of two builds compare whatever their load addresses. */
        for (unsigned word = 0; word < 1024; word++) if (((uint64_t *)pool)[word]) ((uint64_t *)pool)[word] -= (uint64_t)pool;
        unsigned long hash = 5381;
        for (size_t at = 0; at < 16 * 4096; at++) hash = hash * 33 + pool[at];
        printf("%llx %d %u %d %d %lx\n", (unsigned long long)size, last != 0, used, screen, spilled, hash);
    }
    return 0;
}
'''


def xnu_tree():
    if XNU:
        return Path(XNU)
    tree = BUILD / '.cache/xnu-work'
    return tree if (tree / 'osfmk/arm64/start.s').is_file() else None


def macro_text(source, name):
    begin = source.index(f'.macro {name}\n')
    return source[begin:source.index('.endmacro\n', begin) + len('.endmacro\n')]


def build_function(source, pool_pages):
    """The assembly of build_tables: start_first_cpu's lines from Lkernelcache_base_found to the second mapping, as they stand."""
    begin = source.index('\tsub\t\tx18, x0, x23\n')
    last = '\tcreate_bootstrap_mapping x14, x15, x5, x3, x2, x9, x10, x11, x12, x13\n'
    body = source[begin:source.index(last, begin) + len(last)]
    defines = ''.join(f'#define {name} {value}\n' for name, value in CONSTANTS.items())
    defines += f'#define BOOTSTRAP_TABLE_BYTES {pool_pages * 4096}\n'
    macros = ''.join(macro_text(source, name) for name in ('create_l1_table_entry', 'create_l2_block_entries', 'create_bootstrap_mapping'))
    return defines + macros + '''
.text
.p2align 2
.globl _build_tables
_build_tables:
\tstp\tx29, x30, [sp, #-96]!
\tstp\tx19, x20, [sp, #16]
\tstp\tx21, x22, [sp, #32]
\tstp\tx23, x24, [sp, #48]
\tstp\tx25, x26, [sp, #64]
\tstp\tx27, x28, [sp, #80]
\tmov\tx22, x1
\tmov\tx23, x2
\tmov\tx24, x3
\tmov\tx25, x4
''' + body + '''
\tmov\tx0, x2
\tb\tLdone
Lbootstrap_tables_exhausted:
\tmov\tx0, #0
Ldone:
\tldp\tx19, x20, [sp, #16]
\tldp\tx21, x22, [sp, #32]
\tldp\tx23, x24, [sp, #48]
\tldp\tx25, x26, [sp, #64]
\tldp\tx27, x28, [sp, #80]
\tldp\tx29, x30, [sp], #96
\tret
'''


@unittest.skipUnless(platform.machine() == 'arm64' and sys.platform == 'darwin', 'needs an arm64 Mac')
class Tables(unittest.TestCase):
    """start.s's own table set-up over a real pool."""

    @classmethod
    def setUpClass(cls):
        cls.tree = xnu_tree()
        if cls.tree is None:
            raise unittest.SkipTest('no XNU tree: --xnu, --inputs, or the build\'s .cache/xnu-work')
        cls.source = (cls.tree / 'osfmk/arm64/start.s').read_text()

    def run_tables(self, pool_pages, sizes, source=None):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / 'tables.s').write_text(build_function(source or self.source, pool_pages))
            (directory / 'main.c').write_text(TABLES_MAIN)
            header = PHYS_BASE + HEADER_OFFSET
            subprocess.run(['clang', '-arch', 'arm64', '-O1', '-Wno-everything', f'-DHEADER_PA={header:#x}ULL', f'-DVIRT_BASE={VIRT_BASE:#x}ULL',
                            f'-DPHYS_BASE={PHYS_BASE:#x}ULL', str(directory / 'main.c'), '-x', 'assembler-with-cpp', str(directory / 'tables.s'),
                            '-o', str(directory / 'run')], check=True, capture_output=True, text=True)
            result = subprocess.run([str(directory / 'run'), str(pool_pages), *[hex(size) for size in sizes]],
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {}
        for line in result.stdout.splitlines():
            size, fits, used, screen, spilled, digest = line.split()
            rows[int(size, 16)] = dict(fits=fits == '1', used=int(used), screen=screen == '1', spilled=spilled == '1', digest=digest)
        return rows

    def test_the_old_pool_is_exactly_6_gib(self):
        """The review's R1: 16 of 16 pages at 6 GiB, the next 2 MiB finds no page for the screen, 8 GiB stops in the table loop."""
        rows = self.run_tables(16, [6 * GIB, 6 * GIB + 0x200000, 8 * GIB])
        self.assertEqual((rows[6 * GIB]['fits'], rows[6 * GIB]['used'], rows[6 * GIB]['screen']), (True, 15, True))
        step = rows[6 * GIB + 0x200000]
        self.assertEqual((step['fits'], step['used'], step['screen']), (True, 16, False))
        self.assertFalse(rows[8 * GIB]['fits'])
        self.assertFalse(any(row['spilled'] for row in rows.values()))

    def test_the_new_pool(self):
        sizes = {6 * GIB: 15, 8 * GIB: 19, 12 * GIB: 27, 13 * GIB: 29}
        rows = self.run_tables(34, list(sizes))
        for size, tables in sizes.items():
            row = rows[size]
            self.assertEqual((row['fits'], row['used'], row['screen'], row['spilled']), (True, tables, True, False), hex(size))

    def test_its_end_still_stops_the_tables(self):
        """The guard scales with the pool: past 34 pages the mapping stops inside it, never behind it."""
        rows = self.run_tables(34, [16 * GIB, 32 * GIB])
        for row in rows.values():
            self.assertEqual((row['fits'], row['spilled']), (False, False))

    def test_6_gib_is_the_same_tables(self):
        """Only the end of the pool moves: for today's window the two builds write the same bytes, and nothing goes into the new pages."""
        old = self.run_tables(16, [6 * GIB])[6 * GIB]
        new = self.run_tables(34, [6 * GIB])[6 * GIB]
        self.assertEqual((new['digest'], new['used']), (old['digest'], old['used']))
        self.assertEqual(new['used'], 15)

    def test_a_loose_bound_is_seen(self):
        """The criterion on the pool's end catches a guard that lets the last page through."""
        source = self.source.replace('\tb.hs Lbootstrap_tables_exhausted\n', '\tb.hi Lbootstrap_tables_exhausted\n')
        self.assertNotEqual(source, self.source)
        rows = self.run_tables(16, [8 * GIB], source)
        self.assertTrue(rows[8 * GIB]['spilled'] or rows[8 * GIB]['fits'])


class OnTheTree(unittest.TestCase):
    def apply_to(self, root, patch):
        return subprocess.run(['git', '-C', str(root), 'apply', str(patch)], capture_output=True, text=True)

    def test_applies_to_a_copy(self):
        if XNU is None:
            self.skipTest('no --xnu tree given')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in FILES:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(Path(XNU) / name, root / name)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            result = self.apply_to(root, PATCH)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_whole_series_and_a_real_assembly(self):
        if INPUTS is None:
            self.skipTest('no --inputs xnu-inputs.json given')
        inputs = json.loads(Path(INPUTS).read_text())
        before = [Path(patch['path']) for patch in inputs['patches'] if Path(patch['path']).parent != PATCHES]
        series = [line.strip() for line in (PATCHES / 'series').read_text().splitlines()]
        patches = before + [PATCHES / name for name in series if name and not name.startswith('#')]
        if PATCH not in patches:
            patches.append(PATCH)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'clone'
            subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', inputs['source'], str(root)], check=True)
            subprocess.run(['git', '-C', str(root), 'checkout', '--quiet', '--detach', inputs['commit']], check=True)
            for patch in patches:
                result = self.apply_to(root, patch)
                self.assertEqual(result.returncode, 0, f'{patch.name}: {result.stderr[-400:]}')
            start = (root / 'osfmk/arm64/start.s').read_text()
            self.assertNotIn('brk #0xe01', start)
            self.assertIn('#define BOOTSTRAP_TABLE_SIZE (ARM_PGBYTES * 34)', (root / 'osfmk/arm/pmap/pmap.h').read_text())
            # The real assembly: the build's own compile record, with assym.s for the new pool next to the copy of start.s.
            objects = Path(INPUTS).parent / 'tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT'
            record = objects / 'start.o.json'
            if not record.is_file():
                self.skipTest(f'no compile record {record}')
            assym = re.sub(r'^(#define BOOTSTRAP_TABLE_BYTES) \d+$', r'\1 139264', (objects / 'assym.s').read_text(), flags=re.M)
            work = Path(temp) / 'asm'
            work.mkdir()
            (work / 'assym.s').write_text(assym)
            shutil.copy(root / 'osfmk/arm64/start.s', work / 'start.s')
            data = json.loads(record.read_text().strip().rstrip(','))
            command, words = [], iter(data['arguments'])
            for word in words:
                if word in ('-MD', '-MP'):
                    continue
                if word in ('-MF', '-MJ', '-MT', '-MQ'):
                    next(words)
                elif word == '-o':
                    next(words)
                    command += ['-o', str(work / 'start.o')]
                elif word == data['file']:
                    command.append(str(work / 'start.s'))
                else:
                    command.append(word)
            command[1:1] = [f'-I{work}', f'-I{root}/osfmk']
            result = subprocess.run(command, cwd=data['directory'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            objdump = shutil.which('llvm-objdump') or '/opt/homebrew/opt/llvm/bin/llvm-objdump'
            text = subprocess.run([objdump, '-d', '--no-show-raw-insn', str(work / 'start.o')], capture_output=True, text=True, check=True).stdout
            self.assertEqual(len(re.findall(r'add\tx\d+, x25, #0x22, lsl #12', text)), 3)
            self.assertEqual(len(re.findall(r'\tsmc\t#0', text)), 4)
            self.assertNotIn('hvc', text)
            self.assertNotIn('brk\t#0xe01', text)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--xnu')
    parser.add_argument('--inputs')
    args, rest = parser.parse_known_args()
    XNU = args.xnu
    INPUTS = args.inputs
    unittest.main(argv=[sys.argv[0]] + rest)
