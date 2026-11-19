# Bug 账本：现象 → 根因 → 修法 → 坑

> 这里的每一条都是**真机上复现过**的。写法固定：先写「你看到什么」，再写「真正的原因」，
> 然后「怎么修的」，最后「下次别再踩」。行末的 §n 指向 [`HISTORY.md`](HISTORY.md) 的对应章节。
>
> 顺序大致按「引导链从下往上」：USB → loader → 内核 → 驱动 → userland → 镜像内容。

---

## A. USB 与刷机

### A1. 一切 `fastboot` 命令卡死、拔插也救不回来

**现象**：`fastboot devices` 还能看到设备，但 `download` / `getvar` / `oem stop` 全部超时；
反复重试越来越糟；WSL 里 `usbipd attach` 之后尤其容易触发。

**根因（两层）**
1. **`usbipd attach` 会触发设备事件风暴**：旧 loader 每收到一个 device-state-change 就打印一次且
   不等待 USB 完成，主机端看到的是"循环跑码"。WSL 的 usbip 转发层把设备置于半接管状态，
   `fastboot.exe` 的协议直接卡死。
2. **孤儿传输留在 dwc3**：主机半途放弃一次读（例如只读到一半就退出），这个传输不会被取消，
   后续每条回复都错位一格，最终全部超时。**设备侧不 abort，主机侧做什么都没用**
   （`clear_halt` / `set_configuration` / `libusb` 的 port reset 全部试过，无效）。

**修法**
- 不用 WSL 碰 USB：**刷机全部走纯 Windows 的 libusb**（`tools/fb_libusb.py`）。
- loader 侧：官方 `instantnoodle-xnu/xnuloader/loader.c` 在 `usb_wait()` 超时和
  `UsbDeviceEventDeviceStateChange` 两处调用 `USB->abort_xfer()`；我们早期版本一次都没调。
- 客户端侧：`read_stream()` **必须一次读完**，绝不半途退出（这是自造孤儿传输的唯一方式）。

**坑**
- 加了 `abort_xfer` 也不够：abort 之后端点没有重新 arm，下一次传输仍可能失败
  （§75）。所以"修 abort"这条线只做了诊断用镜像，**正式方案是客户端不制造孤儿传输 + 出问题就重启**。
- **读 `oem log` 是最容易制造孤儿传输的操作**。要读就连读完（`fb_libusb.py log` 已经这么做）。

### A2. `fastboot boot` 报 `Failed to load/authenticate boot image: Load Error`

**现象**：第一次能刷，第二次一定失败，断电重启后又好了。

**根因**：**ABL 每次冷启动只接受一次 `boot`**。第一次 `boot` 之后（无论成功与否），
后续 `boot` 都返回 Load Error。这不是镜像坏了、也不是签名问题。

**修法**：`reboot-bootloader`（软重启到 bootloader）就能清掉这个状态，不需要人工断电。

**坑**：如果内核已经卡死，`oem stop` 不会响应（内核不在了），只能硬断电；
`--force-boot` 也绕不过 `download` 阶段。

### A3. 把内核塞进 boot 镜像 → 永远起不来

**现象**：用"外科手术"把 loader 换成新版本、内核留在 boot 镜像里，刷完不启动。

**根因**：`fastboot boot` 只能送 **1.8 MB 的 loader-only 镜像**（loader 是 UEFI app，
由 ABL 当作 boot image 加载）。44 MB 的 payload 必须走 `oem ramdisk` + `download`。

**修法**：放弃"改 boot 镜像"这条路，改用官方配方：
`mkpayload.py`（loader.efi + `--usb`）+ `mkxnuimg.py`（FD=`alioth-drivers.fd`、`UEFI_TARGET=rivena`、
`FD_BASE=0x9FC00000`、`FD_SIZE=0x300000`）。

**坑（我们真的踩了）**
- `replace_loader_in_bootimg.py` 第一版用 **zlib 流（`78 9c`）而不是 gzip**，第二版按
  `kernel_size` 切片把 DTB 截掉了 2949 字节。**连"没改 loader"的重打包都起不来**，
  说明问题在打包器而不在 loader。
