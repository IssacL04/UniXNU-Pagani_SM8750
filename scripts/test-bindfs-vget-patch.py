#!/usr/bin/env python3
"""patches/xnu/phone-bindfs-vget.patch: file IDs for the bindfs view of the system apps. It touches only bindfs and the view's mount,
sits after phone-system-apps-view.patch in the series, and a boot view takes file IDs only when it asks for them (the system apps view)
unless pagani-bindfs-vget says otherwise. The patched bindfs_vget, the capability filter and the mount's decision run in a host harness
(stubbed VFS): every way through bindfs_vget ends with the right vnode or error, the iocounts and path buffers balanced; a mount without
BINDM_PATH_FROM_ID answers nothing and strips both capabilities as the pristine source does.
With --xnu <tree> (an XNU checkout with the earlier series applied; only read) the patch is also applied to a copy of the four files.
With --inputs <xnu-inputs.json> (of a kernel build, naming the XNU source, its commit and the patches before the device series) the whole
series as this checkout has it now goes on a fresh clone, in order, with git apply as the build does.
Run: python3 scripts/test-bindfs-vget-patch.py [--xnu <tree>] [--inputs <xnu-inputs.json>]"""
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
PATCH = PATCHES / 'phone-bindfs-vget.patch'
FILES = ['bsd/kern/kern_exec.c', 'bsd/miscfs/bindfs/bind_vfsops.c', 'bsd/miscfs/bindfs/bind_vnops.c', 'bsd/miscfs/bindfs/bindfs.h']
XNU = None
INPUTS = None

HARNESS_HEAD = r'''
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/param.h>
#include <sys/types.h>

struct vnode { int iocount; int refused; const char *path; int path_error; };
typedef struct vnode *vnode_t;
struct mount { uint64_t mnt_kern_flag; };
typedef int *vfs_context_t;
#define NULLVP ((vnode_t)0)
#define MNTK_PATH_FROM_ID 0x00010000
#define BINDM_FORCE_ROOT 0x80000000ULL
#define BINDM_PATH_FROM_ID 0x40000000ULL
#define BIND_ROOT_INO 2
#define VNODE_LOOKUP_NOFOLLOW 1
#define VNODE_LOOKUP_NOCROSSMOUNT 2
#define ZV_NAMEI 0
#define os_atomic_inc(p, order) (++*(p))
#define VOL_CAPABILITIES_FORMAT 0
#define VOL_CAP_FMT_PERSISTENTOBJECTIDS 0x00000001
#define VOL_CAP_FMT_PATH_FROM_ID 0x00004000

struct bind_mount { vnode_t bindm_rootvp, bindm_lowerrootvp; uint64_t bindm_flags; };
static struct bind_mount *current;
#define MOUNTTOBINDMOUNT(mp) (current)

static struct vnode bindroot, bindchild, lowerroot, lowerfile, lowerother;
static int kernel_context, user_context, buffers, lookups, vgets;
static uint32_t native_bindfs_vget_calls, native_bindfs_vget_resolved;
static int native_bindfs_file_ids, native_bindfs_file_id_mounts, native_bindfs_boot_mount;
static long next_ino;
static vnode_t next_vnode;
static int next_vget_error, next_lookup_error, boot_arg_set;
static uint32_t boot_arg;
static char looked_up[MAXPATHLEN];
static int looked_flags;
static vfs_context_t looked_ctx;
static vnode_t looked_dvp;

static char *zalloc_stub(void) { buffers++; return malloc(MAXPATHLEN); }
static void zfree_stub(char *path) { buffers--; free(path); }
#define zalloc(zone) zalloc_stub()
#define zfree(zone, path) zfree_stub(path)
static vfs_context_t vfs_context_kernel(void) { return &kernel_context; }
static int vnode_get_stub(vnode_t vp) { if (vp->refused) return ENOENT; vp->iocount++; return 0; }
static int vnode_getwithref(vnode_t vp) { return vnode_get_stub(vp); }
static void vnode_put(vnode_t vp) { vp->iocount--; }
static struct mount lowermount;
static struct mount *vnode_mount(vnode_t vp) { (void)vp; return &lowermount; }
static int bindfs_root(struct mount *mp, vnode_t *vpp, vfs_context_t ctx)
{
	(void)mp; (void)ctx;
	if (vnode_get_stub(current->bindm_rootvp)) return ENOENT;
	*vpp = current->bindm_rootvp;
	return 0;
}
static int VFS_VGET(struct mount *mp, ino64_t ino, vnode_t *vpp, vfs_context_t ctx)
{
	(void)mp; (void)ctx;
	vgets++;
	if (next_vget_error) return next_vget_error;
	if ((long)ino != next_ino) return ENOENT;
	next_vnode->iocount++;
	*vpp = next_vnode;
	return 0;
}
static int vn_getpath_fsenter(vnode_t vp, char *path, int *len)
{
	if (vp->iocount < 1) abort();           /* build_path needs an iocount */
	if (vp->path_error) return vp->path_error;
	*len = (int)strlcpy(path, vp->path, (size_t)*len) + 1;
	return 0;
}
static int vnode_lookupat(const char *path, int flags, vnode_t *vpp, vfs_context_t ctx, vnode_t dvp)
{
	if (dvp->iocount < 1) abort();          /* the walk starts from a vnode the caller holds */
	lookups++;
	strlcpy(looked_up, path, sizeof(looked_up));
	looked_flags = flags;
	looked_ctx = ctx;
	looked_dvp = dvp;
	if (next_lookup_error) return next_lookup_error;
	bindchild.iocount++;
	*vpp = &bindchild;
	return 0;
}
static int PE_parse_boot_argn(const char *name, void *value, size_t size)
{
	if (strcmp(name, "pagani-bindfs-vget") || size != sizeof(uint32_t) || !boot_arg_set) return 0;
	memcpy(value, &boot_arg, size);
	return 1;
}
'''

