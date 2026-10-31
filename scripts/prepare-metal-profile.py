#!/usr/bin/env python3
"""Create a separate A830 build profile, retaining the CPU-display default."""
import argparse
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def value(item):
    if isinstance(item, str):
        return json.dumps(item)
    if isinstance(item, bool):
        return str(item).lower()
    if isinstance(item, int):
        return str(item)
    if isinstance(item, list):
        return '[' + ', '.join(value(x) for x in item) + ']'
    if isinstance(item, dict):
        return '{' + ', '.join(json.dumps(k) + ' = ' + value(v) for k, v in item.items()) + '}'
    raise ValueError('Unsupported TOML value: ' + repr(item))


def document(data):
    lines = []
    def table(items, path):
        if path:
            lines.append('[' + '.'.join(json.dumps(k) for k in path) + ']')
        lines.extend(json.dumps(k) + ' = ' + value(v) for k, v in items.items() if not isinstance(v, dict))
        lines.append('')
        for k, v in items.items():
            if isinstance(v, dict):
                table(v, [*path, k])
    table(data, [])
    text = '\n'.join(lines)
    if tomllib.loads(text) != data:
        raise ValueError('Generated TOML failed its round-trip check')
    return text


def prepare(output, soc):
    probe = ROOT.parent / 'UniXNU-Pagani-Drivers/drivers/Stage7Probe'
    if not (probe / 'Stage7Probe.cpp').is_file() or 'pagani_gpu_start' not in (probe / 'Stage7Probe.cpp').read_text():
        raise ValueError('Require the sibling Stage7Probe checkout with the staged GPU entry')
    board = tomllib.loads((ROOT / 'board.toml').read_text())
    board['board']['description'] = 'OnePlus 13T A830/Metal candidate; hardware qualification pending'
    board['components']['include'] += ['Adreno740', 'AdrenoMetal']
    board['kernel']['defconfig'] = 'oneplus13t_metal_defconfig'
    board['kernel']['archives'] += ['component:Adreno740']
    board['kernel']['prelink']['roots'].append('com.apple.iokit.IOGPUFamily')
    board['payload']['title'] = 'OnePlus 13T A830 Metal candidate'
    # shortcut: 120 Hz is software pacing; panel timing and TE synchronization still need device qualification.
    board['payload']['kernel_args'] = ['sheng-vsync=120' if arg == 'sheng-vsync=60' else arg
                                       for arg in board['payload']['kernel_args']]
    # shortcut: SYSMEM fixes observed A830 color corruption; restore GMEM after its load/store paths pass device checks.
    board['payload']['kernel_args'] += ['pagani-gpu=1', 'sheng-gpu-addon=1', 'sheng-gpu-metal-opens=0', 'sheng-fb-gpu=1', 'sheng-tu-debug=sysmem,nocb', 'sheng-gpu-sample=0']
    config = (ROOT / 'configs/oneplus13t_defconfig').read_text()
    marker = '# CONFIG_XNU_NATIVE_ADRENO is not set'
    if config.count(marker) != 1:
        raise ValueError('CPU baseline no longer has the expected Adreno selection')
    config = config.replace(marker, 'CONFIG_XNU_NATIVE_ADRENO=y')
    output.mkdir(parents=True, exist_ok=True)
    for name in ('drivers', 'kits', 'modules', 'package', 'dts', 'scripts', 'sysinfo', 'feeds.toml', 'patches', 'porting.toml'):
        target, source = output / name, ROOT / name
        if target.is_symlink() and target.resolve() == source.resolve():
            continue
        if target.exists() or target.is_symlink():
            raise ValueError('Unexpected existing profile path: ' + str(target))
        target.symlink_to(source, target_is_directory=source.is_dir())
    (output / 'configs').mkdir(exist_ok=True)
    (output / 'configs/oneplus13t_metal_defconfig').write_text(config)
    (output / 'board.toml').write_text(document(board))
    (output / '.cache').mkdir(exist_ok=True)
    firmware = output / '.cache/firmware'
    if not firmware.exists():
        firmware.symlink_to(ROOT / '.cache/firmware', target_is_directory=True)
    sources = [{'name': 'Stage7Probe', 'kind': 'driver', 'local': str(probe.resolve())}]
    sources.append({'name': 'PaganiInput', 'kind': 'driver', 'local': str(probe.parent / 'PaganiInput')})
    sources.append({'name': 'NativeMobileDisplay', 'kind': 'driver', 'local': str(probe.parent / 'NativeMobileDisplay')})
    sources.append({'name': 'PaganiPanel', 'kind': 'driver', 'local': str(probe.parent / 'PaganiPanel')})
    sources.append({'name': 'BootProgress', 'kind': 'driver', 'local': str(probe.parent / 'BootProgress')})
    if soc:
        if not (soc / 'soc.toml').is_file():
            raise ValueError('SoC checkout has no soc.toml: ' + str(soc))
        sources.append({'name': 'sm8750', 'kind': 'soc', 'local': str(soc.resolve())})
    (output / 'local.toml').write_text(document({'source': sources}))
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.cache/metal-device')
    parser.add_argument('--soc', type=Path, help='use the working SoC checkout instead of the remote pin')
    args = parser.parse_args()
    prepare(args.output.resolve(), args.soc)