- 用错 FD 文件（`redwood-drivers.fd` 而不是 `alioth-drivers.fd`）→ 设备**永远不枚举成 4EE0**，
  因为那里面没有这台机器的 USB 设备协议。
- 唯一可信的验证方式：**逐字节复现**一个已知可用的镜像（当时 md5 `76a26f43c08d…`）。

### A4. `oem stop` 之后内核还在跑

**现象**：想结束 iOS 运行取日志，`oem stop` 返回 OKAY 但机器没反应。

**根因**：`oem stop` 是靠 loader 给内核设一个"该退了"的标志 + 内核轮询到才退。
内核如果已经卡死（或还没跑到轮询点），标志没人看。

**修法**：靠 `loader_return_after=<秒>` 让内核**自己**到点返回（这也是后来
"30 分钟自动卡死"的元凶，见 C1）；或者直接断电。

---

## B. loader 与启动参数

### B1. 一个 loader 会话只能 `oem run` 一次（PSCI `-4`）

**现象**：
```
the kernel will run on core 400 (this is core 0)
jumping to 20349f4a8
core 400: the firmware answers 18446744073709551612 to the request to start it   ← -4
core 400 did not start: PSCI error 4
```
内核根本没跳。

**根因**：内核在 core 4（MPIDR 0x400）上跑完返回后，**这个核仍然是「开」的**。
Qualcomm 的 PSCI 对第二次 `CPU_ON(0x400)` 一律回 `-4 INVALID_PARAMETERS`。
不是镜像坏了，是 **loader 会话状态**。

**修法**
- 正解：`reboot bootloader`，重新 `boot` loader，一切重来（2 分钟）。
- 应急：把 cmdline 的 `bootcpu=4` 改成 `bootcpu=0`（loader 自己就在 MPIDR 0 上），
  走 loader 的**本地跳转**路径，完全不碰 PSCI。工具：`tools/bootargs_bootcpu.py`。
  代价：core 0 是 silver 小核，比 core 4 慢约 2.5 倍。

**坑**：别在同一个会话里连点两次 `oem run`。

### B2. cmdline 被静默截断，参数从中间被切开

**现象**：基带能注册，但 IMS PDN 反复掉（`PDP_FAILED_EVENT`）；查日志发现精心调的
modem 参数"像是没生效"。

**根因**：内核 `boot_args.CommandLine` 是 **`char[608]`**（`pexpert/pexpert/arm64/boot.h:26`），
loader 也是同样的 608。loader 先写 `debug=0x8 ` + `rd=md0 `（**18 字节**），
再拷贝 payload 的 cmdline，到第 607 字节就停——**从参数名中间切开**。

实测（loader 打印的最终 cmdline）：
```
... modem=5 cell=1 cell_dcm=1 modem_fw_base=606575 modem_quiet=3 modem_chans=139
    modem_bringup=1 modem_tf          ← 到这里断掉
```
`modem_tftp=1 / modem_blk=1024 / modem_efs=1 / modem_service=1 / modem_secs=120` **全部丢失**，
所以内核用的其实是这些参数的默认值。

**修法**：把 payload cmdline 压到 **589 字节**以内（= 607 − 18），并且**按重要性排序**，
把真正必需的放前面。`tools/bootargs_drop.py in.bin out.bin <token>` 可以整条删除一个参数
（不是设成 0——有些参数只看"在不在"）。

**坑**
- 这个 bug 极难发现：**没有任何报错**，loader 打印的也是截断后的串。
- `-v` 曾经排在最后，所以"我们以为开了 verbose、其实早被切掉"——反过来也解释了
  为什么有时候屏幕上有日志、有时候没有。

### B3. 运行 30 分钟必卡死（用户："用着用着就黑屏，拔插线也没用"）

**现象**：开机后大约 30 分钟，画面冻住/黑屏，点什么都没反应，拔插数据线无效。

**根因**：cmdline 里有 `loader_return_after=1800`。内核在 `EARLY_BOOT` 阶段用
`thread_call_enter_delayed` 挂了定时器，1800 秒墙钟到点就**主动把控制权交还 loader**：

```
--- loader_return_after expired ---
hk_var_save_on_return() → hk_adreno_stop() → hk_wifi_stop()
→ hk_slpi_boot_stop()  → hk_adsp_stop()   → loader_jump(0,0)
```

