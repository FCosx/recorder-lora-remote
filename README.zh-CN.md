# Robot Recorder — Lenovo 开发分支

[English](README.md) | **简体中文**

此分支记录已经验收的 Lenovo 临时录制器：**Ubuntu 24.04 / ROS 2 Jazzy，内部 NVMe 存储**，保留浏览器、Zenoh、LoRa 和云端上传功能。当前机器人为 **Orin NX / ROS 2 Humble**，连接 RealSense 与 N10P 雷达。本地录制是主要功能，LoRa 与云端为可选增强。

先看[记录器使用手册](docs/user-manual.zh-CN.md)。先确认记录器有线 IP；当前 Lenovo 是 **192.168.1.102**。启动机器人的 ROS 发布器并完成桥安装后，再打开 **http://192.168.1.102:8080**。仅打开网页的电脑无需 ROS 或桥。

## 功能

- 勾选标准 ROS 话题；在两个 UI 修改机器人桥监听域并跨重启保存，接收端固定为 **1**。
- MCAP 录到 NVMe，按大小/时间切包，查看消息数/Hz，通过局域网下载并删除已完成录制。
- 显示 CPU 温度、空间与录制告警，包括接收缓冲溢出风险。
- 可选 [LoRa 控制](docs/lora-remote.zh-CN.md)：选话题、启停、切包、状态；远端电脑无需记录器 IP 或现场网络。传感器数据仍经 Ethernet/Zenoh。
- 可选云端：带索引 Zstandard 压缩、手动/空闲自动上传、停止/继续且录制优先。[云端网页](docs/user-manual.zh-CN.md#云端网页)提供账号登录、下载、单话题/四话题完整时间轴预览、Fast/HD 及管理员回收站/恢复。

## 分支与安装包

使用 [Lenovo 分支安装包](https://github.com/FCosx/recorder-lora-remote/releases/tag/lenovo-v0.13.0)，包含匹配的 LoRa 安装器与 x86_64/ARM64 v2 桥。它是独立的 **prerelease**，[main](https://github.com/FCosx/recorder-lora-remote/tree/main) 保留 Pi 版本。已经准备好的记录器提供正常机器人安装入口，用户无需编译。

公开分支仅包含安装工具、LoRa 客户端、加密配对文件、说明书和桥的构建信息。录制/云端后端源码、登录凭据、解密配对及运行数据库仍私有，由维护者准备。仅克隆此仓库不能在空白 Lenovo 上安装完整录制后端。

验收与限制见[测试说明](docs/lenovo-validation.zh-CN.md)。**Lenovo 吞吐率上限尚未测定**；5 MiB/s 步进负载/温度测试已留到下次。Pi 的测试结果不能当作 Lenovo 极限。当前部分 UI 文案仍称 “Pi”，在此分支指 Lenovo 录制器。

LoRa 安装器包含 pySerial 3.5，见[第三方说明](THIRD_PARTY_NOTICES.md)。
