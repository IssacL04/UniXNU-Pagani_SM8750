#!/usr/bin/env python3
"""patches/xnu/phone-checkdirs-kernproc.patch: the shutdown panic of a vnode at usecount -1 once SystemOS is mounted over "/".
checkdirs_callback takes kernproc's current directory along without touching a count (it never held one: set_rootvnode only assigns it), the
boot log has the two roots' addresses and usecounts right after the mount, and SystemOS is a system volume, unmounted once launchd is suspended.
The host harness runs checkdirs on a model of the two boot-time volumes, counted as the phone's: an APFS root starts at 5 (the volume's reference and
the v_parent of private-dir, .snaps and two xattr vnodes), the covered one also has /dev and /private. With the patch's block the record reads
covered 8, root 7, what run 20261101-053955 logged, and the covered root goes to exactly 0 through the shutdown's unmounts; without it (the pristine
function, kept as a control) it reads 7 and 8 and reaches the panic's -1, at the last release, private-dir's v_parent.
With --xnu <tree> (an XNU checkout with the earlier series applied; only read) the harness's copy of the two functions must be what the tree
has, the patch goes on a copy of the two files, and what the shutdown reasoning rests on is read from the tree.
With --inputs <xnu-inputs.json> (of a kernel build, naming the XNU source, its commit and the patches before the device series) the whole
series as this checkout has it now goes on a fresh clone, in order, with git apply as the build does, this patch last if the series lacks it.
Run: python3 scripts/test-checkdirs-kernproc-patch.py [--xnu <tree>] [--inputs <xnu-inputs.json>]"""
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
PATCH = PATCHES / 'phone-checkdirs-kernproc.patch'
FILES = ['bsd/kern/kern_exec.c', 'bsd/vfs/vfs_syscalls.c']
XNU = None
INPUTS = None

HARNESS_HEAD = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct mount { int unused; };
typedef struct mount *mount_t;
struct vnode { int v_usecount; int ref_refused; int dead; struct mount *v_mountedhere; };
typedef struct vnode *vnode_t;
struct filedesc { vnode_t fd_cdir, fd_rdir; };
struct proc { struct filedesc p_fd; int locks; };
typedef struct proc *proc_t;
typedef int *vfs_context_t;
struct cdirargs { vnode_t olddp, newdp; };
#define PROC_RETURNED 0
#define PROC_ALLPROCLIST 1
#define PROC_NOWAITTRANS 2

static struct proc kernel_proc, launchd_proc, app_proc;
static proc_t kernproc = &kernel_proc;
static vnode_t rootvnode;
static vnode_t mounted_root;
static int rootvnode_rw_lock, iocounts, negative;

