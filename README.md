# M-A202 Bi-Directional Stereo Hi-Fi Audio Extender - Reverse Engineering & Linux Tools

![M-A202 TX and RX Units](images/M-A202_TX_RX_units.png)
*M-A202 TX (bottom) and RX (top) units - "Stereo Hi-Fi Audio Extender" with RCA audio and Ethernet*

## Overview

The **M-A202** is a pair of TX/RX devices sold on AliExpress as a "Bi-Directional Audio Extender" (~100 USD). Each unit has an RJ45 Ethernet port, 2x RCA audio input, 2x RCA audio output, a reset button, and a power connector.

This repository documents the **reverse-engineered protocol** and provides **Python scripts** to send and receive audio using standard Linux tools (sox, ffmpeg, VLC, aplay, etc.).

### Key Findings

- Audio is **48 kHz / 16-bit stereo uncompressed PCM** (better than CD quality)
- **Two different protocols per direction:**
  - **Forward (TX→RX):** UDP multicast with proprietary `0xDEADBEEF` header, 3 packets per frame
  - **Return (RX→TX):** Raw PCM over TCP port 7005 - **no headers at all**, full rate, perfect quality
- The return TCP path is the **cleaner protocol** - no metadata bugs, no packet loss (TCP retransmit), continuous 192 KB/s
- Internally this is an **HDMI-over-IP extender** chipset (model LKDCAA, FW V5.8) repurposed for audio
- **Full-rate 141 pkt/s = 47 frames/s continuous** when TX+RX are properly paired via Linux bridge
- The device header claims 4116 audio bytes/frame but **real audio is 4096 bytes** (1024 stereo pairs) - the remaining 20 bytes are metadata that causes clicks if played as audio
- Our software receiver produces **cleaner audio than the hardware RX unit** (which has the same metadata-as-audio bug in its firmware)
- **Pro tip:** For best quality, use the RX unit as your audio input (sends clean TCP) and the TX unit as output (receives TCP on port 7005). `send_audio_tcp.py` can replace the RX hardware entirely

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

### 2. Receive Audio

```bash
# Play directly (sox - recommended):
python3 receive_audio.py | play -t raw -r 48000 -e signed -b 16 -c 2 -

# Record to WAV:
python3 receive_audio.py | sox -t raw -r 48000 -e signed -b 16 -c 2 - output.wav

# Record to FLAC:
python3 receive_audio.py | ffmpeg -f s16le -ar 48000 -ac 2 -i - output.flac

# Play with VLC:
python3 receive_audio.py | cvlc --demux=rawaud --rawaud-channels=2 \
     --rawaud-samplerate=48000 --rawaud-fourcc=s16l -

# Via SSH from remote bridge host:
ssh root@bridge-host "python3 /root/receive_audio.py" | play -t raw -r 48000 -e signed -b 16 -c 2 -

# Show stream info:
python3 receive_audio.py --info
```

### 3. Send Audio (to RX device)

```bash
# Send any audio file:
ffmpeg -i music.mp3 -f s16le -ar 48000 -ac 2 - | python3 send_audio.py

# Send from microphone:
arecord -f S16_LE -c 2 -r 48000 | python3 send_audio.py

# Send from PulseAudio/PipeWire:
parec --format=s16le --channels=2 --rate=48000 | python3 send_audio.py
```

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
| Web Page Title | "HDMI Externder Config Page" (sic) |

### Physical Connections (per unit)

- 1x RJ45 Ethernet (100Mbps only - auto-negotiation broken)
- 2x RCA (Cinch) Audio Input (Left + Right)
- 2x RCA (Cinch) Audio Output (Left + Right)
- 1x Reset button (partial reset only)
- 1x Power input (5V DC)

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
| Header Audio Claim | 4116 bytes (WRONG - includes 20 bytes metadata) |
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
  - Bytes 4112-4115: Metadata (causes clicks if played as audio!)
  - Bytes 4116-4131: Zero padding + sync markers