**从此屏幕没有任何人再画**。而且如果 loader 在 `hc_take_back()`（收回 UFS 控制器）卡住，
30 秒后 Qualcomm hypervisor 看门狗咬合（`WDT_BITE_MS = 30000`），整机断电。

**修法**：**把这条参数整条删掉**（不是设 `0000`——有些默认值只看"参数在不在"，
比如 `mdp_shots` 在"有 loader_return_after"时默认 2000 ms，会每 2 秒 CPU 截帧、
每次拖慢 presenter 10–25 ms）。

**删掉不损失诊断能力**：loader 仍在 core 0 盯 `loader_live.heartbeat`（内核每 10 s 加一，
50 s 不变判 `THE KERNEL HUNG` 并带回日志），hypervisor 看门狗仍在（loader 起内核前
`wdt_set_ms(60000)`，之后由内核按 `hv_wdt_pet=1` 每 10 s 用 SMC 喂）。

**坑**：这个参数是"测试用"的——它存在的意义是让无人值守的测试跑一会儿自己回来。
把它留在给用户用的镜像里，就等于给系统装了个 30 分钟自杀定时器。

### B4. 系统"黑屏停住"且拔插无效：`pci_diag_halt()`

**现象**：不是卡在 UI，而是**整个系统早就结束了**：屏幕黑、什么都不响应，
但 loader 的 USB 还能应答。

**根因**：`bsd/dev/hk_wifi.c:364` 的
```c
__attribute__((noreturn)) static void pci_diag_halt(void)
{
    ... "wifi: UNCLEAN PCIe DMA OWNERSHIP; loader return halted, cold recovery required\n" ...
}
```
运行结束时如果 Wi-Fi 的 DMA 归属不确定，**故意不返回 loader**——避免把网卡还在 DMA 写的
内存交给下一个内核。所以这是**设计行为**，不是 hang。

**修法**：不需要修。它的意思是"这次运行异常结束，需要冷启动"。真正要修的是**让它异常结束的原因**
（例如下面 B5 的 `launchd` 缺失）。

### B5. 系统根本没进 UI：`launchd.darwin: No such file or directory`

**现象**：刷完开机，屏幕停住；日志（loader 带回来的）结尾是：
```
=== /redwood/etc/rc ===
$ exec /sbin/launchd.darwin
/sbin/launchd.darwin: No such file or directory
=== init: done ===
```

**根因**：userland 的 `build.sh` 把 `sbin/launchd` 改名成 `sbin/launchd.ios`（参照项目的命名），
而 ramdisk 的 `/redwood/etc/rc` 还在 exec 旧名字 `.darwin`。
手机之前能跑的那份镜像里 `sbin/launchd.darwin` 是一个 **525,088 字节的实体文件**；
我们重建系统卷时把它丢了。

**怎么发现的**：`7z l -slt` 对比"手机跑过的旧镜像"和"新镜像"的条目，
**旧有新没有的只有 1 条**——就是这个文件。于是"只丢一个文件，系统整个起不来"。

**修法**：构建脚本里 `cp -a sysroot/sbin/launchd.ios sysroot/sbin/launchd.darwin`。
用**实体拷贝**而不是符号链接，保持与已知可用镜像一致（先试过 `ln -sfn`，镜像里是 12 字节链接，
虽然理论上也能解析，但没必要冒这个险）。

**坑**：`sysroot` 是 `cp -al`（硬链接）来的，**直接覆盖会改到 `rootfs` 本体**。
要 `rm` 再 `cp`。

---

## C. 内核与驱动

### C1. 内核一碰 PMIC 就把 loader 的 USB 弄死

**现象**：内核里加了按键/充电读取，读一次 PMIC，loader 的 USB 立刻失效，
只能断电重启。复现 5 次（连"只读"也死）。

**根因**：内核和 loader 是**同一个 EE**（设备树 `qcom,ee=<0>`），
SPMI 仲裁器只有一个，谁抢到就是谁的；内核拿了不还，loader 的 I2C/SPMI 访问全部超时。

**修法**：**内核侧永远不要碰 PMIC / SPMI 仲裁器**。按键由 **loader 代读**，
通过共享内存（`buttons_shared_pa`）交给内核。电源键也是同理。

