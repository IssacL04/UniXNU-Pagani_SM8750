#!/usr/bin/env python3
"""Exercise root, geometry, byte-count and output guards without a phone."""
import importlib.util
from pathlib import Path
import tempfile

spec = importlib.util.spec_from_file_location('reader', Path(__file__).with_name('read-recovery-ufslog.py'))
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class Recovery:
    uid = b'0'
    start = b'359430144'
    size = b'134217728'
    payload = bytes(8192 * 4096)

    def __init__(self):
        self.commands = []

    def read(self, adb, command):
        assert adb == ['adb', '-s', 'test-device']
        assert 'of=' not in command and 'su ' not in command
        self.commands.append(command)
        return {'id -u': self.uid,
                'readlink -f /dev/block/by-name/unixnu': b'/dev/block/sda16',
                'cat /sys/class/block/sda16/start': self.start,
                'blockdev --getsz /dev/block/sda16': self.size,
                'dd if=/dev/block/sda16 bs=4096 skip=16769024 count=8192 2>/dev/null': self.payload}[command]


with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / 'window.bin'
    adb = ['adb', '-s', 'test-device']
    board = reader.ROOT / 'board.toml'
    for field, value in [('uid', b'2000'), ('start', b'1'), ('size', b'1'), ('payload', b'short')]:
        model = Recovery()
        setattr(model, field, value)
        try:
            reader.collect(adb, board, out, model.read)
            raise AssertionError('Invalid recovery response accepted')
        except ValueError:
            assert not out.exists()
            if field != 'payload':
                assert not any(c.startswith('dd ') for c in model.commands)
    model = Recovery()
    assert reader.collect(adb, board, out, model.read) == 'blank'
    assert out.read_bytes() == model.payload
    model.commands.clear()
    try:
        reader.collect(adb, board, out, model.read)
        raise AssertionError('Existing capture overwritten')
    except ValueError:
        assert not model.commands
    out.unlink()
    model.payload = b'PGLOG001\x00\xff\r\n' + bytes(8192 * 4096 - 12)
    assert reader.collect(adb, board, out, model.read).startswith('PGLOG001')
    assert out.read_bytes() == model.payload
print('PASS: recovery root, live geometry, short reads, binary output and overwrite protection')
