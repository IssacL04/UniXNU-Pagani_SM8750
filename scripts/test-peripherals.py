#!/usr/bin/env python3
"""Run the portable peripheral tests against the selected component sources."""
import argparse
import ast
from pathlib import Path
import plistlib
import re
import subprocess
import sys
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
    keys=adapter[adapter.index('    void setupPlusKey('):adapter.index('    int setupTouchPower(')]
    (Path(folder)/'PaganiButtons.inc').write_text(keys)
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
    # PaganiPanel: its host tests, and what they cannot reach in the IOService lifecycle: the order of publication in start. The parameters
    # come before anything can look, the grant before backlight-control, and the registration after both.
    panel=tree/'drivers/PaganiPanel'
    start=(panel/'PaganiPanel.cpp').read_text()
    start=start[start.index('    bool start(IOService *provider) override {'):start.index('    IOReturn setProperties(')]
    steps=[start.index(step) for step in ('pagani_panel_start_dcs(','pagani_panel_publishes(','        publish();',
        '"NativeSandboxGrantProcess"','"backlight-control"','&running,true','&panelTimer,timer','registerService();','panelArm(timer,1);')]
    assert steps==sorted(steps),steps
    # The probe (pagani-panel bits 7, 9, 10, 11, 12): A0 before the first read of DSI; the gate, whose logic the host test runs, is the one way to the first DCS
    # and the one way out of the driver to the engine; the thread after the reporter is set, whatever the first DCS gave; its windows read only but for A1's one page,
    # with the one writable window of A0 gone with the call. What the host tests cannot reach of this glue is pinned statement by statement.
    steps=[start.index(step) for step in ('PE_parse_boot_argn("pagani-panel"','if (pagani_panel_gcc_ahb(options)) setGccAhb();','logState("start",&seen)',
        'pagani_panel_start_dcs(&run,options,&seen,&sendMode,sendPacket,forcing,this)','if (run.held) panelLog(earlyLines[1],','reporter->setTimeoutMS(PANEL_REPORT_FIRST_MS);',
        'if (const unsigned stages=pagani_panel_probe_stages(options)) startProbe(stages);','pagani_panel_publishes(')]
    assert steps==sorted(steps),steps
    driver=(panel/'PaganiPanel.cpp').read_text()
    assert 'pagani_panel_first_dcs(' not in driver and 'dsi_panel_packet_mode(' not in driver and 'dsi_panel_command' not in driver
    assert driver.count('pagani_panel_send_packet(&self->run,&io,self->sendMode,type,payload,length)')==1 and driver.count('auto io=self->dsi.io();')==1
    thread=driver[driver.index('static void panelProbeThread('):driver.index('class PaganiPanel ')]
    assert 'windows[i].map(window.base,window.size,i==PANEL_BLOCK_AHB?0:kIOMapReadOnly)' in thread and 'host.display_on=panelProbeDisplay;' in thread
    assert 'static unsigned panelProbeDisplay(void *) {return __atomic_load_n(&requestedPower,__ATOMIC_ACQUIRE);}' in driver
    assert re.findall(r'kernel_thread_start\(',driver)==['kernel_thread_start('] and len(re.findall(r'\.map\(',driver))==3
    a0=driver[driver.index('    void setGccAhb() {'):driver.index('    void startProbe(')]
    assert 'panel_probe_windows[PANEL_BLOCK_GCC]' in a0 and 'auto clock=gcc.io();auto io=dsi.io();' in a0 and 'panel_probe_a0(&clock,&io,panelLog,earlyLines[0]);' in a0 and 'gcc.release();' in a0
    report=driver[driver.index('    static void report(OSObject *owner'):driver.index('    void setGccAhb() {')]
    assert 'for (char *line:self->earlyLines) if (line[0]) {boot_progress_trace(line);line[0]=0;}' in report
    # A failure of the thread or its windows reaches the log after the moment the events ring drops what comes at boot.
    assert 'else panelLog(earlyLines[2],"panel: probe thread failed");' in driver and 'panelLog(earlyLines[0],"panel: a0 map failed")' in a0
    assert 'char earlyLines[3][PANEL_PROBE_LINE]' in driver
    assert thread.index('IOSleep(panel_probe_first_ms(stages));')<thread.index('"panel: probe map failed"')
    # The writer's hold is a word of bits: a plain store here would let go of the USB probe's hold (PaganiBattery BatteryUsb.h), whose reads fall in A1's seconds.
    assert '__atomic_store_n(&pagani_panel_probe_quiet' not in driver and '__atomic_fetch_or(&pagani_panel_probe_quiet,1u' in driver and '__atomic_fetch_and(&pagani_panel_probe_quiet,~1u' in driver
    probe=re.sub(r'//.*','',(panel/'PanelProbe.h').read_text())
    assert probe.count('peripheral_write(')==1 and 'IODelay' not in probe and not re.search(r'#include <(IOKit|kern|mach|libkern|pexpert)',probe)
    for name in ('panel-brightness','panel-power','panel-probe'):
        subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-sanitize-recover=all',
            '-I',str(tree/'kits/Sm8750Platform'),'-I',str(tree/'kits/oneplus13t'),str(panel/'Test'/(name+'.cpp')),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
    # The whole of PaganiPanel.cpp against stubs of the kernel: what start does around the headers, bit 8 above all.
    subprocess.run([sys.executable,str(panel/'Test/panel-start.py'),str(panel),str(tree/'kits/Sm8750Platform'),str(tree/'kits/oneplus13t')],check=True)
    # The display's refresh tick: the cadence's arithmetic, and sheng-vsync at the four places that read it, cut out of the driver as they are.
    display=tree/'drivers/NativeMobileDisplay'
    subprocess.run(['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(display/'Test/display-timing.cpp'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    subprocess.run([sys.executable,str(display/'Test/vsync-boot-arg.py'),str(display)],check=True)
