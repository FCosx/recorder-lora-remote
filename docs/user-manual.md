# Robot Recorder User Manual

**English** | [简体中文](user-manual.zh-CN.md)

This branch uses a **maintainer-prepared Lenovo running Ubuntu 24.04 / ROS 2 Jazzy**, with recordings on its **internal NVMe**. Robots publish ROS topics; the Lenovo receives them over Ethernet/Zenoh. Only the robot needs the bridge installer. A browser-only computer needs no ROS. The receiver backend, LoRa pairing and cloud access are provisioned privately by the maintainer.

Some UI labels, including **Recordings on the Pi**, still refer to the original hardware; they mean the Lenovo recorder here. This branch does not install the private backend on a blank computer.

## First-time setup

### 1. Confirm the recorder address and connect

Power on the prepared Lenovo, router and switch. Connect the recorder, robot and router **LAN** port to the same switch; connect an operator laptop if needed. The Lenovo uses internal NVMe; an external SSD is not required. If the computer is off, press its power button; service startup requires the operating system to boot.

Confirm the recorder's **wired** IP with the maintainer before setup. The current address is **192.168.1.102**. If unsure, run this on the Lenovo's own terminal and choose the Ethernet address, not Wi-Fi:

```bash
ip -4 -brief address
```

Replace `192.168.1.102` below if it differs. The robot normally uses Ethernet DHCP; Wi-Fi may remain connected. **Start the publishers and finish bridge setup before opening the UI.**

### 2. Start the robot's normal ROS programs

Start its usual sensors/publishers, then run the installer as the **same normal ROS user**. The installer detects the ROS version and initial domain from the current environment or readable running ROS nodes. It loads only the base ROS installation; no robot workspace needs to be loaded. This recorder supports standard ROS message types. Custom-type topics may still appear in the list, but are outside the supported scope. Keep the robot's existing ROS domain. If detection cannot resolve the intended environment, use the troubleshooting section below.

### 3. Install and check the bridge once

ROS 2 **Humble or Jazzy** must already be installed. Missing dependencies need internet access; the prebuilt bridge itself downloads from the recorder. Run on the **robot**, without putting `sudo` before the installer:

```bash
curl -q --noproxy '*' -fL --retry 2 --connect-timeout 5 --max-time 60 \
  http://192.168.1.102:8080/setup/install_robot_bridge.sh \
  -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url http://192.168.1.102:8080
```

Enter the **robot's sudo password** if asked. Setup selects a verified x86_64 or ARM64 bridge; no user compilation is required. It prints the detected ROS version and domain. If the ROS version is ambiguous, it asks you to choose. If no unique domain can be detected, it uses **0**; you can correct this in either UI later. Existing installations retain their saved settings and folder.

The final check reports Ethernet, the recorder service, the single corrected bridge, its helper and visible topics. Follow any **FAIL** instruction before recording. A **WARN** for no topics means the publishers may not be running yet. Wait for **Setup complete**; if interrupted, fix the reported problem and rerun while the recorder is idle.

The bridge starts automatically at boot, waits for Ethernet and reconnects when the recorder is available. **Close the setup terminal; do not start another bridge manually.** A **Robot Recorder** shortcut is added to the robot's application menu; some desktops also show a desktop copy. Setup does not open the browser before you finish.

### 4. Open the recorder

On the robot, open **Robot Recorder** from the application menu. Alternatively, on any computer connected to the switch, open:

**http://192.168.1.102:8080**

Under **Available topics**, **Robot ROS domain** shows the saved domain that the source bridge listens to. The receiving domain stays fixed at **1** and has no user selection. Include `http://` and `:8080`. Local-name access is not assumed for this Lenovo; use its confirmed wired address. A browser-only computer can bookmark that address and needs no installation.

## Everyday recording

After the one-time setup, power on the bundle and robot, start the robot's publishers, then open Robot Recorder or the saved browser address. No bridge command or internet connection is required for routine local recording.