### C2. `buttons=1` 引入系统性崩溃

**现象**：开了 `buttons=1`，系统随机崩；关掉就正常。

**根因**：内核自己读 PMIC（见 C1），触发仲裁器冲突。

**修法**：改成 `buttons_volup_vin=1 buttons_voldown_pullup=1`，按键数据由 loader 写进
共享页，内核只读共享页。§28 之后按键一直稳定。

### C3. GPU zap 内存地址错，bring-up 第 21 步失败

**现象**：Adreno 初始化到第 21 步 `zap` 认证失败，3D core 不接命令。

**根因**：地址是**硬编码**的，而且抄的是参照机型（OnePlus 8）的值 `0x8681a000`；
本机真值是 **`0x8e21a000`**（bootloader 每台分配的 zap shader 区域不同）。

**修法**：二进制 patch 一个常量。patch 后 21 步全过、zap 认证通过、3D core 接受命令。

**坑**：**这个地址每台机器/每次冷启动可能不同**，正确做法是从 UEFI 或设备树里读，
而不是硬编码。当前实现仍然依赖 `board_gpu_zap=` 这个 cmdline 参数人工给值。

### C4. 帧率只有 10 几帧（"卡"）

**现象**：桌面能显示，但动画一卡一卡的。

**根因（我们走了很久的弯路）**：一开始以为是 `anim_max` / `dl_max` / `caenv` 之类的旧框架补丁，
全部无效。真正的官方做法在 **userland**：
`ca_fps_start()` / `ca_ideal_rate()` + backboardd 自动 `CA_FORCE_TIMER`。

**修法**：照官方 userland 重建 ramdisk，cmdline 给 `ca_fps=90 ca_vbl=1`。

**坑**：**这是"必须按参照项目整套移植"的典型例子**——只抄内核侧一个函数没有任何用。
另外：合成仍然是软件 GL，所以"帧率上限"和"实际帧率"是两件事。

### C5. 触摸点了没反应

**根因**：S6SY792 的真机协议与我们早期用的协议不同（上报格式/中断方式）。
**修法**：按真机 I2C 协议重写上报路径（§26），上机验证多点可用。

### C6. Wi-Fi 起不来 / 起来了但没网

**根因（三个独立原因叠在一起）**
1. **BDF 文件**：必须用**本机原生 BDF**（`wifi_bdf_native=1`），通用 BDF 不匹配射频校准。
2. **电源轨**：`wifi_rails=smpa6:950,smpa4:1800,smpa5:1900,smpc8:1350`，**四条都要**，
   少一条或电压错一点就起不来。
3. **`wifi=0` 时以为"关掉就行"**：不行——蓝牙和它共享轨（见 C8）。

### C7. 蓝牙开关灰色

**根因**：基带调试期把 `bt=0` 关了，后来忘了开。
**修法**：`bt=1 bt_ldo=ldoa16 bt_ldo_mv=3024`。

### C8. 蓝牙一开就发热、最后卡死

**现象**：开蓝牙后手机发烫，几分钟后系统卡死。

**根因**：蓝牙和 Wi-Fi **共享电源轨**（`wifi_rails` 里的 smpa4/smpa5/smpc8）。
当时为了排查 Wi-Fi 把 `wifi=0` 且删了 `wifi_rails` → 蓝牙上电失败 →
`bluetoothd` 无限制重试 → CPU 满载发热 → 卡死。

**修法**：即使 `wifi=0` 也**保留 `wifi_rails`**。三者共存配置见 §64。

### C9. 基带能注册但上不了网

**根因（两层）**
1. **IMS PDN 反复掉**：缺 `cell_dcm=1`（TLV 0x12 相关）。加上后稳定注册。
2. **只有 IPv6**：当时那张卡是 **IPv6-only PDN**，而官方 `net_test dhcp en1` 只会 IPv4 DHCP
   → `waitaddr` 超时 → Safari 没网。

**修法**：`cell_dcm=1` 解决注册；IPv6 需要给 `net_test` 加 SLAAC（ConfigMethod=Automatic）
或静态配 IPv6（还没做）。**换卡后数据+通话实测正常**。