static int vnode_ref(vnode_t vp) { if (vp->ref_refused) return 2; vp->v_usecount++; return 0; }
static void vnode_rele(vnode_t vp) { if (--vp->v_usecount < 0) negative++; }
static void vnode_put(vnode_t vp) { (void)vp; iocounts--; }
static void proc_fdlock(proc_t p) { p->locks++; }
static void proc_fdunlock(proc_t p) { p->locks--; }
static void proc_dirs_lock_exclusive(proc_t p) { p->locks += 16; }
static void proc_dirs_unlock_exclusive(proc_t p) { p->locks -= 16; }
static void lck_rw_lock_exclusive(int *lock) { (*lock)++; }
static void lck_rw_unlock_exclusive(int *lock) { (*lock)--; }
static int VFS_ROOT(mount_t mp, vnode_t *vpp, vfs_context_t ctx) { (void)mp; (void)ctx; iocounts++; *vpp = mounted_root; return 0; }
static int callback(proc_t p, void *arg);
static void
proc_iterate(int flags, int (*cb)(proc_t, void *), void *arg, void *filter, void *filter_arg)
{
	proc_t procs[] = {kernproc, &launchd_proc, &app_proc};
	(void)flags; (void)filter; (void)filter_arg;
	for (size_t i = 0; i < sizeof(procs) / sizeof(procs[0]); i++) {
		cb(procs[i], arg);
	}
}
'''

# The two functions as XNU has them, @BLOCK@ where the patch's block goes. --xnu holds them against the tree.
CHECKDIRS = r'''static int
checkdirs_callback(proc_t p, void * arg)
{
	struct cdirargs *cdrp = (struct cdirargs *)arg;
	vnode_t olddp = cdrp->olddp;
	vnode_t newdp = cdrp->newdp;
	struct filedesc *fdp = &p->p_fd;
	vnode_t new_cvp = newdp;
	vnode_t new_rvp = newdp;
	vnode_t old_cvp = NULL;
	vnode_t old_rvp = NULL;

	/*
	 * XXX Also needs to iterate each thread in the process to see if it
	 * XXX is using a per-thread current working directory, and, if so,
	 * XXX update that as well.
	 */

	/*
	 * First, with the proc_fdlock held, check to see if we will need
	 * to do any work.  If not, we will get out fast.
	 */
	proc_fdlock(p);
	if (fdp->fd_cdir != olddp && fdp->fd_rdir != olddp) {
		proc_fdunlock(p);
		return PROC_RETURNED;
	}
	proc_fdunlock(p);

@BLOCK@	/*
	 * Ok, we will have to do some work.  Always take two refs
	 * because we might need that many.  We'll dispose of whatever
	 * we ended up not using.
	 */
	if (vnode_ref(newdp) != 0) {
		return PROC_RETURNED;
	}
	if (vnode_ref(newdp) != 0) {
		vnode_rele(newdp);
		return PROC_RETURNED;
	}

	proc_dirs_lock_exclusive(p);
	/*
	 * Now do the work.  Note: we dropped the proc_fdlock, so we
	 * have to do all of the checks again.
	 */
	proc_fdlock(p);
	if (fdp->fd_cdir == olddp) {
		old_cvp = olddp;
		fdp->fd_cdir = newdp;
		new_cvp = NULL;
	}
	if (fdp->fd_rdir == olddp) {
		old_rvp = olddp;
		fdp->fd_rdir = newdp;
		new_rvp = NULL;
	}
	proc_fdunlock(p);
	proc_dirs_unlock_exclusive(p);

	/*
	 * Dispose of any references that are no longer needed.
	 */
	if (old_cvp != NULL) {
		vnode_rele(old_cvp);
	}
	if (old_rvp != NULL) {
		vnode_rele(old_rvp);
	}
	if (new_cvp != NULL) {
		vnode_rele(new_cvp);
	}
	if (new_rvp != NULL) {
		vnode_rele(new_rvp);
	}

	return PROC_RETURNED;
}
'''

CHECKDIRS_TAIL = r'''static int
checkdirs(vnode_t olddp, vfs_context_t ctx)
{
	vnode_t newdp;
	vnode_t tvp;
	int err;
	struct cdirargs cdr;

	if (olddp->v_usecount == 1) {
		return 0;
	}
	err = VFS_ROOT(olddp->v_mountedhere, &newdp, ctx);

	if (err != 0) {
#if DIAGNOSTIC
		panic("mount: lost mount: error %d", err);
#endif
		return err;
	}

	cdr.olddp = olddp;
	cdr.newdp = newdp;
	/* do not block for exec/fork trans as the vp in cwd & rootdir are not changing */
	proc_iterate(PROC_ALLPROCLIST | PROC_NOWAITTRANS, checkdirs_callback, (void *)&cdr, NULL, NULL);

	if (rootvnode == olddp) {
		vnode_ref(newdp);
		lck_rw_lock_exclusive(&rootvnode_rw_lock);
		tvp = rootvnode;
		rootvnode = newdp;
		lck_rw_unlock_exclusive(&rootvnode_rw_lock);
		vnode_rele(tvp);
	}

	vnode_put(newdp);
	return 0;
}
'''

HARNESS_MAIN = r'''
#define CHECK(condition) do { if (!(condition)) { printf("%s:%d: %s\n", __func__, __LINE__, #condition); failures++; } } while (0)
static int failures;
static struct mount systemos, next_volume;
static struct vnode oldroot, newroot, thirdroot, directory, dirroot;

/* What bsd_init and the fork of launchd leave: the covered root, APFS's five, /dev and /private as children, rootvnode's (kernproc only points at it),
 * launchd's fd_cdir; SystemOS's root, APFS's five. */
