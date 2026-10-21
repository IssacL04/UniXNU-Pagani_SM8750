# 一加 13T UniXNU 移植

本目录是 `PKX110 / OP60F5L1` 一加 13T 的独立设备配置。用户已确认 UniXNU 的 UEFI Shell 成功启动。当前保留菜单基线 `menu-keys/boot.img` 和已实测显示菜单的 `no-sdcc/boot.img`，供后续开发与回退对照；物理侧键交互仍需单独确认。

## XNU 内核适配与 macOS Actions

当前提供源码内核的早期启动配置和 UEFI 负载通路。XNU 已在 macOS Actions 编译并生成 FAT payload。内嵌负载镜像已经实机显示 XNU 启动项，并在 ExitBootServices 后进入 DarwinEnter 跳板；尚无 XNU 自身入口执行的证据。首个目标是进入 XNU 并初始化 ArmDTPlatform、ArmCpu 与架构定时器；没有根文件系统，因此不以启动 iOS 用户态为本轮验收点。

| 部分 | 本轮状态 | 执行位置 |
| --- | --- | --- |
| DarwinBoot 与 13T BootPayloadDxe | 已加入 DSC/FDF，固件编译通过 | 当前 Linux |
| Apple 设备树 | `scripts/make-oneplus13t-adt.py`，主机测试对照实际 `sysinfo/live.dtb` 通过 | Linux 或 macOS |
| XNU 与源码 corecrypto、pthread、ArmDTPlatform、ArmCpu | 第 2 次 Actions 构建通过，已输出 `kernel.macho` | GitHub Actions macOS runner |
| FAT payload 与 Android boot.img | 第 2 次 Actions 已生成 payload；本地已生成 `xnu-source-run-2-embedded/boot.img` 并通过解包比对 | macOS Actions 与当前 Linux |
| kernelcache 预链接、userdata、iOS 用户态 | 未配置，待内核入口验证后接入 | 预链接输入提取与 userdata 工具使用 macOS |