### C10. 内存 6 GB → 8 GB 失败

**根因（三处）**
1. loader `MAX_MEM_SIZE = 0x180000000`（6 GB），只把 6 GB 交给内核。
2. 内核启动页表 `BOOTSTRAP_TABLE_SIZE = ARM_PGBYTES*20`（4K 页，每 GB 两套映射各 1 个 L2 页），
   8 GB 需要 18 页（勉强通过），12 GB 需要 26 页（`DEVELOPMENT` 下直接 panic）。
3. **真机物理内存不连续**：`rivena.dts` 里是 3 段（2–2.9 G / 3–6 G / 8–16 G），6–8 G 有 2 GB 洞。
   UEFI 报的最大连续块只有 8 GB，所以"把宏改成 12 GB"根本拿不到。

**修法（阶段 A）**：改两处（loader 宏 + 页表 20→24），重编 loader 与内核。
**结果：失败**——设备停在 fastboot 坏状态，需要断电 + 从 Android `adb reboot bootloader` 恢复。
**教训**：改内核 + loader 的验证成本极高（一次失败 = 十几分钟 + 可能丢状态），
要么一次改对、要么先在 QEMU 里验证。12 GB 需要"多 bank 离散物理内存"支持（移植级）。

### C11. 相机打不开

**根因**：内核里只有两套相机驱动，都是别机型的：
`hk_camera.c`（POCO X5 Pro / redwood：S5KHM2SD + OV02B10）、
`instantnoodle_camera.c`（OnePlus 8：IMX586/481/471/GC2375）。
RMX3366 是 **IMX766 + IMX615 + IMX481 + OV02B**，两套都不是。`board=instantnoodle` 会走一加 8 路径，
`cam=5` 必然失败。

**已做**：从 Android `/odm/lib64/camera/` 拉到 4 个 sensormodule（V2.0.0，与 OnePlus 同格式）
+ 30 个配置文件（150 MB）。用 `camsensor.py` 试解析：OV02B 能读出 slave/id，
但生成 tab 报 `not enough values to unpack (expected 3, got 2)`（真我 V2 的 power 序列只有 2 字段），
另外三个报 `KeyError: 0`（resolution 结构差异）。

**还差**：适配 `camsensor.py` → 从 `rivena.dts` 提 CCI 地址/GPIO/MCLK/电源轨/CSIPHY →
写真机驱动（或参数化现有驱动）→ `cam=5` 调试预览。

---

## D. 系统镜像与 app

### D1. 界面全英文，改偏好完全没用

**现象**：`AppleLanguages=(zh-Hans-CN,...)`、`AppleLocale=zh_CN` 全部正确
（连 `NSLocale.currentLocale` 都对），但 SpringBoard 就是英文，图标名也是英文。

**根因**：`ios165/select-system.py` 文件头自己写着：
> the empty `LANGUAGE.lproj` directories of the bundles whose strings are in one `.loctable`
> file for all languages: **they are how CoreFoundation knows which languages a bundle has**,
> and without them every string comes out as its key.

而 `KEEP_LANG = ('en','Base','English','en_US','en_GB')` 把这些**空目录**连文件一起裁了。
于是 CoreFoundation 认为每个 bundle "只会英文"，`SpringBoard.loctable` 里 1.1 MB 的中文
永远不会被查。

**修法**：`KEEP_LANG` 加 `zh_CN/zh_HK/zh_TW/zh-Hans/zh-Hant` → 重新生成清单
（43,751 文件 / 2,892 MB）→ **只增量抽取新增的 521 个文件**（+11.3 MB），不重抽 2.9 GB。

**坑**：`private/var/staged_system_apps` 与 `Applications` 同名，manifest 会把它映射到
`Applications/`；补空目录时**不能**预先建 `Applications/Stocks.app` 之类的空目录，
否则 `mv` 报 `Directory not empty`（要先 `rm -rf` 那 32 个纯空目录）。

### D2. 中文生效了，但图标名和 Safari 是方块

**现象**：设置里的字正常中文，但**图标下面空心方块**，Safari 一部分是"方块+问号"。

