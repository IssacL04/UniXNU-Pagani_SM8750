#!/usr/bin/env python3
"""Exercise isolated preparation and cache reuse against a local Git fixture."""
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path

DEVICE = Path(__file__).resolve().parents[1]
prepare = runpy.run_path(str(DEVICE / 'unixnu'))['prepare']


class UpstreamTest(unittest.TestCase):
    def test_patch_isolation_reuse_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, device = root / 'source', root / 'device'
            source.mkdir()
            (device / 'patches').mkdir(parents=True)
            def git(*args, repo=source):
                return subprocess.check_output(['git', *args], cwd=repo, text=True)
            git('init', '-q')
            (source / 'input').write_text('upstream\n')
            ufs_source = root / 'ufs-source'
            ufs_source.mkdir()
            git('init', '-q', repo=ufs_source)
            (ufs_source / 'fixture').write_text('ufs\n')
            git('add', '.', repo=ufs_source)
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'UFS fixture', repo=ufs_source)
            git('-c', 'protocol.file.allow=always', 'submodule', 'add', str(ufs_source), 'drivers/NativeUfs')
            git('-c', 'protocol.file.allow=always', 'submodule', 'add', str(ufs_source), 'drivers/NativeMobileDisplay')
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Fixture')
            (device / 'upstream.rev').write_text(git('rev-parse', 'HEAD'))
            (source / 'input').write_text('board\n')
            patch = device / 'patches/unixnu-source-kernel.patch'
            patch.write_text(git('diff'))
            git('restore', 'input')
            prepared = prepare(device, source)
            self.assertEqual((prepared / 'input').read_text(), 'board\n')
            self.assertEqual((source / 'input').read_text(), 'upstream\n')
            self.assertEqual(git('status', '--porcelain'), '')
            (prepared / 'input').write_text('local work\n')
            self.assertEqual(prepare(device, source), prepared)
            self.assertEqual((prepared / 'input').read_text(), 'local work\n')
            (source / 'drivers/NativeUfs/fixture').write_text('sm8750\n')
            ufs_patch = device / 'patches/native-ufs-sm8750.patch'
            ufs_patch.write_text(git('diff', repo=source / 'drivers/NativeUfs'))
            git('restore', 'fixture', repo=source / 'drivers/NativeUfs')
            with_ufs = prepare(device, source)
            self.assertNotEqual(with_ufs, prepared)
            self.assertEqual((with_ufs / 'drivers/NativeUfs/fixture').read_text(), 'sm8750\n')
            self.assertEqual((source / 'drivers/NativeUfs/fixture').read_text(), 'ufs\n')
            self.assertEqual((prepared / 'input').read_text(), 'local work\n')
            display = source / 'drivers/NativeMobileDisplay'
            (display / 'fixture').write_text('display refresh\n')
            (device / 'patches/native-mobile-display-stage7.patch').write_text(git('diff', repo=display))
            git('restore', 'fixture', repo=display)
            with_display = prepare(device, source)
            self.assertNotEqual(with_display, with_ufs)
            self.assertEqual((with_display / 'drivers/NativeMobileDisplay/fixture').read_text(), 'display refresh\n')
            self.assertEqual((display / 'fixture').read_text(), 'ufs\n')
            self.assertEqual((with_display / 'drivers/NativeUfs/fixture').read_text(), 'sm8750\n')
            patch.write_text('invalid patch\n')
            with self.assertRaises(subprocess.CalledProcessError):
                prepare(device, source)
            self.assertEqual(set((device / '.cache').iterdir()), {prepared, with_ufs, with_display})
            self.assertEqual((source / 'input').read_text(), 'upstream\n')

    def test_board_enables_upstream_archive_builders(self):
        self.assertIn('CONFIG_XNU_BUILD_ARCHIVES=y', (DEVICE / 'configs/oneplus13t_defconfig').read_text())


if __name__ == '__main__':
    unittest.main()
