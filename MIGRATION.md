# OnePlus 13T format-2 migration

Device: PKX110, SM8750. Defconfig: `oneplus13t_defconfig`. OS: `ipados-17.7.11-21H461`.

The migration follows the [upstream guide](https://unixnu.com/porting/migration). It preserves the unified community component repository and the main checkout's fork identity. Original repositories retain `checkpoint/pre-format2-20261025`; the earlier build-39 and build-41 images remain available locally.

## Build sources

| Repository | Tested source revision |
| --- | --- |
| `UniXNU` | `4184df2f7da657057666c2527302c29a90f0e733` |
| `UniXNU-Pagani_SM8750` | `af2ba2975a5f0f6dcedfdcc719a1c646876f5804` |
| `UniXNU-Pagani-Drivers` | `56eb51425dc955d9df3f1878b8801788a9fe2a9a` |
| `UniXNU-sm8750-common` | `895f2996e713d5e4d261b1cc6b3d24439638fdf8` |
| `UEFI-Pagani_SM8750` | `50b7313f40684aa25481cd109d7f48b9a50663fa` |

The main fork includes upstream `16e592abee8a550dec8154ed1f38b5ebc4f16213`. The device's `upstream.rev`, driver gitlink, SoC feed and `unixnu.lock` pin the build inputs. Published builds use no local module overrides. Firmware remains in its existing private repository; private platform identity, firmware blobs and system images remain outside Git.

## Configuration and implementation

The resolver selects ARM64, the SM8750 common source, the iPadOS profile and the device in that order. It resolves 15 components and 64 ordered patch entries into `UniXNU/out/oneplus13t/ipados-17.7.11-21H461/oneplus13t/`.

SM8750 owns the shared CPU0/GIC/timer description and UFS/GCC/SMMU register operations. The board DTS owns the enabled CPU, memory and device identity. The common ADT converter replaces the standalone generator; the retained format-1 fixture checks required handoff properties. Four qualified userspace text fixups now come from the common OS profile.

Community component metadata points to the unified source bundle. Archive builders import the selected prelink library, AES publishes the archive declared by the catalog, and RAMBlock object selection and rebuild detection follow the configured archive path. The RAMBlock handoff query is synchronized with upstream RamBlock `25c57e0e9b68bf452dd1986914525edc9d2320bc`; host checks cover valid, missing, malformed, unmapped and out-of-range memory descriptions. This device supplies no GPU addon.

Firmware includes `UniXNURamDiskDxe`, DiskIoDxe and FAT alongside UniXNU, UniXNUDxe and DarwinBoot. The OnePlus 13T `BootPayloadDxe` embedded FAT path remains enabled because the stock ABL uses the `init_boot` ramdisk during temporary boot.

The physical root remains the 64 GiB `unixnu` partition, LUN 0, 4096-byte LBAs 44928768 through 61705983. Runtime physical writes remain disabled. Data remains a volatile 1 GiB RAM seed.

## Host verification

Run commands from `UniXNU`, with the device and private inputs configured in ignored `unixnu.local.toml`. The local firmware build uses the existing UEFI Python environment, Android LLVM tools and mtools. Set `CLANG_BIN` to the actual LLVM `bin/` directory: the Android compiler wrapper cannot run through a relocated symlink without its adjacent `clang.real`. The kernel is built with macOS/Xcode in CI.

| Command or check | Result and evidence |
| --- | --- |
| `./unixnu defconfig oneplus13t_defconfig -D ../UniXNU-Pagani_SM8750`; `fetch`; `status --json`; `tree` | Passed; four profiles, 15 selected components, fixed revisions and complete archive plan. |
| Device configuration, kernel-source, boot-container, UFS bounds, RAM Data, root-audit, display, DarwinBoot ADT and KeyStore tests | Passed on the macOS runner, including the prelink import and RAMBlock handoff regressions. |
| `dtc` and common ADT comparison | Passed; required legacy properties match. The real contiguous RAM range is described, and DarwinBoot's requested allocation remains 4 GiB. |
| Original IPSW inputs, trust bundle and RAM Data preparation | Passed on the macOS runner. |
| `./unixnu kernel -j 3` | Passed; final source-kernel link, prelink and panic-entry check succeeded in Actions build 46. |
| `./unixnu build package` | Passed locally; AARCH64 DEBUG EFI applications, drivers and the shared initrd handoff driver were built. |
| `./unixnu firmware` | Passed locally; 3 MiB FD built and temporary Mu_Basecore patches were reverted. |
| `./unixnu payload` | Passed locally; 160 MiB FAT image with the build-46 kernel, generated ADT, matching trust bundle and RAM Data seed. |
| `./unixnu bootimg` | Passed locally; Android v4, empty Android ramdisk, gzip-compressed embedded firmware/payload and the complete stock DTB bundle. |
| `python3 scripts/porting-record.py check --device ../UniXNU-Pagani_SM8750` | Passed; all 13 structured areas are covered. |
| `npm --prefix docs run build` | Passed; the updated local record renders in both languages and the documentation site builds. The published record is pinned and rebuilt in the main fork. |

Kernel and host-test logs: [Actions build 46](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40174199304). Local firmware and assembly logs live under the resolved output's `logs/` directory. The before/after inventories, compiled hardware DTB and extracted ADT live under `UniXNU/out/migration-oneplus13t/`.

## Built artifacts

Paths are relative to the resolved output directory.

| Artifact | Bytes |
| --- | ---: |
| `kernel/kernel.macho` | 127725568 |
| `payload/payload.img` | 167772160 |
| `boot/boot.img` | 87928832 |

Complete boot image SHA-256: `97747e4832a438578c7fb5e345546e20fb7a6162b70639d1ddbd0a1b0de85beb`. Firmware SHA-256: `c4b8fef5a34ac180277703ae5f0f2b714887de12102b73d3b111164e1612b6cf`. The stock firmware DTB is unchanged. These identify host-built artifacts; `hardware_tested` remains false.

## Device observations and next step

The earlier build 39 reached the iPadOS UI; see [STAGE6.md](STAGE6.md). Those observations do not establish runtime equivalence for the migrated image. No device boot, flashing or partition write was performed during migration.

The next hardware check is a separately authorized temporary boot of the complete new `boot/boot.img`. Record the exact image, firmware and source revisions, then compare boot checkpoints, root reads and framebuffer presentation. Touch, GPU acceleration, network, audio, persistent Data, SMP and complete power management remain unsupported or unverified as detailed in [porting.toml](porting.toml).
