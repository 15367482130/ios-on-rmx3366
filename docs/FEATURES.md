# 功能矩阵（逐项证据）

> 状态定义：**✅ 可用** = 真机上跑通且被人眼/日志确认；**⚠️ 部分** = 能用但有明确缺陷；
> **❌ 不可用** = 完全没做或做了不通。
> 每一项后面的 §编号 指向 [`HISTORY.md`](HISTORY.md) 里当时的完整记录。

设备：realme 大师探索版 **RMX3366**（kona / SM8250-AC / 12 GB 物理内存 / UFS 3.1 / 90 Hz AMOLED）
系统：iOS 16.5（20F66 rootfs），XNU 8796.121.2，Darwin 22.5.0

---

## 一、总表

| 子系统 | 状态 | 关键开关（cmdline） | 驱动 / 组件 | 证据 |
|--------|------|--------------------|------------|------|
| 引导链 | ✅ | — | `xnuloader`（UEFI app，1.8 MB） | 每次刷机都验证 |
| 内核启动 | ✅ | `bootcpu=4 cpus=8 cpufreq=1` | XNU 8796.121.2 | §23 |
| 显示点亮 | ✅ | `gpu=1 gl=1 ca_fps=90 ca_vbl=1` | `hk_display` / MDP | §23 |
| 桌面合成（软件 GL） | ✅ | `gl=1` | `hk-gl` | §23.13 |
| 帧率上限 | ⚠️ 90 Hz 面板 + 软合成 | `ca_fps=90` | `ca_ideal_rate` / backboardd | §24 |
| 触摸 | ✅ | — | S6SY792（真机协议） | §26 |
| 按键（音量±/电源） | ✅ | `buttons_volup_vin=1 buttons_voldown_pullup=1` | loader 代读 | §28 |
| UFS 存储（读） | ✅ | `ufs=2 ufs_write=0` | `hk_ufs` | §13/§46 |
| `/private/var`（内存） | ✅ | `hk_data=2 hk_data_mb=1024 var_store=0 var_data=hfs var_data_format=1` | `init` 格式化 / 挂载 | §73 |
| 声音（扬声器） | ✅ | `adsp=1 adsp_mem=0x91b00000 sound=4 sound_amps=1` | `hk_adsp` + `hk_speaker` | §29/§30 |
| 麦克风 | ⚠️ | `mic=4` | `hk_mic` | §71 |
| 震动马达 | ⚠️ | `haptic=` 被 cmdline 截断 | `redwood_haptic` | §71 |
| 手电筒 | ✅ | `torch=3` | LED flash | §33 |
| Wi-Fi | ✅ | `wifi=1 wifi_bdf_native=1 wifi_rails=smpa6:950,smpa4:1800,smpa5:1900,smpc8:1350` | `hk_wifi` | §33/§63 |
| 蓝牙 | ✅ | `bt=1 bt_ldo=ldoa16 bt_ldo_mv=3024` | `hk_bt` | §33/§62 |
| 基带（注册/信号） | ✅ | `modem=5 cell=1 cell_dcm=1` | `hk_cell` + `modem` 固件 | §52/§54 |
| 基带（数据上网） | ✅ | 同上 | `hk_cell` + `net_test` | 用户换卡实测 |
| 基带（语音通话） | ✅ | 同上 | `hk_cell` + callservicesd | 用户换卡实测 |
| 基带（短信/VoLTE） | ⚠️ 未实测 | — | 需 `libhackios-call.dylib` 注入 | §64.2 |
| 中文界面 | ✅ | — | 系统卷补 `.lproj` + 完整 PingFang | §76/§78 |
| 第三方 App 安装 | ✅ | `cs_enforcement_disable=1` | `hkinstall` + `hkpack` | §73/§74 |
| App 启动 | ✅ | — | SpringBoard + FrontBoard（需 `claim system`） | §74 |
| 相机 | ❌ | `cam=5`（当前未启用） | 缺 RMX3366 传感器驱动 | §68 |
| 睡眠/唤醒 | ❌ | — | 无 PM 实现 | §78.1 讨论 |
| 永久刷入（免 PC） | ❌ | — | `darwin_file` 路线评估中 | §65–§67 |
| 8 GB / 12 GB 内存 | ❌ | — | loader `MAX_MEM_SIZE` + 页表 | §69/§70 |

