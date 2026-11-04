#!/usr/bin/env python3
"""patches/xnu/phone-app-exec-count.patch: pagani_app_execs, one more at every exec of an app or extension bundle, what the launch boost of the
CPU governor begins on (PaganiArmCpu CpuFreqGovernor.h). The patch's condition runs in a host harness on the exec path as excpath has it, on
the paths the logs show: every app and extension counts, a daemon does not, also one with "com.apple." in its name.
With --xnu <tree> (an XNU checkout without this patch; only read) the patch goes on a copy of kern_exec.c, where the count has to come before the
function frees the strings: run 20261101-053955 panicked at the first exec, strnstr on the NULL that process_signature finds there.
With --inputs <xnu-inputs.json> (of a kernel build) the whole series as this checkout has it now goes on a fresh clone in order, with
phone-checkdirs-kernproc.patch and this patch last where the series lacks them, with git apply as the build does.
Run: python3 scripts/test-app-exec-count-patch.py [--xnu <tree>] [--inputs <xnu-inputs.json>]"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PATCHES = Path(__file__).resolve().parents[1] / 'patches/xnu'
PATCH = PATCHES / 'phone-app-exec-count.patch'
NEW = ['phone-checkdirs-kernproc.patch', 'phone-app-exec-count.patch']
XNU = None
INPUTS = None

COUNTS = ['/Applications/Preferences.app/Preferences', '/Applications/MobileNotes.app/MobileNotes',
          '/private/var/containers/Bundle/Application/5E0B1C5A-6E44-4A1B-8A7D-3B1C0D2E9F10/Foo.app/Foo',
          '/private/var/staged_system_apps/Health.app/Health', '/System/Library/CoreServices/SpringBoard.app/SpringBoard',
          '/Applications/Stocks.app/PlugIns/StocksWidget.appex/StocksWidget',
          '/System/Library/ExtensionKit/Extensions/NetworkingExtension.appex/com.apple.WebKit.Networking',
          '/System/Library/PrivateFrameworks/CoreSuggestionsUI.framework/PlugIns/AegirPoster.appex/AegirPoster',
          '/System/Library/PrivateFrameworks/IDS.framework/identityservicesd.app/identityservicesd']
LEAVES = ['/usr/libexec/xpcproxy', '/usr/bin/powerlogHelperd', '/usr/libexec/PerfPowerServices', '/usr/libexec/mediasetupd',
          '/System/Library/PrivateFrameworks/MobileBackup.framework/backupd', '/usr/libexec/com.apple.sbd', '/usr/sbin/com.apple.foo',
          '/System/Library/PrivateFrameworks/DataMigration.framework/XPCServices/com.apple.datamigrator.xpc/com.apple.datamigrator',
          '/System/Library/Frameworks/ImageCaptureCore.framework/XPCServices/mscamerad-xpc.xpc/mscamerad-xpc']


def added(text):
    return '\n'.join(line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++'))


class AppExecCountPatchTest(unittest.TestCase):
    def setUp(self):
        self.text = PATCH.read_text()
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_adds_only_to_kern_exec(self):
        self.assertEqual(re.findall(r'^\+\+\+ b/(\S+)', self.text, re.M), ['bsd/kern/kern_exec.c'])
        self.assertEqual([line for line in self.text.splitlines() if line.startswith('-') and not line.startswith('---')], [])

    def test_counts_on_a_successful_activation(self):
        hunk = self.text[self.text.index('} else if (error == 0) {'):]
        self.assertIn('if (strnstr(excpath, ".app/", MAXPATHLEN) != NULL', hunk)
        self.assertNotIn('ip_strings', added(self.text).replace('imgp->ip_strings set to NULL', ''))

    def test_the_condition(self):
        condition = re.search(r'if \((strnstr\(excpath.*?)\) \{', added(self.text), re.S).group(1)
        source = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define MAXPATHLEN 1024
#define EXECUTABLE_KEY "executable_path="
static int counts(const char *path)
{
	char strings[2 * MAXPATHLEN];
	const char *excpath = strings + strlen(EXECUTABLE_KEY);
	int length = snprintf(strings, sizeof(strings), EXECUTABLE_KEY "%s", path);
	/* The arguments follow the path's NUL: one naming a bundle is no bundle exec'd. */
	snprintf(strings + length + 1, sizeof(strings) - length - 1, "/Applications/Preferences.app/Preferences");
	return (''' + condition + r''') ? 1 : 0;
}
int main(int argc, char **argv)
{
	for (int i = 2; i < argc; i++) {
		if (counts(argv[i]) != atoi(argv[1])) { printf("%s\n", argv[i]); return 1; }
	}
	return 0;
}
'''
        binary = Path(self.temp.name) / 'harness'
        subprocess.run(['xcrun', 'clang', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-x', 'c', '-', '-o', str(binary)], input=source, text=True, check=True)
        for expected, paths in (('1', COUNTS), ('0', LEAVES)):
            result = subprocess.run([str(binary), expected] + paths, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_applies_to_tree(self):
        if XNU is None:
            self.skipTest('no --xnu tree given')
        root = Path(self.temp.name) / 'xnu'
        (root / 'bsd/kern').mkdir(parents=True)
        shutil.copyfile(Path(XNU) / 'bsd/kern/kern_exec.c', root / 'bsd/kern/kern_exec.c')
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        subprocess.run(['git', 'apply', str(PATCH)], cwd=root, check=True)
        source = (root / 'bsd/kern/kern_exec.c').read_text()
        # The strings live until the end of exec_activate_image: execargs_free sets ip_strings to NULL there, on every path.
        activate = source[source.index('\nexec_activate_image(struct image_params *imgp)\n'):]
        activate = activate[:activate.index('\n}\n')]
        self.assertLess(activate.index('} else if (error == 0) {'), activate.index('OSIncrementAtomic(&pagani_app_execs)'))
        self.assertLess(activate.index('OSIncrementAtomic(&pagani_app_execs)'), activate.index('\nbad:\n'))
        self.assertLess(activate.index('\nbad_notrans:\n'), activate.index('execargs_free(imgp);'))
        free = source[source.index('\nexecargs_free(struct image_params *imgp)\n'):]
        self.assertIn('imgp->ip_strings = NULL;', free[:free.index('\n}\n')])
        signature = source[source.index('\nprocess_signature(proc_t p, struct image_params *imgp)\n'):]
        self.assertNotIn('ip_strings', signature[:signature.index('\n}\n')])

    def test_what_the_condition_rests_on(self):
        if XNU is None:
            self.skipTest('no --xnu tree given')
        source = (Path(XNU) / 'bsd/kern/kern_exec.c').read_text()
        # excpath is what ip_strings holds after the key, and the old path is wiped: a cached buffer leaves no bundle of the last exec.
        save = source[source.index('exec_save_path(struct image_params *imgp, user_addr_t path'):]
        save = save[:save.index('\n}\n')]
        self.assertIn("memset(imgp->ip_strings, '\\0', strlen(EXECUTABLE_KEY) + MAXPATHLEN);", save)
        self.assertIn('bcopy(EXECUTABLE_KEY, imgp->ip_strings, strlen(EXECUTABLE_KEY));', save)
        self.assertIn('*excpath = imgp->ip_strings + strlen(EXECUTABLE_KEY);', save)
        # XNU's strnstr ends at a NUL as the host's does: the harness's arguments after the path say what the phone's do.
        strings = (Path(XNU) / 'osfmk/device/subrs.c').read_text()
        strnstr = strings[strings.index('strnstr_impl(const char *s'):]
        self.assertIn("if ((sc = *s++) == '\\0' || slen-- < 1) {", strnstr[:strnstr.index('\n}\n')])

    def test_series_applies_in_order(self):
        if INPUTS is None:
            self.skipTest('no --inputs xnu-inputs.json given')
        inputs = json.loads(Path(INPUTS).read_text())
        before = [Path(patch['path']) for patch in inputs['patches'] if Path(patch['path']).parent != PATCHES]
        series = [line.strip() for line in (PATCHES / 'series').read_text().splitlines()]
        patches = before + [PATCHES / name for name in series if name and not name.startswith('#')]
        patches += [PATCHES / name for name in NEW if PATCHES / name not in patches]
        root = Path(self.temp.name) / 'clone'
        subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', inputs['source'], str(root)], check=True)
        subprocess.run(['git', '-C', str(root), 'checkout', '--quiet', '--detach', inputs['commit']], check=True)
        for patch in patches:
            result = subprocess.run(['git', '-C', str(root), 'apply', str(patch)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f'{patch.name}: {result.stderr[-400:]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--xnu')
    parser.add_argument('--inputs')
    args, rest = parser.parse_known_args()
    XNU = args.xnu
    INPUTS = args.inputs
    unittest.main(argv=[sys.argv[0]] + rest)