static void
booted(void)
{
	memset(&oldroot, 0, sizeof(oldroot));
	memset(&newroot, 0, sizeof(newroot));
	memset(&thirdroot, 0, sizeof(thirdroot));
	memset(&directory, 0, sizeof(directory));
	memset(&dirroot, 0, sizeof(dirroot));
	memset(&kernel_proc, 0, sizeof(kernel_proc));
	memset(&launchd_proc, 0, sizeof(launchd_proc));
	memset(&app_proc, 0, sizeof(app_proc));
	oldroot.v_usecount = 9;
	newroot.v_usecount = 5;
	thirdroot.v_usecount = 1;
	dirroot.v_usecount = 1;
	rootvnode = &oldroot;
	kernel_proc.p_fd.fd_cdir = &oldroot;
	launchd_proc.p_fd.fd_cdir = &oldroot;
	app_proc.p_fd.fd_cdir = &directory;
	negative = iocounts = 0;
}

/* mount_common for a mount over vp: the covering mount's reference, then checkdirs. */
static void
mount_over(vnode_t vp, struct mount *mp, vnode_t root)
{
	vnode_ref(vp);
	vp->v_mountedhere = mp;
	mounted_root = root;
	checkdirs(vp, NULL);
	CHECK(iocounts == 0 && rootvnode_rw_lock == 0);
	CHECK(kernel_proc.locks == 0 && launchd_proc.locks == 0 && app_proc.locks == 0);
}

/* SystemOS mounted over "/" at boot, then the two unmounts of the shutdown: SystemOS, whose covered vnode goes last, then the root volume. */
static int
union_root(void)
{
	booted();
	mount_over(&oldroot, &systemos, &newroot);
	printf("after mount: covered %d, root %d\n", oldroot.v_usecount, newroot.v_usecount);
	CHECK(rootvnode == &newroot);
	CHECK(kernel_proc.p_fd.fd_cdir == &newroot && launchd_proc.p_fd.fd_cdir == &newroot);
	for (int i = 0; i < 5; i++) {
		vnode_rele(&newroot);           /* apfs_vfsop_unmount of SystemOS: its own reference, its four system vnodes' */
	}
	vnode_rele(&oldroot);                   /* dounmount of SystemOS: the covered vnode */
	for (int i = 0; i < 7; i++) {
		vnode_rele(&oldroot);           /* of the root volume: /dev, /private, three system vnodes, its own; private-dir's v_parent last */
	}
	printf("after shutdown: covered %d, root %d, negative %d\n", oldroot.v_usecount, newroot.v_usecount, negative);
	return negative;
}

#ifndef PRISTINE
static void
a_second_mount_over_the_root(void)
{
	booted();
	mount_over(&oldroot, &systemos, &newroot);
	mount_over(&newroot, &next_volume, &thirdroot);
	CHECK(rootvnode == &thirdroot && kernel_proc.p_fd.fd_cdir == &thirdroot && launchd_proc.p_fd.fd_cdir == &thirdroot);
	CHECK(oldroot.v_usecount == 8);         /* APFS's five, /dev, /private, covered */
	CHECK(newroot.v_usecount == 6);         /* APFS's five, covered */
	CHECK(thirdroot.v_usecount == 3);       /* APFS, launchd, rootvnode: nothing for kernproc */
	CHECK(negative == 0);
}

/* A mount over any other directory: kernproc is not there, and who is there is served as before. */
static void
a_mount_over_a_process_directory(void)
{
	booted();
	app_proc.p_fd.fd_rdir = &directory;
	directory.v_usecount = 2;
	mount_over(&directory, &next_volume, &dirroot);
	CHECK(app_proc.p_fd.fd_cdir == &dirroot && app_proc.p_fd.fd_rdir == &dirroot);
	CHECK(directory.v_usecount == 1);       /* the covering mount */
	CHECK(dirroot.v_usecount == 3);         /* the volume, cdir, rdir */
	CHECK(rootvnode == &oldroot && kernel_proc.p_fd.fd_cdir == &oldroot && oldroot.v_usecount == 9);
}

/* A directory of kernproc other than rootvnode would be one it took a reference on: the references move as for any process. */
static void
kernproc_elsewhere_keeps_the_old_rules(void)
{
	booted();
	kernel_proc.p_fd.fd_cdir = &directory;
	directory.v_usecount = 2;
	mount_over(&directory, &next_volume, &dirroot);
	CHECK(kernel_proc.p_fd.fd_cdir == &dirroot);
	CHECK(directory.v_usecount == 1);       /* the covering mount; kernproc's reference and app_proc's moved */
	CHECK(dirroot.v_usecount == 3);         /* the volume, kernproc, app_proc */
}

