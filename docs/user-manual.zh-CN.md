# 机器人数据记录器使用手册

[English](user-manual.md) | **简体中文**

本手册供第一次接入本记录器的用户使用，前提是拿到维护者已配置好的树莓派；不包含从空白系统部署树莓派的步骤。树莓派接收话题并保存 MCAP 文件；机器人发布 ROS 2 话题；浏览器负责选择话题和控制录制。可直接使用带屏幕的机器人主机（如 Orin）打开网页，不一定需要操作笔记本。树莓派的桥已配置好；新接入的机器人需要安装自己的 Zenoh 桥。

新接入的机器人需要已有 ROS 2 Humble 或 Jazzy，并完成下面的一次性 Zenoh 桥安装和配置。首次安装需有互联网，正常录制时只需机器人与树莓派之间的局域网。日常使用只需连接设备、启动机器人上的桥，再从网页选择机器人正在发布的话题并开始录制。

## 正常使用流程

### 1. 连接设备并找到树莓派

先打开树莓派，等待启动完成。把蜂窝路由器的 LAN 口、树莓派和机器人接到**同一台以太网交换机**；如使用操作笔记本，也将它接入交换机。路由器提供局域网地址和蜂窝网络连接；本地录制不依赖蜂窝网络。当前使用的 IR2700-R 不提供本方案所需的 Wi-Fi 接入点。机器人已有的 Wi-Fi 可以保持连接。

在机器人或操作笔记本的浏览器中输入完整网址：

**http://robot-recorder.local:8080**

务必保留开头的 `http://` 和末尾的 `:8080`。首次配置机器人桥时，需要确认树莓派的**有线 IP**。在机器人或操作笔记本终端依次运行：

```bash
timeout 5 getent ahostsv4 robot-recorder.local | awk '{print $1}' | sort -u
ssh -n recorder@robot-recorder.local 'ip -4 -brief address show dev eth0'
```

树莓派 SSH 用户名通常为 **`recorder`**，密码请向维护者索取。首次连接若询问是否信任主机，核对主机信息后再确认；输入密码时不会显示字符。若维护者更改了用户名，请将命令中的 `recorder` 替换为实际用户名。

第一条命令查询 `.local` 名称对应的地址；树莓派同时连接 Wi-Fi 和有线网络时，**即使只返回一个地址，也可能是 Wi-Fi 地址**。第二条命令查询 `eth0`，它显示的才是配置桥所需的有线 IP。读取 `eth0` 行里的 IPv4 地址，不要包含 `/24` 等前缀长度。然后输入该地址，确认网页服务可访问：

```bash
read -rp '树莓派有线 IP（eth0）: ' PI_IP
curl --noproxy '*' --connect-timeout 3 "http://$PI_IP:8080/api/status"
```

应返回状态 JSON。若 `eth0` 没有 IPv4 地址，先检查树莓派的网线、交换机和路由器 DHCP；若名称无法解析，按文末“网页无法打开”排查。正常情况下无需更改机器人的 IP 或关闭机器人的 Wi-Fi。

### 2. 自动安装并配置机器人桥（只需一次）

机器人需要已安装 ROS 2 Humble 或 Jazzy，首次安装时还需连接互联网。下面的命令会从树莓派取得安装脚本，自动安装依赖、准备修复版 Zenoh 桥，并配置树莓派地址。**只需复制、粘贴命令，无需下载或传输安装包，也无需手动修改源码或执行构建步骤。**

在**机器人终端**粘贴下面整段命令，输入第 1 步从 `eth0` 确认的树莓派有线 IP。不确定地址时，先按第 1 步或文末“确认树莓派有线 IP”查询。

```bash
read -rp '树莓派有线 IP: ' PI_IP
curl -q --noproxy '*' -f --retry 3 --retry-all-errors --connect-timeout 5 \
  "http://$PI_IP:8080/setup/install_robot_bridge.sh" -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url "http://$PI_IP:8080"
```

按提示输入机器人的 sudo 密码，等待显示 `Setup complete`。脚本会自动识别 ROS 版本；如果同时安装了 Humble 和 Jazzy，会询问要使用哪个。首次安装会在后台自动完成本机编译，可能需要较长时间；用户不需要参与构建。如果安装中断，处理报错或恢复网络后，重新粘贴同一段命令即可。

安装后，程序和配置保存在机器人用户的 `~/robot-recorder/` 中。脚本默认使用 ROS 域 **0**，树莓派记录器使用域 **1**。启动桥后，按第 3 步在网页查看机器人正在发布的话题。修复版已在开发笔记本通过连续重启测试；Orin 上的实际运行仍需首次部署验证。

### 3. 启动机器人桥（每次使用时）

在**机器人终端**运行这一条命令，录制期间保持终端开启：

```bash
bash ~/robot-recorder/tools/start_robot_bridge.sh
```

