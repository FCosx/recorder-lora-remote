# 机器人数据记录器使用手册

[English](user-manual.md) | **简体中文**

本手册适用于维护者已配置好的**树莓派、路由器和交换机套装**。机器人发布 ROS 2 话题，树莓派保存 MCAP 文件，浏览器负责选择话题和控制录制。带屏幕的机器人主机可以直接打开网页，也可以另接操作笔记本。

只有**发布 ROS 话题的机器人主机**需要安装下述桥。仅用于打开网页的电脑不需要安装 ROS 或 Zenoh。树莓派的录制服务、接收端桥及可选 LoRa 服务已由维护者准备好。

## 首次使用

### 1. 连接套装

给路由器、交换机和树莓派通电。将路由器的 **LAN 口**、树莓派和机器人接到同一交换机；使用操作笔记本时，也将它接入交换机。等待树莓派启动完成。

配套路由器已为树莓派的有线网口保留 **`192.168.1.182`**。使用这套设备时，通常无需查找 IP 或登录树莓派。机器人以太网应采用自动获取地址（DHCP），已有的 Wi-Fi 可以保持连接。若机器人必须保留原有的固定有线地址，请先看文末排查，不要直接覆盖原配置。

**先完成桥的安装并启动机器人的话题，再打开录制网页。** 更换路由器或套装地址后，请先按文末“查找树莓派有线地址”查询，并替换命令中的 `192.168.1.182`。

### 2. 在机器人上安装桥（只需一次）

在**机器人终端**，使用日常运行 ROS 的普通用户执行。机器人需要已有 ROS 2 **Humble 或 Jazzy**，首次安装还需连接互联网。若使用自定义 ROS 工作空间，请先在这个终端加载平时使用的工作空间环境。

```bash
curl -q --noproxy '*' -fL --retry 2 --connect-timeout 5 --max-time 60   http://192.168.1.182:8080/setup/install_robot_bridge.sh   -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url http://192.168.1.182:8080
```

按提示输入**机器人的 sudo 密码**。脚本会识别 Humble/Jazzy、安装依赖、自动编译修复版桥，并启用开机服务。若同时装有两个 ROS 版本，选择机器人实际使用的版本。首次编译可能较慢，请等到显示 **Setup complete**。若中断，处理报错或恢复网络后，在记录器空闲时重新运行同一段命令。

此后桥会在机器人开机后自动启动，等待有线网络，并在树莓派可用后重新连接。**安装完成即可关闭终端，不要再手动启动第二个桥。** 旧安装也可重跑同一段命令，启用自动启动。

默认机器人 ROS 域为 **0**。若机器人发布器使用其他域，在最后一条命令末尾添加 `--domain N`，将 `N` 换成实际域。树莓派网页保留域 **1**；两端使用不同域是有意的设置。

### 3. 启动机器人并打开网页

启动机器人的正常传感器程序和 ROS 发布器。在机器人或同一交换机上的电脑浏览器打开：

**http://192.168.1.182:8080**

请保留 `http://` 和 `:8080`。**http://robot-recorder.local:8080** 是可选快捷地址，需要电脑支持本地名称解析，而且可能解析到树莓派的 Wi-Fi 地址。使用配套设备时优先用上面的有线地址。

## 日常录制

完成首次安装后，每次只需给套装和机器人通电、启动机器人的发布器，再打开网页。日常本地录制不需要手动运行桥命令，也不依赖互联网。

1. 等待 **Ready to record（可以录制）**，树莓派网页的 ROS 域保持 **1**。
2. 点击 **Refresh topics（刷新话题）**，勾选需要保存的话题。需要切包时，在 **Split MCAP files** 填写大小（MiB）、时长（秒）或两者；都留空则不切包，两项都填时先达到的条件触发切包。
3. 点击 **Begin recording（开始录制）**。计时器在记录器订阅到第一个所选话题后启动。已完成 bag 的时长按第一条至最后一条录入消息计算，因此可能稍有差异。
4. 点击 **Stop recording（停止录制）** 后等待收尾。缓存写入期间大小仍可能增加，请等到结束再断电。
5. 在 **Recordings on the Pi** 中，点击 **View topics** 查看大小、时长、总消息数、各话题消息数和平均 Hz。切分文件仍属于同一录制。**Download** 将 TAR 副本保存到正在使用浏览器的电脑；**Delete** 会永久删除树莓派上的该录制。

本地列表每页显示 10 个录制，话题列表使用内部滚动条。打开页面或点击 **Refresh topics** 时，机器人端进行一次约 1 秒的带宽采样。**—** 表示没有可用估算，不代表零；勾选后显示合计。临时订阅不保存传感器数据，开始录制前必须关闭。估算值不保证所有消息都能录入。

异常录制会显示简短警告，详情在 **View topics**。**Data loss detected** 表示已报告或确认丢失；**Possible data loss** 表示网络饱和等风险；**Robot connection unavailable** 表示原先已连接的机器人链路中断。没有警告也不等于源数据绝对完整。

文件保存在树莓派配置的录制盘上。当前套装需要连接已配置好的 SSD，使用期间请保持连接。关机前先结束录制和传输，再从联网电脑运行：

```bash
ssh -tt recorder@192.168.1.182 'sudo poweroff'
```

树莓派登录密码由维护者提供。等待关机完成后再移除电源。

## 可选增强：LoRa 控制

需要远距离选择话题、开始/停止和查看状态时，按 [LoRa 远程控制说明](lora-remote.zh-CN.md) 设置。远端笔记本无需树莓派 IP 或现场网络，但机器人到树莓派的以太网/Zenoh 数据链路仍需运行。LoRa 不传传感器数据，也不下载 bag。本地录制可以独立使用。

