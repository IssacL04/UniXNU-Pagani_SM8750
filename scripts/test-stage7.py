#!/usr/bin/env python3
"""Exercise the actual compatibility function and display timer with host stubs."""
import argparse
from pathlib import Path
import runpy
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tree', type=Path, required=True)
tree = parser.parse_args().tree
patch = (tree / 'patches/xnu/native-stage7-userspace-compat.patch').read_text()
added = ''.join(line[1:] for line in patch.splitlines(True)
                if line.startswith('+') and not line.startswith('+++'))
compat = added[added.index('/* 21H461'):added.index('    return written;') + len('    return written;\n}\n')]
compat = compat.replace('#include <pexpert/device_tree.h>', '')
assert 'validated == VMP_CS_ALL_TRUE && tainted == VMP_CS_ALL_FALSE' in added
assert 'cache_sync_page(VM_PAGE_GET_PHYS_PAGE(page))' in added
c = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
typedef uint64_t memory_object_offset_t;
typedef void *DTEntry;
struct vnode {const char *v_name;};
#define NULLVP NULL
#define PAGE_SIZE 4096
#define kSuccess 0
#define STARTUP(...)
#define os_atomic_inc(p, order) (++*(p))
static uint32_t property=1;
static unsigned property_size=4;
static int SecureDTLookupEntry(void *unused,const char *path,DTEntry *entry) {
    (void)unused;assert(!strcmp(path,"/chosen"));*entry=NULL;return 0;
}
static int SecureDTGetProperty(DTEntry entry,const char *key,const void **value,unsigned *size) {
    (void)entry;assert(!strcmp(key,"ephemeral-storage"));*value=&property;*size=property_size;return 0;
}
''' + compat + r'''
int main(void) {
    unsigned char page[PAGE_SIZE],expected[PAGE_SIZE];
    struct vnode wrong={"unrelated"};
    property=0;native_stage7_compat_init();assert(!native_stage7_compat_enabled);
    property=1;property_size=8;native_stage7_compat_init();assert(!native_stage7_compat_enabled);
    property_size=4;native_stage7_compat_init();assert(native_stage7_compat_enabled);
    assert(!native_stage7_compat_page(NULL,0,page));
    for(unsigned i=0;i<sizeof(native_stage7_fixups)/sizeof(native_stage7_fixups[0]);++i) {
        const struct native_stage7_fixup *f=&native_stage7_fixups[i];
        const uint64_t offset=f->offset & ~(uint64_t)(PAGE_SIZE-1);
        const size_t within=(size_t)(f->offset-offset);
        struct vnode file={f->name};
        memset(page,0xa5,sizeof page);memcpy(page+within,f->original,f->length);
        memcpy(expected,page,sizeof page);
        assert(!native_stage7_compat_page(&wrong,offset,page));
        assert(!native_stage7_compat_page(&file,offset+PAGE_SIZE,page));
        assert(!native_stage7_compat_page(&file,UINT64_MAX,page));
        native_stage7_compat_enabled=false;
        assert(!native_stage7_compat_page(&file,offset,page));
        native_stage7_compat_enabled=true;
        assert(!memcmp(expected,page,sizeof page));
        assert(native_stage7_compat_page(&file,offset,page)==1);
        memcpy(expected+within,f->replacement,f->length);
        assert(!memcmp(expected,page,sizeof page));
        assert(!native_stage7_compat_page(&file,offset,page));
        printf("%s %llx ",f->name,(unsigned long long)f->offset);
        for(unsigned j=0;j<f->length;++j)printf("%02x",f->original[j]);
        putchar('\n');
    }
    assert(native_stage7_compat_applied==4);
    return 0;
}
'''
display = (tree / 'drivers/NativeMobileDisplay/NativeLegacyDisplay.cpp').read_text()
timer = display[display.index('    IOTimerEventSource *vsyncTimer'):display.index('public:', display.index('    IOTimerEventSource *vsyncTimer'))]
refresh = display[display.index('    bool getRefreshAttributes('):display.index('    // A swap the client')]
cpp = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
struct OSObject {};
using IOReturn=int;
constexpr int kIOReturnSuccess=0;
static uint64_t now=1000000,notifications=0;
static unsigned rate=60,locked=1;
static bool addFails=false;
static int liveTimers=0;
static uint64_t mach_absolute_time(){return now;}
static uint64_t mach_continuous_time(){return now+17;}
static void nanoseconds_to_absolutetime(uint64_t ns,uint64_t *ticks){*ticks=ns/10;}
static bool PE_parse_boot_argn(const char *name,void *value,unsigned size){
    assert(size==4);*static_cast<unsigned *>(value)=!strcmp(name,"sheng-vsync")?rate:locked;return true;
}
static void native_legacy_vsync_observed(unsigned,unsigned){}
static void native_legacy_vsync_notify(void *,uint64_t stamp,uint64_t continuous,uint64_t interval){
    assert(stamp==now && continuous==now+17 && interval==1666666);++notifications;
}
struct IOTimerEventSource {
    uint64_t deadline=0;unsigned arms=0;bool cancelled=false;
    static IOTimerEventSource *timerEventSource(OSObject *,void (*)(OSObject *,IOTimerEventSource *)){
        ++liveTimers;return new IOTimerEventSource;
    }
    void wakeAtTime(uint64_t time){deadline=time;++arms;}
    void cancelTimeout(){cancelled=true;}
    void release(){--liveTimers;delete this;}
};
struct IOWorkLoop {
    int addEventSource(IOTimerEventSource *){return addFails?1:0;}
    void removeEventSource(IOTimerEventSource *timer){assert(timer->cancelled);}
    void runAction(IOReturn (*action)(OSObject *,void *,void *,void *,void *),OSObject *owner){action(owner,nullptr,nullptr,nullptr,nullptr);}
};
#define OSSafeReleaseNULL(p) do {if(p)(p)->release();(p)=nullptr;} while(0)
struct IOMobileFramebufferLegacy:OSObject {
    virtual bool getRefreshAttributes(uint64_t *words,bool){if(!words)return false;for(unsigned i=0;i<6;++i)words[i]=100+i;return true;}
};
class NativeLegacyDisplay:public IOMobileFramebufferLegacy {
public:
    unsigned char storage[5600]={};
    bool primary=true,bootMapping=true;
    IOWorkLoop loop;
    IOWorkLoop *getWorkLoop(){return &loop;}
''' + timer + refresh + r'''
    void clients(bool present){const void *head=present?this:nullptr;memcpy(reinterpret_cast<char *>(this)+5592,&head,sizeof head);}
};
int main(){
    NativeLegacyDisplay display;
    addFails=true;display.startVsync();assert(!display.vsyncTimer && !liveTimers);addFails=false;
    rate=241;display.startVsync();assert(!display.vsyncTimer);rate=60;
    display.startVsync();assert(display.vsyncTimer && !display.vsyncArmed && liveTimers==1);
    display.clients(true);display.armVsync();assert(display.vsyncArmed);
    auto timer=display.vsyncTimer;assert(timer->arms==1 && timer->deadline==now+display.vsyncInterval);
    display.armVsync();assert(timer->arms==1);
    now=timer->deadline;display.vsyncTick();assert(notifications==1 && timer->deadline==now+display.vsyncInterval);
    now+=display.vsyncInterval*4;display.vsyncTick();assert(notifications==2 && timer->deadline==now+display.vsyncInterval);
    display.clients(false);display.vsyncTick();assert(!display.vsyncArmed && notifications==2);
    uint64_t words[6]={};assert(display.getRefreshAttributes(words,false));
    assert(words[0]==(1ull<<32)/60 && words[2]==words[0] && words[3]==words[1] && words[4]==104);
    assert(!display.getRefreshAttributes(nullptr,false));
    display.stopVsync();assert(!display.vsyncTimer && !liveTimers);display.stopVsync();
}
'''
with tempfile.TemporaryDirectory(prefix='stage7-check-') as temporary:
    folder = Path(temporary)
    for name, text, compiler, standard in [('compat.c', c, 'cc', 'c11'), ('refresh.cpp', cpp, 'c++', 'c++17')]:
        source = folder / name
        source.write_text(text)
        binary = source.with_suffix('')
        subprocess.run([compiler, '-std=' + standard, '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
        result = subprocess.check_output([str(binary)], text=True)
        if name == 'compat.c':
            rules = runpy.run_path(str(Path(__file__).with_name('prepare-ram-data.py')))['COMPAT_FIXUPS']
            expected = [f'{Path(path).name} {offset:x} {original}' for _, path, offset, original in rules]
            assert result.splitlines() == expected, 'Build-time byte checks must match all kernel rules'
print('PASS: volatile-only exact byte fixups, post-validation hook, display timer lifetime and fixed refresh cadence')
