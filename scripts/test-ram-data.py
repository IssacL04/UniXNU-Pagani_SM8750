#!/usr/bin/env python3
"""Check the narrowly scoped launch policy and refusal to replace existing data."""
from pathlib import Path
import plistlib
import runpy
import tempfile
import unittest

module = runpy.run_path(str(Path(__file__).with_name('prepare-ram-data.py')))
disable = module['prepare_launch_policy']
prepare_userspace = module['prepare_userspace']


class RamDataPolicyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.daemons = self.root / 'LaunchDaemons'
        self.daemons.mkdir()
        self.original = {}
        for label, arguments in module['DISABLED_JOBS'].items():
            job = dict(Label=label, ProgramArguments=arguments)
            if label == 'com.apple.watchdogd':
                job['_PanicOnCrash'] = dict(PanicOnConsecutiveCrash=True)
            self.original[label] = plistlib.dumps(job)
            (self.daemons / (label + '.plist')).write_bytes(self.original[label])

    def test_only_qualified_jobs_disabled_and_original_unchanged(self):
        labels = {'com.apple.watchdogd', 'com.apple.identityservicesd', 'com.apple.locationd',
                  'com.apple.CommCenter', 'com.apple.bluetoothd', 'com.apple.PerfPowerServices',
                  'com.apple.iomfb_fdr_loader', 'com.apple.iconservices.iconservicesagent'}
        self.assertEqual(set(disable(self.root, self.daemons)), labels)
        folder = self.root / 'db/com.apple.xpc.launchd'
        for name, expected in (('disabled.plist', plistlib.dumps(dict.fromkeys(labels, True))),
                               ('disabled.migrated', b'')):
            path = folder / name
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        for label, data in self.original.items():
            self.assertEqual((self.daemons / (label + '.plist')).read_bytes(), data)
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            disable(self.root, self.daemons)

    def test_reject_symlink_before_writing(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'db').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            disable(self.root, self.daemons)
        self.assertEqual(list(outside.iterdir()), [])

    def test_reject_unexpected_original(self):
        (self.daemons / 'com.apple.locationd.plist').write_bytes(plistlib.dumps({'Label': 'another.service'}))
        with self.assertRaisesRegex(ValueError, 'original'):
            disable(self.root, self.daemons)
        self.assertFalse((self.root / 'db').exists())

    def test_userspace_skips_setup_and_preserves_unrelated_preferences(self):
        preferences = self.root / 'mobile/Library/Preferences'
        preferences.mkdir(parents=True)
        setup = preferences / 'com.apple.purplebuddy.plist'
        original = plistlib.dumps({'SetupDone': False, 'ExistingPreference': 9})
        setup.write_bytes(original)
        springboard = preferences / 'com.apple.springboard.plist'
        springboard.write_bytes(plistlib.dumps({'ExistingPreference': 7}))
        cache = preferences / 'com.apple.MobileGestalt.plist'
        cache.write_bytes(plistlib.dumps({'DeviceClass': 'iPod'}))
        prepare_userspace(self.root)
        values = plistlib.loads(setup.read_bytes())
        self.assertTrue(values['SetupDone'] and values['SetupFinishedAllSteps'])
        self.assertEqual(values['SetupVersion'], 11)
        self.assertFalse(values['daemonizeNeedsToRun'])
        self.assertEqual(values['ExistingPreference'], 9)
        mini = plistlib.loads((preferences / 'com.apple.purplebuddy.notbackedup.plist').read_bytes())
        self.assertEqual(len(mini), 7)
        self.assertTrue(all(value is False for value in mini.values()))
        managed = plistlib.loads((preferences / 'com.apple.managedconfiguration.notbackedup.plist').read_bytes())
        self.assertFalse(managed['LockdownActivationIndicatesCloudConfigurationAvailable'])
        self.assertFalse(cache.exists())
        values = plistlib.loads(springboard.read_bytes())
        self.assertEqual(values['ExistingPreference'], 7)
        self.assertTrue(values['SBDisableAutoDim'] and values['SBDisableIdleSleep'])
        self.assertTrue(values['SBDontDimOrLockOnAC'] and values['BKNoWatchdogs'])
        self.assertEqual(values['FBLaunchWatchdogExceptions'], {'com.apple.purplebuddy': 100.0})
        self.assertFalse(values['MCForceShowCloudConfigurationUI'])
        self.assertEqual(springboard.stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.root / 'containers/Shared/SystemGroup').is_dir())
        migration = plistlib.loads((preferences / 'com.apple.migration.plist').read_bytes())
        self.assertEqual(migration['LastSystemVersion'], '21H461')
        self.assertEqual(migration['DMUserDataDisposition']['buildVersion'], '21H461')
        self.assertFalse(migration['DMUserDataDisposition']['SyntheticDidUpgrade'])
        owner = (self.root / 'mobile').stat()
        for path in preferences.glob('*.plist'):
            self.assertEqual((path.stat().st_uid, path.stat().st_gid), (owner.st_uid, owner.st_gid))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        before = {path.name: path.read_bytes() for path in preferences.glob('*.plist')}
        prepare_userspace(self.root)
        self.assertEqual({path.name: path.read_bytes() for path in preferences.glob('*.plist')}, before)

    def test_compatibility_checks_original_bytes(self):
        for volume, relative, offset, original in module['COMPAT_FIXUPS']:
            path = self.root / volume / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('r+b' if path.exists() else 'wb') as stream:
                stream.seek(offset)
                stream.write(bytes.fromhex(original))
        verify = module['verify_userspace_compat']
        verify(self.root / 'os', self.root / 'system')
        with path.open('r+b') as stream:
            stream.seek(offset)
            stream.write(b'\0')
        with self.assertRaisesRegex(ValueError, 'instructions'):
            verify(self.root / 'os', self.root / 'system')


if __name__ == '__main__':
    unittest.main()
