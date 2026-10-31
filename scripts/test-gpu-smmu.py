#!/usr/bin/env python3
"""Exercise the actual board SMMU checks and status rows with software peers."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT.parent / 'UniXNU'
GPU = MAIN / 'drivers/Adreno740'
board = (ROOT / 'package/PaganiGpu.cpp').read_text()
prepare = 'int prepare_smmu()' + board.split('int prepare_smmu()', 1)[1].split('int prepare_memory()', 1)[0]
status = 'extern "C" int pagani_gpu_status' + board.split('extern "C" int pagani_gpu_status', 1)[1]
report = (GPU / 'NativeAdrenoGmuContext.h').read_text().split('struct NativeAdrenoGmuContextReport {', 1)[1].split('\n};', 1)[0]

source = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <array>
#include "ArmSmmu4KContext.h"
#include "ArmSmmu4KMmio.h"
#include "Sm8750GpuSmmu.h"
#include "NativeAdrenoDiagnostics.h"
#include "PeripheralStatus.h"
using IOReturn=int;
struct NativeAdrenoGmuContextReport {
''' + report + r'''
};
static unsigned reads,writes,fail_read,fail_write,gmu_calls,gpu_calls;
static int bind_rc,gmu_rc,gpu_rc;
static bool bad_actlr,bad_fault;
static unsigned expected_bank=2,expected_slots[3]={0,1,2};
static std::array<uint32_t,0x40000/4> regs;
struct Window {
    volatile uint8_t *cpu=reinterpret_cast<volatile uint8_t *>(regs.data());
    size_t bytes=0x40000;
    int read(size_t at,uint32_t *v) {
        assert(!(at&3) && at<bytes);if(++reads==fail_read)return -1;
        *v=regs[at/4];return 0;
    }
    int write(size_t at,uint32_t v) {
        assert(!(at&3) && at<bytes);if(++writes==fail_write)return -1;
        regs[at/4]=((bad_actlr && (at&0xfff)==4) || (bad_fault && at>=0xc00 && at<0xe00))?0:v;return 0;
    }
};
ArmSmmu4KStatus ArmSmmu4KBindMmio(ArmSmmu4KMmio *,ArmSmmu4KIo *io)
{
    static Window w;
    *io={};io->cookie=&w;io->register_bytes=w.bytes;
    io->read32=[](void *p,size_t at,uint32_t *v) {return static_cast<Window *>(p)->read(at,v);};
    io->write32=[](void *p,size_t at,uint32_t v) {return static_cast<Window *>(p)->write(at,v);};
    io->barrier=[](void *) {return 0;};
    return static_cast<ArmSmmu4KStatus>(bind_rc);
}
static int fill(NativeAdrenoGmuContextReport *r,int rc) {
    r->id2=0x22;r->step=3;r->status=rc;r->program_phase=6;
    r->program_status=8;r->route_phase=2;r->route_status=4;r->mismatch=0x80;return rc;
}
struct Gmu {
    int bringUp(const ArmSmmu4KIo *,unsigned bank,unsigned asid,unsigned slot,uint16_t sid,
                void (*)(uint32_t),NativeAdrenoGmuContextReport *r) {
        assert(bank==expected_bank && asid==1 && slot==expected_slots[2] && sid==5);++gmu_calls;return fill(r,gmu_rc);
    }
};
constexpr uint32_t NativeAdrenoChipA830=0x44050001;
struct Gpu {
    bool done=false;
    bool ready() {return done;}
    int bringUp(const ArmSmmu4KIo *,unsigned bank,unsigned asid,const unsigned *slots,const uint16_t *sids,
                void (*)(uint32_t),NativeAdrenoGmuContextReport *r,uint32_t chip) {
        assert(bank==0 && asid==2 && slots[0]==expected_slots[0] && slots[1]==expected_slots[1] && sids[0]==0 && sids[1]==1);
        assert(chip==NativeAdrenoChipA830);++gpu_calls;done=!gpu_rc;return fill(r,gpu_rc);
    }
};
static struct {
    Window smmu;
    size_t bank_offset[2]{},smmu_offset=0;
    uint32_t smmu_id1=0,smmu_value=0;
    unsigned smmu_context=0;
    ArmSmmu4KMmio smmu_mmio{};
    ArmSmmu4KIo smmu_io{};
    Sm8750GpuSmmuResult smmu_plan{};
    Gmu gmu_context;
    Gpu gpu_context;
    NativeAdrenoGmuContextReport gmu_report{},gpu_report{};
    struct {unsigned stage=0,window=0,offset=0,value=0;} power;
    struct {struct {unsigned phase=0,firmware_init_result=0,hfi_status=0;} load;unsigned protocol_status=0;} gmu_result;
    struct {unsigned gpu_oob_held=0,poisoned=0;} gmu;
    uint64_t requested_hz=0;
} g;
static unsigned activity_reads,activity_value;
static bool activity_error;
static int gmu_read(void *,uint32_t reg,uint32_t *v) {
    assert(reg==0x23b0c && g.gmu.gpu_oob_held && !g.gmu.poisoned);
    ++activity_reads;*v=activity_value;return activity_error?-1:0;
}
static unsigned native_adreno_wc_enabled;
static unsigned long long native_gop_gpu_completions,native_gop_gpu_failures,native_gop_gpu_maps,native_gop_gpu_map_hits;
static const char *current_stage="GPU SMMU";
static int startup_result;
static void stage(const char *name) {current_stage=name;}
extern "C" bool native_adreno_diagnostics(NativeAdrenoDiagnostics *) {return false;}
static void *native_adreno_published_service() {return nullptr;}
''' + prepare + status + r'''
static void reset() {
    g={};regs.fill(0);regs[0x24/4]=0x40000008;regs[0x20/4]=0x48001e08;regs[0]=0x406;
    reads=writes=fail_read=fail_write=gmu_calls=gpu_calls=0;
    bind_rc=gmu_rc=gpu_rc=0;bad_actlr=bad_fault=false;expected_bank=2;
    for(unsigned i=0;i<3;++i)expected_slots[i]=i;
}
static void check_rows(const char *where,const char *detail) {
    char rows[PAGANI_GPU_ROWS][PAGANI_STATUS_BYTES];
    const auto before=regs;unsigned n=reads,w=writes;
    assert(pagani_gpu_status(rows)==1);
    assert(strstr(rows[0],where) && strstr(rows[1],"not published"));
    assert(strstr(rows[2],"SMMU p=") && strstr(rows[3],detail));
    for(auto &row:rows)assert(memchr(row,0,sizeof row));
    assert(n==reads && w==writes && before==regs);
}
int main() {
    reset();assert(!prepare_smmu() && g.gpu_context.ready());
    unsigned normal_reads=reads,normal_writes=writes;
    assert(gmu_calls==1 && gpu_calls==1 && regs[0x20004/4]==0x32b && regs[0x22004/4]==0x32b);
    assert(regs[0x21004/4]==0 && normal_writes==5);
    for(uint32_t id:{0u,1u,0x40010008u,0x70000008u}) {
        reset();regs[0x24/4]=id;startup_result=prepare_smmu();assert(startup_result==-95 && !writes && !gmu_calls);
        check_rows("GPU SMMU select","c=0");
    }
    reset();regs[0x20000/4]=1;assert(prepare_smmu()==-16 && !writes);
    reset();regs[0x22000/4]=1;expected_bank=3;assert(!prepare_smmu() && regs[0x22000/4]==1);
    reset();for(unsigned i=2;i<8;++i)regs[(0x20000+i*0x1000)/4]=1;
    assert(prepare_smmu()==-28 && !writes);
    // Inherited live route in slot 2 and bank 2: preserve it and choose slot 3/bank 3.
    reset();regs[0x808/4]=0x80000020;regs[0xc08/4]=2;expected_bank=3;expected_slots[2]=3;
    assert(!prepare_smmu() && regs[0x808/4]==0x80000020 && regs[0xc08/4]==2);
    // Exact and masked SID conflicts are rejected before any write.
    for(uint32_t smr:{0x80000000u,0x80000001u,0x80000005u,0x80070004u}) {
        reset();regs[0x808/4]=smr;assert(prepare_smmu()==-16 && !writes);
    }
    reset();regs[0x808/4]=0x80000020;regs[0xc08/4]=0;
    assert(prepare_smmu()==-16 && !writes); // inactive bank 0 still has a live owner
    reset();for(unsigned i=0;i<8;++i)regs[(0x800+i*4)/4]=0x80000020+i;
    assert(prepare_smmu()==-28 && !writes);
    // EXIDS uses S2CR.EXIDVALID, not SMR bit 31, for validity.
    reset();regs[0x20/4]|=0x100;regs[0]|=8;regs[0x808/4]=0x80000020;
    assert(!prepare_smmu());
    reset();regs[0x20/4]|=0x100;regs[0]|=8;regs[0xc08/4]=0x400;regs[0x808/4]=5;
    assert(prepare_smmu()==-16 && !writes);
    for(unsigned i=1;i<=normal_reads;++i) {
        reset();fail_read=i;assert(prepare_smmu()==-5 && !gmu_calls && reads==i);
    }
    for(unsigned i=1;i<=normal_writes;++i) {
        reset();fail_write=i;assert(prepare_smmu()==-5 && !gmu_calls && writes==i);
    }
    reset();bad_fault=true;assert(prepare_smmu()==-5 && writes==1 && !gmu_calls);
    reset();bad_actlr=true;assert(prepare_smmu()==-5 && writes==4 && !gmu_calls);
    check_rows("GPU SMMU ACTLR","c=0");
    reset();bind_rc=ArmSmmu4KArgument;assert(prepare_smmu()==bind_rc && !gmu_calls && !writes);
    reset();gmu_rc=-60;startup_result=prepare_smmu();assert(startup_result==-60 && gmu_calls==1 && !gpu_calls);
    check_rows("GPU SMMU GMU","c=1 s=3 p=6/8 r=2/4 mm=80");
    reset();gpu_rc=-70;startup_result=prepare_smmu();assert(startup_result==-70 && gmu_calls==1 && gpu_calls==1);
    check_rows("GPU SMMU GPU","c=2 s=3 p=6/8 r=2/4 mm=80");
    reset();assert(!prepare_smmu());char rows[PAGANI_GPU_ROWS][PAGANI_STATUS_BYTES];
    assert(pagani_gpu_status(rows)==1 && strstr(rows[2],"P step=") && strstr(rows[3],"GMU p="));
    assert(!activity_reads);
    startup_result=0;g.gmu.gpu_oob_held=1;g.requested_hz=222000000;
    assert(pagani_gpu_status(rows)==1 && !strcmp(rows[4],"CLK req=222MHz busy=0 SPactive=?/6"));
    activity_value=1u<<23;
    assert(pagani_gpu_status(rows)==1 && strstr(rows[4],"busy=1"));
    activity_error=true;
    assert(pagani_gpu_status(rows)==1 && strstr(rows[4],"busy=?") && activity_reads==3);
    g.gmu.poisoned=1;
    assert(pagani_gpu_status(rows)==1 && !rows[4][0] && activity_reads==3);
    puts("PASS: SMMU selection/failure paths, no startup diagnostic MMIO, guarded Gen8 activity and requested clock labels");
}
'''
with tempfile.TemporaryDirectory(prefix='pagani-smmu-') as directory:
    work = Path(directory)
    test = work / 'smmu.cpp'
    test.write_text(source)
    binary = work / 'smmu'
    soc = ROOT.parent / 'UniXNU-sm8750-common/kits/Sm8750Platform'
    obj = work / 'plan.o'
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I', str(MAIN / 'kits/ArmSmmu4K'),
                    '-c', soc / 'Sm8750GpuSmmu.c', '-o', obj], check=True)
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I', str(MAIN / 'kits/ArmSmmu4K'), '-I', str(GPU),
                    '-I', str(ROOT.parent / 'UniXNU-Pagani-Drivers/drivers/BootProgress'),
                    '-I', str(soc), str(test), str(obj), '-o', str(binary)], check=True)
    subprocess.run([binary], check=True)
