# Optional Enhancement: LoRa Remote Control

**English** | [简体中文](lora-remote.zh-CN.md)

The recorder's main interface is the Pi's local network page. First follow the [Recorder User Manual](user-manual.md) to set up Ethernet and Zenoh. This guide is for users adding control from a distance.

Compatible USB LoRa radios let an operator laptop select ROS 2 topics, start/stop recording and view Pi status. Recordings remain on the Pi; sensor data does not travel over LoRa.

## First-time installation

Use Linux, Python 3 (3.10 or newer recommended), OpenSSL, and the maintainer-supplied USB radio with its antenna. The remote laptop does not need ROS, Zenoh or a manual build.

Download and install on the **operator laptop**:

```bash
curl -fL --retry 3 --retry-all-errors \
  https://github.com/FCosx/recorder-lora-remote/releases/latest/download/recorder-lora-remote.pyz \
  -o recorder-lora-remote.pyz &&
python3 recorder-lora-remote.pyz install
```

On first installation, enter the pairing passcode supplied privately by the maintainer. Input is hidden. The installer contains encrypted pairing authorization; decrypted credentials are saved only on the laptop. Updating an already paired installation preserves its pairing and command counter without asking for the passcode again.

Downloading requires internet. The maintainer can also supply the installer by USB drive for offline installation. Installation and operation do not require the Pi IP, SSH or access to the site network.

## Everyday use

Attach the antenna, plug in the compatible radio and close programs using its serial port. Run this on the **operator laptop** and keep the terminal open:

```bash
python3 -B ~/robot-recorder/tools/lora_recorder.py remote
```

Open **http://127.0.0.1:8081** in **that laptop's browser**. Wait for `Radio connected`, click `Refresh topics`, select topics, and begin/stop recording. Closing the terminal stops remote control and status updates; it does not stop an ongoing recording on the Pi. Run only one control client for the same pairing at a time.

By default, status requests wait one second after each reply, plus radio transmission time. The recording timer advances locally and is marked as estimated; size and free space use the latest Pi reply.

Before starting, optionally set MiB and/or seconds under `Split MCAP files`. Leave blank to disable splitting. If both limits are set, the first reached starts a new segment; all segments belong to one recording. CPU temperature and the age of the last status update appear at the upper right.

## View recordings

`Refresh recordings` loads five completed recordings per page, showing their names, start times, sizes, durations and message counts. `View topics` loads topic names, message counts, average Hz and types. `Delete` requires confirmation and permanently removes the recording and all its files; it is available only while the recorder is idle. Warning/Error badges include brief reasons, with more detail under `View topics`.

Lists and details load on demand in small radio chunks. Downloads are available through the local Pi page, not the LoRa page. The Pi agent must support these features; the maintainer handles its updates.

After recording finishes, the remote automatically refreshes the newest page once. When metadata arrives, it briefly shows the confirmed bag duration. Live status includes the MCAP file count. Action errors stay visible until dismissed with `Dismiss` or replaced by a new action. Storage indicators distinguish ready and low-storage states.

## Troubleshooting

- **Serial permission denied:** run `sudo usermod -aG dialout "$USER"`, then log out and back in.
- **Multiple serial ports:** append `--port /dev/ttyUSB0` to the startup command, choosing the correct radio port.
- **Radio not found:** check USB connections and the CH340 driver. BRLTTY may claim the serial interface.
- **OpenSSL missing:** on Ubuntu, run `sudo apt install openssl`.
- **No radio reply:** check power, antennas, matching radio settings, and the Pi's recorder/LoRa services.

Share the pairing passcode privately. Do not publish decrypted `remote.json` files or private pre-paired installers. Encrypting a pairing file does not encrypt the radio messages. Range must be tested at the actual location.

The installer includes pySerial 3.5; see [Third-party notices](../THIRD_PARTY_NOTICES.md).

## Status update interval

The default is a one-second wait after each reply before the next status request. Transmission and retries take additional time, so this does not guarantee a fresh update every second. The normal startup command uses this default; the page shows `1 s polling`, and the timer remains smooth between replies.

To reduce radio traffic and leave more capacity for topic/recording lists, press Ctrl+C, then restart with a two-second wait:

```bash
python3 -B ~/robot-recorder/tools/lora_recorder.py remote --poll-seconds 2
```

To restore one second, press Ctrl+C, restart normally and reload the page:

```bash
python3 -B ~/robot-recorder/tools/lora_recorder.py remote
```

Run only one client at a time. No re-pairing or Pi restart is needed. This option changes LoRa status polling only; Ethernet/Zenoh transport and recording settings stay the same. Release v0.4.0 remains available for a full rollback to the earlier two-second version. Check long-distance behavior in the intended environment.
