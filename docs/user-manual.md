# Robot Recorder User Manual

**English** | [简体中文](user-manual.zh-CN.md)

This guide is for first-time users receiving a Pi that the maintainer has already configured. It does not cover deploying the recorder onto a blank Pi. The robot publishes ROS 2 topics; the Pi receives them and saves MCAP files; the browser selects topics and controls recording. A robot host with a display, such as an Orin, can open the page directly. A separate operator laptop is optional. The Pi's Zenoh bridge is already prepared; a new robot needs its own bridge.

The robot must already have ROS 2 Humble or Jazzy. Complete the one-time bridge setup below with internet access. Routine recording only needs the local robot-to-Pi network: connect the devices, start the robot bridge and publishers, then select topics in the browser.

## Normal workflow

### 1. Connect the devices and confirm the Pi's wired IP

Power on the Pi and wait for it to boot. Connect the cellular router's LAN port, the Pi and the robot to the **same Ethernet switch**. Connect the operator laptop too if using one. The router supplies local addresses and cellular internet; local recording does not depend on cellular internet. The IR2700-R used in this setup does not provide the Wi-Fi access point needed for this arrangement. The robot's existing Wi-Fi can stay connected.

**Complete steps 1–3 in the terminal before opening the recorder UI in step 4.** First find a Pi address from the **robot or operator laptop**:

```bash
timeout 5 getent ahostsv4 robot-recorder.local | awk '{print $1}' | sort -u
```

If this returns no address, name discovery is unavailable on this device. Find the Pi's wired lease in the router's DHCP device list, or use a keyboard/display on the **Pi** and run:

```bash
ip -4 -brief address show dev eth0
```

The Pi's SSH username is usually **`recorder`**; ask the maintainer for its password. On first connection, check the host information before accepting it. Password entry does not display characters. Replace `recorder` in the commands if the maintainer uses another username.

Back on the **robot or operator laptop**, enter the address you found and confirm the Pi's Ethernet address over SSH:

```bash
read -rp 'Pi address found above: ' PI_ADDR
ssh "recorder@$PI_ADDR" 'hostname; ip -4 -brief address show dev eth0'
```

If the Pi has both Wi-Fi and Ethernet, a name lookup may return its Wi-Fi address, even if it returns only one result. Use the IPv4 address on the `eth0` line for setup, without `/24` or another prefix length. If `eth0` has no IPv4 address, check the Pi cable, switch and router DHCP first.

On the **robot**, enter that confirmed wired address and verify the route and recorder service from the terminal:

```bash
read -rp 'Pi wired IP (eth0): ' PI_IP
ip -4 route get "$PI_IP"
curl -q --noproxy '*' -fsS --connect-timeout 3 --max-time 6 \
  "http://$PI_IP:8080/api/status"
```

The route should use the Ethernet interface connected to the switch, and the service should return JSON status. Continue to step 2 after both checks succeed. If the route uses Wi-Fi or the request fails, use the troubleshooting section below. Normally you do not need to change the robot's IP or disconnect its Wi-Fi. Keep the wired address for the remaining steps; the browser is opened only after setup.

### 2. Install and configure the robot bridge once

The robot needs ROS 2 Humble or Jazzy and internet access for installation. The following commands fetch the installer from the prepared Pi. It installs dependencies, prepares the corrected Zenoh bridge and configures the Pi address. **Copy and paste the commands; no manual package transfer, source editing or build commands are required.**

In the **robot terminal**, paste the block below and enter the wired Pi address confirmed from `eth0` in step 1:

```bash
read -rp 'Pi wired IP: ' PI_IP
curl -q --noproxy '*' -f --retry 3 --retry-all-errors --connect-timeout 5 \
  "http://$PI_IP:8080/setup/install_robot_bridge.sh" -o /tmp/install_robot_bridge.sh &&
bash /tmp/install_robot_bridge.sh --pi-url "http://$PI_IP:8080"
```

Enter the robot's sudo password when prompted and wait for `Setup complete`. The script detects the installed ROS distribution; if both Humble and Jazzy are present, it asks which to use. It automatically builds the bridge locally on first installation, which can take a while. If interrupted, fix the error or restore connectivity, then rerun the same block.

The installed files and configuration are under the robot user's `~/robot-recorder/`. The default robot ROS domain is **0**; the Pi recorder uses domain **1**. After starting the bridge in step 3, open the browser in step 4 to check the robot's topics. The corrected bridge has passed repeated-restart tests on the development laptop; its first deployment on an Orin still needs on-device validation.

### 3. Start the robot bridge each time