1. Wait for **Ready to record**. Check that **Robot ROS domain** matches the robot's publishers; keep the detected value if it is correct.
2. Click **Refresh topics**, then select the topics to save. Under **Split MCAP files**, optionally enter a size in MiB, a duration in seconds, or both. Leave both blank for one file; the first limit reached starts a new segment.
3. Click **Begin recording**. The timer starts when the recorder subscribes to the first selected topic. Completed bag duration measures the first-to-last recorded message interval, so it may differ slightly.
4. Click **Stop recording** and wait for finalization. The size may still increase while buffered messages are saved. Keep the recorder powered until it finishes.
5. In **Recordings on the Pi**, use **View topics** for size, duration, total/per-topic counts and average Hz. All MCAP segments belong to the same recording. **Download** saves a TAR copy to the computer running the browser. **Delete** permanently removes that recording from the recorder.

The local list shows 10 recordings per page. Available topics have an internal scrollbar. Opening the page or clicking **Refresh topics** requests one robot-local bandwidth snapshot of about one second. **—** means no usable estimate, not zero; selected topics show a combined estimate. Temporary subscribers save no sensor data and must close before recording starts. Estimates do not guarantee that every message will be recorded.

### Change the robot ROS domain

While the recorder is idle, enter the publishers' domain (**0–232**) under **Available topics** and click **Apply domain**. Wait for **Current: …** to confirm the value, then select topics from the refreshed list. Both the LAN and LoRa pages share this setting. The robot saves it and reuses it after reboot; rerunning the installer preserves it.

This changes which domain the bridge listens to. It does not change the robot's publishers or the recorder's fixed domain **1**. A change is unavailable during recording, and recording cannot start while a change is pending. An empty/wrong domain can be corrected through the same control without SSH. If the control says **Robot connection unavailable**, check the managed bridge below; an older robot installation needs the step-3 installer update while idle.

The v2 bridge takes live Image/CompressedImage frames while retaining calibration/TF history. Brief warnings appear beside affected recordings; **View topics** gives details. **Data loss detected** means a loss was reported or verified; **Possible data loss** indicates a risk such as network saturation. **Robot connection unavailable** indicates an interrupted known robot link. An unflagged recording is not proof of complete source delivery.

Recordings are stored on the Lenovo's internal NVMe. Finish recording and wait for finalization before shutting down through Ubuntu or the maintainer's approved SSH account; do not cut power during writes. The backend's locked `recorder` service account is not the Lenovo's SSH login. Credentials are supplied privately.

## Optional enhancement: LoRa control

Follow the [LoRa Remote Guide](lora-remote.md) for distant topic selection, Start/Stop and status. The remote laptop needs no recorder IP or access to the site network; the robot-to-recorder Ethernet/Zenoh data link must still run. LoRa does not carry sensor data or bag downloads. Local recording works independently of LoRa.

## Optional cloud upload

After the maintainer configures cloud access, use the controls beside **Refresh recordings** in **Recordings on the Pi**:

- **Manual upload** is the initial mode. Choose **Upload to cloud** on each completed recording you want to upload.
- Switch to **Automatic upload** and confirm to upload completed recordings when the recorder is idle, including older local recordings.
- **Stop uploads** stops compression, transfer and queued work, and returns the mode to Manual. Choose **Resume upload** on a recording to continue it; preparation or verification may repeat.
- **Cloud connected** describes the recorder's cloud connection. New uploads and mode changes are unavailable while the cloud is unreachable. Radio connectivity alone does not establish cloud access.
- MCAP files are losslessly compressed using indexed Zstandard chunks before upload. Recording takes priority: compression and transfer pause before capture starts and can resume afterward.
- **Uploaded to cloud** appears after all files pass read-back verification. Originals stay on the recorder until you choose **Delete**. Compression needs temporary free space.

The recorder uploads through its own internet connection; LoRa carries only commands and status. Use the cloud website below to access completed uploads. For ROS playback, keep `metadata.yaml` and all referenced `.mcap` segments in the same recording folder.

## Cloud website

Open **https://154.8.234.96** on any computer with internet access. It does not need to be connected to the recorder's switch or have ROS, Zenoh or LoRa installed. The recorder needs its own internet connection to upload; local recording works independently of cloud access.