HARNESS_MAIN = r'''
#define CHECK(condition) do { if (!(condition)) { printf("%s:%d: %s\n", __func__, __LINE__, #condition); failures++; } } while (0)
static int failures;

static void
balanced(vnode_t result)
{
	CHECK(lowerroot.iocount == 0 && lowerfile.iocount == 0 && lowerother.iocount == 0 && buffers == 0);
	CHECK(bindroot.iocount == (result == &bindroot) && bindchild.iocount == (result == &bindchild));
	bindroot.iocount = bindchild.iocount = 0;
}

static void
reset(void)
{
	static struct bind_mount mount;
	mount = (struct bind_mount){&bindroot, &lowerroot, BINDM_PATH_FROM_ID};
	current = &mount;
	lowerroot = (struct vnode){.path = "/private/var/staged_system_apps"};
	lowerfile = (struct vnode){.path = "/private/var/staged_system_apps/Weather.app/PlugIns/WeatherWidget.appex/Info.plist"};
	lowerother = (struct vnode){.path = "/private/var/staged_system_apps2/x"};
	bindroot = (struct vnode){0};
	bindchild = (struct vnode){0};
	lookups = vgets = 0;
	next_ino = 0;
	next_vnode = NULL;
	next_vget_error = next_lookup_error = 0;
	looked_up[0] = 0;
}

static void
test_vget(void)
{
	static struct mount mp;
	vnode_t vp = (vnode_t)1;
	uint32_t calls, resolved;

	/* The root's own ID, what bindfs_getattr reports for it: no lower look-up at all. */
	reset();
	CHECK(bindfs_vget(&mp, BIND_ROOT_INO, &vp, &user_context) == 0 && vp == &bindroot && vgets == 0 && lookups == 0);
	balanced(vp);
	/* The lower root's real ID, a parent ID of an entry without a cached parent. */
	reset();
	next_ino = 700;
	next_vnode = &lowerroot;
	CHECK(bindfs_vget(&mp, 700, &vp, &user_context) == 0 && vp == &bindroot && lookups == 0);
	balanced(vp);
	/* A file of the bound tree: looked up below our root, not crossing a mount, not following, in the kernel's context. */
	reset();
	next_ino = 800;
	next_vnode = &lowerfile;
	calls = native_bindfs_vget_calls;
	resolved = native_bindfs_vget_resolved;
	CHECK(bindfs_vget(&mp, 800, &vp, &user_context) == 0 && vp == &bindchild);
	CHECK(!strcmp(looked_up, "Weather.app/PlugIns/WeatherWidget.appex/Info.plist"));
	CHECK(looked_flags == (VNODE_LOOKUP_NOFOLLOW | VNODE_LOOKUP_NOCROSSMOUNT) && looked_ctx == &kernel_context && looked_dvp == &bindroot);
	CHECK(native_bindfs_vget_calls == calls + 1 && native_bindfs_vget_resolved == resolved + 1);
	balanced(vp);
	/* A sibling whose name starts like the bound root is outside it. */
	reset();
	next_ino = 900;
	next_vnode = &lowerother;
	vp = (vnode_t)1;
	CHECK(bindfs_vget(&mp, 900, &vp, &user_context) == ENOENT && vp == NULLVP && lookups == 0);
	balanced(NULLVP);
	/* The lower file system's answer goes back as it is: ENOENT lets fsgetpath ask the covered volume. */
	reset();
	CHECK(bindfs_vget(&mp, 901, &vp, &user_context) == ENOENT && vgets == 1);
	balanced(NULLVP);
	reset();
	next_vget_error = EIO;
	CHECK(bindfs_vget(&mp, 901, &vp, &user_context) == EIO);
	balanced(NULLVP);
	/* The lower root can be gone. */
	reset();
	lowerroot.refused = 1;
	CHECK(bindfs_vget(&mp, 800, &vp, &user_context) == ENOENT && vgets == 0);
	balanced(NULLVP);
	/* Either path fails. */
	reset();
	next_ino = 800;
	next_vnode = &lowerfile;
	lowerfile.path_error = ENOSPC;
	CHECK(bindfs_vget(&mp, 800, &vp, &user_context) == ENOSPC && lookups == 0);
	balanced(NULLVP);
	reset();
	next_ino = 800;
	next_vnode = &lowerfile;
	lowerroot.path_error = EINVAL;
	CHECK(bindfs_vget(&mp, 800, &vp, &user_context) == EINVAL && lookups == 0);
	balanced(NULLVP);
	/* The look-up fails: nothing is held, the error goes back. */
	reset();
	next_ino = 800;
	next_vnode = &lowerfile;
	next_lookup_error = ENOTDIR;
	resolved = native_bindfs_vget_resolved;
	CHECK(bindfs_vget(&mp, 800, &vp, &user_context) == ENOTDIR && native_bindfs_vget_resolved == resolved);
	balanced(NULLVP);
	/* Our root can be gone as well: no walk from it. */
	reset();
	next_ino = 800;
	next_vnode = &lowerfile;
	bindroot.refused = 1;
	CHECK(bindfs_vget(&mp, 800, &vp, &user_context) == ENOENT && lookups == 0);
	balanced(NULLVP);
	/* Bound at the lower volume's root: the path as it is, without its first slash; the root itself by another vnode is no entry. */
	reset();
	lowerroot.path = "/";
	lowerfile.path = "/Weather.app/Info.plist";
	next_ino = 800;
	next_vnode = &lowerfile;
	CHECK(bindfs_vget(&mp, 800, &vp, &user_context) == 0 && !strcmp(looked_up, "Weather.app/Info.plist"));
	balanced(vp);
	reset();
	lowerroot.path = "/";
	lowerfile.path = "/";
	next_ino = 800;
	next_vnode = &lowerfile;
	CHECK(bindfs_vget(&mp, 800, &vp, &user_context) == ENOENT && lookups == 0);
	balanced(NULLVP);
	/* A mount that did not ask, or one going away: as without the patch, and not counted. */
	reset();
	current->bindm_flags = BINDM_FORCE_ROOT;
	calls = native_bindfs_vget_calls;
	CHECK(bindfs_vget(&mp, BIND_ROOT_INO, &vp, &user_context) == ENOTSUP && vp == NULLVP && vgets == 0 && native_bindfs_vget_calls == calls);
	balanced(NULLVP);
	reset();
	current = NULL;
	CHECK(bindfs_vget(&mp, 800, &vp, &user_context) == ENOTSUP && vp == NULLVP);
}

static void
test_capabilities(void)
{
	const uint32_t both = VOL_CAP_FMT_PERSISTENTOBJECTIDS | VOL_CAP_FMT_PATH_FROM_ID, other = 0x2000;
	for (int flagged = 0; flagged < 2; flagged++) {
		struct { uint32_t capabilities[4], valid[4]; } capabilities = {{both | other}, {both | other}};
		struct bind_mount mount = {.bindm_flags = flagged ? BINDM_PATH_FROM_ID : BINDM_FORCE_ROOT};
		strip_capabilities(&mount, capabilities.capabilities, capabilities.valid);
		CHECK(capabilities.capabilities[0] == (flagged ? both | other : other) && capabilities.valid[0] == (flagged ? both | other : other));
	}
}

static void
test_mount(void)
{
	static const struct { int boot, set; uint32_t value; int asks, takes; } cases[] = {
		{0, 0, 0, 0, 0}, {0, 0, 0, 1, 0}, {0, 1, 2, 1, 0},      /* a mount of a process (the bindfs entitlement): never */
		{1, 0, 0, 0, 0}, {1, 0, 0, 1, 1},                       /* the default: the view that asks, no other */
		{1, 1, 1, 0, 0}, {1, 1, 1, 1, 1},
		{1, 1, 0, 0, 0}, {1, 1, 0, 1, 0},                       /* pagani-bindfs-vget=0: none */
		{1, 1, 2, 0, 1}, {1, 1, 2, 1, 1},                       /* pagani-bindfs-vget=2: every boot view */
	};
	for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
		struct mount mount = {0};
		struct bind_mount bind = {0};
		int before = native_bindfs_file_id_mounts;
		native_bindfs_boot_mount = cases[i].boot;
		boot_arg_set = cases[i].set;
		boot_arg = cases[i].value;
		native_bindfs_file_ids = cases[i].asks;
		mount_flags(&mount, &bind);
		CHECK(!!(bind.bindm_flags & BINDM_PATH_FROM_ID) == cases[i].takes && !!mount.mnt_kern_flag == cases[i].takes);
		CHECK(!!(bind.bindm_flags & BINDM_FORCE_ROOT) == cases[i].boot);
		CHECK(native_bindfs_file_id_mounts == before);          /* a mount that fails after this counts for nothing */
		mount_up(&bind);
		CHECK(native_bindfs_file_id_mounts == before + cases[i].takes);
	}
}

int
main(void)
{
	test_vget();
	test_capabilities();
	test_mount();
	printf("%d failures\n", failures);
	return failures ? 1 : 0;
}
'''