## 云端上传（可选）

维护者配置好云端连接后，在 **Recordings on the Pi** 区域、**Refresh recordings** 旁操作：

- 初始为 **Manual upload（手动上传）**：在需要上传的录制条目上点击 **Upload to cloud**。
- 切换到 **Automatic upload（自动上传）** 并确认后，树莓派空闲时自动上传已完成的录制，也包括以前保存的录制。
- **Stop uploads** 停止压缩、传输及排队任务，并切回手动模式。需要继续时，点击对应录制的 **Resume upload**；部分准备或校验可能重新执行。
- **Cloud connected** 表示树莓派可以访问云端。云端不可达时，不能新建上传任务或切换模式；LoRa 连接正常不代表云端可达。
- MCAP 先无损压缩为带索引的 Zstandard MCAP，再上传。录制始终优先：开始录制前暂停压缩和传输，录制结束后可继续。
- 所有文件通过读回校验后才显示 **Uploaded to cloud**。原文件保留在树莓派，由用户决定是否删除；压缩需要临时空间。

文件由树莓派通过自己的互联网连接上传，LoRa 只传控制和状态。云端账号和下载入口由维护者提供。需要使用 ROS 回放时，将 `metadata.yaml` 及其引用的全部 `.mcap` 文件下载到同一目录。

## 常见问题

### 无法访问树莓派

在**无法连接的电脑上**运行：

```bash
ip -4 route get 192.168.1.182
curl -q --noproxy '*' -fsS --connect-timeout 3 --max-time 6   http://192.168.1.182:8080/api/status
```

路由应使用连接交换机的有线网口，请求应返回状态 JSON。若走 Wi-Fi，检查以太网网线和地址。若命令可以直连，但浏览器返回 **502**，在代理设置中对树莓派 IP 和使用中的 `robot-recorder.local` 添加直连例外。录制服务不可用时还要检查树莓派电源和 SSD。本地网页没有登录验证，请仅在可信局域网使用。

### 查找树莓派有线地址

更换路由器或修改其配置时才通常需要此步骤。优先在路由器 DHCP 租约列表查找 `robot-recorder`，也可在**机器人或操作笔记本**运行：

```bash
timeout 5 getent ahostsv4 robot-recorder.local | awk '{print $1}' | sort -u
ssh recorder@robot-recorder.local 'ip -4 -brief address show dev eth0'
```

第一条可能返回 Wi-Fi 地址，后续使用 **eth0** 行的 IPv4 地址，不带 `/24`。树莓派密码向维护者获取。若名称无法解析，可给**树莓派**接屏幕、键盘，直接运行 `ip -4 -brief address show dev eth0`，或查看路由器租约。eth0 没有地址时，应先检查其有线连接和 DHCP。

### 机器人以太网与树莓派不在同一网段

仅插上网线，不代表两台设备的固定 IP 在同一网段。机器人必须保留原地址时，请网络管理员分配一个树莓派网段内未占用的地址及前缀，再临时追加，保留原地址：

```bash
read -rp '连接交换机的有线网口名: ' LAN_IF
read -rp '管理员分配的未占用 IPv4 地址/前缀: ' LAN_ADDR
sudo ip -4 addr add "$LAN_ADDR" dev "$LAN_IF"
ip -4 route get 192.168.1.182
```

不要随意猜地址。临时地址重启后失效，需要长期使用时请管理员配置。Wi-Fi 可以保持连接；桥会等到具备直达树莓派的有线路由后启动。

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

### 树莓派地址或机器人 ROS 域改变

先停止录制。在**机器人**输入新的有线地址和发布器使用的 ROS 域，重新配置并重启自动服务，无需重新编译：

```bash
read -rp '树莓派有线 IP: ' PI_IP
read -rp '机器人发布器的 ROS 域: ' ROBOT_DOMAIN
curl -q --noproxy '*' -fL --retry 2 --connect-timeout 5 --max-time 60   "http://$PI_IP:8080/setup/install_robot_bridge.sh" -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url "http://$PI_IP:8080"   --configure-only --domain "$ROBOT_DOMAIN"
```

### 找不到话题或消息数异常

确认机器人正在发布、源端桥与发布器 ROS 域一致、树莓派网页使用域 **1**。按上文检查桥服务后，点击 **Refresh topics**。网络需允许机器人连接树莓派的 TCP **7447** 端口。在树莓派运行 `systemctl is-active robot-recorder-bridge.service robot-recorder.service`，应返回两行 `active`。

在**机器人**运行 `pgrep -af '[z]enoh-bridge-ros2dds'`，应只看到一个路径包含 `zenoh-bridge-ros2dds-fixed` 的修复版桥。若有旧的手动桥或旧桥服务，先停止旧实例，不要并行运行 `/usr/bin/zenoh-bridge-ros2dds`。版本号相同不代表已包含修复。消息数仍异常时，请保留 bag 和日志交给维护者。

### 空 bag：检查一条实时消息

保持机器人发布器运行，用 `ssh recorder@192.168.1.182` 登录树莓派，然后在**树莓派**执行：

```bash
source /opt/ros/jazzy/setup.bash
read -rp '需要检查的话题（以 / 开头）: ' TOPIC
timeout 10 env -u ROS_LOCALHOST_ONLY   ROS_DOMAIN_ID=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp   ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET   CYCLONEDDS_URI="file://$HOME/robot-recorder/zenoh/pi-cyclonedds.xml"   ros2 topic echo "$TOPIC" --once --no-arr
```

当前接收域需要这份树莓派本地发现配置。命令收到一条消息后退出，不打印数组内容。超时可能是链路异常、发布器未运行，或话题低频/需要触发；先确认发布器，再重新录制。