---

## 二、逐项细节

### 1. 引导链

```
ABL fastboot (VID 18d1 / PID d00d, product=kona)
   │  download 1.8 MB loader-logfix.img  →  boot
   ▼
xnuloader (PID 4ee0, product=xnuloader)
   │  oem ramdisk            ← 声明这次要往内存装系统
   │  download 2.7 GB       ← APFS 系统卷 + 尾部 modem 固件
   │  download 44 MB payload ← kernel + ramdisk + cmdline
   │  oem run
   ▼
XNU → ramdisk 里的 /sbin/launchd.darwin → iOS 用户态
```

- loader 是一个 **UEFI 应用**，由 Qualcomm 的 UEFI（kona 平台）加载；
  它自己实现 fastboot 协议、UFS 块设备（含 GPT 兜底解析）、PSCI 启核、显示初始化。
- 关键点：`oem run` 之后 loader **仍然活着**，跑在 core 0 上，负责心跳监视、
  按键代读、以及在需要时把内核日志带回 PC。

### 2. 显示与合成

- 面板点亮走 MDP（Mobile Display Processor）路径，参数 `gpu=1 gl=1 ca_fps=90 ca_vbl=1`。
- **合成是软件光栅化**（`hk-gl`），不是 Adreno 650 硬件合成：
  GPU 侧的 zap 内存地址已经修对（本机真值 `0x8e21a000`，不是上游的 `0x8681a000`），
  21 步 bring-up 全过、3D core 接受命令，但缺 47 处 `umi_a650` 驱动移植，不算"能用"。
- 后果：帧率受 CPU 限制，动画不流畅；静态界面、滚动（单帧重绘）可用。

### 3. 触摸

- S6SY792，走真机 I2C 协议；早期用错协议导致"点了没反应"。
- 多点可用；不需要额外 cmdline 开关。

### 4. 存储

- **UFS 读**：`ufs=2` 走内核原生读，`ufs_write=0` 关闭写（防误写、也避开写路径未验证）。
- **系统卷**：2.7 GB APFS 从 USB 收进内存，挂成根。**每次开机都要重装**。
- **`/private/var`**：内存盘（`hk_data=2`，1024 MB，HFS 格式化由 userland `init` 做）。
  所以 Wi-Fi 密码、装的 App、改的设置**重启即失**——这是设计如此，不是 bug。
- 分区的来源：loader 的 `block_shared.part[]`。本机 UEFI **不给** `EFI_PARTITION_INFO_GUID`
  handle，所以 loader 里加了一手"自己读 LBA1 的 GPT"兜底（`tools/loader/patch_loader_gpt_fallback.py`），
  否则内核看不到 `modem_a` 等分区。

### 5. 声音

链路：iOS AudioServer → HAL 插件（`HakiosAudio.driver` / `HKAudio.driver` 符号链接）
→ `hk_adsp` 起 ADSP → MI2S → 功放芯片。

- 早期"硬件全通但 iOS 没声音"，根因是官方 userland 的两处配置没照搬（§30）。
- 扬声器功放两条路径：本机走 AW882xx；OnePlus 8 是 NXP TFA9874（`board=instantnoodle` 时切换）。
- 麦克风 `mic=4` 是"白捡"的：主麦喂 iOS，配合 `mic_tap=1` 可以自测。

### 6. 无线

- **Wi-Fi**：需要**原生 BDF**（`wifi_bdf_native=1`，从 Android 分区取）与四条电源轨，
  轨电压错一个就起不来。
- **蓝牙**：靠 `bt_ldo=ldoa16 bt_ldo_mv=3024`；它**和 Wi-Fi 共用 `wifi_rails` 里的轨**，
  所以即使 `wifi=0` 也不能删 `wifi_rails`，否则蓝牙上电失败 → `bluetoothd` 无限重试 → **发热卡死**（§62）。
