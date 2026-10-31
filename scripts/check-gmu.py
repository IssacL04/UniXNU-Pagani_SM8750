#!/usr/bin/env python3
"""Check the SM8750 GMU loader with pinned local firmware and a software MMIO peer."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UNIXNU = ROOT.parent / 'UniXNU'
SOC = ROOT.parent / 'UniXNU-sm8750-common/kits/Sm8750Platform'
FW = UNIXNU / 'kits/AdrenoFirmware'
GPU = UNIXNU / 'drivers/Adreno740'

subprocess.run(['python3', ROOT / 'scripts/prepare-gpu-firmware.py'], check=True)
subprocess.run(['python3', ROOT / 'scripts/prepare-gpu-opps.py', '--check'], check=True)
subprocess.run(['python3', ROOT / 'scripts/test-gpu-smmu.py'], check=True)
subprocess.run(['python3', ROOT / 'scripts/test-gpu-presenter.py'], check=True)
subprocess.run(['python3', ROOT / 'scripts/test-gpu-pmap.py'], check=True)
with tempfile.TemporaryDirectory(prefix='sm8750-gmu-') as directory:
    out = Path(directory)
    flags = ['-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
             '-I', str(SOC), '-I', str(FW), '-I', str(GPU), '-I', str(ROOT / 'package')]
    objects = []
    for source in [SOC / 'Sm8750Gmu.c', FW / 'AdrenoFirmware.c',
                   FW / 'AdrenoHfi.c', FW / 'AdrenoHfiStartup.c', FW / 'AdrenoHfiVotes.c',
                   SOC / 'Sm8750GmuCommandDb.c', SOC / 'Sm8750SocInfo.c', SOC / 'Sm8750GpuZap.c', SOC / 'Sm8750GpuPower.c', ROOT / 'package/PaganiGpuVotes.c']:
        obj = out / (source.stem + '.o')
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', *flags,
                        '-DSM8750_GMU_HOST_TEST', '-DADRENO_HFI_HOST_TEST',
                        '-c', source, '-o', obj], check=True)
        objects.append(obj)
    binary = out / 'gmu'
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', *flags,
                    SOC / 'Test/gmu.cpp', GPU / 'NativeAdrenoSha256.cpp',
                    *objects, '-o', binary], check=True)
    subprocess.run([binary, ROOT / '.cache/firmware/pkx110-gpu/gen80000_gmu.bin'], check=True)
    votes = out / 'votes'
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', *flags,
                    SOC / 'Test/gpu-votes.c', *objects, '-o', votes], check=True)
    subprocess.run([votes], check=True)
    zap = out / 'zap'
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', *flags,
                    SOC / 'Test/gpu-zap.c', out / 'Sm8750GpuZap.o', '-o', zap], check=True)
    subprocess.run([zap], check=True)
    power = out / 'power'
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', *flags,
                    SOC / 'Test/gpu-power.c', *objects, '-o', power], check=True)
    subprocess.run([power], check=True)
    socinfo = out / 'socinfo'
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', *flags,
                    SOC / 'Test/socinfo.c', out / 'Sm8750SocInfo.o', '-o', socinfo], check=True)
    subprocess.run([socinfo], check=True)
