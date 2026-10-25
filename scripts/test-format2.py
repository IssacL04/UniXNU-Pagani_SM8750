#!/usr/bin/env python3
"""Check the migrated profile and the ADT handoff against the retained format-1 contract."""
import argparse
import runpy
import struct
import subprocess
import tempfile
from pathlib import Path

from unixnu import cli, components, devicetree, feeds, kernel, patches
from unixnu.config import Context

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--device', type=Path, default=Path(__file__).resolve().parents[1])
args = parser.parse_args()
ctx = Context(cli.parser().parse_args(['status', '-D', str(args.device)]))
modules = feeds.resolve(ctx)
assert ctx.schema_version == 2
assert list(ctx.profile_roots) == ['arch', 'soc', 'os', 'device']
assert ctx.work.parts[-3:] == ('oneplus13t', 'ipados-17.7.11-21H461', 'oneplus13t')
assert len(ctx.component_specs) == 15
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
            if path == '/device-tree/arm-io' and key == 'ranges':
                assert actual[path][key] == struct.pack('<QQQ', 0, 0x16000000, 0x1000000)
                continue
            if path == '/device-tree/chosen' and key in ('random-seed','dram-base','dram-size'):
                continue
            assert actual[path][key] == value, (path, key)
    chosen = actual['/device-tree/chosen']
    assert len(chosen['random-seed']) == 64
    assert struct.unpack('<Q', chosen['dram-base']) == (0x980000000,)
    assert struct.unpack('<Q', chosen['dram-size']) == (0x180000000,)
    assert struct.unpack('<Q', chosen['darwinboot-memory-size']) == (0x100000000,)
print('PASS: four profiles, 15 components, ordered archives, root policy and format-2 ADT contract')