- 三者共存（Wi-Fi + BT + 基带）是最后才调通的：`§64`。

### 7. 基带

- `cell=1` 启用蜂窝；固件不读 Android 分区，而是**打包在系统卷尾部**
  （`modem.img` / `efs1` / `efs2` / `efsc`，208,670,720 B），内核按 `modem_fw_base=<LBA>` 去找。
- `cell_dcm=1` 是关键：没有它，IMS PDN 反复掉（`PDP_FAILED_EVENT`），注册上但业务不通。
- **实测**：换一张卡后**数据上网 + 语音通话都正常**（用户确认）。
- 未实测：短信双向、VoLTE（需要 CallKit provider + 签 entitlements 的 `hk_commcenter`，
  并给 `callservicesd` 注入 `libhackios-call.dylib`）；官方也明确没做 hold/呼叫等待/DTMF/MMS/热点/紧急呼叫。

### 8. 中文

分两层，缺一层都不行：

1. **字符串**：iOS 判断"这个 bundle 支持哪些语言"看的是**目录下有没有对应的 `.lproj`
   （哪怕是空目录）**。构建脚本 `KEEP_LANG` 只留英文，把这些空目录全裁了，
   于是 `SpringBoard.loctable` 里 1.1 MB 的中文永远不会被查 → 界面全英文。
   修法：`KEEP_LANG` 加上 `zh_CN/zh_HK/zh_TW/zh-Hans/zh-Hant`，重新生成系统卷（+11.3 MB）。
2. **字形**：镜像里的 `PingFang.ttc` 是**裁剪版**（26.9 MB / 12 字面，只留 Regular+Semibold）。
   正文（Regular）正常，但图标名、Safari 界面走 **Medium** → 落 `.notdef` →
   空心方块 / 带问号的方块。修法：换回 Apple 原始的 **77.8 MB / 36 字面**。

### 9. 第三方 App

没有 `installd`、不校验 Apple 签名（`cs_enforcement_disable=1`），走自研链路：

```
PC: hkpack.py 把 .app 打成 ustar（Payload/NAME.app + ents/）
    hkserve.py 用 HTTP 供包
手机: hkinstall fetch → unpack → install → state
      install 时写 SignerIdentity / SignerOrganization + system_registration
      （= .ipa 路径的默认行为，命令里是 `claim system`）
```

- **必须**带 `claim system`：否则 LaunchServices 把它登记成普通用户 App，
  FrontBoard 拒绝 spawn —— 症状就是"图标在、点了没反应"（§74）。
- 图标出现在桌面后**用手指点**能启动；程序自己调 `open` 会被 FrontBoard 拒（官方也是）。

### 10. 不可用项的具体卡点

| 项 | 已经做到哪 | 还差什么 |
|----|-----------|---------|
| 相机 | 从 Android 拉到 4 个 sensormodule（IMX766/IMX615/IMX481/OV02B，V2.0.0 格式） | `camsensor.py` 解析真我 V2 格式（power 序列 2 字段、resolution 结构差异）；按 `rivena.dts` 写真机驱动的 CCI 地址/GPIO/电源轨/CSIPHY |
| 睡眠 | 无 | 完整 IOPM / PSCI CPU_SUSPEND 路径、显示与触摸的唤醒恢复 |
| 免 PC 开机 | 评估了 `darwin_file` 全栈方案（§66） | loader 把系统卷写回 UFS 并从 UFS 挂载；需要 UFS 写路径 + GPT 兜底 + 校验 |
| 12 GB 内存 | 定位到三处限制（loader 宏、页表 `BOOTSTRAP_TABLE_SIZE`、物理 3 段不连续） | XNU arm64 支持多 bank 离散物理内存（移植级工程量） |
| SMS/VoLTE | `hk_commcenter` 已编译（含签名版） | `libhackios-call.dylib` 注入 `callservicesd` + CallKit provider + entitlements |