### Sign in

1. Ask the project maintainer for your **individual cloud account**. Login details are supplied privately; there is no public registration or default login in this guide.
2. Open the website and choose **Sign in**. If prompted, set your own password of at least 12 characters, then sign in again.
3. A researcher sees only the recorders assigned to their account. This website account is separate from the recorder, router and cloud-provider accounts. Contact the maintainer for account access or a password reset.

### Browse and download

- In **Recording library**, search by recording or recorder name. Each entry shows its start time, compressed size, duration and message count.
- **View topics** shows topic names, recorded counts, average Hz and ROS types.
- **Download bag** saves the complete TAR archive to the computer running the browser. Extract it and keep `metadata.yaml` and every referenced `.mcap` segment together. Individual files are also available under **View topics → Individual files**.
- **Preview data** opens **Single topic** or **Synchronized** (up to four topics). Choose topics and **Image resolution**: **Fast** (up to 480×270) or **HD** (up to 1280×720), preserving aspect ratio and never enlarging smaller images.
- Click **Start preview**. It prepares data, then plays across the recording; **Pause/Resume** controls playback. Drag the shared timeline to inspect a position; synchronized panels update together. **Stop loading** cancels preparation; **Retry preview** retries an interrupted read.
- Preview images/point clouds are sampled copies. HD is a size cap, not guaranteed original resolution. Originals and downloads are unchanged. A first uncached preparation or long recording may take longer or buffer; browser rendering and bounded caching keep full-resolution processing off the server.
- Deleting a local recording affects only its local copy. Administrators manage cloud copies separately: **Delete** moves to **Trash**, **Restore** recovers it, and confirmed **Delete permanently** frees its storage. Trash still uses space. Automatic deletion remains off; no independent bag backup is promised. Sign out on shared computers.

### For project administrators

In **Users**, choose **Researcher**, assign the required recorder(s), then **Create account**. Share the generated temporary password privately; the user changes it at first sign-in. Use **Recorder access** to adjust permissions, **Reset password** to recover access, or **Disable** to withdraw access. Ordinary cloud users need no server or cloud-provider login.

### Common problems

- **Website will not open:** check the internet connection and the full `https://` address, then contact the maintainer if it remains unavailable. No special networking client is required for this cloud website.
- **Sign-in fails:** ask the maintainer to check the account or reset its password.
- **A recording is missing:** confirm **Uploaded to cloud** on the recorder/LoRa page, refresh the cloud library, and ask the maintainer to check your recorder permissions. An unfinished upload is not listed as complete.

## Troubleshooting

### Cannot reach the recorder

On the **computer that cannot connect**, check:

```bash
ip -4 route get 192.168.1.102
curl -q --noproxy '*' -fsS --connect-timeout 3 --max-time 6   http://192.168.1.102:8080/api/status
```

The route should use the Ethernet interface connected to the switch, and the request should return status JSON. If it uses Wi-Fi, check the Ethernet cable and address. If the direct request works but the browser shows **502**, bypass the proxy for the recorder's confirmed wired IP. Check recorder power and its NVMe storage if the recorder service is unavailable. The local UI has no login; keep it on a trusted local network.

### Find the recorder's wired address

Use `ip -4 -brief address` on the Lenovo, or the router's device list. Choose the interface connected to the switch (currently `eno1`). Do not assume the Pi's old `eth0`, hostname or reserved address applies to this host. Ask the maintainer if you cannot access the recorder console.

### Robot Ethernet is on a different subnet

A cable connection alone does not put fixed addresses on the same subnet. If the robot must retain its existing address, ask the network administrator for an unused address/prefix on the recorder's subnet. Add it temporarily while keeping the original address:

```bash
read -rp 'Ethernet interface connected to the switch: ' LAN_IF
read -rp 'Administrator-assigned unused IPv4 address/prefix: ' LAN_ADDR
sudo ip -4 addr add "$LAN_ADDR" dev "$LAN_IF"
ip -4 route get 192.168.1.102
```

