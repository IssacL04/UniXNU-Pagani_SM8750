// SPDX-License-Identifier: MIT
// Optional one-shot export to the board's volatile Data volume.
#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/vnode.h>
#include <sys/uio.h>
#include <sys/fcntl.h>
#include <sys/errno.h>
#include "NativeGpuTrace.h"

static int writeSnapshot(const char *path,const void *data,uint32_t bytes) {
    vfs_context_t ctx=vfs_context_kernel();
    vnode_t vnode=NULLVP;
    const int flags=FWRITE|O_CREAT|O_EXCL|O_NOFOLLOW;
    int error=vnode_open(path,flags,0600,0,&vnode,ctx);
    if(error)return error;
    for(uint32_t at=0;at<bytes;) {
        const int count=bytes-at>65536?65536:int(bytes-at);
        int residual=count;
        error=vn_rdwr(UIO_WRITE,vnode,(caddr_t)data+at,count,at,UIO_SYSSPACE,IO_NOAUTH,
                      vfs_context_ucred(ctx),&residual,vfs_context_proc(ctx));
        if(error)break;
        if(residual<0 || residual>=count){error=EIO;break;}
        at+=count-residual;
    }
    const int closed=vnode_close(vnode,FWRITE,ctx);
    return error?error:closed;
}
static void exportSnapshot(const char *path,uint32_t capacity,uint32_t (*snapshot)(void *,uint32_t)) {
    void *data=IOMalloc(capacity);
    if(!data){IOLog("Pagani GPU trace allocation failed: %s\n",path);return;}
    const uint32_t bytes=snapshot(data,capacity);
    const int error=bytes && bytes<=capacity?writeSnapshot(path,data,bytes):EINVAL;
    IOLog("Pagani GPU trace export %s bytes=%u error=%d (volatile Data)\n",path,bytes,error);
    IOFree(data,capacity);
}
static void exportThread(void *argument,wait_result_t) {
    IOSleep(uint32_t(reinterpret_cast<uintptr_t>(argument))*1000);
    const uint32_t traceBytes=sizeof(NativeGpuTraceHeader)+sizeof(NativeGpuTraceRecord)*
        (NativeGpuTraceCapacity+NativeGpuTraceMetadata+NativeGpuPixelSlots*NativeGpuCaptureRecords);
    exportSnapshot("/private/var/root/gpu.trace.bin",traceBytes,native_gpu_trace_snapshot);
    exportSnapshot("/private/var/root/gpu.pixels.bin",16+NativeGpuPixelSlots*
                   (sizeof(NativeGpuPixelHeader)+NativeGpuPixelBytes),native_gpu_pixel_snapshot);
    thread_terminate(current_thread());
}
extern "C" void pagani_gpu_trace_start() {
    if(!native_gpu_trace_enabled())return;
    unsigned seconds=180;
    PE_parse_boot_argn("pagani-gpu-export",&seconds,sizeof(seconds));
    if(!seconds || seconds>3600)return;
    thread_t thread=THREAD_NULL;
    const kern_return_t error=kernel_thread_start(exportThread,reinterpret_cast<void *>(uintptr_t(seconds)),&thread);
    if(error==KERN_SUCCESS)thread_deallocate(thread);
    else IOLog("Pagani GPU trace thread failed: %d\n",error);
}
