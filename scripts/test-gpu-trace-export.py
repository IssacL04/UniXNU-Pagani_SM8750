#!/usr/bin/env python3
"""Exercise the actual bounded RAM Data writer with partial and failed VFS writes."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
code = (root / 'package/PaganiGpuTrace.cpp').read_text()
writer = code[code.index('static int writeSnapshot('):code.index('static void exportThread(')]
source = r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cerrno>
#include <sys/types.h>
#include <vector>
using vfs_context_t=void *;
using vnode_t=void *;
constexpr vnode_t NULLVP=nullptr;
constexpr int FWRITE=1,O_CREAT=2,O_EXCL=4,O_NOFOLLOW=8,UIO_WRITE=1,UIO_SYSSPACE=1,IO_NOAUTH=1;
static int openError,writeError,closeError,progress=65536,closed,opened,allocs;
static std::vector<char> content;
static vfs_context_t vfs_context_kernel() {return reinterpret_cast<void *>(1);}
static void *vfs_context_ucred(vfs_context_t p) {return p;}
static void *vfs_context_proc(vfs_context_t p) {return p;}
static int vnode_open(const char *,int flags,int mode,int,vnode_t *out,vfs_context_t) {
    assert(flags==(FWRITE|O_CREAT|O_EXCL|O_NOFOLLOW) && mode==0600);++opened;
    if(openError)return openError;*out=reinterpret_cast<void *>(2);return 0;
}
static int vnode_close(vnode_t p,int flags,vfs_context_t) {assert(p && flags==FWRITE);++closed;return closeError;}
static int vn_rdwr(int rw,vnode_t p,char *data,int bytes,off_t at,int,int,void *,int *residual,void *) {
    assert(rw==UIO_WRITE && p && at==off_t(content.size()) && bytes<=65536);
    if(writeError)return writeError;
    int n=bytes<progress?bytes:progress;*residual=bytes-n;
    if(n>0)content.insert(content.end(),data,data+n);return 0;
}
static void *IOMalloc(size_t n) {++allocs;return malloc(n);}
static void IOFree(void *p,size_t) {--allocs;free(p);}
static void IOLog(const char *,...) {}
''' + writer + r'''
static uint32_t empty(void *,uint32_t) {return 0;}
static uint32_t oversized(void *,uint32_t n) {return n+1;}
int main() {
    std::vector<char> bytes(200000);for(size_t i=0;i<bytes.size();++i)bytes[i]=i%127;
    progress=997;assert(!writeSnapshot("trace",bytes.data(),bytes.size()));assert(content==bytes && closed==1);
    content.clear();progress=0;assert(writeSnapshot("trace",bytes.data(),bytes.size())==EIO && closed==2);
    progress=-1;assert(writeSnapshot("trace",bytes.data(),bytes.size())==EIO && closed==3);
    writeError=ENOSPC;assert(writeSnapshot("trace",bytes.data(),bytes.size())==ENOSPC && closed==4);
    writeError=0;progress=65536;closeError=EIO;
    assert(writeSnapshot("trace",bytes.data(),bytes.size())==EIO && closed==5);
    openError=EEXIST;assert(writeSnapshot("trace",bytes.data(),bytes.size())==EEXIST && closed==5);
    const int before=opened;
    exportSnapshot("trace",64,empty);exportSnapshot("trace",64,oversized);
    assert(opened==before && allocs==0);
}
'''
with tempfile.TemporaryDirectory(prefix='pagani-trace-export-') as directory:
    work = Path(directory)
    (work / 'test.cpp').write_text(source)
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-Wno-misleading-indentation', '-fsanitize=address,undefined', work / 'test.cpp',
                    '-o', work / 'test'], check=True)
    subprocess.run([work / 'test'], check=True)
print('PASS: partial writes, zero progress, bounds, open/write/close failures and exclusive private export')
