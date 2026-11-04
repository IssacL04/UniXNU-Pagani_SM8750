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
cache = 'void NativeGOPPresenter::dropFrames()' + presenter.split('void NativeGOPPresenter::dropFrames()', 1)[1].split('IOReturn NativeGOPPresenter::transfer(', 1)[0]
methods = presenter.split('bool NativeGOPPresenter::offer(', 1)[1].split('extern "C" void native_gop_presenter_set_source', 1)[0]
handoff = 'IOReturn NativeGOPPresenter::handoffCall(' + presenter.split('IOReturn NativeGOPPresenter::handoffCall(', 1)[1].split('IOMemoryDescriptor *NativeGOPPresenter::handoffMemory()', 1)[0]
board = (DRIVERS / 'Stage7Probe/Stage7Probe.cpp').read_text()
startup = board.split('static void startPresenter(', 1)[1].split('static bool console(', 1)[0]
source = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <initializer_list>
#include "NativeGOPWire.h"
#include "NativeGOPMappingCache.h"
#include "../BootProgress/PeripheralStatus.h"
#define NATIVE_GPU_TRACE_OPTIONAL
#include "NativeGpuTrace.h"
static void *IOMalloc(size_t n) {return malloc(n);}
static void IOFree(void *p,size_t) {free(p);}
static bool traceOn=true;
static unsigned pixelPieces;
static NativeGpuPixelHeader lastPixel;
static std::vector<uint8_t> pixelBytes;
extern "C" int native_gpu_trace_enabled() {return traceOn;}
extern "C" void native_gpu_trace_record(uint32_t,uint32_t,const uint64_t *,uint32_t) {}
extern "C" int native_gpu_pixel_put(const NativeGpuPixelPiece *p,uint32_t pid) {
    assert(pid==0 && p->header.stage==3 && p->header.flags==1 && p->header.format==80);
    if(!p->offset)pixelBytes.clear();
    assert(p->offset==pixelBytes.size());lastPixel=p->header;++pixelPieces;
    pixelBytes.insert(pixelBytes.end(),p->data,p->data+p->bytes);return 0;
}
using IOReturn=int;
struct task {};
using task_t=task *;
struct OSObject {};
constexpr task_t TASK_NULL=nullptr;
constexpr int kIOReturnSuccess=0,kIOReturnUnsupported=1,kIOReturnBadArgument=2,kIOReturnBusy=3,
    kIOReturnTimeout=4,kIOReturnNotReady=5,kIOReturnNoMemory=6,kIOReturnAborted=7;
