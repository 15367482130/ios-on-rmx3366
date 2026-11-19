# 构建链

> 目标：从源码到"能刷进手机的三件套"。三条线互相独立，可以单独重建：
> **内核**（改驱动才动）、**ramdisk + payload**（改 rc.jobs / 注入库才动）、
> **系统卷**（改 App / 字体 / 本地化才动）。
> loader 是第四条线，**很少动**，动了就要重新验证（见 §4）。

---

## 0. 依赖

| 组件 | 用途 | 备注 |
|------|------|------|
| theos（`/root/theos`） | 交叉编译 iOS 二进制的 clang + ldid + SDK | `toolchain/linux/iphone/bin`、`sdks/iPhoneOS16.5.sdk` |
| `xnu-deps` | 内核构建的依赖（XNU SDK、cctools、部分库） | `xnu-env.sh` 会把它加进 PATH |
| Docker 容器 `oneplus8-build` | 内核编译环境 | 见 §2 |
| Python 3 + `fontTools` | 字体校验（可选，诊断用） | `pip install --break-system-packages fonttools` |
| `7z`（p7zip） | 读写 APFS/DMG 镜像 | 列内容用 `7z l -slt` |

`xnu-env.sh` 定义了几个关键变量：

```bash
HACKIOS_ROOT=/root/work/itn-fpsbuild
XNU_SRC=$HACKIOS_ROOT/xnu-src/xnu-8796.121.2
XNU_SDK_PATH=$HACKIOS_ROOT/xnu-deps/sdk/iPhoneOS16.5.xnu.sdk
THEOS=$HOME/theos
```

---

## 1. 内核

内核不是"整棵树 make"，而是**在树的对象文件上增量编译 + 重链接**：
补丁源在 `tools/nf/cell/`（`*.c`、`cell_dt.cpp`）与 `overlay/`，最终镜像写进
`out/kernels/…` 并记在 `out/cell-kernel.txt`。

```bash
cd /root/work/itn-fpsbuild/tools/nf/cell
python3 build.py --check      # 只编译新增单元，快；用来验证语法
python3 build.py              # 完整编译 + 链接
```

几点必须知道：

1. **编译在容器里**（`oneplus8-build`）。宿主机上没有那套对象文件和头文件。
2. 有两个对象不在 git 里、也不是这里编的：`vfs_attrlist.o`、`ath11k-cell.o`。
   缺它们会链接失败，环境变量 `CELL_VFS_OBJ` / `CELL_ATH11K_OBJ` 可以指路径。
3. 我们的改动大多在 **overlay**（`tools/nf/cell/overlay/xnu/files/bsd/dev/`），
   也就是"用我们的文件盖掉树里的同名文件"——`hk_wifi.c`、`hk_adsp.c`、`hk_sound.c`、
   `hk_mic.c`、`hk_speaker.c` 这些都在里面。
4. 生成的内核就是 payload 的 `kernel` 条目（约 17 MB，Mach-O arm64）。

> **不要**为了改 cmdline 去重编内核——cmdline 是 payload 里的独立条目，改它不需要编译。

---

## 2. userland 与系统卷

`userland/build.sh` 是一份很长的脚本，做三件事：
编 ramdisk 里的用户态程序（`init`、`hkinstall`、各种 daemon/注入库）→ 组 `sysroot` →
`mkapfs` 打成系统卷。

**它在本项目里有几个坑，所以我们把"系统镜像"这一段单独抽出来了**
（`tools/build-system-cn.sh`），因为整份 `build.sh` 会卡在无关的 `metal_drv_test` 链接失败上。

```bash
bash tools/build-system-cn.sh      # 约 3.5 分钟 → userland/system.apfs
```

这个脚本做的、和上游 `build.sh` 不同的事（每一件都是修 bug 修出来的）：

| 动作 | 为什么 |
|------|--------|
| `cp -a sysroot/sbin/launchd.ios sysroot/sbin/launchd.darwin` | ramdisk 的 `/redwood/etc/rc` exec 的是 `.darwin` 这个名字（[BUGS B5](BUGS.md)） |
| 用 `/root/work/fonts/PingFang-full.ttc` 覆盖裁剪版 | 裁剪版只有 Regular/Semibold，图标名/Safari 走 Medium 就变方块（[BUGS D2](BUGS.md)） |
| `ln -sfn /redwood/lib/HakiosAudio.driver`、`HKAudio.driver` | 声音 HAL 插件路径 |
| `mkdir -p sysroot/System/Volumes/Darwin` | 内核/用户态约定的挂载点 |
| `python3 mkhighrate.py sysroot` | 给 189 个 App 的 `Info.plist` 加 `CADisableMinimumFrameDurationOnPhone=YES`，**丢了就退回 60 Hz** |
| `mkapfs.py -z -o system.apfs System=sysroot,manifest=…` | 打成 APFS（`-z` 压缩） |

**注意 `sysroot` 是 `cp -al`（硬链接）来的**：直接改文件会改到 `$IOS/rootfs` 本体。
要替换就 `rm` 再 `cp`。

### 系统卷 = APFS + 尾部固件

`modem.img` / `efs1` / `efs2` / `efsc` 以 4096 对齐**接在 APFS 后面**，
内核按 cmdline 的 `modem_fw_base=<LBA>` 去找。
所以**系统卷大小一变，`modem_fw_base` 必须同步改**（它等于 APFS 的块数）。

原始素材已丢失，只能从旧的系统卷里整段搬（相对布局不变，cell 驱动的相对偏移照旧成立）。

---

## 3. ramdisk 与 payload

