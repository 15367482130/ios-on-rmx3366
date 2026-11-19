# 路线图：没做完的、试过什么、卡在哪

> 这一份是"诚实清单"：每条都写 **目标 / 现在的状态 / 已经试过什么（含失败） / 下一步 / 风险**。
> 排序大致按"性价比"（收益 ÷ 工作量）。
> 时间点参考 [`HISTORY.md`](HISTORY.md) 的 §编号。

---

## 1. 装了 App 不用刷机（热安装）★ 优先

**目标**：把 `xxx.ipa` 拷到 PC 上一个文件夹，手机一分钟内自己装上，**不重启、不刷机**。

**现状**：`hkinstall` 已经是"一串命令"式设计
（`fetch` → `unpack` → `install claim system` → `state`），
但触发它的是 ramdisk 里的 `/redwood/etc/rc.jobs`，而 `rc.jobs` 是**编译进 payload** 的，
所以每换一个 App 就要重打 payload + 全量刷机（2.7 GB）。

**已经试过**
- ✅ 用 `hkserve.py` 供包、`hkinstall` 拉包安装、桌面出图标、点击能起（§74 全链路打通）。
- ✅ `hkadd_app.sh` 能做到"只重打 26 MB ramdisk + 44 MB payload"，不碰 2.7 GB 系统卷。
- ❌ 想让 `rc.jobs` 拉一份"任务清单"再逐条执行：卡在 `fetch` **强制校验 SHA256**，
  而清单内容每次都变、哈希无法预置。

**下一步（最省事的路）**
1. 给 `hkinstall` 的 `fetch` 加一个"跳过校验"的模式（SHA 传 `-`），只对**清单文件**用。
2. 加一个 `job` 子命令：拉 `/job.txt` → 每行一个 `.ipa` 文件名 → 逐个 `fetch` + `install`。
3. `rc.jobs` 改成常驻轮询（每 60 s 一次，失败不退出）。
4. `hkserve.py` 改成能服务文件夹里任意文件（现在是单文件）。

**副作用（其实是好事）**：`/private/var` 是内存，重启后 App 会丢；
轮询会在每次开机后自动把清单里的 App 全部重装，等于"自动恢复"。

**风险**：低。`install` 路径已经验证过，只是加一个入口。

---

## 2. 睡眠 / 唤醒

**目标**：锁屏后能睡着、按电源键能唤醒（现在不保证，长放着建议常亮）。

**现状**：没有完整的电源管理实现。显示驱动里没有 `setPowerState` / blank 路径，
`bsd/dev` 里也没有系统休眠实现。

**已经试过**
- 排查过"用几分钟就黑屏"的现象，一度怀疑是休眠没实现——**结论不是**：
  那次是 `loader_return_after` 定时器（§77）和 `launchd` 缺失（§78）。休眠仍然没实现。

**下一步**
1. 先做"假睡眠"：接受 `IOPMrootDomain` 的 sleep 请求但立刻回 wake，
   保证屏幕不黑、系统不退（先把"能不能睡"变成"愿不愿意睡"）。
2. 再做真睡眠：PSCI `CPU_SUSPEND` + GIC 保存/恢复 + 触摸/显示唤醒序列。
3. 最后做电池：待机功耗曲线（现在没有测量手段，需要外接电流表）。

**风险**：中高。睡眠/唤醒是 XNU 里最容易出"醒不过来"的子系统，做一半比不做更糟。

---

## 3. 相机

**目标**：Camera.app 能开、有预览、能拍照。

**现状**：内核里两套相机驱动都是**别的机型**的（POCO X5 Pro / OnePlus 8），
`board=instantnoodle` 会让它走一加 8 路径，而 RMX3366 的 sensor 完全不同 → `cam=5` 必然失败。

**已经做了**
- ✅ 从 Android `/odm/lib64/camera/` 提取 4 个 sensormodule（V2.0.0 格式）：
  `sunny_imx766.bin`、`qtech_imx615.bin`、`ofilm_imx481.bin`、`shine_ov02b.bin`，外加 30 个配置（150 MB）。
- ✅ 用 `camsensor.py` 试解析：OV02B 能读出 `slave 0x7a / id 0x2b@0x302`，
  但生成 tab 时 `not enough values to unpack (expected 3, got 2)`——真我 V2 的 power 序列只有 2 字段；
  另外三个报 `KeyError: 0`（resolution 结构不同）。
- ✅ 确认 `rivena.dts` 里有完整相机硬件（6× CSIPHY、2× CCI、CSID/IFE）。

**下一步（按依赖顺序）**
1. 适配 `camsensor.py` 解析真我 V2 格式（power 2 字段、resolution 结构）。
2. 从 `rivena.dts` 提出每颗 sensor 的：CCI 从地址、reset GPIO、MCLK、电源轨、CSIPHY 通道。
3. 写真机驱动（或把现有驱动参数化，加一个 `board=rmx3366` 分支）。
4. 编 userland 注入库（`libhackios-media.dylib` 里的 `camera_device`/`camera_isp`/`camera_gpu`）。
5. `cam=5` 上机调预览。

**风险**：高工作量（这是整个项目里最"体力活"的一块），但路径已经清楚。

---

## 4. cmdline 上限（608 B）的正解

**目标**：不再需要为了塞参数而删参数。

**现状**：内核 `boot_args.CommandLine` 是 `char[608]`，loader 也是 608，
loader 先占 18 B（`debug=0x8 rd=md0 `），payload 只剩 **589 B**。
超了会被**静默截断**，而且从参数名中间切开（曾经把 5 个 modem 参数整个吞掉，没人发现）。

**已经试过 / 已知**
- ✅ 用"压缩参数 + 按重要性排序"把 payload 压到 585 B（当前体验版），
  但代价是 `haptic=5`（震动）挤不进去。
