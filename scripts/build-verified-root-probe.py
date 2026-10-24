#!/usr/bin/env python3
"""Cross-build a bounded real-XNU crypto probe, with ignored original inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--component', choices=('systemos', 'os'), default='systemos')
parser.add_argument('--negative-volume-uuid', action='store_true', help='Isolated real-signature policy with the wrong signed volume identity')
parser.add_argument('--include-systemos', action='store_true', help='Include both separately verified original OS and SystemOS policies under the same explicit anchor')
parser.add_argument('--duplicate-os-policy', action='store_true', help='Isolated negative bundle with an ambiguous duplicate OS policy')
args = parser.parse_args()
if args.include_systemos and (args.component != 'os' or args.negative_volume_uuid):
    parser.error('The two-volume bundle requires the positive original OS policy')
if args.duplicate_os_policy and not args.include_systemos:
    parser.error('The duplicate control requires the explicit two-volume bundle')
if args.negative_volume_uuid and args.component != 'os':
    parser.error('The actual-root negative control requires the original OS policy')
out = ROOT / (('build/verified-root-os-xnu' if args.component == 'os' else 'build/verified-root-xnu') +
              ('-wrong-uuid' if args.negative_volume_uuid else '') +
              ('-bundle-ambiguous' if args.duplicate_os_policy else '-bundle' if args.include_systemos else ''))
out.mkdir(parents=True, exist_ok=True)
policy_dir = ROOT / ('build/verified-root-' + args.component)
metadata = json.loads((policy_dir / 'verification.json').read_text())
image = ROOT / '.cache/firmware/target-volumes/044-76034-038.dmg'
manifest = policy_dir / 'manifest.bin'
key = policy_dir / 'trusted-key.bin'
expected_digest = ('e5634d04a8ac35f024845f583394e0a35deb26a04cb0c00286a8674e25a9a4f2' if args.component == 'os' else
                   'b4908cde41d23e6bc05e6af51a2c9eeb00cf0f863a6a18b1600c96a3fd70414f')
expected_count = 1483785 if args.component == 'os' else 806400
if (metadata['image_sha256'] != expected_digest or
        metadata['blocks_verified'] != expected_count or not metadata['real_c_signature_and_block_verification'] or
        hashlib.sha256(key.read_bytes()).hexdigest() != metadata['trusted_key_sha256']):
    raise SystemExit('Require the actually verified unchanged original full image and explicit test anchor')
original_manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
if args.negative_volume_uuid:
    envelope = manifest.read_bytes()
    header = bytearray(envelope[:160])
    header[40] ^= 1
    header_file, signature_file = out / 'wrong-uuid-header.bin', out / 'wrong-uuid-signature.bin'
    header_file.write_bytes(header)
    keys = ROOT / 'build/verified-root-host/keys'
    subprocess.run(['openssl', 'dgst', '-sha256', '-sign', keys / 'owner.pem', '-out', signature_file, header_file], check=True)
    subprocess.run(['openssl', 'dgst', '-sha256', '-verify', keys / 'owner-public.pem', '-signature', signature_file,
                    header_file], check=True, capture_output=True)
    signature = signature_file.read_bytes()
    if len(signature) != 384:
        raise SystemExit('Require actual RSA3072 signature for the negative identity')
    manifest = out / 'wrong-uuid-manifest.bin'
    manifest.write_bytes(header + signature + envelope[544:])
indices = [0, 1, metadata['blocks_verified'] // 2, metadata['blocks_verified'] - 1]
samples = out / 'original-samples.bin'
lengths = [4096] * 4
if args.component == 'os':
    indices = metadata['actual_sample_indices']
    lengths = metadata['actual_sample_lengths']
    if lengths != [4096, 4096, 4096, 1536]:
        raise SystemExit('Expected the actual original OS final block length')
    samples.write_bytes((policy_dir / 'original-samples.bin').read_bytes())
else:
    with image.open('rb') as stream, samples.open('wb') as selected:
        for index in indices:
            stream.seek(index * 4096)
            data = stream.read(4096)
            if len(data) != 4096:
                raise SystemExit('Require full original sample blocks')
            selected.write(data)
assembly = out / 'inputs.S'
assembly.write_text('''// Generated ignored crypto inputs; never a boot-root authorization.
.section __DATA_CONST,__const
.balign 8
.globl _verified_root_manifest, _verified_root_manifest_bytes
_verified_root_manifest:
.incbin "''' + str(manifest) + '''"
_verified_root_manifest_bytes:
.quad . - _verified_root_manifest
.globl _verified_root_key
_verified_root_key:
.incbin "''' + str(key) + '''"
.balign 8
.globl _verified_root_sample_indices
_verified_root_sample_indices:
.quad ''' + ','.join(map(str, indices)) + '''
.globl _verified_root_sample_lengths
_verified_root_sample_lengths:
.quad ''' + ','.join(map(str, lengths)) + '''
.globl _verified_root_samples
_verified_root_samples:
.incbin "''' + str(samples) + '"\n')
policy_records = [dict(manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                       image_bytes=struct.unpack_from('<Q', manifest.read_bytes(), 24)[0])]
if args.include_systemos:
    extra_dir = ROOT / 'build/verified-root-systemos'
    extra_meta = json.loads((extra_dir / 'verification.json').read_text())
    if (extra_meta['image_sha256'] != 'b4908cde41d23e6bc05e6af51a2c9eeb00cf0f863a6a18b1600c96a3fd70414f' or
            extra_meta['blocks_verified'] != 806400 or not extra_meta['real_c_signature_and_block_verification'] or
            (extra_dir / 'trusted-key.bin').read_bytes() != key.read_bytes()):
        raise SystemExit('Require separately fully verified original SystemOS under the same independent anchor')
    extra = extra_dir / 'manifest.bin'
    policy_records.append(dict(manifest_sha256=hashlib.sha256(extra.read_bytes()).hexdigest(), image_bytes=3303014400))
    bundle_assembly = '''.balign 8
.globl _verified_root_systemos_manifest
_verified_root_systemos_manifest:
.incbin "''' + str(extra) + '''"
.balign 8
.globl _verified_root_policies, _verified_root_policy_count
_verified_root_policies:
.quad _verified_root_manifest, ''' + str(manifest.stat().st_size) + '''
.quad _verified_root_systemos_manifest, ''' + str(extra.stat().st_size) + '\n'
    if args.duplicate_os_policy:
        bundle_assembly += '.quad _verified_root_manifest, ' + str(manifest.stat().st_size) + '\n'
        policy_records.append(policy_records[0].copy())
    bundle_assembly += '_verified_root_policy_count:\n.quad ' + str(len(policy_records)) + '\n'
    assembly.write_text(assembly.read_text() + bundle_assembly)
recipe = ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/bsd/DEVELOPMENT/bsd_init.o.json'
record = json.loads(recipe.read_text().strip().rstrip(','))
objects = []
for source in (ROOT / 'kits/VerifiedRoot/src/verified_root.c', ROOT / 'kits/VerifiedRoot/adapters/xnu_crypto.c',
               ROOT / 'scripts/qemu-entry/verified-root-probe.c'):
    destination = out / (source.stem + '.o')
    compile_args, command, index = record['arguments'], [], 0
    while index < len(compile_args):
        value = compile_args[index]
        if value == record['file']:
            command.append(str(source))
        elif value == '-o':
            command += ['-o', str(destination)]
            index += 1
        elif value in ('-MF', '-MJ'):
            index += 1
        elif value not in ('-MD', '-MP'):
            command.append(value)
        index += 1
    command += ['-I' + str(ROOT / 'kits/VerifiedRoot/include'), '-Werror', '-Wno-error=missing-include-dirs']
    result = subprocess.run(command, cwd=record['directory'], capture_output=True, text=True)
    (out / (source.stem + '.log')).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit(result.stderr[-3500:])
    objects.append(destination)
sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-isysroot', sdk, '-c',
                assembly, '-o', out / 'inputs.o'], check=True)
objects.append(out / 'inputs.o')
for obj in objects:
    data = obj.read_bytes()
    if struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 1):
        raise SystemExit('Every probe object must remain ordinary ARM64')
    cursor, deployment = 32, None
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        command, length = struct.unpack_from('<II', data, cursor)
        if command == 0x32:
            deployment = struct.unpack_from('<II', data, cursor + 8)
        cursor += length
    if deployment != (2, 0x110000):
        raise SystemExit('Every probe object must target iOS 17')
archive = out / 'libVerifiedRootProbe.a'
archive.unlink(missing_ok=True)
subprocess.run(['xcrun', 'ar', 'rcs', archive, *objects], check=True)
(out / 'inputs.json').write_text(json.dumps(dict(
    manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
    manifest_bytes=manifest.stat().st_size, trusted_key_sha256=metadata['trusted_key_sha256'],
    original_image_sha256=metadata['image_sha256'], original_block_count=metadata['blocks_verified'],
    actual_sample_indices=indices, actual_sample_lengths=lengths, sample_sha256=hashlib.sha256(samples.read_bytes()).hexdigest(),
    negative_volume_uuid=args.negative_volume_uuid,
    policy_bundle=args.include_systemos, duplicate_os_policy=args.duplicate_os_policy,
    policy_records=policy_records,
    signed_volume_uuid=str(uuid.UUID(bytes=manifest.read_bytes()[40:56])).upper(),
    original_manifest_sha256=original_manifest_sha256,
    archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    source_revision='d8b80295118ef25ac3a784134bcf95cd8e88109f',
    boot_root_authenticated=False, original_image_modified=False, test_instrument_only=True), indent=2) + '\n')
print('Built ordinary ARM64/iOS17 probe with original full signed hash table and real XNU crypto bridge')
