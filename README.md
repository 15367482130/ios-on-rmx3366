# kona-ios — 在 realme RMX3366（骁龙 870 / kona）上跑 iOS 16.5 用户态

把 **iOS 16.5 的 Darwin 用户态（XNU 8796.121.2 / Darwin 22.5.0）** 移植到一台
**Android 手机（realme 大师探索版 RMX3366，Snapdragon 870 / kona / SM8250-AC）** 上的
完整工程记录：引导链、内核驱动、userland、系统镜像构建、纯 Windows 刷机工具，
以及一路上每一个 bug 的根因、修法和踩过的坑。

- 设备：**realme 大师探索版 RMX3366**（不是 OnePlus 8；参照项目跑在 OnePlus 8 上，硬件地址需按 RMX3366 核对）
- 平台：Qualcomm kona / SM8250-AC / Adreno 650 / UFS 3.1 / 90 Hz AMOLED
- 目标系统：**iOS 16.5**（20F66 rootfs，Darwin 22.5.0）
- 宿主：Linux（WSL2）编译 + **纯 Windows 刷机**（不需要 WSL 的 USB 转发）

> 这个仓库 **不包含任何 Apple 二进制**。系统镜像需要你自己从合法来源获取 iOS 16.5
> 的 rootfs 并用 `tools/` 里的脚本处理。仓库里只有我们写的代码、补丁、脚本和文档。

---

## 目录

