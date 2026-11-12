# Lenovo recorder validation — 2026-11-12

**English** | [简体中文](lenovo-validation.zh-CN.md)

Receiver: Lenovo Ryzen 7 8845HS / 32 GB, Ubuntu 24.04.5, ROS 2 Jazzy, internal 1-TB Lexar NVMe/ext4. Source: Orin NX / approximately 16 GB, Ubuntu 22.04.5 / L4T 36.4.7, ROS 2 Humble. Wired transport uses the corrected Zenoh 1.10.1 v2 bridge; receiver domain 1, current source domain 99. Standard messages only.

| Check | Verified result |
|---|---|
| Fresh robot setup | ARM64 prebuilt package, detected Humble/domain, one source bridge/helper, persistent service; no user compilation/workspace detection |
| New-registration readiness | Fixed coordinator/check ordering; isolated real registration connected in 0.203 s without first querying Topics |
| Six-topic split recording | 12.826 s, 9 segments, 626 messages; RGB 182/182, depth 192/192 and scan 128/128 matched an independent reliable source reference within recorded endpoints; no additional missing or duplicate images |
| Late LoRa recording | Selection/start/stop/splitting/details worked; images were fresh and unique; calibration/TF history preserved |
| Repeated recordings | Three 46-message captures, continuous unique sequences, one source reader each, temporary bandwidth estimation idle during capture |
| Bridge interruption | Automatic recovery; correct warning and one sequence gap covering the deliberate outage; fresh unique images after recovery |
| Receive-buffer warning | Isolated tiny-buffer fault produced 420 actual UDP packet drops; both UIs showed possible-loss warnings. Packet count is not a missing-message count |
| Domain controls | LAN changed source to 0, LoRa restored 99, saved on robot; receiver remained 1 |
| Complete-project regression | Maintainer's private/full project: 222 Python tests, 8 JS test files, 21 Rust tests passed. The public branch contains only its applicable subset: 115 Python checks passed, 10 private-backend checks skipped, and 4 JS test files passed |

The receiver/LoRa/cloud functions were restored and tested with NVMe; cloud upload stays Manual by default. Recording has priority over compression/upload. The earlier 333-second, approximately 5.16-MiB/s synthetic functional test had continuous unique sequences, but **the Lenovo rate limit is not measured**. A 5-MiB/s-step benchmark with temperature monitoring and longer boundary confirmation is planned, not completed.

Known boundaries: source-side RGB timing gaps may occur; non-image latched history can replay identical samples; warning coverage is not an end-to-end completeness guarantee. The NX's invalid duplicate RealSense repositories were disabled with backups; APT works and installed drivers were preserved. Vendor signing must be repaired before those entries can be re-enabled. No new v2 physical-reboot, disk-full or long-range radio acceptance is claimed. Original Pi throughput and USB/SSD results do not define Lenovo performance.

Only public setup/client components and documentation are published here. Private recorder/cloud code, credentials, pairing plaintext, databases, raw test bags and maintenance logs are excluded. This branch does not change the stable Pi release.
