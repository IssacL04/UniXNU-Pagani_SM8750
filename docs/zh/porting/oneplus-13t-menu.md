# 一加 13T 首阶段菜单启动指南

本页保留 `no-sdcc` / `menu-keys` 的首阶段菜单基线。当前开发已转入 XNU 源码内核适配：13T 配置新增 DarwinBoot、只读 FAT 负载驱动和单核 ADT，macOS Actions 使用 `oneplus13t_defconfig` 与 `kernel payload`。这些新增路径尚未真机验证；具体输入、产物与操作见设备目录 `UniXNU-Pagani_SM8750/README.md`。

菜单基线阶段的验收点是：一加 13T 从设备允许的临时启动路径进入 UEFI，随后显示并运行 UniXNU 菜单，到此停止。暂不加载 XNU，不挂载 Apple 根卷，不启动 iPadOS/macOS 用户态。

因此可以暂缓 XNU 内核编译、Apple 格式 ADT、IPSW、预链接、trust cache、PMGR、原生 UFS、GPU 和触控驱动。本阶段仍需要可工作的 UEFI 平台，以及它的内存、显示或日志、定时器和必要输入。已有 UEFI 驱动可以复用，尚未满足的接口需要在固件层适配。

## 设备与当前范围

| 项目 | 信息与状态 |
| --- | --- |
| 目标设备 | 一加 13T |
| 系统版本 | 用户提供：`16.0.10.500` |
| 当前 Android 内核 | 用户提供：`6.6.118` |
| SoC 适配方向 | SM8750；已结合用户导出的 sysinfo 核对 |
| 目标结果 | UEFI 可进入，UniXNU 菜单可显示并响应操作 |
| 本轮设备读取 | 手机已通过 Windows CMD 连接 ADB；本构建环境未直连 |
| 用户导出资料 | sysinfo 确认 PKX110、24821、槽位 `_b`、DTB/DTBO 均为 2，AA594 面板 |
| 本轮实现状态 | `no-sdcc` 已真机显示菜单、正常倒计时；`menu-keys` 新增侧键适配，交互待真机验证 |
| 菜单程序检查 | QEMU/AAVMF 下显示三个内置项，键盘选择 Restart 成功；不验证手机固件 |

Android 的 Linux `6.6.118` 内核在原系统中运行；本方案从 bootloader 转入另一套 UEFI 固件，不向 Android 安装 XNU 兼容模块，也不依赖 Linux 的模块 ABI。当前内核版本主要帮助选择硬件资料和匹配原厂镜像，不需要为显示 UniXNU 菜单重编它。

## 1 可复用的 pagani 平台

参考 UEFI 仓库 `uefi-sheng` 在提交 `8b7cc5d155ba147f461dea7121e91104544ab99e` 中包含以下平台文件：

```text
Resources/Configs/pagani.toml
Platforms/OnePlus/paganiPkg/pagani.dsc
Platforms/OnePlus/paganiPkg/pagani.fdf
Platforms/OnePlus/paganiPkg/Include/DXE.inc
Platforms/OnePlus/paganiPkg/Library/MemoryMapLib/
Platforms/OnePlus/paganiPkg/Library/ConfigurationMapLib/
Silicon/Qualcomm/PakalaPkg/
```

该平台引用 SM8750 的 Pakala 配置。其 DSC 中的产品标识为 `13s`、`CPH2723`、`pagani`；状态页也将其列为一加 13s，并报告显示、内部存储和侧键可用。这里的状态属于参考项目记录，不能直接扩展为一加 13T `16.0.10.500` 的验证结果。

先沿用这套平台结构，再检查 13T 的内存保留区、XBL/ABL、面板、侧键和厂商 DXE 输入。不要只改产品名称就把固件视为适配完成。

参考状态页还注明 13s 的 ARB Version 1 条件。需要核对目标 13T 当前固件的回滚约束；本阶段不以更换 XBL/ABL、降级固件或调整回滚状态作为默认步骤。

## 2 最小启动链

```mermaid
flowchart LR
  A[设备 bootloader] --> B[BootShim]
  B --> C[pagani 衍生 UEFI]
  C --> D[BDS]
  D --> E[UniXNU.efi]
  E --> F[菜单与诊断]
```

