#!/usr/bin/env python3
"""Build the 21H461 supplicant and signed launchd cache for the Pagani Data seed."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import sys
import tempfile
import tomllib


def build(tree, os_image, output, firmware=None):
    if sys.platform != 'darwin':
        raise ValueError('The iOS SDK, codesign and hdiutil require macOS')
    if output.exists():
        raise ValueError('Refuse to overwrite ' + str(output))
    spec = importlib.util.spec_from_file_location('boot_runtime', tree / 'scripts/build-boot-runtime.py')
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    component = tree / 'drivers/PaganiWifi/Ath12kWifi'
    runtime.run(sys.executable, component / 'tools/build-supplicant.py', '--target', 'ios')
    output.mkdir(parents=True)
    for name in ('wifi-bin', 'etc/wifi', 'daemons'):
        (output / name).mkdir(parents=True)
    binary = output / 'wifi-bin/unixnu-wpa_supplicant'
    shutil.copy2(component / 'out/wpa-ios/bin/wpa_supplicant', binary)
    binary.chmod(0o755)
    entitlements = output / 'entitlements.plist'
    entitlements.write_bytes(plistlib.dumps({'com.apple.private.security.no-container': True}))
    runtime.run('codesign', '--force', '--sign', '-', '--pagesize', '4096', '--identifier',
                'org.unixnu.wifi.supplicant', '--entitlements', entitlements, binary)
    binary_hash = runtime.verified_cdhash(binary)
    (output / 'etc/wifi/wpa_supplicant.conf').write_text('ap_scan=1\n')
    job = {'Label': 'org.unixnu.wifi.supplicant', 'ProgramArguments': [
        '/usr/libexec/unixnu-wpa_supplicant', '-Dsheng', '-ien0',
        '-c/private/var/ngpu/etc/wifi/wpa_supplicant.conf', '-q'],
        'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 3, 'UserName': 'root',
        'Umask': 0o77, 'ProcessType': 'Interactive',
        'StandardOutPath': '/var/log/unixnu-wifi.log', 'StandardErrorPath': '/var/log/unixnu-wifi.log'}
    (output / 'daemons/org.unixnu.wifi.supplicant.plist').write_bytes(plistlib.dumps(job))
    board = tomllib.loads((Path(__file__).resolve().parents[1] / 'board.toml').read_text())
    environment = board.get('payload', {}).get('runtime', {}).get('launchd_job_environment', {})
    with tempfile.TemporaryDirectory(prefix='wifi-os-', dir=output) as work:
        with runtime.os_mount(os_image, Path(work)) as mount:
            cache = runtime.merge_launchd_cache(mount / 'System/Library/xpc/launchd.plist',
                output / 'daemons', output / 'xpc/launchd.plist', environment)
    cache.update(runtime.sign_launchd_cache(output / 'xpc/launchd.plist'))
    firmware_files = stage_firmware(firmware, output / 'firmware/wlan') if firmware else {}
    report = dict(target='ipados-17.7.11-21H461', hardware_verified=False,
                  cdhashes=[binary_hash, cache['cdhash']], launchd=cache, firmware=firmware_files)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Built signed Pagani Wi-Fi service and launchd cache:', output)


def stage_firmware(source, destination):
    # Use the existing phone-derived manifest; credentials never belong in this input.
    manifest = json.loads((source / 'MANIFEST.json').read_text())
    files = {}
    for name, record in manifest.items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or path.name == 'join.txt' or not path.parts:
            raise ValueError('Invalid firmware manifest path: ' + name)
        local = source / path
        if local.is_symlink() or not local.resolve().is_relative_to(source.resolve()):
            raise ValueError('Firmware escapes input directory: ' + name)
        data = local.read_bytes()
        if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError('Firmware differs from manifest: ' + name)
        files[name] = data
    if not {'peach/bdwlan.elf', 'peach/regdb.bin'} <= files.keys():
        raise ValueError('Peach Data firmware requires the ODM board data and regulatory database')
    for name, data in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o644)
    return {name: manifest[name] for name in files}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--os-image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--firmware', type=Path)
    args = parser.parse_args()
    build(args.tree.resolve(), args.os_image.resolve(), args.output.resolve(), args.firmware)
