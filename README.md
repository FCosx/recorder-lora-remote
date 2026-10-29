# Robot Recorder

**English** | [简体中文](README.zh-CN.md)

A ROS 2 data recorder for robot experiments. Robots send topics to a Raspberry Pi over Ethernet and Zenoh. Users select topics and control recording through a browser on the local network; MCAP files are saved on the Pi.

## Main features

- Discover and select ROS 2 topics to record.
- Start and stop recording; split MCAP files by size or duration.
- Inspect recording size, duration, topic message counts and average Hz; download or delete recordings.
- Monitor recording status, free space, CPU temperature and brief warnings.

## First-time setup

**Start with the [Recorder User Manual](docs/user-manual.md) ([中文](docs/user-manual.zh-CN.md)).** It provides copy-and-paste commands for the normal workflow, followed by troubleshooting for special cases:

1. Connect the robot, prepared Pi and router LAN port to the same Ethernet switch.
2. Find the Pi's wired IP and install the robot's Humble/Jazzy Zenoh bridge once.
3. Start the robot bridge and sensors; finish these setup steps before opening the UI.
4. Open `http://<PI_WIRED_IP>:8080` using the confirmed wired IP, then select topics and record. Inspect, download or delete recordings afterward.

The Pi must already be configured by the maintainer; the robot needs ROS 2 Humble or Jazzy. Installing the robot bridge requires internet access. Routine local recording does not. You do not need to clone this repository first.

## Everyday use

After first-time setup, run this in the **robot terminal** and keep it running during recording:

```bash
bash ~/robot-recorder/tools/start_robot_bridge.sh
```

Start the robot's publishers, then open `http://<PI_WIRED_IP>:8080` on the robot or another computer on the same subnet, replacing the placeholder with the confirmed wired address. Select topics and begin recording. After stopping, wait for finalization before inspecting the result. If name resolution works on this computer, `http://robot-recorder.local:8080` is an optional shortcut.

## Optional enhancement: LoRa remote control

For control outside the local network, add compatible USB LoRa radios and an operator laptop. Follow the [LoRa Remote Guide](docs/lora-remote.md) ([中文](docs/lora-remote.zh-CN.md)). It provides topic selection, Start/Stop, status and brief recording management. Sensor data continues over the robot-to-Pi Ethernet/Zenoh link.

The LoRa laptop can be installed offline and operated without the Pi's IP or access to the site network. GitHub downloads require internet; the maintainer supplies the first-time pairing passcode privately. Status polling waits one second after each reply by default. The LoRa page does not download recordings.

## Repository contents

This repository currently provides the recorder manuals and the optional LoRa client's source and [installer](https://github.com/FCosx/recorder-lora-remote/releases/latest). The maintainer prepares the Pi recording service separately. Pairing authorization in the public installer is encrypted; Pi login passwords and decrypted pairing files are kept private.

The LoRa installer includes pySerial 3.5; see [Third-party notices](THIRD_PARTY_NOTICES.md).
