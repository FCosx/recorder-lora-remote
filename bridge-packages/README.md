# Corrected bridge packages — Lenovo branch

The prepared receiver serves verified x86_64 and ARM64 packages for Humble/Jazzy (glibc 2.35 or newer); users run the manual's command and do not compile. Matching archives are attached to the [Lenovo prerelease](https://github.com/FCosx/recorder-lora-remote/releases/tag/lenovo-v0.13.0). The catalog pins upstream Zenoh 1.10.1, the combined patch and both archive/binary checksums; each archive includes BUILD.json and upstream license/notices.

Version **route-listener-v2** retains the listener-lifetime duplication fix and uses live VOLATILE history specifically for Image/CompressedImage routes. Calibration/TF and other non-image retained topics keep their semantics. The installer provisions bounded 4-MiB source DDS receive buffers and a sufficient kernel ceiling without changing the robot's routes or workspace. Orin NX/Humble installation and real-sensor regression passed; universal performance or complete delivery is not guaranteed.

The receiver backend and its own DDS profile are maintainer-provisioned. Installing this robot-side bridge does not install a receiver backend. The Pi main branch's v1 catalog is separate.