Run this in the **robot terminal** and keep the terminal open during recording:

```bash
bash ~/robot-recorder/tools/start_robot_bridge.sh
```

Run one robot bridge at a time. Exit any earlier manually started bridge first; if an original bridge runs as a service, stop that service first. Running `zenoh-bridge-ros2dds -c ...` directly may launch the uncorrected system version.

Start the robot's sensors and ROS publishers, and leave the bridge running. Setup is now ready for the browser step below.

### 4. Open the UI, record and inspect data

Only after completing steps 1–3, use the **wired IP confirmed in step 1** to open the UI. On the robot or operator laptop, print the address:

```bash
read -rp 'Pi wired IP confirmed in step 1: ' PI_IP
printf 'Recorder URL: http://%s:8080\n' "$PI_IP"
```

Open the printed URL in that computer's browser. Include `http://` and `:8080`. If `.local` resolution works on this computer, **http://robot-recorder.local:8080** is an optional shortcut; use the confirmed wired IP if it fails or resolves to an unsuitable interface.

1. Wait for `Ready to record` and keep the UI's ROS domain at **1**. Keep the robot bridge running.
2. Click `Refresh topics` and select the topics to save. To split a long recording, enter a size in MiB, a duration in seconds, or both under `Split MCAP files`. Leave both blank to disable splitting. Click `Begin recording`. A listed topic is not proof that messages are currently arriving. If expected topics are missing, see troubleshooting.
3. Click `Stop recording` when finished and wait for finalization. Keep the Pi powered during this process.
4. Under `Recordings on the Pi`, click the recording's `View topics` to inspect per-topic message counts. Split MCAP files belong to one recording: expand its file list to inspect segments; `View topics` summarizes the whole recording. `Download` saves a TAR copy containing all segments to the browser's computer. `Delete` permanently removes that recording and all its segments from the Pi.

The size setting is a split trigger, not a strict file-size ceiling: buffered messages can make a segment exceed it. If both limits are set, the first reached triggers a new segment; the last is usually shorter. `Ready to record` confirms that the service is available. Confirm received data using the completed recording's message counts and result. Files remain on the Pi unless a user downloads a copy.

## Optional enhancement: LoRa remote control