ramdisk 是一份 APFS（26 MB），内容来自 `/root/work/itn-fpsbuild/rd-full`：

```
rd-full/
├── etc/rc.jobs          # init 在开机时按行执行的命令（每条一行，支持 sleep N）
├── bin/hkinstall        # 装第三方 App
├── redwood/             # 我们自己的用户态（init、daemon、注入库、LaunchDaemons）
├── sbin/                # launchd、init 等
└── var.skel/            # /private/var 的骨架（每次开机复制到内存盘）
```

重打 ramdisk + payload（**不动 2.7 GB 系统卷**）：

```bash
cd /root/work/itn-fpsbuild
python3 /root/work/instantnoodle-xnu/tools/apfs/mkapfs.py -z --plain fw \
        -o rd-exp.apfs 'hackios=rd-full,manifest=rd-full.manifest'
```

```powershell
python make_payload.py -o itn-exp.bin --from itn-cn4.bin --ramdisk rd-exp.apfs --cmdline "$(cat cmdline.txt)"
```

`make_payload.py` 的约束：

- 容器格式 XNUP：`"XNUP" | u32 size | {char name[16], u32 size, u32 reserved, data}`（16 字节对齐）。
- **`size` 从偏移 8 起算**（不是文件总长）——写错就设备不认。
- 条目顺序：`kernel`、`ramdisk`、`cmdline`；`cmdline` 放最后，因为它最常改。

---

## 4. loader（很少动，动之前先读这段）

loader 是一个 **UEFI 应用**（arm64，`/subsystem:efi_application`，入口 `efi_main`），
源码在 `/root/work/mi10ultra/xnuloader/loader.c`。它自己实现：

- fastboot 协议（`download` / `boot` / `oem ramdisk` / `oem run` / `oem log` / `oem stop` …）
- UFS 块设备 + **自己解析 GPT**（本机 UEFI 不给 `EFI_PARTITION_INFO_GUID` handle）
- 显示初始化、PSCI 启核、device tree 生成、共享内存邮箱（块设备/按键/电池）
- 心跳监视（50 s 无变化判 `THE KERNEL HUNG` 并把日志带回）

编译（要点：**Windows 目标**，不是 Linux ELF）：

```bash
clang --target=aarch64-unknown-windows -ffreestanding -fno-builtin \
      -fno-stack-protector -fshort-wchar -mgeneral-regs-only -O1 \
      -DPAYLOAD_BASE=0xA0000000ULL -c loader.c
lld-link /subsystem:efi_application /entry:efi_main /nodefaultlib \
      /base:0xA1000000 loader.obj /out:loader.efi
```

打包成能 `fastboot boot` 的镜像（**唯一可信配方**）：

```bash
python3 mkpayload.py loader.efi --usb -o payload.bin
python3 mkxnuimg.py --payload payload.bin \
        --fd /root/work/fd-archive/alioth-drivers.fd \
        --uefi-target rivena --fd-base 0x9FC00000 --fd-size 0x300000 \
        -o loader-logfix.img
```

**约束与坑**

| 事项 | 说明 |
|------|------|
| FD 文件 | 必须是 `alioth-drivers.fd`。`redwood-drivers.fd` 缺本机 USB 设备协议，4EE0 永不出现 |
| loader 体积 | 约 79,872 B 是安全上限附近；加打印很容易超出容器导致不启动 |
| `%p` | loader 的迷你 `print()` 不支持，用 `%x` |
| 验证方式 | 生成结果要能**逐字节复现**已知可用镜像（同一 `TimeDateStamp` 下 md5 相同） |
| 不要做的 | 用 `replace_loader_in_bootimg.py` 往 boot 镜像里"外科替换"——两条 bug，修完仍不启动 |

---

## 5. App（第三方）

```bash
# .app 目录或未加密的 .ipa → hkinstall 要的 ustar
python hkpack.py MyApp.app MyApp.tar

# 换掉 ramdisk 里的 rc.jobs 并重打 payload（不动系统卷）
bash tools/loader/hkadd_app.sh MyApp.tar itn-app.bin
```

`hkinstall` 的命令行是"一串步骤"：

```
hkinstall alarm 300 wait-net 120 fetch <ip> <port> /<name> <sha256> /var/tmp/<name> \
          unpack /var/tmp/<name> /var/tmp/hk-unpack \
          install /var/tmp/hk-unpack claim system state <bundle-id>
```

- `alarm` / `wait-net`：超时与等网络（`/private/var` 是内存，Wi-Fi 每次都要重连）。
- `fetch`：HTTP/1.0 GET，**校验 SHA256**，每 32 MB 报一次进度，卡住会重试 3 次。
- `unpack`：解 ustar。
- `install`：`claim system` 是必须的（否则 FrontBoard 拒绝启动）。
- `state`：把安装结果写日志。

---

## 6. 一次改动的"最小重编"对照表

| 你改了什么 | 需要重做什么 | 刷机传多少 |
|-----------|-------------|-----------|
| cmdline（参数） | `make_payload.py` | 44 MB payload（+2.7 GB 系统卷，因为 flash 一次传全部） |
| `rc.jobs` / 注入库 / `hkinstall` | ramdisk + payload | 同上 |
| 系统卷内容（App/字体/`.lproj`） | `build-system-cn.sh` + 追加固件 + payload | 全量 |
| 内核驱动 | `tools/nf/cell/build.py`（容器） + payload | 全量 |
| loader | Windows 交叉编译 + `mkpayload` + `mkxnuimg` | 全量（loader 也要重刷） |

> 这就是为什么"热安装"（不刷机装 App）是当前最值得做的改进：现在装一个 App 要走全量刷机。
