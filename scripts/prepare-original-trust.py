#!/usr/bin/env python3
"""Bundle the two pinned, unchanged 21H461 trust-cache modules."""
import argparse
import hashlib
from pathlib import Path
import struct
import sys


def bundle_modules(modules):
    expected = ('da88460e6e513438d5307e5c526f76497a74754476a24da29f239f0c90120fc2',
                'd121ba89167e03aafd00fa687c30cd8ebc4ccafd10c1408adb2ba3de12403651')
    if len(modules) != 2:
        raise ValueError('Require static and System trust-cache modules')
    for module, digest in zip(modules, expected):
        if (hashlib.sha256(module).hexdigest() != digest or len(module) < 24 or
                struct.unpack_from('<I', module)[0] != 2 or
                len(module) != 24 + struct.unpack_from('<I', module, 20)[0] * 24):
            raise ValueError('Require complete, exact original version-2 trust modules')
    bundle = struct.pack('<3I', 2, 12, 12 + len(modules[0])) + b''.join(modules)
    if hashlib.sha256(bundle).hexdigest() != '7416ca4f8377146626bb284e2133c76bee6cb4e3ee0af5d648b186235a7323a7':
        raise ValueError('Original trust bundle differs')
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.tree / 'scripts'))
    from unixnu.ipsw import im4p_payload
    modules = [im4p_payload((args.inputs / name).read_bytes()) for name in
               ('044-76040-038.dmg.trustcache', '044-76034-038.dmg.trustcache')]
    bundle = bundle_modules(modules)
    # Exercise fail-closed handling against truncation, reordering and mutation.
    for bad in ([modules[0][:-1], modules[1]], list(reversed(modules)),
                [bytes([modules[0][0] ^ 1]) + modules[0][1:], modules[1]]):
        try:
            bundle_modules(bad)
        except ValueError:
            continue
        raise AssertionError('Modified trust module accepted')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(bundle)
    print(f'PASS: two unchanged original trust modules, {len(bundle)} bytes; negative checks passed')


if __name__ == '__main__':
    main()
