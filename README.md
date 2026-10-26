# OnePlus 13T / PKX110 (SM8750)

This community port uses UniXNU format 2: ARM64, the pinned SM8750 common repository, iPadOS 17.7.11 (21H461), and this device profile. The source drivers remain together in [UniXNU-Pagani-Drivers](https://github.com/IssacL04/UniXNU-Pagani-Drivers); `modules/Pagani` pins one commit. Community component metadata and recipes live in the maintained [main fork](https://github.com/IssacL04/UniXNU_Enc3l).

Builds 39 and 48 reached the iPadOS UI on a OnePlus 13T. UFS root reads and CPU framebuffer presentation were observed; build 48 later panicked on a UFS read timeout. Data is a volatile RAM seed. Touch, GPU acceleration, network, audio and complete power management remain unfinished. See [MIGRATION.md](MIGRATION.md) for the build-46 migration sources and checks, [porting.toml](porting.toml) for current scope and [STAGE6.md](STAGE6.md) for hardware observations.

The current source adds S3910 LBP touch, physical power/volume keys and DSI brightness/display blanking. [Actions build 48](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40183635568) passed the portable transport tests, original and compiled HID/backlight ABI checks, full kernel link and prelink. Touch currently polls ATTN and needs retained power/microcode; presentation remains a 60 Hz software timer. See the input/display sections of [porting.toml](porting.toml) for limits.

[Build 49](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40327493773) included the UFS completion recheck. After a temporary boot, the user reported no repeat panic during the observed test, while touch, buttons and brightness remained unusable. The observation does not establish long-term stability.

The latest diagnostic candidate is [Actions build 53](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40361680754). It adds two `SPI` rows below the camera to show GENI firmware/interface flags and the state, interrupt and FIFO registers captured before a failed transfer is cancelled. Portable regressions, compiled HID/backlight ABI checks, the early-console runtime check, full kernel link/prelink and local image readback passed. It retains the full-duplex `0xff` reads, TouchComm v1/v2 support, skip-Setup RAM Data and keyboard-first HID layout from the previous candidates.

The kernel is at `out/oneplus13t/actions/run-53/kernel/kernel.macho` (127,799,296 bytes), and the complete Android v4 image is at `out/oneplus13t/boot/stage7-run-53/boot.img` (87,953,408 bytes). It was sent with `fastboot boot`; Sending and Booting returned `OKAY`, without flashing a partition. The user reported `fw=102 if=1 st=41 irq=0`, FIFO `tx=0 rx=0`, and the same first-read timeout. This confirms that the FIFO interface is disabled. Build 51 had no touch response: `TOUCH T0 00 header r=ffffff92 v=0 n=0` identifies a timeout in the first SPI transfer, before any header was recorded. The next source candidate selects existing SE DMA for FIFO-disabled engines, with checked SMMU mapping and visible DMA diagnostics. Local regressions pass; full compilation and hardware DMA remain pending. Touch remains unusable in the observed build 53. See [STAGE6.md](STAGE6.md) for exact revisions and checks.

On build 50, the phone reached the lock screen; short power presses switch the screen off/on and a long press opens the shutdown UI. Volume presses advance the key-report counter. Touch failed at TouchComm startup with no reports. That observation does not yet establish which protocol mismatch caused the failure; build 51 tests the compatibility fixes above. Brightness remains unqualified.

## Workspace and inputs

Keep `UniXNU/`, `UniXNU-Pagani_SM8750/`, `UniXNU-Pagani-Drivers/`, `UniXNU-sm8750-common/` and `UEFI-Pagani_SM8750/` as sibling checkouts. `upstream.rev` pins the maintained main fork used by CI. Read [AGENTS.md](AGENTS.md) and the [migration guide](https://unixnu.com/porting/migration).

Run from **UniXNU**, using `unixnu.local.toml` for private paths. Set `build.device`, `uefi`, `edk2`, the full stock firmware DTB, the decompressed 21H461 kernelcache, a nonzero private platform seed, the verified trust-cache bundle and the prepared RAM Data image. Input provenance is in [proprietary-files.txt](proprietary-files.txt). Optional source-development overrides are in [local.toml.example](local.toml.example); published builds use the committed gitlink, feed and lock.

```sh
./unixnu defconfig oneplus13t_defconfig -D ../UniXNU-Pagani_SM8750
./unixnu fetch
./unixnu status --json
./unixnu tree
./unixnu ipsw fetch AppleLogo KernelCache OS Cryptex1,SystemOS StaticTrustCache Cryptex1,SystemTrustCache
```

The output directory is `out/oneplus13t/ipados-17.7.11-21H461/oneplus13t/`. Before the kernel build, prepare the root-window policies, original trust bundle and volatile Data seed as shown in [.github/workflows/xnu.yml](.github/workflows/xnu.yml). The seed preparation requires macOS. The Linux kernel toolchain is not provisioned by this repository; see the main [host requirements](https://unixnu.com/guide/requirements).

```sh
./unixnu kernel
./unixnu build package
./unixnu firmware
./unixnu payload
./unixnu bootimg
```

The firmware contains both standard `UniXNURamDiskDxe` and the 13T `BootPayloadDxe` embedded-payload handoff. Keep `bootimg.embed_payload = true`: the stock ABL uses `init_boot`'s ramdisk during temporary boot. `dts/oneplus13t.dts` describes XNU hardware; it does not replace the separate stock DTB used to package the Android boot image.

The physical root target is the existing 64 GiB **unixnu** partition, LUN 0, LBA 44928768 through 61705983 at 4096 bytes per block. Runtime physical writes remain disabled. `userdata-root.img` is a historical filename, not permission to overwrite Android `userdata`. This migration does not perform device writes or boots.

## Checks

```sh
export PYTHONPATH="$PWD/scripts"
python3 ../UniXNU-Pagani_SM8750/scripts/test-format2.py
python3 scripts/porting-record.py check --device ../UniXNU-Pagani_SM8750
python3 ../UniXNU-Pagani_SM8750/scripts/test-peripherals.py --tree out/oneplus13t/ipados-17.7.11-21H461/oneplus13t/tree
```

The kernel workflow also exercises storage command bounds, the source-kernel and boot-image contracts, display timer lifecycle, RAM Data preparation, root-audit values, DarwinBoot ADT validation and the volatile KeyStore boundary. Host results and hardware observations are recorded separately.
