# 硬件与常量（RMX3366 / kona）

> 这台机器是 **realme 大师探索版 RMX3366**，SoC 是 **Snapdragon 870 / SM8250-AC（kona）**。
> 参照项目跑在 **OnePlus 8**（同为 kona，但**不是同一块板子**），所以：
> **地址、GPIO、电源轨、传感器都必须按 RMX3366 核对，不能照抄。**
>
> 另一个容易犯的错：这台手机刷了第三方系统，`adb shell getprop ro.product.model`
> 会报 `PMA110 / OP61BDL1 / Android 17`。那是被改过的系统属性，
> **硬件真实型号仍是 RMX3366**。早期文档里出现的 "OPPO PMA110" 就是这么来的，已废弃。

---

## 1. SoC 与内存

| 项 | 值 | 备注 |
|----|----|------|
| SoC | Snapdragon 870（SM8250-AC） | kona 平台，与 OnePlus 8 同族 |
| CPU | 1× Cortex-A77 @3.2G + 3× A77 @2.42G + 4× A55 @1.8G | `bootcpu=4` 指 MPIDR `0x400`（A77 大核之一） |
| 物理内存 | 12 GB，但**分 3 段不连续** | `rivena.dts`：2–2.9 G / 3–6 G / **8–16 G（中间 2 GB 洞）** |
| 交给内核的内存 | **6 GB** | loader `MAX_MEM_SIZE = 0x180000000` |
| UEFI 报的最大连续块 | 8 GB（base `0x200000000`） | 这就是 8 GB 也拿不满的原因 |

## 2. 显示

| 项 | 值 |
|----|----|
| 面板 | AMOLED，90 Hz |
| 合成 | 软件 GL（`gl=1`），Adreno 650 只到 bring-up，没有合成路径 |
| 帧率参数 | `ca_fps=90 ca_vbl=1` |
| GPU zap 区（**本机真值**） | `0x8e21a000`（参照机型是 `0x8681a000`，抄了必挂） |

> GPU zap 地址是 bootloader 每次分配的，理论上每台/每次可能不同。
> 当前实现靠 cmdline `board_gpu_zap=` 人工给值。**正解是从 UEFI / 设备树里读。**

## 3. 电源轨（错一个就起不来）

| 子系统 | 参数 | 说明 |
|--------|------|------|
| Wi-Fi + BT 共享 | `wifi_rails=smpa6:950,smpa4:1800,smpa5:1900,smpc8:1350` | **四条都要**。即使 `wifi=0` 也不能删，否则蓝牙上电失败 → `bluetoothd` 死循环 → 发热卡死 |
| 蓝牙 LDO | `bt_ldo=ldoa16 bt_ldo_mv=3024` | 3024 mV 是实测值 |
| 音频 DSP | `adsp_mem=0x91b00000` | ADSP 固件/共享内存基址 |

## 4. 存储

| 项 | 值 |
|----|----|
| UFS | 3.1，内核只读（`ufs=2 ufs_write=0`） |
| 分区来源 | loader 的 `block_shared.part[]`；本机 UEFI **不给** `EFI_PARTITION_INFO_GUID` handle，所以 loader 自己解析 LBA1 的 GPT |
| 系统卷 | 2.7 GB APFS，从 USB 进内存后挂成根 |
| `/private/var` | 内存盘 HFS（`hk_data=2 hk_data_mb=1024`） |
| modem 固件 | 接在系统卷尾部 208,670,720 B（`modem.img`/`efs1`/`efs2`/`efsc`，4096 对齐），基址 `modem_fw_base=<APFS 块数>` |

## 5. 相机（未完成，素材已备）

| sensor | 用途 | sensormodule（从 Android `/odm/lib64/camera/` 提取） |
|--------|------|---------------------------------------------------|
| IMX766 | 主摄（广角） | `sunny_imx766.bin`（1.25 MB） |
| IMX615 | 前摄 | `qtech_imx615.bin`（239 KB） |
| IMX481 | 超广角 | `ofilm_imx481.bin`（302 KB） |
| OV02B | 微距 | `shine_ov02b.bin`（53 KB） |

