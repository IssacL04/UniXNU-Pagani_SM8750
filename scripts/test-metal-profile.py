#!/usr/bin/env python3
"""Check profile isolation and the real format-2 archive plan without compiling XNU."""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT.parent / 'UniXNU'
SOC = ROOT.parent / 'UniXNU-sm8750-common'
sys.path.insert(0, str(MAIN / 'scripts'))
from unixnu.cli import parser
from unixnu.config import Context
from unixnu.feeds import resolve
from unixnu.kernel import archive_plan

prepare = runpy.run_path(str(ROOT / 'scripts/prepare-metal-profile.py'))['prepare']
baseline = {name: (ROOT / name).read_bytes() for name in ('board.toml', 'configs/oneplus13t_defconfig')}
with tempfile.TemporaryDirectory(prefix='pagani-metal-profile-') as directory:
    out = Path(directory)
    profile = out / 'device'
    prepare(profile, SOC)
    prepare(profile, SOC)
    board = tomllib.loads((profile / 'board.toml').read_text())
    assert board['kernel']['archives'].count('component:Adreno740') == 1
    assert 'com.apple.iokit.IOGPUFamily' in board['kernel']['prelink']['roots']
    assert 'pagani-gpu=1' in board['payload']['kernel_args']
    assert board['payload']['kernel_args'].count('sheng-vsync=120') == 1
    assert 'sheng-vsync=60' not in board['payload']['kernel_args']
    assert 'sheng-diag=1' not in board['payload']['kernel_args']
    assert 'sheng-gpu-sample=0' in board['payload']['kernel_args']
    assert 'sheng-fb-gpu=1' in board['payload']['kernel_args']
    assert board['payload']['kernel_args'].count('sheng-tu-debug=sysmem,nocb') == 1
    assert 'sheng-gpu-addon=1' in board['payload']['kernel_args']
    assert 'CONFIG_XNU_NATIVE_ADRENO=y' in (profile / 'configs/oneplus13t_metal_defconfig').read_text()
    assert (profile / '.cache/firmware').resolve() == (ROOT / '.cache/firmware').resolve()
    args = parser().parse_args(['status', '-D', str(profile), '--out', str(out / 'build')])
    context = Context(args)
    modules = resolve(context)
    assert modules[('driver', 'Stage7Probe')].path == (ROOT.parent / 'UniXNU-Pagani-Drivers/drivers/Stage7Probe').resolve()
    assert modules[('driver', 'NativeMobileDisplay')].path == (ROOT.parent / 'UniXNU-Pagani-Drivers/drivers/NativeMobileDisplay').resolve()
    assert modules[('driver', 'BootProgress')].path == (ROOT.parent / 'UniXNU-Pagani-Drivers/drivers/BootProgress').resolve()
    assert modules[('driver', 'PaganiPanel')].path == (ROOT.parent / 'UniXNU-Pagani-Drivers/drivers/PaganiPanel').resolve()
    plan = archive_plan(context)
    components = [entry['id'] for kind, entry in plan if kind == 'component']
    assert components.count('Adreno740') == 1
    assert components.index('Adreno740') > components.index('NativeMobileDisplay')
    assert not any(kind == 'script' and entry.startswith('build-pagani-gpu') for kind, entry in plan)
    assert all((ROOT / name).read_bytes() == data for name, data in baseline.items())
    checkout = runpy.run_path(str(ROOT / 'scripts/build-metal-userspace.py'))['checkout']
    source = out / 'source'
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    (source / 'fixture').write_text('pinned source\n')
    subprocess.run(['git', '-C', str(source), 'add', 'fixture'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Input test', '-c', 'user.email=test@example.invalid',
                    'commit', '-qm', 'fixture'], check=True)
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    checkout(source, str(source), revision)
    try:
        checkout(source, str(source), '0' * 40)
    except ValueError:
        pass
    else:
        raise AssertionError('Mismatched source commit was accepted')
print('PASS: isolated Metal profile, firmware sharing, dependency/archive order and unchanged CPU baseline')
