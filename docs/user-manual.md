# Robot Recorder User Manual

**English** | [简体中文](user-manual.zh-CN.md)

This guide is for the **prepared Pi + router + Ethernet switch bundle**. The robot publishes ROS 2 topics; the Pi stores MCAP recordings; a browser selects topics and controls recording. A robot with a screen can also run the browser. A separate operator laptop is optional.

Only the **robot publishing ROS topics** needs the bridge setup below. A computer used just to open the UI needs no ROS or Zenoh installation. The Pi's recording, receiving bridge and optional LoRa services are already prepared by the maintainer.

## First-time setup

### 1. Connect the bundle

Power on the router, switch and Pi. Connect the router's **LAN** port, Pi and robot to the same switch. Connect the operator laptop too, if used. Wait for the Pi to boot.

The supplied router reserves **`192.168.1.182`** for the Pi's Ethernet port. With this bundle, no address discovery or Pi login is normally needed. The robot's Ethernet should use automatic addressing (DHCP). Its existing Wi-Fi may stay connected. If the robot must retain a different fixed Ethernet address, use the troubleshooting section before changing it.

**Finish the bridge setup and start the robot's publishers before opening the UI.** If using another router or a changed bundle address, first follow “Find the Pi's wired address” below and replace `192.168.1.182` in the commands.

### 2. Install the robot bridge once

Run the following on the **robot**, as the normal ROS user. ROS 2 **Humble or Jazzy** must already be installed, and the robot needs internet for this first installation. If the robot uses a custom ROS workspace, source its usual setup script in this terminal first.

```bash
curl -q --noproxy '*' -fL --retry 2 --connect-timeout 5 --max-time 60   http://192.168.1.182:8080/setup/install_robot_bridge.sh   -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url http://192.168.1.182:8080
```

Enter the **robot's sudo password** when asked. The installer detects Humble/Jazzy, installs dependencies, builds the corrected bridge automatically and enables its startup service. If both ROS versions are installed, choose the one used by the robot. The first build may take a while; wait for **Setup complete**. If interrupted, fix the reported error or restore internet, then run the same block again while the recorder is idle.

The bridge starts automatically when the robot boots, waits for the wired network and reconnects when the Pi becomes available. **The setup terminal can be closed.** Do not start a second manual bridge. Existing installations receive automatic startup by rerunning the same setup block.

The default robot ROS domain is **0**. If its publishers use a different domain, append `--domain N` to the final command, replacing `N` with that domain. The Pi UI stays on domain **1**; the two sides intentionally use different domains.

### 3. Start the robot and open the UI

Start the robot's normal sensors and ROS publishers. On the robot or another computer connected to the switch, open:

**http://192.168.1.182:8080**

Include `http://` and `:8080`. The optional shortcut **http://robot-recorder.local:8080** works only where local-name resolution is available; it may select the Pi's Wi-Fi address. Prefer the reserved wired address for this bundle.

## Everyday recording

After the one-time setup, power on the bundle and robot, start the robot's publishers, then open the UI. No bridge command or internet connection is required for routine local recording.

1. Wait for **Ready to record**. Keep the Pi's ROS domain at **1**.
2. Click **Refresh topics**, then select the topics to save. Under **Split MCAP files**, optionally enter a size in MiB, a duration in seconds, or both. Leave both blank for one file; the first limit reached starts a new segment.
3. Click **Begin recording**. The timer starts when the recorder subscribes to the first selected topic. Completed bag duration measures the first-to-last recorded message interval, so it may differ slightly.
4. Click **Stop recording** and wait for finalization. The size may still increase while buffered messages are saved. Keep the Pi powered until it finishes.
5. In **Recordings on the Pi**, use **View topics** for size, duration, total/per-topic counts and average Hz. All MCAP segments belong to the same recording. **Download** saves a TAR copy to the computer running the browser. **Delete** permanently removes that recording from the Pi.

The local list shows 10 recordings per page. Available topics have an internal scrollbar. Opening the page or clicking **Refresh topics** requests one robot-local bandwidth snapshot of about one second. **—** means no usable estimate, not zero; selected topics show a combined estimate. Temporary subscribers save no sensor data and must close before recording starts. Estimates do not guarantee that every message will be recorded.

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

### Pi address or robot domain changed

Stop recording first. On the **robot**, enter the new wired IP and the publishers' ROS domain. This refreshes configuration and restarts the automatic service without rebuilding:

```bash
read -rp 'Pi wired IP: ' PI_IP
read -rp 'Robot publishers ROS domain: ' ROBOT_DOMAIN
curl -q --noproxy '*' -fL --retry 2 --connect-timeout 5 --max-time 60   "http://$PI_IP:8080/setup/install_robot_bridge.sh" -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url "http://$PI_IP:8080"   --configure-only --domain "$ROBOT_DOMAIN"
```

### Topics missing or counts duplicated

Confirm the robot's publishers are running, its domain matches the source bridge and the Pi UI uses domain **1**. Check the bridge service above, then **Refresh topics**. For a network test, the robot must reach the Pi on TCP port **7447**. On the Pi, `systemctl is-active robot-recorder-bridge.service robot-recorder.service` should return two `active` lines.

On the **robot**, `pgrep -af '[z]enoh-bridge-ros2dds'` should show one corrected bridge, with `zenoh-bridge-ros2dds-fixed` in its path. Stop an old manually started bridge or its old service before using this service. Do not run `/usr/bin/zenoh-bridge-ros2dds` in parallel; its version number alone does not identify the correction. If counts remain suspicious, preserve the bag and logs for the maintainer.

### Empty recording: check one live message

Keep publishers running. SSH to the Pi with `ssh recorder@192.168.1.182`, then run on the **Pi**:

```bash
source /opt/ros/jazzy/setup.bash
read -rp 'Topic to check (starting with /): ' TOPIC
timeout 10 env -u ROS_LOCALHOST_ONLY   ROS_DOMAIN_ID=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp   ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET   CYCLONEDDS_URI="file://$HOME/robot-recorder/zenoh/pi-cyclonedds.xml"   ros2 topic echo "$TOPIC" --once --no-arr
```

The Pi-local discovery profile is required for this prepared receiving domain. The command prints one message without arrays. A timeout may mean a missing link, an inactive publisher or a slow/event-driven topic; check the publisher before recording again.