def hunks(text):
    """The new side (context and added lines, markers stripped) of each hunk, one string a hunk."""
    result, current = [], None
    for line in text.splitlines():
        if line.startswith('@@'):
            current = []
            result.append(current)
        elif line.startswith(('diff ', '--- ', '+++ ')):
            current = None
        elif current is not None and line.startswith((' ', '+')):
            current.append(line[1:])
        elif current is not None and line == '':
            current.append('')
    return ['\n'.join(hunk) for hunk in result]


def between(text, start, end):
    at = text.index(start)
    return text[at:text.index(end, at) + len(end)]


def harness_source(text):
    new = '\n'.join(hunks(text))
    vget = between(new, 'static int\nbindfs_vget(struct mount * mp', '\n}\n')
    strip = between(new, '\t\t\tif (!(bind_mp->bindm_flags & BINDM_PATH_FROM_ID)) {', '\n\t\t\t}\n')
    decide = between(new, '\tif (native_bindfs_boot_mount) {', '\n\t}\n')
    count = between(new, '\tif (xmp->bindm_flags & BINDM_PATH_FROM_ID) {', '\n\t}\n')
    return (HARNESS_HEAD + vget +
            '\nstatic void\nstrip_capabilities(struct bind_mount *bind_mp, uint32_t *caps, uint32_t *valid)\n{\n'
            '\tstruct { uint32_t *capabilities, *valid; } capabilities = {caps, valid};\n' + strip + '\n}\n' +
            '\nstatic void\nmount_flags(struct mount *mp, struct bind_mount *xmp)\n{\n' + decide + '\n}\n' +
            '\nstatic void\nmount_up(struct bind_mount *xmp)\n{\n' + count + '\n}\n' + HARNESS_MAIN)


