#!/usr/bin/env python3
"""Apple DT for PKX110 early XNU bring-up, from the exported live.dtb.

Only the boot CPU and GIC are published. DarwinBoot supplies boot_args video
from the live GOP and limits usable RAM to its actual contiguous allocation.
"""
import argparse
import os
import struct
import uuid
import zlib
from pathlib import Path

# sysinfo/live.dtb: /cpus/cpu@0, /soc/interrupt-controller@16000000,
# /soc/timer. Other CPUs and PSCI are deferred until single-core entry works.
GIC_BASE = 0x16000000
GIC_SIZE = 0x10000
GICR_BASE = 0x16080000
GICR_SIZE = 0x200000
GICR_STRIDE = 0x40000
TIMEBASE = 19200000


def node(name, properties=(), children=()):
    properties = [('name', name.encode() + b'\0'), *properties]
    data = struct.pack('<II', len(properties), len(children))
    for key, value in properties:
        if len(key.encode()) > 31:
            raise ValueError('ADT property name exceeds 31 bytes')
        data += struct.pack('<32sI', key.encode(), len(value)) + value + bytes(-len(value) % 4)
    return data + b''.join(children)


def empty_nvram_proxy():
    # Same volatile CHRP layout used by the upstream QEMU/ArmDTPlatform fixture.
    def header(name, size):
        raw = bytearray(struct.pack('<BBH12s', 0x70, 0, size // 16, name))
        checksum = sum(raw)
        while checksum > 255:
            checksum = (checksum & 255) + (checksum >> 8)
        raw[1] = checksum
        return raw

    bank = bytearray(8192)
    bank[:16] = header(b'nvram', 32)
    bank[32:48] = header(b'common', 2064)
    bank[2096:2112] = header(b'free', len(bank) - 2096)
    struct.pack_into('<I', bank, 16, zlib.adler32(bank[20:]))
    return [('nvram-bank-size', struct.pack('<I', len(bank))),
            ('nvram-bank-count', struct.pack('<I', 1)),
            ('nvram-current-bank', bytes(4)), ('nvram-proxy-data', bank)]


def make_tree(memory_size, random_seed, root_match_volume_uuid=None, trust_cache=False, packed_data_ramdisk=False, ipad_identity=False, unique_chip_id=None, chip_id=0x8011):
    if memory_size not in (0x10000000, 0x20000000, 0x40000000) or len(random_seed) != 64:
        raise ValueError('13T probes require 256/512/1024 MiB and a 64-byte random seed')
    if unique_chip_id is not None and not 0 < unique_chip_id < 1 << 64:
        raise ValueError('Platform seed must be a nonzero 64-bit value')
    if ipad_identity and unique_chip_id is None:
        raise ValueError('iPad userspace requires a platform seed for IOPlatformUUID')
    root_matching = []
    if root_match_volume_uuid is not None:
        volume_uuid = str(uuid.UUID(root_match_volume_uuid)).upper()
        xml = ('<dict><key>IOProviderClass</key><string>IOMedia</string>'
               '<key>IOPropertyMatch</key><dict><key>UUID</key><string>' +
               volume_uuid + '</string></dict></dict>\0')
        root_matching = [('root-matching', xml.encode())]
    return node('device-tree', [('model', b'iPad7,1\0' if ipad_identity else b'OnePlus 13T\0'),
                               *([('target-type', b'J120\0')] if ipad_identity else []),
                               ('compatible', b'oneplus,pkx110\0qcom,sm8750\0')], [
        node('chosen', [('random-seed', random_seed), *empty_nvram_proxy(), *root_matching,
                        ('osenvironment', b'main\0'),
                        *([('unique-chip-id', struct.pack('<Q', unique_chip_id)),
                           ('chip-id', struct.pack('<I', chip_id))] if unique_chip_id is not None else []),
                        *([('certificate-production-status', bytes(4)),
                           ('effective-production-status-ap', bytes(4)),
                           ('certificate-security-mode', struct.pack('<I', 1)),
                           ('effective-security-mode-sep', struct.pack('<I', 1)),
                           ('display-scale', struct.pack('<I', 2))] if ipad_identity else []),
                        *([('amfi-only-platform-code', struct.pack('<I', 1))] if trust_cache else []),
                        *([('ephemeral-storage', struct.pack('<I', 1))] if packed_data_ramdisk else []),
                        ('crypto-hash-method', b'sha2-384\0'),
                        ('dram-base', bytes(8)), ('dram-size', bytes(8)),
                        ('darwinboot-memory-size', struct.pack('<Q', memory_size))],
             # AppleImage4 requires the container even without manifest values.
             [node('memory-map', ([('TrustCache', bytes(16))] if trust_cache else []) +
                   ([('PackedRAMDisk', bytes(16))] if packed_data_ramdisk else [])),
              node('manifest-properties')]),
        node('cpus', children=[node('cpu0', [
            ('state', b'running\0'), ('reg', bytes(4)),
            ('device_type', b'cpu\0'), ('compatible', b'arm,armv8\0'),
            ('timebase-frequency', struct.pack('<I', TIMEBASE))])]),
        node('arm-io', [('device_type', b'arm-io\0'),
                        ('#address-cells', struct.pack('<I', 2)),
                        ('#size-cells', struct.pack('<I', 2)),
                        ('ranges', struct.pack('<QQQ', 0, GIC_BASE, GICR_BASE + GICR_SIZE - GIC_BASE))], [
            node('intc', [('compatible', b'arm,gic-v3\0'),
                          ('reg', struct.pack('<4Q', 0, GIC_SIZE, GICR_BASE - GIC_BASE, GICR_SIZE)),
                          ('redistributor-stride', struct.pack('<Q', GICR_STRIDE))])]),
        node('defaults', [('sleep-disabled', struct.pack('<I', 1))]),
        node('options'),
        *([node('buttons', [('compatible', b'buttons\0'), ('device_type', b'buttons\0'),
                           ('button-names', b'hold\0voldown\0volup\0'),
                           ('home-button-type', struct.pack('<I', 2))])] if ipad_identity else []),
        node('product', [('product-name', b'iPad Pro (12.9-inch) (2nd generation)\0' if ipad_identity else b'OnePlus 13T\0'),
                         ('model', b'PKX110\0'),
                         *([('product-description', b'iPad Pro (12.9-inch) (2nd generation)\0'),
                            ('artwork-device-idiom', b'pad\0'),
                            ('artwork-device-subtype', struct.pack('<I', 2732)),
                            ('artwork-scale-factor', struct.pack('<I', 2)),
                            ('artwork-display-gamut', b'P3\0'),
                            ('compatible-device-fallback', b'iPad6,7\0'),
                            ('thin-bezel', struct.pack('<I', 1))] if ipad_identity else [])]),
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dram-size', type=lambda s: int(s, 0), default=0x10000000)
    parser.add_argument('--owned-memory-size', type=lambda s: int(s, 0), default=0x10000000)
    parser.add_argument('--cpu-regs', default='0')
    parser.add_argument('--root-match-volume-uuid')
    parser.add_argument('--trust-cache', action='store_true')
    parser.add_argument('--packed-data-ramdisk', action='store_true')
    parser.add_argument('--ipad-identity', action='store_true')
    parser.add_argument('--unique-chip-id', type=lambda s: int(s, 16))
    parser.add_argument('--chip-id', type=lambda s: int(s, 0), default=0x8011)
    args = parser.parse_args()
    if args.cpu_regs != '0' or args.dram_size != args.owned_memory_size:
        parser.error('Initial profile uses cpu0 and only the DarwinBoot-owned RAM window')
    try:
        data = make_tree(args.owned_memory_size, os.urandom(64), args.root_match_volume_uuid,
                         args.trust_cache, args.packed_data_ramdisk, args.ipad_identity, args.unique_chip_id, args.chip_id)
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(f'13T ADT: {len(data)} bytes, cpu0, GICv3, {TIMEBASE} Hz; hardware untested')


if __name__ == '__main__':
    main()
