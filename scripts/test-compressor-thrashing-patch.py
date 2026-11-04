#!/usr/bin/env python3
"""patches/xnu/phone-compressor-thrashing.patch: the two thrashing detectors count pages against values tuned on 16 KiB pages, so on this 4 KiB
kernel an active compressor (kern.vm_compressor = 2, A830_VM_COMPRESSOR) would call four times less data thrashing and jetsam for it. The
patch scales the four thresholds, and only those, by the page size, at compile time.

1. The patch as text: the four initial values, nothing else; a 16 KiB build keeps Apple's numbers.
2. The real functions (compute_swapout_target_age, is_thrashing and vm_phantom_cache_check_pressure, cut from the patched sources) in a host
   harness driven at a given data rate in MB/s, built for 4 and for 16 KiB pages: the rate at which each detector trips must be the same in
   bytes, and without the patch it must not be (the mutation the criterion has to catch). With no compressor active nothing is counted
   and nothing trips, whatever the values, so the default path is untouched.
3. The kernel's own objects, on this arm64 host: WKdm_compress_4k, WKdm_decompress_4k and lz4raw_* from the build, on 60000 pages of six kinds.
   Those are the only codecs mode 2 runs on 4 KiB pages and nothing but one page has gone through them on the phone.
With --xnu <tree> (an XNU checkout with the earlier series applied; only read; default: the build's .cache/xnu-work) the sources come from there.
With --inputs <xnu-inputs.json> (of a kernel build) the whole series as this checkout has it, then this patch when the series does not list it
yet, goes on a fresh clone with git apply as the build does, and the two C files compile with the build's own records.
Run: python3 scripts/test-compressor-thrashing-patch.py [--xnu <tree>] [--inputs <xnu-inputs.json>]"""
import argparse
import json
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = ROOT.parent
PATCHES = ROOT / 'patches/xnu'
PATCH = PATCHES / 'phone-compressor-thrashing.patch'
BUILD = TOP / 'UniXNU/out-gpu/oneplus13t/ipados-17.7.11-21H461/oneplus13t/tree'
OBJECTS = BUILD / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT'
FILES = ['osfmk/vm/vm_compressor.c', 'osfmk/vm/vm_compressor.h', 'osfmk/vm/vm_phantom_cache.c']
XNU = None
INPUTS = None
LLVM = '/opt/homebrew/opt/llvm/bin/'

SCALED = {'compressor_thrashing_threshold_per_10msecs': 50, 'compressor_thrashing_min_per_10msecs': 20,
          'phantom_cache_thrashing_threshold_ssd': 1000, 'phantom_cache_thrashing_threshold': 500}


