# Recorder LoRa Remote

A Linux laptop client for selecting ROS 2 topics, starting/stopping recording,
and checking a compatible Raspberry Pi recorder over USB serial LoRa radios.
The browser page runs on the laptop at **http://127.0.0.1:8081**. Sensor data and
MCAP files stay on the recorder; this radio link carries commands and status.

## Download and install

Requires Linux with Python 3 (3.10 or newer recommended). No ROS, Zenoh, pip,
or compilation is needed on the remote laptop. The installer includes pySerial.

```bash
curl -fL https://github.com/FCosx/recorder-lora-remote/releases/latest/download/recorder-lora-remote.pyz -o recorder-lora-remote.pyz
python3 recorder-lora-remote.pyz install
```

GitHub requires internet for the download. You can instead copy the installer
from a USB drive: installation and operation need no internet, Pi IP, SSH,
or connection to the recorder's local network.

**New users need authorization for their recorder.** Obtain a private
`recorder-pairing.json` file from its maintainer, for example with the radio
on a USB drive, then import it locally:

```bash
python3 recorder-lora-remote.pyz install --pairing /path/to/recorder-pairing.json
```

An already configured laptop keeps its existing pairing and command counter
when updating, so it does not need to import the file again. Public downloads
contain **no pairing keys**. Never upload the private pairing file or a private
pre-paired installer to GitHub. The supplied radio alone does not authorize a
fresh software installation.

## Run

Attach the paired radio and its antenna. Close serial terminals that might
be using its port, then keep this command running:

```bash
python3 -B ~/robot-recorder/tools/lora_recorder.py remote
```

Open **http://127.0.0.1:8081 on the same laptop**. Wait for Radio connected,
refresh the topic list, select topics or choose All available topics, then
start recording. Stop requests normal bag finalization on the Pi.

Startup and recovery automatically synchronize command numbering over radio.
Closing this terminal stops laptop control/status updates; it does not stop a
recording already running on the Pi. No recorder IP is entered.

The client auto-detects one CH340 adapter. To select a particular port:

```bash
python3 -B ~/robot-recorder/tools/lora_recorder.py remote --port /dev/ttyUSB0
```

If access is denied, run `sudo usermod -aG dialout "$USER"`, then log out and
back in. If USB detects CH340 but no serial port exists, inspect kernel logs
for a driver conflict such as BRLTTY before changing services. Disabling
BRLTTY also affects Braille devices.

## What is supported

- Selected topics or all topics discovered at recording start, up to 100.
- Start/Stop acknowledgments, duplicate-command suppression, and stale-status handling.
- State, elapsed time, MCAP size, free storage, CPU temperature, and topic count.
- Authenticated radio synchronization with a fresh challenge at startup/recovery.
- USB LoRa radios in matching transparent serial mode; UART default 9600 baud.

Only one controller should run for a pairing. Lost radio contact does not stop
recording; status becomes stale and commands are disabled until the link
recovers. HMAC authenticates packets but does not encrypt telemetry. Long-range
operation depends on the actual radios, antennas, environment, and permitted
radio settings; no one-mile guarantee is made here.

A compatible Pi agent and recorder HTTP API must already be configured by the
recorder maintainer. The robot-to-Pi sensor link remains local Ethernet/Zenoh.
This repository distributes the remote installer/runtime, not recorded bags.

## Build from source (maintainers only)

Operators should use the release file above. Developers can build a key-free
installer with:

```bash
python3 -m pip install -r requirements-dev.txt
python3 tools/lora_recorder.py build-public --output dist/recorder-lora-remote.pyz
python3 -m unittest discover -s tests -v
```

The public build does not read a recorder's pairing configuration. Keep the
private `export-remote` command and its output out of public releases. A checksum
file is provided with each release for download-integrity checks.

The bundled pySerial sources are unmodified and covered by their included
BSD-3-Clause license in `lora/licenses/pyserial-LICENSE.txt`.

## 中文快速使用

下载公开安装文件后运行 `python3 recorder-lora-remote.pyz install`。新用户还需从
记录器维护者私下取得 `recorder-pairing.json`，使用上面的 `--pairing` 命令导入。
已有配置更新时会保留配对，无需重复导入。公开安装文件不含任何记录器密钥。

运行 `python3 -B ~/robot-recorder/tools/lora_recorder.py remote` 并保持终端开启，
在**同一台笔记本**打开 **http://127.0.0.1:8081**。选择话题、开始/停止和状态更新
均通过 LoRa；不需要树莓派 IP、SSH 或接入现场网络。首次从 GitHub 下载需要互联网，
也可以通过 U 盘交付安装文件和私有配对文件，在现场完全离线安装。
