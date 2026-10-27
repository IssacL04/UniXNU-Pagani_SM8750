#!/usr/bin/env python3
"""Check the migrated profile and the ADT handoff against the retained format-1 contract."""
import argparse
import os
import re
import runpy
import struct
import subprocess
import tempfile
import tomllib
from pathlib import Path
from unittest import mock

from unixnu import cli, components, devicetree, feeds, kernel, patches
from unixnu.config import Context, ROOT

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--device', type=Path, default=Path(__file__).resolve().parents[1])
args, overrides = parser.parse_known_args()
ctx = Context(cli.parser().parse_args(['status', '-D', str(args.device), *overrides]))
modules = feeds.resolve(ctx)
assert ctx.schema_version == 2
assert list(ctx.profile_roots) == ['arch', 'soc', 'os', 'device']
assert ctx.work.parts[-3:] == ('oneplus13t', 'ipados-17.7.11-21H461', 'oneplus13t')
assert len(ctx.component_specs) == 18
for spec in ctx.component_specs:
    module = modules[spec['kind'], spec['id']]
    assert module.path is not None
    for source in spec.get('source_files', []):
        assert (module.path / source).is_file(), (spec['id'], source)
    revision = subprocess.check_output(['git', '-C', str(module.path), 'rev-parse', 'HEAD'], text=True).strip()
    assert revision == spec['revision'], (spec['id'], revision, spec['revision'])
assert all(m.path and m.path.is_dir() for m in modules.values() if m.kind != 'refer')
assert len(patches.plan(ctx, modules)) == len(set(patches.plan(ctx, modules)))
patches.prepare(ctx, modules)
plan = kernel.archive_plan(ctx)
assert any(kind == 'component' and entry['id'] == 'NativeUfs' for kind, entry in plan)
assert ctx.config['XNU_SOURCE_MOCKFS'] is False
assert ctx.board['userdata']['partition'] == 'unixnu'
assert ctx.board['bootimg']['embed_payload'] is True
assert ctx.board['payload']['text_fixups'] == [
    'dyld_shared_cache_arm64.15,421e8bc,28ad1bb0008544f9,c0035fd6008544f9',
    'dyld_shared_cache_arm64.13,1b05bec,44008052,24008052',
    'dyld_shared_cache_arm64.13,1b05b08,44008052,24008052',
    'BTAudioHALPlugin,38bec,ffc300d1f44f01a9,000080d2c0035fd6']

with mock.patch.object(ctx, 'need_config', return_value={'XNU_BUILD_ARCHIVES': True}), \
        mock.patch.object(kernel, 'archive_plan', return_value=[('script', 'build-software-aes-bindings.py --help')]):
    kernel.build_archives(ctx, dict(os.environ))


def decode(data):
    nodes = {}
    def parse(at, parent):
        props, children = struct.unpack_from('<II', data, at); at += 8
        values = {}
        for _ in range(props):
            name, size = struct.unpack_from('<32sI', data, at); at += 36
            key = name.rstrip(b'\0').decode()
            assert key not in values and at + size <= len(data)
            values[key] = data[at:at+size]; at += (size+3)&~3
        path = parent + '/' + values['name'].rstrip(b'\0').decode(); nodes[path] = values
        for _ in range(children): at = parse(at, path)
        return at
    assert parse(0, '') == len(data)
    return nodes

old = runpy.run_path(str(ctx.device/'scripts/fixtures/make-oneplus13t-adt-v1.py'))
with tempfile.TemporaryDirectory() as directory:
    dtb = Path(directory)/'hardware.dtb'
    subprocess.run(['dtc','-I','dts','-O','dtb','-i',str(ctx.soc.path/'dts'),'-o',str(dtb),str(ctx.device/'dts/oneplus13t.dts')], check=True)
    expected = decode(old['make_tree'](0x100000000, bytes(64), '04769D26-2CA0-4825-B443-E2E5F88300F2', True, True, True, 0x123456789abcdef))
    actual = decode(devicetree.generate(dtb, ctx.board, unique_chip_id='123456789abcdef', data=True, trust=True))
    for path, properties in expected.items():
        for key, value in properties.items():
            if path == '/device-tree' and key == 'compatible':
                assert actual[path][key] == b'J120AP\0' + value
                continue
            if path == '/device-tree/arm-io' and key == 'ranges':
                assert actual[path][key] == struct.pack('<QQQ', 0, 0x16000000, 0x1000000)
                continue
            if path == '/device-tree/chosen' and key in ('random-seed','dram-base','dram-size'):
                continue
            assert actual[path][key] == value, (path, key)
    affinities = [0, 0x100, 0x200, 0x300, 0x400, 0x500, 0x10000, 0x10100]
    for i, affinity in enumerate(affinities):
        cpu = actual[f'/device-tree/cpus/cpu{i}']
        assert struct.unpack('<I', cpu['reg']) == (affinity,)
        assert cpu['state'] == (b'running\0' if i == 0 else b'waiting\0')
        assert struct.unpack('<I', cpu['timebase-frequency']) == (19200000,)
    assert '/device-tree/cpus/cpu8' not in actual
    assert actual['/device-tree/psci']['method'] == b'smc\0'
    assert 'cpus=8' in ctx.board['payload']['kernel_args']
    assert 'sheng-smp=1' in ctx.board['payload']['kernel_args']
    assert 'pagani-peripheral-status=1' not in ctx.board['payload']['kernel_args']
    chosen = actual['/device-tree/chosen']
    assert len(chosen['random-seed']) == 64
    assert struct.unpack('<Q', chosen['dram-base']) == (0x980000000,)
    assert struct.unpack('<Q', chosen['dram-size']) == (0x180000000,)
    assert struct.unpack('<Q', chosen['darwinboot-memory-size']) == (0x100000000,)
    assert actual['/device-tree/product']['product-id'] == bytes.fromhex('e9fefef6e6f9d12a5ba1a2551866cbbd749f0ec3')
    assert actual['/device-tree/product/audio']['wireless-splitter'] == struct.pack('<I', 1)

