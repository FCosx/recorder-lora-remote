# Robot Recorder User Manual

**English** | [简体中文](user-manual.zh-CN.md)

This guide is for the **prepared Pi + router + Ethernet switch bundle**. The robot publishes ROS 2 topics; the Pi stores MCAP recordings; a browser selects topics and controls recording. A robot with a screen can also run the browser. A separate operator laptop is optional.

Only the **robot publishing ROS topics** needs the bridge setup below. A computer used just to open the UI needs no ROS or Zenoh installation. The Pi's recording, receiving bridge and optional LoRa services are already prepared by the maintainer.

## First-time setup

### 1. Connect the bundle

Power on the router, switch and Pi. Connect the router's **LAN** port, Pi and robot to the same switch. Connect the operator laptop too, if used. Keep the prepared SSD connected. Wait for the Pi to boot; if it stays at a red power LED, press its power button once.

The supplied router reserves **`192.168.1.182`** for the Pi's Ethernet port. With this bundle, no address discovery or Pi login is normally needed. The robot's Ethernet should use automatic addressing (DHCP). Its existing Wi-Fi may stay connected. If the robot must retain a different fixed Ethernet address, use the troubleshooting section before changing it.

**Finish the bridge setup and start the robot's publishers before opening the UI.** If using another router or a changed bundle address, first follow “Find the Pi's wired address” below and replace `192.168.1.182` in the commands.

### 2. Start the robot's normal ROS programs

Start its usual sensors/publishers, then run the installer as the **same normal ROS user**. The installer detects the ROS version and initial domain from the current environment or readable running ROS nodes. It loads only the base ROS installation; no robot workspace needs to be loaded. This recorder supports standard ROS message types. Custom-type topics may still appear in the list, but are outside the supported scope. Keep the robot's existing ROS domain. If detection cannot resolve the intended environment, use the troubleshooting section below.

### 3. Install and check the bridge once

ROS 2 **Humble or Jazzy** must already be installed. Missing dependencies need internet access; the prebuilt bridge itself downloads from the Pi. Run on the **robot**, without putting `sudo` before the installer:

```bash
curl -q --noproxy '*' -fL --retry 2 --connect-timeout 5 --max-time 60 \
  http://192.168.1.182:8080/setup/install_robot_bridge.sh \
  -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url http://192.168.1.182:8080
```

Enter the **robot's sudo password** if asked. Setup selects a verified x86_64 or ARM64 bridge; no user compilation is required. It prints the detected ROS version and domain. If the ROS version is ambiguous, it asks you to choose. If no unique domain can be detected, it uses **0**; you can correct this in either UI later. Existing installations retain their saved settings and folder.

The final check reports Ethernet, the Pi recorder, the single corrected bridge, its helper and visible topics. Follow any **FAIL** instruction before recording. A **WARN** for no topics means the publishers may not be running yet. Wait for **Setup complete**; if interrupted, fix the reported problem and rerun while the recorder is idle.

The bridge starts automatically at boot, waits for Ethernet and reconnects when the Pi is available. **Close the setup terminal; do not start another bridge manually.** A **Robot Recorder** shortcut is added to the robot's application menu; some desktops also show a desktop copy. Setup does not open the browser before you finish.

### 4. Open the recorder

On the robot, open **Robot Recorder** from the application menu. Alternatively, on any computer connected to the switch, open:

**http://192.168.1.182:8080**

Under **Available topics**, **Robot ROS domain** shows the saved domain that the source bridge listens to. The Pi's receiving domain stays fixed at **1** and has no user selection. Include `http://` and `:8080`. The optional **http://robot-recorder.local:8080** depends on local-name support and may select Wi-Fi; prefer the bundle's wired address. A browser-only computer can bookmark that address and needs no installation.

## Everyday recording

After the one-time setup, power on the bundle and robot, start the robot's publishers, then open Robot Recorder or the saved browser address. No bridge command or internet connection is required for routine local recording.