每次使用时启动一个机器人桥即可，录制期间保持运行。启动前先退出之前手动运行的桥；如果原版桥由服务启动，先停止该服务。直接运行 `zenoh-bridge-ros2dds -c ...` 仍可能启动系统中的未修复版。

确认机器人的传感器和 ROS 节点已启动，正在发布需要记录的话题。然后在机器人或操作笔记本打开 **http://robot-recorder.local:8080**，界面的 ROS 域保持为 **1**，点击 `Refresh topics`。连接成功后，列表中应显示机器人自己的话题，接下来可直接选择并录制。若没有显示预期话题，按文末“看不到机器人话题”排查。

### 4. 开始录制

1. 确认机器人上的桥仍在运行，在机器人或操作笔记本打开 **http://robot-recorder.local:8080**，等待状态显示 `Ready to record`（可以开始录制）。界面的 ROS 域保持为 **1**。
2. 点击 `Refresh topics`，选择需要保存的话题。需要把长录制分成多个文件时，在 `Split MCAP files` 中填写按大小切分的阈值（MiB）、按时长切分的阈值（秒），或两者都填；留空则不切分。设置好后点击 `Begin recording`。只有话题出现在列表中，并不代表它正在发送消息。
3. 录制结束时点击 `Stop recording`，等待界面完成文件整理。整理期间不要关闭树莓派电源。
4. 在 `Recordings on the Pi` 中点击对应录制的 `View topics`，核对各话题的消息数。切分后的多个 MCAP 文件仍属于同一次录制，可以展开查看每段文件；`View topics` 显示整次录制的汇总。`Download` 会把包含所有分段的 TAR 副本下载到当前浏览器所在设备；`Delete` 会永久删除树莓派上的该次录制及所有分段。

按大小切分的数值是触发切换的参考阈值，不是单个文件的严格上限：缓冲中的消息写入后，文件可能超过填写的大小。两项都填写时，先达到的条件触发切换；最后一段通常较短。网页显示“可以开始录制”，只说明记录器服务可用；是否真的收到数据，应以完成后的话题消息数和录制结果为准。MCAP 文件始终保存在树莓派上，除非用户主动下载副本。

## 可选增强：LoRa 远程控制