另有 30 个 camera 相关配置文件（约 150 MB）。
`rivena.dts` 里有完整的相机硬件描述（6× CSIPHY、2× CCI、CSID/IFE），
**但没有对应的驱动代码**——这是相机移植要补的核心。

可用参照：

- `hk_camera.c`：POCO X5 Pro（redwood）用的，写死 S5KHM2SD + OV02B10 的 GPIO/I2C/电源。
- `instantnoodle_camera.c`：OnePlus 8 用的，写死 IMX586/481/471/GC2375。
  **IMX481 两边都有**，可以复用一部分。

## 6. 输入

| 项 | 说明 |
|----|------|
| 触摸 | S6SY792（真机 I2C 协议，上报格式与早期猜的不同） |
| 按键 | 音量±、电源。**由 loader 代读**，经共享内存 `buttons_shared_pa` 交给内核 |
| 马达 | `haptic=` 参数（当前被 cmdline 上限挤掉） |
| 手电筒 | `torch=3` |

## 7. loader / payload 的地址布局

| 常量 | 值 | 说明 |
|------|----|------|
| `PAYLOAD_BASE` | `0xA0000000` | payload 加载基址（编译期定义） |
| loader 链接基址 | `0xA1000000` | `lld-link /base:` |
| FD 文件 | `alioth-drivers.fd` | `FD_BASE=0x9FC00000`、`FD_SIZE=0x300000`、`UEFI_TARGET=rivena` |
| 内核 cmdline 上限 | **608 B** | 内核与 loader 都是；loader 先占 18 B，payload 只能用 589 B |
| `BOOT_LINE_LENGTH` | 608 | 想放宽必须**内核与 loader 同时改**（结构体布局要一致） |
| 看门狗 | loader `wdt_set_ms(60000)`；内核按 `hv_wdt_pet=1` 每 10 s 喂 | loader 会自动把 `hv_wdt_pet=1` 追加进 cmdline |
| 心跳 | 内核每 10 s `loader_live.heartbeat++`；loader 50 s 无变化判 HUNG | 这是"没有日志也能知道死没死"的机制 |

## 8. 设备树差异（一定要按本机核对）

| 项 | OnePlus 8（参照） | RMX3366（本机） |
|----|------------------|----------------|
| GPU zap 地址 | `0x8681a000` | **`0x8e21a000`** |
| 内存布局 | 连续 | **3 段不连续** |
| 扬声器功放 | NXP TFA9874 ×2 | AW882xx 路径 |
| 相机 sensor | IMX586 等 | IMX766/IMX615/IMX481/OV02B |
| `board=` | `instantnoodle` | 也用 `instantnoodle`（走同一套 kona 默认值，**但要逐项核对**） |

`board=instantnoodle` 是本项目默认使用的板级标识——它让内核走 OnePlus 8 的默认配置，
这也是为什么"很多默认值刚好能用、偶发某些功能不对"。真要完全正确，应该新增一个
`board=rmx3366` 分支，把本机的电源轨、GPIO、sensor 全部按 `rivena.dts` 填进去。

## 9. 从 Android 侧还能取到什么

| 数据 | 位置 | 用途 |
|------|------|------|
| sensormodule | `/odm/lib64/camera/` | 相机驱动参数 |
| Wi-Fi BDF | `/vendor/firmware/wlan/`（或 persist） | `wifi_bdf_native=1` 需要它 |
| 功放配置 | `/vendor/etc/aw882xx_acf.bin` | `sound=3/4` 的寄存器序列 |
| 设备树 | `/sys/firmware/devicetree/base` 或 boot 镜像里的 `rivena.dts` | 所有硬件地址的最终依据 |
| modem 固件 | `/vendor/firmware_mnt/image/` | 打包进系统卷尾部 |