1. [现在能做什么（实测）](#现在能做什么实测)
2. [现在不能做什么](#现在不能做什么)
3. [它是怎么跑起来的](#它是怎么跑起来的)
4. [快速开始：刷入体验版](#快速开始刷入体验版)
5. [仓库结构](#仓库结构)
6. [文档索引](#文档索引)
7. [六条铁律（血泪教训，先读再看代码）](#六条铁律血泪教训先读再看代码)
8. [性能现状](#性能现状)
9. [法务与品牌声明](#法务与品牌声明)
10. [致谢](#致谢)

---

## 现在能做什么（实测）

> 详细证据、日期、验证方法见 [`docs/FEATURES.md`](docs/FEATURES.md)。
> 每一条都是**在这台真机上跑通并被人眼确认过**的，不是"代码写了"。

| # | 功能 | 状态 | 一句话说明 |
|---|------|------|-----------|
| 1 | 引导到 iOS 桌面 | ✅ | 从 ABL fastboot 进 loader，约 60–120 s 到 SpringBoard |
| 2 | 触摸 | ✅ | S6SY792 真机协议，多点可用 |
| 3 | 显示 / 90 Hz | ✅ | AMOLED 点亮、90 Hz 刷新、`ca_fps=90` |
| 4 | 中文界面 | ✅ | 补回所有 `zh_CN/zh_HK/zh_TW.lproj` + 完整 PingFang（36 字面） |
| 5 | UFS 存储 | ✅ | 系统卷从 USB 收进内存后按 APFS 挂载，UFS 读路径可用 |
| 6 | Wi-Fi | ✅ | 原生 BDF + 电源轨修正，能开能连 |
| 7 | 蓝牙 | ✅ | 与 Wi-Fi、基带**三方共存**且不发热（共享轨必须一起给电） |
| 8 | 声音 | ✅ | ADSP + 扬声器功放（TFA9874 / AW882xx 路径） |
| 9 | 物理按键 | ✅ | 音量上/下、电源（由 loader 代读，内核不碰 PMIC） |
| 10 | 手电筒 | ✅ | `torch=3` |
| 11 | 基带：**数据上网** | ✅ | 换卡实测可上网（`cell=1` + `cell_dcm=1` + 打包固件） |
| 12 | 基带：**语音通话** | ✅ | 换卡实测可通话 |
| 13 | 安装第三方 App | ✅ | 自研 `hkinstall`：拉 ustar → 注册 LaunchServices → 桌面出图标、可启动 |
| 14 | 内核日志通道 | ✅ | `oem log` 一次取回完整环形缓冲（USB 端点问题见文档） |
| 15 | 纯 Windows 刷机 | ✅ | `fb_libusb.py`：libusb 直连，绕过 `fastboot.exe`，26 MB/s |

## 现在不能做什么

| 功能 | 状态 | 卡在哪 |
|------|------|--------|
| 相机 | ❌ | 驱动只有 POCO X5 Pro / OnePlus 8 两套，RMX3366 的 4 颗 sensor（IMX766/IMX615/IMX481/OV02B）需要现写；`camsensor.py` 解析真我 V2 sensormodule 还没适配完 |
| App Store / 正常装 ipa | ❌ | 没有 `installd` 签名链；自研安装链路可用，但不走 Apple 的安装/校验/沙盒流程 |
| 睡眠 / 唤醒 | ⚠️ | 无完整 PM 实现；**长时间放着请保持屏幕常亮**，锁屏后不保证能唤醒 |
| 断电保留数据 | ❌ | 系统卷和 `/private/var` 都在内存（`hk_data=2`）：重启后 WiFi 密码、装的 App 全丢 |
| 免电脑开机 | ❌ | 现在每次都要从 fastboot 由 PC 灌 2.7 GB 镜像进内存；`darwin_file` 永久刷入在评估中（见 ROADMAP） |
| 12 GB 内存 | ❌ | loader 只交 6 GB；8 GB 试过失败（页表 + 物理不连续），12 GB 需多 bank 支持 |
| 短信 / VoLTE | ⚠️ | 数据+通话已验证；SMS 双向、VoLTE（CallKit 路径）未实测 |
| GPU 加速合成 | ❌ | Adreno 650 的 zap 认证已过、3D core 接受命令，但缺 47 处 `umi_a650` 驱动移植；桌面合成目前走**软件 GL** |
| 触觉反馈（震动） | ⚠️ | `haptic=` 参数被 608 字节 cmdline 上限挤掉，马达驱动本身可用 |

## 它是怎么跑起来的

```
┌──────────────────────────────────────────────────────────────────┐
│ 手机硬件：kona / SM8250-AC / UFS / 90Hz AMOLED / Adreno 650       │
└──────────────────────────────────────────────────────────────────┘
        ▲ 最后一步：跳进内核
┌──────────────────────────────────────────────────────────────────┐
│ XNU 8796.121.2（iOS 16.5 内核）                                   │
│   我们自己写的 bsd/dev/* 驱动：hk_wifi / hk_bt / hk_adsp / ...     │
│   + loader 交过来的 boot_args（含 device tree）                    │
└──────────────────────────────────────────────────────────────────┘
        ▲ payload = kernel + ramdisk + cmdline（44 MB，从 USB 传）
┌──────────────────────────────────────────────────────────────────┐
│ xnuloader：一个 UEFI 应用（1.8 MB，arm64）                         │
│   自己实现 fastboot 协议、UFS 块设备、显示初始化、PSCI 启核         │
│   「oem ramdisk」→ 把 2.7 GB 系统卷收进内存                        │
│   「oem run」   → 起内核                                           │
└──────────────────────────────────────────────────────────────────┘
        ▲ boot（ABL 的 fastboot）
┌──────────────────────────────────────────────────────────────────┐
│ Android 的 ABL / bootloader（原厂不动）                            │
└──────────────────────────────────────────────────────────────────┘
```

三个关键点，理解它们才能理解为什么这么多坑：

1. **系统卷在内存里**。2.7 GB 的 APFS 镜像每次开机由 USB 灌进 RAM，再挂成根文件系统。
   所以「刷机」其实不是写 flash，而是往内存装系统；断电即失。
2. **loader 和内核是同一个 exception level 的两个阶段**，共享 UEFI 的运行时服务、
   共享一块 `block_shared` 邮箱，也共享 Qualcomm 的 PMIC/SPMI 仲裁器——
   内核一旦去碰 PMIC，loader 的 USB 就死（复现 5 次）。所以按键、块设备都由 loader 代读。
3. **ABL 每次冷启动只接受一次 `boot`**。内核跑完（或挂掉）回来后要在同一会话里再 `oem run`，
   会撞上 Qualcomm PSCI 的 `CPU_ON` 返回 `-4`——必须 `reboot bootloader` 重新来一遍。

## 快速开始：刷入体验版

前提：一台手机（RMX3366，bootloader 已解锁）、一根数据线、一台 Windows。

1. 手机关机 → 按住 **音量下 + 电源** 直到出现 `fastboot` 画面
2. 双击 **`刷机-体验版.bat`**（UAC 选「是」）
3. 等约 2 分钟，看到 `FLASH DONE`
4. 手机 1–2 分钟后进入 iOS 桌面

脚本会自己检查：内置 Python、pyusb、libusb DLL、三个镜像是否齐全。
**USB 驱动只做提示**：如果 Windows 看得到手机但 libusb 打不开，
脚本会问你要不要试装 WinUSB —— **直接按回车就跳过，继续往下走**。

体验版内容：

- 中文界面（完整 PingFang、全部 zh 本地化）
- **没有任何定时器**：不会「到点自己黑屏停住」
- **没有屏幕日志**（去掉了 `-v`，内核不再把文本控制台画到屏幕上）
- 开机后不联网、不装演示 App

细节见 [`packaging/experience-build/使用说明.txt`](packaging/experience-build/使用说明.txt)。

## 仓库结构

```
kona-ios/
├── README.md                     本文
├── docs/
│   ├── FEATURES.md               功能矩阵（每条都带证据与日期）
│   ├── BUGS.md                   每一个 bug：现象 → 根因 → 修法 → 坑（约 40 条）
│   ├── HANDOVER.md               接手文档：环境、路径、流程、优先级、铁律
│   ├── BUILD.md                  构建链：内核 / userland / 系统卷 / ramdisk / payload / loader
│   ├── FLASH.md                  刷机链路与 USB 层的全部坑
│   ├── DEVICE.md                 硬件常量：地址、GPIO、电源轨、传感器、设备树差异
│   ├── ROADMAP.md                没做完的、试过什么、进度如何
│   ├── HISTORY.md                按时间顺序的完整工作记录（78 节，最长的一份）
│   └── CREDITS.md                上游项目与许可
├── tools/
│   ├── fb_libusb.py              纯 Windows 的 libusb fastboot 客户端（核心工具）
│   ├── make_payload.py           kernel + ramdisk + cmdline → XNUP payload
│   ├── dump_payload.py           查看 payload 的条目与 cmdline
│   ├── bootargs_edit.py          cmdline 里按字节替换参数
│   ├── bootargs_drop.py          删掉一条 cmdline 参数（整条，不留空壳）
│   ├── bootargs_bootcpu.py       改 bootcpu（绕过 PSCI -4 的应急手段）
│   ├── hkpack.py                 .app/.ipa → hkinstall 能吃的 ustar
│   ├── hkserve.py                PC 侧 HTTP 供包（纯 stdlib）
│   ├── write_rcjobs.py           生成 ramdisk 的 /redwood/etc/rc.jobs
│   ├── extract_ramdisk.py        从 payload 里取出 ramdisk
│   ├── build-system-cn.sh        系统卷构建（从 userland/build.sh 抽出的系统镜像段）
│   ├── loader/
│   │   ├── hkadd_app.sh          换一个 App → 重打 ramdisk + payload（不动 2.7 GB 系统卷）
│   │   ├── patch_loader_gpt_fallback.py  给 loader 加"自己解析 GPT"的兜底
│   │   ├── patch_cell_firmware_from_md0.py  把 modem/efs 固件打包到系统卷尾部
│   │   └── replace_loader_in_bootimg.py     （失败的方向，留作反面教材）
│   └── app/                      测试 App 的源码（hktest）
└── packaging/
    └── experience-build/         体验版一键刷机包（脚本部分；镜像需自行生成）
```

## 文档索引

| 你想知道 | 去哪看 |
|---------|--------|
| 每个功能到底能不能用、怎么验证的 | [`docs/FEATURES.md`](docs/FEATURES.md) |
| 某个 bug 为什么发生、怎么修的 | [`docs/BUGS.md`](docs/BUGS.md) |
| 我要接着做，从哪开始 | [`docs/HANDOVER.md`](docs/HANDOVER.md) |
| 怎么从零编译出这套东西 | [`docs/BUILD.md`](docs/BUILD.md) |
| 刷机为什么老失败 / USB 为什么卡死 | [`docs/FLASH.md`](docs/FLASH.md) |
| 某个地址/GPIO/电源轨是多少 | [`docs/DEVICE.md`](docs/DEVICE.md) |
| 还剩什么没做、试过哪些死路 | [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| 完整的踩坑流水账（78 节） | [`docs/HISTORY.md`](docs/HISTORY.md) |

## 六条铁律（血泪教训，先读再看代码）

1. **内核永远不要碰 PMIC / SPMI 仲裁器。** 内核和 loader 是同一个 EE（设备树 `qcom,ee=<0>`），
   抢仲裁器会把 loader 的 USB 弄死——读也不行。按键必须由 loader 代读再通过共享内存交给内核。
   复现 5 次，每次都要断电重来。
2. **Wi-Fi 开着的时候绝不 `oem stop`。** PCIe DMA 归属不明时会走 `pci_diag_halt()`：
   内核故意不返回 loader（避免把网卡还在 DMA 写的内存交出去），整机停住，只能断电。
3. **一个 loader 会话只能 `oem run` 一次。** 内核返回后核 4 仍是「开」的，
   Qualcomm PSCI 对第二次 `CPU_ON` 回 `-4 INVALID_PARAMETERS`。要再跑：`reboot bootloader` 重来。
   应急手段是 `bootcpu=0`（走 loader 本地跳转、不调 PSCI，代价是慢约 2.5 倍）。
4. **`fastboot boot` 只能送 1.8 MB 的 loader-only 镜像**；44 MB 的 payload 必须用
   `oem ramdisk` + `download` 单独送。把内核塞进 boot 镜像里 = 起不来。
5. **cmdline 上限是 608 字节**（内核 `boot_args.CommandLine` 决定，loader 也一样）。
   loader 自己先占 18 字节（`debug=0x8 rd=md0 `），所以 payload 只有 **589 字节**。
   超了会被**静默从尾部截断**，而且会从**参数名中间**切开——曾经把
   `modem_efs=1 modem_service=1 modem_secs=120` 整个切掉而没人发现。
6. **不要在同一个 loader 会话里读 `oem log` 之后继续刷机。** 主机半途放弃的传输会留在
   dwc3 里，后续回复逐条错位，最终全部超时；拔插也救不回来，只能重启。
   （已在客户端修掉：`read_stream()` 强制读完整帧。）

## 性能现状

- 桌面合成走 **软件 GL（hk-gl）**：Adreno 650 的 GPU 驱动只到「3D core 接受命令」，
  没有真正的合成路径，所以帧率受 CPU 限制，实测十几帧级（动画不流畅，静态界面可用）。
- App 启动 2–3 秒（iOS 16.5 原生 App，从 SpringBoard 点图标起算）。
- 内存只有 6 GB 交给内核（真机 12 GB，物理 3 段不连续，见 ROADMAP）。
- 首次启动偏慢：2.7 GB 系统卷要经 USB 进内存，之后从 RAM 读。

## 法务与品牌声明

- 本仓库 **不含** Apple 的任何二进制（不含 iOS 系统镜像、固件、私有框架）。
  所有 Apple 组件需使用者依法自行获取；仓库只提供构建/打包/刷机脚本与文档。
- 本项目与 Apple、OPPO/realme、Qualcomm 均无关系，未获其授权或背书。
- 仅供个人研究、学习与教学。刷机有变砖风险，刷之前请确认自己的机器已经解锁
  bootloader 且能接受"这台机器暂时不能当主力机"。
- 代码许可：见 [`LICENSE`](LICENSE)（MIT，仅覆盖本仓库自有的脚本与文档）。
  内核补丁的上游归属见 [`docs/CREDITS.md`](docs/CREDITS.md)。

## 致谢

- **[Evsio0n/instantnoodle-xnu](https://github.com/Evsio0n/instantnoodle-xnu)** —— 同源参照项目，
  跑在 OnePlus 8（也是 kona/SM8250）。本项目的**每一个子系统**都是先读它的实现再移植：
  `AGENTS.md` → `docs/subsystems/<子系统>.md` → `xnu/files/bsd/dev/hk_*.c`。
  没有它，这个移植不可能走这么远。
- **hackios / iphont-xnu-userland** 系（`haxi0`、`oosexgang` 等）—— XNU 跑在 Android 上的
  原始 userland 与 APFS 工具。
- Qualcomm UEFI（`Mu-Silicium` / `edk2` 的 kona 平台移植）—— loader 作为 UEFI 应用的运行环境。
- 以及无数在 XNU 源码里留下注释的人：那些 `/* why */` 是这次移植里最值钱的东西。
