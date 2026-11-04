#!/usr/bin/env python3
"""patches/xnu/phone-shutdown-progress.patch: every step of a shutdown's unmounts as a record of the boot log. The patch adds only; kern_exec.c, built
with the log on, is where the call to boot_progress_root lives, vfs_subr.c, built without (scripts/build-xnu-4k-baseline.sh, its list of objects the
second pass rebuilds, must keep that true), only calls that function: the macro in vfs_subr.c would compile to nothing and no test of a host would know.
With --inputs <xnu-inputs.json> (of a kernel build) the whole series as this checkout has it goes on a fresh clone with git apply as the build does, and
the three lines must stand around dounmount in unmount_callback.
Run: python3 scripts/test-shutdown-progress-patch.py [--inputs <xnu-inputs.json>]"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHES = ROOT / 'patches/xnu'
PATCH = PATCHES / 'phone-shutdown-progress.patch'
BASELINE = ROOT.parent / 'UniXNU/scripts/build-xnu-4k-baseline.sh'
INPUTS = None


class ShutdownProgressPatchTest(unittest.TestCase):
    def setUp(self):
        self.text = PATCH.read_text()

    def test_adds_only(self):
        self.assertEqual(re.findall(r'^\+\+\+ b/(\S+)', self.text, re.M), ['bsd/kern/kern_exec.c', 'bsd/vfs/vfs_subr.c'])
        self.assertEqual([line for line in self.text.splitlines() if line.startswith('-') and not line.startswith('---')], [])

    def test_the_log_call_is_in_an_object_built_with_the_log_on(self):
        vfs = self.text[self.text.index('+++ b/bsd/vfs/vfs_subr.c'):]
        self.assertNotIn('boot_progress_root', vfs)
        self.assertNotIn('early_boot_progress.h', vfs)
        baseline = BASELINE.read_text()
        rebuilt = re.search(r"\('bsd', \[(.*?)\]\)", baseline).group(1)
        self.assertIn("'kern_exec'", rebuilt)
        self.assertNotIn("'vfs_subr'", rebuilt)

    def test_on_the_tree(self):
        if INPUTS is None:
            self.skipTest('no --inputs xnu-inputs.json given')
        inputs = json.loads(Path(INPUTS).read_text())
        before = [Path(patch['path']) for patch in inputs['patches'] if Path(patch['path']).parent != PATCHES]
        series = [line.strip() for line in (PATCHES / 'series').read_text().splitlines()]
        patches = before + [PATCHES / name for name in series if name and not name.startswith('#')]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'clone'
            subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', inputs['source'], str(root)], check=True)
            subprocess.run(['git', '-C', str(root), 'checkout', '--quiet', '--detach', inputs['commit']], check=True)
            for patch in patches:
                result = subprocess.run(['git', '-C', str(root), 'apply', str(patch)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, f'{patch.name}: {result.stderr[-400:]}')
            source = (root / 'bsd/vfs/vfs_subr.c').read_text()
            callback = source[source.index('\nunmount_callback(mount_t mp, void *arg)\n'):]
            callback = callback[:callback.index('\n}\n')]
            self.assertLess(callback.index('"unmount enter"'), callback.index('dounmount(mp, MNT_FORCE, 1, vfs_context_current());'))
            self.assertLess(callback.index('dounmount(mp, MNT_FORCE, 1, vfs_context_current());'), callback.index('"unmount returned"'))
            self.assertLess(callback.index('"unmount skipped"'), callback.index('} else {'))
            # zfree comes after the last use of the name.
            self.assertLess(callback.index('"unmount returned"'), callback.index('zfree(ZV_NAMEI, mntname);'))
            exec_source = (root / 'bsd/kern/kern_exec.c').read_text()
            self.assertLess(exec_source.index('#include <kern/early_boot_progress.h>'), exec_source.index('pagani_shutdown_progress(const char *stage'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs')
    args, rest = parser.parse_known_args()
    INPUTS = args.inputs
    unittest.main(argv=[sys.argv[0]] + rest)
