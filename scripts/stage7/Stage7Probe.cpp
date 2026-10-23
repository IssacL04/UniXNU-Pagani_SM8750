// SPDX-License-Identifier: BSD-2-Clause-Patent
// Adapted from UniXNU-sheng's LegacyDisplayProbe and KeyStoreProbe for SM8750.
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOUserClient.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/c++/OSKext.h>
#include <pexpert/pexpert.h>
#include <mach/kmod.h>
extern "C" kmod_info_t g_kernel_kmod_info;
extern "C" kern_return_t OSKextLoadKextWithIdentifier(const char *);
extern "C" int boot_progress_display_handoff(void);
extern "C" void boot_progress_display_failed(void);
extern "C" void boot_progress_display_status(const char *,uint64_t);
extern "C" void native_legacy_display_static_init(void) __asm__("__GLOBAL__sub_I_NativeLegacyDisplay.cpp");
extern "C" void native_keyevents_static_init(void) __asm__("__GLOBAL__sub_I_NativeKeyStoreEvents.cpp");
extern "C" IOService *native_legacy_display_allocate(void),*native_keyevents_allocate(void);
static IOService *pendingDisplay;
static bool displayInitialized,ephemeralState;
static uint64_t frames,clients,aksCalls,aksOpens;

static void progress(const char *detail,uint64_t value) {boot_progress_display_status(detail,value);}
static bool enabled(const char *name) {
    unsigned value=0;return PE_parse_boot_argn(name,&value,sizeof value) && value==1;
}
static bool registerClass(void (*initializer)(void)) {
    void *handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if(!handle)return false;
    initializer();return OSMetaClass::postModLoad(handle)==kIOReturnSuccess;
}
static bool console(PE_Video &video) {
    return !PE_current_console(&video) && video.v_baseAddr && video.v_width && video.v_height &&
        video.v_width<=16384 && video.v_height<=16384 && video.v_depth==32 && !video.v_rotate &&
        video.v_rowBytes>=video.v_width*4 && video.v_rowBytes<=UINT64_MAX/video.v_height;
}
extern "C" {
__attribute__((noreturn)) void native_legacy_backend_guard(unsigned slot,void *object,void *caller) {
    panic("SM8750 unsupported display slot %u object %p caller %p",slot,object,caller);
}
bool native_legacy_gop_mapping_observed(IOService *,IOMemoryMap *mapping,uint32_t width,uint32_t height) {
    progress("GOP mapping ready",((uint64_t)width<<32)|height);
    return mapping && mapping->getVirtualAddress();
}
void native_legacy_registration_observed(IOService *) {progress("display registered",1);}
void native_legacy_swap_stage(unsigned) {}
void native_legacy_vsync_observed(unsigned event,unsigned hz) {if(event==4)progress("software display refresh Hz",hz);}
void native_legacy_client_enter(task_t,uint32_t type) {progress("display client enter",type);}
void native_legacy_client_observed(IOReturn status,IOUserClient *) {progress("display client",status?(uint32_t)status:++clients);}
void native_legacy_pm_observed(unsigned stage,IOReturn status,unsigned long) {if(status)progress("display PM error",((uint64_t)stage<<32)|(uint32_t)status);}
void native_legacy_frame_observed(unsigned,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t) {}
void native_legacy_frame_colors_observed(const uint32_t *,const uint64_t *,uint64_t) {}
void native_legacy_swap_validation_observed(bool accepted,unsigned reason,const void *,const void *) {if(!accepted)progress("display swap rejected",reason);}
void native_legacy_surface_rejected(uint64_t,uint64_t,uint32_t format,uint32_t,uint64_t,uint64_t,uint64_t) {progress("surface format rejected",format);}
bool native_legacy_prepare_scanout(void) {return boot_progress_display_handoff()!=0;}
void native_legacy_transfer_observed(IOReturn status,const void *,uint64_t) {
    if(status) {
        // A failed first copy must not permanently hide the diagnostic console.
        if(!frames)boot_progress_display_failed();
        progress("display copy failed",(uint32_t)status);
    } else {++frames;progress("system frame copied",frames);}
}
void native_legacy_copy_timing_observed(uint64_t,uint64_t) {}
void native_legacy_retirement_observed(IOService *) {}
// shortcut: CPU scanout only until the SM8750 GPU and its synchronization are implemented.
bool native_legacy_gpu_offer(void *,IOMemoryDescriptor *,uint64_t,uint32_t,uint32_t) {return false;}
void native_legacy_gpu_fallback_observed(int) {}
void native_keyevents_open_refused(void) {progress("key state open refused",0);}
bool native_aks_state_enabled(void) {return ephemeralState;}
uint32_t native_aks_lock_state(void) {return 0;}
void native_aks_call(uint32_t selector,int32_t result) {++aksCalls;if(result)progress("key operation unavailable",selector);}
void native_aks_opened(void) {++aksOpens;}
}
static void startKeyState(void) {
    if(!enabled("offline-key-events") || !enabled("sheng-aks"))return;
    IORegistryEntry *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
    OSData *data=chosen?OSDynamicCast(OSData,chosen->getProperty("ephemeral-storage")):nullptr;
    uint32_t ephemeral=0;
    if(data && data->getLength()==sizeof ephemeral)memcpy(&ephemeral,data->getBytesNoCopy(),sizeof ephemeral);
    OSSafeReleaseNULL(chosen);
    if(ephemeral!=1)return;
    const OSSymbol *name=OSSymbol::withCString("AppleKeyStore");
    bool absent=name && !OSMetaClass::getMetaClassWithName(name);
    OSSafeReleaseNULL(name);
    IOService *provider=IOService::getResourceService();
    if(!absent || !provider || !registerClass(native_keyevents_static_init))return;
    IOService *service=native_keyevents_allocate();
    bool attached=service && service->init() && service->attach(provider);
    // Publish state queries only after the volatile-storage guard passed.
    ephemeralState=true;
    if(attached && service->start(provider)){progress("volatile key state registered",1);return;}
    ephemeralState=false;
    if(attached)service->detach(provider);
    OSSafeReleaseNULL(service);
    progress("volatile key state failed",0);
}
extern "C" void native_legacy_display_probe(void) {
    if(displayInitialized)return;
    displayInitialized=true;
    progress("display class registration enter",0);
    if(!registerClass(native_legacy_display_static_init)){progress("display class failed",0);return;}
    PE_Video video={};
    if(!console(video)){progress("GOP console unavailable",0);return;}
    progress("display allocation enter",0);
    IOService *display=native_legacy_display_allocate();
    progress("display init enter",display!=nullptr);
    if(display && display->init())pendingDisplay=display;
    else OSSafeReleaseNULL(display);
    progress("display class initialized",pendingDisplay!=nullptr);
}
extern "C" void native_legacy_display_late_probe(void) {
    progress("key state start enter",0);
    startKeyState();
    // Original HID services can register now; no synthetic input device or events.
    progress("IOHIDFamily load enter",0);
    progress("IOHIDFamily load",(uint32_t)OSKextLoadKextWithIdentifier("com.apple.iokit.IOHIDFamily"));
    progress("IOHIDEventDriver load enter",0);
    progress("IOHIDEventDriver matching",(uint32_t)OSKext::loadKextWithIdentifier(
        "com.apple.iokit.IOHIDEventDriver",true,false,kOSKextExcludeNone,kOSKextExcludeNone,nullptr));
    OSDictionary *hidMatching=IOService::serviceMatching("IOHIDResource");
    IOService *hidResource=hidMatching?IOService::waitForMatchingService(hidMatching,5000000000ULL):nullptr;
    progress("IOHIDResource ready",hidResource!=nullptr);
    OSSafeReleaseNULL(hidResource);OSSafeReleaseNULL(hidMatching);
    IOService *display=pendingDisplay;
    pendingDisplay=nullptr;
    if(!display){progress("no initialized display",0);return;}
    progress("IOSurface load enter",0);
    kern_return_t loaded=OSKextLoadKextWithIdentifier("com.apple.iokit.IOSurface");
    OSDictionary *matching=IOService::nameMatching("IOCoreSurfaceRoot");
    IOService *surface=matching?IOService::waitForMatchingService(matching,5000000000ULL):nullptr;
    bool surfaceReady=!loaded && surface;
    OSSafeReleaseNULL(surface);OSSafeReleaseNULL(matching);
    progress("IOSurface ready",surfaceReady);
    PE_Video video={};
    if(!surfaceReady || !console(video)){display->release();return;}
    IOPlatformDevice *nub=new IOPlatformDevice;
    IOService *parent=IOService::getResourceService();
    IORegistryEntry *dtParent=IORegistryEntry::fromPath("/arm-io",gIODTPlane);
    IODeviceMemory *memory=IODeviceMemory::withRange(video.v_baseAddr,video.v_rowBytes*video.v_height);
    OSArray *ranges=OSArray::withCapacity(1);
    const char type[]="display-subsystem";
    OSData *typeData=OSData::withBytes(type,sizeof type);
    bool nubAttached=false,nubStarted=false,dtAttached=false,attached=false,started=false;
    if(nub && parent && dtParent && memory && ranges && typeData && nub->init() && ranges->setObject(memory)) {
        nub->setDeviceMemory(ranges);nub->setName("NativeGOPFramebuffer");
        nubAttached=nub->attach(parent);
        nubStarted=nubAttached && nub->start(parent);
        if(nubStarted && nub->setProperty("device_type",typeData)) {
            nub->setName("gop-display",gIODTPlane);
            dtAttached=nub->attachToParent(dtParent,gIODTPlane);
            SInt32 score=0;
            progress("GOP display probe enter",dtAttached);
            attached=dtAttached && display->probe(nub,&score)==display && display->attach(nub);
            progress("GOP display start enter",attached);
            started=attached && display->start(nub);
        }
    }
    progress("GOP display started",started);
    OSSafeReleaseNULL(ranges);OSSafeReleaseNULL(memory);OSSafeReleaseNULL(typeData);
    if(!started) {
        if(attached)display->detach(nub);
        if(dtAttached)nub->detachFromParent(dtParent,gIODTPlane);
        if(nubStarted)nub->stop(parent);
        if(nubAttached)nub->detach(parent);
        OSSafeReleaseNULL(nub);OSSafeReleaseNULL(display);
    }
    // On success the service and its real framebuffer provider live until reboot.
    OSSafeReleaseNULL(dtParent);
}