2026-10-21 的[第 1 次构建](https://github.com/IssacL04/UniXNU-oneplus13t/actions/runs/39613407803)在最终链接时缺少 `_native_legacy_display_probe`：上游 `offline-component-load-probes.patch` 的一处调用漏了 `XNU_NATIVE_LEGACY_DISPLAY` 条件，关闭显示驱动的 13T 配置仍引用该符号。提交 `e352179` 补上条件并增加预处理回归测试，覆盖未定义、关闭和开启三种情况。[第 2 次构建](https://github.com/IssacL04/UniXNU-oneplus13t/actions/runs/39614832285)已成功完成内核与 payload 构建，artifact 为 `oneplus13t-xnu-2`。

本地已下载到 `../UniXNU/out/oneplus13t/actions/run-2/`：源码内核为 21,430,552 字节，payload 为 64 MiB，两者均与云端报告中的哈希一致，FAT 卷内的内核也与独立内核逐字节相同。旧候选 `xnu-source-run-2/boot.img` 经用户实测进入 UniXNU 后显示 `no boot entry found`，说明配置卷尚未被发现，不能视为 XNU 已启动。修复逐字节扫描后的 `xnu-source-run-2-payload-fix/boot.img` 经用户实测仍显示相同提示，随后 BDS 报找不到文件系统协议。后续带状态提示的完整镜像显示 `payload FAT scan B6B54000-B7FFF50C: Not Found`：FDT 与输入范围检查通过，但实际 initrd 只有 21,673,228 字节（20.67 MiB），装不下本轮 64 MiB FAT 卷。内核镜像内嵌负载传递现已实测显示启动项，选择后出现 DarwinBoot 绿色交接条。绿色条位于跳转 XNU 之前，证明加载器交接代码执行；旧提示 “kernel entry code ran” 已改正。

### GitHub Actions 负责哪些部分

通用仓库的 [macos.yml](../UniXNU/.github/workflows/macos.yml) 使用 `macos-15`。XNU 和静态库调用 Xcode/iPhoneOS SDK、`xcrun`；从 IPSW 解压 kernelcache 使用 `compression_tool`；userdata、Data 种子扩容与跳过 Setup 使用 `hdiutil`/`diskutil`。普通 FAT 打包不依赖 macOS，只有启用 Data 种子修改时才需要相应工具。当前 Linux 已将 mtools 解压到 `.cache/host-deps/sysroot/usr/bin`，未安装系统软件。UEFI、DarwinBoot、BootShim 和 boot.img 可以在 Linux 继续构建。

### 仓库怎么安排

设备仓库已发布为 [IssacL04/UniXNU-oneplus13t](https://github.com/IssacL04/UniXNU-oneplus13t)，本目录就是仓库根目录。使用本仓库的 [OnePlus 13T XNU 工作流](.github/workflows/xnu.yml)，无需另建 UniXNU fork 或 UEFI 仓库。

该工作流在 `macos-15` 上拉取上游 UniXNU 的固定提交 `b6ae99c17194e6a18fd819d3148e69fe405e91fc`，应用 [源码内核补丁](patches/unixnu-source-kernel.patch)，选中 `oneplus13t_defconfig`，然后执行 `build kernel payload`。补丁包含 `source_only`、ArmDTPlatform/ArmCpu 的静态库构建脚本与相应回归测试。Apple 源码版本沿用该提交的 `feeds.toml` 固定值。更新上游时，应同时检查补丁能否应用。

云端只需本目录的源码和配置。`.gitignore` 已排除 `.cache/`、原始 `sysinfo/` 和镜像；工作流也不读取它们。与真实 `live.dtb` 对照的测试留在本地执行，云端运行不依赖设备资料的两项 ADT 测试。当前无需设置仓库 Secrets，不下载 IPSW，也不构建 userdata。UEFI 和含原机 DTB 的最终 boot.img 继续使用当前 Linux 工作区生成。

选择公开仓库是因为 GitHub 对公开仓库的标准托管 runner 提供免费运行；私有仓库受账户免费额度与超额计费约束。工作流仅手动触发，artifact 保留 7 天。费用规则以 [GitHub Actions 计费说明](https://docs.github.com/en/billing/concepts/product-billing/github-actions) 为准。

### 第一次发布到 GitHub

当前工作区已安装并登录 `gh`，远端仓库也已创建。日常使用直接跳到下一节“触发构建与下载结果”。以下命令保留给从零部署的情况：登录在你自己的浏览器中完成，随后创建公开仓库并上传所列源码；已有仓库无需重复执行。

在 WSL 终端执行一次：

```sh
sudo apt update
sudo apt install gh
gh auth login --hostname github.com --git-protocol https --web --scopes workflow
gh auth setup-git

cd /home/enc3l/Project/UniXNU_SM8750/UniXNU-oneplus13t
git init -b main
git add .github .gitattributes .gitignore README.md board.toml configs scripts patches
git diff --cached --stat
git commit -m "Add OnePlus 13T source-kernel cloud build"
gh repo create UniXNU-oneplus13t --public --source=. --remote=origin --push
```

`gh auth login` 会显示验证码和登录地址；若 WSL 没有自动打开浏览器，在 Windows 浏览器打开提示地址并输入验证码即可。已检查当前 Git 的作者名和邮箱均有配置。若换电脑后提交提示作者身份缺失，按 Git 提示设置自己的 `user.name` 和 `user.email` 后再提交。[登录参数](https://cli.github.com/manual/gh_auth_login)和[建仓库参数](https://cli.github.com/manual/gh_repo_create)可查 GitHub CLI 手册；安装遇到问题时使用其 [Linux 安装说明](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)。

以上是首次建仓流程。如果你已经在网页创建了同名空仓库，将最后一条命令改为：

```sh
git remote add origin https://github.com/你的账号/UniXNU-oneplus13t.git
git push -u origin main
```

网页创建空仓库时不要预填 README、License 或 `.gitignore`，以便直接推送当前提交。[GitHub 建仓说明](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)

### 触发构建与下载结果

打开新仓库，进入 **Actions → OnePlus 13T XNU → Run workflow**，选择 `main`，再点 **Run workflow**。没有需要填写的输入项。若没有运行按钮，先确认 `.github/workflows/xnu.yml` 已在仓库默认分支，且仓库已启用 Actions；GitHub 的手动触发要求工作流存在于默认分支。[手动运行说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

也可以在本设备仓库目录执行：

```sh
gh workflow run xnu.yml --ref main
gh run list --workflow xnu.yml --limit 5
```

任务会依次检查补丁和测试、安装工具并检查 iPhoneOS SDK、拉取源码、构建内核与 FAT 负载。每次使用新 runner 从源码构建，耗时随网络和 runner 状态变化，超时上限为 6 小时。XNU 的第一遍 bootstrap 用于生成编译参数记录，最终以整个构建步骤的结果为准。

构建完成后，打开这次运行，在页面下方 **Artifacts** 下载 `oneplus13t-xnu-运行序号`。需登录 GitHub 才能下载。[下载说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)

成功产物展开后包含：

```text
kernel/kernel.macho
payload/payload.img
payload/payload.json
logs/
unixnu.lock
```

`payload.img` 内已经放入内核、13T Apple 设备树与菜单配置；`unixnu.lock` 记录本次拉取的引用源码提交。构建失败时，工作流仍尝试上传已有日志，artifact 可能只有日志而没有内核或 payload。如果在 checkout、补丁或工具安装阶段失败且尚无日志文件，直接看对应 Actions 步骤的网页日志。不要将出现 artifact 视为编译成功。

`[kernel] source_only = true` 使构建输出源码 XNU 到 `out/oneplus13t/kernel/kernel.macho`，不调用预链接，也不下载 IPSW。该路径仍执行源码 corecrypto 的正常 POST HMAC 填充。已有设备默认继续走原预链接路径。ArmDTPlatform 和 ArmCpu 从实际 XNU 的 `IOPlatformExpert.cpo.json` 继承编译参数，生成构建脚本已经要求的静态库。

### 下载后在本地打包 boot.img

以下命令使用当前工作区已经构建的 13T UEFI 和本机 DTB。将压缩包路径改为实际下载位置；后续运行使用不同的 `run-N` 目录，保留每次候选及其日志。

```sh
cd /home/enc3l/Project/UniXNU_SM8750/UniXNU
export PATH=/home/enc3l/Project/OP_Kernel_Dev/src/kernel_platform/prebuilts/clang/host/linux-x86/clang-r510928/bin:$PATH
unzip /path/to/oneplus13t-xnu-2.zip -d out/oneplus13t/actions/run-2
test -s out/oneplus13t/actions/run-2/kernel/kernel.macho
test -s out/oneplus13t/actions/run-2/payload/payload.img
./unixnu bootimg -D ../UniXNU-oneplus13t --uefi ../uefi-oneplus13t \
  --dtb ../UniXNU-oneplus13t/.cache/firmware/vendor_boot/dtb \
  --ramdisk out/oneplus13t/actions/run-2/payload/payload.img \
  -o out/oneplus13t/boot/xnu-source-run-2-embedded/boot.img
```

前两项文件检查应均成功，再执行打包。新的候选不会覆盖 `menu-keys`、`no-sdcc` 或 `payload-smoke`。将生成的 `boot.img` 复制到 Windows 后，用已验证的 `fastboot boot` 临时启动路径测试；不要直接刷写 boot 分区。

仅得到 `kernel.macho` 时，也可以在本地安装 mtools 后生成负载：

```sh
./unixnu build payload -D ../UniXNU-oneplus13t --kernel /path/to/kernel.macho
```

后续修改本设备配置或补丁，提交并 `git push`，再手动运行同一工作流。通用仓库中的 `macOS build` 仍保留；本设备的首次构建使用这里的 `OnePlus 13T XNU` 即可。

### 13T 的板级输入

首轮仅发布 MPIDR 为 0 的启动 CPU。GICD 为 `0x16000000/0x10000`，GICR 为 `0x16080000/0x200000`，redistributor stride 为 `0x40000`，timebase 为 19.2 MHz；均已对照本机导出的设备树。ADT 包含 ArmDTPlatform 所需的 chosen、cpus、arm-io、defaults、options 和易失 CHRP NVRAM，不填入虚构的 Apple 设备身份或 sheng 的 UFS/GPU 地址。

DarwinBoot 向 UEFI 申请 256 MiB 连续窗口，并通过 `boot_args` 传入实际基址和大小。ADT 不把 13T 分散的物理内存拼成一段连续可用 RAM。framebuffer 地址与 pitch 由运行时 GOP 提供。侧核、PSCI、电源管理、存储和 GPU 需要后续独立适配；19.2 MHz、GIC 路由及 GOP 在退出 boot services 后的行为仍须实测。

当前 `[bootimg] embed_payload = true` 将完整 FAT 卷追加在 UEFI FD 后，与 BootShim 一起压缩到 Android boot 的 kernel 字段。ARM64 镜像头声明包含负载的完整解压长度。BootShim 只把 FD 搬到固件基址，负载留在原 kernel 输入缓冲区；它用 `x1/x2` 传递负载地址和长度，用 `x3` 标记交接格式。SEC 保存参数并生成独立 HOB。BootPayloadDxe 优先使用此 HOB，范围通过检查后发布只读 Block I/O。它仍只接受 SEC 已保留的 `Kernel` 内存，不放宽到 DXE 堆或任意物理内存。

没有内嵌负载 HOB 时，驱动保留原 FDT/initrd 路径：从 `x0` 取得 FDT，读取 `/chosen/linux,initrd-start` 与 `linux,initrd-end`。FDT 额外允许 `XBL_DT` 区，继续拒绝输入溢出、非法区域和 FDT/ramdisk 重叠。

实际交接的 20.67 MiB initrd 与原机 Android 布局相符：保留的 vendor ramdisk 为 18,480,689 字节，`init_boot_b.img` 中 generic ramdisk 为 3,189,565 字节，合计 21,670,254 字节，距观察长度仅差 2,974 字节。这支持 ABL 继续采用原机 ramdisk 的判断；尚未逐字节读取真机 initrd 证明其内容。Android 13 首发设备将通用 ramdisk 移至 `init_boot`，见 [AOSP generic boot 说明](https://source.android.com/docs/core/architecture/partitions/generic-boot)。当前镜像的 Android ramdisk 字段置空，XNU 负载随 kernel 字段传入，测试继续使用 `fastboot boot`。

Android v4 可能在 FAT 前拼接 vendor ramdisk、在尾部追加 bootconfig；[AOSP 要求 vendor 与 generic ramdisk 在内存中直接相连，中间不填充对齐字节](https://source.android.com/docs/core/architecture/partitions/vendor-boot-partitions#bootloader-support)。保留的 13T `vendor_boot_b.img` 中 vendor ramdisk 长度为 18,480,689 字节，除以 512 余 49。此前按 512 字节步进的扫描器会漏掉这种布局，主机测试已复现。

驱动现逐字节寻找卷标 `UNIXNU13T` 的有效 FAT32 范围，找到完整卷后跳过其内部备份 BPB，遇到多个候选仍拒绝。已有范围、BPB 和只读检查保持有效，新增测试覆盖 1、49 与 18,480,689 字节前缀。卷通过只读 Block I/O 发布给现有 DiskIo/FAT 驱动。原有 RamManager 继续管理 RAM，未额外添加内存。

### 当前可测试镜像

使用 `../UniXNU/out/oneplus13t/boot/xnu-source-run-2-embedded/boot.img`。该镜像包含 UEFI、DarwinBoot、云端第 2 次成功构建的真实 XNU 内核及 13T ADT，使用内嵌负载交接，并保留菜单错误显示。固件构建标识为 `oneplus13t-embedded-payload-20261021`。复制到 Windows 并命名为 `boot-13t-xnu-embedded.img` 后：

```bat
adb reboot bootloader
fastboot boot boot-13t-xnu-embedded.img
```

如果已在 bootloader，只执行第二条。使用 `fastboot boot` 临时启动，不刷写分区。成功读取配置时应出现 **OnePlus 13T XNU bring-up** 启动项，配置来源为 `\EFI\UniXNU\unixnu.toml`，默认等待 10 秒后尝试加载内核。建议从执行命令前开始录像，以便保留菜单切换、报错和重启前的最后画面。

失败时，底部红字应显示 `payload <阶段> <起止地址>: <状态>`。`embedded HOB` 表示内嵌交接结构不合法；`embedded base/size` 后两项为负载基址和长度，表示不在当前保护范围；`embedded FAT` 表示内嵌范围内未找到有效卷；若仍是 `FAT scan`，说明未收到内嵌交接 HOB而回退到了原机 initrd。`FDT range` 表示入口 FDT 不在当前保护范围；`FDT header/size` 表示头部或长度不合法；`initrd properties` 表示缺少 initrd 属性；`initrd range` 表示 ramdisk 范围不合法；`FAT scan` 表示输入已通过检查但找不到唯一有效卷；`BlockIO ... Success` 且仍为内置菜单，表示块设备已发布，需继续定位 DiskIo/FAT 或配置读取。请保留完整红字及地址。状态通过仅本次启动有效的 `UniXNUBootStatus` 变量传递，不写入持久变量；识别到输入设备时等待手动选择，没有输入设备时保留五分钟。若仍只有 `no boot entry found`，说明连该状态也未读取到，需要检查驱动调度或变量服务。

用户此前日志中的 `964E5B22-6459-11D2-8E39-00A0C969723B` 是 `EFI_SIMPLE_FILE_SYSTEM_PROTOCOL`。错误由 BDS 后续 USB 启动路径枚举文件系统时产生，不代表 XNU 内核入口失败。

若出现 XNU 启动项前仍使用 `built-in configuration`，启动停在配置卷发现阶段；如果出现 XNU 启动项后才报错或黑屏，则已经进入后续加载阶段。能取得串口日志时，重点记录 `13T payload:` 的 FDT 地址、initrd 范围和错误码，以及 `DARWINBOOT: inputs validated; exiting boot services`、内核版本和平台日志。绿色交接条只说明 DarwinEnter 执行，不能代替 XNU 启动证据。此候选已实测走到绿色交接条，尚未确认 XNU 入口；当前仍没有根文件系统与完整 iOS 用户态。

### XNU 入口、异常与单核定时器诊断

本轮配置开启 `XNU_BOOT_PROGRESS` 与 `XNU_EARLY_BOOT_PROGRESS`，使用本设备的 `drivers/BootProgress` 和 `scripts/build-boot-progress.py`。该实现复用既有内核阶段钩子及 DarwinBoot 字体，不依赖 UFS、根卷或参考设备的 watchdog。完整内核继续链接真实 corecrypto、pthread、ArmDTPlatform、ArmCpu；`cpus=1` 保持不变。

| 屏幕标记 | 所证明的执行位置 |
| --- | --- |
| 绿色条 | UEFI 已退出，DarwinEnter 跳板正在执行 |
| `S1: XNU entry, MMU off` | XNU 自身入口已经执行，已读取 boot_args |
| `S2: bootstrap maps ready` | 初始内核页表及 framebuffer 临时映射已建立 |
| `S3: MMU enabled` | 开启 MMU 后的检查点已执行 |
| `S4: arm_init entered` | 进入 XNU C 初始化 |
| `S5: PE_init_platform ready` | 早期平台和 ADT 初始化已返回 |
| `S6: kernel VM and exception vectors ready` | arm_vm_init 已返回，framebuffer 已由内核重新映射，并恢复正式异常向量 |

在 `arm_vm_init` 更换页表期间暂停普通 framebuffer 写入。早期致命异常使用保留的初始页表切回物理地址、关闭 MMU/cache 后显示 `ESR_EL1`、`ELR_EL1`、`FAR_EL1`、`SPSR_EL1` 和最后检查点，再停住。检查点 `0x50` 表示正在进行 `arm_vm_init`。后续不可恢复的内核数据异常保留原有 panic 流程并追加寄存器输出。该早期异常路径仅用于当前单核配置，启用 SMP 前需要重新设计同步与缓存处理。

加载器将 `/chosen/dram-base`、`dram-size` 的成对零占位符填写为本次实际分配的 XNU 可用内存窗口，避免后续查找缺失字段时 panic。非零的既有 DRAM 字段保持原值。内核以硬件 `CNTFRQ_EL0` 作为架构时钟换算频率，屏幕显示其值。GIC 映射、Distributor、Redistributor、CPU 接口和 PPI 27 的启用分别输出阶段信息。

进入内核线程阶段后，屏幕顶部显示 `poll`、`timer` 与 `DT/CPU/GIC`。数值使用十六进制；`poll` 增长表示内核定时工作线程执行，`timer` 来自真实 PPI 27 中断计数，不由观察器累加。两者持续增长才可作为单核定时器和调度已运行的证据。上述行为尚待新版镜像的真机结果验证。

### 本地验证

```sh
python3 UniXNU/scripts/test-kernel-source.py
python3 UniXNU/drivers/DarwinBoot/Test/test-adt.py
python3 UniXNU-oneplus13t/scripts/test-adt.py
python3 UniXNU-oneplus13t/scripts/check-memory-map.py
python3 UniXNU/scripts/test-bootimg.py
```

BootPayloadDxe 的测试直接编译生产代码，并使用实际 mtools 生成的 FAT32 镜像。覆盖内嵌 HOB 长度和地址、输入保留区、vendor 前缀/bootconfig 尾部、截断、重复卷、无效 BPB、块读取边界、只读写入拒绝和易失状态写入：

```sh
cc -std=c11 -fshort-wchar -ffunction-sections -fdata-sections \
  -I uefi-oneplus13t/Mu_Basecore/MdePkg/Include \
  -I uefi-oneplus13t/Mu_Basecore/MdePkg/Include/X64 \
  -I uefi-oneplus13t/Mu_Basecore/ArmPkg/Include \
  -I uefi-oneplus13t/Silicon/Silicium/SiliciumPkg/Include \
  uefi-oneplus13t/Platforms/OnePlus/oneplus13tPkg/Drivers/BootPayloadDxe/Test/payload_host.c \
  uefi-oneplus13t/Platforms/OnePlus/oneplus13tPkg/Library/MemoryMapLib/MemoryMapLib.c \
  -Wl,--gc-sections -o /tmp/oneplus13t-payload-test
/tmp/oneplus13t-payload-test UniXNU/out/oneplus13t/actions/run-2/payload/payload.img
```

下文保留已验证菜单基线和之前的故障定位过程。`menu-keys`、`no-sdcc` 镜像未被本轮覆盖。

## 菜单阶段保留产物

相对同级 `UniXNU/`：

| 文件 | 用途 |
| --- | --- |
| `out/oneplus13t/boot/menu-keys/boot.img` | 最新镜像，8,409,088 字节；新增 13T SPMI 侧键输入，提前连接输入控制台 |
| `out/oneplus13t/boot/no-sdcc/boot.img` | 已实测显示 UniXNU 菜单；侧键失效，默认倒计时结束后返回 Android |
| `out/oneplus13t/boot/menu-keys/boot.json` | 最新镜像的离线打包报告 |
| `out/oneplus13t/boot/no-sdcc/boot.json` | 已实测菜单基线的离线打包报告 |
| `out/oneplus13t/logs/firmware.log` | 完整 UEFI 构建日志 |
| `out/oneplus13t/boot/integrated/menu-smoke/menu.png` | 上轮 QEMU/AAVMF 竖屏菜单截图；不是手机实拍 |
| `out/oneplus13t/boot/integrated/menu-smoke/qemu.clean.log` | 上轮菜单显示与 Restart 输入检查日志 |

2026-10-21 清理了首轮离线镜像及 `dxe-trace/`、`cpu-vectors/`、`scm-order/`、`integrated/`、`no-ufs/`、`no-storage/`、`menu-bds/` 中的旧诊断镜像和报告，同时移除了旧固件构建备份、独立 package 构建、中间文件、重复测试目录和缓存日志。`integrated/menu-smoke/` 仅保留文档引用的菜单截图及整理后的测试日志。历史故障结论、源码修正、补丁和 `sysinfo/` 原始设备资料继续保留。

固件工作副本为同级 `uefi-oneplus13t/`，FD 位于 `Build/oneplus13tPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd`，大小为 3 MiB；同目录保留 `Guid.xref`，供后续定位模块。当前固件内的 UniXNU 与 DarwinBoot 从本地源码编译，BootPayloadDxe 来自 13T 板级目录。本轮构建已重新生成中间文件。

独立 Python 环境、BaseTools 可执行工具、本地 uuid 开发头文件与链接库入口，以及打包所需的完整 DTB 集合均保留。临时下载的 QEMU/AAVMF 及其运行依赖、下载包、拆分 DTB 和 Android vendor ramdisk 已移除；重新做 QEMU 测试时需准备相应工具。文档站的 `node_modules` 和构建输出也已清理，重建前需按锁文件安装依赖。

`menu-keys` 基线整合了硬件 fence 保留区、CPU_Vectors、SCM 派发顺序和显示路由保留修正，并清理了 APRIORI 中 GLinkDxe、GpiDxe 两个无效引用：参考 DXE 清单已禁用这两个模块，原派发器会跳过它们。这项清理不代表找到了重启根因。

13T 使用独立的 `oneplus13tPkg/Include/DXE.inc`，从打包清单和 APRIORI 同时移除 UFSDxe、SdccDxe、OplusProject、PILDxe、PILProxyDxe、SPSSDxe；参考 13S 文件保持不变。`PcdBootManagerMenuFile` 继续指向内嵌 UniXNU 的 GUID，固件版本输出为 `4.0-oneplus13t-menu-keys-20261021`。UniXNU 自身日志仍为 WARN，保留 `RESET: PSCI ...` 标记。硬件触发或厂商二进制直接发起的复位不一定经过该库。

## 13T 与 13S 的处理

参考 UEFI 提交为 `8b7cc5d155ba147f461dea7121e91104544ab99e`，厂商模块固定为 Device-Binaries `a1501e0c2e642d6ac0d8f52c85af2a67b75a7799`。保留原有 `paganiPkg`，新增 `oneplus13tPkg`、独立 DSC/FDF 和 `Resources/Configs/oneplus13t.toml`。

| 项目 | 13S 参考 | 本目标 |
| --- | --- | --- |
| 产品身份 | 13s / CPH2723 | 13T / PKX110；当前 sysinfo 已确认 |
| 板级身份 | 24875 | 当前 bootconfig 确认为 24821，SKU 7 |
| 内存图 | DXE 堆为连续的 `0xBE360000–0xD8000000` | 独立 MemoryMapLib 将硬件 fence 区隔离为保留内存 |
| 显示配置 | 1216 × 2640 | 当前 AA594 面板和 splash 保留区已匹配；实际扫描基址、pitch 和格式待验证 |
| DTB 输入 | 不直接采用参考仓库的某个单树 | 使用 13T 历史 vendor_boot 中完整的 13 棵候选树 |
| DTBO | 参考 pagani 变体 | 历史 DTBO 含 24875 与 24821 各两份，保留原镜像不改写 |
| 平台入口 | 参考 Pakala 初始化会 detach MDP SMMU streams | 13T 入口保留 bootloader 的显示路由，等待真机核对 |
| 启动程序 | 原平台未集成 UniXNU | FD 内置 UniXNU、UniXNUDxe、DarwinBoot 与 BootPayloadDxe |
| 内部存储 | 打包厂商 UFSDxe | 首阶段暂不打包 UFSDxe，不能访问手机 UFS 分区 |

显示源码 `pagani-24821-display-sun-overlay.dts` 同时声明 `oplus,project-id = <24821 24875>`，支持共享部分显示配置。这不证明面板保活、供电或整套厂商 DXE 已在当前 13T 固件上匹配。

当前 13T 使用独立内存图，其余区域仍以参考平台为基础，配置映射及厂商 DXE 继续复用。真机已显示菜单，但这没有覆盖所有显示模式或动态内存条件；新侧键接口以及其它 XBL/ABL/ARB 组合仍需实测。

DXE 堆按当前 `sysinfo/live.dtb` 的 `/memory` 与 `/reserved-memory/hwfence-shmem` 拆分，以下区间均为左闭右开：

| 区间 | UEFI 用途 |
| --- | --- |
| `[0xBE360000, 0xD4E23000)` | `DXE_Heap`，可分配内存 |
| `[0xD4E23000, 0xD5100000)` | `HW_Fence`，显式保留内存分配 HOB |
| `[0xD5100000, 0xD8000000)` | `DXE_Heap_Upper`，可分配内存 |

中间的 `0x002DD000` 字节不再交给 DXE 分配器。显式保留描述符也使 RamManagerDxe 后续补充 RAM 时保留该区间。DSC 引用 `oneplus13tPkg/Library/MemoryMapLib/MemoryMapLib.inf`，没有修改原 `paganiPkg`。

## 输入来源与设备状态

用户提供的当前系统为 `16.0.10.500`，内核为 `6.6.118`，并已确认 Bootloader 解锁和 root 可用。目前手机连接 Windows CMD 下的 ADB；本构建环境未直接连接手机。

初始镜像输入来自 `/home/enc3l/Project/OP_Kernel_Dev/device/` 的历史记录与 `current/vendor_boot_b.img`、`dtbo_b.img`。后续由用户导出的 `sysinfo/` 确认了本次启动槽位 `_b`、`dtb_idx=2`、`dtbo_idx=2`，bootconfig 为 orange/unlocked；identity 属性却为 green，原因尚未查明。当前内核带 `enc3l-4k` 自编译标识。这些信息只描述导出时的状态。

历史 vendor_boot 为 v4，DTB 区共 6,821,771 字节，包含 13 棵树。打包继续保留完整集合，没有将带有运行时地址的 `live.dtb` 直接用于启动镜像，也没有强制合并 DTBO。当前导出树的 model、compatible、msm-id 与 board-id 均与历史 DTBO 2 根节点一致；这不证明 ABL 会使用候选镜像追加的 DTB，实际交接仍待验证。

## 构建

在当前工作区可以复用 Android LLVM 18 与本项目的独立 Python 环境：

```sh
export CLANG_BIN=/home/enc3l/Project/OP_Kernel_Dev/src/kernel_platform/prebuilts/clang/host/linux-x86/clang-r510928/bin/
export PATH=/home/enc3l/Project/UniXNU_SM8750/.venv-uefi/bin:/home/enc3l/Project/UniXNU_SM8750/UniXNU-oneplus13t/.cache/host-deps/sysroot/usr/bin:$CLANG_BIN:$PATH
export CPATH=/home/enc3l/Project/UniXNU_SM8750/UniXNU-oneplus13t/.cache/host-deps/sysroot/usr/include
export LIBRARY_PATH=/home/enc3l/Project/UniXNU_SM8750/UniXNU-oneplus13t/.cache/host-libs
cd /home/enc3l/Project/UniXNU_SM8750/UniXNU

./unixnu build firmware -D ../UniXNU-oneplus13t \
  --uefi ../uefi-oneplus13t --edk2 ../uefi-oneplus13t/Mu_Basecore \
  --local-module refer:edk2=../uefi-oneplus13t/Mu_Basecore -j 4

./unixnu bootimg -D ../UniXNU-oneplus13t --uefi ../uefi-oneplus13t \
  --dtb ../UniXNU-oneplus13t/.cache/firmware/vendor_boot/dtb --ramdisk none \
  -o out/oneplus13t/boot/xnu-loader/boot.img
```

必需的 Mu 子模块与 BaseTools 已在工作副本中准备。BaseTools 首次编译需要 uuid 开发头文件，本轮从发行版包解压到 `.cache/host-deps/sysroot/`，没有安装系统软件。重新从干净环境构建时需要准备等效依赖；编译 BaseTools 时可设置本地 `CPATH` 和 `LIBRARY_PATH`。

当前板级配置包含源码 XNU 和 payload，尚未配置 IPSW、Data 或 userdata。Linux 运行 `firmware`、`package`、`payload`、`bootimg`；内核使用上文的 macOS workflow。不要运行完整 `build all`。

## 已通过的离线检查

在工作区根目录运行 `python3 UniXNU-oneplus13t/scripts/check-memory-map.py`，使用系统 `fdtget` 对照用户导出的设备树：14 个 UEFI RAM 分配区均在声明的 RAM 中，且不与静态保留区重叠；硬件 fence 区有显式保留分配 HOB。检查还约束 CPU_Vectors 的精确名称、地址、页大小、属性及与其它区域的边界，缺项、错误地址或跨入 Info_Blk 都会被拒绝。旧 pagani 内存图会因 DXE 堆跨越非 RAM 区间而失败。该检查不推断 Android 动态分配或 bootloader 的瞬时内存用途。

重建后已检查链接的 SEC 模块与最终 FD，三段描述符均存在，`HW_Fence` 的内存类型为 `EfiReservedMemoryType`。新 v4 镜像解出的 FD 与本次构建一致，追加的历史 DTB 集合保持原样。

`no-storage` 版 UEFI 编译及 v4 打包通过。逐层解开该镜像和上一版 `no-ufs`，确认固件卷仅移除 OplusProject、PILDxe、PILProxyDxe、SPSSDxe 四个模块：非填充 FFS 文件从 102 个减为 98 个，APRIORI 从 82 项减为 78 项，其余相对顺序不变，全部启动项均有对应文件。SCM 提供者仍在 Mailbox 前。UniXNU 应用和注册驱动与上一版逐字节一致，RAM 变量模式仍启用。解出的 FD 与本轮构建逐字节一致，BootShim、DTB 与上一版一致，SEC 中含本轮版本号。压缩固件卷占 3 MiB 窗口的 52%。

v4 打包往返验证确认：192 字节 BootShim、完整 3 MiB FD、13 棵未改写 DTB 和空 ramdisk。通用打包器的 7 组测试通过，并额外使用实际 `mkbootimg.py` 验证 v0/v3/v4。签名区域检查只确认结构长度，不代表 AVB 或设备启动策略验证通过。

上轮独立 `UniXNU.efi` 在 QEMU virt + Ubuntu AAVMF 下，以 1216 × 2640 显示了三个内置菜单项。模拟键盘下移并确认后，日志记录 `UNIXNU: action: reset`，检查通过且未出现 ASSERT 或同步异常。[菜单截图](../UniXNU/out/oneplus13t/boot/integrated/menu-smoke/menu.png)来自模拟器。本轮菜单程序未变，没有重复该项测试。独立应用使用通用 UEFI 库；此检查没有运行手机固件中的平台库、13T BootShim 或厂商 DXE。

`menu-bds` 版已通过编译和 v4 打包核对。解包确认主固件卷仍有 98 个非填充 FFS 文件，78 项 APRIORI 与 `no-storage` 完全一致，五个已隔离模块仍未打包。BdsDxe 中的菜单 GUID 已变为 UniXNU，全部新增 BDS 阶段标记均存在。UniXNU 应用逐字节未变，注册驱动与当前构建一致；镜像中的 FD 与本次输出一致，BootShim 和 DTB 未变。此检查尚不能证明真机的事件处理和应用加载成功。

`no-sdcc` 版已通过编译、v4 打包和解包核对。与 `menu-bds` 相比，主固件卷只少 SdccDxe，非填充 FFS 从 98 个减为 97 个，APRIORI 从 78 项减为 77 项，其余相对顺序不变。最终固件中只有 BdsDxe 保留 SD 初始化事件 GUID；BdsDxe、UniXNU 应用及注册驱动与上一版逐字节一致。菜单 GUID、此前五项隔离、BootShim 和完整 DTB 集合均保留，FD 与本次构建一致，版本标识已更新。

## 当前候选的真机测试

将 `out/oneplus13t/boot/menu-keys/boot.img` 复制到 Windows 当前工作目录，并命名为 `boot-13t-menu-keys.img`，在 CMD 中执行：

```bat
adb reboot bootloader
fastboot boot boot-13t-menu-keys.img
```

本轮只临时启动，版本标识为 `menu-keys-20261021`。菜单出现后先松开所有侧键，再在 10 秒内短按音量减：预期选择向下移动且倒计时停止；短按音量加应向上移动。选中 Restart 后短按电源确认，检查是否执行重启。每次按下只上报一次，暂不设置长按连发或组合键。

若仍无输入，请拍下启动日志中所有 `13T keys:` 行，尤其是 PMIC 类型、GPIO6 模式、SPMI 读取状态和 `keypad install` 结果，以及 `SetupKeypad` / `Connect ConIn` 是否仍报错。初始化只读取 PMIC 寄存器，沿用 bootloader 的 GPIO 输入配置；遇到不匹配的布局或禁用的 GPIO 会明确返回错误。没有按键操作时，10 秒后执行 Return to firmware 仍属预期行为。本次没有刷写、解锁或修改手机分区。

## DXE 早期重启定位

用户报告的最后几行为 `SEC: loading DXE core`、DXE Core 基址 `0xD3B81000`、HOB 地址 `0xD39B8018`，随后约 5–15 秒重启回 Android。两个地址都位于低段 DXE 堆。对照当前 DxeMain，HOB 地址打印点之前已完成内存服务、GCD、库构造及配置表安装；仍不能从该行确定实际停点或复位原因。

此次回到 Android 后，用户读取的 `ro.boot.bootreason` 与 `sys.boot.reason` 都是 `bootloader`。这两项没有给出更具体的复位原因，不能据此确认 watchdog 或主动重启。

当前 Mu_Basecore 工作副本增加了阶段日志，覆盖两次 HOB 遍历、事件服务、晚期 debug agent、内存属性和保护、FV 服务、section extraction 及 dispatcher；每次驱动加载、入口调用和返回也记录 GUID。13T DSC 将 framebuffer 的每行延迟从 10 ms 调为 0，并只保留 WARN/ERROR，减少日志开销。这轮没有修改内存保护设置或 watchdog 行为，重启原因仍待验证。

Mu 变更保存在 `patches/mu-basecore-dxe-trace.patch`，Qcom BDS 日志变更保存在 `patches/uefi-bds-trace.patch`，键盘框架优先级修正在 `patches/uefi-keypad-tpl.patch`。当前工作副本已应用；从相同上游版本的干净工作副本重建时，在工作区根目录先执行一次：

```sh
git -C uefi-oneplus13t/Mu_Basecore apply "$PWD/UniXNU-oneplus13t/patches/mu-basecore-dxe-trace.patch"
git -C uefi-oneplus13t apply "$PWD/UniXNU-oneplus13t/patches/uefi-bds-trace.patch"
git -C uefi-oneplus13t apply "$PWD/UniXNU-oneplus13t/patches/uefi-keypad-tpl.patch"
```

这些定位日志已保留在当前 `menu-keys/boot.img` 中。构建目录 `FV/Guid.xref` 可将最后一个驱动 GUID 对应到具体模块。

## CPU_Vectors 缺项修复

诊断镜像的后续反馈为 `ERROR: CPU_Vectors region not present in cfg file !`，随后仍自动重启。该字符串位于固定的 `Binaries/pagani/QcomPkg/Drivers/EnvDxe/EnvDxeEnhanced.efi` 中。反汇编显示，它按精确名称 `CPU_Vectors` 查询内存描述符，成功后要求基址为 `0xA7600000`，再按描述符长度设置只读属性。查询失败时打印错误并返回；因此这个遗漏已确认，但还不能把它认定为自动重启的唯一原因。

13T 独立内存图已在 `[0xA7600000, 0xA7601000)` 补入 `CPU_Vectors`，使用 `AddMem / SYS_MEM / BsData / WRITE_BACK`。这一页原本位于 UEFI_FD_Reserved 与 Info_Blk 之间，没有借用其它区域；真机导出设备树也将其声明为 RAM。4 KiB 长度与仓库现有平台的向量区布局一致，且使 EnvDxe 的只读范围止于 Info_Blk 之前。原 pagani 配置保持不变。

CPU_Vectors 修正及 DXE 定位日志已并入当前统一候选；重启问题仍以真机反馈为准。

## Mailbox 的 SCM 依赖顺序修复

CPU_Vectors 候选的下一次反馈停在 `DXE: start driver E3095547-34B8-4BD4-8D8F-C3223C30318D`，随后打印缺少协议并重启。该 GUID 对应 MailboxDxe。用户转录为 SDM；当前二进制的完整字符串实际是 `mbox_os_init: Failed to locate SCM protocol for Mailbox %d`。

反汇编显示该消息的 `%d` 参数直接取自 LocateProtocol 的返回状态，因此 14 表示 EFI_NOT_FOUND，不是邮箱编号。Mailbox 查询的 GUID 为 `77ED108D-8524-4B8B-9D2E-34987AECB9C1`，ScmDxeCompat 安装的 SCM 协议也使用同一 GUID。

参考 pagani 的 APRIORI 把 MailboxDxe 放在 ShmBridgeDxeLA 和 ScmDxeCompat 之前。13T 使用独立的 `oneplus13tPkg/Include/APRIORI.inc`，将现有两项移到 Mailbox 前，顺序为 `ShmBridgeDxeLA → ScmDxeCompat → MailboxDxe`。原 pagani 文件未改。这修正了已确认的依赖顺序，但提供者是否在真机成功初始化仍需观察。

本轮固件构建与 v4 镜像打包已通过，并从编译后的 FVMAIN.Fv 中确认三项按上述顺序连续排列。镜像中的 FD 与本轮构建产物一致，附加 DTB 与原始输入一致。该轮旧候选已在后续清理中移除。

用户随后反馈，明显报错消失，但仍会重启且没有菜单。`sysinfo/DxE_issue_2/` 中的原厂 bootloader 日志也出现同一条 SCM 14 消息，之后成功交接 Android，因此该消息本身不能作为重启根因。

最新导出记录给出 HARD_RESET / PS_HOLD，但未指出复位调用者。补充的 console-ramoops 含损坏内容和可辨识的 Android 关机记录，没有恢复出 UniXNU 的完整 DXE 日志。统一候选实测仍重启，重建未解决该故障；后续用户提供了下面的 UFS 停点。

## UFSDxe 初始化隔离

用户反馈从出现文字到黑屏重启约 7 秒，最后一行为 `start driver 0D35CD8E-97EA-4F9A-96AF-0F0D89F76567`。构建的 `Guid.xref` 与厂商 INF 都将其映射为 UFSDxe，实际输入为 `UFSDxe.patched.efi`。没有对应的返回日志，说明最后观察到的执行位置在这个驱动入口之后；尚不能区分驱动卡住、异常或外部复位。

该驱动的 INF 声明无条件 DEPEX。仅从 APRIORI 移除无法保证它不再执行，因此本轮同时移除 FDF 中的打包项。UniXNUDxe 直接注册固件卷中的应用，变量使用 `PcdEmuVariableNvModeEnable=TRUE` 的 RAM 模式；没有外部配置时，UniXNU 使用内置三个 action 项。这条菜单启动路径无需 UFS。

`no-ufs` 版只移除了 UFSDxe，随后真机不再自动复位，却暴露了下一节的存储依赖错误。该结果不能单独解释此前复位的底层机制。后续加载手机存储上的配置或 XNU 时，仍须单独完成 13T 的 UFS 适配。

## OplusProject 空指针与存储依赖

`no-ufs` 真机照片显示，最后启动的 `68A710AB-A58D-4C0B-BE1E-5F6EE2C36AD8` 是 OplusProject。它先报告 `ReadWritePartition failed: efi no media`、`ocdt read error`，随后出现 `[Get_Current_Slot] Error locating MemCardInfoProtocol:2`。异常 PC 为 `0xD2E75034`，模块基址为 `0xD2E73000`，故障偏移为 `+0x2034`；`X0=0`、`FAR=0x10`、`ESR=0x96000007` 对应本级数据访问异常。

仓库中的原始 OplusProject 二进制在 `+0x200C` 调用 `HandleProtocol`，错误分支只打印日志，仍走到 `+0x2034` 的 `ldr x8, [x0, #0x10]`。该地址是 `EFI_MEM_CARDINFO_PROTOCOL.GetBootLU` 方法槽；查询失败后输出指针为空，继续取方法指针便触发异常。异常处理器随后 ASSERT 并停机，所以画面中的 `[ArmCpuDxe]` 是处理异常的位置。此证据已定位到厂商模块的错误处理缺陷，无需修改空页映射或关闭内存保护。

本阶段从 FDF 打包清单及 APRIORI 同时移除 OplusProject。仅调整 APRIORI 顺序无效：它随包携带的二进制 DEPEX 只依赖 `ae37b942-457f-4c91-a196-d9669fd347a3`，没有约束存储协议和 `ocdt` 分区。没有修改厂商 EFI，也没有伪造项目识别协议。

同时停用 PILDxe、PILProxyDxe、SPSSDxe 这一组外设固件加载模块。PILDxe 入口会按配置加载固件，二进制包含分区读取和加载失败后的复位路径；SPSSDxe 使用 PIL 协议加载 SPU 固件。这是关闭 UFS 后对阶段范围的配套调整，尚无真机证据证明这三项已经触发过故障。

检查了 OplusProject 协议 GUID `903c579d-ebde-19e0-39a7-43b95fa73f91` 的引用。保留的 PMIC、Buttons、QcomCharger 二进制在所检查的查询点有失败分支：Buttons 在 `+0x3A08/+0x3A10` 检查状态及空指针，并在安装输入协议前返回；QcomCharger 的相关初始化在 `+0x54E0` 至 `+0x5570` 有错误返回。这允许保留基础驱动并停止依赖项目资料的功能，但不构成对整个厂商二进制的运行时验证。此候选不承诺侧键和 UEFI 充电功能；验收先看内嵌菜单能否出现。


## Silicium logo 后的输入错误与 BDS 菜单识别

用户实测 `no-storage` 已进入 Silicium logo 页面，出现 `SetupKeypad: Failed to Locate STI Device Path! Status = Not Found`，约 4–5 秒后回到 Android，期间未看到 UniXNU 菜单、`UNIXNU:` 或 `RESET: PSCI` 日志。该提示来自 `SiliciumPkg/Library/BootManagerLib/KeyCallback.c`：STI 此处指 `EFI_SIMPLE_TEXT_INPUT_EX_PROTOCOL`。`SetupKeypad` 和 `RegisterKeyCallback` 遇错直接返回；`PlatformBootManagerAfterConsole` 仍继续执行 `DeviceBootManagerAfterConsole`。按键缺失符合停用 OplusProject 后的已知限制，该报错分支本身没有复位调用。

后续有两条需区分的路径。Qcom 的 `DeviceBootManagerAfterConsole` 会发送 SD 初始化事件，SdccDxe 消费此事件；BDS 随后按 3 秒超时选择启动项。原配置的 `PcdBootManagerMenuFile` 仍指向 `EEC25BDC-67F2-4D95-B1D5-F81B2039D11D`，不是 UniXNU 的 `9B665204-A133-47A2-9396-9E2B370A4E25`。`UefiBootManagerLib/BmBoot.c` 按文件 GUID 识别菜单，原配置使 UniXNU 在进入应用前经过 `PreReadyToBoot`、`ReadyToBoot` 和控制器健康修复流程。保留的 PMIC、EnvDxe 二进制注册了 ReadyToBoot 回调。

本轮只调整 13T DSC 中的菜单 GUID，让已有 BDS 菜单分支跳过上述 OS 启动通知；继续保留 UniXNUDxe 注册的 BootOrder 和标准 LoadImage/StartImage 路径。SD 初始化、侧键驱动、厂商二进制及内存保护没有新增行为改动。菜单 GUID 不匹配已经确认，但尚无真机证据将 4–5 秒复位归因于某个具体回调。

增加 WARN 日志以覆盖此前不可见的阶段。正常进入应用时应依次经过：

```text
UniXNUDxe: Boot.... first in BootOrder: Success
BDS: after-console begin
BDS: SD init signal begin
BDS: SD init signal end
BDS: after-console end
BDS: wait begin
BDS: wait end
BDS: Boot.... UniXNU begin
BDS: firmware menu; ReadyToBoot skipped
BDS: image buffer ...
BDS: LoadImage begin
BDS: LoadImage result Success
BDS: StartImage begin
UNIXNU: UniXNU ... starting ...
```

若停在 SD 的 `begin` 而没有 `end`，下一步检查 SdccDxe 的事件处理；若 LoadImage 返回错误，按其状态排查镜像路径或加载策略；若已经出现 `StartImage begin` 或 `UNIXNU:`，则继续定位应用入口、控制器连接及界面初始化。若日志进入了 Internal Storage/USB Storage 启动项，要连同此前的 UniXNU 返回状态一起记录。不要仅凭 STI 提示再次删驱动。

Mu 的 BDS 日志已并入 `patches/mu-basecore-dxe-trace.patch`；Qcom SD 事件前后的日志保存在 `patches/uefi-bds-trace.patch`。两份补丁用于从相同上游提交恢复工作副本，当前目录已应用。


## SD 初始化事件期间复位

`menu-bds` 的真机反馈在 STI 输入错误下方出现 `BDS: SD init signal begin`，随后复位，没有 `BDS: SD init signal end`。这将最后观察到的执行区间限定在 Qcom `DeviceBootManagerAfterConsole` 的 `gBS->SignalEvent (InitEvent)` 调用期间，还没有走到 BDS 的启动等待或 UniXNU 加载阶段。因此上一轮菜单 GUID 修正是否改善后续启动，尚未得到真机验证。

该事件组为 `gSdCardInitGuid`（`B7972C36-8A4C-4A56-8B02-1159B52D4BFB`）。检查上一版实际 FVMAIN 中的引用，只有 BdsDxe 和 SdccDxe 包含此 GUID：前者创建并发送事件，自带的 DummyNotify 为空函数；后者是 SD 控制器驱动。其 FFS GUID 为 `F10F76DB-42C1-533F-34A8-69BE24653110`。SdccDxe 先前入口返回 Success，只说明完成注册，不代表后续事件回调已通过。

本轮从 13T 的 DXE 打包清单和 APRIORI 同时移除 SdccDxe。这样既隔离了这次停点涉及的 SD 硬件初始化，也避免 UniXNU 后续 `UniXNUConnectAll` 再次连接该驱动。内嵌菜单和 RAM 变量不需要 SD 介质。已有 UFSDxe、OplusProject、PIL/PILProxy/SPSS 隔离继续保留，13S 的 `paganiPkg` 不变。

Qcom 公共库的事件发送和 begin/end 日志保持原样；去掉 SdccDxe 后该事件不再调用其处理函数。因此本版预期仍显示 `BDS: SD init signal begin`，随后能看到 `BDS: SD init signal end`、`BDS: after-console end`，再进入菜单加载路径。STI 提示仍可能出现，它不是本轮修改对象。

若仍在同一个 begin 后复位，需要进一步追踪事件调度及同时待处理的回调，不能仅凭旧日志断言 SdccDxe 内部的某条指令触发复位。本轮尚未查明闭源驱动内部的具体失败操作，也没有恢复 SD/UFS 支持。


## 菜单已显示后的侧键适配

用户确认 `no-sdcc` 显示 UniXNU 菜单且倒计时持续减少，随后返回 Android。因此本次输入问题有明确的工作基线。`no boot entry found` 表示没有系统启动项，`drivers 0 loaded` 统计 UniXNU 注入的驱动；两者符合本阶段配置。`input yes` 只说明发现输入协议句柄，不能证明三个物理侧键已经注册成功。

闭源 ButtonsDxe 在 `+0x3A00` 查询 OplusProject 协议，失败后沿 `+0x3A08` 返回，早于 `+0x20D8` 的输入接口安装。当前不恢复依赖 UFS 的 OplusProject，而以 `oneplus13tPkg/Drivers/KeypadDeviceDxe` 替换 ButtonsDxe，并复用 Silicium 的 `KeypadDxe` 提供 SimpleTextIn / SimpleTextInputEx。两项均加入 DSC、DXE 和 APRIORI，顺序位于 SPMIDxe 之后；使用与 BDS ConIn 相同的 KeypadDevicePath。

映射来自本机 `sysinfo/live.dtb`，寄存器语义对照本地内核 `pm8941-pwrkey.c` 与 `pinctrl-spmi-gpio.c`：

| 侧键 | 13T 接线与读地址 | 输入键值 |
| --- | --- | --- |
| 音量加 | SPMI bus 0 / SID 0，PMK8550 PON_HLOS `0x1310` bit 6（RESIN） | SCAN_UP |
| 音量减 | SPMI bus 0 / SID 1，PM8550 GPIO6 `0x8D10` bit 0，低有效 | SCAN_DOWN |
| 电源 | SPMI bus 0 / SID 0，PON_HLOS `0x1310` bit 7（KPDPWR） | Enter |

这与仓库中 sheng 的音量键接线方向不同，不能直接复用它的映射。新驱动读取 PON subtype、GPIO type/subtype、模式和使能位，再安装设备协议；不向 PMIC 写配置寄存器。输入去抖阈值为 32 ms，20 ms 轮询下通常约 40 ms 确认。启动或读失败后重新建立基线，按住电源不会被误当成一次新的确认。

SPMI GUID 为 `FA5F306B-F47D-4AC4-A47D-882F8204EC30`。使用的是固定厂商二进制中 revision `0x10003` 的已核对接口前缀，包含 Revision 与 ReadLong；后者返回 32 位 SPMI 结果枚举，非零即失败，还必须验证 BytesRead 为 1。协议表位于 SPMIDxe RVA `0x7098`，ReadLong 位于 `0x141C`；PmicDxeLa 的 `0x249E0` 包装函数使用相同参数次序。升级厂商二进制时须重新核对 ABI。

SPMI ReadLong 内部将任务优先级提升到 TPL_CALLBACK。原键盘框架在 TPL_NOTIFY 调用硬件读取会违反 RaiseTPL 约束。修正后仅由现有 TPL_CALLBACK 定时器采样；WaitForKey 和 ReadKeyStroke 只访问队列，队列更新仍受 TPL_NOTIFY 保护。13T 另设 `PcdConInConnectOnDemand=FALSE`，在显示菜单前连接侧键，避免首次读键才发送 USB 初始化事件。USB 键盘不属于本轮验收范围。

`menu-keys` 已通过固件编译、v4 打包和实际镜像解包核对：相对 `no-sdcc` 只移除 ButtonsDxe，增加 13T KeypadDeviceDxe 与通用 KeypadDxe，非填充 FFS 为 98 个，APRIORI 为 78 项；其余模块的相对派发顺序不变。已确认新驱动与本次编译输出一致，ConIn 按需连接关闭，原菜单 GUID 保留。UniXNU 应用、注册驱动、BootShim 和 DTB 集合逐字节未变。新侧键行为尚未经真机验证。

主机测试直接编译实际设备驱动、通用定时器和输入队列代码，模拟 SPMI；覆盖按键映射、去抖、长按不重复、启动时按住电源、读取错误与短读取、GPIO 配置不匹配、控制台通知和 TPL 约束。旧框架在同一测试中触发非法 RaiseTPL 断言，修正版本通过。在工作区根目录复现：

```sh
cc -std=c11 -fshort-wchar -ffunction-sections -fdata-sections \
  -D_PCD_GET_MODE_32_PcdMaximumLinkedListLength=0 \
  -D_PCD_GET_MODE_BOOL_PcdVerifyNodeInList=1 \
  -I uefi-oneplus13t/Mu_Basecore/MdePkg/Include \
  -I uefi-oneplus13t/Mu_Basecore/MdePkg/Include/X64 \
  -I uefi-oneplus13t/Silicon/Silicium/SiliciumPkg/Include \
  -I uefi-oneplus13t/Silicon/Silicium/SiliciumPkg/Drivers/KeypadDxe \
  uefi-oneplus13t/Platforms/OnePlus/oneplus13tPkg/Drivers/KeypadDeviceDxe/Test/keys_host.c \
  uefi-oneplus13t/Mu_Basecore/MdePkg/Library/BaseDebugLibNull/DebugLib.c \
  uefi-oneplus13t/Mu_Basecore/MdePkg/Library/BaseLib/LinkedList.c \
  -Wl,--gc-sections -o /tmp/oneplus13t-keys-test
/tmp/oneplus13t-keys-test
```
