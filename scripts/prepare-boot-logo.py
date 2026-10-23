#!/usr/bin/env python3
"""Decode the pinned IPSW AppleLogo at build time; keep its pixels out of Git.

iBootIm layout: https://github.com/realnp/ibootim/blob/master/ibootim.c
LZSS format: Haruhiko Okumura's freely usable 1989 ring-buffer format.
"""
import argparse
import hashlib
from pathlib import Path
import struct
import zlib

PIN = 'de55e7b7a4eff459118f8a4ec9af79b017cfdbfec4c5b079346e414c68ff1fba'


def decompress(data, size):
    ring = bytearray(b' ' * 4096)
    head, at, flags = 4096 - 18, 0, 0
    result = bytearray()
    while at < len(data):
        flags >>= 1
        if not flags & 0x100:
            flags = data[at] | 0xff00
            at += 1
        needed = 1 if flags & 1 else 2
        if len(data) - at < needed:
            raise ValueError('Truncated LZSS token')
        if flags & 1:
            literal, count = data[at], 1
        else:
            offset = data[at] | ((data[at + 1] & 0xf0) << 4)
            count = (data[at + 1] & 15) + 3
        at += needed
        if len(result) + count > size:
            raise ValueError('LZSS output exceeds image size')
        for index in range(count):
            value = literal if flags & 1 else ring[(offset + index) & 4095]
            result.append(value)
            ring[head] = value
            head = (head + 1) & 4095
    if len(result) != size:
        raise ValueError('LZSS image size mismatch')
    return result


def decode(blob):
    if hashlib.sha256(blob).hexdigest() != PIN:
        raise ValueError('Require the original 21H461 AppleLogo')
    image = blob[50:]  # Exact IM4P envelope of this hash-pinned component.
    magic, checksum, codec, color, width, height, x, y, size = struct.unpack_from('<8sIIIHHhhI', image)
    if (magic, codec, color, width, height) != (b'iBootIm\0', 0x6c7a7373, 0x67726579, 230, 284):
        raise ValueError('Unexpected original logo format')
    if size != len(image) - 64 or zlib.adler32(image[12:]) != checksum:
        raise ValueError('Original logo extent/checksum mismatch')
    raw = decompress(image[64:], width * height * 2)
    pixels = bytes(raw[i] * (255 - raw[i + 1]) // 255 for i in range(0, len(raw), 2))
    return width, height, x, y, pixels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert decompress(b'\x03AB\xee\xf1', 6) == b'ABABAB'
    for malformed, size in ((b'\xff', 1), (b'\x00\x00', 1), (b'\x01a', 0), (b'\x01a', 2)):
        try:
            decompress(malformed, size)
        except ValueError:
            pass
        else:
            raise AssertionError('Malformed LZSS input accepted')
    width, height, x, y, pixels = decode(args.source.read_bytes())
    header = (f'// Generated from pinned 21H461 AppleLogo.\n'
              f'#define BOOT_LOGO_WIDTH {width}\n#define BOOT_LOGO_HEIGHT {height}\n'
              f'#define BOOT_LOGO_X {x}\n#define BOOT_LOGO_Y {y}\n'
              'static const unsigned char boot_logo[] = {\n')
    header += '\n'.join(','.join(map(str, pixels[i:i + 32])) + ',' for i in range(0, len(pixels), 32))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(header + '\n};\n')
    print(f'PASS: original {width}x{height} logo identity, checksum, LZSS extent and alpha')


if __name__ == '__main__':
    main()
