#!/usr/bin/env python3
"""
Receive audio from HDMI-over-IP audio extender (M-A202 / model LKDCAA).

Protocol: Proprietary UDP multicast with DEADBEEF magic header.
Format: 16-bit signed PCM, little-endian, stereo interleaved, 48000 Hz.

The device sends audio in bursts with periodic gaps (~125ms).
This receiver inserts silence to fill gaps, producing a continuous stream.

Outputs raw PCM to stdout. Pipe to aplay, sox play, ffmpeg, etc.

Usage examples:
  # Direct playback (sox - recommended):
  python3 receive_audio.py | play -t raw -r 48000 -e signed -b 16 -c 2 -

  # Direct playback (aplay):
  python3 receive_audio.py | aplay -f S16_LE -c 2 -r 48000 --buffer-time=500000

  # Record to WAV:
  python3 receive_audio.py | sox -t raw -r 48000 -e signed -b 16 -c 2 - output.wav

  # Record to FLAC:
  python3 receive_audio.py | ffmpeg -f s16le -ar 48000 -ac 2 -i - output.flac

  # Stream info only:
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
HEADER_SIZE = 16
STREAM_HEADER_SIZE = 20


def main():
    parser = argparse.ArgumentParser(description='Receive audio from HDMI-over-IP extender')
    parser.add_argument('--mcast', default='224.0.0.100', help='Multicast group (default: 224.0.0.100)')
    parser.add_argument('--port', type=int, default=7001, help='UDP port (default: 7001)')
    parser.add_argument('--bind', default='0.0.0.0', help='Local IP to bind for multicast (default: 0.0.0.0)')
    parser.add_argument('--info', action='store_true', help='Print stream info to stderr and exit')
    parser.add_argument('--no-fill', action='store_true', help='Do not fill gaps with silence')
    args = parser.parse_args()

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
    sock.bind(('', args.port))

    mreq = struct.pack('4s4s', socket.inet_aton(args.mcast), socket.inet_aton(args.bind))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    if args.info:
        sock.settimeout(5)
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            print("No packets received", file=sys.stderr)
            sys.exit(1)
        magic, seq, plen, npkt = struct.unpack('<IIII', data[:16])
        while seq != 0:
            data, addr = sock.recvfrom(2048)
            magic, seq, plen, npkt = struct.unpack('<IIII', data[:16])
        name = data[16:24].split(b'\x00')[0].decode('ascii', errors='replace')
        audio_len = struct.unpack('<I', data[24:28])[0]
        sample_rate = struct.unpack('<I', data[32:36])[0]
        print(f"Source:      {addr[0]}:{addr[1]}", file=sys.stderr)
        print(f"Multicast:   {args.mcast}:{args.port}", file=sys.stderr)
        print(f"Stream name: {name}", file=sys.stderr)
        print(f"Sample rate: {sample_rate} Hz", file=sys.stderr)
        print(f"Format:      16-bit signed LE, stereo interleaved", file=sys.stderr)
        print(f"Audio bytes/frame: {audio_len}", file=sys.stderr)
        print(f"Packets/frame: {npkt}", file=sys.stderr)
        samples_per_frame = audio_len // 4
        frame_duration_ms = samples_per_frame / sample_rate * 1000
        print(f"Samples/frame: {samples_per_frame} stereo pairs ({frame_duration_ms:.1f} ms)", file=sys.stderr)
        bitrate_kbps = sample_rate * 2 * 16 / 1000
        print(f"Bitrate:     {bitrate_kbps:.0f} kbps (uncompressed)", file=sys.stderr)
        sock.close()
        return

    out_fd = sys.stdout.fileno()
    stderr = sys.stderr
    print("Receiving audio... (Ctrl+C to stop)", file=stderr)

    audio_len = 4116  # bytes per frame (updated from stream)
    frame_duration = audio_len / 4 / 48000  # seconds per frame (~0.0214s)
    fill_gaps = not args.no_fill
    silence_frame = b'\x00' * audio_len

    frame_buf = bytearray()
    frame_pkt_count = 0  # track how many packets in current frame
    last_frame_time = None
    frame_count = 0
    drop_count = 0
    gap_count = 0

    try:
        while True:
            data, addr = sock.recvfrom(2048)
            if len(data) < HEADER_SIZE:
                continue

            magic, seq = struct.unpack('<II', data[:8])
            if magic != MAGIC:
                continue

            if seq == 0:
                now = time.monotonic()

                # Flush previous frame ONLY if complete (3 packets)
                if frame_buf and frame_pkt_count == 3 and len(frame_buf) >= audio_len:
                    out = bytes(frame_buf[:audio_len])

                    # Fill gaps with silence (fast - no per-sample math)
                    if fill_gaps and last_frame_time is not None:
                        gap = now - last_frame_time
                        missed = int(gap / frame_duration) - 1
                        if 0 < missed < 50:
                            os.write(out_fd, silence_frame * missed)
                            gap_count += missed

                    os.write(out_fd, out)
                    frame_count += 1
                    last_frame_time = now
                elif frame_buf:
                    drop_count += 1

                # Start new frame
                frame_buf = bytearray()
                frame_pkt_count = 1
                if len(data) >= HEADER_SIZE + STREAM_HEADER_SIZE:
                    # Header says 4116 but real audio is 4096 bytes (1024 stereo pairs)
                    # Bytes 4096-4116 contain metadata/padding that causes clicks
                    audio_len = 4096
                    sr = struct.unpack('<I', data[32:36])[0]
                    frame_duration = audio_len / 4 / sr
                    silence_frame = b'\x00' * audio_len
                frame_buf.extend(data[HEADER_SIZE + STREAM_HEADER_SIZE:])
            else:
                frame_buf.extend(data[HEADER_SIZE:])
                frame_pkt_count += 1

    except KeyboardInterrupt:
        print(f"\nStopped. ({frame_count} frames, {drop_count} dropped, {gap_count} gaps filled)", file=stderr)
    except BrokenPipeError:
        pass
    finally:
        sock.close()


if __name__ == '__main__':
    main()
