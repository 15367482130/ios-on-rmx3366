# 刷机链路（纯 Windows / libusb）

> 这一份讲"怎么把三件套送进手机"，以及 USB 层所有踩过的坑。
> 为什么不用 `fastboot.exe`、为什么不用 WSL 的 usbip，答案都在下面。

---

## 1. 为什么自己写刷机客户端

试过并失败的方案：

| 方案 | 结果 |
|------|------|
| WSL + `usbipd attach` + Linux `fastboot` | 设备被置于"半接管"状态，fastboot 协议卡死；而且 `attach` 会触发设备事件风暴（旧 loader 每来一个事件打印一次），表现为"循环跑码" |
| Windows 原厂 `fastboot.exe` | 与本机的 libwdi 2012 版 WinUSB 驱动在 bulk 传输上不兼容，大文件必挂 |
| 换驱动（`pnputil` 装微软 WinUSB） | 驱动换了，`fastboot.exe` 仍然挂；同样的驱动下 **libusb 却是好的** |

结论：**用 libusb 直接讲 fastboot 协议**。它绕过了 `fastboot.exe` 的所有毛病，
在纯 Windows 上 26 MB/s 传 2.7 GB，全程不需要管理员、不需要 WSL。

---

## 2. 协议本身（很短）

Fastboot 就是 USB bulk 上的四行文本：

```
主机 → 设备:  "download:0000000a"     ← 长度必须是 8 位小写 hex
设备 → 主机:  "DATA" + 10 字节数据 + "OKAY"
主机 → 设备:  "oem run"
设备 → 主机:  "OKAY"
```

要点：

- **长度必须小写 hex**：loader 的 `parse_number()` 只认 `a-f`，大写 `A-F` 会被当成 0。
- **一个进程只能开一个 libusb backend**：多处 `usb.core.find()` 会互相干扰，
  所以客户端全程只复用一个 device 句柄。
- **boot 之后 PID 会变**：ABL 阶段是 `18d1:d00d`，loader 起来后是 `18d1:4ee0`
  （serial 从机器序列号变成 `xnuloader`）。所以要**重新枚举**，不能复用旧句柄。

---

## 3. 本项目的刷机流程

```powershell
python fb_libusb.py flash loader-logfix.img system.apfs itn-exp.bin
```

内部五步：

| 步骤 | 动作 | 说明 |
|------|------|------|
| 1 | `download` loader（1.8 MB） | 如果当前已经是 `4EE0` 就跳过（loader 已在内存里） |
| 2 | `boot` → 等 `4EE0` 重新枚举 | ABL 只接受一次 `boot`（每次冷启动） |
| 3 | `oem ramdisk` | 告诉 loader "接下来下载的是系统卷" |
| 4 | `download` 系统卷（2.7 GB）+ payload（44 MB） | 26 MB/s，约 105 s |
| 5 | `oem run` | loader 起内核 |

其它命令：

| 命令 | 用途 |
|------|------|
| `fb_libusb.py devices` | 看当前是不是 `fastboot` 设备 |
| `fb_libusb.py getvar product` | `kona`=ABL，`xnuloader`=loader 在跑 |
| `fb_libusb.py log out.txt` | 取内核环形日志（**一次读完**） |
| `fb_libusb.py run payload.bin` | 只换 payload 重跑（系统卷已在内存里时可用，但受限于"一个会话只能 run 一次"） |
| `fb_libusb.py reboot` | `reboot-bootloader`，清掉 ABL 的"已 boot 过"状态 |

### 3.1 分片镜像（GitHub release 用）

GitHub 单个 release 资产上限 **2 GiB**，系统镜像是 2.55 GiB，所以发布时切成
`system.apfs.001` + `system.apfs.002`。

`fb_libusb.py` 接受**路径不存在但 `.001` 链存在**的情况：

```powershell
# 目录里只有 system.apfs.001 / .002，没有 system.apfs 也行
python fb_libusb.py flash loader-logfix.img system.apfs itn-exp.bin
```

内部机制：`resolve_image()` 发现 `system.apfs` 不存在就收集连续的 `.001/.002/...`，
包成 `ImageSource`；`download()` 只用到 `len(data)` 和 64 KiB 对齐切片，`ImageSource`
就在对应分片里 seek + read，一次只占一个 64 KiB 缓冲。

- **不需要合并**：不占额外 2.7 GB 磁盘，不产生第二份副本
- **不缺片不报错**：链断（有 `.001` 没 `.002`，或跳到 `.003`）直接拒绝，且在校验阶段就失败
- 单分片（只有 `.001`）也认；存在完整 `system.apfs` 时**优先用完整文件**，行为与老版本完全一致
- 传完会 `close()`，分片随即可以移动/删除

生成分片 + 校验清单：

```powershell
python tools/make_release.py --src <体验版目录> --out release --tag exp-v1
# [1/3] zip 1357 files -> ios-on-rmx3366-exp-v1.zip (34.5 MB)
# [2/3] split image: 2608.1 MB into 1900 MB parts
# [3/3] sha256 of 3 assets -> SHA256SUMS.txt
```

脚本幂等：已有分片总字节数与源文件一致就复用，不重写。

发布到 GitHub（建仓 + 建 release + 上传，可断点重跑）：

```powershell
python tools/publish_release.py --dir release --tag exp-v1 --notes docs/RELEASE_NOTES.md
```

**踩过的坑**：fine-grained PAT 调 `POST /user/repos` 会返回
`403 Resource not accessible by personal access token` —— fine-grained token 建新仓库需要
账号级 `Administration: write` + "All repositories"，多数人没开。要么先手工建空仓库
（token 只需 `Contents: Read and write`），要么用 classic token 勾 `repo`。

