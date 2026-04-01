#!/bin/bash
# M-A202 Audio Streaming Service
# Starts Icecast2 + all audio streams from TX and RX devices
# Designed to run as a systemd service

set -e

# Configuration
BRIDGE_IF="br0"
BRIDGE_IP="172.16.1.1"
RX_TARGET_IP="172.16.1.93"
RX_DEVICE_IP="172.16.1.101"
ICECAST_HOST="localhost"
ICECAST_PORT="8000"
ICECAST_PASS="hackme"
SCRIPT_DIR="/root"

# Wait for bridge to be up
echo "Waiting for bridge ${BRIDGE_IF}..."
for i in $(seq 1 30); do
    ip link show ${BRIDGE_IF} up >/dev/null 2>&1 && break
    sleep 1
done

# Force 100FDX on bridge ports
for iface in end0 enxc0742bffa60d; do
    if ip link show ${iface} >/dev/null 2>&1; then
        ethtool -s ${iface} speed 100 duplex full autoneg off 2>/dev/null || true
        echo "Forced 100FDX on ${iface}"
    fi
done

# Disable multicast snooping
echo 0 > /sys/devices/virtual/net/${BRIDGE_IF}/bridge/multicast_snooping 2>/dev/null || true

# Add device subnet IP to bridge
ip addr add ${BRIDGE_IP}/24 dev ${BRIDGE_IF} 2>/dev/null || true
ip addr add ${RX_TARGET_IP}/24 dev ${BRIDGE_IF} 2>/dev/null || true

# Block DHCP forwarding between devices
ebtables -F 2>/dev/null || true
ebtables -A FORWARD -p IPv4 --ip-proto udp --ip-dport 67 -j DROP 2>/dev/null || true
ebtables -A FORWARD -p IPv4 --ip-proto udp --ip-dport 68 -j DROP 2>/dev/null || true
echo "DHCP blocked on bridge"

# Wait for Icecast
echo "Waiting for Icecast on port ${ICECAST_PORT}..."
for i in $(seq 1 15); do
    ss -tlnp | grep -q ":${ICECAST_PORT} " && break
    sleep 1
done

if ! ss -tlnp | grep -q ":${ICECAST_PORT} "; then
    echo "Icecast not running, starting..."
    sudo -u nobody icecast2 -c /etc/icecast2/icecast.xml -b 2>/dev/null || true
    sleep 3
fi

echo "Starting audio streams..."

# TX MP3 → /tx
stdbuf -o0 python3 ${SCRIPT_DIR}/receive_audio.py 2>/dev/null | \
    ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 \
    -c:a libmp3lame -b:a 320k -f mp3 -content_type audio/mpeg \
    icecast://source:${ICECAST_PASS}@${ICECAST_HOST}:${ICECAST_PORT}/tx \
    -loglevel warning &
PID_TX_MP3=$!
echo "TX MP3 started (PID ${PID_TX_MP3})"

# TX FLAC → /tx-flac (disabled on low-memory devices, uncomment on Proxmox)
# stdbuf -o0 python3 ${SCRIPT_DIR}/receive_audio.py 2>/dev/null | \
#     ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 \
#     -c:a flac -f ogg -content_type application/ogg \
#     icecast://source:${ICECAST_PASS}@${ICECAST_HOST}:${ICECAST_PORT}/tx-flac \
#     -loglevel warning &
# PID_TX_FLAC=$!
# echo "TX FLAC started (PID ${PID_TX_FLAC})"

# RX MP3 → /rx
python3 ${SCRIPT_DIR}/receive_tcp_server.py --bind ${RX_TARGET_IP} 2>/dev/null | \
    ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 \
    -c:a libmp3lame -b:a 320k -f mp3 -content_type audio/mpeg \
    icecast://source:${ICECAST_PASS}@${ICECAST_HOST}:${ICECAST_PORT}/rx \
    -loglevel warning &
PID_RX_MP3=$!
echo "RX MP3 started (PID ${PID_RX_MP3})"

echo "All streams started. Monitoring..."

# Wait for any child to exit, then restart everything
wait -n
echo "A stream died, exiting (systemd will restart us)..."
kill 0
