# M-A202 Bi-Directional Stereo Hi-Fi Audio Extender - Reverse Engineering & Linux Tools

> [!CAUTION]
> ## <img src="https://img.shields.io/badge/!!-DON'T_BUY_IF_YOU_DIDN'T_ALREADY_HAVE-red?style=for-the-badge&labelColor=red&color=red&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJ3aGl0ZSI+PHBhdGggZD0iTTEyIDJMMS43NSAyMS41aDIwLjVMMTIgMnptMCAxNC41Yy0uNTUgMC0xLS40NS0xLTFzLjQ1LTEgMS0xIDEgLjQ1IDEgMS0uNDUgMS0xIDF6bTEtM2gtMlY5aDJ2NC41eiIvPjwvc3ZnPg==" alt="Warning">
> **It does not even work as intended - neither as back-to-back solution nor as multipoint solution as shown in the [manual](M-A202_Manual_Scanned.pdf). Broken auto-negotiation (won't link to any standard switch), proprietary undocumented protocol, 50% audio duty cycle in default mode, firmware metadata bug causing clicks on the hardware RX, built-in rogue DHCP server, needs Linux bridge with forced 100Mbps. The manual claims "24bit/96KHz", "plug-and-play", "no configuration required" - none of this is true. Everything documented here took a full day of reverse engineering just to get basic audio working.**

![M-A202 TX and RX Units](images/M-A202_TX_RX_units.png)
*M-A202 TX (bottom) and RX (top) units - "Stereo Hi-Fi Audio Extender" with RCA audio and Ethernet*

## Overview

The **M-A202** is a pair of TX/RX devices sold on AliExpress as a "Bi-Directional Audio Extender" (~100 USD). Each unit has an RJ45 Ethernet port, 2x RCA audio input, 2x RCA audio output, a reset button, and a power connector.

This repository documents the **reverse-engineered protocol** and provides **Python scripts** to send and receive audio using standard Linux tools (sox, ffmpeg, VLC, aplay, etc.).

### Key Findings

- Audio is **48 kHz / 16-bit stereo uncompressed PCM** (could be better than CD quality, if done right)
- **Two different protocols per direction:**
  - **Forward (TX→RX):** UDP multicast with proprietary `0xDEADBEEF` header, 3 packets per frame
  - **Return (RX→TX):** Raw PCM over TCP port 7005 - **no headers at all**, full rate, perfect quality
- The return TCP path is the **cleaner protocol** - no metadata bugs, no packet loss (TCP retransmit), continuous 192 KB/s
- Internally this is an **HDMI-over-IP extender** chipset (model LKDCAA, FW V5.8) repurposed for audio
- **Full-rate 141 pkt/s = 47 frames/s continuous** when set to `MULTI_TO_MULTI` mode (default `ONE_TO_MULTI` only gives 50%)
- The device header claims 4116 audio bytes/frame but **real audio is 4096 bytes** (1024 stereo pairs) - the remaining 20 bytes are metadata that causes clicks if played as audio
- Our software receiver produces **cleaner audio than the hardware RX unit** (confirmed over overnight test - hardware RX has firmware bug playing metadata bytes 4096-4116 as audio, causing clicks even on direct cable)
- **RX device works standalone** - sends clean TCP audio to `<subnet>.93:7005`, no TX needed
- The `.93` target IP is derived from TX MAC byte 4 (`00:0c:1d:**93**:95:4d`) and works on any subnet

## Quick Start

### 1. Network Setup (Required)

The devices have **broken Ethernet auto-negotiation**. They cannot link to standard switches.

**Option A: Linux bridge (recommended)** - Use a Linux host with two Ethernet ports:
```bash
# Force both ports to 100Mbps Full Duplex
ethtool -s eth0 speed 100 duplex full autoneg off  # TX device
ethtool -s eth1 speed 100 duplex full autoneg off  # RX device

# Bridge them
brctl addbr br0
brctl addif br0 eth0
brctl addif br0 eth1
ip link set br0 up

# Add IP for accessing devices
ip addr add 192.168.1.54/24 dev br0
```

**Option B: Direct cable** - TX and RX link directly to each other (same broken autoneg = compatible).
A Linux host on a third port can sniff the traffic.

**Option C: Managed switch** - Force per-port speed to 100M Full. Note: some managed switches
still cause audio artifacts; the Linux bridge approach is more reliable.

### 2. Receive Audio - TX Device (MULTI_TO_MULTI mode, UDP multicast)

```bash
# Live playback via SSH (tested overnight - stable):
ssh root@bridge-host "python3 /root/receive_audio.py" 2>/dev/null | \
  play -t raw -r 48000 -e signed -b 16 -c 2 -

# Record to WAV:
ssh root@bridge-host "python3 /root/receive_audio.py" 2>/dev/null | \
  sox -t raw -r 48000 -e signed -b 16 -c 2 - output.wav

# Record to FLAC:
ssh root@bridge-host "python3 /root/receive_audio.py" 2>/dev/null | \
  ffmpeg -f s16le -ar 48000 -ac 2 -i - output.flac

# Show stream info:
ssh root@bridge-host "python3 /root/receive_audio.py --info"
```

### 3. Receive Audio - RX Device (ONE_TO_MULTI mode, TCP to .93)

```bash
# Live playback via SSH:
ssh root@bridge-host "python3 /root/receive_tcp_server.py --bind <subnet>.93" 2>/dev/null | \
  play -t raw -r 48000 -e signed -b 16 -c 2 -

# Record to WAV:
ssh root@bridge-host "python3 /root/receive_tcp_server.py --bind <subnet>.93" 2>/dev/null | \
  sox -t raw -r 48000 -e signed -b 16 -c 2 - output.wav
```

### 4. Send Audio (to device RCA outputs)

```bash
# Send any audio file via UDP multicast (mimics TX):
ffmpeg -i music.mp3 -f s16le -ar 48000 -ac 2 - | python3 send_audio.py

# Send via TCP (mimics RX, plays on TX device outputs):
ffmpeg -i music.mp3 -f s16le -ar 48000 -ac 2 - | python3 send_audio_tcp.py

# Send from microphone:
arecord -f S16_LE -c 2 -r 48000 | python3 send_audio.py
```

### Standalone Device Summary

Each device works independently as a network audio input:

| Device | Mode | Receive Method | Live Play Command |
|--------|------|---------------|-------------------|
| **TX** | MULTI_TO_MULTI | `receive_audio.py` (UDP multicast) | `ssh root@host "python3 receive_audio.py" 2>/dev/null \| play -t raw -r 48000 -e signed -b 16 -c 2 -` |
| **RX** | ONE_TO_MULTI | `receive_tcp_server.py` (TCP on .93) | `ssh root@host "python3 receive_tcp_server.py --bind x.x.x.93" 2>/dev/null \| play -t raw -r 48000 -e signed -b 16 -c 2 -` |

## Device Identification

| Field | Value |
|-------|-------|
| Product | M-A202 Bi-Directional Audio Extender |
| Label | "Stereo Hi-Fi Audio Extender" |
| Source | AliExpress (~100 USD per pair) |
| Internal Manufacturer | XYZ |
| Internal Model | LKDCAA |
| Firmware | V5.8 |
| MAC OUI | 00:0C:1D (Mettler & Fuchs AG) |
| TX Default IP | 192.168.1.100 (static) |
| RX Default IP | DHCP (set to 192.168.1.108 for pairing) |
| Web Interface | http://\<device-ip\>:9999/ |
| Web Page Title | "HDMI Externder Config Page" (sic) :red_circle: **(typo in firmware)** |

### Physical Connections (per unit)

- 1x RJ45 Ethernet (100Mbps only) - :red_circle: **auto-negotiation BROKEN**
- 2x RCA (Cinch) Audio Input (Left + Right)
- 2x RCA (Cinch) Audio Output (Left + Right)
- 1x Reset button - :red_circle: **does NOT fully factory reset**
- 1x Power input (5V DC)

### TX vs RX Device Differences

Despite identical hardware and web UI, the devices behave differently:

| | TX-labeled | RX-labeled |
|--|-----------|-----------|
| UDP multicast (224.0.0.100:7001) | Yes | Yes (ONE_TO_MULTI only) |
| TCP audio to `<subnet>.93:7005` | **No** | **Yes** |
| Built-in DHCP server | Yes | No |
| Best standalone mode | **MULTI_TO_MULTI** (full rate multicast) | **ONE_TO_MULTI** (full rate TCP) |
| Receive script | `receive_audio.py` (raw socket) | `receive_tcp_server.py --bind x.x.x.93` |

**Both devices work standalone as network audio inputs.** Use TX with MULTI_TO_MULTI
for multicast, or RX with ONE_TO_MULTI for clean TCP. Two independent audio inputs
from one $100 pair.

## Manual Claims vs Reality

See the scanned [original manual (PDF)](M-A202_Manual_Scanned.pdf).

| Manual Claim | Reality |
|-------------|---------|
| "24bit / 96KHz digital" | :red_circle: **16-bit / 48KHz** (measured from actual packets) |
| "plug-and-play" | :red_circle: **Requires forced 100Mbps FDX** (broken auto-negotiation) |
| "no configuration required" | :red_circle: **Must set MULTI_TO_MULTI mode** or get 50% audio |
| "No noise; No current sound" | :red_circle: **Firmware metadata bug causes clicks** on hardware RX |
| "supports switch" | :red_circle: **Managed switches cause artifacts**, Linux bridge needed |
| "one-to-many distributed audio" | :red_circle: **ONE_TO_MULTI mode is broken** (50% duty cycle) |
| "Ultra-low bit rate with no delay (2ms)" | Uncompressed PCM at 1.5 Mbps, latency untested |
| "32KHz-96KHz sampling" | :red_circle: **Only 48KHz observed** in protocol |
| "200meters max distance" | Not tested |
| "signal-to-noise ratio: 102dB" | :red_circle: **Unlikely given 16-bit = 96dB theoretical max** |
| "Built-in professional audio codec chip" | It's a repurposed HDMI extender chipset (LKDCAA) |

## The Surprise: It's an HDMI Extender Inside

Despite being sold as an audio device, the firmware reveals this is an **HDMI-over-IP extender** chipset repurposed for audio-only use:

- Web UI title: "HDMI Externder Config Page"
- Has HDMI RX/TX status, video resolution settings (Bypass/720P/1080P)
- Has EDID upload capability and VideoStream routing
- Protocol stream name: `hdmi_rx`

The RCA audio jacks connect through ADC/DAC chips. The HDMI video path exists in the chipset but is unused (no HDMI connectors exposed).

## Protocol Specification

See [M-A202_Protocol_Specification.txt](M-A202_Protocol_Specification.txt) for the full developer-oriented protocol spec.

### Two Audio Directions, Two Protocols

| | Forward (TX→RX) | Return (RX→TX) |
|--|------------------|-----------------|
| Transport | UDP Multicast | TCP |
| Destination | 224.0.0.100:7001 | TX_IP:7005 |
| Headers | DEADBEEF + stream info | **None** (raw PCM) |
| Audio/frame | 4096 bytes (header claims 4116) | Continuous stream |
| Reliability | Unreliable (UDP) | Reliable (TCP retransmit) |
| Quality | Good (with 4096 fix) | **Perfect** (full rate, no bugs) |

The return path is actually the cleaner protocol - raw PCM over TCP with no framing
overhead, no metadata bugs, and TCP handles retransmission automatically.

### Forward Path (TX→RX): UDP Multicast

| Parameter | Value |
|-----------|-------|
| Transport | UDP Multicast |
| Multicast Group | 224.0.0.100 (configurable) |
| Audio Port | 7001 (= base port + 2) |
| Source Port | 62510 |
| Magic | 0xDEADBEEF |
| Encoding | 16-bit signed PCM, little-endian (S16_LE) |
| Channels | 2 (stereo, interleaved) |
| Sample Rate | 48000 Hz |
| Bitrate | 1,536 kbps (uncompressed) |
| **Real Audio/Frame** | **4096 bytes = 1024 stereo pairs = ~21.3ms** |
| Header Audio Claim | 4116 bytes :red_circle: **(WRONG - includes 20 bytes metadata that causes clicks)** |
| Packets/Frame | 3 (burst of 1400-byte UDP packets) |
| Frame Rate | ~47 frames/s (when properly paired) |

### Return Path (RX→TX): TCP

| Parameter | Value |
|-----------|-------|
| Transport | TCP |
| Port | 7005 (RX connects to TX) |
| Encoding | 16-bit signed PCM, little-endian (S16_LE) |
| Channels | 2 (stereo, interleaved) |
| Sample Rate | 48000 Hz |
| Headers | **None** - pure raw PCM bytes |
| TX Acknowledgement | 6 zero bytes (`00 00 00 00 00 00`) periodically |
| Data Rate | ~192,000 bytes/s (full 48kHz stereo continuous) |

### Packet Structure

```
Frame = 3 UDP packets (sent as burst, ~0.1ms apart, every ~21ms):

Packet 0 (seq=0):  [16B header] [20B stream info] [1364B data]  = 1400B
Packet 1 (seq=1):  [16B header] [1384B data]                    = 1400B
Packet 2 (seq=2):  [16B header] [1384B data]                    = 1400B

Total data: 4132 bytes per frame
  - Bytes 0-4095:    Audio PCM (1024 stereo sample pairs)
  - Bytes 4096-4111: Zero padding
  - Bytes 4112-4115: Metadata  ← CAUSES CLICKS if played as audio!
  - Bytes 4116-4131: Zero padding + sync markers

Header (all packets):
  0x00  uint32_le  Magic: 0xDEADBEEF
  0x04  uint32_le  Sequence (0, 1, or 2)
  0x08  uint32_le  Payload size (1400)
  0x0C  uint32_le  Packets per frame (3)

Stream info (seq=0 only):
  0x10  char[8]    Name: "hdmi_rx\0"
  0x18  uint32_le  Audio bytes/frame: 4116  ← WRONG! Real audio is 4096
  0x1C  uint32_le  Reserved: 0
  0x20  uint32_le  Sample rate: 48000
```

### :red_circle: **Critical Bug: audio_len Field**

The device reports `audio_len=4116` in the stream header, but **real audio is only 4096 bytes**
(exactly 1024 stereo sample pairs - a clean power-of-2 buffer). Bytes 4096-4116 contain
metadata/padding including a value (0x05A2 = 1442) that produces audible clicks when
interpreted as audio.

**The hardware RX unit has this same bug** - it plays the metadata as audio, causing
occasional clicks even on a clean direct-cable connection. Our software receiver correctly
truncates to 4096 bytes, producing cleaner output than the hardware.

### Boot & Pairing Sequence (Reverse Engineered)

The TX device has a **built-in DHCP server** that automatically assigns an IP to the RX:

```
t=0s    TX boots:
        - Gets static IP 192.168.1.100
        - Starts DHCP server on port 67
        - IGMP join 224.0.0.101 (return multicast?)
        - Starts multicast audio on 224.0.0.100:7001

t=27s   RX boots:
        - Sends DHCP Discover (broadcast)
        - TX replies with DHCP Offer → RX gets 192.168.1.101

t=28s   RX configures:
        - Gratuitous ARP for 192.168.1.101
        - IGMP join 224.0.0.100 (forward audio)
        - ARP for TX (192.168.1.100)

t=28s   RX pairs with TX:
        - TCP SYN → TX:7005 → SYN-ACK → connected
        - Immediately starts streaming return audio over TCP
        - No further handshake needed

Total pairing time: ~1 second after RX boots
```

**To impersonate the RX from Linux:** Get IP 192.168.1.101 (from TX's DHCP or set static),
then TCP connect to 192.168.1.100:7005 and read/write raw PCM.

### Critical Discovery: The .93 Target IP

The RX device always connects to **`<subnet>.93`** on TCP port 7005 to stream its return audio.
This is derived from the **TX MAC address byte 4**: `00:0c:1d:**93**:95:4d` → last octet = **93**.

Tested on multiple subnets:
- On 192.168.1.0/24: RX connects to **192.168.1.93**:7005
- On 172.16.1.0/24: RX connects to **172.16.1.93**:7005

This is hardcoded in firmware and survives all resets. The .93 is NOT the gateway,
NOT from DHCP, and NOT configurable via the web UI.

**To receive return audio on any network:** Simply assign `.93` on the device subnet
to your server and run `receive_tcp_server.py`. No bridge, no Orange Pi, no sniffing needed.

```bash
# On your server (e.g. Proxmox host):
ip addr add 172.16.1.93/24 dev eth0
python3 receive_tcp_server.py --bind 172.16.1.93 | play -t raw -r 48000 -e signed -b 16 -c 2 -
```

### Network Integration

The TX runs its own DHCP server, which conflicts with existing networks. To integrate
the devices into your own network:

**Option A: Isolated bridge (recommended)**
Put both devices on an isolated Linux bridge with the TX's DHCP server serving the RX.
Use a separate interface for your LAN uplink. The bridge host sees all traffic.

```
[LAN] ── [USB/3rd NIC] ── [Linux Host] ── [br0: eth0 + eth1] ── [TX + RX]
                               ↑
                    Runs receive scripts,
                    streams to Chromecast, etc.
```

**Option B: Docker container with dedicated NICs**
Pass two physical NICs to a Docker container on a Proxmox server.
Container runs the bridge, receive scripts, and audio streaming.
The TX's DHCP stays isolated inside the container's bridge.

**Option C: Direct on your LAN (simplest for audio receive)**
Set both devices to static IPs on your subnet. The RX will always connect to
`<subnet>.93:7005` (derived from TX MAC). Just assign `.93` to your server.
No bridge needed - only requirement is forced 100FDX on the port facing each device.

```bash
# On your server:
ip addr add 10.0.0.93/24 dev eth0   # match your subnet
python3 receive_tcp_server.py --bind 10.0.0.93 | play -t raw -r 48000 -e signed -b 16 -c 2 -
```

**Note:** Block the TX's built-in DHCP server to avoid conflicts:
```bash
ebtables -A FORWARD -p IPv4 --ip-src <TX_IP> --ip-proto udp --ip-dport 68 -j DROP
```

### Protocol Ports

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 67/68 | UDP DHCP | TX->RX | TX's built-in DHCP assigns RX IP :red_circle: **(conflicts with network DHCP!)** |
| 7001 | UDP multicast | TX->network | Forward audio (224.0.0.100) |
| 7002 | UDP unicast | TX->RX | Forward audio (when paired) |
| 7005 | TCP | RX->TX | Return audio + control channel |
| 9999 | TCP/HTTP | any->device | Web configuration UI |
| 62510 | UDP source | TX outbound | Source port for all audio |

## Web UI Configuration

Accessible at `http://<device-ip>:9999/` with these sections:

| Section | Controls |
|---------|----------|
| Info | Device name, serial number |
| Status | HDMI RX/TX status, video info, VideoStream routing |
| Ethernet | IP, gateway, netmask, DHCP on/off |
| Multicast | Multicast IP and base port (range 5000-6999) |
| HDMI | TX resolution (Bypass/720P/1080P), EDID upload |
| Restore | Factory reset (key: **888888**) |
| Transmit Mode | ONE_TO_MULTI or MULTI_TO_MULTI |

### Web UI Notes
- Multicast IP shows "244" for first octet - :red_circle: **display bug**; actual traffic uses 224
- Port field shows base port (6999); audio streams on base+2 (7001)
- Factory reset via web key `888888` resets most settings
- Physical reset button does NOT fully factory reset
- Both devices must be on the **same subnet** for proper pairing via TCP port 7005

## Script Reference

### receive_audio.py - Receive Forward Audio (TX→network)

Uses raw sockets to capture UDP multicast, strips DEADBEEF headers and metadata, outputs
clean raw S16_LE stereo 48kHz PCM to stdout. Drops incomplete frames and fills gaps with
silence. Requires root (raw sockets). Works reliably on Linux bridges.

```
Options:
  --mcast GROUP    Multicast group (default: 224.0.0.100)
  --port PORT      UDP port (default: 7001)
  --bind IP        Local IP for multicast join (default: 0.0.0.0)
  --info           Print stream info and exit
  --no-fill        Do not fill gaps with silence (raw audio only)
```

### receive_return_audio.py - Receive Return Audio (RX→TX)

Sniffs the TCP stream from RX to TX on port 7005 (must run on the bridge host).
Outputs raw PCM - no header stripping needed since the return path has no headers.
**This produces the cleanest audio** (full rate, no metadata bugs).

```
Options:
  --iface IFACE    Network interface to sniff (default: br0)
  --rx-ip IP       RX device IP (default: 192.168.1.108)
  --tx-ip IP       TX device IP (default: 192.168.1.100)
  --port PORT      TCP port (default: 7005)
```

### send_audio.py - Send via UDP Multicast (mimics TX)

Reads raw S16_LE stereo 48kHz PCM from stdin, sends using the DEADBEEF multicast protocol.

```
Options:
  --mcast GROUP    Multicast group (default: 224.0.0.100)
  --port PORT      UDP port (default: 7001)
  --rate HZ        Sample rate (default: 48000)
  --ttl N          Multicast TTL (default: 255)
  --src-port PORT  Source UDP port (default: 62510)
```

### send_audio_tcp.py - Send via TCP (mimics RX)

Connects to the TX device on TCP port 7005 and streams raw PCM audio.
The TX plays this on its RCA outputs. **This replaces the hardware RX entirely.**

```
Options:
  --tx-ip IP       TX device IP (default: 192.168.1.100)
  --port PORT      TCP port (default: 7005)
  --rate HZ        Sample rate (default: 48000)
```

```bash
# Example: send music file to TX's RCA outputs:
ffmpeg -i music.mp3 -f s16le -ar 48000 -ac 2 - | python3 send_audio_tcp.py

# Example: send microphone to TX's RCA outputs:
arecord -f S16_LE -c 2 -r 48000 | python3 send_audio_tcp.py
```

## Known Issues & Workarounds

### :red_circle: **Broken Ethernet Auto-Negotiation**
Both TX and RX units fail to auto-negotiate with standard equipment. Must force 100Mbps
Full Duplex via `ethtool` or managed switch. The two devices DO link to each other via
direct cable (same broken autoneg = compatible).

### :red_circle: **Managed Switches Cause Artifacts**
Even with correct speed/duplex settings, managed switches can introduce audio stuttering.
A Linux bridge (two ports, both forced 100FDX) works reliably. The cause is likely
multicast handling or store-and-forward latency in the switch.

### :red_circle: **Linux Bridge Multicast Socket Issue**
Standard UDP multicast sockets (`IP_ADD_MEMBERSHIP`) may not receive packets on Linux bridges,
even with `multicast_snooping=0`. Packets are visible in tcpdump (raw sockets) but not delivered
to regular sockets. The `receive_audio.py` script uses raw sockets (`AF_PACKET`) to work around
this reliably. Requires root.

### :red_circle: **TX: 50% Duty Cycle in Default Mode (SOLVED)**
The default `ONE_TO_MULTI` mode causes 50% duty cycle (22 frames/s with ~125ms gaps).
**Fix: Set `MULTI_TO_MULTI` via web UI → full continuous 48kHz (47 frames/s), no RX needed.**

```
Web UI (http://<TX_IP>:9999/) → Transmit Mode → MULTI_TO_MULTI → Commit → Reboot
```

| Mode | Packet Rate | Result |
|------|-------------|--------|
| ONE_TO_MULTI (default) | 66 pkt/s (50%) | :red_circle: **Gaps, stuttering, unusable** |
| **MULTI_TO_MULTI** | **141 pkt/s (100%)** | **Full continuous 48kHz** |

### :red_circle: **Hardware RX Clicking (Software Receiver is Better)**
The RX unit's firmware plays metadata bytes (4096-4116) as audio, causing occasional clicks
even on a clean direct-cable connection. This is a firmware bug. Our software receiver
correctly strips the metadata and produces cleaner audio.

**Confirmed via overnight streaming test:** `receive_audio.py` ran continuously for 12+ hours
with clean audio - no clicks, no dropouts. The $100 hardware RX is literally worse than
a Python script.

## Hidden Features

1. **HDMI Video over IP** - The chipset supports 720P/1080P video streaming (base port)
2. **EDID Upload** - Custom EDID for the HDMI RX input
3. **MULTI_TO_MULTI Mode** - Enables full-rate streaming. Also allows multiple TX devices on the same multicast group
4. **Configurable Multicast** - Multiple independent audio channels on one network
5. **Factory Reset** - Key: `888888`

## Is This a Common Platform?

Yes. The LKDCAA chipset with "XYZ" manufacturer and `0xDEADBEEF` magic is a widely-used
Chinese HDMI-over-IP platform found in many budget extenders under different brand names:

- Common in $30-150 HDMI extenders on AliExpress/Alibaba
- Proprietary protocol (not AES67/Dante/AVB)
- Firmware versions V4.x through V6.x observed
- Same web UI across different brands
- 100Mbps Ethernet with known auto-negotiation issues

## Enhancement Ideas

- **Docker on Proxmox** - Run the Linux bridge + receiver in a Docker container on a
  Proxmox server. Pass two physical NICs (forced 100FDX) to the container. Eliminates
  the need for a dedicated Orange Pi. Container runs bridge + scripts + Chromecast streaming.
- **Chromecast Audio multi-room** - Pipe `receive_return_audio.py` through ffmpeg to
  create an HTTP MP3 stream, then use pychromecast to cast to all Chromecast Audio devices.
  Alternative: create a speaker group in Google Home app and cast to the group.
- **MULTI_TO_MULTI mode is the fix for 50% duty cycle** - Enables full-rate continuous 48kHz on the TX even without the RX device. Set via web UI.
- **ALSA virtual sound card** - `snd-aloop` + scripts = transparent virtual device
- **PulseAudio/PipeWire module** - Network audio source/sink
- **Audio processing** - Insert sox/ffmpeg effects in the pipeline
- **RTP bridge** - Convert to standard RTP for pro audio tools
- **Wireshark dissector** - Custom dissector for the 0xDEADBEEF protocol

## Icecast2 HTTP Streaming (Tested)

Both devices can stream simultaneously via Icecast2 as proper HTTP audio streams,
accessible from any browser or media player on the network.

### Setup

```bash
# Install
apt install icecast2 ffmpeg

# Configure /etc/icecast2/icecast.xml (source-password: hackme)
# Start Icecast (not as root)
sudo -u nobody icecast2 -c /etc/icecast2/icecast.xml -b

# Block DHCP between devices on the bridge
ebtables -A FORWARD -p IPv4 --ip-proto udp --ip-dport 67 -j DROP
ebtables -A FORWARD -p IPv4 --ip-proto udp --ip-dport 68 -j DROP

# Feed TX device → Icecast /tx mount
python3 receive_audio.py 2>/dev/null | \
  ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 \
  -c:a libmp3lame -b:a 320k -f mp3 -content_type audio/mpeg \
  icecast://source:hackme@localhost:8000/tx -loglevel warning &

# Feed RX device → Icecast /rx mount
python3 receive_tcp_server.py --bind <subnet>.93 2>/dev/null | \
  ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 \
  -c:a libmp3lame -b:a 320k -f mp3 -content_type audio/mpeg \
  icecast://source:hackme@localhost:8000/rx -loglevel warning &
```

### All Streams

```bash
# TX MP3 → Icecast /tx
python3 receive_audio.py 2>/dev/null | \
  ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 \
  -c:a libmp3lame -b:a 320k -f mp3 -content_type audio/mpeg \
  icecast://source:hackme@localhost:8000/tx &

# TX FLAC (lossless, lower latency) → Icecast /tx-flac
python3 receive_audio.py 2>/dev/null | \
  ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 \
  -c:a flac -f ogg -content_type application/ogg \
  icecast://source:hackme@localhost:8000/tx-flac &

# RX MP3 → Icecast /rx
python3 receive_tcp_server.py --bind <subnet>.93 2>/dev/null | \
  ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 \
  -c:a libmp3lame -b:a 320k -f mp3 -content_type audio/mpeg \
  icecast://source:hackme@localhost:8000/rx &
```

### Listen

```
http://<server>:8000/tx        ← TX audio, MP3 (browser/Chromecast)
http://<server>:8000/tx-flac   ← TX audio, lossless FLAC (low latency, pro use)
http://<server>:8000/rx        ← RX audio, MP3 (browser/Chromecast)
http://<server>:8000/          ← Icecast status page
```

Works in any browser, VLC, ffplay, mpv, or Chromecast. Multiple simultaneous listeners supported.

> [!NOTE]
> **RX FLAC (/rx-flac) is not stable** - the RX uses a single TCP connection held by the MP3
> encoder. A second receiver (raw socket sniffer) for FLAC causes glitches due to TCP segment
> reassembly issues. Fix: use `tee` to split the single TCP stream into both encoders.
> This is planned for the Proxmox production setup.

> [!NOTE]
> Don't use ffmpeg's built-in `-listen 1` HTTP server - it only supports one client
> and dies after disconnect. Icecast2 is purpose-built for audio streaming.

## Network Debugging

```bash
# View live traffic:
tcpdump -nn -i eth0 host 192.168.1.100 and udp port 7001

# Hex dump:
tcpdump -nn -i eth0 host 192.168.1.100 and udp port 7001 -X -c 10

# Capture for Wireshark:
tcpdump -nn -i eth0 host 192.168.1.100 -w capture.pcap

# Measure packet rate:
timeout 3 tcpdump -nn -c 500 -i eth0 'udp port 7001' 2>&1 | tail -3
# Full rate = ~141 pkt/s = 47 frames/s
```

## License

These reverse engineering notes and scripts are provided for educational and interoperability purposes. Use at your own risk.

## Analysis Environment

| Component | Details |
|-----------|---------|
| Host | Orange Pi R1 Plus |
| OS | Debian/Armbian (arm64) |
| Network | Linux bridge (end0 + enxc0742bffa60d), USB adapter uplink |
| Analysis Date | 2026-03-31 |
