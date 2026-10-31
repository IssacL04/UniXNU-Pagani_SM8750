/* SPDX-License-Identifier: MIT */
#include "PaganiGpuVotes.h"
#include "PaganiGpuOpps.h"
AdrenoHfiStartupStatus PaganiGpuBuildStartup(const Sm8750GmuVoteInputs *in,
    uint32_t speed,uint32_t soc,AdrenoHfiStartupConfig *out,unsigned *initial,unsigned *bandwidth)
{
    if(!in || !out || !initial || !bandwidth || speed>511)return AdrenoHfiStartupInvalid;
    const PaganiGpuProfile *profile=0;
    for(unsigned i=0;i<sizeof(pagani_gpu_profiles)/sizeof(*pagani_gpu_profiles);++i) {
        const PaganiGpuProfile *p=pagani_gpu_profiles+i;
        if(p->speed_bin!=UINT32_MAX && p->speed_bin!=speed)continue;
        if(p->sku[0] && p->sku[1] && soc!=p->sku[0] && soc!=p->sku[1])continue;
        profile=p;break;
    }
    if(!profile)return AdrenoHfiStartupInvalid;
    AdrenoHfiStartupConfig c={0};uint32_t levels[16],votes[16],dep[16];
    const AdrenoHfiRail *secondary=in->gmxc.data?&in->gmxc:&in->mx;
    for(unsigned i=0;i<profile->count;++i)levels[i]=profile->opps[i].level;
    if(AdrenoHfiGen8Votes(levels,profile->count,&in->gfx,secondary,&in->mx,&in->gbx,votes,dep,16))
        return AdrenoHfiStartupInvalid;
    c.performance_table=AdrenoHfiPerfA8xx;c.gpu_count=profile->count;
    for(unsigned i=0;i<c.gpu_count;++i) {
        c.gpu[i]=(AdrenoHfiPerformanceLevel){profile->opps[i].hz,votes[i]};
        c.gpu_dependency_votes[i]=dep[i];
    }
    c.gmu_count=sizeof(pagani_gmu_opps)/sizeof(*pagani_gmu_opps);
    for(unsigned i=0;i<c.gmu_count;++i)levels[i]=pagani_gmu_opps[i].level;
    if(AdrenoHfiGen8Votes(levels,c.gmu_count,&in->cx,&in->mx,&in->mx,
        &(AdrenoHfiRail){0},votes,dep,16))return AdrenoHfiStartupInvalid;
    for(unsigned i=0;i<c.gmu_count;++i)c.gmu[i]=(AdrenoHfiPerformanceLevel){pagani_gmu_opps[i].hz,votes[i]};
    const Sm8750GmuBcmInput *inputs[]={&in->sh0,&in->mc0,&in->acv};
    AdrenoHfiBcm bcms[3]={{.buswidth=16},{.buswidth=4},{.fixed=1,.perfmode=4,.perfmode_kbps=10687500}};
    for(unsigned i=0;i<3;++i) {
        bcms[i].address=inputs[i]->address;
        if(AdrenoHfiBcmAux(bcms+i,inputs[i]->aux.data,inputs[i]->aux.bytes))return AdrenoHfiStartupInvalid;
    }
    if(AdrenoHfiBuildBandwidth(pagani_gpu_bandwidths,sizeof(pagani_gpu_bandwidths)/sizeof(*pagani_gpu_bandwidths),
        bcms,3,in->cn0_address,&c) || AdrenoHfiStartupValidate(&c))return AdrenoHfiStartupInvalid;
    // shortcut: keep IFPC/ACD off until the board qualifies retention and dynamic power-up lists.
    // Use the board's 525 MHz OPP with its matched voltage and bandwidth votes.
    unsigned selected=profile->initial;
    for(unsigned i=1;i<profile->count;++i)
        if(profile->opps[i].hz<=525000000)selected=i;
    *out=c;*initial=selected;*bandwidth=profile->opps[selected].bandwidth;
    return AdrenoHfiStartupSuccess;
}
