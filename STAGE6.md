# Stage 6：一加 13T 存储与根卷

更新：2026-10-23。当前处于只读 UFS 探测准备阶段，尚未完成 XNU 根卷挂载或 `launchd` 启动。

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

启动内核继续使用 boot 镜像路径。根卷镜像文件沿用工具名称 `userdata-root.img`，目标分区为 `unixnu`。根卷、后续 Data 持久化与诊断落盘都应限定在这个新分区；本阶段关闭持久写入。

## 已完成的本地适配

- `patches/native-ufs-sm8750.patch` 基于 NativeUfs `af785c1777161a62931425c2faaa536ce0bebd5b`，补齐 SM8750 GCC 偏移、时钟检查、MCQ 拒绝、LUN 容量枚举和精确分区选择。SM8750 根目标固定为 `unixnu`，找不到时停止。
- 只读构建关闭 Data/日志写窗口，并在 SCSI 入口拒绝写命令。探测模式保留共享的传输、GPT、manifest 和 SMMU 代码，不依赖尚未预链接的 IOStorageFamily。
- `unixnu --prepare` 将设备补丁应用到独立缓存，补丁摘要参与缓存名称。
- 镜像生成器使用 `[userdata].partition` 输出部署命令，13T 配置指定 `unixnu` 及实测 64 GiB 范围。
- 主机 ASan/UBSan 检查通过：时钟门控、LUN 枚举、SCSI/队列故障、MCQ 拒绝、写入拒绝、GPT/manifest、实际采集 GPT、SMMU 和跨块读取。实际 ADT/设备树核对及源码隔离测试通过。

寄存器来源为原机 `sysinfo/live.dtb` 与本地 OnePlus 源码：`gcc-sun.c` 所在内核提交 `745702d5ed2c0435f2b1d3bb78bc4f48422d4191`，设备树提交 `6a196f79f77acd55cf302e1696c038e4cad99254`。UFS 为 `0x1d84000/0x3000`，apps SMMU 为 `0x15000000/0x100000`，stream ID 为 `0x60`。AHB、UniPro、ICE、PHY AUX、聚合 AXI 等时钟偏移与 SM8550 不同。

## 当前断点与下一步

1. 用现有 macOS Actions 构建带 NativeUfs 的源码内核和 FAT payload，检查链接与镜像内容。当前默认 `native-ufs-probe=2`，只读 GCC/UFS 寄存器后通过诊断 panic 页面显示结果。
2. 本地打包完整 boot.img，经 `fastboot boot` 临时启动；记录 `gdsc/axi/ahb/aggre/hc_read/cap/ver/hcs/hce/memcfg/rsr/ahit`。诊断 panic 后停住是探测模式的预期行为。
3. 只有电源、时钟和旧式队列条件满足后，使用 `native-ufs-probe=10` 检查控制器接管、SMMU、LUN、GPT 和 `unixnu` 首块。预期首末 LBA 与上表一致，空分区 manifest 状态为 1。若时钟关闭或 MCQ 活跃，按实际停点继续适配，不能忽略拒绝条件。
4. 准备匹配的 IPSW、APFS/IOStorageFamily 预链接、平台 provider、签名根窗口及 UUID。当前源码探测内核不发布根卷，不能仅追加 `native-ufs-root=1` 启动系统。
5. 生成根卷镜像，核对容量及目标后部署到 `unixnu`，用模式 11 读取窗口，再切换具备完整根卷支持的内核。只有看到根卷挂载和 `launchd` 启动，才能将 Stage 6 标为完成。

当前未刷写任何手机分区，未启用 Data 持久化或诊断日志落盘。已实测的 run-9 回退镜像仍位于 `out/oneplus13t/boot/xnu-source-run-9-root-panic/boot.img`。

## 恢复检查

在设备仓库执行：

```sh
python3 scripts/test-upstream.py
python3 scripts/test-adt.py
python3 scripts/test-stage6.py --captured sysinfo/stage6-20261022
```

云端没有原机采集文件，使用 `python3 scripts/test-stage6.py --tree "$UNIXNU_TREE" --openssl-prefix "$(brew --prefix openssl@3)"`。构建日志位于 `out/oneplus13t/logs/`。发生额度中断时，从本节及“当前断点与下一步”续接；无需重新分区。