- ✅ 确认 `BOOT_LINE_LENGTH` 在内核 `pexpert/pexpert/arm64/boot.h` 与 loader 里**各有一份**，
  必须同时改，否则结构体布局不一致（`CommandLine` 之后的字段全部错位）。

**下一步**
1. 两边同时改成 1024，**并在 QEMU 里先跑通**（不要直接上机——一次失败就是十几分钟 + 可能丢状态）。
2. 或者：不改结构体，改成"payload 里写短名"（如 `h=5`）并在内核加别名解析——更 hack，但零风险。

**风险**：中。改 `boot_args` 结构是"全系统级"的改动。

---

## 5. 永久刷入（脱离 PC 开机）

**目标**：手机自己开机进 iOS，不需要电脑灌 2.7 GB。

**现状**：每次开机都要 PC 在旁边，因为系统卷在内存里。

**已评估的路线**（§65–§67）
- 方案：`darwin_file` 全栈——把系统卷**写回 UFS** 的某个分区/文件，loader 从 UFS 读并挂载。
- 已完成的准备：loader 的 **GPT 兜底解析**（本机 UEFI 不给分区 handle，
  见 `tools/loader/patch_loader_gpt_fallback.py`，偏移已用真机 `_gpt_hdr.bin`/`_gpt_entries.bin` 验证）。
- 未完成：UFS **写**路径（现在 `ufs_write=0`）、写入后校验、以及"从 UFS 挂载系统卷"的引导分支。

**风险**：高。写 UFS 会动真分区，写错就是变砖（虽然可以从 fastboot 救回来）。

---

## 6. 短信 / VoLTE

**目标**：短信双向、VoLTE 通话（现在数据 + 通话已经能用，但走的是 CS 回落）。

**现状**：`hk_commcenter` 已编译（有未签名版和签名版），信号显示正常；
但 ramdisk 里**没有** `libhackios-call.dylib` 和 `inject.conf`，所以 `callservicesd` 没被注入。

**下一步**
1. 编 `libhackios-call.dylib`（官方有实现），加进 ramdisk 的注入列表。
2. 用签名版 `hk_commcenter` + CallKit provider（需要真 entitlements）。
3. 实测 SMS 双向、VoLTE、以及掉线重连。

**已知明确没做**（官方也一样）：呼叫等待/hold、DTMF、MMS、热点、紧急呼叫、蓝牙耳机通话、modem 睡眠。

---

## 7. GPU 硬件合成

**目标**：桌面合成走 Adreno 650，帧率不再受 CPU 限制。

**现状**：zap 认证已过（地址修对之后 21 步 bring-up 全成功、3D core 接受命令），
但缺 **47 处 `umi_a650` 驱动移植**，所以合成仍走软件 GL。

**已经试过**
- ✅ GPU zap 地址纠错（`0x8681a000` → `0x8e21a000`），二进制 patch 一个常量。
- ❌ 想"只移植合成相关的几处"——不行，`umi_a650` 是一整套命令流抽象，缺一处就不出图。

**下一步**：老实按 upstream 的 `metal` 路径移植（参照项目已有 Metal 合成，但那是 OnePlus 8/Adreno 650 同款，
理论上可以直接搬，实际要按本机 GPU 频率/电源/固件核对）。

**风险**：高工作量。收益是"流畅"，不是"能用"。

---

## 8. 内存 8 GB / 12 GB

**目标**：把 12 GB 物理内存都用上（现在只交 6 GB 给内核）。

**已经试过（失败）**
- 阶段 A：改 loader `MAX_MEM_SIZE` → 8 GB + 内核页表 `BOOTSTRAP_TABLE_SIZE` 20→24，
  **结果设备卡在 fastboot 坏状态**，需要断电 + 从 Android `adb reboot bootloader` 恢复（§70）。
- 查清了三处限制：loader 宏、页表大小、**物理三段不连续（6–8 G 有 2 GB 洞）**。
- 结论：`maxmem` 之类的 boot-arg 只能向下裁剪，不能向上扩；三棵树都没有现成的大内存补丁。

**下一步**：给 XNU arm64 加"多 bank 离散物理内存"支持
（`boot_args` 现在只有一个 `physBase` + `memSize`），loader 交多段，`ARM_LARGE_MEMORY` 配套。
这是移植级工程，不建议在没解决"睡眠/相机"之前动。

---

## 9. 小项

| 项 | 现状 | 下一步 |
|----|------|--------|
| 震动马达 | 驱动可用，`haptic=5` 被 608 B 上限挤掉 | 见 §4 |
| 麦克风 | `mic=4` 已加，未系统验证 | 录音测试（语音备忘录） |
| `rc.jobs` 轮询 | 体验版已清空（不装 App） | 与 §1 一起做 |
| 粤语本地化 | `KEEP_LANG` 没加 `yue_CN`（原始镜像里有） | 加进保留列表，+几 MB |
| Emoji | `AppleColorEmoji-160px.ttc` 被裁到 3 个 strike（136.7 → 61.8 MB） | 一般够用；如果要完整 emoji，换回原文件（+75 MB） |
| 启动时间 | 60–120 s（含 2.7 GB 传输） | 压缩系统卷（`mkapfs -z` 已开）；考虑只传变化的层 |
| 多次重启后 WiFi 密码丢失 | 设计如此（`/var` 在内存） | 见 §5 |

---

## 10. 明确"不做"的

- **App Store**：需要 Apple 的安装/签名/沙盒全链路，不在本项目范围。
- **越狱/插件体系**：与本项目目标（跑起 iOS 用户态）无关。
- **绕过激活/账号**：不做。
- **把 iOS 镜像塞进仓库**：不合法，也不做。
