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
    extras = ['Adreno830', 'AdrenoMetal', 'PaganiAdsp', 'PaganiAudio', 'PaganiBattery', 'PaganiHaptics',
              'PaganiSensors', 'PaganiSpeaker', 'PaganiWifi', 'PaganiBt', 'PaganiCamera', 'PaganiTorch', 'PaganiUsb']
    board['components']['include'] += extras + ['AdrenoFirmware']
    board['kernel']['defconfig'] = 'oneplus13t_metal_defconfig'
    board['kernel']['archives'] += ['component:Adreno830', 'build-pagani-gpu.py',
                                    *('component:' + name for name in extras[2:])]
    board['kernel']['prelink']['roots'].append('com.apple.iokit.IOGPUFamily')
    board['kernel']['prelink']['roots'] += ['com.apple.driver.AppleUSBXDCI', 'com.apple.driver.AppleUSBDeviceMux']
    board['payload']['title'] = 'OnePlus 13T A830 Metal candidate'
    # Panel TE and page flips stay opt-in until this build has device measurements.
    board['payload']['kernel_args'] = ['sheng-vsync=120' if arg == 'sheng-vsync=60' else arg
                                       for arg in board['payload']['kernel_args']]
    # shortcut: SYSMEM fixes observed A830 color corruption; restore GMEM after its load/store paths pass device checks.
    board['payload']['kernel_args'] += ['pagani-gpu=1', 'sheng-gpu-addon=1', 'sheng-gpu-metal-opens=0', 'sheng-fb-gpu=1', 'sheng-tu-debug=sysmem,nocb', 'sheng-gpu-sample=0',
                                      'pagani-vsync=120', 'pagani-battery=1', 'pagani-cpufreq=2', 'pagani-wifi=6', 'pagani-usb=1',
                                      'pagani-gpu-maxlevel=9', 'pagani-gpu-dcvs-min=342', 'pagani-gpu-ttarget=85']
    board.setdefault('adt', {}).setdefault('product', {})['wlan'] = {}
    config = (ROOT / 'configs/oneplus13t_defconfig').read_text()
    marker = '# CONFIG_XNU_NATIVE_ADRENO is not set'
    if config.count(marker) != 1:
        raise ValueError('CPU baseline no longer has the expected Adreno selection')
    config = config.replace(marker, 'CONFIG_XNU_NATIVE_ADRENO=y')
    config += '\nCONFIG_XNU_NATIVE_ADRENO_ARCHIVE="{tree}/build/adreno830/libAdreno830.a"\n'
    config += 'CONFIG_XNU_EXTRA_LD_ARCHIVES="{tree}/build/pagani-audio/libPaganiAudio.a"\n'
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
    drivers = probe.parent
    sources = [{'name': name, 'kind': 'driver', 'local': str((drivers / name).resolve())}
               for name in board['components']['include'] if (drivers / name).is_dir()]
    # A830 uses the pinned on-demand SMMU kit and its matching table-page provider.
    sources.append({'name': 'ArmSmmu4K', 'kind': 'kit', 'local': str(ROOT / 'modules/ArmSmmu4K')})
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
