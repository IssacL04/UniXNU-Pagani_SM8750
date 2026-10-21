#!/usr/bin/env python3
"""Exercise XNU's real panic wrappers and entry hook with the host renderer."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def function(source, name):
    start = source.index('\nvoid\n' + name + '(') + 1
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('xnu', type=Path, help='Patched XNU source directory')
parser.add_argument('--font', type=Path, required=True)
args = parser.parse_args()
source = (args.xnu / 'osfmk/kern/debug.c').read_text()
entry = function(source, 'panic_trap_to_debugger')
assert entry.index('boot_progress_panic(') < entry.index('iotrace_disable()')
# Keep the actual entry prefix; the rest needs live kernel debugger machinery.
entry = entry[:entry.index('#if defined(__x86_64__)')]
entry = '\n'.join(line for line in entry.splitlines() if not line.startswith('#pragma'))
entry += '\n(void)ctx; (void)panic_data_ptr; original_path++;\n}\n'
fixture = '''
#define main console_test_main
#include "console.c"
#undef main
typedef unsigned char uuid_t[16];
#define DEBUGGER_INTERNAL_OPTIONS_MASK 0x200ULL
static unsigned original_path, data_calls;
static void ext_paniclog_panic_with_data(uuid_t uuid,void *addr,uint32_t length) {
    assert(uuid[0]==0x5a && addr && length==7); data_calls++;
}
'''
fixture += entry
fixture += '\n'.join(function(source, name) for name in ('panic', 'panic_with_options', 'panic_with_data'))
fixture += '''
int main(void) {
    enum { W=1216, H=2640 };
    uint32_t *pixels=calloc(W*H,sizeof(*pixels)); assert(pixels);
    boot_args args={.virtBase=0xfffffff007004000ULL,.physBase=0xc0004000,.memSize=0x10000000,
        .Video={(uintptr_t)pixels,1,W*4,W,H,32}};
    early_boot_progress_init(&args);
    panic("plain %s %u %llx", "argument", 41U, 0xfedcba9876543210ULL);
    assert(!strcmp(boot_progress_panic_text,"plain argument 41 fedcba9876543210"));
    assert(panic_state && !panic_clipped);
    early_boot_progress_init(&args);
    panic_with_options(9,(void *)0x1234,0x240,"options %s %u %llx", "argument", 43U, 0x100000001ULL);
    assert(!strcmp(boot_progress_panic_text,"options argument 43 100000001"));
    early_boot_progress_init(&args);
    uuid_t uuid={0x5a}; char data[7]={0};
    panic_with_data(uuid,data,sizeof(data),"data %s %u %llx", "argument", 47U, 0x1122334455667788ULL);
    assert(!strcmp(boot_progress_panic_text,"data argument 47 1122334455667788"));
    assert(data_calls==1 && original_path==3);
    early_boot_progress_init(&args); early_boot_progress_suspend();
    panic("unmapped framebuffer");
    assert(original_path==4 && !panic_state && !boot_progress_panic_text[0]);
    free(pixels);
    puts("PASS: real XNU panic/with_options/with_data wrappers, native va_list, early common hook and inactive fallback");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='13t-panic-entry-') as name:
    work = Path(name)
    (work / 'panic.c').write_text(fixture)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I', str(Path(__file__).resolve().parent), '-I', str(args.font.resolve()),
                    str(work / 'panic.c'), '-o', str(work / 'panic')], check=True)
    subprocess.run([str(work / 'panic')], env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'), check=True)
