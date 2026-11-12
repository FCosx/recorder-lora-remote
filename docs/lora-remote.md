# Optional Enhancement: LoRa Remote Control

**English** | [简体中文](lora-remote.zh-CN.md)

The main interface is the recorder's local network page. First follow the [Recorder User Manual](user-manual.md) to set up Ethernet and Zenoh. This guide is for users adding control from a distance.

Compatible USB LoRa radios let an operator laptop select ROS 2 topics, start/stop recording and view recorder status. Recordings remain on the recorder; sensor data does not travel over LoRa.

This Lenovo branch uses the existing recorder protocol and pairing; the remote does not need ROS. Some UI labels still say Pi.

## First-time installation

Use Linux, Python 3 (3.10 or newer recommended), OpenSSL, and the maintainer-supplied USB radio with its antenna. The remote laptop does not need ROS, Zenoh or a manual build.

Download and install on the **operator laptop**:

```bash
curl -fL --retry 3 --retry-all-errors \
  https://github.com/FCosx/recorder-lora-remote/releases/download/lenovo-v0.13.0/recorder-lora-remote.pyz \
  -o recorder-lora-remote.pyz &&
python3 recorder-lora-remote.pyz install
```

On first installation, enter the pairing passcode supplied privately by the maintainer. Input is hidden. The installer contains encrypted pairing authorization; decrypted credentials are saved only on the laptop. Updating an already paired installation preserves its pairing and command counter without asking for the passcode again.

Downloading requires internet. The maintainer can also supply the installer by USB drive for offline installation. Installation and operation do not require the recorder IP, SSH or access to the site network.

## Everyday use

Attach the antenna, plug in the radio, and close other programs using its serial port. Open **Robot Recorder LoRa** from the operator laptop's application menu. The installer creates this shortcut; some desktops also show a desktop copy. It starts the controller in the background and opens **http://127.0.0.1:8081** on that laptop. Opening it again reuses the same controller.

If the menu entry is unavailable, run this command; the terminal can then be closed:

```bash
python3 -B ~/robot-recorder/tools/lora_recorder.py open
```

Wait for **Radio connected**, refresh topics, select the required ones, then begin/stop recording. **Closing the browser or launch terminal does not stop the background controller.** To stop it explicitly:

```bash
python3 -B ~/robot-recorder/tools/lora_recorder.py remote-stop
```

Stopping the controller does not stop an ongoing recording on the recorder. The controller is not automatically enabled at boot; open the launcher when needed. One controller is allowed per pairing on the same user account; close a controller on another laptop before switching laptops.

For foreground terminal operation instead, first stop the background controller, then run `python3 -B ~/robot-recorder/tools/lora_recorder.py remote` and keep that terminal open. Ctrl+C stops this foreground version. No recorder IP or network connection is needed for either mode.

By default, status requests wait one second after each reply, plus radio transmission time. The recording timer advances locally and is marked as estimated; size and free space use the latest recorder reply.

Before starting, optionally set MiB and/or seconds under `Split MCAP files`. Leave blank to disable splitting. If both limits are set, the first reached starts a new segment; all segments belong to one recording. CPU temperature appears at the upper right.

## Robot ROS domain

**Available topics → Robot ROS domain** is shared with the local recorder page. While idle, enter the publishers' domain (**0–232**), click **Apply domain**, and wait for **Current: …** to confirm the change. The topic list refreshes afterward. The robot saves the value across reboots; unknown initial detection uses **0**.

This selects the source bridge's listening domain. It does not change publishers or the recorder's fixed domain **1**. Recording and domain changes cannot run together. Even if the selected domain has no topics, you can correct it over LoRa without SSH or a recorder IP on this laptop. The robot-to-recorder Ethernet link and updated managed source bridge must be running. If the control is unavailable, check that bridge using the recorder manual.

## Bandwidth preview

Opening the page or clicking **Refresh topics** requests one quick robot-side bandwidth snapshot. Topics are sampled together for about one second, targeting a result within about 1–2 seconds on a healthy link. **—** means insufficient samples or a timeout, not zero. Per-topic rates and the selected total stay visible until the next refresh. LoRa delivery takes additional time. Temporary subscribers count bytes in robot RAM only, save no messages and send only metadata/results to the recorder. Starting recording from either UI waits for the robot to confirm that its temporary subscribers have closed; missing confirmation prevents recording from starting. These short receive-rate estimates do not guarantee complete delivery or sustainable storage throughput.