Do not guess an address. This addition is lost after reboot; ask the administrator to make it persistent if needed. Wi-Fi may stay connected. The bridge waits until a direct wired route to the recorder is available.

### Run the combined setup check

On the **robot**, using the installation account:

```bash
python3 -B ~/robot-recorder/tools/check_robot_setup.py
```

This is read-only and safe during recording: it does not restart services, subscribe to sensor streams or estimate bandwidth. For a custom installation folder, replace `~/robot-recorder` with that folder.

### ROS settings were not detected

Run setup as the normal account that runs the robot's ROS programs. Root/container processes or domains set inside a program may not be readable. An unknown or ambiguous domain defaults to **0**; use **Robot ROS domain → Apply domain** in either UI to correct it.

If ROS-version detection needs an override, rerun the installer with the installed version. This example explicitly selects Humble and source domain 5:

```bash
bash /tmp/install_robot_bridge.sh --pi-url http://192.168.1.102:8080 \
  --ros-distro humble --domain 5
```

For Jazzy use `--ros-distro jazzy`. No workspace setup path is needed. `--domain` sets the bridge's listening domain, not the publishers' domain. If no compatible prebuilt package is available, setup stops without replacing the existing bridge; ask the maintainer for a tested package.

### Check, restart or stop the robot bridge

On the **robot**, using the same account that installed it:

```bash
systemctl --user status robot-recorder-source-bridge.service --no-pager
journalctl --user -u robot-recorder-source-bridge.service -n 30 --no-pager
```

Only while the recorder is idle, use the required command:

```bash
systemctl --user restart robot-recorder-source-bridge.service  # Recover/reload
systemctl --user stop robot-recorder-source-bridge.service     # Disconnect intentionally
systemctl --user start robot-recorder-source-bridge.service    # Reconnect
```

These are alternatives; do not run all three for a status check. Killing a managed bridge process causes it to restart automatically. A stopped service remains enabled for the next boot.

### Stop now and disable automatic startup

When finished using the recorder, stop any recording first. On the **robot**, using the same account that installed the bridge, run:

```bash
systemctl --user disable --now robot-recorder-source-bridge.service
```

This stops the bridge immediately and prevents it from starting after reboot. Installed files and saved settings remain. Closing the browser or disconnecting the bundle alone does not disable automatic startup.

To start it again and restore automatic startup later:

```bash
systemctl --user enable --now robot-recorder-source-bridge.service
```

No reinstall is needed. Rerunning the installer also enables automatic startup.

### recorder address changed

A robot ROS-domain change only needs **Apply domain** in either UI. If the recorder's wired IP changed, stop recording first and update the robot's saved recorder address:

```bash
read -rp 'recorder wired IP: ' PI_IP
curl -q --noproxy '*' -fL --retry 2 --connect-timeout 5 --max-time 60 \
  "http://$PI_IP:8080/setup/install_robot_bridge.sh" -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url "http://$PI_IP:8080" --configure-only
```

This preserves the saved robot domain and restarts the automatic bridge without rebuilding it.

### Topics missing or counts duplicated

Confirm the robot's publishers are running, its domain matches **Robot ROS domain** in the UI and the recorder receiver stays on domain **1**. Check the bridge service above, then **Refresh topics**. For a network test, the robot must reach the recorder on TCP port **7447**. On the recorder, `systemctl is-active robot-recorder-bridge.service robot-recorder.service` should return two `active` lines.

On the **robot**, `pgrep -af '[z]enoh-bridge-ros2dds'` should show one corrected bridge, with `zenoh-bridge-ros2dds-fixed` in its path. Stop an old manually started bridge or its old service before using this service. Do not run `/usr/bin/zenoh-bridge-ros2dds` in parallel; its version number alone does not identify the correction. If counts remain suspicious, preserve the bag and logs for the maintainer.

### Empty recording or suspicious counts

Run the combined setup check on the robot, confirm the publisher/domain and preserve the recording and its logs for the maintainer. Warning details may report cache loss, link interruption or UDP receive-buffer overflow. Packet drops are a **risk signal**, not an exact missing-message count; no warning does not prove complete publisher delivery.