constexpr int kMillisecondScale=1,THREAD_ABORTSAFE=0,THREAD_AWAKENED=1,kIOMapAnywhere=1;
static unsigned taskRefs,doneCalls;
static int doneStatus;
static bool mapFails;
int boot_progress_gpu_band(unsigned *first,unsigned *last) {*first=4;*last=16;return 1;}
static void native_legacy_frame_stage(unsigned,uint64_t){}
static void native_legacy_display_event(unsigned){}
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
    uint32_t pixels[4096]{};
    IOMemoryMap() {++live;}
    void retain() {++refs;}
    uint64_t getVirtualAddress() {return reinterpret_cast<uintptr_t>(pixels);}
    uint64_t getPhysicalAddress() {return 0x90000000;}
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
static uint32_t native_gop_gpu_timing_us[6]={0,0,0,0,0,UINT32_MAX};
static uint64_t native_gop_wait_stats[7],native_gop_map_stats[8];
static void native_legacy_gpu_complete_timed(void *p,int status,uint64_t,uint64_t) {assert(p);++doneCalls;doneStatus=status;}
class NativeGOPPresenter {
public:
    IOMemoryMap *mapping=nullptr;
''' + fields + r'''
    bool offer(void *,IOMemoryDescriptor *,uint64_t,uint32_t,uint32_t,OSObject *surface=nullptr,uint64_t targetOffset=0);
    uint32_t cacheMapping(task_t,OSObject *,IOMemoryDescriptor *,IOMemoryMap **);
    static void handoffClosed(task_t);
    static IOReturn handoffCall(uint32_t,task_t,const void *,size_t,void *,size_t);
};
static NativeGOPPresenter *gHandoff;
''' + cache + r'''
bool NativeGOPPresenter::offer(''' + methods + handoff + r'''
static void lifecycle() {
    IOLock lock;
    NativeGOPPresenter p;p.gate=&lock;IOLock frameLock;p.framesLock=&frameLock;p.scanoutBytes=3*16384;p.online=true;p.gpuMode=true;
    gHandoff=&p;
    p.mode={NGP_VERSION,NGP_BGRX8888,64,64,256,16384};
    IOMemoryDescriptor frame,failedFrame;
    task_t first=reinterpret_cast<task_t>(1),other=reinterpret_cast<task_t>(2);
    NGPSwap swap{};NGPOverlay band{};
    assert(!p.offer(&p,&frame,256,64,64));
    assert(p.waitSwap(nullptr,1,&swap)==kIOReturnBadArgument);
    assert(p.waitSwap(first,1,&swap)==kIOReturnTimeout && taskRefs==1);
    assert(p.waitSwap(other,1,&swap)==kIOReturnBusy && taskRefs==1);
    assert(!p.handoffCall(NGP_METHOD_BAND,first,nullptr,0,&band,sizeof band) && band.first==4 && band.rows==12);
    NGPBand extended{};
    assert(!p.handoffCall(NGP_METHOD_BAND,first,nullptr,0,&extended,sizeof extended) && extended.y0==4 && extended.y1==16);
    assert(!p.offer(&p,&frame,256,64,64,nullptr,16384));
    assert(!p.offer(&p,&frame,252,64,64) && !p.offer(&p,&frame,256,63,64));
    assert(!p.offer(&p,&frame,UINT64_MAX,64,64));
    assert(p.offer(&p,&frame,256,64,64) && frame.refs==2);
    assert(!p.offer(&p,&frame,256,64,64));
    ticks+=123000;
    assert(!p.waitSwap(first,1,&swap) && swap.address && swap.reserved && IOMemoryMap::live==1);
    const auto id=swap.reserved;
    assert(p.completeSwap(other,swap.sequence,0)==kIOReturnBadArgument);
    assert(p.completeSwap(first,swap.sequence+1,0)==kIOReturnBadArgument && !doneCalls);
    p.abandonSwap(other);assert(frame.refs==3 && !doneCalls);
    NGPCompleteTimed timing={{swap.sequence,0,0},11,22,33,44,55,0};
    for(size_t size:{0u,15u,17u,39u,41u})
        assert(p.handoffCall(NGP_METHOD_COMPLETE_SWAP,first,&timing,size,nullptr,0)==kIOReturnBadArgument && !doneCalls);
    timing.reserved=1;
    assert(p.handoffCall(NGP_METHOD_COMPLETE_SWAP,first,&timing,sizeof timing,nullptr,0)==kIOReturnBadArgument);
    timing.reserved=0;timing.done.reserved=1;
    assert(p.handoffCall(NGP_METHOD_COMPLETE_SWAP,first,&timing,sizeof timing,nullptr,0)==kIOReturnBadArgument);
    timing.done.reserved=0;
    assert(p.handoffCall(NGP_METHOD_COMPLETE_SWAP,other,&timing,sizeof timing,nullptr,0)==kIOReturnBadArgument && !doneCalls);
    ticks+=16877000;
    assert(!p.handoffCall(NGP_METHOD_COMPLETE_SWAP,first,&timing,sizeof timing,nullptr,0) && doneCalls==1 && !doneStatus);
    assert(frame.refs==2 && IOMemoryMap::live==1 && native_gop_gpu_completions==1);
    assert(native_gop_gpu_last_ns==17000000 && native_gop_gpu_maps==1);
    const uint32_t expected[]={123,11,22,33,44,55};
    assert(!memcmp(native_gop_gpu_timing_us,expected,sizeof expected));
    // A cache hit must not attempt another task map, even if mapping new memory now fails.
    mapFails=true;
    assert(p.offer(&p,&frame,256,64,64) && !p.waitSwap(first,1,&swap) && swap.reserved==id);
    NGPComplete legacy={swap.sequence,0,0};
    assert(!p.handoffCall(NGP_METHOD_COMPLETE_SWAP,first,&legacy,sizeof legacy,nullptr,0) && doneCalls==2 && native_gop_gpu_map_hits==1);
    assert(native_gop_gpu_timing_us[0]==0 && native_gop_gpu_timing_us[1]==0 && native_gop_gpu_timing_us[5]==UINT32_MAX);
    assert(p.offer(&p,&failedFrame,256,64,64));
    assert(p.waitSwap(first,1,&swap)==kIOReturnTimeout && doneCalls==3 && doneStatus==kIOReturnNoMemory);
    assert(p.gpuClient && taskRefs==2 && frame.refs==2 && failedFrame.refs==1 && IOMemoryMap::live==1);
    p.abandonSwap(first);assert(!taskRefs && frame.refs==1 && !IOMemoryMap::live);
    mapFails=false;IOMemoryDescriptor frames[7];
    assert(p.waitSwap(other,1,&swap)==kIOReturnTimeout);
    for(unsigned i=0;i<7;i++) {
        assert(p.offer(&p,&frames[i],256,64,64) && !p.waitSwap(other,1,&swap));
        assert(swap.reserved);
        assert(!p.completeSwap(other,swap.sequence,0));
    }
    assert(IOMemoryMap::live==6 && frames[0].refs==1 && frames[6].refs==2);
    assert(p.offer(&p,&frames[0],256,64,64) && !p.waitSwap(other,1,&swap) && swap.reserved);
    p.abandonSwap(first);assert(p.swap.offered);
    p.abandonSwap(other);
    assert(!IOMemoryMap::live && !taskRefs && !lock.held);
    for(auto &f:frames)assert(f.refs==1);
    p.abandonSwap(other);assert(!IOMemoryMap::live && !taskRefs);
    uint64_t target=0;
    assert(p.waitSwap(first,1,&swap,&target)==kIOReturnTimeout);
    assert(p.offer(&p,&frame,256,64,64,nullptr,16384));
    assert(!p.waitSwap(first,1,&swap,&target) && target==16384);
    assert(!p.completeSwap(first,swap.sequence,0));
    p.abandonSwap(first);assert(!IOMemoryMap::live && !taskRefs);
    // Sampling follows a successful delivered completion and precedes the next offer.
    p.mapping=new IOMemoryMap;p.capturePixels=true;traceOn=false;
    for(unsigned i=0;i<4096;++i)p.mapping->pixels[i]=i+0xff000000;
    p.captureScanout(1);assert(!pixelPieces && !p.captured);
    traceOn=true;p.mode.stride=252;p.captureScanout(1);assert(!pixelPieces);
    p.mode.stride=256;p.mode.height=65;p.captureScanout(1);assert(!pixelPieces);
    p.mode.height=64;
    assert(p.waitSwap(first,1,&swap)==kIOReturnTimeout);
    assert(p.offer(&p,&frame,256,64,64) && !p.waitSwap(first,1,&swap));
    assert(!pixelPieces && !p.completeSwap(first,swap.sequence,kIOReturnAborted) && !pixelPieces);
    assert(p.offer(&p,&frame,256,64,64) && !p.waitSwap(first,1,&swap));
    assert(!p.completeSwap(first,swap.sequence,0) && pixelPieces==16 && p.captured==1);
    assert(lastPixel.capture==swap.sequence && pixelBytes.size()==16384);
    assert(!memcmp(pixelBytes.data(),p.mapping->pixels,16384));
    p.captureScanout(100);assert(pixelPieces==16);
    ticks+=30000000000ull;p.captureScanout(101);assert(pixelPieces==32);
    ticks+=30000000000ull;p.captureScanout(102);assert(pixelPieces==48);
    ticks+=30000000000ull;p.captureScanout(103);assert(pixelPieces==48);
    p.abandonSwap();p.mapping->release();p.mapping=nullptr;
    assert(!IOMemoryMap::live && !taskRefs);
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
static bool flag,registration=true,initOk=true,attachOk=true,startOk=true;
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
static void startPresenter(''' + startup + r'''
int main() {
    IOService nub;
    startPresenter(&nub);assert(!allocations);
    flag=true;registration=false;startPresenter(&nub);assert(!allocations);
    registration=true;initOk=false;startPresenter(&nub);assert(releases==1 && !gpuPresenter);
    initOk=true;attachOk=false;startPresenter(&nub);assert(releases==2 && !detaches);
    attachOk=true;startOk=false;startPresenter(&nub);assert(releases==3 && detaches==1 && !gpuPresenter);
    startOk=true;startPresenter(&nub);assert(gpuPresenter && allocations==4 && releases==3);
}
'''
with tempfile.TemporaryDirectory(prefix='pagani-presenter-') as directory:
    work = Path(directory)
    for name, content in [('presenter', source + '\nint main() {lifecycle();}\n'), ('startup', startup_source)]:
        src = work / (name + '.cpp')
        src.write_text(content)
        binary = work / name
        subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-Wno-address', '-fsanitize=address,undefined', '-I',
                        str(DRIVERS / 'NativeMobileDisplay'), src, '-o', binary], check=True)
        subprocess.run([binary], check=True)
print('PASS: actual presenter ownership, bounds, completion, map/close fallback and presenter startup lifecycle')
