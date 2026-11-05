# Robot Recorder

**English** | [简体中文](README.zh-CN.md)

A ROS 2 data recorder for robot experiments. Robots send topics to a Raspberry Pi over Ethernet and Zenoh. Users select topics and control recording through a browser on the local network; MCAP files are saved on the Pi.

## Main features

- Optional MinIO uploads: indexed MCAP Zstandard compression, automatic idle/manual modes, verified-upload badges; recording takes priority.
- Discover and select ROS 2 topics to record.
- Start and stop recording; split MCAP files by size or duration.
- Inspect recording size, duration, topic message counts and average Hz; download or delete recordings.
- Monitor recording status, free space, CPU temperature and brief warnings.

## First-time setup

**Start with the [Recorder User Manual](docs/user-manual.md) ([中文](docs/user-manual.zh-CN.md)).** It provides copy-and-paste commands for the normal workflow, followed by troubleshooting for special cases:

1. Connect the robot, prepared Pi and router LAN port to the same Ethernet switch.
2. On the robot publishing ROS topics, run the manual's Humble/Jazzy bridge installer once. It enables automatic startup.
3. Start the robot's sensors and publishers; finish setup before opening the UI.
4. Open `http://192.168.1.182:8080`, the Pi's reserved wired address in the supplied bundle. Select topics and record; inspect, download or delete recordings afterward.

The Pi must already be configured by the maintainer; the robot needs ROS 2 Humble or Jazzy. Installing the robot bridge requires internet access. Routine local recording does not. You do not need to clone this repository first.

## Everyday use

Power on the bundle and robot, start the robot's publishers, then open **http://192.168.1.182:8080** on a computer connected to the switch. The robot bridge starts automatically and reconnects when the Pi is available; no terminal needs to stay open. A browser-only computer needs no ROS or bridge installation.

Select topics and begin recording. After stopping, wait for finalization before inspecting the result. If the bundle address changes or a robot has a fixed Ethernet address on a different subnet, follow the manual's troubleshooting section. Local-name access is an optional shortcut.

## Optional enhancement: LoRa remote control

For control outside the local network, add compatible USB LoRa radios and an operator laptop. Follow the [LoRa Remote Guide](docs/lora-remote.md) ([中文](docs/lora-remote.zh-CN.md)). It provides topic selection, Start/Stop, status and brief recording management. Sensor data continues over the robot-to-Pi Ethernet/Zenoh link.

The LoRa laptop can be installed offline and operated without the Pi's IP or access to the site network. GitHub downloads require internet; the maintainer supplies the first-time pairing passcode privately. Status polling waits one second after each reply by default. The LoRa page does not download recordings.

## Repository contents

This repository currently provides the recorder manuals and the optional LoRa client's source and [installer](https://github.com/FCosx/recorder-lora-remote/releases/latest). The maintainer prepares the Pi recording service separately. Pairing authorization in the public installer is encrypted; Pi login passwords and decrypted pairing files are kept private.

The robot bridge launcher also starts a small rate helper. Refreshing either UI takes one short robot-local snapshot; recording waits for temporary readers to close. Existing robots receive the helper and automatic startup by rerunning the manual's setup command while the recorder is idle.

The LoRa installer includes pySerial 3.5; see [Third-party notices](THIRD_PARTY_NOTICES.md).
