#!/usr/bin/env python3
"""Check the migrated profile and the ADT handoff against the retained format-1 contract."""
import argparse
import os
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
    chosen = actual['/device-tree/chosen']
    assert len(chosen['random-seed']) == 64
    assert struct.unpack('<Q', chosen['dram-base']) == (0x980000000,)
    assert struct.unpack('<Q', chosen['dram-size']) == (0x180000000,)
    assert struct.unpack('<Q', chosen['darwinboot-memory-size']) == (0x100000000,)
    assert actual['/device-tree/product']['product-id'] == bytes.fromhex('e9fefef6e6f9d12a5ba1a2551866cbbd749f0ec3')
    assert actual['/device-tree/product/audio']['wireless-splitter'] == struct.pack('<I', 1)

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