**根因**：镜像里的 `PingFang.ttc` 是**裁剪版**：`unpack.sh` 调
`font_trim.py faces ... '^\.?PingFang(SC|TC|HK)-(Regular|Semibold)$'`，
把 77.8 MB / **36 字面**裁成 26.9 MB / **12 字面**（只留 Regular + Semibold）。
用 fontTools 核对：汉字覆盖 22/22 完整，**缺的是字重**——正文 Regular 正常，
图标名/Safari 界面走 **Medium**，找不到字面就落 `.notdef`。

**修法**：换回 Apple 原始 `PingFang.ttc`（77,871,956 B，36 字面），
从 `rootfs.dmg` 直接抽：`7z e rootfs.dmg System/Library/Fonts/LanguageSupport/PingFang.ttc`。

**坑**：`sysroot` 是硬链接，必须 `rm` 再 `cp`（否则改到 rootfs 本体，
下次构建会"莫名其妙带着 77 MB 的字体"）。

### D3. 装好的 App 图标在，点了没反应

**根因**：`hkinstall` 的 `unpack`+`install` 路径**不写** `SignerIdentity` /
`SignerOrganization` / `SignatureVersion`，LaunchServices 把它登记成"普通用户 App"，
FrontBoard 拒绝 spawn。而 `.ipa` 路径默认 `claim_signer=true` + `system_registration=true`。

**修法**：`install` 之前加 `claim system`。之后图标出现、点击能起、能画、能写容器。

**坑**：日志里只有一句 `FrontBoard refuse to start`，很容易以为是容器权限问题。

### D4. 重建系统卷后"少了一个文件"，系统起不来

见 B5。**通用教训**：每次重建系统卷，都要拿 `7z l -slt` 跟"上一个能用的镜像"做
**双向差集**：既看"新增了什么"，也看"少了什么"。我们就是靠这个在几百条差异里
一眼看到唯一缺失的那一个文件。

---

## E. 工具链与元问题

### E1. 反复找不到"到底谁改坏了"

**现象**：同一个镜像，早上能起、晚上不能起；改了很多处，不知道是哪一处。

**元问题**：这个项目经过多次转手，产物众多（`itn-*.bin` 几十个、`loader-*.img` 十几个），
很容易**重复编译/重复下载**，或者在错误的基线上继续。

**做法（后来定成规矩）**
1. 动手前先查"这件事是不是已经做过"：`outputs/` 里的同名产物、构建日志、
   交接文档对应章节、上游源码树、`git log -S`。
2. 每次只改**一个变量**，并且**保留一个已知可用的基线镜像**（本项目是 `loader-logfix.img`）。
3. 镜像的打包必须**可逐字节复现**——否则"改了没变"和"没改"分不清。

### E2. `make_payload` 的长度字段搞错

**现象**：拼出来的 payload 设备不认。

**根因**：XNUP 容器的 `size` 字段**从偏移 8 起算**，不是文件总长。多算 8 字节 → loader 解析错位。

**修法**：`struct.pack_into("<II", out, 0, 0x50554E58, len(out) - 8)`。

### E3. 用 `%p` 打印指针，loader 里不支持

**现象**：加了一行调试打印，loader 编译能过但输出乱。

**根因**：loader 的 `print()` 是自实现的迷你格式化，不支持 `%p`。

**修法**：改用 `%x` 并自己 cast 成 `uint64_t`。

### E4. 加了调试打印，loader 体积超出容器

**现象**：loader 从 79,872 B 涨到 80,384 B 之后，刷进去不启动。

**根因**：boot 镜像里给 loader 留的空间是固定的（对齐后的 slot），超出就覆盖后面的内容。

**修法**：精简打印、`-O1`，把体积压回 79,872 B。**每次改 loader 都要看体积**。

### E5. "改完还是老样子"——其实读到的是缓存/旧文件

**教训集合**
- `7z` 列镜像内容是**惰性**的：`-slt` 输出要先落盘再 grep，直接管道会被截断。
- WSL 里 `/mnt/c` 上的大文件（2.7 GB）**不要用 `cp` 反复搬**，慢且容易中断；
  在 WSL 原生盘做完再一次性拷出来。
- 内核日志是**环形缓冲**，读两次拿到的是不同窗口；要看"从开机到现在的完整序列"，
  必须在运行结束后一次性 `oem log`。
