# Stage 6–7：一加 13T 存储、用户态与系统界面

更新：2026-10-27。**第 50 版已获真机确认：跳过 Setup 进入锁屏，电源键短按亮灭屏、长按打开关机界面；触控初始化失败。** 第 51 版首次 SPI 读取超时，触控仍无响应。第 53 版已完成构建、镜像回验及临时启动，实机读数确认 FIFO 接口关闭，首次 SPI 传输仍超时。第 54 版 SE DMA 候选已通过完整构建、镜像回验及临时启动，实机首次读取返回全零协议头并报 `-71`，触摸 HID 尚未启动。当前源码补齐成功读取后的诊断，待下一次完整构建。

当前测试镜像为 `out/oneplus13t/boot/stage7-run-54/boot.img`，构建使用设备源码 `fba1472`。第 50、51、53 版镜像继续保留；桌面应用交互、亮度及长期稳定性仍未验证。当前概况见 [README](README.md)，分项证据见 [porting.toml](porting.toml)。下文按时间保留各轮诊断与后续修复，最新结果见末尾。

## iPadOS 输入

`board.toml` 已选择上游移植路线固定的 iPadOS 17.7.11（21H461，iPad7,1 / j120ap）Apple 恢复包，并固定 OS 与 SystemOS DMG 的 SHA-256。2026-10-23 通过 Apple CDN 的实际 BuildManifest 核对了版本、机型及 Erase identity；OS 为 `044-76040-038.dmg`（5,157,406,069 字节），SystemOS 为 `044-76034-038.dmg`（3,303,014,400 字节）。两份下载均通过固定哈希校验，保存在 `out/ipsw/21H461/`。版本核对日志为 `out/oneplus13t/logs/stage6-ipados-17.7.11-info.log`。