1. Wait for **Ready to record**. Check that **Robot ROS domain** matches the robot's publishers; keep the detected value if it is correct.
2. Click **Refresh topics**, then select the topics to save. Under **Split MCAP files**, optionally enter a size in MiB, a duration in seconds, or both. Leave both blank for one file; the first limit reached starts a new segment.
3. Click **Begin recording**. The timer starts when the recorder subscribes to the first selected topic. Completed bag duration measures the first-to-last recorded message interval, so it may differ slightly.
4. Click **Stop recording** and wait for finalization. The size may still increase while buffered messages are saved. Keep the Pi powered until it finishes.
5. In **Recordings on the Pi**, use **View topics** for size, duration, total/per-topic counts and average Hz. All MCAP segments belong to the same recording. **Download** saves a TAR copy to the computer running the browser. **Delete** permanently removes that recording from the Pi.

The local list shows 10 recordings per page. Available topics have an internal scrollbar. Opening the page or clicking **Refresh topics** requests one robot-local bandwidth snapshot of about one second. **—** means no usable estimate, not zero; selected topics show a combined estimate. Temporary subscribers save no sensor data and must close before recording starts. Estimates do not guarantee that every message will be recorded.

### Change the robot ROS domain

While the recorder is idle, enter the publishers' domain (**0–232**) under **Available topics** and click **Apply domain**. Wait for **Current: …** to confirm the value, then select topics from the refreshed list. Both the LAN and LoRa pages share this setting. The robot saves it and reuses it after reboot; rerunning the installer preserves it.

This changes which domain the bridge listens to. It does not change the robot's publishers or the Pi's fixed domain **1**. A change is unavailable during recording, and recording cannot start while a change is pending. An empty/wrong domain can be corrected through the same control without SSH. If the control says **Robot connection unavailable**, check the managed bridge below; an older robot installation needs the step-3 installer update while idle.

Brief warnings appear beside affected recordings; **View topics** gives details. **Data loss detected** means a loss was reported or verified; **Possible data loss** indicates a risk such as network saturation. **Robot connection unavailable** indicates an interrupted known robot link. An unflagged recording is not proof of complete source delivery.

The Pi stores recordings on its configured recording drive. The current bundle requires its prepared SSD to be connected; keep it connected during use. To shut down safely, finish recording and any transfer, then run this from a connected computer:

```bash
ssh -tt recorder@192.168.1.182 'sudo poweroff'
```

Ask the maintainer for the Pi login password. Wait for shutdown to finish before removing power.

## Optional enhancement: LoRa control

Follow the [LoRa Remote Guide](lora-remote.md) for distant topic selection, Start/Stop and status. The remote laptop needs no Pi IP or access to the site network; the robot-to-Pi Ethernet/Zenoh data link must still run. LoRa does not carry sensor data or bag downloads. Local recording works independently of LoRa.

## Optional cloud upload

After the maintainer configures cloud access, use the controls beside **Refresh recordings** in **Recordings on the Pi**:

- **Manual upload** is the initial mode. Choose **Upload to cloud** on each completed recording you want to upload.
- Switch to **Automatic upload** and confirm to upload completed recordings when the Pi is idle, including older local recordings.
- **Stop uploads** stops compression, transfer and queued work, and returns the mode to Manual. Choose **Resume upload** on a recording to continue it; preparation or verification may repeat.
- **Cloud connected** describes the Pi's cloud connection. New uploads and mode changes are unavailable while the cloud is unreachable. Radio connectivity alone does not establish cloud access.
- MCAP files are losslessly compressed using indexed Zstandard chunks before upload. Recording takes priority: compression and transfer pause before capture starts and can resume afterward.
- **Uploaded to cloud** appears after all files pass read-back verification. Originals stay on the Pi until you choose **Delete**. Compression needs temporary free space.

The Pi uploads through its own internet connection; LoRa carries only commands and status. The maintainer supplies cloud accounts and the download address. For ROS playback, download `metadata.yaml` and every referenced `.mcap` file into the same folder.

## Troubleshooting

### Cannot reach the Pi

On the **computer that cannot connect**, check:

```bash
ip -4 route get 192.168.1.182
curl -q --noproxy '*' -fsS --connect-timeout 3 --max-time 6   http://192.168.1.182:8080/api/status
```