# Execute the selected XNU lookup and topology macros, including both Aff2 Prime CPUs.
xnu = ctx.tree / '.cache/xnu-work'
machine = (xnu / 'osfmk/arm64/machine_routines.c').read_text()
macros = '\n'.join(re.findall(r'^#define MPIDR_(?:CPU|CLUSTER)_ID.*$', machine, re.M))
lookup = re.search(r'int\nml_get_cpu_number\(uint32_t phys_id\)\n\{.*?\n\}', machine, re.S).group()
start = (xnu / 'osfmk/arm64/start.s').read_text()
reset = re.search(r'and\s+x0, x15, #(0x[0-9A-Fa-f]+)', start).group(1)
assert len({affinity & int(reset, 0) for affinity in affinities}) == 8
assert 'cbnz x21, Lsecondary_progress_vectors' in start
secondary = start.split('Lsecondary_progress_vectors:', 1)[1].split('Lprogress_vectors_ready:', 1)[0]
assert 'EXT(ExceptionVectorsBase)' in secondary and 'msr VBAR_EL1, x0' in secondary
config = (xnu / 'pexpert/pexpert/arm64/board_config.h').read_text().split('#include <pexpert/arm64/BCM2837.h>', 1)[1].split('#endif', 1)[0]
assert re.search(r'#define MAX_CPUS\s+8\b', config)
assert re.search(r'#define MAX_CPU_CLUSTERS\s+2\b', config)
assert '#define HAS_CLUSTER 1' in (xnu / 'pexpert/pexpert/arm64/BCM2837.h').read_text()
source = r'''
#include <assert.h>
#include <stdint.h>
#define MPIDR_AFF0_MASK 0xff
#define MPIDR_AFF1_MASK 0xff00
#define MPIDR_AFF2_MASK 0xff0000
#define MPIDR_AFF0_SHIFT 0
#define MPIDR_AFF1_SHIFT 8
#define MPIDR_AFF2_SHIFT 16
static struct { unsigned num_cpus; struct { uint32_t phys_id; } cpus[8]; } topology_info =
    {8, {{0}, {0x100}, {0x200}, {0x300}, {0x400}, {0x500}, {0x10000}, {0x10100}}};
''' + macros + '\n' + lookup + r'''
int main(void) {
    for (unsigned i=0; i<8; i++) {
        uint32_t raw = topology_info.cpus[i].phys_id | 0x81000000;
        assert(ml_get_cpu_number(raw) == (int)i);
        assert(MPIDR_CPU_ID(raw) == (i < 6 ? i : i-6));
        assert(MPIDR_CLUSTER_ID(raw) == (i < 6 ? 0 : 1));
    }
    assert(ml_get_cpu_number(0x600) == -1);
    assert(ml_get_cpu_number(0x20000) == -1);
}
'''
with tempfile.TemporaryDirectory() as directory:
    binary = Path(directory) / 'topology'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-x', 'c', '-', '-o', str(binary)],
                   input=source, text=True, check=True)
    subprocess.run([str(binary)], check=True)
    reset_block = re.search(r'#if HAS_CLUSTER\n.*?\n#endif', start, re.S).group()
    resume_block = re.search(r'#if HAS_CLUSTER && !NO_CPU_OVRD\n.*?\n#endif', start, re.S).group()
    asm = (f'#define ASSEMBLER 1\n#include "{xnu}/pexpert/pexpert/arm64/BCM2837.h"\n'
           '.text\n.globl _smp_reset\n_smp_reset:\n' + reset_block + '\n' + resume_block + '\nret\n')
    subprocess.run([os.environ.get('CLANG', 'clang'), '--target=arm64-apple-darwin',
                    '-x', 'assembler-with-cpp', '-c', '-', '-o', str(Path(directory)/'smp-reset.o')],
                   input=asm, text=True, check=True)