A known robot link that stops responding shows **Robot connection unavailable** after about 4–5 seconds, plus LoRa delivery time. Recording continues. A recovered interruption remains noted on that recording; `View topics` shows the interruption count. This reuses the existing helper heartbeat, adds no sensor subscriptions, and does not measure message loss. No warning is shown until a robot helper has been seen in the current domain; shorter interruptions may not be detected.

## View recordings

`Refresh recordings` loads all completed recordings in one list, showing their names, start times, sizes, durations and message counts. No page changes are needed. `View topics` loads topic names, message counts, average Hz and types. `Delete` requires confirmation and permanently removes the recording and all its files; it is available only while the recorder is idle. Warning/Error badges include brief reasons, with more detail under `View topics`.

Lists and details load on demand in small radio chunks. Downloads are available through the local recorder page, not the LoRa page. The recorder agent must support these features; the maintainer handles its updates.

After recording finishes, the remote automatically refreshes the list once. When metadata arrives, it briefly shows the confirmed bag duration. Starting another recording clears the previous completion feedback. Live status includes the MCAP file count. Action errors stay visible until dismissed with `Dismiss` or replaced by a new action. Storage indicators distinguish ready and low-storage states.

## Troubleshooting

- **Serial permission denied:** run `sudo usermod -aG dialout "$USER"`, then log out and back in.
- **Multiple serial ports:** stop the controller, then run `python3 -B ~/robot-recorder/tools/lora_recorder.py open --port /dev/ttyUSB0`, choosing the correct radio. Use that command again when starting with a non-default port.
- **Radio not found:** check USB connections and the CH340 driver. BRLTTY may claim the serial interface.
- **OpenSSL missing:** on Ubuntu, run `sudo apt install openssl`.
- **Launcher error:** check `journalctl --user -u robot-recorder-lora-remote.service -n 20 --no-pager`. If an older foreground controller is running, stop it with Ctrl+C before opening the new launcher.
- **No radio reply:** check power, antennas, matching radio settings, and the recorder's recorder/LoRa services.

Share the pairing passcode privately. Do not publish decrypted `remote.json` files or private pre-paired installers. Encrypting a pairing file does not encrypt the radio messages. Range must be tested at the actual location.

The installer includes pySerial 3.5; see [Third-party notices](https://github.com/FCosx/recorder-lora-remote/blob/lenovo-recorder/THIRD_PARTY_NOTICES.md).

## Status update interval

The default is a one-second wait after each reply before the next status request. Transmission and retries take additional time, so this does not guarantee a fresh update every second. The normal startup command uses this default; the recording timer remains smooth between replies.

To use a two-second wait, stop the controller and open it with an explicit interval:

```bash
python3 -B ~/robot-recorder/tools/lora_recorder.py remote-stop
python3 -B ~/robot-recorder/tools/lora_recorder.py open --poll-seconds 2
```

To restore the default, stop it and open normally:

```bash
python3 -B ~/robot-recorder/tools/lora_recorder.py remote-stop
python3 -B ~/robot-recorder/tools/lora_recorder.py open
```

Run only one client at a time. No re-pairing or recorder restart is needed. This option changes LoRa status polling only; Ethernet/Zenoh transport and recording settings stay the same. The main-branch release v0.4.0 remains available for a full rollback to the earlier two-second version. Check long-distance behavior in the intended environment.

## Optional cloud upload

After the maintainer configures cloud access, use the controls beside **Refresh recordings** in **Recordings on the Pi**:

- **Manual upload** is the initial mode. Choose **Upload to cloud** on each completed recording you want to upload.
- Switch to **Automatic upload** and confirm to upload completed recordings when the recorder is idle, including older local recordings.
- **Stop uploads** stops compression, transfer and queued work, and returns the mode to Manual. Choose **Resume upload** on a recording to continue it; preparation or verification may repeat.
- **Cloud connected** describes the recorder's cloud connection. New uploads and mode changes are unavailable while the cloud is unreachable. Radio connectivity alone does not establish cloud access.
- MCAP files are losslessly compressed using indexed Zstandard chunks before upload. Recording takes priority: compression and transfer pause before capture starts and can resume afterward.
- **Uploaded to cloud** appears after all files pass read-back verification. Originals stay on the recorder until you choose **Delete**. Compression needs temporary free space.

The recorder uploads through its own internet connection; LoRa carries only commands and status. To browse or download cloud copies, open **https://154.8.234.96** on an internet-connected computer and sign in with an individual account supplied privately by the maintainer. See the [cloud website section of the Recorder User Manual](user-manual.md#cloud-website) for account permissions, downloads and troubleshooting. LoRa control itself still needs no site network.