---

## 4. USB 层的坑（每条都真的发生过）

### 4.1 孤儿传输 = 之后全部超时

**机制**：主机发了一次读，读了半截就退出（例如脚本 `break`、管道被 `head` 关掉），
这个 bulk 传输留在 dwc3 控制器里。下一次读拿到的其实是上一次的剩余数据，
于是**每条回复都错位**，最终全部超时。

**特征**：`getvar` 能回 `OKAY` 但值是空的；`download` 卡在某个百分比；`oem stop` 无响应。

**主机侧能做什么**：`clear_halt`、`set_configuration`、libusb 的 port reset —— **全部无效**。
（都试过，写在 `fb_libusb.py` 的错误提示里。）

**只能靠**：
1. 客户端**绝不半途退出**（`read_stream()` 一次读到 `OKAY`/`FAIL` 为止）；
2. 设备侧 `USB->abort_xfer()` + 重新 arm 端点（官方 loader 有两处 abort，我们早期一次都没调）；
3. 重启（`reboot bootloader`）或拔插数据线。

**最容易踩的场景**：`fastboot oem log | head -50`——管道一关，主机就放弃读。
所以**永远不要把刷机/取日志命令接管道**。

### 4.2 `oem log` 之后不要接着刷机

`oem log` 是"staging + 一次性读完整个缓冲"。读完之后端点常常已经处于半坏状态。
正确姿势：**读完日志就准备重启**，不要在同一个会话里继续 `download`。

### 4.3 ABL 只接受一次 `boot`

冷启动后第一条 `boot` 有效；之后一律
`Failed to load/authenticate boot image: Load Error`。
`reboot-bootloader` 可以清掉，不需要断电。

### 4.4 一个 loader 会话只能 `oem run` 一次

`oem run` 之后内核在 core 4 上跑；它返回后 core 4 仍处于 on，
PSCI 的第二次 `CPU_ON` 返回 `-4`。要再跑只能 `reboot bootloader`。

### 4.5 下载大小写

```python
fb.cmd("download:%08x" % len(data))   # 小写
```

写成 `%08X` 会让 loader 解析成 0，然后它等一个永远不来的数据块。

### 4.6 打印机/读卡器冒充设备

`VID 22d9` 是 realme 的 MTP（Android 正常开机时的 USB 模式），不是 EDL、也不是 fastboot。
看到 `22d9:2769` 说明**手机在 Android 里**，或者 loader 根本没启动。

---

## 5. 驱动（Windows 侧）

libusb 需要设备绑定到 **WinUSB** 或 libusb 兼容驱动。

- 已经在用 Zadig 装过的机器：直接用，什么都不用做。
- 新机器：Zadig → `Options → List All Devices` → 选 `18d1` 那个设备 → `WinUSB` → `Replace Driver`。

体验版脚本的处理方式是**只提示、不强制**：

```
[1/5] Looking for the phone...
  Windows sees the phone but libusb cannot open it: ...
  This is the USB driver, not the phone.
  Press ENTER to skip this and continue, or type Y then ENTER to let this script try ...
```

- 直接回车 → 跳过，继续刷（设备其实可能只是模式不对）。
- 输入 `y` → 试装微软的 `winusb.inf`（best-effort，装不上就给 Zadig 的指引）。

另外脚本会区分两种"看不到设备"：

| 情况 | 含义 | 脚本行为 |
|------|------|---------|
| 有 `18d1:d00d` 但 libusb 打不开 | 驱动问题 | 提示装驱动，可跳过 |
| 有 `18d1:4ee0` | 已经在 loader 里（不是 fastboot） | 提示关机重进 fastboot |
| 什么都没有 | 手机不在 fastboot | 提示进 fastboot，不刷 |

---

## 6. 失败恢复手册

### 6.1 刷到一半失败了

1. **不要拔线**。
2. 重新跑一遍脚本（`flash` 是幂等的：重新 `download` + `boot`/`oem ramdisk` + `oem run`）。
3. 如果 `boot` 返回 Load Error → `fb_libusb.py reboot` 清状态再刷。

### 6.2 卡在 fastboot 不动

- 长按电源 10 s 强制断电 → 重新进 fastboot → 再刷。
- 若能进 Android：`adb reboot bootloader`，再从 fastboot 刷（这是最干净的恢复路径）。

### 6.3 loader 起来了但 `oem run` 失败

- 大概率是"这个会话已经 run 过"（PSCI -4）→ `reboot bootloader` 重来。
- 也可能是 payload 太大 / `PAYLOAD_BASE` 冲突：确认 payload ≤ 容器上限（44 MB 是安全的）。

### 6.4 日志里出现 `wifi: UNCLEAN PCIe DMA OWNERSHIP`

这不是刷机问题，是**上一次运行异常结束**。断电冷启动即可；然后去查"为什么会异常结束"
（最常见：`loader_return_after` 定时器、或 `launchd` 缺失导致 init 直接退出）。

---

## 7. 时序参考（这台机器实测）

| 阶段 | 耗时 |
|------|------|
| `download` loader（1.8 MB） | < 0.2 s |
| `boot` → `4EE0` 枚举 | 2–20 s（首次可能要 20 s，驱动加载慢） |
| `download` 系统卷（2.7 GB） | 100–110 s（26 MB/s） |
| `download` payload（44 MB） | 1.5–2 s |
| `oem run` → 桌面 | 60–120 s |
| **合计** | **约 2 分钟刷 + 1–2 分钟起** |
