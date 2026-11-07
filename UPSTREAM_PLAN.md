# OnePlus 13T 上游适配计划

本轮在 main 上适配 Metal、SMMU、Turnip、诊断、Wi-Fi、USB、图标服务、触控和灭屏绘制，保持 SM8750 / Adreno830 / iPadOS 17.7.11（21H461）目标。2026-11-07 的 Run 41 已完成全新内核、macOS Metal/Turnip 与 Wi-Fi 服务构建、签名 Data/trust 打包和主机回归，并生成配套测试 `boot.img`。本轮实机验收留待用户手动进行。

## 基线

- 留档分支：[archive，12b4e06](https://github.com/IssacL04/UniXNU-Pagani_SM8750/tree/12b4e06852d65d05e7839c6e0a5c0c16c1252a09)。它保存 Run 36 对应的设备源码、组件引用、v19 源码补丁包及实机记录。
- [Run 36](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/41918525305) 已完成完整内核和 Metal 构建；用户确认桌面启动，反馈应用内滑动明显改善，冷启动和桌面滑动仍会掉帧。“接近 120 帧”是主观反馈，尚无逐帧测量。
- 保留现有固件、256 GB 分区布局、内存窗、CPU 调频和 A830 板级适配。每批修改固定来源提交，以同一套配置和输入构建；archive 保留为回退点。
- 配对内核、Data、trust 和 boot.img 的本地位置见 [STAGE6.md](STAGE6.md)。Git 分支不包含这些二进制产物，也不会延长 Actions 产物保留期限。

## 实施顺序

| 批次 | 适配内容 | 完成条件 |
| --- | --- | --- |
| 0 | 建立本地编译基线，并补齐编码、完成回调、资源释放、线程身份和图标服务的关联诊断；保留日志过滤，线程栈采样只读取状态稳定的等待线程 | 未改功能的基线可重复编译；相同场景能区分 CPU 编码、内存处理、GPU 和显示等待，诊断不引入明显停顿 |
| 1 | Metal 图像内存复用、退役资源后台释放、分配重试前回收及空闲块复用，覆盖上游运行时补丁 0027～0030；编码线程继承 CoreAnimation 渲染线程策略；队列销毁或降级时撤销旧优先级提升 | 内存压力、资源生命周期、编码和队列优先级回归通过；保持 A830 当前单环提交约束，比较冷启动与桌面切换长帧 |
| 2 | ArmSmmu4K 按需分配页表和批量映射叶表遍历优化，同步迁移 A830 调用方及测试夹具 | 映射、解映射、别名检查、分配失败和 TLB 同步回归通过；内核编译及链接通过，再观察映射耗时和页表占用 |
| 3 | Turnip 临时附件、GMEM 内存侧颜色交换、逐线程渲染模式及颜色自检；同步必要的队列优先级接口 | SYSMEM 基线保持可用；GMEM 单独比较颜色、透明度、纹理及帧时间，实机通过后再决定默认渲染路径 |
| 4 | 将新版 mac80211/cfg80211、wpa_supplicant 和连接生命周期接入 PaganiWifi；补齐认证服务、Data 固件、签名与 trust 打包 | 保留 Peach/WCN7880 的供电、PCIe、DMA 和固件适配；按阶段验证启动，再验证扫描、WPA2、DHCP、收发、断线重连及开关 Wi-Fi；接入 21H461 的 Apple80211 通知 ABI |
| 5 | 适配图标服务诊断和按服务设置 launchd 环境的能力；在 21H461 上确认服务入口、渲染选择和缓存行为 | 新装应用、冷启动、桌面、文件夹及重启后的图标完整；比较默认、Metal 和软件渲染的实际结果，按证据选择配置 |
| 6 | 将手势起点、触点身份、短暂丢点处理和抬手事件优化迁移到 S3910 TouchComm/HID 路径，并结合触摸到显示的时间记录检查滑动节奏 | 单指滚动、点按、边缘手势、多指及交叉移动通过；无卡住触点、误释放或手势起点漂移，滤波不得引入可感知延迟 |

每批先完成对应的本地检查，再构建候选镜像并记录设备结果。图标服务沿用原系统服务，不以关闭服务掩盖卡顿；Sheng 的环境变量需要核对 21H461 行为。触控只迁移适用的事件处理逻辑，保留 S3910 协议、坐标和板级参数，不直接替换为 Novatek 驱动。

上游来源固定为本次已抓取快照：UniXNU `13e5973`、AdrenoMetal `e82788d`、ArmSmmu4K `83969cd`、Ath12kWifi `28de7b9`、UniXNU-sheng `4601795`、ShengNovatekTouch `69fdd62`。实现时在提交记录中注明具体移植提交和本地适配。

## 2026-11-07 本地进度

| 批次 | 已完成 | 验证边界 |
| --- | --- | --- |
| 0 | 复用已成功构建的 Run 36 本地基线；迁入线程、编码、完成、资源释放和图标诊断，栈采样限于持锁的稳定等待线程 | 诊断 ABI 和线程状态回归通过；未测量手机长帧 |
| 1 | 迁入运行时补丁 0027～0030、CoreAnimation 编码线程策略继承和队列优先级回收 | 队列优先级回收、macOS 堆别名与复用、重复释放及完成回调 QoS 回归通过；长期内存压力和手机帧时间仍待测量 |
| 2 | ArmSmmu4K 更新到 `83969cd`；A830/GMU 改为按需分配页表，补齐分配失败回滚、调用方和夹具 | 映射、跨 4 GiB 地址、TLB、客户端与生命周期相关回归通过，完整内核通过 |
| 3 | 接入临时附件、GMEM 内存侧颜色交换、逐线程模式和颜色自检；适配本地诊断补丁上下文 | 默认继续使用 `sysmem,nocb`；颜色、透明度及帧时间等待实机比较 |
| 4 | 接入锁定的 mac80211/cfg80211、原版 wpa_supplicant、控制通道、21H461 Apple80211 事件、launchd 缓存合并及签名/trust/Data 接线；保留 Peach 固件与校准路径 | 115 项系统接口检查、主栈完整退出、WPA2/开放网络、重密钥、错误密码与重放拒绝通过；WCN7850 及 Peach 的 6 种校准场景通过 ASan/UBSan。Run 40 已生成并验证新签名包，包含本机两个 ODM 固件文件；硬件开关仍默认关闭，实机连接尚未验证 |
| 5 | 接入图标服务诊断、Data 启用项及按服务设置 launchd 环境的能力，默认保留原系统环境 | launchd 合并与原条目保留测试通过；图标完整性、缓存及渲染选择待实机比较 |
| 6 | S3910 保留控制器触点 ID，首次按下投递失败时保留起点，抬手重试，连续三次读错才释放触点 | S3910/SPI、面板和显示时序综合回归通过；未进行手机触控测试 |

已在锁定源码上验证完整补丁序列：Mesa 18 个补丁、metal2vulkan 30 个补丁均成功应用。

Peach 全栈检查还复现并修复了 MHI 上下文指针丢失 4 字节对齐信息、QMI TLV 整数未对齐访问。共享读写助手新增所有字节偏移的断言。内核构建遇到的私有头文件和加密头文件顺序问题均已修复；每次失败后先清理构建、编译器和临时缓存，再恢复 ABI/签名输入并重建。

本地构建入口为 `/mnt/wsl/unixnu-build/workspace/enter-build`，源码副本位于同卷的 `workspace/run36`。最终命令：

```sh
/mnt/wsl/unixnu-build/workspace/enter-build python3 /mnt/wsl/unixnu-build/workspace/build-guard.py adaptation-final-20261107.log
```

该命令内部执行 `./unixnu kernel -j 6`。完整日志位于 `/mnt/wsl/unixnu-build/artifacts/logs/adaptation-final-20261107.log`，内核位于 `workspace/run36/UniXNU/out/oneplus13t/ipados-17.7.11-21H461/oneplus13t_metal/kernel/kernel.macho`，SHA-256 为 `6a16a4b4140bdd23e067dcd58596dbe1a8326936a33570eca839e15b57c2182e`。最终内核副本及七个仓库的可恢复源码快照已保存到同卷的 `artifacts/adaptation-20261107/kernel.macho` 和 `artifacts/adaptation-20261107/sources.tar.gz`。Run 36 基线另存于同卷的 `artifacts/run36-local-baseline`。

相关回归入口为设备仓的 `scripts/test-stall-stack-patch.py`、`scripts/check-gpu-trace.py`、`scripts/test-wifi-packaging.py --tree <tree>`、`scripts/test-peripherals.py --tree <tree>`，以及组件仓的 `drivers/Adreno830/tests/run-host-tests.py` 和 `drivers/PaganiWifi/Ath12kWifi/tools/test-*.py`、`tools/peach-sim.sh`。测试使用 Clang 和 ASan/UBSan；现有内核模型关闭 LeakSanitizer，主栈退出测试另以分配/释放计数检查生命周期。

构建卷和 VHDX 文件均未达到 80 GB。构建入口监控卷内占用并在超限时终止构建、清理缓存；本轮还单独检查了 `D:\WSL\UniXNU-Build\unixnu-build.vhdx` 的文件大小。本地验证阶段未操作手机。2026-11-07 起继续使用 GitHub Actions 在 macOS 完成 Metal/Turnip、认证服务、签名和 Data/trust 配对构建，再按表中的实机条件验收。

## 2026-11-07 Actions 与测试镜像

[Run 39](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/42276555172) 完成新内核的编译、链接、预链接、A830 集成回归和 XNU 补丁检查，随后在 Metal 前端发现诊断安装函数缺少生产调用。修复后，[Run 40](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/42281947375) 使用新 runner，复用同源的 Run 39 内核及基础 Data，完成 Metal/Turnip、Wi-Fi 认证服务、签名 Data/trust 和 Metal 主机回归。源码为设备提交 `34c5b41` 与 v23 源码包；固件通过已授权的 Actions Secret 恢复，原文件未进入源码包。

测试镜像位于 `out/oneplus13t/boot/metal-main-40/boot.img`，102,129,664 字节，SHA-256 为 `8260ed42c46af4f909693361f012fbbfc008a072f502e5d7de0a7e1480d6485f`。它使用 Run 40 的配套产物与 Run 36 已测 UEFI/stock DTB；内核/Data UUID、Data 哈希、owner 与原始 Apple trust 模块、FAT 文件和 Android v4 封装回读均通过。详情见 [STAGE6.md](STAGE6.md)。

默认继续使用 `sysmem,nocb` 和 4 GiB 内存窗，图标服务启用，诊断追踪默认关闭。Wi-Fi 新栈、认证服务和 Peach 板级固件已集成，`pagani-wifi` 仍沿用阶段式启用方式，缺省为关闭；先完成基本启动验收，再按驱动文档逐阶段测试 Wi-Fi。主机接口回归沿用 `MVK_CONFIG_USE_MTLHEAP=0`，未验证 MoltenVK 原生 placement-heap 的共享纹理写入路径。2026-11-07 经用户授权执行临时启动，fastboot 的 Sending/Booting 均返回 OKAY，未刷写分区。系统启动、GPU 帧时间、Wi-Fi 连接和 S3910 触控行为仍待实机确认。

最终下载后 D 盘构建卷约使用 22 GiB，VHDX 文件为 31,545,360,384 字节，低于 80 GB 清理阈值。

## Run 40 后续：Wi-Fi、USB、灭屏与桌面排查

用户反馈 Run 40 的桌面卡顿、负一屏和小组件黑白、冷启动白屏，以及灭屏后日志仍可见。桌面截图约 14 FPS、GPU 160 MHz / 68°C，应用内约 89 FPS、GPU 342 MHz。当前 profile 1 在达到 70°C 后限到 160 MHz，低于 60°C 才解除；这与桌面状态相符，但无法单独解释冷启动时的 idle。保留现有温控和 SYSMEM 策略，避免把未经实测的温度阈值或全套启动配置作为修复。

- Wi-Fi：找到确定的配置遗漏，原镜像没有 `pagani-wifi`，驱动直接退出。新候选启用阶段 6，并显式提供 `product/wlan` ADT 节点；保留新版认证服务和本机 Peach 固件。
- USB：移植 [QcomDwc3 e4efe95](https://github.com/UniXNU/QcomDwc3/tree/e4efe95) 的设备模式结构，按 PKX110 的 M31 PHY、PMIH010x repeater、GCC、IRQ 和 SID 重新实现接线。针对原始 21H461 验证 AppleUSBXDCI 的 267 个虚表槽、实例尺寸和字段指令后绑定。候选启用 `pagani-usb=1`，复用系统 USBMux；范围为 USB 2.0 设备模式，主机/OTG 和 USB 3 尚未实现。
- 灭屏：黑帧路径原本保留日志区域，后台状态线程继续绘制。现已全屏清黑、停止休眠期间绘制，亮屏后重画；panic 显示保留。实际渲染器的 ASan/UBSan 检查覆盖黑屏、后台更新、恢复和 panic。
- 桌面：对照 [AdrenoMetal 双平面纹理修复](https://github.com/UniXNU/AdrenoMetal/commit/bcbbc707)、[Adreno740 连续分配退避](https://github.com/UniXNU/Adreno740/commit/01ed692a)，以及 DroidVM 的 [GPU 授权](https://github.com/Droid-VM/UniXNU-droidvm/commit/ede54445)和 [LaunchServices 扩展注册](https://github.com/Droid-VM/UniXNU-droidvm/commit/3bacdc96)案例。当前源码已包含纹理和分配修复，Metal 进程规则实际允许请求设备的所有进程；扩展注册问题仍是待日志验证的假设，尚无证据宣布黑白小组件或冷启动白屏已修复。

配置与 USB 时钟、PHY、复位、SMMU 所有权模型检查通过；首次完整链接发现中断函数名称不匹配，已改用现有 `armcpu_spi_enable/disable`。清缓存后的策略输入恢复现已纳入构建入口。完整本地编译、链接和 USB 原版栈预链接通过，日志为 `/mnt/wsl/unixnu-build/artifacts/logs/wifi-usb-sleep-20261107-retry2.log`，内核 SHA-256 为 `a2dd30c00332094200361fab1f58e0962992e7c5ae51e0ee0450a06c5fa2c2d3`。

[Run 41](https://github.com/IssacL04/UniXNU-Pagani_SM8750/actions/runs/42299358397) 使用设备提交 `38ba795` 和 v24 源码包，完成全新内核、49 项 A830 检查、XNU 补丁检查、Metal/Turnip、Wi-Fi 服务、签名 Data/trust 和 Metal 主机回归。新镜像为 `out/oneplus13t/boot/metal-main-41/boot.img`，102,264,832 字节，SHA-256 `b98238f44254083f1b1601af6ce339b2145acf38e17cc1abdae5d7ec7f09301f`。配套 UUID、Data 内容、trust、内核新增入口、FAT 文件、`pagani-wifi=6 pagani-usb=1`、wlan 节点和 Android v4 封装回读均通过。Run 40 镜像保留。随后于 2026-11-07 21:41 经用户授权执行 Run 41 临时启动，Sending/Booting 均返回 OKAY，总计 3.208 秒，未刷写分区；设备已退出 fastboot，首次电脑检查尚未发现 Apple USB 枚举。用户随后确认已进入桌面、灭屏全黑且亮屏后日志恢复；Wi-Fi 控制中心按钮开启后自动熄灭，设置开关无法开启，USB 仍仅显示充电而无电脑枚举。小组件渲染和冷启动动画问题仍在，用户正在保留该版本静置观察 GPU；目前不能将静置等同于持续编译着色器。详细产物与实机记录见 [STAGE6.md](STAGE6.md)。

## 推送前的本地编译检查

仓库已有 Linux XNU 构建路径，可用于 WSL2 上的真实 ARM64 编译、归档和链接预检。现有入口是主仓的 `scripts/linux/setup-toolchain.py`、`scripts/unixnu/kernel.py` 和各组件构建脚本，无需另建一套编译系统。

2026-11-05 本机检查结果：`setup-toolchain.py --check` 在 `llvm-config missing` 处退出；`/opt/unixnu-linux`、`xcrun`、`cmake` 和 `ninja` 尚未就绪。Android 工具链中的 Clang 可以运行，但不支持 XNU 所需的 `__builtin_xnu_type_summary`，不能直接替代专用工具链。该条是当日的环境记录；2026-11-07 的成功构建已替代这一阻塞。

| 层次 | 本地检查内容 | 能提前发现的故障 |
| --- | --- | --- |
| 源码和配置 | 用将要提交给 CI 的同一个源码包恢复隔离目录，解析 Metal profile，核对组件、同级依赖、补丁应用和生成头文件 | 错误 pin、缺失 AdrenoFirmware 等依赖、补丁冲突、源码目录差异 |
| 快速回归 | 复用相关的 Python、C/C++ 及 ASan/UBSan 检查；保留编译器警告要求，将确实依赖 macOS 的测试单列 | 调用参数遗漏、结构体或函数签名变化、边界错误、纯 Python 导入路径问题 |
| 实际组件编译 | 使用本机 XNU bootstrap 生成的编译记录和真实生成头文件，以 ARM64 Mach-O 目标编译受影响组件、归档，并检查架构和重复强符号 | 缺失声明、真实头文件冲突、生产编译参数问题、重复归档对象；不能以 host fixture 通过代替 |
| 完整内核 | 复用 `./unixnu kernel` 的 bootstrap、组件归档、最终链接和预链接流程；重要接口改动提交前跑一次完整检查 | 跨组件缺失符号、重复定义、归档顺序和预链接问题；bootstrap 为取得编译记录而允许的链接失败不算最终成功 |

后续实施时，在主仓目录先准备并检查工具链：

```sh
python3 scripts/linux/setup-toolchain.py --print-packages
sudo python3 scripts/linux/setup-toolchain.py
python3 scripts/linux/setup-toolchain.py --check
```

安装会编译专用 Clang，并写入工具链前缀及 `/usr/bin` 的兼容工具。完成后再使用与 CI 相同的 Metal 配置、源码包、固件和 ABI 输入建立本地基线；普通默认配置不能代表 Run 36。增量检查复用本地编译记录，不能直接重放带有 macOS 绝对路径的云端命令。

Linux 预检能覆盖大量编译和链接错误，但 Apple Clang、SDK、macOS shell 工具和 Objective-C/Metal 运行时仍有差异。正式 Metal 用户态构建、签名、Data 制作及实际 Metal 主机测试继续在 macOS 完成。若有本地或远程 Mac，可在推送前使用与 Actions 相同的 Xcode/SDK 跑这些检查，进一步缩小差异。

本地预检通过后才提交同一套输入进行云端完整验证。Run 36 本地基线和本轮候选均已通过 Linux 目标内核流程，后续继续以该流程作为提交门槛。
