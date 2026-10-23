#!/usr/bin/env python3
"""Prepare volatile APFS Data from the pinned OS, preserving its var ownership.

Adapted from UniXNU scripts/prepare-owner-data-fixture.py; requires macOS/root.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import plistlib
import runpy
import shutil
import stat
import subprocess
import uuid


def prepare_userspace(target):
    for relative in ('containers/Bundle', 'containers/Data/System',
                     'containers/Shared/SystemGroup', 'containers/Temp'):
        (target / relative).mkdir(mode=0o755, parents=True, exist_ok=True)
    preferences = target / 'mobile/Library/Preferences'
    preferences.mkdir(mode=0o755, parents=True, exist_ok=True)
    for relative in (
        'containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist',
        'mobile/Library/Preferences/com.apple.MobileGestalt.plist',
        'mobile/Library/Preferences/com.apple.mobilegestalt.plist',
    ):
        (target / relative).unlink(missing_ok=True)
    path = preferences / 'com.apple.springboard.plist'
    values = plistlib.loads(path.read_bytes()) if path.exists() else {}
    values.update(SBDisableAutoDim=True, SBDontDimOrLockOnAC=True, SBDisableIdleSleep=True)
    path.write_bytes(plistlib.dumps(values, fmt=plistlib.FMT_BINARY))
    owner = (target / 'mobile').stat()
    os.chown(path, owner.st_uid, owner.st_gid)
    path.chmod(0o600)


def disable_unimplemented_watchdog(target, daemon):
    job = plistlib.loads(daemon.read_bytes())
    if (job.get('Label') != 'com.apple.watchdogd' or
            job.get('ProgramArguments') != ['/usr/libexec/watchdogd'] or
            job.get('_PanicOnCrash', {}).get('PanicOnConsecutiveCrash') is not True):
        raise ValueError('Unexpected original watchdog launch policy')
    for relative in ('db', 'db/com.apple.xpc.launchd'):
        directory = target / relative
        if directory.is_symlink():
            raise ValueError('Refuse symlink in launch policy path')
        directory.mkdir(mode=0o755, exist_ok=True)
    paths = [directory / name for name in ('disabled.plist', 'disabled.migrated')]
    if any(path.exists() or path.is_symlink() for path in paths):
        raise ValueError('Refuse to overwrite an existing launch policy')
    # shortcut: disable watchdogd in volatile Data until a real IOWatchdog backend exists.
    policy = {'com.apple.watchdogd': True}
    for path, data in zip(paths, (plistlib.dumps(policy), b'')):
        with path.open('xb') as stream:
            stream.write(data)
        path.chmod(0o644)
        if path.read_bytes() != data:
            raise ValueError('Launch policy readback mismatch')
    return list(policy)


@contextmanager
def mounted(image, target, readonly=False):
    target.mkdir(parents=True, exist_ok=True)
    options = ['-readonly', '-noautofsck'] if readonly else []
    attached = plistlib.loads(subprocess.check_output([
        'hdiutil', 'attach', '-nobrowse', '-owners', 'on', *options,
        '-mountpoint', str(target), '-plist', str(image)]))
    device = attached['system-entities'][0]['dev-entry']
    try:
        volumes = [e for e in attached['system-entities'] if e.get('mount-point') == str(target)]
        if len(volumes) != 1:
            raise ValueError('Require exactly one mounted volume')
        yield volumes[0]['dev-entry']
    finally:
        subprocess.run(['hdiutil', 'detach', device], check=True)


def prepare(tree, source, output, config):
    if os.geteuid() != 0:
        raise ValueError('Run as root to preserve original uid/gid and modes')
    if output.exists():
        raise ValueError('Refuse to overwrite an existing RAM Data seed')
    with source.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != '3f99b859c9728379110b66657c7b15285bcb1925ad8b5726542e2cdcf8b1028d':
            raise ValueError('OS input hash mismatch')
    output.mkdir(parents=True)
    image = output / 'data.cdr'
    # shortcut: 256 MiB volatile Data for bring-up; qualify persistent storage separately.
    subprocess.run(['hdiutil', 'create', '-size', '256m', '-layout', 'NONE', '-fs', 'APFS',
                    '-volname', 'OwnerData', '-type', 'UDTO', str(image)], check=True)
    original, target = output / 'os', output / 'data'
    count = total = 0
    with mounted(source, original, readonly=True):
        if hashlib.sha256((original / 'sbin/launchd').read_bytes()).hexdigest() != '8cec9a3c44a443b08e977ccc5d577850316ad428c575dc01f09b018dbd5b6a25':
            raise ValueError('Original launchd identity mismatch')
        with mounted(image, target) as device:
            info = plistlib.loads(subprocess.check_output(['diskutil', 'info', '-plist', device]))
            identity = str(uuid.UUID(info['VolumeUUID'])).upper()
            source_var = original / 'private/var'
            for current, dirs, files in os.walk(source_var, followlinks=False):
                dirs[:] = [name for name in dirs if name != 'staged_system_apps']
                dest = target / Path(current).relative_to(source_var)
                dest.mkdir(exist_ok=True)
                for name in [None, *dirs, *files]:
                    src = Path(current) if name is None else Path(current) / name
                    dst = dest if name is None else dest / name
                    metadata = src.lstat()
                    if src.is_symlink():
                        os.symlink(os.readlink(src), dst)
                        if name in dirs:
                            dirs.remove(name)
                    elif src.is_dir():
                        dst.mkdir(exist_ok=True)
                    elif src.is_file():
                        shutil.copy2(src, dst)
                        count += 1
                        total += metadata.st_size
                    else:
                        raise ValueError(f'Unsupported seed file: {src}')
                    os.chown(dst, metadata.st_uid, metadata.st_gid, follow_symlinks=False)
                    if not src.is_symlink():
                        os.chmod(dst, stat.S_IMODE(metadata.st_mode))
                    actual = dst.lstat()
                    if (actual.st_uid, actual.st_gid, stat.S_IMODE(actual.st_mode)) != (
                            metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)):
                        raise ValueError(f'Seed ownership/mode mismatch: {src}')
            for name in ('keybags', 'mobile/tmp', 'tmp', 'run'):
                directory = target / name
                if not directory.exists():
                    directory.mkdir(parents=True)
                    parent = directory.parent.stat()
                    os.chown(directory, parent.st_uid, parent.st_gid)
            os.chmod(target / 'tmp', 0o1777)
            prepare_userspace(target)
            disabled_jobs = disable_unimplemented_watchdog(
                target, original / 'System/Library/LaunchDaemons/com.apple.watchdogd.plist')
    with image.open('rb') as stream:
        header = stream.read(4096)
    if image.stat().st_size != 256 * 1024**2 or header[32:36] != b'NXSB':
        raise ValueError('Unexpected APFS seed geometry')
    pack = runpy.run_path(str(tree / 'drivers/DarwinBoot/Test/packed_ramdisk.py'))['pack']
    packed = pack(image, output / 'data.dbrdisk')
    report = dict(volume_uuid=identity, packed=packed, source_regular_files=count,
                  source_regular_bytes=total, guest_mutable=True, persistent=False,
                  bringup_disabled_jobs=disabled_jobs,
                  mobilegestalt_cache_cleared=True, setup_skipped=False, auto_dim_disabled=True,
                  ownership_preserved=True, os_inputs_modified=False, hardware_tested=False)
    (output / 'seed.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = [line for line in config.read_text().splitlines()
             if not line.startswith('CONFIG_XNU_OWNER_DATA_VOLUME_UUID=')]
    config.write_text('\n'.join([*lines, f'CONFIG_XNU_OWNER_DATA_VOLUME_UUID="{identity}"']) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    prepare(*(getattr(args, name).resolve() for name in ('tree', 'source', 'output', 'config')))
