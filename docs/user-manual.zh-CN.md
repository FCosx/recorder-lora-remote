# 机器人数据记录器使用手册

[English](user-manual.md) | **简体中文**

此分支使用维护者预先准备的 **Lenovo / Ubuntu 24.04 / ROS 2 Jazzy**，录制保存到**内部 NVMe**。机器人经 Ethernet/Zenoh 发送话题。只有机器人需要安装桥，仅打开网页的电脑无需 ROS。录制后端、LoRa 配对及云端访问由维护者私下准备。

当前部分 UI 仍称 **Recordings on the Pi**，在此分支指 Lenovo 录制器。此仓库不能在空白电脑上安装私有后端。

## 首次使用

### 1. 确认记录器地址并接线

启动已经准备好的 Lenovo、路由器和交换机。把记录器、机器人和路由器 **LAN** 口接入同一交换机，需要时接入操作电脑。使用内部 NVMe，无需外接 SSD。电脑关机时先按电源键，操作系统启动后服务才会自启。

设置前先向维护者确认**有线 IP**，当前为 **192.168.1.102**。不确定时，在 Lenovo 自身终端运行，选择连接交换机的以太网地址，不要选 Wi-Fi：

```bash
ip -4 -brief address
```

地址不同时替换下文 `192.168.1.102`。机器人以太网通常用 DHCP，Wi-Fi 可保持连接。**先启动发布器并完成桥安装，再打开网页。**

### 2. 启动机器人的正常 ROS 程序

先启动平时使用的传感器和 ROS 发布器，再用**同一个普通 ROS 用户**运行安装器。安装器会从当前环境或可读取的运行中 ROS 节点自动识别版本和初始域。只加载 ROS 基础环境，不需要加载机器人的工作空间。本记录器支持标准 ROS 消息类型；自定义类型的话题仍可出现在列表中，但不属于支持范围。 保持机器人原有的 ROS 域；若无法识别所需环境，再按文末排查部分处理。

### 3. 一次安装，并自动检查

机器人需要已安装 ROS 2 **Humble 或 Jazzy**。缺少的依赖需要联网下载；预编译桥本身从记录器获取。以下命令在**机器人终端**运行，不要在安装命令前加 `sudo`：

```bash
curl -q --noproxy '*' -fL --retry 2 --connect-timeout 5 --max-time 60 \
  http://192.168.1.102:8080/setup/install_robot_bridge.sh \
  -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url http://192.168.1.102:8080
```

按提示输入**机器人的 sudo 密码**。安装器自动选择经过校验的 x86_64 或 ARM64 桥，不需要用户编译。它会显示识别到的 ROS 版本和域。ROS 版本无法唯一确定时会要求选择；无法识别唯一的域时使用 **0**，之后可在任一 UI 中修改。已有安装保留原来的配置和安装目录。

最后会集中检查以太网、记录器录制服务、单个修复版桥、助手和话题发现。出现 **FAIL** 时，按提示处理后再录制。仅提示没有话题的 **WARN**，可能只是发布器尚未启动。等待 **Setup complete**；若安装中断，解决报错后，在记录器空闲时重跑同一段命令。

桥会开机自动启动，等待有线网络，并在记录器可用后重新连接。**安装完成可关闭终端，不要再手动启动第二个桥。** 机器人的应用菜单会增加 **Robot Recorder** 入口；部分桌面也会显示桌面副本。安装时不会提前打开浏览器。

### 4. 打开录制网页

在机器人应用菜单中打开 **Robot Recorder**，或在同一交换机上的任意电脑浏览器输入：

**http://192.168.1.102:8080**

**Available topics** 下的 **Robot ROS domain（机器人 ROS 域）** 显示源端桥当前监听的域。记录器接收域固定为 **1**，无需在网页选择。请保留 `http://` 和 `:8080`。此 Lenovo 不假设已配置本地名称解析，请使用确认的有线地址。仅打开网页的电脑可将该地址加入书签，不需要安装软件。

## 日常录制

完成首次安装后，每次只需给套装和机器人通电、启动机器人的发布器，再从 Robot Recorder 入口或浏览器书签打开网页。日常本地录制不需要手动运行桥命令，也不依赖互联网。

