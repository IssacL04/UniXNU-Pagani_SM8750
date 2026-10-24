# OnePlus 13T first-stage menu guide

This page retains the first-stage `no-sdcc` / `menu-keys` baseline. Current development adds a source XNU profile, DarwinBoot, a read-only FAT payload driver and a single-CPU ADT. The macOS workflow uses `oneplus13t_defconfig` and `kernel payload`. These new paths remain untested on hardware; see the device repository `UniXNU-Pagani_SM8750/README.md` for inputs, artifacts and commands.

The acceptance point for the original menu stage is a OnePlus 13T entering UEFI through a temporary boot method allowed by the device, then displaying and running the UniXNU menu. Stop there. Do not load XNU, mount an Apple root or start iPadOS/macOS userland.

XNU compilation, Apple ADT generation, IPSW, prelinking, trust caches, PMGR, native UFS, GPU and touch drivers can wait. This stage still needs a working UEFI platform, including memory, display or logging, a timer and necessary input. Existing UEFI drivers can be reused; missing interfaces require firmware-layer adaptation.

## Device and current scope

| Item | Information and status |
| --- | --- |
| Target | OnePlus 13T |
| System version | User-reported `16.0.10.500` |
| Android kernel | User-reported `6.6.118` |
| SoC direction | SM8750; checked against user-exported sysinfo |
| Desired result | UEFI entry, visible UniXNU menu and working menu interaction |
| Device inspection in this session | Phone connected through ADB in Windows CMD; no direct connection to this build environment |
| Implementation status | The no-sdcc build displays the menu and counts down on hardware; menu-keys adds side-button support, pending hardware interaction testing |
| User-exported evidence | sysinfo confirms PKX110, project 24821, slot `_b`, DTB/DTBO indices 2 and the AA594 panel |
| Menu application check | Three built-in entries displayed under QEMU/AAVMF; keyboard selection of Restart passed; phone firmware not tested |

The Android Linux `6.6.118` kernel runs the existing OS. This path enters a separate UEFI firmware from the bootloader. It does not install an XNU compatibility module into Android or depend on Linux module ABI. The Android kernel version helps identify hardware references and matching stock images; it need not be rebuilt to display the UniXNU menu.

## 1 The reusable pagani platform

Reference firmware repository `uefi-sheng`, commit `8b7cc5d155ba147f461dea7121e91104544ab99e`, contains:

```text
Resources/Configs/pagani.toml
Platforms/OnePlus/paganiPkg/pagani.dsc
Platforms/OnePlus/paganiPkg/pagani.fdf
Platforms/OnePlus/paganiPkg/Include/DXE.inc
Platforms/OnePlus/paganiPkg/Library/MemoryMapLib/
Platforms/OnePlus/paganiPkg/Library/ConfigurationMapLib/
Silicon/Qualcomm/PakalaPkg/
```

This platform uses the SM8750 Pakala configuration. Its DSC identifies `13s`, `CPH2723` and `pagani`. The status page also identifies OnePlus 13s and reports working display, internal storage and side buttons. Those are reference-project records, not validation of the OnePlus 13T on `16.0.10.500`.

Reuse this structure while checking 13T reservations, XBL/ABL, panel, side buttons and vendor DXE inputs. Changing the product name alone does not complete the adaptation.

The reference status page also specifies an ARB Version 1 condition for 13s. Check the target 13T firmware's rollback constraints. Replacing XBL/ABL, downgrading firmware or changing rollback state is not a default step in this stage.

## 2 Minimum boot chain

```mermaid
flowchart LR
  A[Device bootloader] --> B[BootShim]
  B --> C[UEFI derived from pagani]
  C --> D[BDS]
  D --> E[UniXNU.efi]
  E --> F[Menu and diagnostics]
```

