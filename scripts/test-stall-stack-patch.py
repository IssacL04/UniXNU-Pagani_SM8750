#!/usr/bin/env python3
"""Exercise the patched XNU sampler's stack gate across scheduler transitions."""
import os
from pathlib import Path
import subprocess
import tempfile

patch = Path(__file__).resolve().parents[1] / 'patches/xnu/phone-stall-probe.patch'
source = '\n'.join(line[1:] for line in patch.read_text().splitlines()
                   if line.startswith('+') and not line.startswith('+++'))
start = source.index('int\nboot_progress_stall_thread_read(')
function = source[start:source.index('\n}', start) + 2].replace('thread_t thread = handle;', 'thread_t thread = static_cast<thread_t>(handle);')
harness = r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
enum { TH_WAIT=1, TH_RUN=4, TH_TERMINATE=16, TH_TERMINATE2=32 };
struct Thread;
struct Processor { Thread *active_thread; int cpu_id; };
using processor_t=Processor *;
constexpr processor_t PROCESSOR_NULL=nullptr;
struct Thread {
    processor_t last_processor=nullptr;
    uint64_t thread_id=1,wait_event=0,last_run_time=0,last_made_runnable_time=0;
    void *continuation=nullptr;uintptr_t kernel_stack=1;
    unsigned state=0,block_hint=0,active=1,sched_pri=47,base_pri=47;
};
using thread_t=Thread *;
constexpr thread_t THREAD_NULL=nullptr;
using spl_t=int;
static bool locked;
static spl_t splsched(){return 1;}
static void splx(spl_t s){assert(s==1 && !locked);}
static void thread_lock(thread_t){assert(!locked);locked=true;}
static void thread_unlock(thread_t){assert(locked);locked=false;}
static processor_t thread_get_runq(thread_t){return nullptr;}
#define VM_KERNEL_UNSLIDE(x) (x)
#define VM_KERNEL_UNSLIDE_OR_PERM(x) (x)
struct boot_progress_stall_thread {
    uint64_t tid,wait_event,last_run,made_runnable,continuation;
    unsigned kframes,state,hint,active,sched_pri,base_pri;
    int cpu,reserved,user;
};
static unsigned walks;
static void stall_kernel_frames(thread_t,boot_progress_stall_thread *out){assert(locked);++walks;out->kframes=1;}
static int get_user_regs(thread_t){return 0;}
static void stall_regs_copy(int *out,int value){*out=value;}
''' + function + r'''
int main(){
    Thread t;boot_progress_stall_thread out{};
    assert(!boot_progress_stall_thread_read(nullptr,&out));
    for(unsigned state=0;state<64;++state){
        t.state=state;walks=0;
        assert(boot_progress_stall_thread_read(&t,&out));
        const bool stable=(state&(TH_WAIT|TH_RUN|TH_TERMINATE|TH_TERMINATE2))==TH_WAIT;
        assert(walks==unsigned(stable) && out.kframes==unsigned(stable));
    }
    t.state=TH_WAIT;t.kernel_stack=0;walks=0;
    assert(boot_progress_stall_thread_read(&t,&out) && !walks);
    t.kernel_stack=1;t.continuation=&t;
    assert(boot_progress_stall_thread_read(&t,&out) && !walks);
}
'''
with tempfile.TemporaryDirectory(prefix='pagani-stall-stack-') as directory:
    work = Path(directory)
    (work / 'test.cpp').write_text(harness)
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', work / 'test.cpp', '-o', work / 'test'], check=True)
    subprocess.run([work / 'test'], check=True)
print('PASS: only stable waiting threads expose kernel stacks; switching, runnable and terminating threads are skipped')
