# OnePlus 13T 上游适配计划

本轮在 main 上适配 Metal、SMMU、Turnip、诊断、Wi-Fi、图标服务和触控优化，保持 SM8750 / Adreno830 / iPadOS 17.7.11（21H461）目标。当前只完成留档与计划，以下实现和验证均待执行。

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

## 推送前的本地编译检查

仓库已有 Linux XNU 构建路径，可用于 WSL2 上的真实 ARM64 编译、归档和链接预检。现有入口是主仓的 `scripts/linux/setup-toolchain.py`、`scripts/unixnu/kernel.py` 和各组件构建脚本，无需另建一套编译系统。

2026-11-05 本机检查结果：`setup-toolchain.py --check` 在 `llvm-config missing` 处退出；`/opt/unixnu-linux`、`xcrun`、`cmake` 和 `ninja` 尚未就绪。Android 工具链中的 Clang 可以运行，但不支持 XNU 所需的 `__builtin_xnu_type_summary`，不能直接替代专用工具链。本轮未安装依赖或启动内核编译。

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

本地预检通过后才提交同一套输入进行云端完整验证。首次需要先证明 Run 36 能在 Linux 工具链完成目标内核流程，再把它作为后续适配的提交门槛。