This stage remains inside UEFI. It does not invoke DarwinBoot, call ExitBootServices or enter XNU `start.s`. DarwinBoot's EL1 check, the contiguous XNU window, 4 KiB user ABI and XNU CPU/GIC drivers are outside acceptance here. UEFI's own CPU, GIC and timer initialization must still work.

Embed UniXNU.efi and UniXNUDxe in the same firmware volume for the minimum path. UniXNUDxe registers the application as a `Boot####` option, and BDS starts it. The built-in menu can then be used without writing configuration to Android userdata or an EFI partition.

## 3 Device information to establish first

Once the phone is connected to ADB, begin with read-only queries:

```sh
adb devices -l
adb shell getprop ro.product.model
adb shell getprop ro.product.device
adb shell getprop ro.product.board
adb shell getprop ro.boot.hardware
adb shell getprop ro.build.display.id
adb shell getprop ro.build.fingerprint
adb shell getprop ro.boot.slot_suffix
adb shell getprop ro.boot.flash.locked
adb shell getprop ro.boot.verifiedbootstate
adb shell uname -a
```

These properties identify the device and firmware. They do not independently establish that the bootloader accepts a temporary image. Inspect relevant state in fastboot separately and retain complete results. This stage does not perform unlocking, erasing or flashing.

| Open item | Purpose |
| --- | --- |
| Actual model, device and board identifiers | Establish the relationship between 13T and the pagani reference |
| Bootloader state and temporary boot support | Establish whether `fastboot boot` is usable |
| Stock boot/vendor_boot/DTB inputs matching `16.0.10.500` | Inspect actual image layout, DTB handoff and reservations |
| XBL/ABL and rollback conditions | Check reference firmware prerequisites |
| Actual framebuffer address, pitch, format and panel retention | Keep firmware and menu output visible |
| Side-button to UEFI input path | Make the menu operable |

Inspect the relevant inputs without first extracting an Apple restore image or rebuilding the Android kernel.

## 4 Required change locations

| Location | Reference platform | Local implementation and remaining work |
| --- | --- | --- |
| `Resources/Configs/pagani.toml` | Header v4 and FD settings | Separate `oneplus13t.toml` created; verify the load window on hardware |
| `paganiPkg/Library/MemoryMapLib/` | Reference physical map | Separate 13T library reserves `0xD4E23000–0xD5100000` outside the DXE heaps |
| `paganiPkg/pagani.dsc` | Firmware platform without UniXNU integration | Separate `oneplus13tPkg` includes UniXNU components and library mappings |
| `paganiPkg/Include/DXE.inc` | Module list included by FDF | 13T FDF embeds the application and registrar; FD layout checked |
| `[firmware] packages` | Package search paths | 13T board.toml includes the generic repository's `package/` |
| `Binaries/pagani/` | Device-Binaries submodule inputs | Initialize and verify the reference inputs and their applicability to 13T |
| `scripts/unixnu/bootimg.py` | Baseline verifier assumes the older header layout | v3/v4 checks and DTB-bundle preservation implemented and checked offline |
| UniXNU configuration | Built-in menu works without a file | Add an action-only configuration later if needed |

The firmware commit pins Binaries to `a1501e0c2e642d6ac0d8f52c85af2a67b75a7799`. Cloning only the outer repository does not populate its DXE files. A checkout lacking these inputs cannot perform the complete firmware build directly.

### DSC and FDF integration

Use the already integrated sheng DSC as a reference. Add these entries to the target DSC `[Components]`:

```text
UniXNUPkg/Application/UniXNU/UniXNU.inf
UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
```

Add at least these `[LibraryClasses]` mappings, retaining the platform's existing mappings:

```text
UniXNULib|UniXNUPkg/Library/UniXNULib/UniXNULib.inf
FdtLib|MdePkg/Library/BaseFdtLib/BaseFdtLib.inf
```

Add the same two INF modules to the FDF module list:

```text
INF UniXNUPkg/Application/UniXNU/UniXNU.inf
INF UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
```

