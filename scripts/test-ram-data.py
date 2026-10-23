#!/usr/bin/env python3
"""Check the narrowly scoped launch policy and refusal to replace existing data."""
from pathlib import Path
import plistlib
import runpy
import tempfile
import unittest

disable = runpy.run_path(str(Path(__file__).with_name('prepare-ram-data.py')))[
    'disable_unimplemented_watchdog']


class RamDataPolicyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.daemon = self.root / 'watchdog.plist'
        self.original = plistlib.dumps(dict(
            Label='com.apple.watchdogd', ProgramArguments=['/usr/libexec/watchdogd'],
            _PanicOnCrash=dict(PanicOnConsecutiveCrash=True)))
        self.daemon.write_bytes(self.original)

    def test_only_watchdog_disabled_and_original_unchanged(self):
        self.assertEqual(disable(self.root, self.daemon), ['com.apple.watchdogd'])
        folder = self.root / 'db/com.apple.xpc.launchd'
        for name, expected in (('disabled.plist', plistlib.dumps({'com.apple.watchdogd': True})),
                               ('disabled.migrated', b'')):
            path = folder / name
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.daemon.read_bytes(), self.original)
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            disable(self.root, self.daemon)

    def test_reject_symlink_before_writing(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'db').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            disable(self.root, self.daemon)
        self.assertEqual(list(outside.iterdir()), [])

    def test_reject_unexpected_original(self):
        self.daemon.write_bytes(plistlib.dumps({'Label': 'another.service'}))
        with self.assertRaisesRegex(ValueError, 'original'):
            disable(self.root, self.daemon)
        self.assertFalse((self.root / 'db').exists())


if __name__ == '__main__':
    unittest.main()
