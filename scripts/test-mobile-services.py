#!/usr/bin/env python3
"""Exercise the actual USB pairing and owner Wi-Fi launch policy fragments."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def additions(name):
    return '\n'.join(line[1:] for line in (ROOT / 'patches/xnu' / name).read_text().splitlines()
                     if line.startswith('+') and not line.startswith('+++'))


launch = additions('phone-wifi-service-launch.patch')
launch = launch[:launch.index('\n\tif (!pagani_wifi_owner_launch')]
fsid = additions('native-union-statfs-fsid.patch')
probe = (ROOT.parent / 'UniXNU-Pagani-Drivers/drivers/Stage7Probe/Stage7Probe.cpp').read_text()
aks = re.search(r'uint32_t native_aks_lock_state\(void\) \{.*?\n\}', probe, re.S).group()
source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define MAXPATHLEN 1024
#define NULLVP NULL
#define CS_VALID 1
#define CS_SIGNED 2
struct image_params { void *ip_vp; unsigned ip_csflags; };
static unsigned wifi = 6, sls = 3;
static bool supplied = true, ephemeralState = true;
static int path_error;
static const char *image_path = "/usr/libexec/unixnu-wpa_supplicant";
static bool PE_parse_boot_argn(const char *name, void *out, unsigned size) {
    assert(size == sizeof(uint32_t));
    if (supplied) *(uint32_t *)out = strcmp(name, "pagani-wifi") ? sls : wifi;
    return supplied;
}
static int vn_getpath(void *vp, char *path, int *length) {
    assert(vp && *length >= (int)strlen(image_path) + 1);
    if (!path_error) strcpy(path, image_path);
    return path_error;
}
''' + launch + '\n' + aks + r'''
#define MNT_UNION 1
#define MNT_ROOTFS 2
#define VROOT 1
struct fsstat { int f_fsid; };
struct mount;
struct vnode { unsigned v_flag; struct mount *v_mount; };
struct mount { unsigned mnt_flag; struct vnode *mnt_vnodecovered; struct fsstat mnt_vfsstat; };
static int identity(struct mount *mp) {
    struct fsstat result = mp->mnt_vfsstat, *sfs = &result;
''' + fsid + r'''
    return result.f_fsid;
}
int main(void) {
    struct image_params p = {(void *)1, CS_VALID | CS_SIGNED};
    assert(pagani_wifi_owner_launch(&p));
    assert(!pagani_wifi_owner_launch(NULL));
    p.ip_vp = NULL; assert(!pagani_wifi_owner_launch(&p)); p.ip_vp = (void *)1;
    for (unsigned f = 0; f < 3; ++f) { p.ip_csflags = f; assert(!pagani_wifi_owner_launch(&p)); }
    p.ip_csflags = 3;
    for (wifi = 0; wifi < 8; ++wifi) assert(pagani_wifi_owner_launch(&p) == (wifi == 6));
    wifi = 6; supplied = false; assert(!pagani_wifi_owner_launch(&p)); supplied = true;
    path_error = 1; assert(!pagani_wifi_owner_launch(&p)); path_error = 0;
    const char *wrong[] = {"/usr/libexec/lockdownd", "/tmp/unixnu-wpa_supplicant", "/usr/libexec/unixnu-wpa_supplicant-copy"};
    for (unsigned i = 0; i < 3; ++i) { image_path = wrong[i]; assert(!pagani_wifi_owner_launch(&p)); }
    for (sls = 0; sls < 5; ++sls) assert(native_aks_lock_state() == (sls == 3 ? 3 : 0));
    sls = 3; ephemeralState = false; assert(native_aks_lock_state() == 0);
    ephemeralState = true; supplied = false; assert(native_aks_lock_state() == 0);
    struct mount root = {MNT_ROOTFS, NULL, {10}};
    struct vnode covered = {VROOT, &root};
    struct mount system = {MNT_UNION, &covered, {20}};
    assert(identity(&system) == 10);
    system.mnt_flag = 0; assert(identity(&system) == 20); system.mnt_flag = MNT_UNION;
    covered.v_flag = 0; assert(identity(&system) == 20); covered.v_flag = VROOT;
    root.mnt_flag = 0; assert(identity(&system) == 20); root.mnt_flag = MNT_ROOTFS;
    system.mnt_vnodecovered = NULL; assert(identity(&system) == 20);
}
'''
with tempfile.TemporaryDirectory(prefix='pagani-mobile-services-') as directory:
    path = Path(directory)
    (path / 'policy.c').write_text(source)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(path / 'policy.c'), '-o', str(path / 'policy')], check=True)
    subprocess.run([str(path / 'policy')], check=True)
print('PASS: signed Wi-Fi service scope, ephemeral lock state and union-root filesystem identity')
