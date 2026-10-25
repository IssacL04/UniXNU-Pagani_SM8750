#!/usr/bin/env python3
"""Run the actual root-audit checkpoint with controlled kernel inputs."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tree', type=Path, required=True)
args = parser.parse_args()
added = (args.tree / '.cache/xnu-work/bsd/kern/bsd_init.c').read_text()
function = added[added.index('void\nnative_owner_root_checkpoint('):]
function = function[:function.index('\n}\n') + 3]
# Strip the compiler checkpoint, which deliberately uses target-specific registers.
function = re.sub(r'\s*__asm__ volatile\([^;]+;', '', function)
harness = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
typedef unsigned dev_t;
static int supplied, enabled, calls;
static int native_owner_root_readonly;
static dev_t native_owner_root_selected_device;
static char report[256];
static int PE_parse_boot_argn(const char *name, void *out, unsigned size) {
    assert(!strcmp(name, "native-root-audit") && size == sizeof(int));
    *(int *)out = enabled;
    return supplied;
}
static void panic(const char *format, ...) {
    va_list args; va_start(args, format);
    vsnprintf(report, sizeof(report), format, args);
    va_end(args); ++calls;
}
'''
harness += function
harness += r'''
int main(void) {
    native_owner_root_readonly = 1; native_owner_root_selected_device = 0x123;
    supplied = 0; enabled = 1;
    native_owner_root_checkpoint(5, 1, 0x123); assert(calls == 0);
    supplied = 1; enabled = 0;
    native_owner_root_checkpoint(5, 1, 0x123); assert(calls == 0);
    enabled = 1;
    native_owner_root_checkpoint(5, 1, 0x123);
    assert(calls == 1 && !strcmp(report,
      "NATIVE_ROOT binding: apple=5 owner=1 readonly=1 mounted=123 selected=123"));
    native_owner_root_readonly = 0;
    native_owner_root_checkpoint(22, 0, 0x456);
    assert(calls == 2 && !strcmp(report,
      "NATIVE_ROOT binding: apple=22 owner=0 readonly=0 mounted=456 selected=123"));
}
'''
with tempfile.TemporaryDirectory(prefix='root-audit-') as directory:
    source = Path(directory) / 'check.c'
    binary = Path(directory) / 'check'
    source.write_text(harness)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
print('PASS: audit opt-in, accepted and rejected bindings preserve actual diagnostic values')