Leave DarwinBoot out of this stage. Building an EFI file alone does not make the phone run it. Connect the DSC build, firmware volume and BDS application launch path.

### Display and buttons

The pagani reference defaults to SimpleFbDxe and declares a `1216 × 2640`, 32-bit framebuffer. These are reference settings; verify the scanout base and actual pitch left by the current 13T firmware. Framebuffer reuse needs no XNU display driver, but the panel, power and memory must remain valid throughout UEFI execution.

The no-sdcc build displays the menu on hardware, but ButtonsDxe returns before installing its input interface because OplusProject is absent. The menu-keys build replaces it with a separate 13T KeypadDeviceDxe and reuses the generic KeypadDxe. The exported DT maps volume up to PMK8550 PON RESIN, volume down to PM8550 GPIO6, and power to PON KPDPWR. These produce Up, Down and Enter respectively. Host tests cover reading and debounce; physical key behavior remains unverified.

## 5 Header v4 and DTB bundles

The baseline `bootimg.py::verify()` parses the older header and cannot validate the v4 selected by pagani.toml. The local implementation now checks v3/v4 headers, 4 KiB alignment and signature-region length separately, while retaining legacy address checks.

The historical 13T vendor_boot input contains 13 candidate DTBs. The local packer validates and retains the complete bundle for bootloader hardware selection. This run neither guessed a single tree nor changed the phone's DTBO. Real mkbootimg.py round-trip checks passed for v0, v3 and v4. These checks do not establish device acceptance.

The current menu candidate excludes UFSDxe, SdccDxe, OplusProject and PIL/PILProxy/SPSS and is `out/oneplus13t/boot/menu-keys/boot.img` in the generic repository. Its adjacent boot.json still records `hardware_tested: false`. Device control files are in sibling `UniXNU-Pagani_SM8750/`, and the firmware working copy is `UEFI-Pagani_SM8750/`. They use the oneplus13t board name and separate DSC/FDF files. See the device directory README.md for differences, actual build commands and unresolved hardware conditions.

The new candidate retains the working menu baseline, adds side-button input and disables on-demand ConIn connection so input connects before the menu appears. The default timeout still returns to firmware after 10 seconds. Release all buttons, then briefly press volume down: selection should move down and the countdown should stop. A short power press confirms. If keys do not respond, capture every `13T keys:` log line.

The subsequent sysinfo comparison found that the reference DXE heap covered the phone's hwfence-shmem reservation. The 13T DSC now selects an independent MemoryMapLib with an explicit reserved allocation HOB for that interval and usable heaps on either side. The device directory scripts/check-memory-map.py checks allocations against the exported DT. This does not replace boot-time handoff validation.

## 6 Build scope and host

Building only UEFI applications and firmware does not require the Xcode `iphoneos` SDK used by XNU. The reference firmware documentation recommends Linux. UniXNU package/firmware paths use EDK II, Python, make and LLVM CLANGPDB tools. Package and firmware builds passed in the current Linux workspace.

The driver expects CLANGPDB tools `clang`, `lld-link`, `llvm-lib` and `llvm-rc`. BootShim also uses `llvm-objcopy` and `llvm-nm`. A system clang installation alone may be incomplete. Device USB/fastboot connectivity is a separate check from host compilation.

The original menu-only board.toml defined only `[board]` and `[firmware]`, without `[ipsw]`, `[kernel]`, `[payload]` or `[userdata]`. After initializing submodules and preparing LLVM, Python and BaseTools, use the actual workspace paths from the generic repository:

```sh
./unixnu status -D ../UniXNU-Pagani_SM8750
./unixnu build firmware -D ../UniXNU-Pagani_SM8750 \
  --uefi ../UEFI-Pagani_SM8750 --edk2 ../UEFI-Pagani_SM8750/Mu_Basecore \
  --local-module refer:edk2=../UEFI-Pagani_SM8750/Mu_Basecore -j 4
```