1. 等待 **Ready to record（可以录制）**。确认 **Robot ROS domain** 与机器人的发布器一致；识别正确时无需修改。
2. 点击 **Refresh topics（刷新话题）**，勾选需要保存的话题。需要切包时，在 **Split MCAP files** 填写大小（MiB）、时长（秒）或两者；都留空则不切包，两项都填时先达到的条件触发切包。
3. 点击 **Begin recording（开始录制）**。计时器在记录器订阅到第一个所选话题后启动。已完成 bag 的时长按第一条至最后一条录入消息计算，因此可能稍有差异。
4. 点击 **Stop recording（停止录制）** 后等待收尾。缓存写入期间大小仍可能增加，请等到结束再断电。
5. 在 **Recordings on the Pi** 中，点击 **View topics** 查看大小、时长、总消息数、各话题消息数和平均 Hz。切分文件仍属于同一录制。**Download** 将 TAR 副本保存到正在使用浏览器的电脑；**Delete** 会永久删除记录器上的该录制。

本地列表每页显示 10 个录制，话题列表使用内部滚动条。打开页面或点击 **Refresh topics** 时，机器人端进行一次约 1 秒的带宽采样。**—** 表示没有可用估算，不代表零；勾选后显示合计。临时订阅不保存传感器数据，开始录制前必须关闭。估算值不保证所有消息都能录入。

### 修改机器人 ROS 域

记录器空闲时，在 **Available topics** 下输入发布器的域（**0–232**），点击 **Apply domain（应用域）**。等待 **Current: …** 显示确认值，再从刷新的列表选择话题。本地网页与 LoRa 网页共用这一设置，机器人会保存它，重启后继续使用；重跑安装器也会保留已保存的域。

此操作只改变桥监听哪个域，不会修改机器人的发布器，也不会改变记录器固定的接收域 **1**。录制中不能改域，改域未完成时也不能开始录制。误选了没有话题的域，可直接在同一位置改回，无需 SSH。若显示 **Robot connection unavailable**，请按下文检查桥服务；旧版机器人端需要在空闲时重跑第 3 步安装命令以更新。

v2 桥使用实时 Image/CompressedImage，保留 calibration/TF 历史。异常录制会显示简短警告，详情在 **View topics**。**Data loss detected** 表示已报告或确认丢失；**Possible data loss** 表示网络饱和等风险；**Robot connection unavailable** 表示原先已连接的机器人链路中断。没有警告也不等于源数据绝对完整。

录制保存在 Lenovo 内部 NVMe。关机前先停止录制、等待封包完成，再通过 Ubuntu 或维护者认可的 SSH 账号正常关机；写入时不要断电。后端使用的锁定 `recorder` 服务账号不是 Lenovo 的 SSH 登录账号，登录资料私下提供。

## 可选增强：LoRa 控制

需要远距离选择话题、开始/停止和查看状态时，按 [LoRa 远程控制说明](lora-remote.zh-CN.md) 设置。远端笔记本无需记录器 IP 或现场网络，但机器人到记录器的以太网/Zenoh 数据链路仍需运行。LoRa 不传传感器数据，也不下载 bag。本地录制可以独立使用。

## 云端上传（可选）

维护者配置好云端连接后，在 **Recordings on the Pi** 区域、**Refresh recordings** 旁操作：

- 初始为 **Manual upload（手动上传）**：在需要上传的录制条目上点击 **Upload to cloud**。
- 切换到 **Automatic upload（自动上传）** 并确认后，记录器空闲时自动上传已完成的录制，也包括以前保存的录制。
- **Stop uploads** 停止压缩、传输及排队任务，并切回手动模式。需要继续时，点击对应录制的 **Resume upload**；部分准备或校验可能重新执行。
- **Cloud connected** 表示记录器可以访问云端。云端不可达时，不能新建上传任务或切换模式；LoRa 连接正常不代表云端可达。
- MCAP 先无损压缩为带索引的 Zstandard MCAP，再上传。录制始终优先：开始录制前暂停压缩和传输，录制结束后可继续。
- 所有文件通过读回校验后才显示 **Uploaded to cloud**。原文件保留在记录器，由用户决定是否删除；压缩需要临时空间。

文件由记录器通过自己的互联网连接上传，LoRa 只传控制和状态。上传完成后，可按下节进入云端网页。需要使用 ROS 回放时，将 `metadata.yaml` 及其引用的全部 `.mcap` 分段保留在同一录制目录。

## 云端网页

在任何能上网的电脑打开 **https://154.8.234.96**。这台电脑无需接入记录器的交换机，也不需要安装 ROS、Zenoh 或 LoRa。上传时，记录器自身需要联网；本地录制可独立使用。

