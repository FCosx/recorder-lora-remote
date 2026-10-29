# Recorder LoRa Remote

通过 USB LoRa 电台选择 ROS 2 话题、开始/停止录制，并查看树莓派状态。数据保存在树莓派，不通过 LoRa 传输。

## 首次安装

需要 Linux、Python 3（建议 3.10 或更新）和 OpenSSL；无需 ROS、Zenoh 或自行编译。

```bash
curl -fL https://github.com/FCosx/recorder-lora-remote/releases/latest/download/recorder-lora-remote.pyz -o recorder-lora-remote.pyz
python3 recorder-lora-remote.pyz install
```

首次安装输入维护者提供的配对口令，输入时不显示字符。安装包包含加密配对文件；解密后的凭据仅保存于本机。已有配对更新时无需再次输入，原配对和命令编号会保留。

下载需要互联网，也可用 U 盘复制安装包。安装及日常控制不需要树莓派 IP、SSH 或现场网络。

## 每次使用

接好天线，插入配套电台，关闭占用串口的程序，然后运行并保持终端开启：

```bash
python3 -B ~/robot-recorder/tools/lora_recorder.py remote
```

在**这台笔记本**打开 **http://127.0.0.1:8081**。等待 `Radio connected`，刷新并选择话题，然后开始/停止录制。关闭终端只会停止远程控制，不会结束树莓派正在进行的录制。同一配对只运行一个控制端。

状态请求在收到回复后等待 2 秒，再加无线传输时间。录制计时器会在本机连续递增并标为估计；大小、空间等数值以树莓派回复为准。

## 常见问题

- 串口权限不足：`sudo usermod -aG dialout "$USER"`，注销后重新登录。
- 多个串口：在启动命令末尾添加 `--port /dev/ttyUSB0`，选择正确电台。
- 找不到电台：检查 USB 连接及 CH340 驱动；BRLTTY 可能占用串口。
- 缺少 OpenSSL：Ubuntu 运行 `sudo apt install openssl`。
- 无线无回复：检查两端电源、天线、匹配的电台设置，以及树莓派录制/LoRa 服务。

配对口令需私下交付；不要公开解密后的 `remote.json` 或私有预配对安装包。配对文件加密不等于无线数据加密。远距离效果需实测。

安装包含 pySerial 3.5，许可见 [第三方说明](THIRD_PARTY_NOTICES.md)。