这一阶段一直运行在 UEFI 环境内，不调用 DarwinBoot，不执行 ExitBootServices，不进入 XNU 的 `start.s`。DarwinBoot 的 EL1 检查、连续 XNU 内存窗口、4 KiB 用户 ABI 和 XNU CPU/GIC 驱动都不在当前验收范围内。UEFI 自身的 CPU、GIC 和 timer 初始化仍需工作。

最小方案把 `UniXNU.efi` 和 `UniXNUDxe` 放入同一个固件卷。`UniXNUDxe` 注册固件卷中的应用为 `Boot####`，BDS 随后启动它。这样可以先使用内置菜单，不要求把配置写进手机的 Android userdata 或 EFI 分区。

## 3 首轮需要核对的设备信息

真机连接 ADB 后，可先执行只读查询：

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

这些属性用于定位设备与固件，不能单独证明 bootloader 接受临时镜像。进入 fastboot 后再读取相应状态，并保留完整命令结果；当前阶段不执行解锁、擦除或刷写。

| 待确认项 | 用途 |
| --- | --- |
| 实际型号、device 与 board 标识 | 检查 13T 与 pagani 参考平台的对应关系 |
| bootloader 状态、临时启动能力 | 确定能否使用 `fastboot boot` |
| 匹配 `16.0.10.500` 的原厂 boot/vendor_boot/DTB 等输入 | 分析实际镜像结构、DTB 交接及保留区 |
| XBL/ABL 与回滚条件 | 判断参考 UEFI 的前置条件是否适用 |
| 实际 framebuffer 地址、pitch、格式与面板保活 | 使固件和菜单持续可见 |
| 侧键到 UEFI 输入的路径 | 使菜单可操作 |

本阶段只需分析相关输入，不需要为了显示菜单先提取 Apple 恢复镜像或重建 Android 内核。

## 4 需要改到哪些位置

| 位置 | 参考平台情况 | 本地实现与剩余工作 |
| --- | --- | --- |
| `Resources/Configs/pagani.toml` | header 为 v4，带 FD 配置 | 已建立独立 `oneplus13t.toml`；加载窗口仍待实机核对 |
| `paganiPkg/Library/MemoryMapLib/` | 参考平台的物理内存图 | 13T 已建立独立库，将 `0xD4E23000–0xD5100000` 从 DXE 堆隔离为保留内存 |
| `paganiPkg/pagani.dsc` | 包含固件平台，尚未集成 UniXNU | 新建 `oneplus13tPkg`，已加入 UniXNU 的组件和库映射 |
| `paganiPkg/Include/DXE.inc` | FDF 使用的模块列表 | 13T FDF 已加入 UniXNU 应用与 registrar，FD 布局检查通过 |
| `[firmware] packages` | 包搜索路径 | 13T `board.toml` 已加入通用仓库的 `package/` 路径 |
| `Binaries/pagani/` | 来自 Device-Binaries 子模块 | 初始化并核对参考输入，确认与 13T 的匹配关系 |
| `scripts/unixnu/bootimg.py` | 基准 verifier 使用旧 header 布局 | 已实现 v3/v4 校验和 DTB 集合保留，离线检查通过 |
| UniXNU 配置 | 默认即可显示内置菜单 | 有需要时再提供只含 action 的配置 |

`Binaries` 在该 UEFI 提交固定到 `a1501e0c2e642d6ac0d8f52c85af2a67b75a7799`。仅克隆外层仓库不会取得其中的 DXE 文件；缺少这些输入的目录不能直接进行完整固件构建。

### DSC 与 FDF 集成

参考已集成 UniXNU 的 sheng DSC，把以下两项加入目标 DSC 的 `[Components]`：

```text
UniXNUPkg/Application/UniXNU/UniXNU.inf
UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
```

目标 `[LibraryClasses]` 至少补齐以下库映射，并保留平台其它已有映射：

```text
UniXNULib|UniXNUPkg/Library/UniXNULib/UniXNULib.inf
FdtLib|MdePkg/Library/BaseFdtLib/BaseFdtLib.inf
```

在 FDF 的模块列表中加入同样两个 INF：

```text
INF UniXNUPkg/Application/UniXNU/UniXNU.inf
INF UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
```