# Exercise the selected Clutch/pset contract with a second hardware cluster.
clutch = (xnu / 'osfmk/kern/sched_clutch.c').read_text()
dispatch = clutch.split('const struct sched_dispatch_table sched_clutch_dispatch = {', 1)[1].split('};', 1)[0]
multiple = re.search(r'\.multiple_psets_enabled\s*=\s*(TRUE|FALSE)', dispatch).group(1)
processor = (xnu / 'osfmk/kern/processor.c').read_text()
create = re.search(r'processor_set_t\npset_create\(.*?\n\}', processor, re.S).group()
sched = (xnu / 'osfmk/kern/sched_prim.c').read_text()
enabled = re.search(r'bool\nsched_steal_thread_enabled\(.*?\n\}', sched, re.S).group()
steal = re.search(r'static thread_t\nsched_clutch_steal_thread\([^;]*?\)\n\{.*?\n\}', clutch, re.S).group()
source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#define TRUE 1
#define FALSE 0
#define __unused __attribute__((unused))
typedef int pset_cluster_type_t;
typedef void *thread_t;
#define THREAD_NULL NULL
typedef struct processor_set *processor_set_t;
typedef struct node *pset_node_t;
struct node { processor_set_t psets; uint64_t pset_map; } node;
struct processor_set {
    pset_cluster_type_t pset_cluster_type;
    uint32_t pset_cluster_id;
    int pset_id;
    processor_set_t pset_list;
    pset_node_t node;
    unsigned owner;
} pset0 = {.node = &node}, spare;
struct { processor_set_t pset; } boot = {&pset0}, *master_processor = &boot;
#define processor_pset(p) ((p)->pset)
#define PROCESSOR_SET_NULL NULL
static struct { bool multiple_psets_enabled; } policy = {SELECTED_MULTIPLE};
#define SCHED(f) (policy.f)
static unsigned allocations;
#define zalloc_permanent_type(type) (allocations++, &spare)
static int pset_node_lock;
static void lck_spin_lock(int *lock) { (void)lock; }
static void lck_spin_unlock(int *lock) { (void)lock; }
static void pset_init(processor_set_t pset, pset_node_t target) {
    pset->node = target; target->pset_map |= 1ULL << pset->pset_id;
}
static unsigned bit_count(uint64_t bits) { return __builtin_popcountll(bits); }
static void pset_lock(processor_set_t pset) {
    assert(pset->owner != 0xf1d34); pset->owner = 0xf1d34;
}
static void pset_unlock(processor_set_t pset) {
    assert(pset->owner == 0xf1d34); pset->owner = 0;
}
''' + create + '\n' + enabled + '\n' + steal + r'''
int main(void) {
    node.psets = &pset0; node.pset_map = 1;
    processor_set_t prime = pset_create(&node, 0, 1, 1);
    pset_lock(&pset0);
    if (sched_steal_thread_enabled(&pset0)) {
        assert(sched_clutch_steal_thread(&pset0) == THREAD_NULL);
        pset_lock(&pset0); /* thread_select reacquires after steal returns. */
    }
    pset_unlock(&pset0);
    assert(prime == &pset0 && allocations == 0 && node.pset_map == 1);
}
'''
with tempfile.TemporaryDirectory() as directory:
    binary = Path(directory) / 'clutch-pset'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    f'-DSELECTED_MULTIPLE={multiple}', '-x', 'c', '-', '-o', str(binary)],
                   input=source, text=True, check=True)
    subprocess.run([str(binary)], check=True)

validate = runpy.run_path(str(ROOT / 'scripts/porting-record.py'))['validate']
foreign = tomllib.loads((ctx.device / 'porting.toml').read_text())
for area in foreign['area']:
    area['components'] = ['NativeMobileDisplay'] if area['id'] == 'display' else []
board = dict(ctx.board, components={'include': ['NativeMobileDisplay']})
validate(foreign, board, 'foreign snapshot', allow_custom_components=True)
try:
    validate(foreign, board, 'local selection')
except ValueError as error:
    assert 'components without an area' in str(error)
else:
    raise AssertionError('Local records must cover the selected component dependencies')
print('PASS: four profiles, 18 components, ordered archives, root policy and format-2 ADT contract')
