"""Read the exact iPadOS 17.7.11 binary using the board's prelink addresses."""
import hashlib
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kits/NativePrelink'))
from native_prelink import backed_offset, exports, macho, unserialize_xml


class OriginalImage:
    slide = 0x1000000

    def __init__(self, path):
        self.data = path.read_bytes()
        self.sha256 = hashlib.sha256(self.data).hexdigest()
        if self.sha256 != 'f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7':
            raise ValueError('Require the pinned 21H461 original kernelcache')
        self.image = macho(self.data)
        self.names = {name: address - self.slide
                      for address, names in exports(self.data, self.image).items() for name in names}

    def read(self, address, size):
        offset = backed_offset(self.image['segments'], address + self.slide, size, len(self.data))
        return self.data[offset:offset + size]

    def pointers(self, address, count):
        return tuple(value - self.slide if value else 0
                     for value in struct.unpack('<' + 'Q' * count, self.read(address, count * 8)))

    def family_text(self, identifier, expected):
        info = next(s for s in self.image['segments'] if s['name'] == '__PRELINK_INFO')
        metadata = unserialize_xml(self.read(info['va'] - self.slide, info['filesize']))
        entry, = [e for e in metadata['_PrelinkInfoDictionary'] if e['CFBundleIdentifier'] == identifier]
        offset = backed_offset(self.image['segments'], entry['_PrelinkExecutableLoadAddr'], 32, len(self.data))
        segment = next(s for s in macho(self.data, offset)['segments'] if s['name'] == '__TEXT_EXEC')
        text = dict(va=segment['va'] - self.slide, size=segment['filesize'])
        self.family_sha256 = hashlib.sha256(self.read(text['va'], text['size'])).hexdigest()
        if self.family_sha256 != expected:
            raise ValueError('Original executable identity mismatch: ' + identifier)
        return text
