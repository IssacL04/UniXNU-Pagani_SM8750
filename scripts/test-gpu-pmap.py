#!/usr/bin/env python3
"""Exercise the actual pmap patch over locked software mapping lists; no kernel access."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
patch = (ROOT / 'patches/xnu/gpu-user-mappings.patch').read_text()
code = '\n'.join(line[1:] for line in patch.splitlines()
                 if line.startswith('+') and not line.startswith('+++'))
fixture = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t ppnum_t;
typedef uint64_t pmap_paddr_t;
typedef struct Pmap {char pmap_procname[24];} *pmap_t;
typedef struct Pte {pmap_t owner;uint64_t va;bool iommu;} pt_entry_t;
typedef struct Pve {pt_entry_t *pte[2];struct Pve *next;} pv_entry_t;
static struct Pmap kernel={"kernel"},user={"first-user-long-name"},other={"other"};
static pmap_t kernel_pmap=&kernel;
static pv_entry_t *head;
static pt_entry_t *direct;
static unsigned kind,locks,unlocks;
static bool locked;
#define XNU_MONITOR 0
#define PVH_FLAG_IOMMU 1
#define PVH_TYPE_PTEP 1
#define PVH_TYPE_PVEP 2
#define PT_ENTRY_NULL NULL
#define PV_ENTRY_NULL NULL
#define PTE_PER_PVE 2
static pmap_paddr_t ptoa(ppnum_t n) {return (uint64_t)n<<12;}
static bool pa_valid(pmap_paddr_t pa) {return pa==4096;}
static unsigned pa_index(pmap_paddr_t pa) {assert(pa==4096);return 0;}
static void pvh_lock(unsigned i) {assert(!i&&!locked);locked=true;++locks;}
static void pvh_unlock(unsigned i) {assert(!i&&locked);locked=false;++unlocks;}
static pv_entry_t **pai_to_pvh(unsigned i) {assert(!i&&locked);return &head;}
static bool pvh_test_type(pv_entry_t **p,unsigned type) {assert(p==&head&&locked);return kind==type;}
static pt_entry_t *pvh_ptep(pv_entry_t **p) {assert(p==&head&&locked);return direct;}
static pv_entry_t *pvh_pve_list(pv_entry_t **p) {assert(p==&head&&locked);return head;}
static pt_entry_t *pve_get_ptep(pv_entry_t *p,int i) {assert(locked&&i>=0&&i<2);return p->pte[i];}
static pv_entry_t *pve_next(pv_entry_t *p) {assert(locked);return p->next;}
static bool pvh_ptep_is_iommu(pt_entry_t *p) {assert(locked);return p->iommu;}
static pmap_t ptep_get_pmap(pt_entry_t *p) {assert(locked&&!p->iommu);return p->owner;}
static uint64_t ptep_get_va(pt_entry_t *p) {assert(locked&&!p->iommu);return p->va;}
size_t fake_strlcpy(char *out,const char *in,size_t n) {size_t len=strlen(in);if(n){size_t copy=len<n-1?len:n-1;memcpy(out,in,copy);out[copy]=0;}return len;}
#define strlcpy fake_strlcpy
'''
checks = r'''
int main(void) {
    void *owner=(void *)1;uint64_t va=1;char name[17]="old";
    assert(!native_pmap_user_mappings(2,&owner,&va,name)&&!owner&&!va&&!name[0]&&!locks);
    assert(!native_pmap_user_mappings(1,NULL,NULL,NULL)&&locks==1&&unlocks==1);
    pt_entry_t k={&kernel,0x8000,false},a={&user,0x1000,false},b={&other,0x2000,false};
    pt_entry_t io={NULL,0,true},a2={&user,0x3000,false};
    kind=PVH_TYPE_PTEP;direct=&k;assert(!native_pmap_user_mappings(1,NULL,NULL,NULL));
    direct=&io;assert(!native_pmap_user_mappings(1,NULL,NULL,NULL));
    direct=&a;assert(native_pmap_user_mappings(1,&owner,&va,name)==1&&owner==&user&&va==0x1000);
    if(MACH_ASSERT)assert(!strcmp(name,"first-user-long-"));else assert(!name[0]);
    pv_entry_t third={{&a2,&b},NULL},second={{&a,NULL},&third},first={{&io,&k},&second};
    kind=PVH_TYPE_PVEP;head=&first;
    assert(native_pmap_user_mappings(1,&owner,&va,name)==3&&owner==&user&&va==0x1000);
    assert(native_pmap_user_mappings(1,NULL,NULL,NULL)==3);
    assert(head==&first&&first.next==&second&&second.next==&third&&!third.next);
    assert(first.pte[0]==&io&&first.pte[1]==&k&&second.pte[0]==&a&&!second.pte[1]);
    assert(third.pte[0]==&a2&&third.pte[1]==&b&&a.va==0x1000&&a.owner==&user);
    kind=3;assert(!native_pmap_user_mappings(1,NULL,NULL,NULL));
    assert(!locked&&locks==unlocks);
    puts("PASS: actual pmap helper: invalid/empty/kernel/IOMMU/single/list mappings, first owner, optional outputs and balanced locks; no mapping mutation");
}
'''
with tempfile.TemporaryDirectory(prefix='pagani-pmap-') as directory:
    source = Path(directory) / 'pmap.c'
    source.write_text(fixture + code + checks)
    for enabled in (0, 1):
        binary = Path(directory) / ('pmap-' + str(enabled))
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-DMACH_ASSERT=' + str(enabled),
                        source, '-o', binary], check=True)
        subprocess.run([binary], check=True)