UniXNU was built inside the firmware in this run. Avoid an unqualified `build` or `build all`, which enters the complete flow. See `UniXNU-Pagani_SM8750/README.md` for environment variables and host dependencies.

Pack with the extracted historical 13T vendor_boot DTB bundle:

```sh
./unixnu bootimg -D ../UniXNU-Pagani_SM8750 --uefi ../UEFI-Pagani_SM8750 \
  --dtb ../UniXNU-Pagani_SM8750/.cache/firmware/vendor_boot/dtb --ramdisk none \
  -o out/oneplus13t/boot/xnu-loader/boot.img
```

The DTB input is a historical backup and still needs comparison with the current device. The no-sdcc menu display is now confirmed on hardware; the new side-key image remains a candidate. Other boot paths and vendor-driver compatibility are not covered by that result.

## 7 Menu configuration and observation

Use the built-in menu in Config.c first, without a configuration volume. It includes Return to firmware, Restart and Power off. Removable EFI loaders may also be discovered, so inspect the actual entries.

The built-in configuration executes its default after about ten seconds, normally returning to firmware. An automatic return after showing the menu is not necessarily a crash. Once a readable configuration volume exists, this action-only configuration provides more observation time:

```toml
version = 1

[boot]
timeout = -1
fallback_timeout = 300
default = "exit"

[kits]
autoload = false

[ui]
title = "UniXNU"
layout = "portrait"

[[entry]]
id = "exit"
title = "Return to firmware"
type = "action"
action = "exit"
```

The path is `\EFI\UniXNU\unixnu.toml`. A negative timeout waits for input when an input device exists. Without one, the menu still uses the 300-second fallback. Do not create a `type = "xnu"` entry or supply an Apple kernel/Data seed in this stage.

## 8 Acceptance order and remaining work

| Order | Acceptance point | Then proceed to |
| --- | --- | --- |
| 1 | 13T identity, current firmware, temporary boot and recovery established | Firmware platform selection |
| 2 | Target UEFI inputs complete; FD builds with correct module layout | Image packing |
| 3 | v4 round trip succeeds; BootShim/FD addresses and sizes checked | Temporary hardware boot |
| 4 | Sustained firmware logs or visible UEFI interface | UniXNU application startup |
| 5 | `UNIXNU:` startup and `menu: shown`, or clearly visible UniXNU menu | Input verification |
| 6 | Menu navigation/confirmation works, return behavior is explained and entry repeats | Stage complete |

Without input, record menu display as achieved and menu interaction as remaining. QEMU success or a successful firmware build alone does not complete hardware acceptance.

Step 5 is now confirmed: UniXNU is visible on the phone. Step 6, side-button interaction, remains to be tested. Temporarily boot the new menu-keys/boot.img; the device directory README.md identifies the artifact, key sequence and diagnostic logs. XNU native-driver work remains deferred.

## Sources and later stages

- [Reference pagani platform](https://github.com/UniXNU/uefi-sheng/tree/8b7cc5d155ba147f461dea7121e91104544ab99e/Platforms/OnePlus/paganiPkg)
- [Reference image parameters](https://github.com/UniXNU/uefi-sheng/blob/8b7cc5d155ba147f461dea7121e91104544ab99e/Resources/Configs/pagani.toml)
- [Reference device status](https://github.com/UniXNU/uefi-sheng/blob/8b7cc5d155ba147f461dea7121e91104544ab99e/Status.md#oneplus-13s)
- [UniXNU firmware integration](https://github.com/UniXNU/UniXNU/blob/fb2bb310564ce66779e472a021881cf7c5764919/package/UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.c)
- [Current boot image implementation](https://github.com/UniXNU/UniXNU/blob/fb2bb310564ce66779e472a021881cf7c5764919/scripts/unixnu/bootimg.py)
- [Complete SoC guide](/porting/soc-porting), [UEFI firmware](/porting/uefi-firmware), [Boot configuration](/reference/boot-configuration)
