#!/usr/bin/env python3
"""
Receive forward audio from M-A202 TX device (UDP multicast).

Uses raw sockets to reliably capture multicast on Linux bridges.
Format: 48kHz, 16-bit signed LE, stereo interleaved.
Real audio is 4096 bytes per frame (device header claims 4116 - ignore it).

IMPORTANT: Set TX to MULTI_TO_MULTI mode for full-rate continuous audio.

Outputs raw PCM to stdout. Pipe to play, aplay, ffmpeg, etc.

Usage:
  python3 receive_audio.py | play -t raw -r 48000 -e signed -b 16 -c 2 -

  # Via SSH:
  ssh root@bridge-host "python3 receive_audio.py" 2>/dev/null | play -t raw -r 48000 -e signed -b 16 -c 2 -

  # Record to WAV:
  python3 receive_audio.py | sox -t raw -r 48000 -e signed -b 16 -c 2 - output.wav

  # Stream info:
  python3 receive_audio.py --info
"""

import socket
import struct
import sys
import os
import time
import argparse
import signal

MAGIC = 0xDEADBEEF
AUDIO_LEN = 4096  # real audio per frame (NOT 4116 as device claims)


def main():
    parser = argparse.ArgumentParser(description='Receive forward audio from M-A202 TX')
    parser.add_argument('--iface', default='br0', help='Interface to capture on (default: br0)')
    parser.add_argument('--port', type=int, default=7001, help='UDP port (default: 7001)')
    parser.add_argument('--info', action='store_true', help='Print stream info and exit')
    parser.add_argument('--no-fill', action='store_true', help='Do not fill gaps with silence')
    args = parser.parse_args()

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    try:
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0800))
        sock.bind((args.iface, 0))
    except PermissionError:
        print("Need root. Run with sudo.", file=sys.stderr)
        sys.exit(1)

    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)

    if args.info:
        print("Waiting for first packet...", file=sys.stderr)
        while True:
            data = sock.recv(65535)
            if len(data) < 56 or data[23] != 17:
                continue
            ip_hdr_len = (data[14] & 0x0F) * 4
            udp_off = 14 + ip_hdr_len
            dst_port = struct.unpack(">H", data[udp_off+2:udp_off+4])[0]
            if dst_port != args.port:
                continue
            payload = data[udp_off+8:]
            if len(payload) < 36:
                continue
            magic, seq = struct.unpack('<II', payload[:8])
            if magic != MAGIC or seq != 0:
                continue
            src_ip = ".".join(str(b) for b in data[26:30])
            name = payload[16:24].split(b'\x00')[0].decode('ascii', errors='replace')
            claimed_len = struct.unpack('<I', payload[24:28])[0]
            sr = struct.unpack('<I', payload[32:36])[0]
            print("Source:      %s" % src_ip, file=sys.stderr)
            print("Interface:   %s" % args.iface, file=sys.stderr)
            print("Stream name: %s" % name, file=sys.stderr)
            print("Sample rate: %d Hz" % sr, file=sys.stderr)
            print("Format:      16-bit signed LE, stereo interleaved", file=sys.stderr)
            print("Claimed audio/frame: %d (WRONG)" % claimed_len, file=sys.stderr)
            print("Real audio/frame: %d bytes = %d stereo pairs" % (AUDIO_LEN, AUDIO_LEN // 4), file=sys.stderr)
            print("Packets/frame: 3", file=sys.stderr)
            sock.close()
            return

    out_fd = sys.stdout.fileno()
    stderr = sys.stderr
    fill_gaps = not args.no_fill
    silence = b'\x00' * AUDIO_LEN
    frame_duration = AUDIO_LEN / 4 / 48000

    print("Receiving audio on %s... (Ctrl+C to stop)" % args.iface, file=stderr)

    frame_buf = bytearray()
    pkt_count = 0
    last_time = None
    frame_count = 0
    drop_count = 0
    gap_count = 0

    try:
        while True:
            data = sock.recv(65535)
            if len(data) < 56 or data[23] != 17:
                continue
            ip_hdr_len = (data[14] & 0x0F) * 4
            udp_off = 14 + ip_hdr_len
            dst_port = struct.unpack(">H", data[udp_off+2:udp_off+4])[0]
            if dst_port != args.port:
                continue
            payload = data[udp_off+8:]
            if len(payload) < 16:
                continue
            magic, seq = struct.unpack("<II", payload[:8])
            if magic != MAGIC:
                continue

            if seq == 0:
                now = time.monotonic()
                if frame_buf and pkt_count == 3 and len(frame_buf) >= AUDIO_LEN:
                    if fill_gaps and last_time is not None:
                        gap = now - last_time
                        missed = int(gap / frame_duration) - 1
                        if 0 < missed < 50:
                            os.write(out_fd, silence * missed)
                            gap_count += missed
                    os.write(out_fd, bytes(frame_buf[:AUDIO_LEN]))
                    frame_count += 1
                    last_time = now
                elif frame_buf:
                    drop_count += 1

                frame_buf = bytearray()
                pkt_count = 1
                frame_buf.extend(payload[36:])
            else:
                frame_buf.extend(payload[16:])
                pkt_count += 1

    except KeyboardInterrupt:
        print("\nStopped. (%d frames, %d dropped, %d gaps)" % (frame_count, drop_count, gap_count), file=stderr)
    except BrokenPipeError:
        pass
    finally:
        sock.close()


if __name__ == '__main__':
    main()
