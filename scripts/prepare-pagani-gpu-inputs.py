#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Generate package/PaganiGpuInputs.h, the device-tree constants of the A830 board (ARCHITECTURE 3.2, 3.5, 7.3).

(A) Windows, interrupts, stream IDs, the SMMU interrupts, the speed-bin fuse cell, the LLCC windows and the reserved regions
    come from the hardware DTS (dts/oneplus13t.dts with the SoC dtsi), the single source of the board description.
(B) Values the UniXNU DTS does not carry because they are board policy of the stock kernel (the GPU power-level bins, the
    bus and GMU tables, the apps DRV-2, AOSS QMP, IPCC and TSENS windows, the SCM wait-queue interrupt, the SoC ids, ACTLR
    and UBWC) come from the PKX110 runtime DTB. A runtime DTB differs from boot to boot, so the generator does not pin the
    file for these: it normalises the GPU-relevant values into JSON and pins that JSON's SHA-256 in
    scripts/data/sm8750-gpu-inputs.json ("runtime_dt"), which also stores the values. The header is therefore generated
    and --check'ed without the runtime DTB; with --live-dtb (the pinned capture) the generator extracts (B) again and
    requires it to equal the recorded values, and requires every (A) value the runtime DTB also has to agree with the DTS.
    --record (with --live-dtb) rewrites the recorded (B) values and their pin.

The output is committed; --check regenerates and compares.
"""
import argparse
import hashlib
import json
import struct
import subprocess
import tempfile
from pathlib import Path

DEVICE = Path(__file__).resolve().parents[1]
OUTPUT = DEVICE / 'package/PaganiGpuInputs.h'
PINS = DEVICE / 'scripts/data/sm8750-gpu-inputs.json'
SOC_ID = 618        # SMEM socinfo id measured on PKX110 (one of the runtime DT qcom,msm-id SoCs)
MAX_LEVELS = 16     # Adreno830LevelMax / KGSL_MAX_PWRLEVELS
MAX_SKUS = 4        # Adreno830BinSkus
BINS = 6            # Adreno830BinCount
LLCC_NAMES = ['llcc0_base', 'llcc1_base', 'llcc2_base', 'llcc3_base', 'llcc_broadcast_or_base', 'llcc_broadcast_and_base']


def fail(message):
    raise SystemExit('prepare-pagani-gpu-inputs: ' + message)


class Node:
    def __init__(self, name, parent):
        self.name, self.parent, self.props, self.children = name, parent, {}, {}

    def path(self):
        return '/' if self.parent is None else (self.parent.path().rstrip('/') + '/' + self.name)

    def cells(self, key, default):
        raw = self.props.get(key)
        return struct.unpack('>I', raw)[0] if raw else default

    def u32s(self, key):
        raw = self.props.get(key)
        if raw is None:
            fail(f'{self.path()}: no {key}')
        return list(struct.unpack(f'>{len(raw) // 4}I', raw))

    def u32(self, key, default=None):
        if key not in self.props:
            if default is None:
                fail(f'{self.path()}: no {key}')
            return default
        values = self.u32s(key)
        if len(values) != 1:
            fail(f'{self.path()}: {key} is not one cell')
        return values[0]

    def strings(self, key):
        raw = self.props.get(key, b'')
        return [s.decode() for s in raw.rstrip(b'\0').split(b'\0')] if raw else []

    def reg(self):
        """[(address, size)] in the parent's cell format."""
        acells, scells = self.parent.cells('#address-cells', 2), self.parent.cells('#size-cells', 1)
        values, step, result = self.u32s('reg'), acells + scells, []
        if len(values) % step:
            fail(f'{self.path()}: reg is not a multiple of {step} cells')
        for i in range(0, len(values), step):
            number = lambda cells: sum(v << (32 * (len(cells) - 1 - k)) for k, v in enumerate(cells))
            result.append((number(values[i:i + acells]), number(values[i + acells:i + step])))
        return result

    def named_reg(self, name):
        names = self.strings('reg-names')
        if name not in names:
            fail(f'{self.path()}: no reg named {name}')
        return self.reg()[names.index(name)]

    def interrupts(self):
        """[(INTID, flags)] of GIC SPI triplets."""
        values = self.u32s('interrupts')
        if len(values) % 3:
            fail(f'{self.path()}: interrupts are not GIC triplets')
        result = []
        for i in range(0, len(values), 3):
            if values[i] != 0:
                fail(f'{self.path()}: interrupt {i // 3} is not an SPI')
            result.append((values[i + 1] + 32, values[i + 2]))
        return result

    def named_interrupt(self, name):
        names = self.strings('interrupt-names')
        if name not in names:
            fail(f'{self.path()}: no interrupt named {name}')
        return self.interrupts()[names.index(name)][0]

    def walk(self):
        yield self
        for child in self.children.values():
            yield from child.walk()


