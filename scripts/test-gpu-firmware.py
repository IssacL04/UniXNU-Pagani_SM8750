#!/usr/bin/env python3
"""Check firmware pin enforcement without committing vendor bytes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import struct

SPEC = importlib.util.spec_from_file_location('gpu_firmware', Path(__file__).with_name('prepare-gpu-firmware.py'))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FirmwareTests(unittest.TestCase):
    def zap(self):
        data = bytearray(640)
        data[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<HHI', data, 16, 2, 164, 1)
        struct.pack_into('<I', data, 28, 52)
        struct.pack_into('<HH', data, 42, 32, 3)
        struct.pack_into('<8I', data, 52, 0, 0, 0, 0, 148, 0, 0x7000000, 0)
        struct.pack_into('<8I', data, 84, 1, 256, 4096, 4096, 64, 128, 0x8000007, 4096)
        struct.pack_into('<8I', data, 116, 0, 512, 0, 0, 128, 128, 0x2000000, 4096)
        data[256:320] = b'P' * 64
        data[512:640] = b'H' * 128
        return data

    def test_zap(self):
        original = self.zap()
        meta, load = MODULE.zap_parts(original)
        self.assertEqual(meta, original[:148] + b'H' * 128)
        self.assertEqual(load, b'P' * 64 + bytes(4096 - 64))
        for offset, value in ((28, 0xffff), (100, 129), (96, 0xfffff800), (108, 7), (120, 600)):
            data = bytearray(original)
            struct.pack_into('<I', data, offset, value)
            with self.assertRaises(ValueError):
                MODULE.zap_parts(data)

    def test_pin_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'inputs'
            source.mkdir()
            pins = {}
            for index, (_, name) in enumerate(MODULE.FILES):
                data = self.zap() if name.endswith('.mbn') else bytes([index]) * (128 + index)
                (source / name).write_bytes(data)
                pins[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            MODULE.PINS = root / 'pins.json'
            MODULE.PINS.write_text(json.dumps({'firmware': {'files': pins}}))
            for _, name in MODULE.FILES:
                path = source / name
                data = path.read_bytes()
                for bad in (data[:-1], bytes([data[0] ^ 1]) + data[1:]):
                    path.write_bytes(bad)
                    with self.assertRaises(ValueError):
                        MODULE.prepare(source, root / 'rejected')
                    self.assertFalse((root / 'rejected').exists())
                path.write_bytes(data)
            output = root / 'accepted'
            MODULE.prepare(source, output)
            for symbol, name in MODULE.FILES:
                self.assertEqual((source / name).read_bytes(), (output / name).read_bytes())
                self.assertIn('_sm8750_gpu_' + symbol + ':', (output / 'firmware.S').read_text())


if __name__ == '__main__':
    unittest.main()
