#!/usr/bin/env python3
"""Check legacy and modern boot containers, corrupted handoffs and stock DTB bundles."""
import gzip
import os
import struct
import tempfile
import unittest
from pathlib import Path

from unixnu.bootimg import DEFAULTS, compile_shim, split_dtb, verify
from unixnu.util import Error, tool


class BootImageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ramdisk = self.root / 'ramdisk'
        self.ramdisk.write_bytes(b'configuration volume')
        self.firmware = b'firmware and shim' * 400
        self.tree = struct.pack('>10I', 0xd00dfeed, 40, 40, 40, 40, 17, 16, 0, 0, 0)

    def fixture(self, version, ramdisk=None):
        ramdisk = self.ramdisk.read_bytes() if ramdisk is None else ramdisk
        kernel = gzip.compress(self.firmware, mtime=0) + self.tree
        header = bytearray(4096)
        header[:8] = b'ANDROID!'
        if version >= 3:
            struct.pack_into('<4I', header, 8, len(kernel), len(ramdisk), 0, 1584 if version == 4 else 1580)
            struct.pack_into('<I', header, 40, version)
            if version == 4:
                struct.pack_into('<I', header, 1580, 4096)
        else:
            struct.pack_into('<10I', header, 8, len(kernel), DEFAULTS['kernel_offset'], len(ramdisk),
                             0, 0, 0, DEFAULTS['tags_offset'], 4096, version, 0)
        pad = lambda value: value + bytes(-len(value) % 4096)
        path = self.root / 'boot.img'
        path.write_bytes(bytes(header) + pad(kernel) + pad(ramdisk) + (bytes(4096) if version == 4 else b''))
        return path, dict(DEFAULTS, header_version=version)

    def test_supported_headers(self):
        for version in range(5):
            with self.subTest(version=version):
                path, image = self.fixture(version)
                report = verify(path, self.firmware, self.tree, self.ramdisk, image)
                self.assertEqual(report['header_version'], version)
                self.assertEqual('kernel_address' in report, version < 3)

    def test_empty_ramdisk(self):
        self.ramdisk.write_bytes(b'')
        for version in (0, 3, 4):
            path, image = self.fixture(version)
            self.assertEqual(verify(path, self.firmware, self.tree, self.ramdisk, image)['ramdisk_bytes'], 0)

    def test_embedded_payload_container(self):
        self.firmware += b'embedded FAT payload' * 4096
        self.ramdisk.write_bytes(b'')
        path, image = self.fixture(4)
        self.assertEqual(verify(path, self.firmware, self.tree, self.ramdisk, image)['ramdisk_bytes'], 0)
        with self.assertRaises(Error):
            verify(path, self.firmware[:-1], self.tree, self.ramdisk, image)

    def test_real_shim_payload_header(self):
        uefi = Path(os.environ.get('UNIXNU_UEFI', Path(__file__).resolve().parents[2] / 'UEFI-Pagani_SM8750'))
        if not (uefi / 'BootShim/BootShim.S').is_file():
            self.skipTest('local Mu-Silicium checkout not present')
        try:
            for name in ('clang', 'llvm-objcopy', 'llvm-nm'):
                tool(name)
        except Error as error:
            self.skipTest(str(error))
        for payload_size in (0, 64 * 1024 * 1024):
            shim = compile_shim(uefi, 0xA7100000, 0x300000, True, self.root, payload_size)
            self.assertEqual(struct.unpack_from('<QQ', shim, 8),
                             (0xA7100000, len(shim) + 0x300000 + payload_size))
            if payload_size:
                self.assertIn(struct.pack('<Q', 0x554E49584E55504C), shim)

    def test_bad_modern_headers(self):
        for offset, value in ((20, 1580), (24, 1), (40, 5), (1580, 8192), (8, 0xffffffff)):
            with self.subTest(offset=offset):
                path, image = self.fixture(4)
                data = bytearray(path.read_bytes())
                struct.pack_into('<I', data, offset, value)
                path.write_bytes(data)
                with self.assertRaises(Error):
                    verify(path, self.firmware, self.tree, self.ramdisk, image)

    def test_truncation_and_extra_bytes(self):
        path, image = self.fixture(4)
        data = path.read_bytes()
        for broken in (b'', data[:43], data[:4096], data[:-1], data + b'extra'):
            path.write_bytes(broken)
            with self.assertRaises(Error):
                verify(path, self.firmware, self.tree, self.ramdisk, image)

    def test_wrong_addresses_and_page(self):
        path, image = self.fixture(0)
        for key in ('base', 'pagesize'):
            with self.assertRaises(Error):
                verify(path, self.firmware, self.tree, self.ramdisk, {**image, key: 8192})
        path, image = self.fixture(4)
        with self.assertRaises(Error):
            verify(path, self.firmware, self.tree, self.ramdisk, {**image, 'pagesize': 8192})

    def test_corrupted_gzip_and_handoff(self):
        path, image = self.fixture(4)
        for firmware, tree in ((b'wrong', self.tree), (self.firmware, b'wrong')):
            with self.assertRaises(Error):
                verify(path, firmware, tree, self.ramdisk, image)
        self.ramdisk.write_bytes(b'changed')
        with self.assertRaises(Error):
            verify(path, self.firmware, self.tree, self.ramdisk, image)
        data = bytearray(path.read_bytes())
        data[4096] ^= 0xff
        path.write_bytes(data)
        with self.assertRaises(Error):
            verify(path, self.firmware, self.tree, self.ramdisk, image)

    def test_stock_dtb_bundle(self):
        self.assertEqual(split_dtb(self.tree * 3), [self.tree] * 3)
        for data in (b'', self.tree[:39], self.tree + b'padding', self.tree + self.tree[:39]):
            with self.assertRaises(Error):
                split_dtb(data)
        for size in (0, 39, 41, 0xffffffff):
            data = bytearray(self.tree)
            struct.pack_into('>I', data, 4, size)
            with self.assertRaises(Error):
                split_dtb(data)


if __name__ == '__main__':
    unittest.main()