The route should use the Ethernet interface connected to the switch, and the request should return status JSON. If it uses Wi-Fi, check the Ethernet cable and address. If the direct request works but the browser shows **502**, bypass the proxy for the Pi's IP and, if used, `robot-recorder.local`. Check Pi power and the SSD if the recorder service is unavailable. The local UI has no login; keep it on a trusted local network.

### Find the Pi's wired address

This is needed if the router or its configuration changed. First check the router's DHCP lease list for `robot-recorder`. Alternatively, on the **robot or operator laptop**:

```bash
timeout 5 getent ahostsv4 robot-recorder.local | awk '{print $1}' | sort -u
ssh recorder@robot-recorder.local 'ip -4 -brief address show dev eth0'
```

The first command may return Wi-Fi. Use the IPv4 address on the **eth0** line, without `/24`. Ask the maintainer for the Pi password. If the name does not resolve, attach a display/keyboard to the **Pi** and run `ip -4 -brief address show dev eth0`, or use the router's lease list. No eth0 address means its wired connection/DHCP needs attention.

### Robot Ethernet is on a different subnet

A cable connection alone does not put fixed addresses on the same subnet. If the robot must retain its existing address, ask the network administrator for an unused address/prefix on the Pi's subnet. Add it temporarily while keeping the original address:

```bash
read -rp 'Ethernet interface connected to the switch: ' LAN_IF
read -rp 'Administrator-assigned unused IPv4 address/prefix: ' LAN_ADDR
sudo ip -4 addr add "$LAN_ADDR" dev "$LAN_IF"
ip -4 route get 192.168.1.182
```

Do not guess an address. This addition is lost after reboot; ask the administrator to make it persistent if needed. Wi-Fi may stay connected. The bridge waits until a direct wired route to the Pi is available.

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
bash /tmp/install_robot_bridge.sh --pi-url http://192.168.1.182:8080 \
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

### Pi address changed

A robot ROS-domain change only needs **Apply domain** in either UI. If the Pi's wired IP changed, stop recording first and update the robot's saved Pi address:

```bash
read -rp 'Pi wired IP: ' PI_IP
curl -q --noproxy '*' -fL --retry 2 --connect-timeout 5 --max-time 60 \
  "http://$PI_IP:8080/setup/install_robot_bridge.sh" -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url "http://$PI_IP:8080" --configure-only
```

This preserves the saved robot domain and restarts the automatic bridge without rebuilding it.

### Topics missing or counts duplicated

Confirm the robot's publishers are running, its domain matches **Robot ROS domain** in the UI and the Pi receiver stays on domain **1**. Check the bridge service above, then **Refresh topics**. For a network test, the robot must reach the Pi on TCP port **7447**. On the Pi, `systemctl is-active robot-recorder-bridge.service robot-recorder.service` should return two `active` lines.

On the **robot**, `pgrep -af '[z]enoh-bridge-ros2dds'` should show one corrected bridge, with `zenoh-bridge-ros2dds-fixed` in its path. Stop an old manually started bridge or its old service before using this service. Do not run `/usr/bin/zenoh-bridge-ros2dds` in parallel; its version number alone does not identify the correction. If counts remain suspicious, preserve the bag and logs for the maintainer.

### Empty recording: check one live message

Keep publishers running. SSH to the Pi with `ssh recorder@192.168.1.182`, then run on the **Pi**:

```bash
source /opt/ros/jazzy/setup.bash
read -rp 'Topic to check (starting with /): ' TOPIC
timeout 10 env -u ROS_LOCALHOST_ONLY   ROS_DOMAIN_ID=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp   ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET   CYCLONEDDS_URI="file://$HOME/robot-recorder/zenoh/pi-cyclonedds.xml"   ros2 topic echo "$TOPIC" --once --no-arr
```

The Pi-local discovery profile is required for this prepared receiving domain. The command prints one message without arrays. A timeout may mean a missing link, an inactive publisher or a slow/event-driven topic; check the publisher before recording again.