def read_fdt(data):
    magic, total, structure, strings = struct.unpack_from('>4I', data)
    if magic != 0xd00dfeed or total > len(data):
        fail('not a flattened device tree')
    at, root, node = structure, None, None
    while True:
        token = struct.unpack_from('>I', data, at)[0]
        at += 4
        if token == 1:
            end = data.index(b'\0', at)
            name = data[at:end].decode()
            at = (end + 4) & ~3
            child = Node(name, node)
            if node is None:
                root = child
            else:
                node.children[name] = child
            node = child
        elif token == 2:
            node = node.parent
        elif token == 3:
            size, offset = struct.unpack_from('>II', data, at)
            at += 8
            key = data[strings + offset:data.index(b'\0', strings + offset)].decode()
            node.props[key] = data[at:at + size]
            at = (at + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            return root
        else:
            fail(f'bad FDT token {token}')


def find(root, path):
    node = root
    for part in path.strip('/').split('/'):
        if part not in node.children:
            fail(f'node {path} not found (at {node.path()})')
        node = node.children[part]
    return node


def by_phandle(root, handle):
    for node in root.walk():
        if node.props.get('phandle') == struct.pack('>I', handle):
            return node
    fail(f'phandle {handle:#x} not found')


def compile_dts(soc):
    source = DEVICE / 'dts/oneplus13t.dts'
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / 'hardware.dtb'
        subprocess.run(['dtc', '-q', '-I', 'dts', '-O', 'dtb', '-i', str(soc / 'dts'), '-o', str(output), str(source)], check=True)
        return read_fdt(output.read_bytes())


def sids(root, node, smmu_handle):
    """The stream IDs of an iommus property of <&smmu SID MASK> specifiers (mask 0)."""
    specifier = node.u32s('iommus')
    if len(specifier) % 3:
        fail(f'{node.path()}: iommus is not <&smmu SID MASK> specifiers')
    result = []
    for i in range(0, len(specifier), 3):
        if specifier[i] != smmu_handle or specifier[i + 2] != 0:
            fail(f'{node.path()}: iommus entry {i // 3} is not <&gpu_smmu SID 0>')
        result.append(specifier[i + 1])
    return result


def hardware_values(hardware):
    """(A): from the DTS. Name -> (value, note)."""
    values = {}

    def put(name, value, note):
        values[name] = (value, note)

    gpu, gmu = find(hardware, '/soc/gpu@3d00000'), find(hardware, '/soc/gmu@3d37000')
    smmu, qfprom = find(hardware, '/soc/iommu@3da0000'), find(hardware, '/soc/efuse@221c8000')
    llcc = find(hardware, '/soc/cache-controller@24800000')
    for node in (gpu, gmu, smmu, qfprom, llcc, find(hardware, '/soc/clock-controller@3d90000')):
        if node.strings('status') != ['okay']:
            fail(f'{node.path()} is not enabled in dts/oneplus13t.dts')
    for key, name in (('GPU', 'kgsl_3d0_reg_memory'), ('RSCC', 'rscc'), ('CX_DBGC', 'cx_dbgc'), ('CX_MISC', 'cx_misc')):
        put(f'WINDOW_{key}', gpu.named_reg(name), f'gpu reg {name}')
    for key, name in (('GMU', 'gmu'), ('GMU_AO', 'gmu_ao_blk_dec0')):
        put(f'WINDOW_{key}', gmu.named_reg(name), f'gmu reg {name}')
    put('WINDOW_GPUCC', find(hardware, '/soc/clock-controller@3d90000').reg()[0], 'gpucc reg')
    put('WINDOW_GCC', find(hardware, '/soc/clock-controller@100000').reg()[0], 'gcc reg')
    put('WINDOW_SMMU', smmu.reg()[0], 'gpu_smmu reg')
    for key, path in (('CMD_DB', '/reserved-memory/cmd-db@81c60000'), ('SMEM', '/reserved-memory/smem@81d00000'),
                      ('ZAP', '/reserved-memory/gpu-microcode@9b09a000')):
        put(f'WINDOW_{key}', find(hardware, path).reg()[0], f'{path} reg, no-map')
    put('WINDOW_QFPROM', qfprom.reg()[0], 'qfprom reg')
    put('WINDOW_LLCC', [llcc.named_reg(name) for name in LLCC_NAMES], 'llcc reg ' + ', '.join(LLCC_NAMES))
    put('CHIP_ID', gpu.u32('qcom,chipid'), 'gpu qcom,chipid')
    for key, name in (('GPU', 'kgsl_3d0_irq'), ('CX_HOST', 'cx_host_irq')):
        put(f'IRQ_{key}', gpu.named_interrupt(name), f'gpu interrupt {name} (INTID)')
    for key, name in (('HFI', 'hfi'), ('GMU', 'gmu')):
        put(f'IRQ_{key}', gmu.named_interrupt(name), f'gmu interrupt {name} (INTID)')
    if smmu.u32('#global-interrupts') != 1 or smmu.u32('#iommu-cells') != 2:
        fail('gpu_smmu: expected one global interrupt and #iommu-cells = 2')
    irqs = [intid for intid, _ in smmu.interrupts()]
    if len(irqs) < 5:
        fail('gpu_smmu: fewer than four context-bank interrupts')
    put('IRQ_SMMU_GLOBAL', irqs[0], 'gpu_smmu global interrupt (INTID)')
    put('IRQ_SMMU_CB', irqs[1:5], 'gpu_smmu context banks 0..3 (INTID)')
    handle = smmu.u32('phandle')
    gpu_sids = sids(hardware, gpu, handle)
    if len(gpu_sids) != 2:
        fail('gpu iommus: expected the user and LPAC streams')
    put('SID_GPU', gpu_sids[0], 'gpu iommus 0 (gfx3d_user)')
    put('SID_LPAC', gpu_sids[1], 'gpu iommus 1 (gfx3d_lpac)')
    gmu_sids = sids(hardware, gmu, handle)
    if len(gmu_sids) != 1:
        fail('gmu iommus: expected one stream')
    put('SID_GMU', gmu_sids[0], 'gmu iommus')
    names, cells = gpu.strings('nvmem-cell-names'), gpu.u32s('nvmem-cells')
    if names != ['speed_bin'] or len(cells) != 1:
        fail('gpu: nvmem-cells is not the speed_bin cell')
    fuse = by_phandle(hardware, cells[0])
    if fuse.parent is not qfprom:
        fail('gpu speed_bin cell is not in the qfprom node')
    bits = fuse.u32s('bits')
    if bits[0] != 0:
        fail('gpu_speed_bin does not start at bit 0')
    put('QFPROM_SPEEDBIN_OFFSET', fuse.reg()[0][0], 'qfprom gpu-speed-bin reg')
    put('SPEEDBIN_BITS', bits[1], 'qfprom gpu-speed-bin bits')
    return values


LEVEL_PROPS = {'reg', 'qcom,gpu-freq', 'qcom,level', 'qcom,bus-min', 'qcom,bus-freq', 'qcom,bus-max', 'qcom,acd-level'}
BIN_PROPS = {'qcom,speed-bin', 'qcom,sku-codes', 'qcom,initial-pwrlevel', '#address-cells', '#size-cells'}


def level_bins(gpu, ddr_levels):
    """qcom,gpu-pwrlevel-bins in DT order; levels stored ascending, initial as the DT index (0 = fastest), as KGSL reads it
    (Sm8750GpuBin, Adreno830Board::initial_level)."""
    result = []
    for node in gpu.children['qcom,gpu-pwrlevel-bins'].children.values():
        if not node.name.startswith('qcom,gpu-pwrlevels-'):
            continue
        extra = set(node.props) - BIN_PROPS - {'name'}
        if extra:
            fail(f'{node.path()}: unhandled properties {sorted(extra)}')
        levels = {}
        for level in node.children.values():
            extra = set(level.props) - LEVEL_PROPS - {'name'}
            if extra:
                fail(f'{level.path()}: unhandled properties {sorted(extra)}')
            freq = level.u32('qcom,gpu-freq')
            if freq == 0:
                continue   # KGSL ignores zero levels
            if freq % 1000:
                fail(f'{level.path()}: frequency is not a whole kHz')
            bus = level.u32('qcom,bus-freq')
            entry = {'khz': freq // 1000, 'vlvl': level.u32('qcom,level'), 'bus_min': level.u32('qcom,bus-min', bus),
                     'bus': bus, 'bus_max': level.u32('qcom,bus-max', bus), 'acd': level.u32('qcom,acd-level', 0)}
            index = level.u32('reg')
            if index in levels:
                fail(f'{level.path()}: duplicate reg {index}')
            if not entry['bus_min'] <= entry['bus'] <= entry['bus_max'] < ddr_levels:
                fail(f'{level.path()}: bus votes out of order or past qcom,bus-table-ddr')
            levels[index] = entry
        count = len(levels)
        if sorted(levels) != list(range(count)) or not 0 < count <= MAX_LEVELS:
            fail(f'{node.path()}: level indices are not 0..{count - 1} or more than {MAX_LEVELS}')
        ordered = [levels[i] for i in range(count)]
        if any(b['khz'] > a['khz'] for a, b in zip(ordered, ordered[1:])):
            fail(f'{node.path()}: levels are not in descending frequency order')
        skus = node.u32s('qcom,sku-codes') if 'qcom,sku-codes' in node.props else []
        if len(skus) > MAX_SKUS:
            fail(f'{node.path()}: {len(skus)} sku codes')
        initial = node.u32('qcom,initial-pwrlevel')
        if initial >= count:
            fail(f'{node.path()}: bad qcom,initial-pwrlevel')
        speed = node.u32('qcom,speed-bin') if 'qcom,speed-bin' in node.props else None
        if speed is None and not skus:
            fail(f'{node.path()}: neither qcom,speed-bin nor qcom,sku-codes')
        result.append({'name': node.name, 'speed_bin': speed, 'skus': skus, 'initial': initial,
                       'levels': list(reversed(ordered))})
    if len(result) != BINS:
        fail(f'expected {BINS} power-level bins, found {len(result)}')
    return result


def common_levels(bins):
    """The ascending prefix on which every bin agrees in khz, vlvl and acd (Sm8750GpuLevelsCommon); bus votes the lowest
    any bin gives."""
    count = min(len(b['levels']) for b in bins)
    common = []
    for i in range(count):
        first = bins[0]['levels'][i]
        if any((b['levels'][i]['khz'], b['levels'][i]['vlvl'], b['levels'][i]['acd']) !=
               (first['khz'], first['vlvl'], first['acd']) for b in bins):
            break
        common.append({key: (min(b['levels'][i][key] for b in bins) if key.startswith('bus') else first[key])
                       for key in first})
    return common


def runtime_values(live):
    """(B): from the runtime DTB, as plain JSON values."""
    gpu, gmu = find(live, '/soc/qcom,kgsl-3d0@3d00000'), find(live, '/soc/qcom,gmu@3d37000')
    smmu = find(live, '/soc/kgsl-smmu@3da0000')
    zones = find(live, '/soc/thermal-zones')
    sensors = {zones.children[f'gpuss-{i}'].u32s('thermal-sensors')[0] for i in range(8)}
    if len(sensors) != 1:
        fail('the GPU thermal zones gpuss-0..7 do not share one TSENS block')
    tsens = by_phandle(live, sensors.pop())
    actlr = smmu.u32s('qcom,actlr')
    if len(actlr) != 3:
        fail('kgsl-smmu qcom,actlr is not one <SID MASK VALUE> triplet')
    table = gmu.u32s('qcom,gmu-freq-table')
    if len(table) != 4:
        fail('qcom,gmu-freq-table is not two <Hz vlvl> pairs')
    ddr = gpu.u32s('qcom,bus-table-ddr')
    msm = live.u32s('qcom,msm-id')
    return {
        'WINDOW_RSC_DRV2': list(find(live, '/soc/rsc@16500000').named_reg('drv-2')),
        'WINDOW_AOSS_MSGRAM': list(find(live, '/soc/power-controller@c300000').reg()[0]),
        'WINDOW_IPCC': list(find(live, '/soc/qcom,ipcc@406000').reg()[0]),
        'WINDOW_TSENS_TM': list(tsens.reg()[0]),
        'TSENS_NAME': tsens.name,
        'IRQ_SCM_WAITQ': find(live, '/firmware/qcom_scm').interrupts()[0][0],
        'SMMU_ACTLR_DT': actlr[2],
        'UBWC_MODE': gpu.u32('qcom,ubwc-mode'),
        'MIN_ACCESS_LENGTH': gpu.u32('qcom,min-access-length'),
        'DDR_KBPS': ddr,
        'CNOC_LEVELS': gpu.u32s('qcom,bus-table-cnoc'),
        'GMU_KHZ': [table[0] // 1000, table[2] // 1000],
        'GMU_VLVL': [table[1], table[3]],
        'SOC_IDS': sorted({value & 0xffff for value in msm[0::2]}),
        'BINS': level_bins(gpu, len(ddr)),
    }


def cross_check(hardware, hardware_tree, live):
    """Every (A) value the runtime DTB also has must agree with the DTS (the SMMU interrupts: all 25 context banks)."""
    gpu, gmu = find(live, '/soc/qcom,kgsl-3d0@3d00000'), find(live, '/soc/qcom,gmu@3d37000')
    smmu = find(live, '/soc/kgsl-smmu@3da0000')
    llcc = find(live, '/soc/cache-controller@24800000')
    fuse = find(live, '/soc/qfprom@221c8000/gpu_speed_bin@138')
    handle = smmu.u32('phandle')

    def sid(node):
        specifier = node.u32s('iommus')
        if len(specifier) != 3 or specifier[0] != handle:
            fail(f'{node.path()}: iommus is not one <&kgsl_smmu SID MASK> specifier')
        return specifier[1]

    live_values = {
        'WINDOW_GPU': gpu.named_reg('kgsl_3d0_reg_memory'), 'WINDOW_RSCC': gpu.named_reg('rscc'),
        'WINDOW_CX_DBGC': gpu.named_reg('cx_dbgc'), 'WINDOW_CX_MISC': gpu.named_reg('cx_misc'),
        'WINDOW_GMU': gmu.named_reg('gmu'), 'WINDOW_GMU_AO': gmu.named_reg('gmu_ao_blk_dec0'),
        'WINDOW_GPUCC': find(live, '/soc/clock-controller@3d90000').reg()[0],
        'WINDOW_GCC': find(live, '/soc/clock-controller@100000').reg()[0],
        'WINDOW_SMMU': smmu.reg()[0],
        'WINDOW_CMD_DB': find(live, '/reserved-memory/aop_cmd_db_region@81c60000').reg()[0],
        'WINDOW_SMEM': find(live, '/reserved-memory/smem_region@81d00000').reg()[0],
        'WINDOW_ZAP': find(live, '/reserved-memory/gpu_microcode_region@9b09a000').reg()[0],
        'WINDOW_QFPROM': find(live, '/soc/qfprom@221c8000').reg()[0],
        'WINDOW_LLCC': [llcc.named_reg(name) for name in LLCC_NAMES],
        'CHIP_ID': gpu.u32('qcom,chipid'),
        'IRQ_GPU': gpu.named_interrupt('kgsl_3d0_irq'), 'IRQ_CX_HOST': gpu.named_interrupt('cx_host_irq'),
        'IRQ_HFI': gmu.named_interrupt('hfi'), 'IRQ_GMU': gmu.named_interrupt('gmu'),
        'IRQ_SMMU_GLOBAL': smmu.interrupts()[0][0], 'IRQ_SMMU_CB': [i for i, _ in smmu.interrupts()[1:5]],
        'SID_GPU': sid(find(live, '/soc/qcom,kgsl-iommu@3da0000/gfx3d_user')),
        'SID_LPAC': sid(find(live, '/soc/qcom,kgsl-iommu@3da0000/gfx3d_lpac')),
        'SID_GMU': sid(gmu),
        'QFPROM_SPEEDBIN_OFFSET': fuse.reg()[0][0], 'SPEEDBIN_BITS': fuse.u32s('bits')[1],
    }
    for name, live_value in live_values.items():
        if hardware[name][0] != live_value:
            fail(f'{name}: DTS {hardware[name][0]} differs from the runtime DTB {live_value}')
    if gpu.props.get('nvmem-cells') != fuse.props.get('phandle'):
        fail('the runtime DTB GPU speed_bin cell is not gpu_speed_bin@138')
    if find(live, '/soc/kgsl-smmu@3da0000').u32('#global-interrupts') != 1:
        fail('kgsl-smmu: expected one global interrupt')
    if smmu.interrupts() != find(hardware_tree, '/soc/iommu@3da0000').interrupts():
        fail('the DTS gpu_smmu interrupts differ from the runtime DTB')


def digest_of(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def c_levels(levels):
    return '{' + ', '.join(f'{{{l["khz"]}u, {l["vlvl"]:#x}u, {l["bus_min"]}u, {l["bus"]}u, {l["bus_max"]}u, 0u, {l["acd"]:#010x}u}}'
                           for l in levels) + '}'


def render(hardware, runtime, digest, runtime_digest):
    lines = ['// SPDX-License-Identifier: BSD-2-Clause-Patent',
             '// Generated by scripts/prepare-pagani-gpu-inputs.py; edit the DTS or record the runtime DT again, then run it.',
             '// (A) dts/oneplus13t.dts + soc:dts/sm8750.dtsi; (B) the PKX110 runtime DT values recorded in',
             f'// scripts/data/sm8750-gpu-inputs.json (normalised JSON sha256 {runtime_digest}).',
             '// Interrupts are GIC INTIDs (SPI + 32). Level tables are ascending (GMU level = index + 1, level 0 is off);',
             '// PAGANI_GPU_BIN_INITIAL is qcom,initial-pwrlevel, the DT index (0 = fastest), as KGSL reads it.',
             '#pragma once',
             f'#define PAGANI_GPU_INPUTS_DIGEST "{digest}"',
             f'#define PAGANI_GPU_RUNTIME_DT_DIGEST "{runtime_digest}"']

    def window(value):
        return f'{{{value[0]:#x}ULL, {value[1]:#x}ULL}}'

    def number(name, value):
        hexadecimal = name.startswith(('CHIP_ID', 'SMMU_ACTLR', 'QFPROM_SPEEDBIN_OFFSET', 'GMU_VLVL'))
        return f'{value:#x}u' if hexadecimal else f'{value}u'

    for name, (value, note) in hardware.items():
        if name == 'WINDOW_LLCC':
            lines.append(f'#define PAGANI_GPU_WINDOW_LLCC_COUNT {len(value)}u')
            lines.append(f'#define PAGANI_GPU_WINDOW_LLCC {{{", ".join(window(v) for v in value)}}}  // {note}')
        elif name.startswith('WINDOW_'):
            lines.append(f'#define PAGANI_GPU_{name} {window(value)}  // {note}')
        elif isinstance(value, list):
            lines.append(f'#define PAGANI_GPU_{name}_COUNT {len(value)}u')
            lines.append(f'#define PAGANI_GPU_{name} {{{", ".join(number(name, v) for v in value)}}}  // {note}')
        else:
            lines.append(f'#define PAGANI_GPU_{name} {number(name, value)}  // {note}')
    lines.append(f'#define PAGANI_GPU_SOC_ID {SOC_ID}u  // SMEM socinfo id measured on PKX110; runtime DT qcom,msm-id '
                 f'{"/".join(map(str, runtime["SOC_IDS"]))}')
    for name in ('WINDOW_RSC_DRV2', 'WINDOW_AOSS_MSGRAM', 'WINDOW_IPCC', 'WINDOW_TSENS_TM'):
        note = {'WINDOW_RSC_DRV2': 'runtime DT apps_rsc reg drv-2', 'WINDOW_AOSS_MSGRAM': 'runtime DT aoss_qmp reg (message RAM)',
                'WINDOW_IPCC': 'runtime DT ipcc_mproc reg',
                'WINDOW_TSENS_TM': f'runtime DT {runtime["TSENS_NAME"]} TM region (sensors of gpuss-0..7)'}[name]
        lines.append(f'#define PAGANI_GPU_{name} {window(runtime[name])}  // {note}')
    for name, note in (('IRQ_SCM_WAITQ', 'runtime DT qcom_scm interrupt (INTID, edge)'),
                       ('SMMU_ACTLR_DT', 'runtime DT kgsl-smmu qcom,actlr value (KGSL); PKX110 keeps only 0x303'),
                       ('UBWC_MODE', 'runtime DT qcom,ubwc-mode'), ('MIN_ACCESS_LENGTH', 'runtime DT qcom,min-access-length')):
        lines.append(f'#define PAGANI_GPU_{name} {number(name, runtime[name])}  // {note}')
    for name, note in (('DDR_KBPS', 'runtime DT qcom,bus-table-ddr'), ('CNOC_LEVELS', 'runtime DT qcom,bus-table-cnoc'),
                       ('GMU_KHZ', 'runtime DT qcom,gmu-freq-table (Hz / 1000)'),
                       ('GMU_VLVL', 'runtime DT qcom,gmu-freq-table levels')):
        value = runtime[name]
        lines.append(f'#define PAGANI_GPU_{name}_COUNT {len(value)}u')
        lines.append(f'#define PAGANI_GPU_{name} {{{", ".join(number(name, v) for v in value)}}}  // {note}')
    bins = runtime['BINS']
    lines.append(f'#define PAGANI_GPU_BIN_COUNT {len(bins)}u  // runtime DT qcom,gpu-pwrlevel-bins, DT order')
    for i, b in enumerate(bins):
        lines.append(f'#define PAGANI_GPU_BIN{i}_COUNT {len(b["levels"])}u  // {b["name"]}')
        lines.append(f'#define PAGANI_GPU_BIN{i}_LEVELS {c_levels(b["levels"])}')
    lines.append(f'#define PAGANI_GPU_BIN_SPEED {{{", ".join(f"{(b["speed_bin"] or 0):#x}u" for b in bins)}}}  // qcom,speed-bin (0: SKU bin)')
    lines.append(f'#define PAGANI_GPU_BIN_SKU_COUNT {{{", ".join(f"{len(b["skus"])}u" for b in bins)}}}  // qcom,sku-codes count')
    lines.append('#define PAGANI_GPU_BIN_SKU {' + ', '.join(
        '{' + ', '.join(f'{v}u' for v in (b['skus'] + [0] * MAX_SKUS)[:MAX_SKUS]) + '}' for b in bins) + '}  // qcom,sku-codes')
    lines.append(f'#define PAGANI_GPU_BIN_INITIAL {{{", ".join(f"{b["initial"]}u" for b in bins)}}}  // qcom,initial-pwrlevel')
    common = common_levels(bins)
    lines.append(f'#define PAGANI_GPU_COMMON_LEVEL_COUNT {len(common)}u  // the <= {common[-1]["khz"] // 1000} MHz levels every bin shares')
    lines.append(f'#define PAGANI_GPU_COMMON_LEVELS {c_levels(common)}')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-dtb', type=Path, help='PKX110 runtime DTB (pinned): re-extract and compare the recorded values')
    parser.add_argument('--soc', type=Path, default=DEVICE.parent / 'UniXNU-sm8750-common', help='sm8750-common checkout')
    parser.add_argument('--check', action='store_true', help='compare with the committed header instead of writing it')
    parser.add_argument('--record', action='store_true', help='with --live-dtb: record the runtime DT values and their pin')
    args = parser.parse_args()
    pins = json.loads(PINS.read_text())
    hardware_tree = compile_dts(args.soc)
    hardware = hardware_values(hardware_tree)
    recorded = pins.get('runtime_dt', {})
    if args.live_dtb:
        pin = pins['live_dtb']
        data = args.live_dtb.read_bytes()
        if len(data) != pin['bytes'] or hashlib.sha256(data).hexdigest() != pin['sha256']:
            fail(f'{args.live_dtb} is not the pinned runtime DTB ({pin["sha256"]})')
        live = read_fdt(data)
        cross_check(hardware, hardware_tree, live)
        runtime = runtime_values(live)
        if args.record:
            pins['runtime_dt'] = {'comment': 'Normalised GPU values of the pinned runtime DTB (ARCHITECTURE 3.2 B); '
                                             'sha256 is that of this "values" object as compact sorted JSON.',
                                  'sha256': digest_of(runtime), 'values': runtime}
            PINS.write_text(json.dumps(pins, indent=2, ensure_ascii=False) + '\n')
            recorded = pins['runtime_dt']
        elif runtime != recorded.get('values'):
            fail('the runtime DTB values differ from the recorded ones; run with --record after checking them')
    elif args.record:
        fail('--record needs --live-dtb')
    runtime = recorded.get('values')
    if runtime is None:
        fail('no recorded runtime DT values; run with --live-dtb <runtime DTB> --record')
    runtime_digest = digest_of(runtime)
    if runtime_digest != recorded.get('sha256'):
        fail(f'the recorded runtime DT values do not match their pin {recorded.get("sha256")}')
    if SOC_ID not in runtime['SOC_IDS']:
        fail(f'SoC id {SOC_ID} is not in the runtime DT qcom,msm-id')
    digest = digest_of({'hardware': {k: v for k, (v, _) in hardware.items()}, 'runtime': runtime, 'soc_id': SOC_ID})
    text = render(hardware, runtime, digest, runtime_digest)
    count = len(hardware) + len(runtime) + 1
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text() != text:
            fail(f'{OUTPUT} is stale; run without --check')
        source = 'the DTS and the pinned runtime DTB' if args.live_dtb else 'the DTS and the recorded runtime DT values'
        print(f'PASS: {OUTPUT.relative_to(DEVICE)} matches {source} ({count} inputs, {len(runtime["BINS"])} level bins)')
        return
    OUTPUT.write_text(text)
    print(f'wrote {OUTPUT.relative_to(DEVICE)} ({count} inputs, digest {digest[:16]})')


if __name__ == '__main__':
    main()