### 登录

1. 向项目维护者申请**个人云端账号**。登录资料私下提供，本手册不公布默认账号或密码，也不提供公开注册。
2. 打开网页并点击 **Sign in（登录）**。首次登录若要求修改密码，请设置至少 12 个字符的新密码，再重新登录。
3. 普通用户只能看到账号已获授权的记录器。云端网页账号与记录器、路由器及云服务商账号分别管理；申请权限或重置密码请联系维护者。

### 查看和下载

- 在 **Recording library（录制库）** 按录制名或记录器名称搜索。条目显示开始时间、压缩后大小、时长和消息数。
- **View topics（查看话题）** 显示话题名称、已录消息数、平均 Hz 和 ROS 类型。
- **Download bag（下载录制）** 将完整 TAR 包保存到当前使用浏览器的电脑。解压后，把 `metadata.yaml` 及其引用的全部 `.mcap` 分段保留在同一录制目录中。也可在 **View topics → Individual files** 中下载单个文件。
- **Preview data（预览数据）** 可选 **Single topic** 或 **Synchronized**（最多四话题）。选择话题和 **Image resolution**：**Fast** 最大 480×270，**HD** 最大 1280×720，保持比例，不放大小图。
- 点击 **Start preview** 先准备数据再播放完整时间轴；用 **Pause/Resume** 暂停/继续，拖动时间轴检查指定位置，同步面板一起更新。**Stop loading** 取消准备，**Retry preview** 重试中断的读取。
- 图像和点云是抽样预览副本；HD 是尺寸上限，不保证原始分辨率。原文件及下载不变。首次生成或长包仍可能等待/缓冲；渲染在用户浏览器运行，缓存有资源上限。
- 删除本地录制只影响本地副本。云端由管理员独立管理：**Delete** 移入 **Trash**，**Restore** 恢复，确认 **Delete permanently** 才释放空间；回收站仍占空间。自动删除保持关闭，尚不承诺独立 bag 备份。公用电脑用完请退出。

### 项目管理员

在 **Users（用户）** 中选择 **Researcher（普通研究用户）**，勾选允许访问的记录器，再点击 **Create account（创建账号）**。将生成的临时密码私下交给用户，由用户首次登录时修改。**Recorder access** 用于调整访问范围，**Reset password** 用于重置密码，**Disable** 用于停用账号。普通云端用户无需登录服务器或云服务商控制台。

### 云端问题排查

- **网页打不开**：检查互联网连接及完整的 `https://` 地址；仍无法访问时联系维护者。访问此云端网页无需额外安装网络客户端。
- **登录失败**：请维护者检查账号状态或重置密码。
- **找不到录制**：先确认记录器或 LoRa 页面已显示 **Uploaded to cloud**，再刷新云端列表，并请维护者核对账号的记录器权限。未完成的上传不会作为完整录制显示。

## 常见问题

### 无法访问记录器

在**无法连接的电脑上**运行：

```bash
ip -4 route get 192.168.1.102
curl -q --noproxy '*' -fsS --connect-timeout 3 --max-time 6   http://192.168.1.102:8080/api/status
```

路由应使用连接交换机的有线网口，请求应返回状态 JSON。若走 Wi-Fi，检查以太网网线和地址。若命令可以直连，但浏览器返回 **502**，在代理设置中对记录器已确认的有线 IP 添加直连例外。录制服务不可用时还要检查记录器电源和 NVMe 存储。本地网页没有登录验证，请仅在可信局域网使用。

### 查找记录器有线地址

在 Lenovo 运行 `ip -4 -brief address`，或查看路由器设备列表。选择连接交换机的网口（当前 `eno1`），不要沿用 Pi 的 `eth0`、主机名或保留地址。无法访问记录器控制台时请联系维护者。

### 机器人以太网与记录器不在同一网段

仅插上网线，不代表两台设备的固定 IP 在同一网段。机器人必须保留原地址时，请网络管理员分配一个记录器网段内未占用的地址及前缀，再临时追加，保留原地址：

```bash
read -rp '连接交换机的有线网口名: ' LAN_IF
read -rp '管理员分配的未占用 IPv4 地址/前缀: ' LAN_ADDR
sudo ip -4 addr add "$LAN_ADDR" dev "$LAN_IF"
ip -4 route get 192.168.1.102
```