Add compatible LoRa radios and an operator laptop for topic selection, Start/Stop, status and brief recording management from a distance. Follow the [LoRa Remote Guide](lora-remote.md). The installer can be supplied offline by the maintainer or downloaded from [GitHub](https://github.com/FCosx/recorder-lora-remote). The maintainer supplies the initial pairing passcode privately.

The LoRa laptop needs no Pi IP, SSH or access to the site network. Keep the robot-to-Pi Ethernet/Zenoh data link running. MCAP files are saved on the Pi; use the local network page to download them. The local page independently supports recording, splitting, inspection, downloads and deletion without LoRa setup.

## Troubleshooting

### Confirm the Pi's wired IP

On the **robot or operator laptop**:

```bash
timeout 5 getent ahostsv4 robot-recorder.local | awk '{print $1}' | sort -u
```

Name resolution does not label which interface owns an address. With both Wi-Fi and Ethernet on the Pi, it may return only Wi-Fi. Confirm Ethernet separately:

```bash
ssh recorder@robot-recorder.local 'ip -4 -brief address show dev eth0'
```

Use the login details described in step 1. Enter the IPv4 address without `/24` when configuring the bridge. The command still checks Ethernet even if SSH itself connects over Wi-Fi.

To inspect the Pi's Wi-Fi address:

```bash
ssh recorder@robot-recorder.local 'ip -4 -brief address show dev wlan0'
```

An IPv4 address on `wlan0` indicates that the wireless interface is configured. Use the `eth0` address for the robot bridge. If the name does not resolve, check power and cables, or find the wired lease in the router's DHCP device list. Do not guess an address.

### Cannot open the page

1. Use `http://<PI_WIRED_IP>:8080`, replacing `<PI_WIRED_IP>` with the wired address confirmed in step 1. Include `http://` and `:8080`.
2. On the computer running the browser, check the route and direct service response:

   ```bash
   read -rp 'Pi wired IP: ' PI_IP
   ip -4 route get "$PI_IP"
   curl -q --noproxy '*' -fsS --connect-timeout 3 --max-time 6 \
     "http://$PI_IP:8080/api/status"
   ```

3. If the wired IP works but the optional `.local` shortcut fails, run `getent ahostsv4 robot-recorder.local` on this computer. Name resolution is not required to continue with the wired IP. For `.local` resolution, check `systemctl is-active avahi-daemon.service` on the Pi and ensure the network permits mDNS multicast; ask the maintainer to configure it if needed.
4. If direct command-line access works but the browser shows **502**, add the Pi's wired IP and, if used, `robot-recorder.local` to the browser/system proxy bypass list.
5. If direct access still fails, check Pi power, Ethernet and the wired IP in the router's DHCP list. On the Pi, check `systemctl is-active robot-recorder.service`. If routing uses Wi-Fi, follow the next section.

### Traffic uses the wrong interface

If the robot has both Wi-Fi and Ethernet, and the name resolves but the page times out, confirm the Pi's **wired IP**, then check routing on the robot:

```bash
read -rp 'Pi wired IP: ' PI_IP
ip -4 route get "$PI_IP"             # dev should name the Ethernet interface connected to the switch
ip -4 -brief address                 # Check for an Ethernet address on the same subnet
```

Plugging in a cable does not guarantee both devices are on the same IPv4 subnet. If the route shows Wi-Fi, investigate the Ethernet address before changing anything.

If an additional same-subnet address is needed, ask the network administrator for an unused address that will not conflict with DHCP, with the correct prefix. Absence from a DHCP lease list alone does not prove an address is unused. These commands add a temporary address while retaining the interface's original address:

```bash
read -rp 'Pi wired IP: ' PI_IP
read -rp 'Ethernet interface connected to the switch: ' LAN_IF
read -rp 'Assigned unused IPv4 address/prefix on that subnet: ' LAN_ADDR
sudo ip -4 addr add "$LAN_ADDR" dev "$LAN_IF"  # Temporary; lost after reboot
ip -4 route get "$PI_IP"                  # dev should now be the Ethernet interface above
curl --noproxy '*' --connect-timeout 3 "http://$PI_IP:8080/api/status"
```

Reapply the temporary address after a reboot or ask an administrator to configure it persistently. Wi-Fi can stay connected. If routing already uses the correct Ethernet interface, check the web response instead of adding an address.

### The Pi IP or robot ROS domain changed

Press Ctrl+C in the bridge terminal. In the **robot terminal**, enter the new Pi wired IP and replace `--domain 0` with the robot publishers' actual domain. This updates the configuration without reinstalling:

```bash
read -rp 'Pi wired IP: ' PI_IP
bash /tmp/install_robot_bridge.sh --pi-url "http://$PI_IP:8080" --configure-only --domain 0
bash ~/robot-recorder/tools/start_robot_bridge.sh
```

If the temporary installer script was removed, first download it again using step 2.

### Robot topics are missing

Check that the robot is publishing and its bridge is running, then click `Refresh topics`. The robot bridge must use the publishers' domain (**0** in this project's tests); the Pi UI uses domain **1**. Check the Pi IP in the robot's `robot.json5`. Use the configuration update above if the IP or domain changed. TCP port **7447** must be reachable from the robot to the Pi.

If topics remain missing, connect over SSH using the confirmed Pi wired IP as in step 1, then check both services on the **Pi**:

```bash
systemctl is-active robot-recorder-bridge.service robot-recorder.service
```

Both should report `active`.

### Message counts are unusually high or duplicated

On the **robot**, inspect bridge processes:

```bash
pgrep -af '[z]enoh-bridge-ros2dds'
```

There should be one bridge process, with a path containing `zenoh-bridge-ros2dds-fixed`. If it is `/usr/bin/zenoh-bridge-ros2dds`, stop the old bridge and start the corrected version using step 3. The version number alone does not identify the patch: both report 1.10.1.

Compare the average recorded Hz in `View topics` with the robot's actual publishing rate. If counts remain suspicious with the corrected bridge, preserve the bag and logs for the maintainer.

### A recording contains no messages

Keep the robot publishers running and connect over SSH using the confirmed Pi wired IP as in step 1. Run this on the **Pi**:

```bash
source /opt/ros/jazzy/setup.bash
read -rp 'Robot topic to check (starting with /): ' TOPIC
timeout 10 env -u ROS_LOCALHOST_ONLY \
  ROS_DOMAIN_ID=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET \
  ros2 topic echo "$TOPIC" --once --no-arr
```

This prints one message and exits, omitting array contents. If nothing arrives within ten seconds, check that the topic is currently publishing. Slow or event-driven topics may require more time or a trigger. If a continuously published topic is still silent, fix the bridge connection before recording again.

The web page currently has no login; use it on a trusted local network. The prepared Pi supplies the bridge installer and corrected bridge resources. You do not need to clone this GitHub repository first.
