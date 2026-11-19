# 接手文档（从这里开始）

> 写给下一个接手的人：你需要什么环境、东西都在哪、怎么跑一遍、按什么顺序做、
> 哪些坑已经有人替你踩过了。
>
> 如果你是第一次看这个项目，先读 [`../README.md`](../README.md) 的「它是怎么跑起来的」，
> 再回来。

---

## 1. 项目一句话

一台 realme RMX3366（kona / SM8250-AC）被移植成能跑 **iOS 16.5 用户态**：
从 ABL fastboot 由 PC 灌入 loader + 2.7 GB 内存系统卷 + 44 MB payload，
到 SpringBoard 桌面，触摸/显示/中文/Wi-Fi/蓝牙/声音/基带数据与通话/装第三方 App 都可用。

**它不是**：能日常使用的手机、能过 Apple 校验的系统、能 OTA 的系统。
每次开机都要 PC 在旁边（2.7 GB 灌内存），断电即失。

---

## 2. 环境

### 2.1 两套环境，职责严格分开

| 用途 | 在哪 | 为什么 |
|------|------|--------|
| 编译内核 / userland / 打包镜像 | **WSL2 Linux（Ubuntu）** | 需要 clang、theos、mkapfs、容器 |
| 任何与手机通信（fastboot/adb/刷机/取日志） | **纯 Windows** | WSL 的 usbip 转发会把设备置于半接管状态，fastboot 协议直接卡死 |

> 这条分工是硬规矩。历史上所有"刷机卡死"里至少一半是"在 WSL 里碰 USB"造成的。

### 2.2 WSL 侧

| 东西 | 路径 | 说明 |
|------|------|------|
| 主工作树（userland + 系统镜像 + 内核补丁） | `/root/work/itn-fpsbuild` | 从 `instantnoodle-xnu` 派生，加了我们的中文/字体/launchd 修复 |
| 参照项目（**必读**） | `/root/work/instantnoodle-xnu` | OnePlus 8 上的同源实现，完成度高得多 |
| loader 源码树 | `/root/work/mi10ultra/xnuloader` | loader 只能从这棵树编（另一棵树编出来在本机起不来） |
| 内核源码树（另一份，历史） | `/root/work/mi10ultra/xnu-src` | 部分旧驱动在这里，注意与本机真实内核区分 |
| theos 工具链 | `/root/theos`（`toolchain/linux/iphone/bin/{clang,ldid}`、`sdks/iPhoneOS16.5.sdk`） | 编 iOS 二进制 |
| 完整 PingFang | `/root/work/fonts/PingFang-full.ttc` | 77,871,956 B，36 字面 |
| 系统卷构建脚本 | `/root/work/mksys-cn.sh` | 从 `userland/build.sh` 抽出的"只做系统镜像"那段 |
| ramdisk 工作树 | `/root/work/itn-fpsbuild/rd-full` | ramdisk 内容（`etc/rc.jobs`、`bin/hkinstall`、`redwood/`） |

### 2.3 Windows 侧

| 东西 | 路径/说明 |
|------|-----------|
| 刷机客户端 | `tools/fb_libusb.py`（libusb 直连，不需要 `fastboot.exe`） |
| 依赖 | `pyusb` + `libusb-1.0.dll`（放在脚本同目录） |
| 体验版打包 | `packaging/experience-build/`（含内置 Python 运行时，拷到任何 Windows 都能刷） |

### 2.4 设备侧（每次开机都在变，不要期望"记住了"）

- `/private/var` 是 **RAM**（`hk_data=2`，1024 MB）：Wi-Fi 密码、装的 App 全部重启即失。
- 系统卷也是 RAM：每次开机由 PC 灌 2.7 GB。
- 因此"改一个设置试试"这件事在重启后不留痕——这既是麻烦，也是安全网。

---

## 3. 一遍完整流程（从零到桌面）

```bash
# ---------- WSL ----------
# 1) 系统镜像（含中文、完整字体、帧率 plist、launchd.darwin）
bash /root/work/mksys-cn.sh                     # 约 3.5 分钟 → userland/system.apfs

# 2) 追加 modem 固件（从"旧的、已知能用的系统卷"尾部整段搬过来）
python3 - <<'PY'
import os, shutil
OLD="/mnt/c/.../system-sdx55.apfs"; NEW="/root/work/itn-fpsbuild/userland/system.apfs"
OUT="/mnt/c/.../system-sdx55-cn3.apfs"; base_old=604668*4096
blob=os.path.getsize(OLD)-base_old
with open(OLD,"rb") as f, open(OUT,"wb") as o:
    shutil.copyfileobj(open(NEW,"rb"),o,4<<20); f.seek(base_old)
    left=blob
    while left:
        c=f.read(min(8<<20,left)); o.write(c); left-=len(c)
print("modem_fw_base =", os.path.getsize(NEW)//4096)
PY

# 3) payload：kernel + ramdisk + cmdline（cmdline 里 modem_fw_base 要等于上一步的块数）
python3 make_payload.py -o itn-exp.bin --from itn-cn4.bin \
        --ramdisk rd-exp.apfs --cmdline "$(cat _cmdexp2.txt)"
```

