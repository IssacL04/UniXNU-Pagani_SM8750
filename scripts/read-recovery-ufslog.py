#!/usr/bin/env python3
"""Read the unixnu log window through root recovery ADB; never write to the phone."""
import argparse
from pathlib import Path
import re
import shlex
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
LOG_BLOCKS = 8192


def shell(adb, command):
    result = subprocess.run([*adb, 'exec-out', 'sh', '-c', shlex.quote(command)],
                            capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace').strip() or 'ADB command failed')
    return result.stdout


def collect(adb, board, output, read=shell):
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    layout = tomllib.loads(board.read_text(encoding='utf-8'))['userdata']
    first, last, block = (layout[k] for k in ('first_lba', 'last_lba', 'lba_bytes'))
    if layout['partition'] != 'unixnu' or block != 4096 or last - first + 1 <= LOG_BLOCKS:
        raise ValueError('Unsupported board log geometry')
    if read(adb, 'id -u').strip() != b'0':
        raise ValueError('Root recovery ADB is required (no su commands are issued)')
    device = read(adb, 'readlink -f /dev/block/by-name/unixnu').decode().strip()
    if not re.fullmatch(r'/dev/block/sd[a-z]+[0-9]+', device):
        raise ValueError(f'Unexpected unixnu block path: {device}')
    start = int(read(adb, f'cat /sys/class/block/{Path(device).name}/start'))
    sectors = int(read(adb, f'blockdev --getsz {device}'))
    if start != first * 8 or sectors != (last - first + 1) * 8:
        raise ValueError('Live partition start/size differs from board.toml; no log read attempted')
    skip = last - first + 1 - LOG_BLOCKS
    data = read(adb, f'dd if={device} bs=4096 skip={skip} count={LOG_BLOCKS} 2>/dev/null')
    if len(data) != LOG_BLOCKS * block:
        raise ValueError(f'Short log read: {len(data)} bytes')
    with output.open('xb') as stream:
        stream.write(data)
    kind = 'PGLOG001 (decode and check CRC next)' if data.startswith(b'PGLOG001') else 'blank' if not any(data) else 'unrecognized content'
    return kind


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True, help='explicit recovery ADB serial')
    parser.add_argument('--adb', default='adb', help='adb executable, also accepts adb.exe')
    parser.add_argument('--board', type=Path, default=ROOT / 'board.toml')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    kind = collect([args.adb, '-s', args.serial], args.board, args.output)
    print(f'{args.output}: 32 MiB, {kind}; phone read only')


if __name__ == '__main__':
    main()
