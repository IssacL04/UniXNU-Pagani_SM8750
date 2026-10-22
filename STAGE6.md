# Stage 6：一加 13T 存储与根卷

更新：2026-10-23。第 11 次内核曾在真机读到 UFS 控制器寄存器；后续启动稳定停在早期 VM 初始化。第 12 次照片已将停点缩小到 `vm_pages` 页描述符数组的映射循环，哈希桶、锁数组与 `vm_tag_init` 均已通过。正在增加每页地址和页表分配日志，区分具体等待路径。8.74 GiB 的 iPadOS 根镜像已生成并通过本地校验，尚未写入手机。XNU 根卷挂载及 `launchd` 启动仍未完成。

最终目标是在一加 13T 上启动 iPadOS 用户态和界面。当前源码 XNU 仅用于打通硬件路径；本阶段以 iPadOS 根卷挂载及其 `launchd` 启动为验收条件，图形界面仍需后续用户态、显示与输入适配。

## iPadOS 输入

`board.toml` 已选择上游移植路线固定的 iPadOS 17.7.11（21H461，iPad7,1 / j120ap）Apple 恢复包，并固定 OS 与 SystemOS DMG 的 SHA-256。2026-10-23 通过 Apple CDN 的实际 BuildManifest 核对了版本、机型及 Erase identity；OS 为 `044-76040-038.dmg`（5,157,406,069 字节），SystemOS 为 `044-76034-038.dmg`（3,303,014,400 字节）。两份下载均通过固定哈希校验，保存在 `out/ipsw/21H461/`。版本核对日志为 `out/oneplus13t/logs/stage6-ipados-17.7.11-info.log`。