```powershell
# ---------- Windows ----------
python fb_libusb.py flash loader-logfix.img system-sdx55-cn3.apfs itn-exp.bin
#   [1/5] download loader → boot → 等 4EE0 重新枚举
#   [3/5] oem ramdisk
#   [4/5] download system.apfs (2.7 GB) + payload (44 MB)
#   [5/5] oem run
```

手机侧：开机 → 白苹果（其实没有苹果标，是黑屏+背光） → 约 60–120 秒到 SpringBoard。

---

## 4. 产物清单（哪些是"真的"，哪些是历史垃圾）

### 4.1 当前可信的三件套

| 文件 | 大小 | 说明 |
|------|------|------|
| `loader-logfix.img` | 1,822,720 B | loader，**唯一可信来源**：`mkpayload.py` + `mkxnuimg.py`（FD=`alioth-drivers.fd`, `UEFI_TARGET=rivena`）生成，可逐字节复现 |
| `system-sdx55-cn3.apfs` | 2,734,755,840 B | 系统卷：中文 + 完整 PingFang + 帧率 plist + `launchd.darwin` + 尾部 208,670,720 B modem 固件（基址 LBA 616,720） |
| `itn-exp.bin` | 44,163,944 B | 体验版 payload：无定时器、无 `-v`、cmdline 585 B（不截断） |

### 4.2 历史产物（**不要拿它们当基线**）

`itn-*.bin` 有几十个、`loader-*.img` 十几个。命名规则是"当次实验的标签"，不是版本号。
如果你不确定用哪个，**用 4.1 的三件套**，或者照 §3 重新生成。

### 4.3 已知失败的方向（别重复）

- `replace_loader_in_bootimg.py`：外科手术式替换 boot 镜像里的 loader，两条 bug（zlib 不是 gzip、
  按 `kernel_size` 截断 DTB），修完仍不启动。**放弃**。
- `loader-abort*.img`：给 loader 加 `abort_xfer` 想解决端点卡死。测试证明 abort 之后端点
  没有重新 arm，仍是坏的。**留作诊断镜像**。
- 内存 6→8 GB：改 loader 宏 + 页表，结果设备卡 fastboot 坏状态。**已回退**。
- `redwood-drivers.fd`：缺本机 USB 设备协议，4EE0 永不出现。**必须用 `alioth-drivers.fd`**。

---

## 5. 接手后的优先级（按"投入/收益"排序）

1. **让"装 App"变成不需要刷机**（热安装）：`hkinstall` 已经能 `fetch`+`install`，
   现在只差一个"常驻轮询 PC 的 job 清单"的入口。收益最大、风险最低。
2. **睡眠/唤醒**：不实现的话，用户体验上"离开几分钟回来就废"。
   需要 IOPM + PSCI CPU_SUSPEND + 显示/触摸唤醒恢复。
3. **相机**：工作量最大（要写 4 颗 sensor 的驱动），但这是"能不能当手机用"的分水岭。
   起点已经备好：4 个 sensormodule + `rivena.dts` + 两份参照驱动。
4. **cmdline 上限（608）的正解**：把内核 `boot_args.CommandLine` 和 loader 一起放大到 1024，
   一次性解决"参数被截断"和"haptic 挤不进去"两个问题。风险：改 `boot_args` 结构要两边同步。
5. **永久刷入（`darwin_file`）**：让手机脱离 PC 开机。评估过路线（§65–§67），
   需要 UFS 写路径 + GPT 兜底 + 校验。
6. **短信/VoLTE**：`hk_commcenter` 已编译（含签名版），差 `libhackios-call.dylib` 注入 `callservicesd`。
7. **GPU 合成**：Adreno 650 的 47 处 `umi_a650` 移植。收益是流畅度，代价是"另一个大工程"。

---

## 6. 六条铁律（违反一次浪费半天）

