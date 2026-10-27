#!/usr/bin/env python3
"""Run the portable peripheral tests against the selected component sources."""
import argparse
import ast
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tree',type=Path,required=True)
tree=parser.parse_args().tree.resolve()
source=tree/'drivers/PaganiInput'
spi=tree/'drivers/QcomGeniSpi'
events=(source/'HidEvents.h').read_text()
xml=re.search(r'static const char xml\[\] =\s*((?:"(?:[^"\\]|\\.)*"\s*)+);',events).group(1)
xml=''.join(ast.literal_eval(s) for s in re.findall(r'"(?:[^"\\]|\\.)*"',xml))
personality,=plistlib.loads(('<plist version="1.0">'+xml+'</plist>').encode())
assert personality['IOClass']=='IOHIDEventDriver' and personality['IOProviderClass']=='IOHIDInterface'
assert personality['CFBundleIdentifier']=='com.apple.iokit.IOHIDFamily'
assert personality['IOPropertyMatch']=={'Product':'Pagani S3910'} and personality['Transport']=='SPI'
assert personality['DeviceUsagePairs']==[{'DeviceUsagePage':13,'DeviceUsage':4}]
assert personality['PrimaryUsagePage']==13 and personality['PrimaryUsage']==4
assert all(personality[k] is True for k in ['Built-In','DisplayIntegrated','DigitizerCollectionDispatch'])
with tempfile.TemporaryDirectory(prefix='pagani-peripherals-') as folder:
    binary=Path(folder)/'peripherals'
    adapter=(source/'PaganiInput.cpp').read_text()
    read=adapter[adapter.index('    int transferTouch('):adapter.index('    static void sleepTouch(')]
    (Path(folder)/'PaganiReadTouch.inc').write_text(read)
    power=adapter[adapter.index('    int setupTouchPower('):adapter.index('    int setupTouch()')]
    (Path(folder)/'PaganiTouchPower.inc').write_text(power)
    objects=[]
    for path in (source/'S3910.c',spi/'GeniSpi.c'):
        obj=Path(folder)/(path.stem+'.o');objects.append(str(obj))
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
            '-c',str(path),'-o',str(obj)],check=True)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
        '-I',folder,'-I',str(source),'-I',str(spi),'-I',str(tree/'kits/Sm8750Platform'),'-I',str(tree/'kits/oneplus13t'),
        str(source/'Test/peripherals.cpp'),*objects,'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
        '-I',str(spi),str(spi/'GeniSpi.c'),str(spi/'Test/geni-spi.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