当前不加入 DarwinBoot INF。仅构建出 `.efi` 文件不会使手机自动运行它，DSC、固件卷和 BDS 的应用启动路径需要全部接通。

### 显示和按键

参考 pagani 平台默认使用 `SimpleFbDxe`，DSC 写有 `1216 × 2640`、32 位显示参数。这些是参考配置值，仍需核对 13T 当前固件留下的扫描输出基址与真实 pitch。复用 framebuffer 不要求实现 XNU 显示驱动，但要求面板、电源与该内存在 UEFI 阶段保持有效。

`no-sdcc` 已在真机显示菜单，但 ButtonsDxe 因缺少 OplusProject 协议而提前返回，没有安装侧键输入。`menu-keys` 用独立的 13T KeypadDeviceDxe 替换它，并复用通用 KeypadDxe。按本机设备树，音量加读取 PMK8550 PON RESIN，音量减读取 PM8550 GPIO6，电源读取 PON KPDPWR，分别上报上、下和 Enter。读取与去抖已通过主机测试，物理侧键仍待真机确认。

## 5 header v4 与 DTB 集合

基准版本的 `bootimg.py::verify()` 按旧 header 布局解析，不能验证 `pagani.toml` 所选的 v4。本地实现已为 v3/v4 加入独立的 header、4 KiB 对齐和 signature 区域长度检查，同时保留旧格式的地址检查。

13T 历史 vendor_boot 输入包含 13 棵候选 DTB。本地打包器现在保留并逐棵检查整个集合，交给 bootloader 按实际硬件选择；本轮没有猜选其中一棵，也没有改写手机上的 DTBO。结构往返验证已使用实际 `mkbootimg.py` 通过 v0、v3、v4 检查，但不代表设备已接受这些镜像。

当前停用 UFSDxe、SdccDxe、OplusProject 和 PIL/PILProxy/SPSS 的菜单候选为通用仓库中的 `out/oneplus13t/boot/menu-keys/boot.img`，同目录报告 `boot.json` 仍记录 `hardware_tested: false`。目标控制文件位于同级 `UniXNU-Pagani_SM8750/`，固件工作副本位于 `UEFI-Pagani_SM8750/`。它们分别使用 `oneplus13t` 板名与独立 DSC/FDF，详细差异、构建命令及尚未确认的硬件条件见设备目录的 `README.md`。

新候选保留已经显示菜单的基础配置，新增侧键驱动，并关闭 ConIn 按需连接以提前接入输入。内置菜单默认 10 秒返回固件；进入后松开所有侧键，再短按音量减，应停止倒计时并向下移动，电源短按确认。若无响应，记录所有 `13T keys:` 日志。

后续 sysinfo 核对发现，参考 DXE 堆覆盖了真机的 `hwfence-shmem`。当前 13T DSC 已切换到独立 MemoryMapLib，将该区间设为显式保留内存分配 HOB，并保留两侧可用堆。设备目录的 `scripts/check-memory-map.py` 对照导出设备树检查分配区及保留区；这不代替实际启动时的内存交接验证。

## 6 构建范围与主机

只编译 UEFI 应用和固件时，不需要 XNU 构建所用的 Xcode `iphoneos` SDK。参考 UEFI 的构建文档推荐 Linux；UniXNU 的 package/firmware 路径使用 EDK II、Python、make 和 LLVM CLANGPDB 工具。本轮已在当前 Linux 工作环境中完成 package 和固件构建。

构建驱动要求的 CLANGPDB 工具包括 `clang`、`lld-link`、`llvm-lib` 和 `llvm-rc`；BootShim 还使用 `llvm-objcopy`、`llvm-nm`。仅安装系统 `clang` 不一定齐备。真机 USB/fastboot 连接与主机是否能编译是两项独立检查。

菜单基线当时的 `board.toml` 仅提供 `[board]` 和 `[firmware]`，没有配置 `[ipsw]`、`[kernel]`、`[payload]` 或 `[userdata]`。初始化子模块、准备 LLVM/Python/BaseTools 后，在通用仓库中使用本轮实际路径：