不要随意猜地址。临时地址重启后失效，需要长期使用时请管理员配置。Wi-Fi 可以保持连接；桥会等到具备直达记录器的有线路由后启动。

### 一条命令集中检查

在**机器人**上，使用安装时的账号运行：

```bash
python3 -B ~/robot-recorder/tools/check_robot_setup.py
```

这是只读检查，录制中也可运行；不会重启服务、订阅传感器数据或估算带宽。如果安装在自定义目录，将 `~/robot-recorder` 替换为该目录。

### ROS 环境没有正确识别

使用运行机器人 ROS 程序的普通账号安装。root/容器中的程序，或在代码内部设置的域，可能无法自动读取。无法识别唯一的域时默认使用 **0**，可在任一 UI 的 **Robot ROS domain → Apply domain** 中修改。

若需指定 ROS 版本，在安装命令中填写实际安装的版本。以下示例明确选择 Humble 和源端域 5：

```bash
bash /tmp/install_robot_bridge.sh --pi-url http://192.168.1.102:8080 \
  --ros-distro humble --domain 5
```

Jazzy 使用 `--ros-distro jazzy`。不需要提供工作空间路径。`--domain` 设置桥监听的域，不会修改发布器的域。没有兼容预编译包时，安装器会停止并保留现有桥，请联系维护者提供经过测试的包。

### 检查、重启或停止机器人桥

在**机器人**上，使用安装时的同一用户检查：

```bash
systemctl --user status robot-recorder-source-bridge.service --no-pager
journalctl --user -u robot-recorder-source-bridge.service -n 30 --no-pager
```

仅在记录器空闲时，按需要选择下面的一条命令：

```bash
systemctl --user restart robot-recorder-source-bridge.service  # 恢复或重载
systemctl --user stop robot-recorder-source-bridge.service     # 主动断开
systemctl --user start robot-recorder-source-bridge.service    # 重新连接
```

三条是不同操作，检查状态不需要依次执行。直接杀死受管理的桥进程会触发自动重启；用 stop 停止后，下次开机仍会自动启动。

### 立即停止并关闭开机自启

不再使用记录器时，先结束正在进行的录制。在**机器人**上，使用安装桥时的同一账号运行：

```bash
systemctl --user disable --now robot-recorder-source-bridge.service
```

这条命令会立即停止桥，并关闭开机自启；安装文件和已保存的设置仍会保留。仅关闭浏览器或拔掉套装连接，不会关闭开机自启。

以后需要重新启动，并恢复开机自启时运行：

```bash
systemctl --user enable --now robot-recorder-source-bridge.service
```

无需重新安装。重新运行安装器也会启用开机自启。

### 记录器地址改变

机器人 ROS 域改变时，只需在任一 UI 中使用 **Apply domain**。若记录器有线 IP 改变，先停止录制，再在机器人终端更新保存的地址：

```bash
read -rp '记录器有线 IP: ' PI_IP
curl -q --noproxy '*' -fL --retry 2 --connect-timeout 5 --max-time 60 \
  "http://$PI_IP:8080/setup/install_robot_bridge.sh" -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url "http://$PI_IP:8080" --configure-only
```

此操作保留已保存的机器人域，重新配置并重启自动桥服务，无需编译。

### 找不到话题或消息数异常

确认机器人正在发布、UI 的 **Robot ROS domain** 与发布器一致；记录器接收域始终为 **1**。按上文检查桥服务后，点击 **Refresh topics**。网络需允许机器人连接记录器的 TCP **7447** 端口。在记录器运行 `systemctl is-active robot-recorder-bridge.service robot-recorder.service`，应返回两行 `active`。

在**机器人**运行 `pgrep -af '[z]enoh-bridge-ros2dds'`，应只看到一个路径包含 `zenoh-bridge-ros2dds-fixed` 的修复版桥。若有旧的手动桥或旧桥服务，先停止旧实例，不要并行运行 `/usr/bin/zenoh-bridge-ros2dds`。版本号相同不代表已包含修复。消息数仍异常时，请保留 bag 和日志交给维护者。

### 空 bag 或可疑消息数

在机器人运行集中自检，核对发布器和 ROS 域；保留录制和日志交给维护者。详情可能显示缓存丢失、链路中断或 UDP 接收缓冲溢出。包溢出是**可能丢消息的风险**，不是精确丢消息数；没有告警不代表完整接收了发布器全部数据。