1. **内核绝不碰 PMIC/SPMI 仲裁器**（会弄死 loader 的 USB，只能断电）。
2. **Wi-Fi 开着时绝不 `oem stop`**（`pci_diag_halt()`，整机停住）。
3. **一个 loader 会话只 `oem run` 一次**（PSCI `-4`）。要再跑就 `reboot bootloader`。
4. **`fastboot boot` 只送 1.8 MB loader**；payload 走 `oem ramdisk` + `download`。
5. **cmdline ≤ 589 字节（payload 部分）**，否则静默从尾部截断、从参数名中间切开。
6. **读 `oem log` 要一次读完**，否则孤儿传留在 dwc3，后续全部超时。

外加两条元规矩：

7. **动手前先查"是不是已经做过"**（产物、日志、本文件对应章节、上游源码）。
8. **每次只改一个变量，并保留一个已知可用的基线镜像**。

---

## 7. "我想改 X，该看哪里"

| 想改 | 看这里 | 注意 |
|------|--------|------|
| 启动参数（cmdline） | `tools/bootargs_edit.py` / `bootargs_drop.py`；先读 `BUGS.md B2` | 589 字节上限，改完一定核对长度 |
| ramdisk 内容（`rc.jobs`、注入库、hkinstall） | `/root/work/itn-fpsbuild/rd-full` + `tools/loader/hkadd_app.sh` | 只重打 26 MB ramdisk + 44 MB payload，不动 2.7 GB 系统卷 |
| 系统卷内容（App、字体、`.lproj`、plist） | `tools/build-system-cn.sh` | 改完必须跟"上一个能用的镜像"做双向差集 |
| 内核驱动 | `/root/work/itn-fpsbuild/tools/nf/cell/`（`build.py`）与 overlay | 在 `oneplus8-build` 容器里编译，见 `BUILD.md` |
| loader | `/root/work/mi10ultra/xnuloader/loader.c` | 只有这棵树编出来的能在本机起；改完**看体积**（79,872 B 是上限附近） |
| 刷机客户端 | `tools/fb_libusb.py` | `read_stream()` 必须整帧读完；`download` 的大小必须**小写 hex** |
| 打包体验版 | `packaging/experience-build/` | 三个镜像改名进包 + `versions.json` 同步 |

---

## 8. 诊断手册

### 8.1 起不来怎么分诊

| 现象 | 最可能 | 怎么确认 |
|------|--------|---------|
| loader 都不枚举（没有 4EE0） | loader 镜像错 / FD 文件错 | 换回 `loader-logfix.img` 再试 |
| 枚举 4EE0 但 `oem run` 返回 FAIL | 上一个会话已经 run 过（PSCI -4） | `reboot bootloader` 重来 |
| 黑屏、loader 还活着、`oem log` 有输出 | 内核起来了但用户态没起 | 看日志结尾有没有 `init: done` |
| 日志结尾 `launchd.darwin: No such file` | 系统卷缺 `sbin/launchd.darwin` | 见 `BUGS.md B5` |
| 日志结尾 `wifi: UNCLEAN PCIe DMA OWNERSHIP` | 运行被异常结束 + 故意 halt | 找"谁结束了运行"（定时器/panic） |
| 到桌面但界面英文 | 系统卷 `.lproj` 被裁 | 见 `BUGS.md D1` |
| 到桌面但有方块 | PingFang 是裁剪版 | 见 `BUGS.md D2` |
| 用 30 分钟自己黑屏 | cmdline 里有 `loader_return_after` | 见 `BUGS.md B3` |

### 8.2 取日志的正确姿势

```powershell
python fb_libusb.py log _log.txt      # 一次 staging + 一次读完整帧
```

只有在**内核还活着、loader 也还活着**的时候才有意义。读完这一次之后，
端点可能就卡了——**所以读完就准备重启，不要接着刷机**。

---

## 9. 交接时的工作区状态（截至 2026-11-19 晚）

- 体验版三件套已生成并**在真机上验证过中文/显示/触摸/无线/基带**。
- 体验版 payload（`itn-exp.bin`）的 cmdline 已精简到 585 B，**无定时器、无 `-v`**，
  尚未做"长时间连续使用"的验证（用户下一步要做的就是这个）。
- `rc.jobs` 已被清空（体验版不联网、不装演示 App）；`hkinstall` 仍在 ramdisk 里。
- 系统卷 `system-sdx55-cn3.apfs` 的 modem 固件段来自更早的 `system-sdx55.apfs`
  （原始 `modem.img`/`efs*` 素材已丢失，只能整段搬）。
