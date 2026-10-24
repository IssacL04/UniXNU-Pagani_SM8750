# 移植总览

一个设备移植包含两个仓库和一份板级配置。

| 仓库 | 内容 |
| --- | --- |
| `UniXNU-<device>` | `board.toml`、内核 defconfig、设备脚本、驱动、kit、补丁和设备 package |
| `uefi-<device>` | Mu-Silicium UEFI 移植：设备配置、DSC/FDF、预检和厂商输入 |

`UniXNU` 提供构建驱动、UEFI 启动管理器、DarwinBoot 和通用驱动。设备仓库会覆盖同名模块。

移植到另一款 SoC 时，先阅读[跨 SoC 移植详细指南](/zh/porting/soc-porting)，核对代码中的硬件依赖、构建输入和分阶段验收条件。

若当前只需要一加 13T 进入 UEFI 与 UniXNU 菜单，使用[首阶段菜单启动指南](/zh/porting/oneplus-13t-menu)。该阶段暂不加载 XNU。

## 移植清单

1. [移植 UEFI 固件](/zh/porting/uefi-firmware)，让设备能进入菜单、使用 framebuffer 和负载卷。
2. [创建设备仓库](/zh/porting/device-repository)，包含 `board.toml`、defconfig 和 package。
3. 选择目标 IPSW 和设备身份。
4. [生成 ADT](/zh/porting/device-tree)，提供 XNU 读取的节点和属性。
5. 构建负载和启动镜像。
6. [按阶段 bring-up](/zh/porting/bring-up)：固件、菜单、负载、内核入口、平台专家、存储、根卷、用户态。
7. 为显示、存储、输入和电源加入设备驱动和 kit。
8. 构建 userdata 镜像并刷写。

## 通用部分

以下部分来自 `UniXNU`，通常无需设备副本：

- 构建驱动和模块解析。
- UniXNU 和配置 schema。
- DarwinBoot 和加载器协议。
- NativePrelink。
- 4 KiB XNU 补丁。
- 通用平台专家、CPU、VirtIO 和块驱动。

## 设备相关部分

- UEFI 固件移植和厂商二进制。
- 固件基址和大小。
- 设备树和 ADT 生成器。
- 内核 defconfig 及其选择的静态库。
- 板级电源、显示、触控和 GPU 驱动。
- IPSW 身份和 trust cache。
- userdata 分区几何。

## 设备页面

[设备](/zh/devices/)章节列出设备仓库。每个页面记录该设备的数值。移植指南使用占位符，具体数值链接到设备页面。

## 下一步

- [设备仓库](/zh/porting/device-repository)
- [UEFI 固件](/zh/porting/uefi-firmware)
- [设备树](/zh/porting/device-tree)
- [bring-up 顺序](/zh/porting/bring-up)