def added(text):
    return [line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++')]


def removed(text):
    return [line[1:] for line in text.splitlines() if line.startswith('-') and not line.startswith('---')]


def tree():
    if XNU:
        return Path(XNU)
    work = BUILD / '.cache/xnu-work'
    return work if (work / FILES[0]).is_file() else None


def sources(patch_text):
    """{file: text} of the three files with patch_text applied (None: as they are) by git apply, on a copy."""
    base = tree()
    if base is None:
        raise unittest.SkipTest('no XNU tree: --xnu, or the build\'s .cache/xnu-work')
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for name in FILES:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(base / name, root / name)
        if patch_text is not None:
            # The tree may already have it: the series lists this patch once the main line has merged it.
            if 'VM_THRASHING_PAGES' not in (root / FILES[1]).read_text():
                subprocess.run(['git', 'init', '-q', str(root)], check=True)
                (root / 'p.patch').write_text(patch_text)
                subprocess.run(['git', '-C', str(root), 'apply', 'p.patch'], check=True, capture_output=True)
        return {name: (root / name).read_text() for name in FILES}


def function(source, signature):
    """One function's text, from the line of its return type to the closing brace in column 0; signature is the whole line of its name."""
    begin = source.index(f'\n{signature}\n')
    begin = source.rindex('\n', 0, begin) + 1
    return source[begin:source.index('\n}\n', begin) + 3]


HARNESS_HEAD = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int boolean_t;
typedef unsigned long clock_sec_t;
typedef unsigned int clock_nsec_t;
#define TRUE 1
#define FALSE 0
#define XNU_TARGET_OS_OSX 0
#define PHANTOM_CACHE_DEBUG 0
#define KERNEL_DEBUG(...) ((void)0)
#define DBG_FUNC_START 0
#define DBG_FUNC_END 0
#define PAGE ARM_PGBYTES
static uint64_t clock_ms = 1000000000ULL;
static void clock_get_system_nanotime(clock_sec_t *sec, clock_nsec_t *nsec) { *sec = clock_ms / 1000; *nsec = (clock_ms % 1000) * 1000000; }
uint64_t vm_compressor_compute_elapsed_msecs(clock_sec_t end_sec, clock_nsec_t end_nsec, clock_sec_t start_sec, clock_nsec_t start_nsec)
{
    return (end_sec * 1000 + end_nsec / 1000000) - (start_sec * 1000 + start_nsec / 1000000);
}
#define DECOMPRESSION_SAMPLE_MAX_AGE (60 * 30)
static uint32_t age_of_decompressions_during_sample_period[DECOMPRESSION_SAMPLE_MAX_AGE];
static uint32_t overage_decompressions_during_sample_period;
static clock_sec_t start_of_sample_period_sec, start_of_eval_period_sec;
static clock_nsec_t start_of_sample_period_nsec, start_of_eval_period_nsec;
static uint32_t sample_period_compression_count, sample_period_decompression_count;
static uint32_t last_eval_compression_count, last_eval_decompression_count;
static uint32_t swapout_target_age;
static uint32_t VM_PAGE_COMPRESSOR_COUNT = 400000;
static unsigned vm_page_external_count;
#define AVAILABLE_MEMORY 1000000u
'''

# Thirty seconds of a steady load: pages/s from MB/s, one call every 10 ms, as often as the compactor would ask at worst.
HARNESS_MAIN = r'''
static double rate_pages(double mb) { return mb * 1000000.0 / PAGE; }

static int compressor_trips(double compress_mb, double decompress_mb)
{
    double c = rate_pages(compress_mb) / 100, d = rate_pages(decompress_mb) / 100, cc = 0, dd = 0;
    for (int tick = 0; tick < 3000; tick++) {
        clock_ms += 10;
        cc += c; dd += d;
        unsigned nc = (unsigned)cc, nd = (unsigned)dd;
        cc -= nc; dd -= nd;
        sample_period_compression_count += nc;
        sample_period_decompression_count += nd;
        age_of_decompressions_during_sample_period[3] += nd;
        compute_swapout_target_age();
        if (swapout_target_age) { swapout_target_age = 0; return 1; }
    }
    return 0;
}

static int phantom_trips(double added_mb, double found_share, int ssd)
{
    double a = rate_pages(added_mb) / 100, carry = 0;
    pc_history = 0;
    for (int tick = 0; tick < 3000; tick++) {
        clock_ms += 10;
        carry += a;
        unsigned n = (unsigned)carry;
        carry -= n;
        if (ssd) { sample_period_ghost_added_count_ssd += n; sample_period_ghost_found_count_ssd += (unsigned)(n * found_share); }
        else { sample_period_ghost_added_count += n; sample_period_ghost_found_count += (unsigned)(n * found_share); }
        if (vm_phantom_cache_check_pressure()) return 1;
    }
    return 0;
}

int main(void)
{
    static const double rates[] = {0, 5, 10, 15, 19, 21, 30, 32, 33, 40, 60, 65, 66, 75, 81, 82, 85, 100, 160, 320};
    start_of_sample_period_sec = start_of_eval_period_sec = clock_ms / 1000;
    pc_start_of_eval_period_sec = clock_ms / 1000;
    printf("values %u %u %u %u\n", compressor_thrashing_threshold_per_10msecs, compressor_thrashing_min_per_10msecs,
           phantom_cache_thrashing_threshold_ssd, phantom_cache_thrashing_threshold);
    for (unsigned i = 0; i < sizeof(rates) / sizeof(rates[0]); i++) {
        printf("compressor %g %d\n", rates[i], compressor_trips(320, rates[i]));
        printf("min %g %d\n", rates[i], compressor_trips(rates[i], 320));
        printf("ssd %g %d\n", rates[i], phantom_trips(rates[i], 1.0, 1));
        printf("disk %g %d\n", rates[i], phantom_trips(rates[i], 1.0, 0));
        printf("sparse %g %d\n", rates[i], phantom_trips(rates[i], 0.25, 1));
    }
    return 0;
}
'''


def harness(files):
    compressor, phantom, header = files[FILES[0]], files[FILES[2]], files[FILES[1]]
    begin = compressor.index('uint32_t compressor_eval_period_in_msecs')
    end = compressor.index('int             compaction_swapper_init_now')
    detector = compressor[begin:end]
    macro = re.search(r'^#define VM_THRASHING_PAGES.*$', header, re.M)
    begin = phantom.index('uint32_t phantom_cache_eval_period_in_msecs')
    end = phantom.index('uint32_t        vm_phantom_object_id')
    variables = phantom[begin:end]
    return (HARNESS_HEAD + (macro.group(0) + '\n' if macro else '') + detector + variables + function(phantom, 'is_thrashing(uint32_t added, uint32_t found, uint32_t threshold)')
            + function(phantom, 'vm_phantom_cache_check_pressure()') + HARNESS_MAIN)


def run_harness(files, page):
    """{detector: the lowest rate in MB/s that trips}, and the four values, for a build with this page size."""
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        (directory / 'main.c').write_text(harness(files))
        subprocess.run(['clang', '-O1', '-Wno-everything', f'-DARM_PGBYTES={page}', str(directory / 'main.c'), '-o', str(directory / 'run')],
                       check=True, capture_output=True, text=True)
        output = subprocess.run([str(directory / 'run')], capture_output=True, text=True, check=True, timeout=120).stdout
    lowest, values = {}, None
    for line in output.splitlines():
        words = line.split()
        if words[0] == 'values':
            values = [int(word) for word in words[1:]]
        elif words[2] == '1':
            lowest.setdefault(words[0], float(words[1]))
    return values, lowest


class PatchText(unittest.TestCase):
    def setUp(self):
        self.text = PATCH.read_text()

    def test_touches_only_the_four_values(self):
        self.assertEqual(re.findall(r'^\+\+\+ b/(\S+)', self.text, re.M), FILES)
        self.assertEqual(sorted(line.strip() for line in removed(self.text)),
                         sorted(f'uint32_t {name} = {value};' for name, value in SCALED.items()))
        for name, value in SCALED.items():
            self.assertIn(f'uint32_t {name} = VM_THRASHING_PAGES({value});', added(self.text))

    def test_scales_with_the_page_size_at_compile_time(self):
        self.assertIn('#define VM_THRASHING_PAGES(pages_16k)           ((pages_16k) * (16384 / ARM_PGBYTES))', added(self.text))
        # PAGE_SIZE is a variable in a kernel without __ARM_16K_PG__ (PAGE_SHIFT_CONST): it cannot initialize a global.
        self.assertFalse(any('PAGE_SIZE' in line for line in added(self.text)))

    def test_macos_values_stay(self):
        self.assertIn(' uint32_t phantom_cache_thrashing_threshold = 50;', self.text)


class Detectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patched = sources(PATCH.read_text())
        pristine = dict(cls.patched)
        # The mutation: the sources without the patch, built for the same page sizes.
        pristine[FILES[0]] = re.sub(r'VM_THRASHING_PAGES\((\d+)\)', r'\1', pristine[FILES[0]])
        pristine[FILES[2]] = re.sub(r'VM_THRASHING_PAGES\((\d+)\)', r'\1', pristine[FILES[2]])
        cls.pristine = pristine
        cls.result = {page: run_harness(cls.patched, page) for page in (4096, 16384)}

    def test_values(self):
        self.assertEqual(self.result[4096][0], [200, 80, 4000, 2000])
        self.assertEqual(self.result[16384][0], [50, 20, 1000, 500])

    def test_the_same_rate_in_bytes_as_a_16k_device(self):
        four, sixteen = self.result[4096][1], self.result[16384][1]
        self.assertEqual(set(four), {'compressor', 'min', 'ssd', 'disk'})      # 'sparse' never trips: found stays below added / 2
        self.assertEqual(four, sixteen)

    def test_the_rates_are_those_of_the_comment(self):
        lowest = self.result[4096][1]
        # The steps of the grid above the exact rate. The phantom cache looks at a period before it ends (here at 240 of its 250 ms).
        self.assertEqual(lowest['compressor'], 82)      # 50 pages of 16 KiB per 10 ms: 81.9 MB/s, 78 MiB/s
        self.assertEqual(lowest['min'], 33)             # 20 pages of 16 KiB per 10 ms: 32.8 MB/s
        self.assertEqual(lowest['ssd'], 75)             # 1000 pages of 16 KiB per 250 ms: 65.5 MB/s, 62 MiB/s
        self.assertEqual(lowest['disk'], 40)            # 500 of them: 32.8 MB/s

    def test_without_the_patch_4k_trips_four_times_lower(self):
        """The mutation: thresholds as Apple's, on 4 KiB pages. The criterion above has to see this."""
        values, lowest = run_harness(self.pristine, 4096)
        self.assertEqual(values, [50, 20, 1000, 500])
        self.assertNotEqual(lowest, self.result[16384][1])
        self.assertEqual(lowest['compressor'], 21)
        self.assertEqual(lowest['ssd'], 19)

    def test_default_path_is_untouched(self):
        """Mode 8: the phantom cache is not set up, so nothing is ever counted; no compressions, no decompressions: nothing trips."""
        phantom = self.patched[FILES[2]]
        init = function(phantom, 'vm_phantom_cache_init(void)')
        self.assertLess(init.index('if (!VM_CONFIG_COMPRESSOR_IS_ACTIVE) {'), init.index('num_entries ='))
        ghost = function(phantom, 'vm_phantom_cache_add_ghost(vm_page_t m)')
        self.assertLess(ghost.index('if (vm_phantom_cache_num_entries == 0) {'), ghost.index('OSAddAtomic'))
        self.assertIn('phantom_cache_thrashing_threshold', function(phantom, 'vm_phantom_cache_check_pressure()'))


@unittest.skipUnless(platform.machine() == 'arm64' and sys.platform == 'darwin', 'needs an arm64 Mac')
class KernelCodecs(unittest.TestCase):
    MAIN = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define PG 4096
typedef unsigned int WK_word;
void WKdm_decompress_4k(const WK_word *, WK_word *, WK_word *, unsigned int);
int WKdm_compress_4k(const WK_word *, WK_word *, WK_word *, unsigned int);
size_t lz4raw_encode_buffer(uint8_t *, size_t, const uint8_t *, size_t, void *);
size_t lz4raw_decode_buffer(uint8_t *, size_t, const uint8_t *, size_t, void *);
static uint32_t rng = 12345;
static uint32_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }
static void fill(uint32_t *p, int kind)
{
    for (int i = 0; i < PG / 4; i++) {
        switch (kind) {
        case 0: p[i] = 0; break;                                    /* the single value page: return 0, no data */
        case 1: p[i] = rnd(); break;                                /* incompressible: return -1 */
        case 2: p[i] = 0xfffffff0u ^ (i & 7); break;                /* the dictionary's hits */
        case 3: p[i] = i & 1 ? 0x10000000 + (rnd() & 0xff) : 0; break;
        case 4: p[i] = (rnd() & 3) ? 0x12345678 : rnd(); break;
        default: p[i] = 0x01010101u * (i % 251) ^ (rnd() % 16); break;
        }
    }
    if (kind == 5 && (rnd() & 1)) { memset(p, 0, PG); p[rnd() % (PG / 4)] = rnd(); }     /* the mostly zero page (MZV) */
}
int main(void)
{
    static uint32_t src[PG / 4] __attribute__((aligned(4096))), out[PG / 4] __attribute__((aligned(4096)));
    static uint8_t cdst[PG * 2] __attribute__((aligned(64))), scratch[PG * 4] __attribute__((aligned(64)));
    unsigned long wk = 0, single = 0, refused = 0, lz = 0, lzfail = 0;
    for (int round = 0; round < 60000; round++) {
        fill(src, round % 6);
        memset(out, 0xa5, sizeof(out));
        int limit = (round & 1) ? PG - 512 : PG;
        int c = WKdm_compress_4k(src, (WK_word *)cdst, (WK_word *)scratch, limit);
        if (c == -1) refused++;
        else if (c == 0) { for (int i = 1; i < PG / 4; i++) assert(src[i] == src[0]); single++; }
        else {
            assert(c > 0 && c <= limit);
            WKdm_decompress_4k((WK_word *)cdst, out, (WK_word *)scratch, c);
            if (memcmp(src, out, PG)) { printf("WK mismatch round %d\n", round); return 1; }
            wk++;
        }
        size_t l = lz4raw_encode_buffer(cdst, PG * 2, (uint8_t *)src, PG, scratch);
        if (!l) { lzfail++; continue; }
        memset(out, 0x5a, sizeof(out));
        if (lz4raw_decode_buffer((uint8_t *)out, PG, cdst, l, scratch) != PG || memcmp(src, out, PG)) { printf("LZ4 mismatch round %d\n", round); return 1; }
        lz++;
    }
    printf("%lu %lu %lu %lu %lu\n", wk, single, refused, lz, lzfail);
    return 0;
}
'''

    @staticmethod
    def as_macos(source, target):
        """A copy of an iOS object the host linker takes: only the platform in its load commands changes."""
        data = bytearray(source.read_bytes())
        offset, changed = 32, False
        for _ in range(struct.unpack_from('<I', data, 16)[0]):
            command, size = struct.unpack_from('<II', data, offset)
            if command == 0x32:         # LC_BUILD_VERSION
                struct.pack_into('<I', data, offset + 8, 1)
                changed = True
            elif command == 0x25:       # LC_VERSION_MIN_IPHONEOS
                struct.pack_into('<I', data, offset, 0x24)
                changed = True
            offset += size
        assert changed, source
        target.write_bytes(data)

    def test_round_trip(self):
        names = ['WKdmCompress_4k', 'WKdmDecompress_4k', 'WKdmData', 'lz4', 'lz4_encode_arm64', 'lz4_decode_arm64']
        if not all((OBJECTS / f'{name}.o').is_file() for name in names):
            self.skipTest(f'no kernel objects in {OBJECTS}')
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in names:
                self.as_macos(OBJECTS / f'{name}.o', directory / f'{name}.o')
            (directory / 'main.c').write_text(self.MAIN)
            subprocess.run(['clang', '-arch', 'arm64', '-O1', '-Wno-everything', str(directory / 'main.c'),
                            *[str(directory / f'{name}.o') for name in names], '-o', str(directory / 'run')],
                           check=True, capture_output=True, text=True)
            result = subprocess.run([str(directory / 'run')], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        wk, single, refused, lz, lzfail = [int(word) for word in result.stdout.split()]
        self.assertEqual(wk + single + refused, 60000)
        self.assertGreater(wk, 20000)
        self.assertEqual(single, 10000)
        self.assertGreater(refused, 5000)
        self.assertEqual((lz, lzfail), (60000, 0))


class OnTheTree(unittest.TestCase):
    def test_whole_series_and_real_compiles(self):
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
                result = subprocess.run(['git', '-C', str(root), 'apply', str(patch)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, f'{patch.name}: {result.stderr[-400:]}')
            objects = Path(INPUTS).parent / 'tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT'
            for name, symbols in (('vm_phantom_cache', {'_phantom_cache_thrashing_threshold': 2000, '_phantom_cache_thrashing_threshold_ssd': 4000}),
                                  ('vm_compressor', {'_compressor_thrashing_threshold_per_10msecs': 200,
                                                     '_compressor_thrashing_min_per_10msecs': 80})):
                record = objects / f'{name}.o.json'
                if not record.is_file():
                    self.skipTest(f'no compile record {record}')
                data = json.loads(record.read_text().strip().rstrip(','))
                output = Path(temp) / f'{name}.o'
                command, words = [], iter(data['arguments'])
                for word in words:
                    if word in ('-MD', '-MP'):
                        continue
                    if word in ('-MF', '-MJ', '-MT', '-MQ'):
                        next(words)
                    elif word == '-o':
                        next(words)
                        command += ['-o', str(output)]
                    elif word == data['file']:
                        command.append(str(root / 'osfmk/vm' / f'{name}.c'))
                    else:
                        command.append(word)
                command[1:1] = [f'-I{root}/osfmk']
                result = subprocess.run(command, cwd=data['directory'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr[-2000:])
                self.assertEqual(read_words(output, symbols), symbols)


def read_words(path, symbols):
    names = subprocess.run([LLVM + 'llvm-nm', '-n', str(path)], capture_output=True, text=True, check=True).stdout
    address = {line.split()[2]: int(line.split()[0], 16) for line in names.splitlines() if len(line.split()) == 3}
    dump = subprocess.run([LLVM + 'llvm-objdump', '-s', '--section=__data', str(path)], capture_output=True, text=True, check=True).stdout
    memory = {}
    for line in dump.splitlines():
        match = re.match(r'\s*([0-9a-f]+) ((?:[0-9a-f]{2,8} )+)', line)
        if match:
            hexes = match.group(2).replace(' ', '')
            for i in range(0, len(hexes), 2):
                memory[int(match.group(1), 16) + i // 2] = int(hexes[i:i + 2], 16)
    return {name: int.from_bytes(bytes(memory.get(address[name] + i, 0) for i in range(4)), 'little') for name in symbols}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--xnu')
    parser.add_argument('--inputs')
    args, rest = parser.parse_known_args()
    XNU = args.xnu
    INPUTS = args.inputs
    unittest.main(argv=[sys.argv[0]] + rest)
