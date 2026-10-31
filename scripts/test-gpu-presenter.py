#!/usr/bin/env python3
"""Exercise the actual scanout ownership and board startup over host peers."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DRIVERS = ROOT.parent / 'UniXNU-Pagani-Drivers/drivers'
presenter = (DRIVERS / 'NativeMobileDisplay/NativeGOPPresenter.cpp').read_text()
fields = presenter.split('    IOMemoryMap *mapping=nullptr;', 1)[1].split('public:', 1)[0]
methods = presenter.split('bool NativeGOPPresenter::offer(', 1)[1].split('extern "C" void native_gop_presenter_set_source', 1)[0]
board = (DRIVERS / 'Stage7Probe/Stage7Probe.cpp').read_text()
startup = board.split('static void startGpuPresenter(', 1)[1].split('static bool console(', 1)[0]
source = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <initializer_list>
#include "NativeGOPWire.h"
using IOReturn=int;
using task_t=void *;
constexpr task_t TASK_NULL=nullptr;
constexpr int kIOReturnSuccess=0,kIOReturnUnsupported=1,kIOReturnBadArgument=2,kIOReturnBusy=3,
    kIOReturnTimeout=4,kIOReturnNotReady=5,kIOReturnNoMemory=6,kIOReturnAborted=7;
constexpr int kMillisecondScale=1,THREAD_ABORTSAFE=0,THREAD_AWAKENED=1,kIOMapAnywhere=1;
static unsigned taskRefs,doneCalls;
static int doneStatus;
static bool mapFails,preserved;
static void native_legacy_overlay_rows(uint32_t *first,uint32_t *rows) {*first=4;*rows=12;}
static void native_legacy_overlay_preserve(int value) {preserved=value;}
static void task_reference(task_t t) {assert(t);++taskRefs;}
static void task_deallocate(task_t t) {assert(t && taskRefs);--taskRefs;}
static uint64_t ticks=10;
static uint64_t mach_absolute_time() {return ticks;}
static void absolutetime_to_nanoseconds(uint64_t v,uint64_t *out) {*out=v;}
static void clock_interval_to_deadline(uint32_t v,int,uint64_t *out) {*out=v;}
struct IOLock {bool held=false;};
static void IOLockLock(IOLock *p) {assert(!p->held);p->held=true;}
static void IOLockUnlock(IOLock *p) {assert(p->held);p->held=false;}
static void IOLockWakeup(IOLock *p,void *,bool) {assert(p->held);}
static int IOLockSleepDeadline(IOLock *p,void *,uint64_t,int) {assert(p->held);return 0;}
struct IOService {};
struct IOMemoryMap {
    static unsigned live;
    unsigned refs=1;
    IOMemoryMap() {++live;}
    void retain() {++refs;}
    uint64_t getVirtualAddress() {return 0x100000;}
    uint64_t getLength() {return 16384;}
    void release() {assert(live && refs);if(!--refs){--live;delete this;}}
};
unsigned IOMemoryMap::live;
struct IOMemoryDescriptor {
    unsigned refs=1;
    void retain() {++refs;}
    void release() {assert(refs);--refs;}
    uint64_t getLength() {return 16384;}
    IOMemoryMap *createMappingInTask(task_t,uint64_t,unsigned) {return mapFails?nullptr:new IOMemoryMap;}
};
#define OSSafeReleaseNULL(p) do {if(p)(p)->release();p=nullptr;}while(0)
static uint64_t native_gop_gpu_offers,native_gop_gpu_completions,native_gop_gpu_failures,native_gop_gpu_abandoned;
static uint64_t native_gop_gpu_last_ns,native_gop_gpu_maps,native_gop_gpu_map_hits;
static uint64_t native_gop_wait_stats[7];
static void native_legacy_gpu_complete(void *p,int status) {assert(p);++doneCalls;doneStatus=status;}
class NativeGOPPresenter {
public:
''' + fields + r'''
    bool offer(void *,IOMemoryDescriptor *,uint64_t,uint32_t,uint32_t);
};
bool NativeGOPPresenter::offer(''' + methods + r'''
static void lifecycle() {
    IOLock lock;
    NativeGOPPresenter p;p.gate=&lock;p.online=true;p.gpuMode=true;
    p.mode={NGP_VERSION,NGP_BGRX8888,64,64,256,16384};
    IOMemoryDescriptor frame,failedFrame;
    task_t first=reinterpret_cast<void *>(1),other=reinterpret_cast<void *>(2);
    NGPSwap swap{};NGPOverlay band{};
    assert(!p.offer(&p,&frame,256,64,64));
    assert(p.waitSwap(nullptr,1,&swap)==kIOReturnBadArgument);
    assert(p.waitSwap(first,1,&swap)==kIOReturnTimeout && taskRefs==1);
    assert(p.waitSwap(other,1,&swap)==kIOReturnBusy && taskRefs==1);
    assert(p.overlay(other,&band)==kIOReturnBusy && !preserved);
    assert(!p.overlay(first,&band) && preserved && band.first==4 && band.rows==12);
    assert(!p.offer(&p,&frame,252,64,64) && !p.offer(&p,&frame,256,63,64));
    assert(!p.offer(&p,&frame,UINT64_MAX,64,64));
    assert(p.offer(&p,&frame,256,64,64) && frame.refs==2);
    assert(!p.offer(&p,&frame,256,64,64));
    assert(!p.waitSwap(first,1,&swap) && swap.address && swap.reserved && IOMemoryMap::live==1);
    const auto id=swap.reserved;
    assert(p.completeSwap(other,swap.sequence,0)==kIOReturnBadArgument);
    assert(p.completeSwap(first,swap.sequence+1,0)==kIOReturnBadArgument && !doneCalls);
    p.abandonSwap(other);assert(frame.refs==3 && !doneCalls && preserved);
    ticks+=17000000;
    assert(!p.completeSwap(first,swap.sequence,0) && doneCalls==1 && !doneStatus);
    assert(frame.refs==2 && IOMemoryMap::live==1 && native_gop_gpu_completions==1);
    assert(native_gop_gpu_last_ns==17000000 && native_gop_gpu_maps==1);
    // A cache hit must not attempt another task map, even if mapping new memory now fails.
    mapFails=true;
    assert(p.offer(&p,&frame,256,64,64) && !p.waitSwap(first,1,&swap) && swap.reserved==id);
    assert(!p.completeSwap(first,swap.sequence,0) && doneCalls==2 && native_gop_gpu_map_hits==1);
    assert(p.offer(&p,&failedFrame,256,64,64));
    assert(p.waitSwap(first,1,&swap)==kIOReturnNoMemory && doneCalls==3 && doneStatus==kIOReturnAborted);
    assert(!p.gpuClient && !taskRefs && frame.refs==1 && failedFrame.refs==1 && !preserved && !IOMemoryMap::live);
    mapFails=false;IOMemoryDescriptor frames[7];
    assert(p.waitSwap(other,1,&swap)==kIOReturnTimeout);
    assert(!p.overlay(other,&band));
    for(unsigned i=0;i<7;i++) {
        assert(p.offer(&p,&frames[i],256,64,64) && !p.waitSwap(other,1,&swap));
        assert((swap.reserved!=0)==(i<6));
        assert(!p.completeSwap(other,swap.sequence,0));
    }
    assert(IOMemoryMap::live==6 && frames[6].refs==1);
    assert(p.offer(&p,&frames[0],256,64,64) && !p.waitSwap(other,1,&swap) && swap.reserved);
    p.abandonSwap(first);assert(p.swap.offered && preserved);
    p.abandonSwap(other);
    assert(!IOMemoryMap::live && !taskRefs && !preserved && !lock.held);
    for(auto &f:frames)assert(f.refs==1);
    p.abandonSwap(other);assert(!IOMemoryMap::live && !taskRefs);
    uint32_t spans[4];
    for(NGPOverlay b: {NGPOverlay{4,12},NGPOverlay{0,0},NGPOverlay{0,64},NGPOverlay{65,1},NGPOverlay{63,UINT32_MAX}}) {
        ngp_visible_rows(64,b,spans);
        unsigned touched[64]={};
        for(unsigned part=0;part<2;part++)for(unsigned y=spans[part*2];y<spans[part*2+1];y++) {assert(y<64);++touched[y];}
        const bool valid=b.first<=64 && b.rows<=64-b.first;
        for(unsigned y=0;y<64;y++)assert(touched[y]==unsigned(!(valid && y>=b.first && y-b.first<b.rows)));
    }
}
'''

startup_source = r'''
#include <cassert>
#include <cstdint>
static bool gpuReady,flag,registration=true,initOk=true,attachOk=true,startOk=true;
static unsigned allocations,releases,detaches;
struct IOService {
    static IOService *getResourceService() {static IOService home;return &home;}
    bool init() {return initOk;}
    bool attach(IOService *) {return attachOk;}
    bool start(IOService *) {return startOk;}
    void detach(IOService *) {++detaches;}
    void release() {++releases;}
};
static IOService *gpuPresenter;
static void native_gop_presenter_static_init() {}
static bool enabled(const char *) {return flag;}
static bool registerClass(void (*)()) {return registration;}
static IOService *native_gop_presenter_create() {++allocations;static IOService p;return &p;}
static void native_gop_presenter_set_source(IOService *,IOService *nub) {assert(nub);}
static void progress(const char *,uint64_t) {}
#define OSSafeReleaseNULL(p) do {if(p)(p)->release();p=nullptr;}while(0)
static void startGpuPresenter(''' + startup + r'''
int main() {
    IOService nub;
    startGpuPresenter(&nub);assert(!allocations);
    flag=true;startGpuPresenter(&nub);assert(!allocations);
    gpuReady=true;registration=false;startGpuPresenter(&nub);assert(!allocations);
    registration=true;initOk=false;startGpuPresenter(&nub);assert(releases==1 && !gpuPresenter);
    initOk=true;attachOk=false;startGpuPresenter(&nub);assert(releases==2 && !detaches);
    attachOk=true;startOk=false;startGpuPresenter(&nub);assert(releases==3 && detaches==1 && !gpuPresenter);
    startOk=true;startGpuPresenter(&nub);assert(gpuPresenter && allocations==4 && releases==3);
}
'''
with tempfile.TemporaryDirectory(prefix='pagani-presenter-') as directory:
    work = Path(directory)
    for name, content in [('presenter', source + '\nint main() {lifecycle();}\n'), ('startup', startup_source)]:
        src = work / (name + '.cpp')
        src.write_text(content)
        binary = work / name
        subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined', '-I',
                        str(DRIVERS / 'NativeMobileDisplay'), src, '-o', binary], check=True)
        subprocess.run([binary], check=True)
print('PASS: actual presenter ownership, bounds, completion, map/close fallback and GPU-ready startup gates')
