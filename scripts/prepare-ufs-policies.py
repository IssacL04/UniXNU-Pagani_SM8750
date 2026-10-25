#!/usr/bin/env python3
"""Prepare signed policies for the exact OS windows already deployed to unixnu."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import plistlib
import runpy
import subprocess
import uuid


class View(ctypes.Structure):
    _fields_ = [('hashes', ctypes.c_void_p), ('image_bytes', ctypes.c_uint64),
                ('block_count', ctypes.c_uint64), ('generation', ctypes.c_uint64),
                ('volume_uuid', ctypes.c_uint8 * 16), ('image_sha256', ctypes.c_uint8 * 32)]


def prepare(tree, inputs, openssl):
    kit = tree / 'kits/PaganiVerifiedRoot'
    host = tree / 'build/verified-root-host'
    # Reuse the real parser/signature/block tests and their private local build key.
    subprocess.run(['python3', kit / 'tests/check.py', '--output', host,
                    '--openssl-prefix', openssl], check=True)
    make = runpy.run_path(str(kit / 'tools/manifest.py'))['make']
    native = ctypes.CDLL(str(host / 'verified-root.dylib'))
    native.vr_host_open.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                    ctypes.c_uint64, ctypes.POINTER(View)]
    native.vr_host_block.argtypes = [ctypes.POINTER(View), ctypes.c_uint64,
                                     ctypes.c_void_p, ctypes.c_size_t]
    windows = (
        ('os', '044-76040-038.dmg', 6077580800, '04769D26-2CA0-4825-B443-E2E5F88300F2',
         '3f99b859c9728379110b66657c7b15285bcb1925ad8b5726542e2cdcf8b1028d',
         'e5634d04a8ac35f024845f583394e0a35deb26a04cb0c00286a8674e25a9a4f2'),
        ('systemos', '044-76034-038.dmg', 3303014400, '8846FE78-2910-4297-AF97-D59BB6F8FC16',
         'b4908cde41d23e6bc05e6af51a2c9eeb00cf0f863a6a18b1600c96a3fd70414f',
         'b4908cde41d23e6bc05e6af51a2c9eeb00cf0f863a6a18b1600c96a3fd70414f'),
    )
    for name, filename, size, identity, source_digest, raw_digest in windows:
        source = inputs / filename
        with source.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != source_digest:
                raise ValueError(f'{name}: IPSW input hash mismatch')
        device = None
        if name == 'os':
            attached = plistlib.loads(subprocess.check_output([
                'hdiutil', 'attach', '-nomount', '-readonly', '-noautofsck', '-plist', source]))
            device, = [e['dev-entry'] for e in attached['system-entities']
                       if e.get('content-hint') == 'GUID_partition_scheme']
            raw = Path(device.replace('/dev/disk', '/dev/rdisk'))
        else:
            raw = source
        out = tree / ('build/verified-root-' + name)
        try:
            with raw.open('rb') as stream:
                record = make(stream, size, host / 'keys/owner.pem', host / 'keys/owner-public.pem',
                              uuid.UUID(identity), 1, out)
            if record['image_sha256'] != raw_digest:
                raise ValueError(f'{name}: decoded image differs from the deployed window')
            envelope = ctypes.create_string_buffer((out / 'manifest.bin').read_bytes())
            key = ctypes.create_string_buffer((out / 'trusted-key.bin').read_bytes())
            view = View()
            if native.vr_host_open(envelope, len(envelope) - 1, key, 1, ctypes.byref(view)):
                raise ValueError(f'{name}: C signature verification failed')
            if view.image_bytes != size or bytes(view.volume_uuid) != uuid.UUID(identity).bytes:
                raise ValueError(f'{name}: signed geometry or identity mismatch')
            indices = [0, 1, view.block_count // 2, view.block_count - 1]
            samples, lengths, complete = [], [], hashlib.sha256()
            with raw.open('rb') as stream:
                for index in range(view.block_count):
                    block = stream.read(min(4096, size - index * 4096))
                    if native.vr_host_block(ctypes.byref(view), index, block, len(block)):
                        raise ValueError(f'{name}: C block verification failed at {index}')
                    complete.update(block)
                    if index in indices:
                        samples.append(block.ljust(4096, b'\0'))
                        lengths.append(len(block))
                if stream.read(1) or complete.hexdigest() != raw_digest:
                    raise ValueError(f'{name}: complete readback mismatch')
            (out / 'original-samples.bin').write_bytes(b''.join(samples))
            record.update(blocks_verified=view.block_count, actual_sample_indices=indices,
                          actual_sample_lengths=lengths, real_c_signature_and_block_verification=True,
                          host_only=True, boot_root_authenticated=False, hardware_tested=False)
            (out / 'verification.json').write_text(json.dumps(record, indent=2) + '\n')
            print(f'PASS: {name}: pinned image, actual RSA and {view.block_count} blocks verified')
        finally:
            if device:
                subprocess.run(['hdiutil', 'detach', device], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--openssl-prefix', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.tree.resolve(), args.inputs.resolve(), args.openssl_prefix.resolve())