Header (all packets):
  0x00  uint32_le  Magic: 0xDEADBEEF
  0x04  uint32_le  Sequence (0, 1, or 2)
  0x08  uint32_le  Payload size (1400)
  0x0C  uint32_le  Packets per frame (3)

Stream info (seq=0 only):
  0x10  char[8]    Name: "hdmi_rx\0"
  0x18  uint32_le  Audio bytes/frame: 4116 (WRONG - use 4096)
  0x1C  uint32_le  Reserved: 0
  0x20  uint32_le  Sample rate: 48000
```

### Critical Bug: audio_len Field

The device reports `audio_len=4116` in the stream header, but **real audio is only 4096 bytes**
(exactly 1024 stereo sample pairs - a clean power-of-2 buffer). Bytes 4096-4116 contain
metadata/padding including a value (0x05A2 = 1442) that produces audible clicks when
interpreted as audio.

**The hardware RX unit has this same bug** - it plays the metadata as audio, causing
occasional clicks even on a clean direct-cable connection. Our software receiver correctly
truncates to 4096 bytes, producing cleaner output than the hardware.

### Protocol Ports

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 7001 | UDP multicast | TX->network | Audio stream (224.0.0.100) |
| 7002 | UDP unicast | TX->RX | Audio stream (when paired) |
| 7005 | TCP | TX<->RX | Control/pairing channel |
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
- Multicast IP shows "244" for first octet - display bug; actual traffic uses 224
- Port field shows base port (6999); audio streams on base+2 (7001)
- Factory reset via web key `888888` resets most settings
- Physical reset button does NOT fully factory reset
- Both devices must be on the **same subnet** for proper pairing via TCP port 7005

## Script Reference

### receive_audio.py - Receive Forward Audio (TX→network)

Joins the UDP multicast group, strips DEADBEEF headers and metadata, outputs clean
raw S16_LE stereo 48kHz PCM to stdout. Drops incomplete frames and fills gaps with silence.

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

### Broken Ethernet Auto-Negotiation
Both TX and RX units fail to auto-negotiate with standard equipment. Must force 100Mbps
Full Duplex via `ethtool` or managed switch. The two devices DO link to each other via
direct cable (same broken autoneg = compatible).

### Managed Switches Cause Artifacts
Even with correct speed/duplex settings, managed switches can introduce audio stuttering.
A Linux bridge (two ports, both forced 100FDX) works reliably. The cause is likely
multicast handling or store-and-forward latency in the switch.

### TX Without RX: 50% Duty Cycle
When the TX operates alone (no RX paired on same subnet), it sends only ~22 frames/s
(50% of full rate). Both devices must be on the same IP subnet with matching multicast
settings for the TCP control channel (port 7005) to establish and enable full-rate streaming.

### Hardware RX Clicking
The RX unit's firmware plays metadata bytes (4096-4116) as audio, causing occasional clicks
even on a clean direct-cable connection. This is a firmware bug. Our software receiver
correctly strips the metadata and produces cleaner audio.

## Hidden Features

1. **HDMI Video over IP** - The chipset supports 720P/1080P video streaming (base port)
2. **EDID Upload** - Custom EDID for the HDMI RX input
3. **MULTI_TO_MULTI Mode** - Multiple TX devices on the same multicast group
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
- **MULTI_TO_MULTI mode** - Untested with both devices set to this mode simultaneously.
  May change protocol behavior (possibly TCP-only, eliminating multicast clicking).
- **ALSA virtual sound card** - `snd-aloop` + scripts = transparent virtual device
- **PulseAudio/PipeWire module** - Network audio source/sink
- **Audio processing** - Insert sox/ffmpeg effects in the pipeline
- **RTP bridge** - Convert to standard RTP for pro audio tools
- **Wireshark dissector** - Custom dissector for the 0xDEADBEEF protocol

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
