#!/usr/bin/env python3
"""
Receive return-direction audio from M-A202 RX device.

The RX device sends raw PCM audio to the TX on TCP port 7005.
Format: 48kHz, 16-bit signed LE, stereo interleaved. No headers.

This script sniffs the TCP stream using a raw socket on the bridge interface.
Must run as root on the bridge host (Orange Pi) with both devices connected.

Outputs raw PCM to stdout.

Usage examples:
  # Play directly:
  python3 receive_return_audio.py | play -t raw -r 48000 -e signed -b 16 -c 2 -

  # Record to WAV:
  python3 receive_return_audio.py | sox -t raw -r 48000 -e signed -b 16 -c 2 - output.wav

  # Record to FLAC:
  python3 receive_return_audio.py | ffmpeg -f s16le -ar 48000 -ac 2 -i - output.flac

  # Remote playback via SSH:
  ssh root@bridge-host "python3 receive_return_audio.py" | play -t raw -r 48000 -e signed -b 16 -c 2 -
"""

import socket
import struct
import sys
import os
import argparse
import signal


def main():
    parser = argparse.ArgumentParser(description='Receive return audio from M-A202 RX device')
    parser.add_argument('--iface', default='br0', help='Network interface to sniff (default: br0)')
    parser.add_argument('--rx-ip', default='192.168.1.101', help='RX device IP (default: 192.168.1.101)')
    parser.add_argument('--port', type=int, default=7005, help='TCP port (default: 7005)')
    args = parser.parse_args()

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    stderr = sys.stderr
    out_fd = sys.stdout.fileno()

    rx_ip_bytes = socket.inet_aton(args.rx_ip)

    # Raw socket to sniff all IP packets on the bridge
    try:
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0800))
        sock.bind((args.iface, 0))
    except PermissionError:
        print("Need root to sniff packets. Run with sudo.", file=stderr)
        sys.exit(1)

    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)

    print("Receiving return audio from RX %s via %s... (Ctrl+C to stop)" % (args.rx_ip, args.iface), file=stderr)

    byte_count = 0

    try:
        while True:
            data = sock.recv(65535)
            if len(data) < 54:
                continue

            # Ethernet header (14 bytes) + IP header
            ethertype = struct.unpack(">H", data[12:14])[0]
            if ethertype != 0x0800:
                continue

            # IP header
            ip_proto = data[23]
            if ip_proto != 6:  # TCP
                continue

            ip_src = data[26:30]
            if ip_src != rx_ip_bytes:
                continue

            # TCP header
            ip_hdr_len = (data[14] & 0x0F) * 4
            tcp_off = 14 + ip_hdr_len
            dst_port = struct.unpack(">H", data[tcp_off + 2:tcp_off + 4])[0]
            if dst_port != args.port:
                continue

            tcp_hdr_len = ((data[tcp_off + 12] >> 4) & 0xF) * 4
            payload = data[tcp_off + tcp_hdr_len:]

            if len(payload) > 6:  # Skip TCP ACKs and TX's 6-byte keepalives
                os.write(out_fd, payload)
                byte_count += len(payload)

    except KeyboardInterrupt:
        print("\nStopped. (%d bytes)" % byte_count, file=stderr)
    except BrokenPipeError:
        pass
    finally:
        sock.close()


if __name__ == '__main__':
    main()
