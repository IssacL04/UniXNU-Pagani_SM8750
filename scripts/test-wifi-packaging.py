#!/usr/bin/env python3
"""Check launchd merging and Peach input validation without Apple signing tools."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tree', type=Path, required=True)
args = parser.parse_args()
runtime = module('boot_runtime', args.tree / 'scripts/build-boot-runtime.py')
wifi = module('wifi_build', Path(__file__).with_name('build-wifi-userspace.py'))


def serialize(*command):
    assert command[:3] == ('plutil', '-convert', 'binary1')
    path = command[3]
    path.write_bytes(plistlib.dumps(plistlib.loads(path.read_bytes()), fmt=plistlib.FMT_BINARY))


def refused(operation):
    try:
        operation()
    except ValueError:
        return
    raise AssertionError('invalid input accepted')


runtime.run = serialize  # Host fixture only; production uses Apple's serializer and codesign.
with tempfile.TemporaryDirectory(prefix='pagani-wifi-package-') as directory:
    root = Path(directory)
    source, jobs, merged = root / 'original.plist', root / 'daemons', root / 'xpc/launchd.plist'
    jobs.mkdir()
    icon = 'com.apple.iconservices.iconservicesagent'
    key = '/System/Library/LaunchDaemons/' + icon + '.plist'
    original = {'LaunchDaemons': {key: {'Label': icon, 'EnvironmentVariables': {'KEEP': 'yes'}}}, 'Version': 1}
    source.write_bytes(plistlib.dumps(original))
    job = jobs / 'org.unixnu.wifi.supplicant.plist'
    job.write_bytes(plistlib.dumps({'Label': 'org.unixnu.wifi.supplicant'}))
    report = runtime.merge_launchd_cache(source, jobs, merged)
    assert report['original_entries_preserved'] and report['original_jobs'] == 1
    assert plistlib.loads(merged.read_bytes())['LaunchDaemons'][key] == original['LaunchDaemons'][key]
    runtime.merge_launchd_cache(source, jobs, merged, {icon: {'CI_ENABLE_METAL_GPU': '1'}})
    assert plistlib.loads(merged.read_bytes())['LaunchDaemons'][key]['EnvironmentVariables'] == {
        'KEEP': 'yes', 'CI_ENABLE_METAL_GPU': '1'}
    assert plistlib.loads(source.read_bytes()) == original
    refused(lambda: runtime.merge_launchd_cache(source, jobs, merged, {'missing': {'MODE': '1'}}))
    refused(lambda: runtime.merge_launchd_cache(source, jobs, merged, {icon: {'MODE': 1}}))
    refused(lambda: runtime.merge_launchd_cache(merged, jobs, root / 'collision.plist'))
    firmware = root / 'firmware'
    (firmware / 'peach').mkdir(parents=True)
    manifest = {}
    for name in ('peach/bdwlan.elf', 'peach/regdb.bin'):
        body = ('fixture:' + name).encode()
        (firmware / name).write_bytes(body)
        manifest[name] = {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
    manifest_path = firmware / 'MANIFEST.json'
    manifest_path.write_text(json.dumps(manifest))
    assert wifi.stage_firmware(firmware, root / 'staged') == manifest
    (firmware / 'peach/regdb.bin').write_bytes(b'tampered')
    refused(lambda: wifi.stage_firmware(firmware, root / 'bad'))
    manifest_path.write_text(json.dumps({'../escape': {}}))
    refused(lambda: wifi.stage_firmware(firmware, root / 'bad'))
    manifest_path.write_text(json.dumps({'join.txt': {}}))
    refused(lambda: wifi.stage_firmware(firmware, root / 'bad'))
print('PASS: launchd preservation, per-service environment, collisions, Peach hashes and path/credential rejection')
