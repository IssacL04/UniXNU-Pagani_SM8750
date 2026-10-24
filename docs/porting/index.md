# Porting overview

A device port has two repositories and one board configuration.

| Repository | Contents |
| --- | --- |
| `UniXNU-<device>` | `board.toml`, kernel defconfig, device scripts, drivers, kits, patches and device package |
| `uefi-<device>` | Mu-Silicium UEFI port: device configuration, DSC/FDF, preflight and vendor inputs |

`UniXNU` supplies the build driver, the UEFI boot manager, DarwinBoot and the generic drivers. A device repository overrides any module with the same name.

For another SoC, start with the [detailed SoC porting guide](/porting/soc-porting) to identify hardware dependencies, build inputs and acceptance criteria for each stage.

For a OnePlus 13T that only needs to reach UEFI and the UniXNU menu, use the [first-stage menu guide](/porting/oneplus-13t-menu). That stage leaves XNU loading deferred.

## Porting checklist

1. [Port the UEFI firmware](/porting/uefi-firmware) so the device reaches a menu, a framebuffer and a payload volume.
2. [Create the device repository](/porting/device-repository) with `board.toml`, a defconfig and the package directory.
3. Select the target IPSW and its identity.
4. [Generate the ADT](/porting/device-tree) with the nodes and properties XNU consumes.
5. Build the payload and the boot image.
6. [Bring up in stages](/porting/bring-up): firmware, menu, payload, kernel entry, platform expert, storage, root, userland.
7. Add device drivers and kits for display, storage, input and power.
8. Build the userdata image and flash it.

## What stays generic

These parts come from `UniXNU` and usually need no device copy:

- The build driver and module resolution.
- UniXNU and its configuration schema.
- DarwinBoot and the loader protocol.
- NativePrelink.
- The 4 KiB XNU patches.
- The generic platform expert, CPU, VirtIO and block drivers.

## What is device specific

- The UEFI firmware port and its vendor binaries.
- The firmware base and size.
- The device tree and the ADT generator.
- The kernel defconfig and the archives it selects.
- The board power, display, touch and GPU drivers.
- The IPSW identity and the trust caches.
- The userdata partition geometry.

## Device pages

The [Devices](/devices/) section lists device repositories. Each page records the values for that device. The porting guide uses placeholders and links to the device pages for concrete values.

## Next steps

- [Device repository](/porting/device-repository)
- [UEFI firmware](/porting/uefi-firmware)
- [Device tree](/porting/device-tree)
- [Bring-up order](/porting/bring-up)
