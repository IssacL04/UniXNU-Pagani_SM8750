#!/usr/bin/env python3
"""Check the 13T UEFI RAM allocations against the exported bootloader DT."""
import re
import subprocess
from pathlib import Path


DEVICE = Path(__file__).resolve().parents[1]
UEFI = DEVICE.parent / 'uefi-oneplus13t'
PACKAGE = UEFI / 'Platforms/OnePlus/oneplus13tPkg'
DTB = DEVICE / 'sysinfo/live.dtb'


def dt_ranges(node):
    value = subprocess.check_output(['fdtget', '-t', 'x', str(DTB), node, 'reg'], text=True)
    cells = [int(cell, 16) for cell in value.split()]
    assert len(cells) % 4 == 0, f'{node}: expected 64-bit addresses and sizes'
    return [(a << 32 | b, (a << 32 | b) + (c << 32 | d))
            for a, b, c, d in zip(cells[::4], cells[1::4], cells[2::4], cells[3::4]) if c or d]


def check(source):
    rows = re.findall(r'\{"([^"]+)",\s*(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+),'
                      r'\s*(\w+),\s*(\w+),\s*(\w+),\s*(\w+),\s*(\w+)\}', source)
    assert rows and len(rows) == source.count('{"'), 'unparsed memory-map entries'
    ram = sorted(dt_ranges('/memory'))
    reserved = []
    nodes = subprocess.check_output(['fdtget', '-l', str(DTB), '/reserved-memory'], text=True)
    for name in nodes.splitlines():
        node = '/reserved-memory/' + name
        props = subprocess.check_output(['fdtget', '-p', str(DTB), node], text=True).splitlines()
        if 'reg' in props:
            reserved.extend((start, end, name) for start, end in dt_ranges(node))
    fence = dt_ranges('/reserved-memory/hwfence-shmem')
    assert fence, 'hardware-fence reservation missing from the exported DT'
    protected = []
    allocations = 0
    for name, base, size, hob, resource, _, kind, _ in rows:
        start = int(base, 16)
        end = start + int(size, 16)
        assert start % 4096 == end % 4096 == 0 and end > start, name
        if hob == 'AddMem' and resource == 'SYS_MEM' and kind == 'Reserv':
            protected.append((start, end))
        if resource != 'SYS_MEM' or kind == 'Reserv':
            continue
        allocations += 1
        cursor = start
        for low, high in ram:
            if low <= cursor < high:
                cursor = min(end, high)
        assert cursor == end, f'{name}: allocation crosses a non-RAM interval'
        for low, high, label in reserved:
            assert end <= low or start >= high, f'{name}: overlaps {label}'
    assert all(any(low <= start and end <= high for low, high in protected)
               for start, end in fence), 'hardware-fence range lacks an explicit reserved allocation HOB'
    vectors = [row for row in rows if row[0] == 'CPU_Vectors']
    assert len(vectors) == 1, 'EnvDxeEnhanced requires one CPU_Vectors region'
    _, base, size, hob, resource, attrs, kind, arm_attrs = vectors[0]
    start, length = int(base, 16), int(size, 16)
    assert (start, length) == (0xA7600000, 0x1000), 'CPU_Vectors must occupy the page before Info_Blk'
    assert (hob, resource, attrs, kind, arm_attrs) == ('AddMem', 'SYS_MEM', 'SYS_MEM_CAP', 'BsData', 'WRITE_BACK'), 'CPU_Vectors must be mapped and allocated before EnvDxeEnhanced runs'
    for name, base, size, *_ in rows:
        if name != 'CPU_Vectors':
            low, high = int(base, 16), int(base, 16) + int(size, 16)
            assert start + length <= low or start >= high, f'CPU_Vectors overlaps {name}'
    print(f'PASS: {allocations} RAM allocations fit the exported DT; hardware-fence and CPU_Vectors checks passed')


if __name__ == '__main__':
    assert 'MemoryMapLib|oneplus13tPkg/Library/MemoryMapLib/MemoryMapLib.inf' in (PACKAGE / 'oneplus13t.dsc').read_text()
    check((PACKAGE / 'Library/MemoryMapLib/MemoryMapLib.c').read_text())
