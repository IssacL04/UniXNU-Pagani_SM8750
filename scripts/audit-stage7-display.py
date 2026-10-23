#!/usr/bin/env python3
"""Identify the original generic framebuffer implementation and its abstract leaves."""
import hashlib
import json
from pathlib import Path
import struct
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'kits/NativePrelink'))
from native_prelink import macho,backed_offset,exports
def require(v,why):
    if not v:raise SystemExit(why)
from original_stage7 import OriginalImage
original=OriginalImage(Path(sys.argv[1]))
read=original.read
names=original.names
text=original.family_text('com.apple.iokit.IOMobileGraphicsFamily',
    '2e044ee68c1650397e1435234ca6459206262e4c7ed709cb7131c6f664f9bd9b')
def vptr(pc):
    a,b,c=struct.unpack('<3I',read(pc,12))
    require(a&0x9f00001f==0x90000008 and b&0xffc003ff==0x91000108 and c==0x91004108,'Actual constructor ADRP/ADD/vptr header')
    imm=((a>>5)&0x7ffff)*4+((a>>29)&3)
    if imm&(1<<20):imm-=1<<21
    return (pc&~4095)+(imm<<12)+((b>>10)&4095)+16
def branch(pc):
    w=struct.unpack('<I',read(pc,4))[0];require(w&0xfc000000==0x94000000,'Actual direct constructor call')
    value=w&0x3ffffff;return pc+4*(value-(1<<26) if value&(1<<25) else value)
base_vptr=vptr(0xfffffff00577b324);service_vptr=vptr(0xfffffff00577b51c);legacy_vptr=vptr(0xfffffff0057865d8)
require(branch(0xfffffff0057865fc)==0xfffffff00577b510
        and branch(0xfffffff00577b540)==0xfffffff00577b318,'Actual protected Legacy -> Service -> Framebuffer constructor chain')
base=original.pointers(base_vptr,262);service=original.pointers(service_vptr,262)
require([i for i,(a,b) in enumerate(zip(base,service)) if a!=b]==[0,1,7],'Service adds no generic operational overrides')
legacy=original.pointers(legacy_vptr,358)
require(all(legacy) and read(legacy_vptr+358*8,24)==bytes(24),'Exact nonnull method extent and next aligned vtable boundary')
pure=[i for i,va in enumerate(legacy) if va==names['___cxa_pure_virtual']]
require(pure==[211,213,245,246,306,307,337,338,345],'Actual remaining abstract slots')
changed=[i for i,(a,b) in enumerate(zip(base,legacy)) if a!=b]
require(len(changed)==103 and [i for i in changed if i<168]==[0,1,7,14,21,44,79,85,86,87,111,141,155],
        'Actual original generic implementation overrides')
require(names['__ZN9IOService13newUserClientEP4taskPvjPP12IOUserClient']==base[141],
        'Actual newUserClient override occupies the native four-argument ABI slot')
for i,va in enumerate(legacy):
    if i>=168 and i not in pure:require(text['va']<=va<text['va']+text['size'],'Original family owns inherited generic method')
out=ROOT/'build/display-analysis/mobile-graphics-legacy-abi.json'
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(dict(original_sha256=original.sha256,
    original_family_text_sha256=original.family_sha256,
    metadata_source='Pinned 21H461 original binary; static audit only',
    base_vptr=hex(base_vptr),service_vptr=hex(service_vptr),legacy_vptr=hex(legacy_vptr),
    legacy_instance_bytes=0x18a0,legacy_virtual_entries=358,abstract_slots=pure,
    inherited_generic_changes=changed,source_service_operation_overrides=0,
    original_new_user_client=hex(legacy[141]),original_init=hex(legacy[21]),original_start=hex(legacy[86]),
    new_user_client_abi='IOService::newUserClient(task_t,void*,UInt32,IOUserClient**)',
    original_stop=hex(legacy[87]),original_client_initializer=hex(0xfffffff005776810),
    methods=[dict(slot=i,address=hex(va),abstract=i in pure,prototype_qualified=False) for i,va in enumerate(legacy)],
    static_dispatch_audit=True,legacy_runtime_instance_created=False,backend_contract_complete=False,
    original_instructions_modified=False,desktop=False),indent=2)+'\n')
print('PASS: original Legacy has 358 slots with nine abstract leaves; original generic client/start/dispatch entries identified')
print('Service adds no operational overrides; Legacy initialization/start/backend contracts still require implementation and runtime qualification')