class BindfsVgetPatchTest(unittest.TestCase):
    def setUp(self):
        self.text = PATCH.read_text()
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_touches_only_bindfs_and_the_view(self):
        self.assertEqual(sorted(re.findall(r'^\+\+\+ b/(\S+)', self.text, re.M)), sorted(FILES))
        removed = [line[1:].strip() for line in self.text.splitlines() if line.startswith('-') and not line.startswith('---')]
        self.assertEqual(sorted(removed), sorted([
            '#define BIND_ROOT_INO 2',
            '/* don\'t support vget */',
            'capabilities.capabilities[VOL_CAPABILITIES_FORMAT] &= ~(VOL_CAP_FMT_PERSISTENTOBJECTIDS | VOL_CAP_FMT_PATH_FROM_ID);',
            'capabilities.valid[VOL_CAPABILITIES_FORMAT] &= ~(VOL_CAP_FMT_PERSISTENTOBJECTIDS | VOL_CAP_FMT_PATH_FROM_ID);',
            '',
            'snprintf(line, sizeof(line), "system apps view stage %d status %d, migration sentinel %d", native_system_apps_stage,',
            'native_system_apps_status, native_system_apps_sentinel);',
        ]))

    def test_series_order(self):
        series = [line.strip() for line in (PATCHES / 'series').read_text().splitlines() if line.strip()]
        self.assertEqual(series.count('phone-bindfs-vget.patch'), 1)
        self.assertLess(series.index('phone-system-apps-view.patch'), series.index('phone-bindfs-vget.patch'))

    def test_only_the_system_apps_view_asks(self):
        new = '\n'.join(hunks(self.text))
        self.assertEqual(new.count('native_bindfs_file_ids = 1;'), 1)
        # The end with its context: the same text also is the variable's definition in bind_vfsops.c, which must not end the block.
        block = between(new, 'native_bindfs_file_ids = 1;', '\tnative_bindfs_file_ids = 0;\n\tif (boot_progress_trace) {')
        self.assertIn('"/Applications/MobileCal.app"', block)
        self.assertNotIn('native_cryptex', block)

    def test_harness(self):
        binary = Path(self.temp.name) / 'harness'
        subprocess.run(['xcrun', 'clang', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-x', 'c', '-', '-o', str(binary)],
                       input=harness_source(self.text), text=True, check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_applies_to_tree(self):
        if XNU is None:
            self.skipTest('no --xnu tree given')
        root = Path(self.temp.name) / 'xnu'
        for name in FILES:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(XNU) / name, root / name)
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        subprocess.run(['git', 'apply', '--check', str(PATCH)], cwd=root, check=True)
        subprocess.run(['git', 'apply', str(PATCH)], cwd=root, check=True)
        self.assertIn('.vfs_vget               = bindfs_vget,', (root / 'bsd/miscfs/bindfs/bind_vfsops.c').read_text())

    def test_series_applies_in_order(self):
        if INPUTS is None:
            self.skipTest('no --inputs xnu-inputs.json given')
        inputs = json.loads(Path(INPUTS).read_text())
        before = [Path(patch['path']) for patch in inputs['patches'] if Path(patch['path']).parent != PATCHES]
        self.assertEqual([Path(patch['path']) for patch in inputs['patches']][:len(before)], before)
        series = [line.strip() for line in (PATCHES / 'series').read_text().splitlines()]
        patches = before + [PATCHES / name for name in series if name and not name.startswith('#')]
        self.assertIn(PATCH, patches)
        root = Path(self.temp.name) / 'xnu'
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
