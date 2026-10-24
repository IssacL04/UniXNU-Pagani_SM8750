#!/usr/bin/env python3
"""Check the bundled modules and the official resolver's local override contract."""
import argparse
import configparser
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace

DEVICE = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tree', type=Path, required=True)
args = parser.parse_args()
base = runpy.run_path(str(DEVICE / 'unixnu'))['prepare']()
sys.path.insert(0, str(base / 'scripts'))
from unixnu import cli, feeds

config = configparser.ConfigParser()
config.read(DEVICE / '.gitmodules')
assert config.sections() == ['submodule "modules/Pagani"']
assert config[config.sections()[0]]['url'] == 'https://github.com/IssacL04/UniXNU-Pagani-Drivers.git'
bundle = DEVICE / 'modules/Pagani'
ctx = SimpleNamespace(root=base, device=DEVICE, args=cli.common().parse_args([]))
resolved = feeds.resolve(ctx)
count = 0
for kind, folder in [('driver', 'drivers'), ('kit', 'kits')]:
    for module in (bundle / folder).iterdir():
        if not module.is_dir():
            continue
        link = DEVICE / folder / module.name
        assert link.is_symlink() and not link.readlink().is_absolute(), link
        tracked = subprocess.check_output(['git', '-C', str(DEVICE), 'ls-files', '-s',
                                           '--', str(link.relative_to(DEVICE))], text=True)
        assert tracked.startswith('120000 '), f'{link}: Git must track the symlink, not its target files'
        assert link.resolve() == module.resolve(), link
        assert resolved[kind, module.name].origin == 'device', link
        assert resolved[kind, module.name].path.resolve() == module.resolve(), link
        assert (args.tree / folder / module.name).resolve() == module.resolve(), link
        count += 1
assert count == 14, count
assert (args.tree / 'patches/xnu').resolve() == DEVICE / 'patches/xnu'
for path in ('drivers/ShengPlatformPower/ShengPlatformPower.cpp',
             'drivers/Stage7Probe/Stage7Probe.cpp'):
    assert (args.tree / path).is_file(), path

with tempfile.TemporaryDirectory(prefix='pagani-layout-') as directory:
    local = Path(directory).resolve()
    for folder, name in [('drivers', 'NativeUfs'), ('kits', 'VerifiedRoot')]:
        (local / folder / name).mkdir(parents=True)
    alias = local / 'alias'
    alias.symlink_to(local, target_is_directory=True)
    ctx.args = cli.common().parse_args(['--local', str(alias)])
    overridden = feeds.resolve(ctx)
    assert overridden['driver', 'NativeUfs'].path == local / 'drivers/NativeUfs'
    assert overridden['kit', 'VerifiedRoot'].path == local / 'kits/VerifiedRoot'
    assert overridden['driver', 'ArmCpu'].path.resolve() == bundle / 'drivers/ArmCpu'
    # A non-recursive clone must fail before silently falling back to generic drivers.
    (local / 'unixnu').write_bytes((DEVICE / 'unixnu').read_bytes())
    result = subprocess.run([sys.executable, str(local / 'unixnu'), '--prepare'],
                            capture_output=True, text=True)
    assert result.returncode != 0 and 'git submodule update --init --recursive' in result.stderr
print('PASS: 14 pinned modules, assembled paths, local overrides and missing-submodule guard')