```sh
./unixnu status -D ../UniXNU-Pagani_SM8750
./unixnu build firmware -D ../UniXNU-Pagani_SM8750 \
  --uefi ../UEFI-Pagani_SM8750 --edk2 ../UEFI-Pagani_SM8750/Mu_Basecore \
  --local-module refer:edk2=../UEFI-Pagani_SM8750/Mu_Basecore -j 4
```

本轮 UniXNU 应用随固件一同编译。不要执行无步骤参数的 `build` 或 `build all`，它们会进入完整构建流程。环境变量与主机依赖见 `UniXNU-Pagani_SM8750/README.md`。

使用已经提取的历史 13T vendor_boot DTB 集合打包：

```sh
./unixnu bootimg -D ../UniXNU-Pagani_SM8750 --uefi ../UEFI-Pagani_SM8750 \
  --dtb ../UniXNU-Pagani_SM8750/.cache/firmware/vendor_boot/dtb --ramdisk none \
  -o out/oneplus13t/boot/xnu-loader/boot.img
```

该 DTB 输入来自历史备份，未代替当前设备核对。`no-sdcc` 的菜单显示已获真机确认，新侧键镜像仍是待验证候选；其它启动路径和厂商驱动兼容性尚未覆盖。

## 7 菜单配置与观察

最小方案使用 `Config.c` 中的内置菜单，不提供配置卷。菜单包含 Return to firmware、Restart、Power off；它可能额外扫描到可移动 EFI 加载器，需要检查实际菜单内容。

内置配置默认约 10 秒后执行默认项，通常返回固件。菜单出现后自动返回并不一定是崩溃。若已具备可读取的配置卷，可用以下仅含 action 的配置停留更久：

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

配置路径是 `\EFI\UniXNU\unixnu.toml`。有输入设备时，负 timeout 等待输入；没有输入设备时，菜单仍会使用这里的 300 秒 fallback。当前阶段不创建 `type = "xnu"` 菜单项，也不提供 Apple 内核或 Data seed。

## 8 验收顺序与待办

| 顺序 | 验收点 | 完成后再推进 |
| --- | --- | --- |
| 1 | 13T 身份、当前固件、临时启动和恢复方式已核对 | 固件平台选择 |
| 2 | 目标 UEFI 依赖齐备，FD 构建成功且模块布局正确 | 镜像封装 |
| 3 | v4 封装/解包一致，BootShim 与 FD 地址、大小已校验 | 真机临时启动 |
| 4 | 真机持续显示 UEFI 日志或界面 | UniXNU 应用启动 |
| 5 | `UNIXNU:` 启动日志及 `menu: shown`，或明确可见的 UniXNU 菜单 | 输入验证 |
| 6 | 能切换和确认菜单项，返回行为可解释，可重复进入 | 本阶段完成 |

没有输入时，只完成了“菜单显示”，应把“菜单交互”保留为待办。仅通过 QEMU 或固件编译也不构成真机完成。

当前已达到第 5 步：真机显示 UniXNU 菜单。第 6 步侧键交互尚待验证。使用新的 `menu-keys/boot.img` 临时启动，详细产物、按键顺序与日志说明见设备目录 README.md。当前阶段无需展开 XNU 原生驱动开发。

## 源码与后续章节

- [参考 pagani 平台](https://github.com/UniXNU/uefi-sheng/tree/8b7cc5d155ba147f461dea7121e91104544ab99e/Platforms/OnePlus/paganiPkg)
- [参考镜像参数](https://github.com/UniXNU/uefi-sheng/blob/8b7cc5d155ba147f461dea7121e91104544ab99e/Resources/Configs/pagani.toml)
- [参考设备状态](https://github.com/UniXNU/uefi-sheng/blob/8b7cc5d155ba147f461dea7121e91104544ab99e/Status.md#oneplus-13s)
- [UniXNU 固件集成](https://github.com/UniXNU/UniXNU/blob/fb2bb310564ce66779e472a021881cf7c5764919/package/UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.c)
- [当前启动镜像实现](https://github.com/UniXNU/UniXNU/blob/fb2bb310564ce66779e472a021881cf7c5764919/scripts/unixnu/bootimg.py)
- [跨 SoC 完整指南](/zh/porting/soc-porting)、[UEFI 固件](/zh/porting/uefi-firmware)、[启动配置](/zh/reference/boot-configuration)