/* newdp refused while the patch's block has nothing to take: the pointer still follows. */
static void
a_refused_reference_does_not_strand_kernproc(void)
{
	booted();
	newroot.ref_refused = 1;
	vnode_ref(&oldroot);
	oldroot.v_mountedhere = &systemos;
	mounted_root = &newroot;
	checkdirs(&oldroot, NULL);
	CHECK(kernel_proc.p_fd.fd_cdir == &newroot);
	CHECK(launchd_proc.p_fd.fd_cdir == &oldroot);
	CHECK(newroot.v_usecount == 5);
}
#endif

/* The record of kern_exec.c, the worst values into its buffer. */
static void
record(void)
{
	struct vnode a = {.v_usecount = 2}, b = {.v_usecount = 3};
	vnode_t original_os_root = &a;
	vnode_t rootvnode = &b;
	@RECORD@
	(void)original_os_root; (void)rootvnode;
}

int
main(void)
{
	int negatives = union_root();
#ifndef PRISTINE
	CHECK(negatives == 0);
	a_second_mount_over_the_root();
	a_mount_over_a_process_directory();
	kernproc_elsewhere_keeps_the_old_rules();
	a_refused_reference_does_not_strand_kernproc();
	record();
#else
	(void)negatives;
#endif
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


def block(text):
    new = '\n'.join(hunks(text))
    return between(new, '\t/*\n\t * phone-checkdirs-kernproc.patch.', '\t\treturn PROC_RETURNED;\n\t}\n') + '\n'


def harness_source(text, pristine=False):
    new = '\n'.join(hunks(text))
    record_block = between(new, '\t\tchar roots[96];', 'boot_progress_root("SystemOS root refs", roots, 0);\n')
    # Every byte of the buffer visible to the sanitizer; the line must fit with the largest addresses and counts.
    record_block = record_block.replace('boot_progress_root("SystemOS root refs", roots, 0);',
                                        'CHECK(strlen(roots) < sizeof(roots) - 1); printf("record: %s\\n", roots);')
    return ('#define PRISTINE 1\n' if pristine else '') + HARNESS_HEAD + CHECKDIRS.replace('@BLOCK@', '' if pristine else block(text)) + '\n' + \
        CHECKDIRS_TAIL + 'static int callback(proc_t p, void *arg) { return checkdirs_callback(p, arg); }\n' + \
        HARNESS_MAIN.replace('@RECORD@', record_block)


class CheckdirsKernprocPatchTest(unittest.TestCase):
    def setUp(self):
        self.text = PATCH.read_text()
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def run_harness(self, pristine):
        binary = Path(self.temp.name) / ('pristine' if pristine else 'patched')
        subprocess.run(['xcrun', 'clang', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        '-Wno-unused-parameter', '-Wno-unused-variable', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-x', 'c', '-',
                        '-o', str(binary)], input=harness_source(self.text, pristine), text=True, check=True)
        return subprocess.run([str(binary)], capture_output=True, text=True)

    def test_adds_only(self):
        self.assertEqual(sorted(re.findall(r'^\+\+\+ b/(\S+)', self.text, re.M)), sorted(FILES))
        removed = [line for line in self.text.splitlines() if line.startswith('-') and not line.startswith('---')]
        self.assertEqual(removed, [])

    def test_the_fix_gives_what_the_phone_logged(self):
        result = self.run_harness(False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('after mount: covered 8, root 7\n', result.stdout)
        self.assertIn('after shutdown: covered 0, root 2, negative 0\n', result.stdout)

    def test_without_it_the_panic_comes_back(self):
        result = self.run_harness(True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('after mount: covered 7, root 8\n', result.stdout)
        self.assertIn('after shutdown: covered -1, root 3, negative 1\n', result.stdout)

    def test_the_record_is_right_after_the_mount(self):
        new = hunks(self.text)
        exec_hunk = next(hunk for hunk in new if 'SystemOS root refs' in hunk)
        self.assertLess(exec_hunk.index('if (error) goto done;'), exec_hunk.index('SystemOS root refs'))
        self.assertLess(exec_hunk.index('SystemOS root refs'), exec_hunk.index('native_owner_cache_stage = 4;'))
        self.assertLess(exec_hunk.index('SystemOS root refs'), exec_hunk.index('SystemOS vnode lookup enter'))

    def test_systemos_is_a_system_volume_once_authorized(self):
        new = hunks(self.text)
        guard = next(hunk for hunk in new if 'vfs_setmntsystem' in hunk)
        self.assertLess(guard.index('if (!cache_authorized) { error = EAUTH; goto done; }'), guard.index('vfs_setmntsystem(cache_mount);'))
        self.assertLess(guard.index('#if defined(XNU_OWNER_UNION_SYSTEMOS) && XNU_OWNER_UNION_SYSTEMOS'), guard.index('vfs_setmntsystem(cache_mount);'))
        self.assertLess(guard.index('vfs_setmntsystem(cache_mount);'), guard.index('#endif', guard.index('vfs_setmntsystem(cache_mount);')))

    def copy_tree(self):
        root = Path(self.temp.name) / 'xnu'
        for name in FILES:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(XNU) / name, root / name)
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        return root

    def test_the_harness_has_the_trees_functions(self):
        if XNU is None:
            self.skipTest('no --xnu tree given')
        source = (Path(XNU) / 'bsd/vfs/vfs_syscalls.c').read_text()
        self.assertIn(CHECKDIRS.replace('@BLOCK@', ''), source)
        self.assertIn(CHECKDIRS_TAIL, source)

    def test_applies_to_tree(self):
        if XNU is None:
            self.skipTest('no --xnu tree given')
        root = self.copy_tree()
        subprocess.run(['git', 'apply', '--check', str(PATCH)], cwd=root, check=True)
        subprocess.run(['git', 'apply', str(PATCH)], cwd=root, check=True)
        self.assertIn(CHECKDIRS.replace('@BLOCK@', block(self.text)), (root / 'bsd/vfs/vfs_syscalls.c').read_text())

    def test_what_the_shutdown_reasoning_rests_on(self):
        if XNU is None:
            self.skipTest('no --xnu tree given')
        read = lambda name: (Path(XNU) / name).read_text()
        # set_rootvnode only assigns kernproc's directory; bsd_init's one vnode_ref is rootvnode's.
        self.assertIn('kernproc->p_fd.fd_cdir = new_rootvnode;', read('bsd/kern/bsd_init.c'))
        # A system volume is skipped by the first pass, and launchd is suspended between the passes.
        self.assertIn('((mp->mnt_flag & MNT_ROOTFS) || (mp->mnt_kern_flag & MNTK_SYSTEM))', read('bsd/vfs/vfs_subr.c'))
        shutdown = read('bsd/kern/kern_shutdown.c')
        first, second = shutdown.index('vfs_unmountall(TRUE);'), shutdown.index('vfs_unmountall(FALSE);')
        self.assertLess(first, shutdown.index('proc_shutdown(FALSE);'))
        self.assertLess(shutdown.index('proc_shutdown(FALSE);'), second)
        self.assertIn('task_suspend_internal(proc_task(initproc));', shutdown)
        # Lookups from the reclaimed root end in ENOENT; the page-in does not: a destroyed pager is a memory error, fatal to launchd.
        self.assertIn('if (dp == NULLVP || (dp->v_lflag & VL_DEAD)) {', read('bsd/vfs/vfs_lookup.c'))
        self.assertIn('\t\t/* Always panic for launchd */', read('bsd/kern/kern_exit.c'))
        self.assertIn('if (pager == MEMORY_OBJECT_NULL) {', read('osfmk/vm/vm_fault.c'))
        # The flag does nothing else: refused unmount(2), and the rename of a volume root (a union root never gets there).
        uses = [line for name in ('bsd/vfs/vfs_syscalls.c', 'bsd/vfs/vfs_subr.c') for line in read(name).splitlines()
                if 'MNTK_SYSTEM)' in line and ' & ' in line and '|=' not in line]
        self.assertEqual(len(uses), 3, uses)

    def test_series_applies_in_order(self):
        if INPUTS is None:
            self.skipTest('no --inputs xnu-inputs.json given')
        inputs = json.loads(Path(INPUTS).read_text())
        before = [Path(patch['path']) for patch in inputs['patches'] if Path(patch['path']).parent != PATCHES]
        self.assertEqual([Path(patch['path']) for patch in inputs['patches']][:len(before)], before)
        series = [line.strip() for line in (PATCHES / 'series').read_text().splitlines()]
        patches = before + [PATCHES / name for name in series if name and not name.startswith('#')]
        if PATCH not in patches:
            patches.append(PATCH)
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