本地使用 Apple LZFSE 和 [dmg2img 的完整 LZFSE 块解码版本](https://github.com/citruz/dmg2img/commit/88295c834532310764f8883ae81328999118aad0) 转换 OS，原始磁盘为 6,077,580,800 字节。六个 UDIF 分段 CRC、主备 GPT 的 header/表 CRC、两份分区项一致性和 APFS 容量全部通过；UDIF ignore 块按格式排除在分段 CRC 之外，转换结果对应范围为零。SystemOS 本身就是原始 APFS，直接保留。通过项目现有 manifest 写入代码封装后，根镜像位于 `out/oneplus13t/unixnu-root/unixnu-root.img`，共 9,382,658,048 字节（8.74 GiB），适合 64 GiB 的 `unixnu` 分区。OS/SystemOS 窗口完整读回 SHA-256、manifest 哈希及生产 NativeUfs 解析器检查通过，解析器输入为真机采集 GPT 加本地镜像。配套 `unixnu-root.json` 记录实际布局、哈希、转换来源及 `hardware_tested=false`；构建日志为 `out/oneplus13t/logs/stage6-root-image-build.log`。本轮未使用 macOS hdiutil，也未验证真机 APFS 挂载。

DeviceTree、两份 trust cache 和原始 KernelCache 也已从同一恢复包提取。`out/ipsw/21H461/kernelcache.decompressed` 为 46,415,872 字节，SHA-256 为 `f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7`，与参考移植固定值一致。该输入已用于第 24 次候选的 kext 预链接，运行时接口兼容性仍待真机验证。

使用 [apfsutil](https://github.com/sgan81/apfs-fuse)（`66b86bd525e8cb90f9012543be89b1f092b75cf3`，本地仅补 `<cstdint>` 头文件）只读解析了两份磁盘文件，未挂载文件系统：OS 为 System 角色、UUID `04769D26-2CA0-4825-B443-E2E5F88300F2`，SystemOS UUID 为 `8846FE78-2910-4297-AF97-D59BB6F8FC16`。日志位于 `stage6-os-apfs-volumes.log` 与 `stage6-systemos-apfs-volumes.log`。

已用现有 VerifiedRoot 工具生成两份本地签名策略，位于 `out/oneplus13t/unixnu-root/policies/{OS,SystemOS}/`。两份策略共用本地生成的 RSA-3072 信任锚，绑定上述实际卷 UUID、镜像大小与完整哈希。现有 C 校验器通过真实 RSA 签名和全部数据块校验：OS 为 1,483,785 块，SystemOS 为 806,400 块；结果与根镜像窗口 SHA-256 一致。私钥仅保存在本地缓存，未上传。配套 `verification.json` 明确记录 `host_only=true`、`boot_root_authenticated=false` 和 `hardware_tested=false`；日志为 `out/oneplus13t/logs/stage6-root-policy-build.log`。第 24 次内核嵌入云端独立生成并验证的同一镜像策略；本地策略继续保留，手机上的根镜像无需重刷。

第 24 次内核的模式 12 真机照片已确认只读卷发布与 APFS 卷发现。完整 NativeUfs 类、匹配的 Apple APFS/IOStorageFamily、软件 AES 和逐块签名策略已通过这段实际读取路径。随后 UUID 匹配与第 26 次真机审计又确认了根卷挂载和只读设备认证绑定。第 27 次候选移除已完成的模式 12 和根卷审计停机点，接入 trust cache、受限平台 provider 与 owner root 接受；完整运行结果仍待验证。手机硬件配置继续使用 13T 的实际地址，内存由 DarwinBoot 实际分配。

## 设备与分区

本项目固定使用 Windows 工具目录 `D:\Software\AndroidTools\UOTAN\UotanToolbox\Bin\platform-tools`。在 WSL 中对应 `/mnt/d/Software/AndroidTools/UOTAN/UotanToolbox/Bin/platform-tools`。2026-10-22 已通过其中的 ADB 连接 PKX110，取得 root 读取权限。

| 项目 | 已读取的值 |
| --- | --- |
| 根卷目标 | GPT 名称 `unixnu`，`/dev/block/sda16` |
| 容量 | 68,719,476,736 字节，即 64 GiB |
| UFS LUN / 逻辑块大小 | LUN 0 / 4096 字节 |
| 首、末 LBA | 44,928,768 / 61,705,983，均包含 |
| Android userdata | `/dev/block/sda15`，LBA 4,020,972 至 44,928,767 |
| GPT | 主、备 header 和分区表 CRC 通过，分区项一致 |
| unixnu 首块 | 4096 字节全零；检查时没有挂载 |
| Android UFS 状态 | UFS 4.0，六个 LUN，HS-G5、双通道、Rate B |

只读采集保存在本地 `sysinfo/stage6-20261022/`：主、备 GPT、`unixnu` 首块、几何信息和 Android UFS 状态。该目录不上传。Android 采集值作为对照；第 20 次候选后续照片已独立确认 XNU 读取到相同分区边界及首块头部零值。

启动内核继续使用 boot 镜像路径。本轮根卷镜像命名为 `unixnu-root.img`，目标分区为 `unixnu`；通用工具默认输出名仍为 `userdata-root.img`。根卷、后续 Data 持久化与诊断落盘都应限定在这个新分区；本阶段关闭持久写入。

## 已完成的本地适配

- `patches/native-ufs-sm8750.patch` 基于 NativeUfs `af785c1777161a62931425c2faaa536ce0bebd5b`，补齐 SM8750 GCC 偏移、时钟检查、MCQ 拒绝、LUN 容量枚举和精确分区选择。SM8750 根目标固定为 `unixnu`，找不到时停止。
- 只读构建关闭 Data/日志写窗口，并在 SCSI 入口拒绝写命令。探测模式保留共享的传输、GPT、manifest 和 SMMU 代码，不依赖尚未预链接的 IOStorageFamily。
- `unixnu --prepare` 将设备补丁应用到独立缓存，补丁摘要参与缓存名称。
- 镜像生成器使用 `[userdata].partition` 输出部署命令，13T 配置指定 `unixnu` 及实测 64 GiB 范围。
- 主机 ASan/UBSan 检查通过：时钟门控、LUN 枚举、SCSI/队列故障、MCQ 拒绝、写入拒绝、GPT/manifest、实际采集 GPT、SMMU 和跨块读取。实际 ADT/设备树核对及源码隔离测试通过。

寄存器来源为原机 `sysinfo/live.dtb` 与本地 OnePlus 源码：`gcc-sun.c` 所在内核提交 `745702d5ed2c0435f2b1d3bb78bc4f48422d4191`，设备树提交 `6a196f79f77acd55cf302e1696c038e4cad99254`。UFS 为 `0x1d84000/0x3000`，apps SMMU 为 `0x15000000/0x100000`，stream ID 为 `0x60`。AHB、UniPro、ICE、PHY AUX、聚合 AXI 等时钟偏移与 SM8550 不同。

## 当前断点与下一步

1. 第 20 次候选已通过只读 GPT/首块检查，先保留这一可复现基线。模式 10 主动停止是设计行为，无需为了消除该 panic 修改传输代码。
2. 根镜像已通过 Fastboot 写入 `unixnu`，模式 11 真机照片确认 `manifest status=0 windows=2`，两个窗口均为 `read=1`，偏移、大小及 manifest 内哈希字段与本地输入一致。已完成窗口首块读回，尚未进行手机侧全镜像哈希验证。
3. 第 31 次已越过 SystemOS copyout 停点并启动用户态服务，tzinit PID 17 退出状态为 30；第 33 次进入 watchdogd PID 144，停于 SIGTRAP。第 34 次在 RAM Data 中停用该任务后，用户观察到持续运行十多分钟，尚无图形界面。
4. 按 bring-up.md 的目标，根卷挂载与原版 `launchd` 启动已经通过，当前进入阶段 7。第 39 次加入更大内存与 Data、软件刷新、HID 匹配和固定用户态兼容规则后，用户确认进入系统图形界面；触摸无响应。下一步适配触摸控制器和 HID 事件上报，再验证向导与应用交互；长期稳定性仍待验证。

## 真机寄存器结果与第二轮启动

[第 11 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39835493916)以 `3d7f658` 构建成功，产物位于 `out/oneplus13t/actions/run-11/`。最终 Mach-O 已包含 NativeUfs；独立内核与 FAT 内核一致，内核和 payload 哈希与云端报告一致。该镜像配置为 `native-ufs-probe=2`，只读 GCC/UFS 寄存器后通过诊断 panic 页面显示结果。

完整镜像位于 `out/oneplus13t/boot/stage6-run-11-registers/boot.img`，大小 15,216,640 字节；v4 头、内嵌 64 MiB 负载、UEFI 与原机 DTB 解包比对通过。类型记录由 1,265 增至 1,266，参与分池的记录由 1,118 增至 1,119；使用同版 XNU 原始预算函数重放，`kt_fixed_zones=240` 最大槽位仍为 30，ASan/UBSan 检查通过（当前沙箱禁用 LeakSanitizer）。已对序列号 `3B15BB01BAT00000`、槽位 B 执行临时启动，fastboot 的 Sending 和 Booting 均返回 OKAY；日志为 `out/oneplus13t/logs/stage6-run-11-fastboot.log`。后续照片已确认内核显示探测结果，见下节。诊断 panic 后停住是探测模式的预期行为。

用户提供的第 11 次镜像照片已显示 `NATIVE_UFS inspect`，停点为 `PE_lockdown_iokit`；此前未记录 fatal exception。这是模式 2 主动触发的诊断 panic。

| 字段 | 屏幕值 |
| --- | --- |
| `hc_read` | `1` |
| `cap` / `ver` | `d5c7031f` / `00000400` |
| `axi` / `ahb` / `aggre` | `08000001` / `88000003` / `08000001` |
| `hcs` / `hce` | `0000010f` / `00000001` |
| `memcfg` / `rsr` / `ahit` | `00000000` / `1` / `0` |
| `utrlba` | `d6523000` |

这些值确认时钟检查允许访问控制器、HCE 已启用，MCQ 当前未启用。页面的 `root=unixnu` 仅表示配置选择，尚不代表 GPT 查找成功；`root: not entered` 表示尚未进入 BSD 根设备阶段。

已将默认探测切换为模式 10，复用同一内核生成 `out/oneplus13t/boot/stage6-run-11-gpt/boot.img`。FAT 配置读回一致、内核逐字节未变、boot 镜像解包比对通过。设备恢复 Android 后再次临时启动，Sending 和 Booting 均返回 OKAY；日志为 `out/oneplus13t/logs/stage6-run-11-gpt-fastboot.log`。

后续照片显示早期日志停在 `[XNU] pmap_steal`，用户确认超过一分钟无变化，屏幕没有 panic 正文或 UFS 结果。再次从两份完整 boot 镜像中提取内核及 ADT，二者分别逐字节一致；只有菜单标题和探测参数变化。当前证据无法确定具体卡点，也不能据此认定 UFS 传输故障。

同版 XNU 的 `pmap_steal` 是初始化阶段名。最终内核中的相关回调地址为 `socd_client_init=0xfffffff0079cfa60`、`vm_map_steal_memory=0xfffffff0079d9cb8`、`cpu_data_startup_init=0xfffffff0079f3d24`、`bump_static_counter=0xfffffff00772e0a0`。已有 `startup_debug=1` 可打印回调地址及阶段返回；`vm_mem_bootstrap` 的内部事件原本没有输出到屏幕，需补检查点。

已生成并临时启动 `out/oneplus13t/boot/stage6-run-11-gpt-startup/boot.img`，仅增加详细日志和调整菜单标题，内核与 ADT 不变；配置读回和完整镜像解包验证通过。Sending 和 Booting 均返回 OKAY，日志为 `out/oneplus13t/logs/stage6-run-11-gpt-startup-fastboot.log`。照片已显示四个回调依次执行并打印 `reached phase 5`；目前停点在后续 VM 初始化范围。

再次临时启动未经修改的 `stage6-run-11-registers/boot.img` 作对照，用户反馈仍停在 `pmap_steal`。因此现有证据不支持把问题归因于模式 10；根因尚未确定。对照启动日志为 `out/oneplus13t/logs/stage6-run-11-registers-control-fastboot.log`。

新增 `zzzzzz-vm-bootstrap-progress.patch` 复用 BootProgress，显示 VM 顶层步骤、页哈希桶分配、每次早期映射的起始地址及大小、页描述符分配和初始化/释放的边界。只增加诊断输出，保留内存容量、分配和映射逻辑。补丁包含在设备适配总补丁中，默认继续使用只读 UFS 模式 10 和 `startup_debug=1`。

[第 12 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39841189570)以提交 `04fd62a` 成功构建，源码隔离、只读存储与 panic 参数检查通过。产物位于 `out/oneplus13t/actions/run-12/`。已核对云端哈希、FAT 中的实际配置和内核，确认新增 VM 诊断字符串进入最终 Mach-O。参与分池的 1,119 条记录与 run-11 一致，`kt_fixed_zones=240` 仍使用此前已校验的最大 30 槽位；ADT 仅随机种子改变，硬件与内存属性一致。

完整镜像为 `out/oneplus13t/boot/stage6-run-12-vm-trace/boot.img`（15,216,640 字节），封装与解包比对通过。已在设备 Fastboot 状态下临时启动，Sending 和 Booting 均返回 OKAY；日志为 `out/oneplus13t/logs/stage6-run-12-vm-trace-fastboot.log`。

用户随后提供的照片确认：初始空闲页为 59,800，`vm_page_buckets` 的 `0x40000` 字节映射和锁数组的 `0x10000` 字节映射均返回；`vm_tag_init` 已返回并进入 `pmap_startup`。最后显示 `VM page array allocation`，数组含 59,028 项，申请 `0x2b3bc0` 字节（约 2.70 MiB），起始 VA 为 `0xfffffff03a6ce000`，分配前仍有 59,720 个空闲页；没有出现对应的 `VM steal mapped`。因此当前停点在 `pmap_steal_memory_internal` 的数组映射范围，尚不能区分页表扩展、锁等待或单页映射。

下一轮保持分配逻辑不变，仅在该数组路径记录每一页的 VA/PA，并记录早期 `pmap_expand`、页表页分配和 PTD 分配边界。若页表扩展发生，原始 XNU 会调用依赖 VM 空闲链表的分配器；当前仍在建立 VM 数据结构，这是一条待验证的依赖路径。根因尚未确认，未据此扩大内存窗口或改动分配器。

[第 13 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39843893411)以提交 `b67df75` 成功构建并通过全部检查，产物为 `out/oneplus13t/actions/run-13/`。实际 Mach-O 已包含逐页映射、页表扩展及 PTD 分配日志；云端/本地哈希、FAT 内核和配置均一致。分池输入仍为 1,266/1,119 条，ADT 与 run-12 仅随机种子不同。已生成 `out/oneplus13t/boot/stage6-run-13-vm-pages/boot.img`（15,216,640 字节），封装验证通过，并对已恢复 Fastboot 的设备临时启动，Sending 和 Booting 均返回 OKAY。日志为 `out/oneplus13t/logs/stage6-run-13-vm-pages-fastboot.log`。

用户的新照片确认，第 306 页的 VA 为 `0xfffffff023000000`、PA 为 `0xbfbee000`，随后打印 `VM expand` 和 `VM tt page allocation: level=3`，没有出现分配返回。当前路径需要扩展 L3 页表，而 `pmap_pages_alloc_zeroed` 依赖尚未建立的 VM 空闲页链表。

调用关系核对发现：`early_boot_progress_vm_ready` 先用 `ml_io_map_wcomb` 映射帧缓冲，随后 `PE_create_console` 经 `initialize_screen` 再映射一次。13T 的每份映射为 `round_page(0xa50 * 0x1300) = 0xc3f000` 字节（约 12.25 MiB）；`arm_vm_init` 原本只为一份帧缓冲预建 L3 页表。根据数组起点、两份帧缓冲和前两份哈希表的大小，可重建本次动态 VA 起点 `0xfffffff021600000`，原预建范围恰好结束于实测停点 `0xfffffff023000000`。这是源码与屏幕地址一致的根因解释，修复效果仍需真机验证。

新增 `zzzzzzz-early-framebuffer-page-tables.patch`，仅在启用 `XNU_EARLY_BOOT_PROGRESS` 时为第二份帧缓冲预建页表，不改动 VM 分配器或 256 MiB 物理内存窗口。现有源码测试增加一项检查，直接编译补丁中的计算语句，覆盖本次第 306 页边界、四种 2 MiB 地址偏移、诊断开关和空帧缓冲；八项测试通过。全套有序补丁对固定版本 `arm_vm_init.c` 的应用检查通过。第 14 次云端构建及临时启动照片已定位到 AppleImage4 所需设备树节点缺失，修正版待测试。

[第 14 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39846520174)以提交 `55ad302` 成功构建，源码回归、只读存储和 panic 参数检查全部通过。产物位于 `out/oneplus13t/actions/run-14/`；内核为 21,504,448 字节，SHA-256 为 `9c783e1367007e8c738c20d25a5635b414f8f3108b45bb08067dca480edca6f3`。云端/本地哈希、FAT 内嵌内核、模式 10 和详细日志参数核对通过，分池输入仍为 1,266/1,119 条，ADT 与 run-13 仅随机种子不同。

完整镜像为 `out/oneplus13t/boot/stage6-run-14-page-tables/boot.img`（15,216,640 字节），封装与解包验证通过。对用户恢复到 Fastboot 的同一设备执行了 `fastboot boot`，Sending 和 Booting 均返回 OKAY，日志为 `out/oneplus13t/logs/stage6-run-14-page-tables-fastboot.log`。随后用户照片确认内核越过 VM 初始化并进入 BSD/UFS 路径，早期页表修复已获真机验证。

第 14 次照片的 panic 正文为 `UFS ROOT FAILURE: unsupported SMMU geometry`，阶段为 `SMMU planning`，结果 `e00002d8`。实测 `IDR1=0x60000053`、`IDR2=0x5111`；控制器仍为 `CAP=0xd5c7031f`、`VER=0x400`、`HCS=0x10f`、`HCE=1`，DMA 区已分配且连续长度为 `0x22000`。命令计数和块读取计数均为零，尚未发出 SCSI 读取或读取 GPT。

按固定版本 Linux SMMU 驱动中的 IDR1 字段定义，`0x60000053` 表示 4 KiB 寄存器页、128 页全局区域和 83 个 context bank，访问全部 context bank 需要 `0xd3000` 字节；NativeUfs 的旧平台范围为 `0xd0000`，因此在任何 SMMU 配置写入前被边界检查拒绝。原机 `sysinfo/live.dtb` 的 `/soc/apps-smmu@15000000/reg` 为 `0x15000000 0x100000`，与 [Linux SM8750 设备树](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/qcom/sm8750.dtsi)一致。

修复将 SM8750 的映射范围、规划器和只读 context-bank 探测统一为该 1 MiB 区域；旧平台保持原范围。保留地址宽度、页大小、占用、读回和写入顺序检查；SM8750 超过当前完整扫描能力的 stream 数量会明确拒绝，避免只扫描部分条目后占用其他设备的 context bank。现有 SMMU 测试新增实测 IDR1/DMA、最高 context bank、占用回退、映射边界及拒绝后零写入检查。七项 Stage 6 生产路径测试（含采集 GPT）、旧平台 SMMU 测试、八项源码测试和原机资源检查均通过，ASan/UBSan 未报错。

已删除定位 VM 卡点时加入的每页 VA/PA 打印，`startup_debug` 改为 `0`，保留 VM 阶段边界及 panic 页。全套有序补丁应用检查通过；后续启动应减少初始化地址刷屏。第 15 次云端构建及临时启动已完成，后续屏幕结果见下文。

[第 15 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39849922905)以提交 `af3a84e` 成功构建并通过全部检查。产物位于 `out/oneplus13t/actions/run-15/`；内核为 21,504,240 字节，SHA-256 为 `ceaec696563b2345710ce0ce351c6dda33c3c4c894c3ab2bfed5e7bf957d8fb1`。云端/本地哈希和 FAT 内嵌内核一致；实际配置为模式 10、`startup_debug=0`，逐页打印字符串已从最终内核删除，关键阶段日志仍在。分池输入仍为 1,266/1,119 条，ADT 与 run-14 仅随机种子不同。

已生成 `out/oneplus13t/boot/stage6-run-15-smmu/boot.img`（15,216,640 字节），封装与解包验证通过。对同一 Fastboot 设备临时启动，Sending 和 Booting 均返回 OKAY；日志为 `out/oneplus13t/logs/stage6-run-15-smmu-fastboot.log`。随后照片确认新的 panic 为 `unsupported SMMU stream count`，详见下文。

第 15 次新照片的正文从 `unsupported SMMU geometry` 变为 `unsupported SMMU stream count`，源码位置为 `NativeUfs.cpp:1771`。后一个字符串仅存在于新加入的检查中，确认运行的是新内核；几何检查已通过，但尚未配置 context bank 或发送 UFS 命令。当前拒绝来自 `IDR0.NUMSMRG > 128`，原始 IDR0 尚未出现在此 panic 页中。

同版 OnePlus Linux `arm-smmu-qcom.c` 的 `qcom_smmu_cfg_probe` 明确将超过 128 的映射组限制为前 128 个标准组，原因是额外组的寄存器行为不同。上一轮新增的直接拒绝条件比该兼容处理更严格。后续模式 7 已取得原始 IDR0 和现有 stream 状态，修复见下文。

已从 run-15 的原 payload 制作 `out/oneplus13t/boot/stage6-run-15-smmu-registers/boot.img`，只将模式 10 改为模式 7 并更新菜单标题。内核与 ADT 均逐字节一致，配置读回及 boot 封装验证通过。对用户恢复的 Fastboot 设备临时启动，Sending 和 Booting 均返回 OKAY；日志为 `out/oneplus13t/logs/stage6-run-15-smmu-registers-fastboot.log`。模式 7 只读取 SMMU 全局寄存器及标准 stream 条目，不修改 stream 配置。

模式 7 照片显示 `sCR0=002f0406`、`IDR0=4c017e84`、`IDR1=60000053`、`gfsr=0`。原始组数为 132，诊断扫描前 128 组，其中 7 个有效条目均为 TRANSLATE；UFS SID `0x60` 匹配条目 0，`SMR=80000060`、`S2CR=00000000`。这是只读诊断的预期 panic，尚无 UFS 命令或存储块读取结果。

修复恢复高通驱动的 128 组上限，不访问额外四组。对 SM8750，仅允许实测的精确 SID `0x60`、`S2CR=0` 条目从 bank 0 转向空闲的顶部 bank；其他属性、掩码匹配和重复 SID 继续拒绝。接管前仍要求 UFS 队列空闲并停止；先完成新 bank 配置及读回，再修改 UFS 的 S2CR。原 bank 0 及其他 stream 不写入。主机测试使用实测 ID 和 UFS 条目，另用合成的其他 stream/旧 bank 内容验证保留、回退、写入顺序、读回失败和 MMIO 边界；旧平台回归也通过。完整存储回归结果记录在 `out/oneplus13t/logs/stage6-run-16-tests.log`。硬件效果待屏幕日志确认。

[第 16 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39853616767)以 `ccce59f` 构建成功并通过全部检查。产物位于 `out/oneplus13t/actions/run-16/`，实际内核为 21,504,240 字节，云端/本地哈希、FAT 内核和模式 10 参数一致；旧的 stream-count 拒绝字符串已移除。分池输入仍为 1,266/1,119 条，ADT 与 run-15 仅随机种子不同。

完整镜像为 `out/oneplus13t/boot/stage6-run-16-smmu-stream/boot.img`（15,216,640 字节），boot v4、64 MiB 内嵌负载及解包比对通过。已对同一设备执行临时启动，Sending 和 Booting 均返回 OKAY；日志为 `out/oneplus13t/logs/stage6-run-16-smmu-stream-fastboot.log`。随后照片确认的 SMMU 与 UFS 结果见下文。

run-16 照片显示 `UFS ROOT FAILURE: NOP OUT`、`result=e00002d6`、`CMD n=1`、`db=1`、`ocs=0f`、`polls=2`、`dbSeen=1`、`isSeen=0`。SMMU 为 slot 0、`SMR=80000060`、`S2CR=52`（bank 82）、`CBAR=10000`、`SCTLR=0`、`CBA2R=1`，说明规划、配置和读回检查已通过。全局故障为 `0->0`，context-bank 状态为 `400->400`；该值没有变化，不能作为本次新增转换故障的证据。尚未执行 SCSI/GPT 读取。

下一版只补故障证据：保存等待预算与实际经过的绝对计数器 ticks，失败时读取 CNTFRQ/CNTKCTL；对专用 DMA 区域执行 invalidate-only 后读取原始 OCS 与响应头。快照可能仍被控制器修改，不能据此将命令认定为完成，超时后的隔离和禁止重用继续生效。现有测试新增“DMA 已有回复但 doorbell 仍为 1”的故障，确认仍返回超时且不重用缓冲区；八项存储路径测试及诊断文本边界检查通过，最大字段加八项媒体信息为 2,089 字节，低于 2,500 字节容量。日志为 `out/oneplus13t/logs/stage6-run-17-tests.log`。

同版 [XNU rtclock.c](https://github.com/apple-oss-distributions/xnu/blob/d8b80295118ef25ac3a784134bcf95cd8e88109f/osfmk/arm/rtclock.c) 的短延时底层使用 WFE。它是否造成当前轮询间隔异常仍需新增读数确认，本轮未修改计时器、SMMU 路由或 UPIU 描述符。

[第 17 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39856037282)以 `5828caf` 构建成功，全部云端检查通过。产物位于 `out/oneplus13t/actions/run-17/`，内核为 21,520,624 字节；云端/本地哈希、FAT 内嵌内核及实际参数核对通过，新增 WAIT 字符串存在。分池输入仍为 1,266/1,119 条，ADT 与 run-16 仅随机种子不同。

完整镜像 `out/oneplus13t/boot/stage6-run-17-timeout/boot.img` 为 15,216,640 字节，封装解包比对通过，已临时启动；Sending 和 Booting 均返回 OKAY。日志为 `out/oneplus13t/logs/stage6-run-17-timeout-fastboot.log`。随后照片确认 NOP 仍超时，详见下节。

当前未刷写任何手机分区，未启用 Data 持久化或诊断日志落盘。已实测的 run-9 回退镜像仍位于 `out/oneplus13t/boot/xnu-source-run-9-root-panic/boot.img`。

## 恢复检查

在设备仓库执行：

```sh
python3 scripts/test-upstream.py
python3 scripts/test-adt.py
python3 scripts/test-stage6.py --captured sysinfo/stage6-20261022
```

云端没有原机采集文件，使用 `python3 scripts/test-stage6.py --tree "$UNIXNU_TREE" --openssl-prefix "$(brew --prefix openssl@3)"`。构建日志位于 `out/oneplus13t/logs/`。发生额度中断时，从本节及“当前断点与下一步”续接；无需重新分区。


## 第十七次真机结果与轮询、汇编修正

屏幕显示 `WAIT ticks=91411e/3a9802 hz=124f800`：计数器为 19.2 MHz，预算约 200 ms，实际约 495.802 ms，仅两次轮询。失效快照为 `DMA ocs=f rsp=00000000`，doorbell 为 1，未见控制器写回完成。SMMU 配置读回继续通过，global fault 为 0→0，context FSR 为 0x400→0x400；这些结果不能证明 DMA 已经正确到达控制器。

照片中的 `cntkctl=e00002d6` 无效。对 run-17 完整内核反汇编后确认，`mrs CNTFRQ; mrs CNTKCTL` 只生成第一条指令，第二个输出寄存器残留超时错误码。相同的 Apple Mach-O 汇编分号规则还影响 ArmCpu 的计数器读取、SGI 写入和屏障，以及 BootProgress 的中断屏蔽。现统一使用换行分隔；同时修正未启用的 SGI 自测中输入、输出操作数序号写反的问题。

按当前固定 XNU 源码，CPU 注册没有提供 powergate latency 时，`ml_delay_should_spin` 返回 false，`IODelay(2)` 在可等待上下文中会走线程等待路径。SM8750 UFS 的两微秒轮询改为 `mach_absolute_time` 加 deadline 的忙等，保留 200 ms 命令预算及失败隔离；系统其他延时与事件流配置不变。尚不能据此认定 NOP 故障已修复。

`out/oneplus13t/logs/stage6-run-18-tests.log` 记录八项存储路径 ASan/UBSan 测试和真实 GPT 检查通过。新增检查提取生产代码的 21 段多指令汇编，按 ARM64 Mach-O 编译并反汇编，核对每一条系统寄存器指令和屏障；超时故障测试确认轮询不调用线程延时且仍拒绝重用 DMA。隔离准备、源码内核检查和 BootProgress 主机检查亦通过。


## 第十八次构建与临时启动

[第 18 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39858691906)以 `a4fec23` 构建成功，全部云端检查通过。产物位于 `out/oneplus13t/actions/run-18/`，内核为 21,520,624 字节；云端/本地哈希、FAT 内嵌内核和参数检查通过，分池记录仍为 1,266/1,119 条，ADT 与 run-17 仅随机种子不同。最终内核反汇编确认 CNTKCTL 读取、计时器/SGI 屏障、SGI 写入、UFS 忙等循环及 panic 中断屏蔽指令均存在；轮询循环位于独立的 `pollUfsTransfer` 函数中。

`out/oneplus13t/boot/stage6-run-18-poll/boot.img` 为 15,216,640 字节，封装及解包比对通过，已临时启动；Sending 和 Booting 均返回 OKAY。日志为 `out/oneplus13t/logs/stage6-run-18-poll-fastboot.log`。本轮没有写入分区；后续屏幕结果见下节。


## 第十八次真机结果与计划位置

照片显示 `polls=50816`（格式为十进制），`WAIT ticks=3a9830/3a9800 hz=124f800 cntkctl=34f`。按 19.2 MHz 换算，预算 200 ms、实际约 200.0025 ms；短轮询已恢复正常，CNTKCTL 读取也不再残留错误码。首条命令仍为 `NOP OUT` / `e00002d6`，doorbell=1、OCS=0xf、DMA response=0。SMMU 配置读回通过；global fault 为 0→0、context FSR 为 0x400→0x400，没有这次命令新增故障的证据，但仍不能证明 DMA 正常。`IO reads=0`、媒体窗口均为零，GPT/分区字段尚未填充。

按最初 bring-up 顺序，阶段 1–5 的源码探测内核启动链已走通，并进入 BSD 根设备等待；阶段 6 停在底层存储命令通信，还未到 GPT/`unixnu` 识别、OS/SystemOS 发布和根卷挂载。阶段 7 用户态尚未开始。现有 framebuffer 字符输出用于内核诊断，不代表 iPadOS 图形界面或显示服务已经启动。

## 第十八次之后的候选修复：SMMU 同步与队列聚合

补丁补上两处交接处理，已用于下节的第 19 次构建与临时启动。后续屏幕确认仍在 NOP 超时，尚未确定根因。

SM8750 在 SMMU 配置读回通过后执行 `TLBIALLNSNH` 和 `sTLBGSYNC`，最多忙等 100 ms，确认 `sTLBGSTATUS.GSACTIVE` 清零后才启动 UFS 请求队列。写入值使用 `0xffffffff`，沿用 [Linux SMMU 驱动](https://github.com/torvalds/linux/blob/master/drivers/iommu/arm/arm-smmu/arm-smmu.c) 对高通 trapped-MMIO 的非 WZR 处理。该操作失效非安全域的 TLB 缓存，保留 stream 映射与页表；run-19 的 `tlb=0` 确认同步检查通过，但不能证明 DMA 地址路径正确。同步超时会在发送 NOP 前停止，错误为 `SMMU TLB sync timeout`。

队列启动前关闭固件遗留的 `UTRIACR` 中断聚合并读回检查，UTRD 设置 Interrupt Command 位，保持 HC 的 `IE=0` 和现有轮询完成条件。Linux 的设备管理命令及 EDK2 的 NOP 均设置该位。此前没有记录聚合寄存器，因此这属于候选修复，尚无证据证明聚合导致了 run-18 的卡住。

新 panic 行为 `PATH ie=... iacr=旧值->当前值 memcfg=... tlb=...`。到达 NOP 时预期 `ie=0`、`iacr` bit31 清零、`memcfg` bit0 清零、`tlb` bit0 清零；`tlb=ffffffff` 表示尚未采样。此处更正原先的位号：`MEM_CFG` bit0 选择 MCQ，bit1 用于 ESI 中断。即使这些条件全部满足，也只说明配置与同步检查通过，仍需 `doorbell` 清零及 OCS/UPIU 完成响应才能证明通信成功。若 NOP 仍超时，结合这一行继续区分队列配置与 DMA 路径；保留原来的 DMA 隔离，禁止超时后复用或重试。

本地已通过八项 Stage 6 ASan/UBSan 测试、21 段生产 ARM64 汇编的 Mach-O 检查、补丁隔离准备测试、旧平台的命令与 SMMU 回归，以及最大宽度诊断文本检查。新增用例覆盖同步立即完成、延迟完成、持续忙超时、聚合关闭失败和请求标志。run-18 镜像保持原样。

## 第十九次构建与临时启动

用户授权后，将仅包含本次 UFS 补丁的提交 `8912bfc` 推送至现有 `bringup/stage6-unixnu` 分支。[第 19 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39861947626)已成功完成源码准备、存储回归、完整 XNU/FAT 构建及 panic 参数检查。产物位于 `out/oneplus13t/actions/run-19/`，内核为 21,520,624 字节。云端报告与本地哈希、FAT 内嵌内核逐字节比对和只读模式 10 参数检查通过；ADT 与 run-18 仅随机种子不同。

最终 Mach-O 反汇编确认 SMMU 的 `TLBIALLNSNH`/`sTLBGSYNC` 使用非 WZR 寄存器写入，保留屏障、状态读取和限时轮询；队列聚合关闭操作和 UTRD Interrupt Command 位也已进入最终内核。

完整镜像为 `out/oneplus13t/boot/stage6-run-19-dma-sync/boot.img`（15,220,736 字节）。沿用 run-18 的 UEFI 和原机 DTB，boot v4、64 MiB 内嵌负载及封装解包比对通过，Windows 读取的镜像哈希与本地一致。已对连接的 Fastboot 手机执行临时启动，Sending 和 Booting 均返回 OKAY；日志为 `out/oneplus13t/logs/stage6-run-19-dma-sync-fastboot.log`。未刷写分区。

后续手机照片确认第 19 次构建仍停在 `NOP OUT`：`db=1`、`ocs=0f`、`rsp=0`、`is=0`，未进入 SCSI 或 GPT 读取。新增信息为 `PATH ie=0 iacr=0->0 memcfg=0 tlb=0`：固件原本未开启中断聚合，TLB 同步检查也已通过，本次修改未恢复请求完成。`hcs=10f`、`hce=1`、`rsr=1` 和无新增 SMMU fault 仍不足以证明设备收到 NOP。

## run-19 后的链路状态检查候选

现有接管流程直接启动队列并发送 NOP，没有读取物理链路状态；之后的 SCSI 设备唤醒无法帮助一个尚不能完成 NOP 的链路。当前照片没有 TX 状态，因此固件留下 Hibern8 只是待验证假设。

SM8750 的队列启动前现在读取本地 `MPHY_TX_FSM_STATE`（属性 `0x0041`，TX lane 0），仅当值为 `1` 时发送 `DME_HIBER_EXIT`。实现对照本地 SM8750 OEM 内核的 `ufs_qcom_check_hibern8()`、`ufshcd_uic_pwr_ctrl()` 和 UFSHCI 定义：发送前清除旧完成位，退出时同时等待 `UCCS` 与 `UHXS`，检查 UIC 返回码和 `UPMCRS=PWR_LOCAL`，再读 TX 状态。自动休眠计时器若启用则关闭并读回确认，避免查询后再次休眠。普通寄存器及 UIC 命令完成等待上限为 100 ms，Hibern8 退出事件另等最多 500 ms；SM8750 使用计时器忙等，避免早期 `IODelay` 依赖调度唤醒。

新增 `LINK tx=前值->后值 cmd=命令 rc=返回码 is=完成状态 ahitBefore=原值`，未取得的 TX 状态或返回码用 `ffffffff` 表示。读状态或退出失败会在请求队列启动、发送 NOP 之前停止；未加入链路复位、冷启动或超时后 DMA 重试。另将 MCQ 拒绝条件从 `MEM_CFG` bit1 修正为 bit0；run-19 中该寄存器为零，所以位号错误解释不了这次超时。

本地补丁准备、八项 Stage 6 ASan/UBSan 测试（含已采集 GPT）、21 段 ARM64 汇编检查、旧平台命令回归及最大诊断长度检查通过。新增故障注入覆盖已唤醒链路、Hibern8 退出、旧完成位、UIC 未就绪/超时/错误返回、致命错误、缺少退出事件、错误电源状态、退出后仍在休眠及自动休眠关闭失败。候选后续已通过第 20 次完整 XNU 构建及 GPT/首块真机读取。成功检查页未打印 TX 前后状态，尚不能仅凭这页确定实际执行了 Hibern8 退出分支。


## 社区实现对照（2026-10-23）

按用户提供的[社区设备列表](https://unixnu.com/zh/devices/)查询，并检查公开代码。下表中的实机进度来自维护者记录；本项目未独立复测这些设备。

| 设备 / 已检查版本 | 相关证据 | 对当前问题的意义 |
| --- | --- | --- |
| 小米 17 Pro / SM8850，`ios-pandora` `d338ef09c93b` | [实机记录](https://github.com/ShueiTsuki/ios-pandora/blob/d338ef09c93ba7e69d03e997478fe3ad3acda309/device/DT_FINDINGS.md)记录 `CAP=d5c7031f`、`VER=400`、`HCS=10f`、`MEM_CFG=0`，Hibern8 中 `DBR=1`、`IS=0`；退出后 TX/RX 变为 5，并收到 SCSI 响应 | 与 run-19 的控制器和超时表现最接近，支持优先验证链路休眠假设 |
| 一加 10 Pro / SM8450，`UniXNU-negroni` `f812002ae3e6` | [0092 补丁](https://github.com/pawlickerr/UniXNU-negroni/blob/f812002ae3e6b861d23007efdfd9f1c394934ba9/patches/xnu/0092-negroni-ufs-wlun-active.patch)修正设备管理 WLUN `0xd0` 上的 ACTIVE 命令；设备页报告 SpringBoard | 属于 SCSI 已能返回后的设备电源问题；我们已有相同 WLUN/ACTIVE 命令，不能用它解释 NOP 不完成 |
| 一加 Ace 5 / SM8650，`UniXNU-OnePlus-Ace5` `694b39eb76e4` | [设备页](https://unixnu.com/zh/devices/giulia)报告 Hello/Setup；[读取探针的 SMMU 接管](https://github.com/tycykp/UniXNU-OnePlus-Ace5/blob/694b39eb76e4019c75c89780812c68c12070658e/scripts/ufs-read/GiuliaSmmuTakeover.h)可把精确 SID 改路由到空闲 context，保留旧 context | 该代码处理原 context 不适合接管的情况。不能据此认定它解决了与 run-19 相同的故障；本轮不增加 SMMU 改路由 |
| 小米平板 7 / SM7675，`UniXNU-uke` `0fde2b1b53b8` | [进度记录](https://github.com/Allenwdk/UniXNU-uke/blob/0fde2b1b53b871e9b33b1b242a7034f56e2c71c4/docs/PROGRESS.md)报告 GPT、根挂载和 launchd；RootCommands/RootQueue/SmmuTakeover 与我们固定的上游基线文件相同 | 主要差异在板级时钟、根卷发布和用户态；未找到对应 NOP 超时的额外修复 |
| 小米平板 8 Pro、一加平板 2 Pro等 SM8750 条目 | 列表和设备页分别记录 CI 编译或 XNU 入口阶段，未报告原生 UFS 根成功 | 暂未找到同 SoC、已验证能直接套用的存储接管方案 |

`UniXNU/NativeUfs` 查询时的 HEAD 仍为本项目固定的 `af785c1777161a62931425c2faaa536ce0bebd5b`，没有发现新的上游提交可直接更新。列表中的 `jasper2863/UniXNU-giulia` API 返回 404，改查同页列出的 tycykp 仓库。

Pandora 的[0118 补丁](https://github.com/ShueiTsuki/ios-pandora/blob/d338ef09c93ba7e69d03e997478fe3ad3acda309/xnu/patches/0118-pandora-ufs-hibern8-exit.patch)先等 UCCS（100 ms），再等 UHXS（500 ms），检查 `UPMCRS=PWR_LOCAL`。本轮沿用已有条件退出实现，并据此将两个等待分开；增加 250 ms 延迟退出成功及 500 ms 无退出事件失败测试。保留仅在 TX 状态确认为 1 时执行退出、错误时阻止 DMA 队列启动的约束。社区证据增强了假设，但不代替本机测试。

用户已授权后续 GitHub Actions 构建，并明确手机断开、真机测试留待回来后进行。本轮只准备下一次临时启动镜像。


## 第二十次构建与后续实机结果

仅包含 UFS 补丁的提交 `df66c896446f1870d44e0839841701eeb10a4050` 已推送到现有 `bringup/stage6-unixnu` 分支。[第 20 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39864645069)全部成功，包含源码准备、板级检查、存储回归、完整 XNU/FAT 构建和 panic 参数检查。产物下载至 `out/oneplus13t/actions/run-20/`。

内核 `kernel/kernel.macho` 为 21,520,800 字节，SHA-256 为 `c03805398ca83f376b39ef136d75d122b37b1bc0298937b7993a5ac213d267db`。本地哈希与云端报告一致，FAT 内嵌内核逐字节相同；启动参数仍为 `native-ufs-probe=10 native-ufs-diagnostics=1 startup_debug=0`，ADT 与 run-19 仅随机种子不同。最终 Mach-O 反汇编确认 `DME_GET 0x0041`、TX=1 条件判断、`DME_HIBER_EXIT 0x18`、UCCS/UHXS 分段等待及 `UPMCRS` 检查均已进入内核。

待测镜像为 `out/oneplus13t/boot/stage6-run-20-hibern8/boot.img`，15,220,736 字节，SHA-256 为 `409987aecee5058d5fdf7fcc975b17c7435493b52727626f848fe3a98b2b7460`。boot v4、64 MiB 内嵌负载和封装解包比对通过；UEFI、原机 DTB 与 run-19 相同。`boot.json` 保持 `hardware_tested=false`。用户已拔掉手机，本轮没有调用 Fastboot，也没有刷写分区。

下次回到 Fastboot 后，使用此镜像临时启动。若出现 panic，优先记录新的 `LINK` 行与原 `CMD/QUEUE/PATH` 行：`tx=1->5` 表示采样到 Hibern8 并退出至 HS burst；若随后仍为 NOP 超时，则继续检查 DMA 路径。`tx=5->5` 表示查询时链路已在 HS burst，本次未执行退出。`cmd=18` 且失败时结合 `rc`、`is` 和 `hcs` 判断命令、退出事件或电源结果，不能仅凭某个状态值认定存储已恢复。是否真正读取 GPT 仍以完成响应和后续读取阶段为准。


### 第 20 次候选的只读检查通过

用户后续提供的照片显示 `NATIVE_UFS root check`，触发点为 `NativeUfs.cpp:1847`。对照该构建源码，这是模式 10 在 `hostBringUp()` 与 `findRootLayout()` 成功之后主动执行的诊断 panic。它表明 NOP、后续设备命令、LUN 容量读取、GPT 及分区首块读取均已通过本次检查；没有走之前的 `UFS ROOT FAILURE: NOP OUT` 分支。

照片中的 `partition=unixnu first=2ad8f00 last=3ad8eff` 对应十进制 LBA 44,928,768 至 61,705,983，共 16,777,216 个 4096 字节块，即 64 GiB，与板级配置及 Android 采集一致。LUN 0 末 LBA 为 `3ad8fff`；LUN 1–5 的末 LBA 分别为 `7ff`、`7ff`、`bff`、`9afff`、`1fbff`，六个 LUN 块大小均为 4096。

`block0 magic 00000000 00000000`、`ext4magic=0000`、`ext4blocks=0` 表示打印出的头部字段为零，不能据此断言整个分区全零。`manifest status=1 windows=0` 的源码含义是未找到 `SHNGROOT` 标识，符合本流程尚未部署根镜像的状态。当前内核带 `NATIVE_UFS_PROBE_ONLY=1`，完成上述探测后不会发布 IOMedia 根卷；页面下方的根设备等待阶段与此一致。

本轮据照片和同版源码确认结果，仅更新文档，没有修改驱动、重新构建或操作手机。后续进入根镜像部署和完整根卷内核集成阶段；持续读取稳定性、APFS 挂载与用户态仍未验证。


## 根镜像部署与模式 11 准备

2026-10-23，用户授权开始部署并将设备连接到 Fastboot。现场确认序列号 `3B15BB01BAT00000`、产品 `sun`、槽位 B，`partition-size:unixnu=0x1000000000`，分区类型为 raw。写入前重新计算本地镜像完整 SHA-256，与 `unixnu-root.json` 的 `fd43ee7035ce185ce4215ac93fdc006fd784a54b3b7442e21457c226cbe03093` 一致。部署使用项目指定的 Windows platform-tools，目标限定为 `unixnu`，`-S 256M` 分块；完成结果另记于下文。

模式 11 镜像位于 `out/oneplus13t/boot/stage6-run-20-root-windows/boot.img`，复用第 20 次已通过 UFS/GPT 实测的内核，只将 FAT 配置切换为 `native-ufs-probe=11` 并修改菜单标题。配置读回一致，boot 封装与解包比对通过。该模式读取 manifest 及每个窗口的首块后主动 panic，不执行根卷发布或挂载，也不校验手机上全部 8.74 GiB 数据。

本地镜像对应的模式 11 预期字段：

| 字段 | OS（w0） | SystemOS（w1） |
| --- | --- | --- |
| offset（十六进制） | `100000` | `16a600000` |
| size（十六进制） | `16a408600` | `c4e00000` |
| GPT 显示字段 | `20494645 54524150` | `00000000 00000000` |
| manifest 中 SHA-256 前四字 | `e5634d04 a8ac35f0 24845f58 3394e0a3` | `b4908cde 41d23e6b c05e6af5 1a2c9eeb` |

应同时出现 `manifest status=0 windows=2`、两个窗口的 `read=1`。SystemOS 是原始 APFS，首块偏移 32 为 `NXSB`，没有外层 GPT；模式 11 打印的两个 GPT 字段为零符合本地输入，不应单凭这两个零判定读取失败。屏幕中的 SHA 来自 manifest，不能代替窗口数据的完整读回哈希。

同时完成了根卷内核的本地预链接准备：使用第 20 次原生内核、固定的 `21H461` KernelCache 和现有 NativePrelink 工具，分别生成 `out/oneplus13t/kernel/storage-prelink-check.macho`（54,071,296 字节）与 `root-prelink-check.macho`（54,366,208 字节）。后者采用固定参考配置的 30 个组件闭包；预链接保留 Apple 可执行字节，原始输入未修改。现有 AMFI/PMGR 静态检查通过，确认本版 AMFI 的 provider 调用与原始 ApplePMGR/AppleT8011PMGR 方法匹配。这些是构建准备产物，报告仍明确标记 `abi_qualified=false`、`loadable=false`、`runtime_qualified=false`；未将它们封装启动。NativeUfs 完整存储类绑定、签名策略入核、平台 provider 发布、根卷配置及内存容量验证仍待完成，不能用本次静态检查代替真机挂载验收。


部署结果：`out/oneplus13t/logs/stage6-root-flash-unixnu.log` 记录 34/34 个 sparse 分块的 Sending/Writing 全部 OKAY，进程退出码为 0，Fastboot 报告总用时 611.509 秒。镜像预处理从 WSL UNC 路径读取原始文件，期间没有传输输出；后续已正常开始分块发送并完成。仅写入 `unixnu`，未执行其他分区的 flash/erase。此结果确认 Fastboot 写入完成；手机侧全镜像读回校验尚未进行。

模式 11 已对同一设备执行临时 `fastboot boot`，Sending 和 Booting 均返回 OKAY，退出码为 0，总用时 0.835 秒；日志为 `out/oneplus13t/logs/stage6-run-20-root-windows-fastboot.log`。随后用户提供的屏幕结果确认 manifest 与两个窗口首块读取通过，详见下文。


模式 11 真机照片确认：`NATIVE_UFS root windows`，`partition=unixnu first=2ad8f00 last=3ad8eff manifest status=0 windows=2`；OS 的 `off=100000 size=16a408600 gpt=20494645 54524150 read=1`，SystemOS 的 `off=16a600000 size=c4e00000 gpt=00000000 00000000 read=1`。两行 SHA 前四字也与上表一致。停点 `NativeUfs.cpp:1880` 是该模式输出结果后的主动 panic，页面同时显示此前没有记录 fatal exception。由此确认已写入镜像的 manifest、窗口布局及两个窗口首块可由 XNU 原生 UFS 路径读出；未据此声称窗口全量哈希验证、APFS 挂载或用户态启动成功。


## 模式 12 候选集成

模式 11 通过后，候选配置开启完整 NativeUfs 块设备类和已有签名策略验证路径，预链接固定 `21H461` 的 IOStorageFamily/APFS 依赖闭包。默认参数为 `native-ufs-probe=12`，由原有报告线程显示 IOMedia 发现结果；仍编译 `NATIVE_UFS_READ_ONLY=1`，未启用根卷挂载或用户态启动配置。模式 10/11 的已实测镜像保留在 `out/`，可继续作为底层读路径基线。

`build-ufs-storage-bindings.py` 改编自 uke 固定提交的绑定检查，通过原始 KernelCache 核对公开 IOBlockStorageDevice 的 190 槽方法表、176 个继承方法、构造器、元类及基类析构语义，随后应用固定预链接偏移；不依赖另一个设备未公开的运行记录。脚本遇到版本、方法表或导入不匹配会停止构建。macOS 实际编译与绑定结果尚待云端确认。

`prepare-ufs-policies.py` 复用 VerifiedRoot 的实际 C/RSA/篡改拒绝测试，从固定 OS/SystemOS 镜像生成两份策略，并用 C 校验器重新验证每一块。云端生成的私钥仅留在临时构建环境，不纳入上传路径；新内核的公开信任锚可与此前本地策略不同，但两份原始窗口的完整哈希固定，手机上的根镜像无需因此重刷。

完整策略约 70 MiB，驱动还会建立受保护副本。因此候选将 DarwinBoot 请求的连续内存从 256 MiB 调至 512 MiB，FAT 负载容量调至 160 MiB。保留加载器实际内存分配及范围检查；新增 ADT 用例检查 512 MiB 请求，原有 256 MiB 输入仍支持。这个新内存窗口尚未进行真机测试。

第 21 次 Actions 已由提交 `323c5f74f055c0b942ce36ca991ce501a34bad07` 启动：<https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39929267713>。本地四项 ADT 检查、源码隔离测试、八项存储回归及 21 段 ARM64 汇编检查通过；云端源码/板级与只读存储检查也已通过，正在准备固定镜像的策略。用户已将手机恢复 Fastboot，候选尚未临时启动。

第 21 次构建随后在存储 ABI 参考对象的编译选项处失败：Apple Clang 不支持 `-Wno-unnecessary-virtual-specifier`，被 `-Werror` 拒绝。此前 NativeAES、完整 NativeUfs 均已编译通过；云端实际完成七组 VerifiedRoot 测试，并逐块验证 OS 的 1,483,785 块和 SystemOS 的 806,400 块。日志保存于 `out/oneplus13t/actions/run-21/logs/`，这些结果不代表手机上的逐块校验已通过。

提交 `c745fdebf599c903ec0feea964cef564e315c984` 仅删除上述无效编译选项，保留严格告警和全部 ABI 检查。第 22 次构建已启动：<https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39931711046>。手机只读查询的 `max-download-size` 为 805,306,368 字节，候选尚未临时启动。

第 22 次构建通过参考对象编译、190 槽位/176 内核方法匹配和构造入口识别，随后被新增的析构入口检查拒绝。固定 kernelcache 中，该抽象类的 D1/D0 为 `brk #1`，D2 位于 `0xfffffff00596edb8`，经导入桩跳转至 `IOService::D2`（`0xfffffff0077c799c`）；先前假定 D1 也为尾跳转不成立。提交 `bfc24028969d19e0795698dce1c658c924704e7c` 按实际指令检查 D1/D0、D2 分支、导入桩及目标符号。本地执行同一检查通过，把目标改为 D0 的负例被拒绝。第 23 次构建：<https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39933152338>，尚待完成及真机验证。

第 23 次构建的全部 11 个 NativeUfs 绑定通过，随后签名策略编译被 XNU 记录中的可选 `EXPORT_HDRS/libsa` 缺失目录告警阻止。提交 `489b4b5970474dcda2389d355a169ac6245f5ad2` 仅增加 `-Wno-error=missing-include-dirs`，该告警仍可见，其余 `-Werror` 保留。本地检查确认真实头文件缺失和普通代码告警仍被拒绝；隔离补丁测试与脚本语法检查通过。

## 第 24 次构建与模式 12 临时启动

[第 24 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39935525749)全部通过，对应提交 `489b4b5970474dcda2389d355a169ac6245f5ad2`。产物位于 `out/oneplus13t/actions/run-24/`，内核为 127,119,360 字节，FAT 负载为 160 MiB。内核与负载的本地哈希匹配云端报告，FAT 内核、ADT 和启动参数读回一致。最终 Mach-O 中两份策略的 UUID、大小和完整镜像哈希均与已部署窗口一致，策略数为 2。

最终内核含 13 个 Mach-O 映像，类型记录为 1,733 项，其中 1,523 项参与分池。按同版 XNU 分配函数重放，`kt_fixed_zones=240` 最大槽位为 26，ASan/UBSan 通过。实际 FAT 中的 ADT 请求 512 MiB，物理基址仍由 DarwinBoot 分配；新内存窗口能否在手机上正常使用仍需屏幕结果确认。

启动镜像为 `out/oneplus13t/boot/stage6-run-24-verified-media/boot.img`，85,360,640 字节。v4 封装与解包比对通过，内嵌 160 MiB 负载，UEFI 和 DTB 与已验证的第 20 次镜像相同。再次确认设备序列号 `3B15BB01BAT00000`、产品 `sun` 后执行临时 `fastboot boot`，Sending、Booting 均返回 OKAY，退出码为 0，总用时 2.655 秒；日志为 `out/oneplus13t/logs/stage6-run-24-verified-media-fastboot.log`。本次未再刷写分区。

模式 12 尝试发布两个经过策略验证的只读块设备，等待最多约 20 秒后主动 panic，显示 `published`、`reads`、`failures`、`media` 及磁盘信息。后续照片显示程序尚未到达该报告线程，而是在 AppleImage4 初始化中停止，详见下节。


## 第 24 次真机结果：AppleImage4 缺少设备树节点

照片显示 `last stage: mac_policy_initmach`、`root: not entered`，实际错误为 `panic: failed to get manifest properties`。这里 MAC 是 Mandatory Access Control（强制访问控制），该阶段属于 XNU 的安全策略初始化，与系统是否为 macOS 无关。

照片中的 caller `0xfffffff004a982d4` 位于第 24 次预链接的 `com.apple.security.AppleImage4`。实际二进制在 `0xfffffff004a98604` 准备字符串 `/chosen/manifest-properties`，于 `0xfffffff004a98618` 调用节点查找，并在 `0xfffffff004a98620` 检查空指针；失败时跳到 `0xfffffff004a98700`，传入照片中对应的 panic 文本。当前 FAT 中的 ADT 确实缺少该节点。这里的属性容器与 `unixnu` 根镜像中的 `SHNGROOT` manifest 是不同对象，不能据此判断已写入根镜像损坏。

已在 `make-oneplus13t-adt.py` 的 `/chosen` 下补上空 `manifest-properties` 子节点，并为 256/512 MiB 两种 ADT 加入节点检查。四项 ADT 测试通过。重新生成时沿用第 24 次随机种子；实际解码比较确认仅新增这个空节点，其余节点及属性、FAT 内核、签名策略和启动参数均保留。没有填入伪造的 manifest 值或修改 Image4 校验代码。

修正版为 `out/oneplus13t/boot/stage6-run-24-manifest-node/boot.img`，85,360,640 字节；UEFI、原机 DTB、v4 封装及内嵌 160 MiB 负载保持一致，封装读回检查通过。该版本尚未临时启动，需要手机返回 Fastboot 后验证；补齐节点仅针对本次已定位的空指针失败，不代表后续 Image4 或根卷检查已通过。


## 后续真机结果：Image4 哈希算法属性缺失

用户新照片显示同一 AppleImage4 panic 调用入口 `0xfffffff004a982d4`，错误变为 `panic: non-sensical crypto hash method:`，`root: not entered`。启动路径已经越过先前缺少 manifest 容器的检查，但仍未到达根卷探测。

同一恢复包的 `out/ipsw/21H461/DeviceTree.j120ap.im4p` 经 IM4P 提取和本地 LZFSE 解压，完整解析 249 个节点；原始 `/chosen/crypto-hash-method` 为 `sha2-384\0`。实际第 24 次 AppleImage4 二进制在 `0xfffffff004a98fec` 引用 `crypto-hash-method`，在 `0xfffffff004a99018` 引用 `sha2-384`，错误文本引用位于 `0xfffffff004a99100`。上一版 13T ADT 没有这一属性。该声明用于 Image4 算法选择，与 VerifiedRoot 策略内部的 SHA-256 是不同用途。

已在 `/chosen` 增加 `crypto-hash-method = "sha2-384"`，保留结尾空字节，并在 256/512 MiB ADT 测试中检查准确值。四项 ADT 测试通过。实际负载比较确认相对上一版只新增这一属性，既有空 manifest 节点、随机种子、其他 ADT 属性、内核、签名策略及启动参数均保持一致。

新镜像：`out/oneplus13t/boot/stage6-run-24-image4-hash/boot.img`。boot 封装和解包比对通过，UEFI、原机 DTB 及 160 MiB 内嵌负载容量保持一致。本轮未对手机执行命令、未刷写分区；修正版尚待临时启动，后续 Image4、卷发现和根卷挂载仍未确认。


## 模式 12 真机结果：APFS 卷发现通过

补齐 `crypto-hash-method` 后，用户照片显示 `NATIVE_UFS media report: published=2 reads=142 failures=0 media=7`，位置为 `NativeUfs.cpp:1784`。该行对应 `mediaReportThread()` 的主动 `panic("%s", gMediaReport)`，用于保存媒体枚举结果。照片还显示此前未记录 fatal exception；本次停机符合模式 12 的设计。

| 媒体 | 照片中的 UUID | 对应内容 |
| --- | --- | --- |
| `disk1s1` | `8846FE78-2910-4297-AF97-D59BB6F8FC16` | SystemOS 卷 |
| `disk3s1` | `04769D26-2CA0-4825-B443-E2E5F88300F2` | OS 根卷 |

两者均与本地只读解析结果及嵌入签名策略一致。`reads=142` 是驱动读取计数，不能据此宣称手机已验证整个 8.74 GiB 镜像。实际已证明两份窗口能发布、原始 IOStorageFamily/APFS 能识别其卷，相关读取没有报告失败。

最后阶段为 `root device wait begin`，最近阶段含 `root fallback: IOMedia Content=Apple_HFS`。当前 ADT 缺少 `/chosen/root-matching`，XNU 使用默认 HFS 匹配，因此没有选中已经发现的 APFS 根卷。

已复用上游的 IOMedia UUID 匹配格式，为 13T ADT 工具增加现有 payload 接口使用的 `--root-match-volume-uuid` 参数；`board.toml` 指向上述 OS 卷 UUID。UUID 先由标准库校验和规范化，再构造匹配字典。六项 ADT 测试通过，包含默认不匹配、有效 UUID 规范化及无效输入拒绝；实际 CLI 输出与负载中的匹配字典一致。

新候选位于 `out/oneplus13t/boot/stage6-run-24-root-match/boot.img`。与上一版逐项比较，仅新增根卷匹配属性，随机种子、其他 ADT 属性、内核、签名策略和启动参数一致。继续使用 `native-ufs-probe=12` 与原有只读构建；没有启用 owner root 信任、改变认证判定或补入用户态安全组件。该候选用于观察根设备选择和挂载进度，不能作为完整用户态启动镜像。报告线程仍可能在挂载完成前主动停止。

封装及解包比对通过，UEFI、原机 DTB 与 160 MiB 内嵌负载容量保持一致。本轮未对手机执行命令、未刷写分区；新候选尚待临时启动。


## UUID 匹配后的真机结果：根卷已挂载，认证未通过

最新照片明确显示 `root device wait returned: matched`、`root device selected: disk3s1`、`setconf returned: disk3s1`，以及 `vfs_mountroot mounted; authentication pending`。随后的 `rootvp not authenticated after mounting @bsd_init.c:1101` 位于根卷认证失败分支；此前没有 fatal exception。这轮已验证 APFS 根卷选择和挂载，尚未通过认证或执行用户态。

当前构建已用 VerifiedRoot 对 UFS 窗口读取做签名策略及逐块校验，但 `CONFIG_XNU_OWNER_ROOT_AUDIT` 和 `CONFIG_XNU_OWNER_ROOT_TRUST` 均未启用，挂载后没有查询这条验证链。不能通过修改启动参数或去掉 panic 来代替挂载设备的认证绑定。

本地提交 `2b010bb` 启用已有的 owner root 审计，继续关闭 owner root 接受开关。它复用 `NativeVirtioBlock` 中已有的挂载设备查询函数：用 BSD 主次设备号匹配唯一 IOMedia，沿 provider 链调用 `native_ufs_block_authenticates()`，将实际卷 UUID 与已验证的 UFS 策略绑定。复用的组件编入内核，但未添加 VirtIO 设备节点；13T 的存储仍由 NativeUfs 提供。构建器要求该组件的原始 IOBlockStorageDevice 导入全部落在已核实的 UFS 绑定集合中。

新增 `native-root-audit=1` 仅在审计检查点输出 `NATIVE_ROOT binding: apple=... owner=... readonly=... mounted=... selected=...` 并主动停机。预计下一步应验证 `owner=1`、`readonly=1` 且两项设备号一致；这些值尚未在真机取得。报告之后的根卷接受、SystemOS/Data 挂载和用户态安全组件集成仍待完成。

本地六项 ADT 测试、两项准备/隔离测试和实际审计检查点的 ASan/UBSan 测试通过，覆盖未启用报告、启用报告、成功/失败绑定值的保留。完整 Apple 工具链编译仍需云端运行。平台自动审批两次拒绝向既有 `IssacL04/UniXNU-Pagani_SM8750` 的 `bringup/stage6-unixnu` 分支推送，补充本会话此前的持续云端构建授权后仍被拒绝，理由是未认可该目的地的明确发布授权。本次没有触发云端构建，没有新的 boot.img，也没有对手机执行命令或刷写分区。


用户随后明确允许该提交推送和构建。`2b010bb7b5bc8bbd03a7c139a99742a0f10809ea` 已推送到既有分支，[第 25 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39947153821) 已启动。构建完成后检查实际内核、负载与启动封装，再进行真机审计。

第 25 次构建在新增测试读取源码目录时失败：同一步骤中 `$UNIXNU_TREE` 尚未从 `$GITHUB_ENV` 生效。提交 `80b5729` 仅改为使用已有 `$TREE`。第 26 次构建（run `39947395002`）已通过该测试、ADT 和只读存储检查，正在继续完整构建。


## 第 26 次构建：根卷绑定审计镜像已准备

[第 26 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39947395002) 已全部成功，提交为 `80b57292a1a4e99731d14a9f53ff066d006d1e20`。新增检查点测试、只读 UFS 测试、原始存储绑定、完整 XNU 编译及 panic 参数路径检查均通过。策略构建使用实际 RSA 与 C 校验器验证 OS 的 1,483,785 个块和 SystemOS 的 806,400 个块。新增认证查询组件编译成功，其全部 IOBlockStorageDevice 导入均在已核实的 NativeUfs 绑定集合内。

下载产物位于 `out/oneplus13t/actions/run-26/`。最终内核与 FAT 内嵌内核完全一致，实际 ADT 包含 OS 卷 UUID、两个已修复的 Image4 输入和 512 MiB DarwinBoot 分配请求；`native-root-audit=1`、模式 12 和原有只读配置均正确。实际内核包含挂载设备查询、UFS 验证回调及诊断文本，嵌入策略数量为 2；`native_owner_root_trust_enabled` 位于零填充的 `__common`，owner root 接受保持关闭。对实际预链接内核的分配记录重放通过：13 个映像、1,734 条类型记录、1,524 条参与分池，预算 240 时最大 26 槽，ASan/UBSan 无报错。

启动镜像为 `out/oneplus13t/boot/stage6-run-26-root-audit/boot.img`，85,368,832 字节。封装、解包比对及哈希核对通过，UEFI、原机 DTB、v4 头与 160 MiB 内嵌负载容量保持一致。本轮尚未执行手机启动或分区写入；等待手机返回 Fastboot，或由用户手动临时启动。下一张照片需要核对 `NATIVE_ROOT binding` 中的 `owner`、`readonly` 和两个设备号。

用户确认返回 Fastboot 后，读取到同一序列号 `3B15BB01BAT00000`、产品 `sun`，随后临时启动第 26 次审计镜像。Sending 和 Booting 均为 OKAY，命令退出码 0，总用时 2.566 秒；日志为 `out/oneplus13t/logs/stage6-run-26-root-audit-fastboot.log`。未刷写分区。Fastboot 结果仅确认镜像传输和启动请求成功，认证绑定结果仍需屏幕照片。


## 第 26 次真机审计通过，继续原始 AMFI 启动集成

用户最新照片显示 `NATIVE_ROOT binding: apple=80 owner=1 readonly=1 mounted=1000006 selected=1000006 @bsd_init.c:1264`。`apple=80` 是原生根卷认证的返回值；`owner=1` 来自挂载设备、实际 IOMedia UUID 与已验证 UFS 策略的查询，且根卷只读。后两项按 `%x` 输出，均为 `0x01000006`。检查点按本次构建配置主动 panic；这已完成绑定审计，不代表 launchd 已运行。

提交 `abb7bc7` 启用已有 owner root 接受逻辑：原生认证失败时，仅在上述 owner 绑定查询通过且根卷只读的条件下继续。它同时加入原始 AppleMobileFileIntegrity、CoreTrust、sandbox、ApplePMGR 与文件压缩 kext 的依赖闭包，使用原项目固定的 AMFI 早期初始化入口。设备树保留 13T 身份，新增 DarwinBoot 所需的 TrustCache 内存绑定占位和平台代码限制。

信任缓存由同一 21H461 恢复包的两份未修改原始模块组成，共 61,356 字节，固定 SHA-256 为 `7416ca4f8377146626bb284e2133c76bee6cb4e3ee0af5d648b186235a7323a7`；未加入自签名用户程序。原始 16 KiB 代码签名到 4 KiB 页的验证缓存、SystemOS 挂载/启动、启动 manifest 和 SystemOS union 使用既有实现。本轮不加入可写 Data 分区或持久化功能。

平台 provider 沿用原项目受限 PMGR 实现，保留上游 ABI 名称。构建改为直接核对固定原始 kernelcache，不依赖旧设备的历史构建产物：原始 AMFI 的读/置位/写调用、PMGR 的两个 AON 方法、实际目标 AppleT8011PMGR 的相同常量读/空写指令均通过本地核对。其余未实现的电源操作主动 panic；没有访问 Apple 寄存器或宣称 SM8750 电源管理已经完成。实际 340 槽 C++ 分派与链接仍由云端编译检查。

七项 ADT 测试、真实根卷审计函数测试及信任缓存校验通过；信任缓存的截断、顺序交换和内容损坏输入均被拒绝。提交已推送，第 27 次 Actions 为 https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39960099028 。目前尚无新启动镜像，也未执行本轮手机命令。

第 27 次构建通过了策略、原始信任缓存和原始 PMGR 指令检查，随后在 PMGR 组件编译时因 Xcode 16.4 不认识 `-Wno-unnecessary-virtual-specifier` 而失败。提交 `cd618a2` 仅删除该警告选项，保留 `-Wall -Wextra -Werror` 和全部 ABI 检查，已推送并触发下一次构建。失败日志保存在 `out/oneplus13t/actions/run-27/logs/`。


## 第 28 次构建与临时启动

[第 28 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39961798078) 全部成功，提交为 `cd618a276130def4b82712dcb87d47a5c6e1cbf5`。PMGR 组件通过 ARM64/iOS17 编译、完整分派表和原始绑定校验。完整 XNU、17 个原始组件的预链接、FAT 负载和 panic 参数路径检查均通过。实际 RSA 与 C 校验器再次通过 OS 的 1,483,785 块和 SystemOS 的 806,400 块验证。

产物保存在 `out/oneplus13t/actions/run-28/`。下载改用分段读取加速，范围长度和 ZIP CRC 全部通过。最终内核为 127,250,432 字节，SHA-256 为 `cec9bb67c88634b7965b2336916859115d51023035d6185edaf7180b52816bcc`；实际 FAT 中的内核完全相同。FAT 的 SHA-256 为 `f61fac4a1619358b63aab36ff6c7607d36c9b9ae4d66a7c28261f61a0257ca6b`。

本地直接检查 FAT，确认原始信任缓存与本地固定输入完全一致、ADT 包含 TrustCache 占位和平台代码限制、OS UUID 正确，启动参数为 `native-ufs-root=1 sheng-pmgr=2`，已去掉模式 12 和根卷审计停机参数。实际内核的 owner root 接受开关为 1，策略数量为 2；两个策略头的 UUID、镜像大小与摘要均匹配手机上已有镜像。AMFI 和 PMGR 的实际可执行段哈希仍与固定原始输入一致。分配记录重放检查通过：18 个映像、1,869 条记录、1,638 条参与分池，预算 240 时最大 27 槽，ASan/UBSan 无报错。

启动镜像为 `out/oneplus13t/boot/stage6-run-28-root-startup/boot.img`，86,339,584 字节，SHA-256 为 `2fe8d84262c86bb5da0975e8269e94b40830f25857aaf3be50a6d3170d9e2ef8`。封装解包与输入比对通过；UEFI、原机启动 DTB、v4 头和 160 MiB 内嵌负载容量保持一致。

用户确认手机进入 Fastboot 后，已核对序列号 `3B15BB01BAT00000` 和产品 `sun`，并临时启动该镜像。Sending 用时 1.969 秒、Booting 用时 0.337 秒，均为 OKAY；总用时 2.792 秒、退出码 0。日志为 `out/oneplus13t/logs/stage6-run-28-root-startup-fastboot.log`。没有刷写分区。当前只能确认传输和启动请求成功；PMGR 运行、SystemOS 挂载和 launchd 执行仍需下一张真机照片判断。


## 第 28 次真机结果：根卷接受通过，SystemOS 准备未返回

用户照片显示 `root authentication decision recorded` 之后继续完成 devfs、信号、BSD task、mountroot post hook 和 `bsd_init`，随后出现 `bsd_do_post - done`、`load_init_program enter` 与 `SystemOS mount enter`。屏幕没有 panic 标题，顶部 poll/timer 仍在刷新。底部较早的 `ether_family_init`、`net_init_run`、`setconf` 等内容来自环形日志；不能据此判断发生了重启循环。

这证明根卷接受阶段已继续执行，用户态启动准备已开始，但尚未证明 SystemOS 挂载成功或 launchd 已执行。`SystemOS mount enter` 包围整个 `native_owner_cache_prepare()`；其中包含 OS 设备认证复查、SystemOS 设备查询、copyout、实际 mount、vnode 查询、挂载后认证以及 boot manifest 发布。原有日志无法区分具体等待位置。

照片中的 `vm_free_delayed_pages: initialized 0 free pages` 不能作为系统剩余 RAM 为零的证据。按本次构建锁定的 [Apple XNU 源码](https://github.com/apple-oss-distributions/xnu/blob/d8b80295118ef25ac3a784134bcf95cd8e88109f/osfmk/vm/vm_compressor_backing_store.c)，`vm_swap_create_file failed` 是后台 swap 创建线程在函数返回失败后打印的日志；打开文件失败等情况都会走该返回路径。本配置尚无可写 Data/swap，但照片未提供失败 errno 或内存计数，不能将这行直接认定为 SystemOS 停滞的根因。

提交 `0d4aeff` 仅增加观测：在上述 SystemOS 调用边界使用已有 `boot_progress_root()` 更新日志和顶部最后阶段；进入准备函数后，原来的 CPU 状态行切换为 `free=... avail=... UFS=... err=...`。页数与 UFS 计数均为十进制，页大小为 4 KiB；这是软件计数的即时读取，字段可能来自相邻更新。原有 poll/timer 仍为十六进制。状态更新不访问设备寄存器、不取得 UFS 锁、不改变请求或认证状态。状态行按屏宽截断，防止覆盖最后阶段。

实际渲染器的 ASan/UBSan 测试和准备/隔离测试通过，覆盖新计数的格式、窄屏截断、ROOT 行保留、光标恢复和计数不被观察者改写。根卷认证、原始代码签名、挂载标志、只读 UFS 和设备树输入保持上一版配置。[第 29 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39969583173) 已启动，尚未生成新的启动镜像。

第 29 次构建在首轮 XNU 编译失败。完整日志确认 `kern_exec.c` 调用 `boot_progress_root()` 时缺少声明；该函数属于 `early_boot_progress.h`，此前文件只包含 `boot_progress.h`。提交 `4fde866` 在 SystemOS 补丁中补上正确的头文件。隔离补丁准备通过，直接从实际补丁生成的头文件在诊断开关为 0、1 时均通过 C11 严格语法检查，且调用文件在使用前包含该头文件。失败日志保存在 `out/oneplus13t/actions/run-29/logs/`。修复已推送重建；尚未执行本轮手机启动。

[第 30 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39971699941) 已启动，使用提交 `4fde8661799d728c0e1d86e37036f2c4e2ecfbfd`。


## 第 30 次构建与诊断镜像临时启动

第 30 次 Actions 全部成功，提交为 `4fde8661799d728c0e1d86e37036f2c4e2ecfbfd`。完整 XNU 编译、原始 PMGR 绑定、内核预链接、FAT 生成和 panic 参数路径检查均通过。产物位于 `out/oneplus13t/actions/run-30/`，下载范围、分段长度和 ZIP CRC 校验通过。

实际 FAT 内核与独立内核完全一致，大小为 127,250,432 字节。内核包含所有新增 SystemOS 阶段文字和五项 RAM/UFS 计数符号；ADT、原始信任缓存、根卷启动参数、owner trust 接受开关、两份策略身份以及 AMFI/PMGR 原始可执行段检查通过。实际分配记录重放仍为 18 个映像、1,869 条记录、1,638 条参与分池，预算 240 时最大 27 槽，ASan/UBSan 通过。

内核 SHA-256 为 `461beee763a751576727dabd000792c382ff04ec1c61ae9fede00febd8149cc1`，FAT SHA-256 为 `e2e7e1aaa1aadb39ce4750bd6ccab972bf160dc816f60041908b3753a8127347`。

启动镜像为 `out/oneplus13t/boot/stage6-run-30-systemos-progress/boot.img`，86,339,584 字节，SHA-256 为 `1a8a5498683e51e80165d1064c7402b45e566aea05786ccb14cae7699770033a`。封装解包与输入比对通过，UEFI、原机 DTB、v4 头和 160 MiB 内嵌负载保持一致。

用户此前确认手机已进入 Fastboot；本轮再次读到序列号 `3B15BB01BAT00000`、产品 `sun`，随后执行临时启动。Sending 和 Booting 均为 OKAY，分别耗时 1.964 秒与 0.337 秒，总用时 2.662 秒，退出码 0。日志为 `out/oneplus13t/logs/stage6-run-30-systemos-progress-fastboot.log`，没有刷写分区。

目前仅确认传输与启动请求成功。需新照片读取顶部 ROOT 阶段、free/avail 页数及 UFS/err 计数；若停住，再间隔约 30 秒拍摄同一区域以比较计数。SystemOS 挂载与 launchd 启动仍未验证。


## 第 30 次真机结果与社区移植对照：首个用户页访问

新照片最后阶段为 `SystemOS copyout enter`，scratch 地址是 `0x1000`。此前根卷认证返回 1，SystemOS UUID 查询已找到 `/dev/disk1s1`，设备号为 `0x01000002`。未出现 `SystemOS mount syscall enter`，因此等待位于四次 copyout 组成的区间；照片不足以区分具体哪一次。顶部空闲页约 74,160 页（4 KiB 页，约 290 MiB），UFS 读取计数为 241；这张静态照片不能确认计数是否持续变化，也不支持“内存已经耗尽”的判断。屏幕未显示 panic 标题。

按用户给出的 [UniXNU 设备列表](https://unixnu.com/zh/devices/)，定向查看了使用相同 iPadOS 17.7.11 输入且进度更靠前的移植：

- [umi 构建器，固定提交 3eb7257](https://github.com/reAAAq/UniXNU-umi/blob/3eb72578597d2ca16471b172d45eddc096a34a04/bringup/tools/build_umi_xnu.py#L165) 在 owner root 启动时明确要求 `CONFIG_XNU_NATIVE_PAN=y`，否则直接拒绝构建。设备页报告已到 Hello/设置；本次未独立验证该设备运行。
- [uke 完整配置，固定提交 cf55281](https://github.com/Allenwdk/UniXNU-uke/blob/cf552816de501906082405ebb0e355d8c70f7b60/configs/uke-full_defconfig#L27) 启用原生 PAN，设备页报告已运行 launchd。该仓库其他认证和 Data 方案不作为本轮改动。
- [tb128fu 配置，固定提交 0d55473](https://github.com/xVanTuring/UniXNU-tb128fu/blob/0d55473e5c3a60656a12123d4c2fa8ea4f4a7383/configs/tb128fu_defconfig#L43) 明确关闭 PAN，因为其 ARMv8.0 CPU 不支持这组指令。这个差异说明不能直接照搬完整设备配置。

本次使用的 [Apple copyio.c](https://github.com/apple-oss-distributions/xnu/blob/d8b80295118ef25ac3a784134bcf95cd8e88109f/osfmk/arm64/copyio.c#L90) 仅在 `__ARM_PAN_AVAILABLE__` 为真时，在用户访问前清 PAN、之后恢复 PAN。原生适配已有 `native-arm-pan.patch`，通过 `XNU_NATIVE_PAN` 为 BCM2837 构建目标声明该能力；13T 之前未开启它。对实际第 30 次内核 `_copyout` 的反汇编确认：检查地址之后直接进入 `__bcopyout`，没有 PAN 读写指令。

固定源码的 `start.s` 将 `SCTLR_EL1` 写为默认值，`proc_reg.h` 的默认值没有设置 SPAN 位。支持 PAN 的 CPU 在异常入口可因此置 PAN；若用户访问路径未临时清除它，权限异常可能反复发生，而缺页处理无法解除 PAN 保护。这与当前第一次写入用户 scratch 页时停滞相符，是本轮优先验证的机制。尚未读取真机该位置的 PAN/ESR/FAR，因此不能仅凭照片宣布根因已经实测确认。

提交 `f7549d0` 只在 `configs/oneplus13t_defconfig` 加入 `CONFIG_XNU_NATIVE_PAN=y` 和原因注释。现有配置解析器与实际 `xnu_env()` 检查通过，输出 `XNU_NATIVE_PAN=1`；owner root/SystemOS 选项保留，Data 挂载仍关闭。完整编译、最终指令检查及临时启动待完成。

[第 31 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39977287333) 已启动，提交为 `f7549d053c2b82952ea762a26bb1b85aedd48c3d`。


## 第 31 次：原生 PAN 镜像验证与临时启动

第 31 次 Actions 全部成功，产物位于 `out/oneplus13t/actions/run-31/`。分段下载约 57 秒，范围、长度和 ZIP CRC 校验全部通过。内核与实际 FAT 内嵌文件相同；ADT、原始 trust cache、根卷参数、两份策略、owner trust 开关和 AMFI/PMGR 原始可执行段检查均通过。实际分配记录仍为 18 个映像、1,869 条记录、1,638 条参与分池，预算 240 时最大 27 槽，ASan/UBSan 通过。

最终内核反汇编确认：`_copyin` 和 `_copyout` 都先读取 PAN，在实际 `__bcopyin`/`__bcopyout` 调用前执行 `msr PAN, #0`，返回后执行 `msr PAN, #1`。同一检查已用第 30 次实际内核验证，能拒绝缺失 PAN 切换的旧产物。这证明新配置确实进入执行代码，尚不代表真机已越过该路径。

内核 SHA-256 为 `42b85d96b615d586cdf3bf2cf2d79ba80337b4cb344d46549c10954e0ec80ecd`，FAT SHA-256 为 `52cae3eadad3252b08d101ad4e5f41576f5c8e85eda02da531196c8fa2661b21`。

启动镜像为 `out/oneplus13t/boot/stage6-run-31-native-pan/boot.img`，86,339,584 字节，SHA-256 为 `3f2af3df5432f50fd214e40c98114997a60fe4be761096fc054deb376631430d`。封装解包和实际文件校验通过，UEFI、原机 DTB、v4 头、零 Android ramdisk 和 160 MiB 内嵌负载保持一致。

用户确认进入 Fastboot 后，已再次核对同一序列号 `3B15BB01BAT00000` 和产品 `sun`，然后临时启动。Sending 用时 1.976 秒、Booting 用时 0.337 秒，均为 OKAY；总用时 2.600 秒，退出码 0。日志为 `out/oneplus13t/logs/stage6-run-31-native-pan-fastboot.log`。没有刷写分区。等待新照片确认是否越过 `SystemOS copyout enter`，以及挂载或 launchd 是否继续推进。


## 第 31 次真机：SystemOS 成功，tzinit 缺少可写 Data

照片显示最后阶段为 `exec process signature accepted`，根阶段 `SystemOS boot manifest returned`，序号 `0x1f`、返回值 0。panic 为 `tzinit[17] exited -- no exit reason available -- (signal 0, exit status 30)`，调用地址 `0xfffffff00bfdabf4`，启动约 20 秒。此前的 copyout 停点已消失；进程 17 和连续的 exec/signature 阶段说明已进入 launchd 之后的服务启动，但尚未得到稳定用户态或界面。

通过本地只读 apfs-fuse 库从同一 OS 原始镜像提取 `/usr/libexec/tzinit`，文件标识为 `TimeZoneUpdates-87.2.1`。提取器同时读出的 launchd 哈希为 `8cec9a3c44a443b08e977ccc5d577850316ad428c575dc01f09b018dbd5b6a25`，与原始输入锚点一致。tzinit 的错误分支在 `0x100005e18` 至 `0x100005e40` 读取 errno、检查 1–255 范围并传入 exit；程序包含 `/var/db/timezone/zoneinfo`、`icutz`、`localtime` 及 create_symlink 调用。退出码 30 对应 EROFS；具体哪一次文件调用失败尚无用户态日志。

下一候选复用上游 NativeRamBlock 的稀疏页读写和现有 Data 挂载代码，使用原始 private/var（排除 staged_system_apps）生成 256 MiB APFS，保留 uid/gid、权限与符号链接。真实卷 UUID 注入构建配置，DBRDISK1 打包结果须通过完整逻辑内容 SHA-256 回验；DarwinBoot 通过 PackedRAMDisk 传入。Data 仅写 RAM，重启后恢复初始种子，不启用 UFS 持久窗口。

本地已通过 7 项 ADT 检查和源码隔离检查。现有稀疏盘测试中旧的 2 GiB 上限断言与当前允许 1 TiB 的解析器不符；仅在临时测试副本中将越界值改为 1 TiB + 4096，4000 次差分读写及损坏输入、短复制、分配失败检查通过 ASan/UBSan。生产驱动未作更改。APFS 格式化、驱动链接与新镜像真机结果仍待本轮构建验证。

本地提交 `5277550` 已完成上述接线；256 MiB 稀疏样本通过现有 DBRDISK1 打包和完整逻辑 SHA-256 回验。用户已确认手机重新进入 Fastboot，并再次明确授权本次及后续修复的仓库推送和 Actions 构建。提交已推送，第 32 次构建（39985324701）已通过原始镜像校验与 RAM Data 生成，正在编译 XNU。当前尚未执行本轮临时启动。


## 第 32 次构建：Data 种子通过，移除跨设备链接依赖

[第 32 次构建](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39985324701)已完成真实 APFS Data 格式化及 NativeRamBlock 编译，最终内核链接缺少 `sheng_boot_watchdog_policy`。该调用来自通用 `zzz-boot-progress.patch` 的 Data 挂载后路径，对应 sheng 设备的可选 launchd 服务禁用策略，当前 13T 未使用这些启动选项，也没有包含该实现。提交 `d75ba0b` 在 13T 的隔离源码补丁中移除这段调用，保留 Data 挂载、错误处理和进度记录。补丁应用及 8 项现有内核构建测试通过；[第 33 次构建](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39988002937)正在验证最终链接。

第 32 次真实种子位于 `out/oneplus13t/actions/run-32/oneplus13t-xnu-32/ram-data/`：逻辑容量 268,435,456 字节，打包后 1,003,616 字节，卷 UUID 为 `CBCABAE2-8CE9-4DCB-971F-F3F68F2A7B26`。39 个原始文件共 611,715 字节，属主和权限均已逐项核对。下载后独立检查编码哈希、完整逻辑 SHA-256 和只读 APFS 解析通过；解析出的 UUID 与 macOS 报告一致，卷为未启用 FileVault 的 OwnerData。重建将产生自己的配套种子和 UUID，不能混用不同构建的内核与 Data。


## 第 33 次：RAM Data 候选检查通过并临时启动

[第 33 次构建](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39988002937)以 `d75ba0b` 完成，全部步骤成功。上一轮缺失的 sheng 专用策略调用已从实际内核中消失，Data mount enter/returned 诊断仍保留。最终内核为 127,320,064 字节，含 17 个原版预链接组件；原版安全组件代码、两份根策略身份、trust cache 和启动参数检查通过。NativeRamBlock 的种子查询、读写和 Data 挂载状态符号均已链接，copyin/copyout 的 PAN 清除与恢复仍包围实际复制调用。18 个映像共 1,870 条 kalloc 类型记录，1,639 条参与分池；预算 240 的最大槽位为 27，原始预算算法 ASan/UBSan 重放通过。

实际 FAT 中的 Data 与上传种子逐字节一致，逻辑容量 268,435,456 字节，压缩打包后 1,003,616 字节，卷 UUID 为 `578EFED6-C632-4032-8AFB-6598EC3F66D3`。独立 APFS 解析得到相同 UUID，完整逻辑 SHA-256 为 `4195d9243ea4a72b478ae12bfa359a2b261f07e49b6cce9d51c54c5e285296a3`；内核中包含此 UUID，ADT 包含 PackedRAMDisk，启动配置通过 initrd 加载对应文件且没有持久化参数。

内核 SHA-256 为 `f2f88abc43a3d6411733a3dd44bb473f1c55647239b5f0c26a460ddf3184ef2d`，FAT SHA-256 为 `400bcf262df12c604e37c0035526978bf9f0848b6fe050305307b7c0ed5f2612`。启动镜像位于 `out/oneplus13t/boot/stage6-run-33-ram-data/boot.img`，86,925,312 字节，SHA-256 为 `f81f5d3c9f8d89b946764e474ee5f60e0ce2ff175c0a8b463b411ba60b41048e`。封装检查通过，v4 头、160 MiB 内嵌 FAT、UEFI 和原机 DTB 均符合预期，Android ramdisk 字段为空。

只读 Fastboot 查询确认设备 `3B15BB01BAT00000`、型号 `sun` 后，已执行 `fastboot boot`：Sending 1.988 秒、Booting 0.337 秒，均为 OKAY，总计 2.668 秒。日志为 `out/oneplus13t/logs/stage6-run-33-ram-data-fastboot.log`。本轮没有刷写分区；Data 写入仅保存在 RAM，重启后恢复初始种子。当前只确认镜像发送和启动请求成功，Data 真正挂载、tzinit 正常退出及后续用户态运行仍需手机照片验证。


## 第 33 次真机：watchdogd SIGTRAP 与第 34 次临时服务策略

新照片显示 `watchdogd[144] exited -- exit reason namespace 2 subcode 0x5`，最后阶段为 `exec process signature accepted`。SystemOS boot manifest 返回 0，序号 0x1f，age 为 0x65，约 101 秒。页面没有此前记录的 fatal exception。当前候选已经执行到 Data 挂载之后的服务启动路径，未再停在 tzinit；没有单独采集 tzinit 的成功退出记录。

固定 [XNU reason.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-10063.141.1/bsd/sys/reason.h) 定义 namespace 2 为 OS_REASON_SIGNAL，[signal.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-10063.141.1/bsd/sys/signal.h) 定义 5 为 SIGTRAP。两份官方文件已实际读取核对，因此本次并非 watchdog 超时 namespace。

从同一原始 OS 只读提取的 watchdogd 在 `0x100006768` 查找 IOWatchdog；没有匹配服务时，在非虚拟机分支进入 `0x10000aaf8`，通过 `_os_crash` 和 `brk #1` 报告无法查找 watchdog KEXT。当前最终内核没有 IOWatchdog 提供者。原始 com.apple.watchdogd.plist 启用了 `_PanicOnCrash/PanicOnConsecutiveCrash`，与当前进程退出触发内核 panic 的现象一致。照片没有用户态异常 PC，因此缺少后端仍是有代码证据支持的首要解释，未把具体分支当作现场捕获结果。

提交 `57c36e5` 在新建的临时 APFS Data 中写入 `db/com.apple.xpc.launchd/disabled.plist`，唯一条目为 `com.apple.watchdogd=true`，并创建空的 disabled.migrated 标记。两文件权限为 0644；源任务 Label、ProgramArguments 和 panic 策略必须与固定系统一致，否则停止。现有策略文件和符号链接路径均拒绝覆盖。原始系统文件、watchdogd、launchd 及内核 panic 条件均未修改。此策略仅用于硬件后端尚未实现的 bring-up，恢复 watchdog 功能仍需实际驱动适配。 同一原版 launchd 的 `0x100047090` 对 disabled.migrated 调用 stat，成功即跳转到 `0x100046fd4` 加载 disabled.plist；这确认空标记足以选择现有策略加载路径。

本地 3 项回归检查、实际原始任务 plist 检查通过，云端检查已接入同一测试。[第 34 次构建](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39991765255)正在运行；用户已确认重新进入 Fastboot。后续先从实际 APFS 种子读回策略，再临时启动；物理 UFS 写入继续关闭。


## 第 34 次：策略产物核对与临时启动

第 34 次 Actions 全部成功。下载范围、长度与 ZIP CRC 检查通过；从实际 FAT 提取的内核和 Data 与上传文件完全一致。独立解析实际 APFS 后，disabled.plist 只有 `com.apple.watchdogd=true`，disabled.migrated 为零字节。内核仍含 17 个原版预链接组件，原始安全代码、两份根策略、trust cache、PAN 切换及 Data 挂载诊断均通过检查。kalloc 共 18 个映像、1,870 条记录、1,639 条参与分池，预算 240 的最大槽位仍为 27。

Data UUID 为 `924B8B8B-321B-45B9-AE49-3862B0AE81F2`，256 MiB 逻辑镜像打包为 1,007,712 字节；完整逻辑 SHA-256 为 `b12d2639f31e835ff42fa59dba79762b9d49c3dda856234a6c0624447d5fb7e6`，并已核对内核中的卷 UUID。仍从原版 private/var 保留 39 个文件共 611,715 字节及其属主和权限。

启动镜像位于 `out/oneplus13t/boot/stage6-run-34-watchdog-policy/boot.img`，86,925,312 字节，SHA-256 为 `6714d95dffd0f55550009e6920220ff0c4d83964cd4c69e07eff05e49748537f`。封装解包检查、v4 头与文件哈希通过；UEFI、原机 DTB 和 160 MiB 负载布局保持一致。

用户确认重新进入 Fastboot 后，再次只读核对设备 `3B15BB01BAT00000` 和型号 `sun`，随后执行临时启动。Sending 1.981 秒、Booting 0.337 秒，均为 OKAY，总计 2.613 秒，退出码 0。日志为 `out/oneplus13t/logs/stage6-run-34-watchdog-policy-fastboot.log`。没有刷写分区。当前等待新照片确认是否越过 watchdogd 停点；硬件 watchdog 尚未实现，Data 修改随重启清除。

## 第 35 次候选：Stage 7 用户态服务与 CPU 显示

前六阶段及本轮继续使用 iPadOS 17.7.11（21H461，iPad7,1 / j120ap）、XNU 10063.141.1。参考 [UniXNU-sheng](https://github.com/UniXNU/UniXNU-sheng/tree/ab3121e766f68832c90370ae2dd007284d9510d8) 的显示与临时 KeyStore 接线，使用当前固定的 UniXNU 通用驱动源码。Pong 与 Pandora 的 iOS 16 实现仅作设计参考，未混用其内核或驱动 ABI。

本轮加入原版 IOSurface、IOMobileGraphicsFamily、IOHIDFamily、IOHIDEventDriver 及依赖闭包，启用 NativeLegacyDisplay 的 CPU framebuffer 路径。构建脚本直接审查固定 Apple kernelcache：核对原版可执行段、358 项虚表、继承关系及绑定函数指令，再检查编译所得对象；不再依赖 Sheng 私有的预链接候选与旧 QEMU 产物。对象大小沿用同版原始类 ABI，SM8750 上的实例创建与生命周期尚待验证。

板级服务从实际 GOP 获取地址、尺寸及 stride，交接后启动日志停止覆盖系统帧，panic 保留显示能力。原版 HID 服务加载不等于触摸设备适配。临时 AppleKeyStore 状态服务只在 ADT 声明 PackedRAMDisk 临时存储且明确启用时注册，不提供密钥、密码或数据保护操作，不能用于安全存储。OS/SystemOS 仍保持原版，UFS 写入保持关闭。

DarwinBoot 连续内存请求从 512 MiB 提至 1 GiB；实机 DT 存在足够大的高地址 RAM 区间，加载器仍必须从真实 UEFI 常规内存分配成功后才启动，不覆盖保留区。256 MiB RAM Data 继续采用稀疏页存储。1 GiB 的实际分配与运行尚待本轮实机验证。进程日志增加 PID、名称和退出状态，用来区分正常多进程执行与重启循环。

本地原版显示 ABI 审查、全部九项 ADT 检查、framebuffer 交接及 panic 的 ASan/UBSan 检查通过。复用 NativeKeyStoreEvents 边界测试通过；Linux GCC 测试运行额外预包含 cstdint，并关闭测试桩的缩进告警，驱动源码未改。完整 iOS 编译、预链接和硬件显示结果另行记录，当前不声称桌面可用。

### 本轮新增验收目标：Logo 与实际系统界面

用户要求本轮显示 Apple Logo，开机并至少进入 Setup，可参考官方 MobileGestalt / Skip Setup。已按 [MobileGestalt](https://unixnu.com/guide/mobilegestalt) 补齐 iPad7,1/J120、pad artwork、显示倍率及无机械 Home 键的用户态身份，硬件 compatible 保留 oneplus,pkx110/qcom,sm8750。采用参考移植的开发环境状态字段，不代表手机具有 Apple 的安全硬件。构建为每个全新 RAM Data 候选生成独立平台种子，填充 unique-chip-id/chip-id，供 IOPlatformUUID 生成；它是该候选的合成平台标识，不是 Apple ECID 或手机熔丝值，同一镜像重启不变。

Data 准备会清除三个 MobileGestalt 缓存路径，创建容器目录，并设置防自动息屏偏好；保留原始 SetupDone 等状态。[Skip Setup](https://unixnu.com/guide/skip-setup) 已接入现有可选 payload 工具，本候选默认不跳过。用户确认手机已进入 Fastboot，可在镜像检查通过后临时启动。

AppleLogo 来自固定 IPSW 的 Firmware/all_flash/applelogo@2732~ipad.im4p，原始 SHA-256 为 de55e7b7a4eff459118f8a4ec9af79b017cfdbfec4c5b079346e414c68ff1fba。构建期校验身份、iBootIm checksum、230×284 灰度/透明度与 LZSS 解码长度，生成内核使用的头文件，不将 Apple 图片提交 Git。XNU 入口在实际 GOP 上居中显示原版 Logo，日志仍记入阶段缓冲，panic 可覆盖 Logo；系统呈现后诊断绘制让出 framebuffer。Logo 出现只证明启动显示路径运行，Setup/SpringBoard 必须以实际用户态画面验证。

新增十项 ADT、四项 RAM Data 策略测试通过，Logo/显示交接/panic 的 framebuffer ASan/UBSan 测试通过。原版 Logo 提取图已人工检查。完整 iOS 构建及实机界面仍在推进。

第 35 次 Actions（40002433110）已完成原始输入、根窗口策略、Data 种子及原版显示静态 ABI 检查，停在新增显示驱动的编译：复用的 XNU `-Weverything` 将编译记录中缺失的 `EXPORT_HDRS/libsa` 搜索目录升级为错误。已保留完整 ABI/目标参数，改用参考驱动的 `-Wall -Wextra -Werror` 警告集合。日志前面的 bootstrap 未解析驱动符号是生成编译记录时的预期中间结果，后续 archive 编译错误才是本次终止点。第 36 次将合并该修复、原版 Logo 与用户态身份改动。

### 第 37 次：显示后端构建通过并临时启动

第 36 次（40004316536）停在 Xcode 16.4 不支持的 `-Wno-unnecessary-virtual-specifier`；提交 `cead04f` 删除该选项。[第 37 次构建](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40007131314)全部成功。NativeLegacyDisplay、Stage7Probe、NativeKeyStoreEvents 的 iOS 17 对象检查、原版显示 ABI 绑定、最终链接及 panic 参数检查均通过。

下载后的实际 FAT、内核、ADT、trust cache 和 APFS 种子检查通过。内核为 127,664,128 字节，含 29 个原版可执行组件；IOHIDEventDriver 是无独立可执行文件的配置组件，已从实际预链接元数据确认存在。AMFI、PMGR、IOHIDFamily 和 IOMobileGraphicsFamily 的原版可执行段保持一致。原始 Logo 的全部像素位于实际内核中，CPU 呈现与临时 KeyStore 接线均已链接；ADT 的 1 GiB 请求、iPad 身份和临时存储标记符合配置。30 个映像共 2,319 条 kalloc 类型记录，2,081 条参与分池；预算 240 的最大槽位为 28，原算法 ASan/UBSan 重放通过。

Data 卷 UUID 为 `DCA82E33-8DB3-4192-A510-B1A9C6903118`，256 MiB 逻辑镜像打包为 1,015,904 字节。实际 FAT 中的种子与上传文件一致，完整逻辑哈希及内核中的 UUID 检查通过。只读 APFS 解析确认仍仅停用 watchdogd，三个防自动息屏偏好已写入，默认未跳过 Setup。另从原始 OS 核对 `Setup.app` 和 `SpringBoard.app` 均位于只读系统卷，不受 Data 排除 staged_system_apps 的影响。

完整镜像为 `out/oneplus13t/boot/stage7-run-37/boot.img`，87,916,544 字节。封装回验、实际文件哈希、Android v4、160 MiB 内嵌 FAT 和空 Android ramdisk 字段检查通过，UEFI、DTB 与 BootShim 布局保持一致。只读核对设备 `3B15BB01BAT00000`、型号 `sun` 后执行 `fastboot boot`：Sending 2.011 秒、Booting 0.338 秒，均为 OKAY，总计 2.667 秒，退出码 0。日志位于 `out/oneplus13t/logs/stage7-run-37-fastboot.log`。

本轮未刷写分区。当前确认镜像发送和临时启动请求成功，等待手机画面验证 Logo、显示服务和 Setup；触摸、GPU 加速及安全密钥存储尚未实现。Data 修改仍随重启清除。

### 第 37 次真机：持续显示 Logo

用户反馈一直停在 Apple Logo，尚无设置界面。第 37 次在绘制 Logo 后永久屏蔽普通日志，因此现有画面无法区分内核停滞、服务启动失败与进程反复退出；Logo 本身只确认 XNU 早期绘制路径运行。

下一候选保留 Logo 上方的阶段、定时器/内存/UFS、显示服务状态和最后退出进程；观察线程运行 30 次仍未交接显示时，展开最近阶段并继续启动。显示状态和最后一次进程退出独立保存，避免被后续 exec 日志冲掉。还修复首次画面复制失败后诊断仍被关闭的路径：尚无成功帧时释放显示占用；成功帧和 panic 仍受保护。这是源码中确认的条件性缺陷，尚未证明就是本次真机停点。

显示初始化、HID/IOSurface 加载、用户客户端和 GOP start 的入口均记录状态；ADT 补齐与实际未旋转 GOP 一致的 display-rotation=0。framebuffer 的 ASan/UBSan 检查覆盖 30 秒回退、首帧失败恢复、成功交接后的像素保护、持久退出记录及 panic；10 项 ADT 测试通过。此次未根据 Logo 画面推断具体服务故障，也未扩大服务禁用列表。

### 第 38 次：诊断候选构建通过并临时启动

[第 38 次构建](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40011668869)以 `e46eb16` 完成，全部步骤成功。实际 FAT 中的内核、ADT、trust cache、根策略和 RAM Data 配套检查通过，原版安全、显示及 HID 可执行段保持一致。内核为 127,664,128 字节，仍含 29 个原版可执行组件及 IOHIDEventDriver 配置。Data UUID 为 `37B0C3E1-BE3F-471E-BBCE-CDB05ADA267B`，256 MiB 逻辑镜像打包为 1,015,904 字节；实际 APFS 读回确认仅停用 watchdogd，默认未跳过 Setup。

新增显示状态接口、首帧失败恢复接口和 display-rotation=0 均已核对实际负载。编译器将固定诊断提示展开成逐字调用，因此字符串搜索未命中；反汇编确认 30 次轮询比较分支及完整提示字符序列均保留。此处是检查方法的修正，没有为此修改内核或重新构建。

完整镜像为 `out/oneplus13t/boot/stage7-run-38/boot.img`，87,916,544 字节。封装回验、实际哈希和 Android v4 头检查通过，UEFI、原机 DTB、BootShim 与 160 MiB 内嵌 FAT 布局保持一致。用户重新确认 Fastboot 后，只读查询设备 `3B15BB01BAT00000` 和型号 `sun`，再执行临时启动：Sending 2.007 秒、Booting 0.337 秒，均为 OKAY，总计 2.644 秒，退出码 0。日志位于 `out/oneplus13t/logs/stage7-run-38-fastboot.log`。

本轮未刷写分区，物理 UFS 写入继续关闭。当前等待手机新画面；成功发送镜像不代表已经进入 Setup，诊断回退也依赖观察线程继续运行。

### 第 39 次候选：补齐进入初始化向导的运行条件

第 38 次用户反馈日志跑完后仍停在 Logo。本轮对照固定 iPadOS 17.7.11 的 [UniXNU-sheng](https://github.com/UniXNU/UniXNU-sheng/tree/251b291adf941b9953fe3ae66a808b9b626e164d)、[UniXNU-tb128fu](https://github.com/xVanTuring/UniXNU-tb128fu/tree/0d55473e5c3a60656a12123d4c2fa8ea4f4a7383) 和通用显示库。Pong 使用 iOS 16，仅作为设计参考。现有预链接依赖已包含参考的大部分原版组件，未接入不适用于 SM8750 的 GPU 或外设寄存器实现。

DarwinBoot 请求增至 4 GiB，临时 APFS Data 增至 1 GiB。13T 实际 DT 的高地址 RAM 存在 6 GiB 区间；加载器仍须从真实 UEFI ConventionalMemory 成功分配连续窗口，本候选准备时尚未验证真机分配，后续第 39 次已用此配置进入系统界面。Data 使用现有稀疏页后端，1 GiB 低于其 2 GiB 易失卷上限；重启后仍恢复种子。新增同版 migration 偏好避免升级迁移，保持 Setup 完成标记不变。

临时 launchd 策略沿用现有文件方式，增加 identityservicesd、locationd、CommCenter、bluetoothd、PerfPowerServices、iomfb_fdr_loader 和 iconservicesagent。前两项涉及同版参考记录的 SpringBoard/chronod/liveactivitiesd 同步等待链，后续项对应缺少硬件后端或参考机上的反复退出。加上 watchdogd 共八项；每项必须匹配当前原始任务的 Label 和完整 ProgramArguments，匹配失败即停止。此策略不代表已在 13T 捕获相同等待栈，停用图标渲染服务也可能使缺少缓存的图标留白。原始系统任务 plist 不修改。

IOHIDEventDriver 改用参考的匹配加载接口，等待 IOHIDResource 并记录结果。显示库借用 [NativeMobileDisplay 8666a995](https://github.com/UniXNU/NativeMobileDisplay/tree/8666a9950c9699b368931d18cac92c0fdb2ce9c0) 的 work-loop 定时器，向原版客户端发送实际时钟驱动的 60 Hz 软件刷新通知，发布对应固定节奏。它用于软件渲染调度，不代表已适配物理面板 vblank。原版虚表和刷新函数绑定继续在编译期核对。关闭额外 kprintf spam，并使用同版参考的 -no_corpses，避免反复崩溃时收集大型 corpse 占用启动资源。

Sheng 的四处 21H461 用户态兼容修复已与当前磁盘原始指令逐字节核对：AttentionAwareness 初始化锁等待、PosterBoard 两处数据保护属性约束、无蓝牙后端时 BTAudioHALPlugin 的忙重试。内核仅在 ephemeral-storage=1、完整原页通过签名校验且文件名/偏移/原始字节全部匹配时修改内存页，并同步指令缓存；磁盘系统文件不变。实现采用固定四项表，不开放任意地址或启动参数补丁。PosterBoard 调整只适用于当前未实现数据保护的临时卷，不能作为安全存储能力。

新测试直接执行补丁中的兼容函数和显示定时器代码，覆盖非临时环境拒绝、错误文件/偏移/字节、修改范围、重复应用、无订阅者、迟到时钟、定时器释放及固定刷新属性；ASan/UBSan 通过。本地运行关闭 LeakSanitizer，因为受控执行环境不支持其进程跟踪，地址和未定义行为检查仍开启。五项 Data 测试、十项 ADT 测试和隔离源码/驱动补丁复用测试通过。新增内核补丁与现有相关补丁已在固定 XNU 原始文件上共同应用成功。完整 iOS 编译和 Setup 真机结果另行记录。

### 第 39 次：构建、产物检查与临时启动

[第 39 次构建](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40017111424)以 `02c7ccd` 完成，全部步骤成功，包括新增兼容函数和刷新定时器的主机检查、显示驱动 358 项接口布局检查及原生 panic 参数检查。最终内核为 127,668,224 字节，含 29 个原版可执行组件和 IOHIDEventDriver 配置。实际 FAT、ADT 的 4 GiB 请求、trust cache、两份根策略及原版安全/显示/HID 可执行段均通过核对。

Data UUID 为 `A752350A-AB19-41D8-ADF9-01485A68BA56`，1 GiB 逻辑 APFS 打包为 1,020,016 字节，完整逻辑哈希通过。独立 APFS 读回确认八项 disabled 策略、空迁移标记、21H461 migration 偏好和禁止自动暗屏设置；两份 Setup 完成偏好文件均不存在。原始系统输入保持不变。

最终机器码保留了四条固定兼容规则、临时存储开关及原始代码页签名验证后的调用；完整验证且无 taint 才进入修复，修改后调用 cache_sync_page。实际显示虚表第 301 项指向新的刷新属性实现，定时器回调使用真实系统时钟并调用原版通知函数。30 个映像共 2,319 条 kalloc 类型记录，2,081 条参与分池；预算 240 的最大槽位为 28，原算法 ASan/UBSan 重放通过。

完整镜像为 `out/oneplus13t/boot/stage7-run-39/boot.img`，87,924,736 字节。封装回验和实际哈希通过，Android v4 头、空 Android ramdisk 字段、UEFI、原机 DTB、BootShim 与 160 MiB 内嵌 FAT 布局核对通过。用户确认 Fastboot 并授权本轮临时启动后，只读核对设备 `3B15BB01BAT00000`、产品 `sun`，再发送镜像：Sending 2.007 秒、Booting 0.337 秒，均为 OKAY，总计 2.700 秒，退出码 0。日志为 `out/oneplus13t/logs/stage7-run-39-fastboot.log`。

本轮未刷写分区，物理 UFS 写入仍关闭，Data 修改随重启清除。临时启动完成时尚待手机反馈；后续已确认进入系统界面，见下一节。GPU、触摸和无线外设仍未适配。

### 第 39 次真机：进入系统界面，触摸待适配

2026-10-24，用户在第 39 版临时启动后反馈“成功进入系统”，同时确认触摸没有反应。本次据此记录为系统图形界面启动通过：UEFI、DarwinBoot、XNU、只读 OS/SystemOS、临时 Data、原版用户态和显示路径已共同推进到系统画面。反馈未明确区分向导页面与桌面，因此不额外登记“已完成初始化向导”或“桌面应用可交互”。

这次运行使用 4 GiB 内存窗口请求、1 GiB RAM Data、CPU framebuffer 呈现和 60 Hz 软件刷新配置。镜像内容及调用路径此前已核对；此次反馈增加了整机界面启动的证据，不等于可用内存容量、实际帧率、每项兼容修复或所有系统服务都已逐项实测。

触摸无响应符合当前代码范围：已接入 IOHIDFamily / IOHIDEventDriver，尚无 13T 触摸控制器的初始化、硬件事件读取和 HID 触摸报告路径。后续需要完成该输入链路，再验证点击、滑动、坐标方向以及向导和应用交互。UEFI 的侧键候选与 iPadOS 触摸输入属于不同阶段，不能互相替代。

README 已汇总当前全部已支持的启动、运行、存储、显示、诊断和构建能力，并单列部分支持与未完成项。此次只更新文档，不重建或重新启动镜像；`stage7-run-39` 保留为已进入系统界面的基线。物理 UFS 写入继续关闭，Data 随重启恢复种子，GPU、触摸、无线外设和安全存储仍未完成。

### 第 48 次真机：进入系统后出现 UFS 读取超时

2026-10-26，使用 `fastboot -s 3B15BB01BAT00000 boot` 临时启动 `out/oneplus13t/boot/stage7-run-48/boot.img`，没有刷写分区。镜像为 87,945,216 字节，SHA-256 为 `ed302c539495dcae18e21fefe0a424d4f09f2b5f480741dbd5b5f6f7ab44a9fe`。设备返回 `product: sun`、`is-userspace: no`；Sending 和 Booting 均为 OKAY，总计 2.631 秒，日志保存在镜像目录的 `fastboot-boot.log`。对应内核来自设备提交 `e6435b2bda6e91431f3bc0c442d1ff9c47be1451` 的 Actions build 48。

用户确认短暂进入系统，但触摸、音量键、电源键短按和亮度调整均无响应，随后 panic。照片显示最后阶段为 `stage7: system frame copied`，消息为 `UFS ROOT FAILURE: root window read failed`，由 `NativeUfs.cpp:1340` 的诊断函数进入 panic。关键值如下：

| 现场字段 | 观察值 |
| --- | --- |
| 返回值 | `e00002d6`，即读取超时 |
| 请求 / 已读取次数 / 失败次数 | `298005` / `297989` / `1` |
| 轮询次数 | `polls=1` |
| 耗时 / 期限 / 时钟频率 | `1c342e9` / `124f802` / `124f800`，约 1.5403 秒 / 1 秒 / 19.2 MHz |
| 轮询时保存的状态 | `dbSeen=1`、`isSeen=0`、`ocs=0f` |
| 失败后的寄存器与 DMA 快照 | `db=0`、`is=1`、`DMA ocs=0`、`rsp=21000000` |

代码先读取 doorbell 和完成状态，再检查截止时间；两者之间若发生调度延迟，旧代码会依据先前的忙状态直接返回超时。照片中的前后状态与这条竞态路径一致。失败快照采集晚于轮询，也不是原子的；现场没有调度跟踪，尚不能确认是哪段执行造成了长间隔。SMMU 的 `cb=400->400` 没有显示这次请求新增的该位错误，不能单凭这个已有状态判定 SMMU 是根因。

驱动提交 `7ae6c0283f590d6f82ddacee103fa11dc96c3ec5` 在发现到期后再进行一次完整状态采样。确认 doorbell 已清除、OCS 有效后，仍走原有响应、任务标记、LUN、长度和数据校验；仍被控制器占用、未接受或报告硬件错误的请求继续隔离。新增用例先在旧代码上复现误超时，再在修复后通过。`TransferPoll` 和实际 `RootCommands` 的 ASan/UBSan 检查通过，覆盖 SM8750 只读路径及共享实现的其他编译配置。格式 2 的 18 个组件、版本固定及 ADT 检查通过；完整 `test-stage6.py` 也通过，包括 21 处生产 ARM64 汇编检查、队列与协议边界、根窗口读取和 SMMU 测试。随后已完成第 49 次内核构建（见下一节），真机复测仍待进行，三个新增外设尚未通过硬件验收。


### 第 49 次：UFS 完成状态复查候选已构建

[第 49 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40327493773) 全部成功。源码固定为设备 `be18db0025fbde66ffd0a55302f9c1bc0fe3c122`、主仓库 `0853a79ade7da1611e3f757f384cd43d1d7852f2`、驱动 `7ae6c0283f590d6f82ddacee103fa11dc96c3ec5`。18 个组件、UFS 回归、原版接口绑定、完整内核编译与预链接均通过。内核位于 `out/oneplus13t/actions/run-49/kernel/kernel.macho`，127,778,816 字节，SHA-256 为 `ee6a0a0b5d1806965c263b6067c32b77af86e8f858e476f0e33a7c0d4fe4c3fe`。

使用同次构建的信任缓存及 RAM Data，复用未变的 UEFI 固件，执行 `./unixnu payload` 和 `./unixnu bootimg`。最终镜像为 `out/oneplus13t/boot/stage7-run-49/boot.img`，87,945,216 字节，SHA-256 为 `5bceb7c3cac31cafde66d8b349c0fec547684aa16e7266645af544a7ae20564f`。Android v4、空 Android ramdisk、160 MiB 内嵌 FAT 与 stock DTB 的封装回验通过；FAT 读回核对了内核、信任缓存、Data、三个外设启动参数及 ADT 的 4 GiB 请求、根 UUID 和内存映射占位项。

第 48 次镜像和启动日志继续保留。构建与封装通过时，第 49 次尚未上机；随后的实测见下一节。

### 第 49 次真机与后续输入测试候选

2026-10-26，用户授权后，以 `fastboot -s 3B15BB01BAT00000 boot` 临时启动上述第 49 次镜像。发送 85,884 KB，用时 2.012 秒；Booting 用时 0.337 秒，均返回 OKAY，总计 2.674 秒，没有刷写分区。启动后设备退出 fastboot，日志为 `out/oneplus13t/boot/stage7-run-49/fastboot-boot.log`。用户反馈“不再panic了，但是这些功能依然不可用”。本次据此记录为观察期间未复现第 48 次的 panic；未取得持续时长或完整运行日志，触摸、音量键、电源键短按和亮度仍未通过实测。

按用户要求拉取并合并官方 UniXNU `ae68700`，参考[跳过 Setup](https://unixnu.com/zh/guide/skip-setup)和[输入移植](https://unixnu.com/zh/porting/input)指南继续准备候选。上游的 J120AP / product-id 身份、嵌套 ADT 节点及 XNU 补丁与本地 13T 组件共同保留；格式 2 检查已确认补丁可以顺序应用，既有硬件 compatible 和 4 GiB handoff 请求仍在。

RAM Data 生成步骤在新卷已挂载时，合入上游 `seed-data-skip-setup.py` 的五组偏好，标记 Setup 完成，关闭 mini-buddy、云配置入口和自动暗屏，保留原有无关键、mobile 所有权与 0600 文件权限。`ram-data/seed.json` 记录 `setup_skipped=true`。这一步发生在 macOS 的种子准备阶段，因此 Linux 本地封装可直接使用同次构建的成品种子；此路径没有调用 payload 的 `--skip-setup` 二次编辑选项。原始 OS/SystemOS 镜像仍只读，Data 仍随重启恢复。

触控设备的报告描述符改为上游已实测的键盘集合在前、触控集合在后，实际触点仍来自 S3910。该排列用于原版通用 HID 事件驱动的匹配，不代表已确认这就是 13T 无触摸的唯一原因。候选还开启 `pagani-peripheral-status=1`：系统画面顶部保留 `KEYS`、`TOUCH`、`PANEL` 三行，显示初始化阶段、十六进制结果 `r`、十六进制采样值 `v` 和十进制成功报告或 DSI 命令数 `n`。状态每秒以及每次系统画面复制后刷新；普通启动日志继续遵守显示交接，panic 画面不受覆盖。

主机检查已通过 Setup 偏好合并及权限、HID 应用集合顺序和报告长度、触点释放、按键消抖、SPMI/GCC/DSI 模型，以及状态绘制的边界、开关和 panic 保护。完整构建和镜像读回结果见下面的第 50 次记录；直接进入 SpringBoard 及外设响应仍需真机观察。


### 第 50 次：跳过 Setup 与外设状态候选

[第 50 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40337200766) 全部成功。源码固定为设备 `1e98cc4c10c86904d7cafc6cb98dc4a29538628d`、主仓库 `7394044ed7d3e55c94a74890866b085c48f5cde3`、驱动 `a7501893746fea0ab61e7e6541565b56b7d3726b`；SM8750 公共包仍为 `9e90b16861612c0251c453ccbf6cf10592ea87e2`。18 个组件、格式 2 与 UFS 回归、输入和显示对象的原版 ABI 绑定检查、完整内核编译及预链接均通过。内核为 `out/oneplus13t/actions/run-50/kernel/kernel.macho`，127,782,912 字节，SHA-256 为 `c4852b897e2400416ece72e8fd76b8daa9c6ba45c8fd82d71b375ce22d1448ae`。

同次生成的 RAM Data UUID 为 `2B96615F-06A6-42D2-8831-00359E87D78C`，1 GiB 逻辑镜像打包为 1,032,304 字节。打包格式和完整逻辑哈希通过检查；独立 APFS 读回确认五组 Setup 偏好、21H461 migration 标记、防自动暗屏、UID/GID 501 和 0600 权限，内核中的 Data UUID 也一致。`seed.json` 的 `setup_skipped=true` 与实际内容相符。`payload.json` 中 `skip_setup=false` 仅表示本地未使用二次编辑选项，已在云端写好的偏好保留在实际镜像中。

使用同次内核、信任缓存和 Data，复用未变的 UEFI，执行 `./unixnu payload` 和 `./unixnu bootimg`。最终镜像位于 `out/oneplus13t/boot/stage7-run-50/boot.img`，87,949,312 字节，SHA-256 为 `2ff4b9bfc572c85940cac96490dbca24c4c75121c451c3f488202831de8497c8`。Android v4、空 Android ramdisk、160 MiB 内嵌 FAT 读回通过；实际负载的内核、信任缓存、Data、ADT、4 GiB 内存请求、根 UUID、J120AP/product-id 和四个外设启动参数均与报告及配置一致。第 49 次镜像继续保留。

2026-10-26，在已连接的 `3B15BB01BAT00000` 上读取到 `product: sun` 和 `is-userspace: no` 后，用 `fastboot boot` 临时启动第 50 次镜像。发送 85,888 KB 用时 1.979 秒，Booting 用时 0.337 秒，均为 OKAY，总计 2.579 秒，没有刷写分区。输出保存在该镜像目录的 `fastboot-boot.log`。这确认引导器接受了镜像；是否进入 SpringBoard，以及 `KEYS / TOUCH / PANEL` 状态和实际外设响应，等待手机观察反馈。


### 第 50 次锁屏与触控故障定位

用户照片确认第 50 次已显示壁纸、日期时间和底部手势条，进入锁屏，跳过 Setup 生效。照片第一行显示 `PMIC sample r=0 ... n=8`，用户观察到音量键和电源键操作会增加计数，并进一步确认电源键短按可亮灭屏、长按可打开关机界面。音量变化的实际系统效果尚未单独确认。触控行停在 `TouchComm start r=ffffffb9 ... n=0`；`ffffffb9` 对应适配层的 `-71`，表示协议校验失败，尚未进入 HID 触点上报。`v` 被摄像头遮住，用户也无法读出。第三行记录 `DSI disabled r=e00002d8`；按用户要求，本轮只处理触控。

对照用户指定的 [data-a-live S3910P 代码](https://github.com/ShueiTsuki/data-a-live/blob/ba094818ed915cd3689937180a6f619c0e9c86ef/wsl/pandora_touch.c)、[OnePlus S3910 HBP 原厂实现](https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8750/tree/6a196f79f77acd55cf302e1696c038e4cad99254/vendor/oplus/kernel/tp/hbp/hbp/chips/synaptics/s3910)，并检查 UniXNU 列表中的 [T733](https://github.com/RigoLigoRLC/unixnu-sm-t733/blob/7ec704db1f60d99ea8606aabada919ed2dcbae1b/package/T733Touch.cpp) 与 [pong](https://github.com/Chengdong-Yu/UniXNU-pong/tree/ab74f075320fe54eee24d5d150386e5b0f0f427f)。T733 使用 FocalTech、pong 使用 Goodix；data-a-live 的 S3910P 协议最接近，但其 SM8850 GPI、电源引脚和 Xiaomi 原始帧矩阵与 13T 不同。

源码中确认两处兼容性缺口：13T 读 SPI 时未像原厂一样同时发送全 `0xff` 字节；协议层只接受 v1 的 `0xa5` 标记，不能处理 v2。实际失败报头尚未取得，因此这两处缺口仍是本次故障的候选原因。新实现修正全双工读法，在通过报头校验后选择 v1/v2；v2 核对 CRC6/CRC16，按芯片公布的上限分片，处理 ACK/RETRY，并在命令重发时保留序列位。原有 LBP 设置、报告格式读回及触点生命周期继续使用 13T 路径。复位后的等待对齐 OnePlus S3910 的 100 ms，命令等待采用最多 300 次、间隔 10 ms 的轮询。未加入其他机型的 GPIO、RPMh/GPI 或触摸矩阵配置。

诊断行下移四个文字行，避开摄像头；触控错误显示 `T<协议版本> <命令> <阶段>`。版本 0 表示尚未识别到有效协议报头；`header/continued` 的 `v` 按小端保存收到的前四字节，其他校验阶段保存失败的长度、状态或数值。主机回归先在旧的实际 `readTouch` 回调上复现缺少 `0xff` 发送数据，再验证修改后通过；v1/v2 报文、固定命令字节、独立 CRC、分片、延迟响应、重试、损坏报文及有界原始帧排空均通过 ASan/UBSan。状态绘制的保护范围、camera 区域保留、显示交接和 panic 保护也通过。完整构建及封装结果见下一节，真机触摸效果仍待验证。

### 第 51 次：S3910 协议修复候选

[第 51 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40351567815) 全部成功。源码固定为设备 `9d9726f53038aa5d090dd13502064de9b4c94128`、主仓库 `e719753b199ef642c591218fb46b0f9f460d3b97`、驱动 `6ac9935624dfeed5106568162dd8c50f79a51c4b`；SM8750 公共包保持 `9e90b16861612c0251c453ccbf6cf10592ea87e2`。18 个组件、格式 2、UFS 和触控协议回归、C/C++ 对象编译、原版及编译后 HID/背光 ABI 检查、完整内核链接和预链接均通过。内核位于 `out/oneplus13t/actions/run-51/kernel/kernel.macho`，127,799,296 字节，SHA-256 为 `dfb1b54c85e853c12db3f4042644629460743076583fdfa47d0178e06e09f96a`；实际内核包含新增协议阶段诊断。

同次 RAM Data UUID 为 `33B58198-95BA-4B5A-A00E-DBAA5C52AFFE`，与内核一致。1 GiB 逻辑 APFS 的打包及完整逻辑哈希通过，独立读回确认五组 Setup 偏好、防自动暗屏、migration、UID/GID 501 和 0600 权限。使用同次内核、信任缓存和 Data，复用未变的 UEFI，执行 `./unixnu payload` 与 `./unixnu bootimg`。

最终镜像为 `out/oneplus13t/boot/stage7-run-51/boot.img`，87,953,408 字节，SHA-256 为 `3c1017d97dfdc3014a3770fa9e1223e98ead65882f47fbaf0b641f8be94b080e`。Android v4、空 ramdisk、内嵌 UEFI 和 160 MiB FAT 回验通过；从 FAT 实际提取的内核、信任缓存、Data、ADT、4 GiB 请求、根 UUID、J120AP/product-id 及四个外设参数均匹配。第 50 版镜像继续保留。

2026-10-27（北京时间），对设备 `3B15BB01BAT00000` 只读核对 `product: sun`、`is-userspace: no` 后执行 `fastboot boot`。发送 85,892 KB 用时 2.025 秒，Booting 用时 0.338 秒，均为 OKAY，总计 2.649 秒；日志为该镜像目录的 `fastboot-boot.log`。没有刷写分区。引导器接受镜像后，触控响应及 `T0/T1/T2` 状态等待用户观察；本次只修正触控兼容性和诊断位置，亮度问题暂未处理。

### 第 51 次真机：首次 SPI 传输超时

用户确认点击仍无反应，状态为 `TOUCH T0 00 header r=ffffff92 v=0 n=0`。`ffffff92` 对应 `-110`；此处 `s3910_start()` 的第一次 `message()` 尚未发送识别命令，4 字节读回调就从 `geni_spi_transfer()` 返回超时。`v` 在调用读回调前清零，传输成功后才写入报头，因此不能把本次 `v=0` 解释为芯片返回全零，也不能据此判定 TouchComm v1/v2。

对照现有 Sheng 探测实现、T733 和 data-a-live：不同板型分别采用保留顶层 IRQ 使能的 SE DMA、FIFO PIO 或 GPI DMA。当前缺少 13T 的 `GENI_IF_DISABLE_RO`、完成状态和 FIFO 现场，尚不能确定应修改哪一条路径。下一候选仅把 `QcomGeniSpi` 已在取消命令前保存的 `status/irq/txfs/rxfs` 连同初始化时的 `firmware/if_disable` 显示为两条 `SPI` 行；失败后继续停止触控并释放触点。保持现有 GPIO、时钟、IRQ 路由和传输模式，避免恢复后的寄存器覆盖故障现场。

主机测试执行实际读写回调，验证超时快照传递、成功时不发布错误、后续传输清除旧快照标记及读参数边界；既有 v1/v2、触点、按键与 GENI 回归通过。显示测试确认新增两行位于摄像头下方，保持图像边界、开关和 panic 保护。完整内核构建与寄存器真机读数待下一轮记录。

### 第 52 次：早期控制台编译检查与修正

[第 52 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40358763110) 通过配置、输入回归及输入对象编译，但在最终 XNU 编译调用早期控制台构建时被现有检查拦截：`BootProgress.o` 新增 `_bzero` 依赖。状态行从三行增至五行后，局部副本由 240 字节变成 400 字节；启用自动栈清零的 ARM64 编译会为该数组生成外部清零调用。该检查限制早期控制台在内核服务可用前调用运行时助手，未因此生成新的可启动内核。

修正把状态行副本改为逐行 80 字节，每次复制仍检查显示交接、busy 与 panic 状态。使用实际函数、ARM64 Apple 目标、自动栈初始化和相同 freestanding 限制，在旧函数上复现 `_bzero`，修改后确认没有 `_bzero/_memset/_memcpy` 调用；ASan/UBSan 显示边界和 panic 保护检查也通过。保留自动初始化及生产依赖检查，等待第 53 次完整构建。

### 第 53 次：SPI 超时现场镜像与临时启动

[第 53 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40361680754) 全部成功，包括修正后的早期控制台运行时依赖检查。源码固定为设备 `c5edbf3617dd5effd63b74f915218539adca1476`、主仓库 `335699bffbe0958f66f316c29dc8db499e7116d3`、驱动 `4f8206071a7188b283846f973a16f0cf0df9b7c2`；SM8750 公共包保持原版本。18 个组件、输入和存储回归、原版及编译后对象 ABI 检查、完整链接与预链接均通过。实际内核含两条新增 SPI 诊断格式，大小 127,799,296 字节，SHA-256 为 `6ed39dd4e001197a1d08ca46d0ca5d38b7c38fec48e4d0b593244c08c8d42b6f`。

同次 RAM Data UUID 为 `A117890E-4D7A-4B21-8D46-CE0494D928B0`，与内核一致；1 GiB 逻辑哈希和打包格式通过，独立 APFS 读回确认五组 Setup 偏好、migration、防自动暗屏、UID/GID 501 与 0600 权限。使用同次内核、信任缓存和 Data，执行 `./unixnu payload`、`./unixnu bootimg`，生成 `out/oneplus13t/boot/stage7-run-53/boot.img`，87,953,408 字节，SHA-256 为 `ca75c2fc6953c92e30eb1897d95589756a85b5ce93666dcd70d62c52abd1149d`。Android v4、空 ramdisk、未变的 UEFI、160 MiB FAT 及其中实际内核、信任缓存、Data、ADT 身份、根 UUID、4 GiB 请求和四个外设参数回验通过。

2026-10-27（北京时间），在用户已恢复 Fastboot 后核对设备 `3B15BB01BAT00000`、`product: sun` 和 `is-userspace: no`，临时启动上述镜像。发送 85,892 KB 用时 2.010 秒，Booting 用时 0.336 秒，均为 OKAY，总计 2.677 秒，未刷写分区；日志保存在该镜像目录的 `fastboot-boot.log`。等待 `TOUCH` 和两行 `SPI` 读数。本版仅补齐失败现场，尚未更改 FIFO/DMA 选择或 IRQ 路由，也未确认触控恢复。


### 第 53 版反馈：FIFO 关闭，接入 SE DMA 候选

用户抄录的现场为：

```text
TOUCH T0 00 header r=ffffff92 v=0 n=0
SPI fw=102 if=1 st=41 irq=0
SPI FIFO tx=0 rx=0
```

触控仍无响应。`if` 的 bit 0 确认 FIFO 接口关闭；`st` 的 bit 0 表示主引擎仍忙。FIFO 状态为空，首次四字节读取没有完成，尚未进入 TouchComm 协议识别。`st=0x41` 不表示 secondary engine 活跃，该位在 bit 12。

当前候选在 FIFO 关闭时使用现有 QcomGeniSpi 的 SE DMA 分支。13T 实际 DTB 给出 QUP stream `0xa3`、apps SMMU `0x15000000/0x100000`；GPI 的 stream 不用于这条路径。驱动分配独立的 4 KiB TX/RX 页，显式维护缓存，并复用现有 SMMU 规划器寻找独占 VA64 bypass bank。UFS 映射保持原样；已有翻译、共享、掩码、重复映射或固件 bank 0 会被拒绝，屏幕显示对应 SMR/S2CR，不扩大固件映射接管范围。

SE 内部状态生成保持开启，ArmCpu 已在 GIC 初始化时屏蔽未使用的 SPI，中断仍未接入处理函数。DMA 失败显示状态及 TX/RX length-in 计数。由于该板的 DMA reset 完成尚未验收，暴露给硬件的 8 KiB 缓冲区保留到重启，避免错误路径释放仍可能被访问的内存。

本地 ASan/UBSan 的协议、实际读写适配器、PIO/SE DMA 模型、两种 SMMU 构建配置及显示/panic 回归通过。完整对象编译和这条 DMA 路径的实机行为尚未验证；触控不能标为可用。


### 第 54 次：SE DMA 候选构建与临时启动

[第 54 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/40369222494) 全部成功。源码固定为设备 `fba147283bead8e3e9f7c3ce9edc36f012bb1ec9`、主仓库 `1397e2ddbea6fd052897a92047c8ed56f8afd7f9`、驱动 `26a32f52812c9b4cf76da4a668a68bd0997589d7`、SM8750 公共包 `b6706a5d941808e81851e783de450913f33d5f8a`。18 个组件、配置和生产约束、UFS/触控回归、原版及编译后 HID/背光 ABI、早期控制台运行时检查、完整内核链接和预链接均通过。实际内核含 DMA 与 SMMU 诊断格式，大小 127,799,296 字节，SHA-256 为 `1491d7140e11c84157732bb33b9d4ed9cadf3b0dfe978db7901d3c814988dfc6`。

同次 RAM Data UUID 为 `A2F3B373-709F-4496-991A-9627B4EA1FAA`，与内核一致；完整 1 GiB 逻辑哈希和打包格式通过，独立 APFS 读回确认五组偏好及 UID/GID 501、0600 权限。配套镜像为 `out/oneplus13t/boot/stage7-run-54/boot.img`，87,953,408 字节，SHA-256 为 `04bb97f75226933ff612847ba851b77d807dac27e581e60c6f6b6b4ab4af70dc`。Android v4、空 ramdisk、未变 UEFI、160 MiB FAT 及其中实际内核、信任缓存、Data、ADT 身份、根 UUID、4 GiB 请求和四个外设参数回验通过。第 53 版镜像保留。

用户回复“#54 已连接”后，核对序列号 `3B15BB01BAT00000`、`product: sun`、`is-userspace: no` 和镜像哈希，执行 `fastboot boot`。Sending 用时 2.009 秒、Booting 用时 0.338 秒，均为 OKAY，总计 2.673 秒，未刷写分区。日志位于镜像目录的 `fastboot-boot.log`。等待本版 `TOUCH` 与 `SPI DMA` 或 `SMMU` 读数；这些主机与传输结果尚未证明 DMA 已在手机上完成数据搬运，也未证明触控恢复。


### 第 54 版反馈：全零协议头与成功读取诊断

用户反馈“下面两行没有出现。只有 `TOUCH T0 00 header r=ffffffb9 v=0 n=0`”。依据本版代码，SPI 调用返回成功后，解析器将四个 RX 字节打包到 `v`，随后拒绝全零协议头并返回 `-71`。初始化在 `IOHIDDevice::start` 之前退出。该结果证明软件走过了传输完成分支，仍不能证明有效 S3910 数据或用户态触摸链路已工作。

原诊断只在 SPI 返回错误时显示，所以此次协议层失败没有下方两行。当前候选在首次成功读取时保留 `SPI RX n=... h=... a=.../... rst=...` 和 `SPI dma=... ti=... ri=... st=...`。数值均为十六进制；`h` 为前四字节的小端打包值，`a` 为 ATTN 读取前/后电平，`rst` 为 RESET GPIO IN_OUT 的低两位（输入 bit 0、输出锁存 bit 1），`ti/ri` 为库保存的 TX/RX length-in，`st` 为调用返回后的 GENI 状态。后续协议拒绝保留该现场，传输错误仍显示原有取消前快照。

本轮保留 SE DMA、复位等待和协议判定。实际适配器测试覆盖“SPI 成功但四字节为零，TouchComm 报 -71，现场仍保留”，也覆盖首次快照不被后续成功读取覆盖、短读边界和失败时避免读取恢复后的状态；ASan/UBSan 协议与 PIO/SE DMA 模型、显示/panic 检查通过。完整对象编译和新镜像实测待完成。
