# 上游与许可

这个项目是**站在别人的肩膀上**完成的。下面按"对我们的实质影响"排序。

---

## 1. Evsio0n/instantnoodle-xnu（最重要）

<https://github.com/Evsio0n/instantnoodle-xnu>

- 同源项目（同样是 XNU 8796.121.2 + HackiOS 派生），跑在 **OnePlus 8**（kona / SM8250）。
- **完成度比我们高得多**：Metal 合成、UFS 落盘、90 Hz、按键、TFA9874 声音、Wi-Fi、蜂窝
  （数据/短信/VoLTE 都有）都已经做成。
- 本项目的**每一个子系统**都是先读它再移植：
  `AGENTS.md` → `docs/subsystems/<子系统>.md` → `docs/research/` → `xnu/files/bsd/dev/hk_*.c`。
- 我们的很多"顿悟"直接来自它的注释，例如：
  - `hk_wifi.c` 里 `pci_diag_halt()` 那一段"归属不明就不把内存交出去"的设计；
  - `select-system.py` 文件头关于"空 `.lproj` 目录是 CoreFoundation 判断语言的依据"的说明；
  - `font_trim.py` 里"为什么可以只留 Regular/Semibold"的前提（我们是字重不够才出问题）；
  - `loader_return.c` 里 `loader_return_after` 的用途（测试用，不是给用户用的）。

> 如果只有一句话给后来者：**先看它怎么做，再动手。** 我们在旧框架上打补丁浪费了整整一天。

## 2. hackios / iphont-xnu-userland 系

- `haxi0`、`oosexgang` 等人的 `iphont-xnu-userland` / `hackios-xnu-userland`：
  XNU 跑在 Android 手机上的**原始 userland**（init、注入库、daemon 启动顺序）、
  APFS 工具（`mkapfs.py` / `verify.py`）以及系统镜像构建管线。
- 本项目 `userland/` 与 `tools/apfs/` 的大部分代码来自这里。

## 3. Qualcomm UEFI 生态

- `Mu-Silicium` / `edk2` 的 kona 平台移植：loader 作为 UEFI 应用运行的环境，
  以及 UFS、显示、PSCI 的底层协议。
- `xnuloader` 本身是这套生态里的"能跑 iOS 的 bootloader"的分支。

## 4. 其它

- `dekefake/hackios-op8pro`：OnePlus 8 Pro 的蜂窝驱动移植（上游 `tools/nf/cell` 的 `port.py`
  就是从这个仓库的 14 个文件生成 `instantnoodle_cell.c` / `hk_mhi.c` 等）。
- 各类反向工程资料：fastboot 协议、GPT、APFS、`iPhoneOS16.5.sdk` 的头文件、ldid 签名。

---

## 许可

| 内容 | 许可 |
|------|------|
| 本仓库自有的脚本与文档（`tools/`、`docs/`、`README.md`、`packaging/`） | **MIT**（见根目录 `LICENSE`） |
| 派生自 XNU 的补丁与驱动（`bsd/dev/*`、overlay 里的文件） | 随 XNU 的 **Apple Public Source License 2.0** |
| `tools/apfs/`（`mkapfs.py` 等） | 跟随上游 `iphont-xnu-userland` 的许可 |
| Apple 的系统二进制、固件、SDK | **不在本仓库**，需自行依法获取 |

> 本仓库**不包含**任何 Apple 的二进制（无 iOS 镜像、无固件、无私有框架）。
> 你需要的 `rootfs.dmg`、`AppleColorEmoji-160px.ttc`、`PingFang.ttc`、modem 固件等，
> 都必须自己从合法来源获取，并按 `docs/BUILD.md` 处理。

---

## 商标

Apple、iPhone、iOS、macOS 是 Apple Inc. 的商标。
Qualcomm、Snapdragon 是 Qualcomm Incorporated 的商标。
realme、OPPO 是其各自所有者的商标。
本项目与上述公司**无任何关联**，未获其授权或背书。