本地使用 Apple LZFSE 和 [dmg2img 的完整 LZFSE 块解码版本](https://github.com/citruz/dmg2img/commit/88295c834532310764f8883ae81328999118aad0) 转换 OS，原始磁盘为 6,077,580,800 字节。六个 UDIF 分段 CRC、主备 GPT 的 header/表 CRC、两份分区项一致性和 APFS 容量全部通过；UDIF ignore 块按格式排除在分段 CRC 之外，转换结果对应范围为零。SystemOS 本身就是原始 APFS，直接保留。通过项目现有 manifest 写入代码封装后，根镜像位于 `out/oneplus13t/unixnu-root/unixnu-root.img`，共 9,382,658,048 字节（8.74 GiB），适合 64 GiB 的 `unixnu` 分区。OS/SystemOS 窗口完整读回 SHA-256、manifest 哈希及生产 NativeUfs 解析器检查通过，解析器输入为真机采集 GPT 加本地镜像。配套 `unixnu-root.json` 记录实际布局、哈希、转换来源及 `hardware_tested=false`；构建日志为 `out/oneplus13t/logs/stage6-root-image-build.log`。本轮未使用 macOS hdiutil，也未验证真机 APFS 挂载。

DeviceTree、两份 trust cache 和原始 KernelCache 也已从同一恢复包提取。`out/ipsw/21H461/kernelcache.decompressed` 为 46,415,872 字节，SHA-256 为 `f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7`，与参考移植固定值一致。输入准备完成仍不代表 kext 预链接完成。

`kernel.source_only` 暂时保留，用于当前硬件探测。还需接入匹配的 Apple APFS、IOStorageFamily、trust cache、平台 provider、根卷策略和预链接内核；配置 IPSW 不表示这些步骤已经完成。手机硬件配置继续使用 13T 的实际地址与内存范围。

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

只读采集保存在本地 `sysinfo/stage6-20261022/`：主、备 GPT、`unixnu` 首块、几何信息和 Android UFS 状态。该目录不上传。Android 驱动读取成功证明分区存在；XNU 接管控制器仍需独立真机验证。

启动内核继续使用 boot 镜像路径。本轮根卷镜像命名为 `unixnu-root.img`，目标分区为 `unixnu`；通用工具默认输出名仍为 `userdata-root.img`。根卷、后续 Data 持久化与诊断落盘都应限定在这个新分区；本阶段关闭持久写入。

## 已完成的本地适配

- `patches/native-ufs-sm8750.patch` 基于 NativeUfs `af785c1777161a62931425c2faaa536ce0bebd5b`，补齐 SM8750 GCC 偏移、时钟检查、MCQ 拒绝、LUN 容量枚举和精确分区选择。SM8750 根目标固定为 `unixnu`，找不到时停止。
- 只读构建关闭 Data/日志写窗口，并在 SCSI 入口拒绝写命令。探测模式保留共享的传输、GPT、manifest 和 SMMU 代码，不依赖尚未预链接的 IOStorageFamily。
- `unixnu --prepare` 将设备补丁应用到独立缓存，补丁摘要参与缓存名称。
- 镜像生成器使用 `[userdata].partition` 输出部署命令，13T 配置指定 `unixnu` 及实测 64 GiB 范围。
- 主机 ASan/UBSan 检查通过：时钟门控、LUN 枚举、SCSI/队列故障、MCQ 拒绝、写入拒绝、GPT/manifest、实际采集 GPT、SMMU 和跨块读取。实际 ADT/设备树核对及源码隔离测试通过。

寄存器来源为原机 `sysinfo/live.dtb` 与本地 OnePlus 源码：`gcc-sun.c` 所在内核提交 `745702d5ed2c0435f2b1d3bb78bc4f48422d4191`，设备树提交 `6a196f79f77acd55cf302e1696c038e4cad99254`。UFS 为 `0x1d84000/0x3000`，apps SMMU 为 `0x15000000/0x100000`，stream ID 为 `0x60`。AHB、UniPro、ICE、PHY AUX、聚合 AXI 等时钟偏移与 SM8550 不同。

## 当前断点与下一步

1. [第 11 次 Actions](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/39835493916)以 `3d7f658` 构建成功，产物位于 `out/oneplus13t/actions/run-11/`。最终 Mach-O 已包含 NativeUfs；独立内核与 FAT 内核一致，内核和 payload 哈希与云端报告一致。该镜像配置为 `native-ufs-probe=2`，只读 GCC/UFS 寄存器后通过诊断 panic 页面显示结果。
2. 完整镜像位于 `out/oneplus13t/boot/stage6-run-11-registers/boot.img`，大小 15,216,640 字节；v4 头、内嵌 64 MiB 负载、UEFI 与原机 DTB 解包比对通过。类型记录由 1,265 增至 1,266，参与分池的记录由 1,118 增至 1,119；使用同版 XNU 原始预算函数重放，`kt_fixed_zones=240` 最大槽位仍为 30，ASan/UBSan 检查通过（当前沙箱禁用 LeakSanitizer）。已对序列号 `3B15BB01BAT00000`、槽位 B 执行临时启动，fastboot 的 Sending 和 Booting 均返回 OKAY；日志为 `out/oneplus13t/logs/stage6-run-11-fastboot.log`。后续照片已确认内核显示探测结果，见下节。诊断 panic 后停住是探测模式的预期行为。
3. 寄存器照片已确认电源、时钟和旧式队列条件满足；模式 10 首次启动停在早期 `pmap_steal` 日志，当前先用详细初始化日志定位。越过停点后，再核对控制器接管、SMMU、LUN、GPT 和 `unixnu` 首块；预期首末 LBA 与上表一致，空分区 manifest 状态为 1。若时钟关闭或 MCQ 活跃，按实际停点继续适配，不能忽略拒绝条件。
4. 准备匹配的 IPSW、APFS/IOStorageFamily 预链接、平台 provider、签名根窗口及 UUID。当前源码探测内核不发布根卷，不能仅追加 `native-ufs-root=1` 启动系统。
5. 根卷镜像已生成并完成本地校验。先确认 XNU 只读 GPT/首块探测，再将镜像部署到 `unixnu`，用模式 11 读取窗口，随后切换具备完整根卷支持的内核。只有看到根卷挂载和 `launchd` 启动，才能将 Stage 6 标为完成。

## 真机寄存器结果与第二轮启动

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

当前未刷写任何手机分区，未启用 Data 持久化或诊断日志落盘。已实测的 run-9 回退镜像仍位于 `out/oneplus13t/boot/xnu-source-run-9-root-panic/boot.img`。

## 恢复检查

在设备仓库执行：

```sh
python3 scripts/test-upstream.py
python3 scripts/test-adt.py
python3 scripts/test-stage6.py --captured sysinfo/stage6-20261022
```

云端没有原机采集文件，使用 `python3 scripts/test-stage6.py --tree "$UNIXNU_TREE" --openssl-prefix "$(brew --prefix openssl@3)"`。构建日志位于 `out/oneplus13t/logs/`。发生额度中断时，从本节及“当前断点与下一步”续接；无需重新分区。
