# iOS 体验版 exp-v1 — 真我 RMX3366（骁龙 870 / kona）

**中文界面、无定时返回、无内核文字日志。** 刷完只要不手动重启，想体验多久就多久。

> 状态：实验性。这是把 iOS 16.5 用户态跑在 Android 手机上的一次移植实验，**不能当日常机用**。
> 会改掉手机的引导流程；出问题时刷回 Android 需要 fastboot 和原厂固件。自己负责。

---

## 一、这个 release 里有什么

| 文件 | 大小 | 说明 |
|---|---|---|
| `ios-on-rmx3366-exp-v1.zip` | 34.5 MB | 全部脚本 + 内置 Python + pyusb + libusb DLL + 内核 payload + loader |
| `system.apfs.001` | 1900 MB | 系统镜像前半（**必须和 .002 一起下**） |
| `system.apfs.002` | 708 MB | 系统镜像后半 |
| `SHA256SUMS.txt` | 1 KB | 上面三个文件的 sha256 |

**为什么系统镜像是两个文件？** GitHub 单个 release 资产上限 2 GiB，而系统镜像是 2.55 GiB（2,734,755,840 字节）。
所以它被切成 `.001` + `.002` 两片。

**你不需要合并它们。** 刷机脚本会直接跨分片流式读取——不占额外 2.7 GB 磁盘，也不会多出一份镜像副本。
（如果你就是想合并，`copy /b system.apfs.001+system.apfs.002 system.apfs` 也行，脚本两种布局都认。）

---

## 二、刷机：三步

### 1) 下载

把 **4 个文件**下到同一个文件夹（`SHA256SUMS.txt` 可选但建议下）。

### 2) 解压

右键 `ios-on-rmx3366-exp-v1.zip` → 全部解压，得到一个 `ios-on-rmx3366-exp-v1` 文件夹。
把 `system.apfs.001` 和 `system.apfs.002` **移动进这个文件夹**（和 `刷机-体验版.bat` 放一起）。

```
ios-on-rmx3366-exp-v1\
    ├─ 刷机-体验版.bat          <- 双击这个
    ├─ runtime\                 <- 内置 Python 3.13，不用装任何东西
    ├─ site-packages\           <- pyusb
    ├─ libusb-1.0.dll
    ├─ fb_libusb.py
    ├─ loader-logfix.img
    ├─ itn-exp.bin
    ├─ system.apfs.001          <- 你放进来的
    ├─ system.apfs.002          <- 你放进来的
    └─ versions.json
```

### 3) 手机进 fastboot，双击 bat

1. 手机关机 → 同时按住 **音量下 + 电源** 进 fastboot（出现 realme logo / "fastboot" 字样）
2. 插 USB 线
3. 双击 `刷机-体验版.bat`，UAC 弹窗点"是"

脚本会自己做这些事，中途不用你管：

```
[0/5] 检查包是否完整（含分片大小校验，抓下载不全）
[1/5] 找手机（区分"没进 fastboot"和"驱动有问题"）
       -> 驱动有问题时只提示，按回车跳过也能继续刷；
          输入 y 才会调 Windows 自带的 WinUSB 驱动安装脚本
[2/5] 如果装了 usbipd，自动 unbind（否则 WSL 会抢设备）
[3/5] 等 3 秒让设备稳定
[4/5] 刷机：loader -> 2.7 GB 系统镜像 -> 内核 payload，约 2-4 分钟
[5/5] oem run 启动
```

**全程不要拔线。** 传完约 1-2 分钟出苹果 logo，再到桌面。

### 失败了怎么办

- 直接**重跑 bat 是安全的**，脚本不依赖上一次的状态
- 手机黑屏、拔插线没用 → 长按电源 10 秒强关，重进 fastboot
- 屏幕卡住不动但手机有反应 → 大概率是 loader 里的 `pci_diag_halt()` 故意停死，只能强关重来
- 刷坏了想回 Android → fastboot 刷原厂 `boot.img` / `super.img`，或进 recovery 恢复

---

## 三、这一版有什么

**能用**

- 中文界面（简体 / 繁体 / 英文，完整 `.lproj` + 完整 PingFang 36 字面，无方块字）
- 桌面、图标、设置、Safari、文件等系统 App 可点可用
- GPU 渲染 / Metal 合成，90 Hz（`ca_fps=90` + `ca_vbl=1`）
- 触摸、按键（音量上下 + 电源）
- WiFi（连上后能上网）
- 声音（扬声器、听筒）
- 蜂窝 + 数据 + 通话 —— **换卡实测可用**
- UFS 持久化、手电筒、蓝牙

**不能 / 不完整**

- 相机基本不可用
- 重启后 `/var` 在 RAM 里，**WiFi 密码和装过的 App 会丢**（`hk_data=2`，1024 MB tmpfs）
- 装 App：只能用已内置的 `.app`（往 system 镜像里加），没有 App Store 登录下载
- 休眠 / 长时间待机不稳定
- 没有 iCloud、没有推送、没有定位
- 单次 loader 会话只能 `oem run` 一次；第二次会 `PSCI error 4`

完整清单见仓库 `docs/FEATURES.md`，每个 bug 的根因和修法见 `docs/BUGS.md`。

---

## 四、校验下载是否完整

```cmd
certutil -hashfile system.apfs.001 SHA256
certutil -hashfile system.apfs.002 SHA256
certutil -hashfile ios-on-rmx3366-exp-v1.zip SHA256
```

和 `SHA256SUMS.txt` 里的值逐行对比。**不匹配就别刷**，重新下载。

脚本自己也会在 `[0/5]` 阶段核对分片总字节数，下载不全直接停下，不会给手机发任何东西。

---

## 五、硬件前提

- 真我 realme 大师探索版 **RMX3366**（骁龙 870 / kona）
- 系统属性被改过的第三方 ROM 不影响，硬件认 RMX3366
- Windows 10/11 + USB 线（要能传数据，不是纯充电线）
- **不要**在 WSL 里跑（usbipd 转发会让设备半接管，fastboot 协议卡死）

---

## 六、这个版本改了什么（相对上一版）

- 删掉 `loader_return_after=1800` 定时返回：不会再跑 30 分钟自动停
- 删掉 `-v`：不再有屏上滚动的内核文字日志，第一帧就是图形界面
- 精简 cmdline 到 585 字节（loader 上限 608，超了会丢 `modem_efs/service/secs`）
- 驱动检查从"强制"改成"提示 + 回车跳过"

---

源码、构建流程、每个坑的细节都在仓库文档里；这个 release 只是把"能刷的成品"打包好。
遇到问题请带 `[4/5]` 之后的完整输出开 issue。
