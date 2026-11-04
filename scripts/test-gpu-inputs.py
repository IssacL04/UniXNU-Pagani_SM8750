#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Check the A830 board inputs (IMPLEMENTATION_PLAN 0.3 C2).

1. package/PaganiGpuInputs.h equals what scripts/prepare-pagani-gpu-inputs.py derives from the DTS and the recorded runtime
   DT values (always), and from the pinned runtime DTB itself with --live-dtb (a private local file).
2. The real board glue (package/PaganiGpuBoard.cpp) with the real Adreno830 orchestrator (Adreno830Start, Adreno830Status,
   the firmware pins) and the pinned gen80000 images, built for the host with -fsanitize=address,undefined over the module
   doubles of Adreno830 tests/test_start.cpp: pagani-gpu-stop=0 pagani-gpu-status=2 must stop after S0 with the S0 page (the
   board's six level bins, common table, windows and knobs pass the driver's checks); the asynchronous start must do the
   same; a corrupted GMU image must fail S0 at its step. Without the firmware directory the run checks the refusal of the
   weak zero-length images instead.
"""
import argparse
import json
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path

DEVICE = Path(__file__).resolve().parents[1]
PINS = DEVICE / 'scripts/data/sm8750-gpu-inputs.json'
FLAGS = ['-std=c++23', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined']

KERNEL_DOUBLE = r'''
// Host doubles of the kernel services PaganiGpuBoard.cpp uses: boot arguments from a table, a thread that runs inline.
#pragma once
#include <cstdint>
#include <cstring>
using thread_t = void *;
using wait_result_t = int;
using kern_return_t = int;
constexpr kern_return_t KERN_SUCCESS = 0;
using thread_continue_t = void (*)(void *, wait_result_t);
struct BootArgument { const char *name; uint32_t value; };
inline const BootArgument *host_boot_args;
inline unsigned host_threads;
inline bool PE_parse_boot_argn(const char *name, void *value, int size)
{
    for (const BootArgument *a = host_boot_args; a && a->name; ++a)
        if (!std::strcmp(a->name, name) && size == sizeof(uint32_t)) { std::memcpy(value, &a->value, sizeof a->value); return true; }
    return false;
}
inline kern_return_t kernel_thread_start(thread_continue_t body, void *parameter, thread_t *thread)
{
    ++host_threads; *thread = &host_threads; body(parameter, 0); return KERN_SUCCESS;
}
inline void thread_deallocate(thread_t) {}
'''

HARNESS = r'''
#include "XnuMemoryFixture.h"
#include "Adreno830Start.h"
#include "Adreno830Status.h"
#include "HostKernel.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
extern "C" void pagani_gpu_start(void);
const Adreno830Os *test_start_host_os(void);   // Adreno830 tests/test_start.cpp, built with main renamed
int main(int argc, char **argv)
{
    adreno830_set_os(test_start_host_os());
    static const BootArgument stop0[] = {{"pagani-gpu", 1}, {"pagani-gpu-stop", 0}, {"pagani-gpu-status", 2}, {nullptr, 0}};
    static const BootArgument async[] = {{"pagani-gpu-stop", 0}, {"pagani-gpu-status", 1}, {"pagani-gpu-async", 1}, {nullptr, 0}};
    const std::string mode = argc > 1 ? argv[1] : "";
    host_boot_args = mode == "async" ? async : stop0;
    pagani_gpu_start();
    pagani_gpu_start();   // once per boot
    const unsigned rows = adreno830_status_current_mode() >= 2 ? 4 : 1;
    for (unsigned i = 0; i < rows; ++i) std::printf("ROW %s\n", adreno830_status.rows[i]);
    std::printf("STATE %u STAGE %u STEP %#x REASON %u THREADS %u\n", adreno830_status.state, adreno830_status.stage,
                adreno830_status.step, adreno830_status.reason, host_threads);
    return 0;
}
'''

# The rows of a run stopped after S0 (pagani-gpu-status=2): the SoC, fuse and cmd-db values are the module doubles' (the
# hardware reads belong to the device); FW ok and the stop are the real driver's verdict on this board's inputs. Row 0
# ends with the bring-up profile (p1 = annibale, the default).
STOPPED = ['GPU S0 INPUTS STOP ok 0ms p1', 'SOC 618 FC 0 BIN 190 FW ok', 'ARC gfx 16 mx 15 cx 15 gmxc -',
           'BCM SH0 1000/16 MC0 1000/4 ACV 0 CN0 2']


def fail(message):
    raise SystemExit('test-gpu-inputs: ' + message)


def run(command, **kw):
    result = subprocess.run([str(c) for c in command], capture_output=True, text=True, **kw)
    if result.returncode:
        fail(' '.join(map(str, command[:3])) + '...\n' + (result.stdout + result.stderr)[-4000:])
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adreno830', type=Path, default=DEVICE.parent / 'Adreno830', help='Adreno830 checkout')
    parser.add_argument('--unixnu', type=Path, default=DEVICE.parent / 'UniXNU', help='UniXNU checkout (ArmSmmu4K, AdrenoPM4 kits)')
    parser.add_argument('--firmware', type=Path, default=DEVICE / '.cache/firmware/pkx110-gpu')
    parser.add_argument('--live-dtb', type=Path, help='PKX110 runtime DTB: also regenerate and compare PaganiGpuInputs.h')
    args = parser.parse_args()
    checks = 0
    generator = [sys.executable, DEVICE / 'scripts/prepare-pagani-gpu-inputs.py', '--check']
    print(run(generator), end='')
    checks += 1
    if args.live_dtb:
        print(run([*generator, '--live-dtb', args.live_dtb]), end='')
        checks += 1
    else:
        print('SKIP PaganiGpuInputs.h against the runtime DTB itself: no --live-dtb')
    builder = runpy.run_path(str(DEVICE / 'scripts/build-pagani-gpu.py'))
    pins = json.loads(PINS.read_text())['firmware']
    a830 = args.adreno830.resolve()
    firmware = all((args.firmware / name).is_file() for name in pins['files'])
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        include = work / 'include'
        for name in ('IOKit/IOTypes.h', 'IOKit/IOLib.h'):
            (include / name).parent.mkdir(parents=True, exist_ok=True)
            (include / name).write_text('#include "XnuMemoryFixture.h"\n')
        for name in ('kern/thread.h', 'pexpert/pexpert.h'):
            (include / name).parent.mkdir(parents=True, exist_ok=True)
            (include / name).write_text('#include "HostKernel.h"\n')
        (include / 'kern/clock.h').write_text('#include "Adreno830HostClock.h"\n')
        (include / 'HostKernel.h').write_text(KERNEL_DOUBLE)
        (include / 'PaganiGpuFirmwarePins.h').write_text(builder['pins_header'](pins))
        (work / 'harness.cpp').write_text(HARNESS)
        kits = args.unixnu.resolve() / 'kits'
        common = [*FLAGS, '-I', include, '-I', a830 / 'tests', '-I', a830, '-I', a830 / 'platform/sm8750',
                  '-I', kits / 'ArmSmmu4K', '-I', kits / 'AdrenoPM4', '-I', DEVICE / 'package']
        (work / 'doubles.cpp').write_text('#define main test_start_main\n#include "test_start.cpp"\n')
        sources = [DEVICE / 'package/PaganiGpuBoard.cpp', a830 / 'Adreno830Start.cpp', a830 / 'Adreno830Status.cpp',
                   a830 / 'NativeAdrenoFirmware.cpp', a830 / 'NativeAdrenoSha256.cpp', work / 'doubles.cpp', work / 'harness.cpp']

        def binary(name, directory):
            if directory is None:   # the driver's weak zero-length defaults, as in a --no-firmware build
                stub = work / 'empty.cpp'
                stub.write_text('#include <stdint.h>\n' + ''.join(
                    f'extern "C" __attribute__((weak)) const uint8_t {e["symbol"]}[1]={{0}};\n'
                    f'extern "C" __attribute__((weak)) const uint64_t {e["symbol"]}_size=0;\n' for e in pins['files'].values()))
                objects = [stub]
            else:
                assembly, _ = builder['firmware_assembly'](pins, directory, '__DATA,__const')
                (work / f'{name}.S').write_text(assembly)
                run(['xcrun', 'clang', '-c', work / f'{name}.S', '-o', work / f'{name}.o'])
                objects = [work / f'{name}.o']
            output = work / name
            run(['xcrun', 'clang++', *common, '-DADRENO830_HOST_TEST', *sources, *objects, '-o', output])
            return output

        def outcome(program, *arguments):
            lines = run([program, *arguments]).splitlines()
            return [line[4:] for line in lines if line.startswith('ROW ')], lines[-1]

        if firmware:
            program = binary('board', args.firmware)
            rows, state = outcome(program)
            if rows != STOPPED or not state.startswith('STATE 4 STAGE 0 STEP 0x66 REASON 21 THREADS 0'):
                fail(f'pagani-gpu-stop=0: {rows} {state}')
            rows, state = outcome(program, 'async')
            if rows != STOPPED[:1] or not state.startswith('STATE 4 STAGE 0 STEP 0x66 REASON 21 THREADS 1'):
                fail(f'pagani-gpu-async=1: {rows} {state}')
            # One flipped byte in the GMU image: the pinned hash no longer matches, S0 fails at step 0x50.
            corrupt = work / 'corrupt'
            corrupt.mkdir()
            for name in pins['files']:
                data = bytearray((args.firmware / name).read_bytes())
                if name == 'gen80000_gmu.bin':
                    data[len(data) // 2] ^= 1
                (corrupt / name).write_bytes(data)
            pins_copy = json.loads(json.dumps(pins))
            gmu = pins_copy['files']['gen80000_gmu.bin']
            gmu['sha256'] = builder['sha']((corrupt / 'gen80000_gmu.bin').read_bytes())   # embed it anyway
            assembly, _ = builder['firmware_assembly'](pins_copy, corrupt, '__DATA,__const')
            (work / 'corrupt.S').write_text(assembly)
            run(['xcrun', 'clang', '-c', work / 'corrupt.S', '-o', work / 'corrupt.o'])
            run(['xcrun', 'clang++', *common, '-DADRENO830_HOST_TEST', *sources, work / 'corrupt.o', '-o', work / 'bad'])
            rows, state = outcome(work / 'bad')
            if not rows or not rows[0].startswith('GPU S0.50 INPUTS FAIL ') or rows[1] != 'SOC - FC - BIN - FW bad' or \
                    not state.startswith('STATE 3 STAGE 0 STEP 0x50 REASON 2'):
                fail(f'corrupted GMU image: {rows} {state}')
            checks += 3
            print(f'board: S0 passes with the 4 pinned images ({", ".join(pins["files"])}); async start; corrupted GMU refused')
        else:
            print(f'SKIP pinned firmware run: {args.firmware} lacks the gen80000 images')
        rows, state = outcome(binary('nofirmware', None))
        if not rows or not rows[0].startswith('GPU S0.50 INPUTS FAIL ') or not state.startswith('STATE 3 STAGE 0 STEP 0x50 REASON 2'):
            fail(f'no firmware: {rows} {state}')
        checks += 1
    print(f'PASS: {checks} A830 board input checks (generated header, real board glue and orchestrator through S0 on the host)')


if __name__ == '__main__':
    main()