在前面的局域网录制流程上，可增加配套 LoRa 电台和操作笔记本，用于远处的话题选择、开始/停止、状态查看和简要录制管理。按 [LoRa 使用说明](lora-remote.zh-CN.md) 安装控制端；安装包可由维护者离线交付，或从 [GitHub](https://github.com/FCosx/recorder-lora-remote) 下载。首次配对口令由维护者私下提供。

LoRa 操作笔记本不需要树莓派 IP、SSH 或接入现场网络；机器人与树莓派之间的以太网/Zenoh 数据链路仍须保持。MCAP 文件保存在树莓派；下载录制使用局域网页面。局域网页面可独立完成录制、切包、查看、下载和删除，无需配置 LoRa。

## 遇到问题时

### 确认树莓派有线 IP

在**机器人或操作笔记本终端**运行：

```bash
timeout 5 getent ahostsv4 robot-recorder.local | awk '{print $1}' | sort -u
```

名称查询只返回地址，不标注它属于哪个网口。树莓派同时连接有线和 Wi-Fi 时，可能只返回 Wi-Fi 地址，因此用下面的命令确认有线 IP：

```bash
ssh recorder@robot-recorder.local 'ip -4 -brief address show dev eth0'
```

SSH 用户名与密码说明见第 1 步。读取 `eth0` 行的 IPv4 地址，填写安装提示时不要带 `/24` 等前缀长度。即使 SSH 通过 Wi-Fi 地址连接，这条命令查询的仍是树莓派的有线网口。

如需确认树莓派是否也连接 Wi-Fi，可运行：

```bash
ssh recorder@robot-recorder.local 'ip -4 -brief address show dev wlan0'
```

`wlan0` 行若有 IPv4 地址，说明该无线网口当前配置了 IPv4；机器人桥仍应填写前面查到的 `eth0` 地址。若名称查询没有输出，请检查树莓派是否已开机、网线是否连接；也可到路由器 DHCP 设备列表查找树莓派的有线租约，按下面的排查步骤处理，不要猜测 IP。

### 网页无法打开

1. 确认输入的是 **`http://robot-recorder.local:8080`**，包含 `http://` 和 `:8080`。
2. 在打开网页的设备上检查名称解析和网页响应：

   ```bash
   getent ahostsv4 robot-recorder.local
   curl --noproxy '*' --max-time 5 http://robot-recorder.local:8080/api/status
   ```

3. 如果名称无法解析，先确认树莓派已开机且网线已连接；到路由器 DHCP 设备列表查找 `robot-recorder`，或在树莓派上运行 `ip -4 -brief address show dev eth0`。若要使用 `.local` 名称，再在树莓派上检查 `systemctl is-active avahi-daemon.service`，并确认网络允许 mDNS 组播。名称服务未配置时，请联系维护者处理；也可先用有线 IP 访问。
4. 如果命令行直连正常，但浏览器显示 **502**，请把 `robot-recorder.local` 加入浏览器或系统代理的“不使用代理”列表。
5. 如果仍无法打开，到路由器的 DHCP 设备列表中查找树莓派地址，或在树莓派上运行 `ip -4 -brief address show eth0`，再试 `http://<树莓派IP>:8080`。同时检查 `systemctl is-active robot-recorder.service`。

### 有线网络走错网口

如果机器人同时连接 Wi-Fi 和交换机，名称能解析但网页超时，先确认树莓派的**有线 IP**，再在机器人上检查路由和各网口地址：

```bash
read -rp '树莓派有线 IP: ' PI_IP
ip -4 route get "$PI_IP"             # dev 应是连接交换机的有线网口
ip -4 -brief address                 # 查看有线网口是否有同网段地址
```

若路由显示 Wi-Fi 网口，仅插上网线并不保证两个设备处于同一 IPv4 网段。

如果有线网口需要增加同网段地址，先请网络管理员分配该网段中未使用、且不会与 DHCP 自动分配冲突的地址，并确认地址前缀与树莓派有线网络一致。仅在 DHCP 列表中找不到一个地址，不能证明它未被其他设备占用。下面的命令只临时增加地址，不删除网口原有地址：

```bash
read -rp '树莓派有线 IP: ' PI_IP
read -rp '连接交换机的有线网口名: ' LAN_IF
read -rp '该网段中未占用的 IPv4 地址/前缀: ' LAN_ADDR
sudo ip -4 addr add "$LAN_ADDR" dev "$LAN_IF"  # 临时增加；重启后失效
ip -4 route get "$PI_IP"                  # 应显示 dev 为上述有线网口
curl --noproxy '*' --connect-timeout 3 "http://$PI_IP:8080/api/status"
```

机器人重启后需重新配置临时地址，或由管理员将其设置为永久地址。Wi-Fi 不必关闭。若 `route get` 已显示正确的有线网口，直接检查网页响应，不要增加地址。

### 树莓派 IP 或机器人 ROS 域发生变化

先在桥的终端按 Ctrl+C。然后在**机器人终端**粘贴下面的命令，输入新的树莓派有线 IP；`--domain 0` 改为机器人实际话题所在的 ROS 域。此操作只更新配置，不重新安装：

```bash
read -rp '树莓派有线 IP: ' PI_IP
bash /tmp/install_robot_bridge.sh --pi-url "http://$PI_IP:8080" --configure-only --domain 0
bash ~/robot-recorder/tools/start_robot_bridge.sh
```

如果临时安装脚本已被清理，先重新运行第 2 步的下载命令。

### 看不到机器人话题

确认机器人正在发布、机器人桥仍在运行，然后点击 `Refresh topics`。检查机器人桥的域与发布节点相同（本项目测试为 **0**）、网页使用 ROS 域 **1**，以及机器人配置文件 `robot.json5` 中的树莓派 IP。需要修改地址或 ROS 域时，使用上面的配置更新命令。机器人到树莓派的 TCP **7447** 端口也必须可达。

如果仍看不到话题，从机器人或操作笔记本运行 `ssh recorder@robot-recorder.local` 登录树莓派，再检查两个服务是否都显示 `active`：

```bash
systemctl is-active robot-recorder-bridge.service robot-recorder.service
```

### 消息数异常偏高或发现重复

先在机器人上检查桥进程：

```bash
pgrep -af '[z]enoh-bridge-ros2dds'
```

应只有一个桥进程，程序路径应包含 `zenoh-bridge-ros2dds-fixed`。若是 `/usr/bin/zenoh-bridge-ros2dds`，先停止旧桥，再按第 3 步启动修复版。仅查看 `--version` 不能区分补丁，因为两者都显示 1.10.1。若确认使用修复版仍有重复，保留 bag 和日志交给维护者分析。

核对 `View topics` 中各话题的平均录制频率是否符合机器人的实际发布频率。若明显偏高或怀疑重复，保留 bag 和日志交给维护者分析。

### 录制结果没有消息

先保持机器人发布节点运行，再从机器人或操作笔记本运行 `ssh recorder@robot-recorder.local` 登录树莓派。在**树莓派**上执行：

```bash
source /opt/ros/jazzy/setup.bash
read -rp '要检查的机器人话题名（以 / 开头）: ' TOPIC
timeout 10 env -u ROS_LOCALHOST_ONLY \
  ROS_DOMAIN_ID=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET \
  ros2 topic echo "$TOPIC" --once --no-arr
```

输入需要检查的实际话题名。收到消息后会打印一条消息并退出，数组内容会省略。若 10 秒内没有输出，确认该话题此时确实在发送数据；低频或事件话题可能需要等待或触发。若持续发布的话题仍收不到消息，先检查桥接连接，再重新录制。

网页目前没有登录功能，只应在可信任的局域网中使用。桥安装脚本及修复版桥由已配置好的树莓派提供，无需先克隆此 GitHub 仓库。
