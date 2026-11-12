# Robot Recorder — Lenovo development branch

**English** | [简体中文](README.zh-CN.md)

This branch records the tested Lenovo replacement for the Raspberry Pi recorder: **Ubuntu 24.04 / ROS 2 Jazzy, internal NVMe storage**, and the existing browser, Zenoh, LoRa and cloud-upload functions. The current robot is an **Orin NX running ROS 2 Humble**, with RealSense and N10P LiDAR. Local recording remains the main function; LoRa and cloud are optional.

Start with the [Recorder User Manual](docs/user-manual.md) ([中文](docs/user-manual.zh-CN.md)). Confirm the recorder's wired address first; the current Lenovo is **192.168.1.102**. Start the robot's ROS publishers and finish the bridge installer before opening **http://192.168.1.102:8080**. A browser-only computer needs no ROS or bridge installation.

## Included functions

- Select standard ROS topics; change the robot bridge's ROS domain from either UI, saved across reboots. Receiver domain stays **1**.
- Record MCAP to NVMe, split by size/time, inspect counts/Hz, download over LAN/Wi-Fi, and delete completed recordings.
- Show CPU temperature, storage and recording warnings, including receive-buffer overflow risk.
- Optional [LoRa control](docs/lora-remote.md): topic selection, start/stop, splitting and status without a recorder IP or site-network connection on the remote laptop. Sensor data still uses Ethernet/Zenoh.
- Optional cloud upload with indexed Zstandard compression, Manual/idle Automatic modes, pause/resume and recording priority. [Cloud access](docs/user-manual.md#cloud-website) includes login, downloads, full-timeline single/four-topic previews, Fast/HD image choices and administrator Trash/Restore.

## Branch and packages

Use the [Lenovo branch package](https://github.com/FCosx/recorder-lora-remote/releases/tag/lenovo-v0.13.0) for its matching LoRa installer and x86_64/ARM64 v2 bridge archives. It is a **prerelease**, separate from the Pi version on [main](https://github.com/FCosx/recorder-lora-remote/tree/main). The prepared recorder serves the normal robot installer; users do not compile anything.

This public branch contains setup tools, the LoRa client, encrypted pairing authorization, guides and bridge provenance. The recorder application, cloud backend, login credentials, decrypted pairing and operational databases remain private and are provisioned by the maintainer. Cloning this repository alone does not install the recorder backend on a blank Lenovo.

See [validation and limitations](docs/lenovo-validation.md) ([中文](docs/lenovo-validation.zh-CN.md)). **The Lenovo throughput limit has not been measured.** The planned 5 MiB/s-step load/temperature benchmark is saved for the next session. Pi throughput results do not establish a Lenovo limit. Some current UI labels still say “Pi”; in this branch they refer to the Lenovo recorder.

The LoRa installer includes pySerial 3.5; see [Third-party notices](THIRD_PARTY_NOTICES.md).
