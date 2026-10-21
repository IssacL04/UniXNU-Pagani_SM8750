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
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=source, text=True)
            git('init', '-q')
            (source / 'input').write_text('upstream\n')
            git('add', 'input')
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
            patch.write_text('invalid patch\n')
            with self.assertRaises(subprocess.CalledProcessError):
                prepare(device, source)
            self.assertEqual(list((device / '.cache').iterdir()), [prepared])
            self.assertEqual((source / 'input').read_text(), 'upstream\n')

    def test_board_enables_upstream_archive_builders(self):
        self.assertIn('CONFIG_XNU_BUILD_ARCHIVES=y', (DEVICE / 'configs/oneplus13t_defconfig').read_text())


if __name__ == '__main__':
    unittest.main()
