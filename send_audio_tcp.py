#!/usr/bin/env python3
"""
Send audio to M-A202 TX device via TCP, mimicking the RX device.

Connects to the TX on TCP port 7005 and streams raw PCM audio.
The TX will play this audio on its RCA outputs.
Format: 48kHz, 16-bit signed LE, stereo interleaved. No headers.

This effectively turns any Linux machine into an M-A202 RX device.

Usage examples:
  # Send a music file:
  ffmpeg -i music.mp3 -f s16le -ar 48000 -ac 2 - | python3 send_audio_tcp.py

  # Send from microphone:
  arecord -f S16_LE -c 2 -r 48000 | python3 send_audio_tcp.py

  # Send from PulseAudio/PipeWire:
  parec --format=s16le --channels=2 --rate=48000 | python3 send_audio_tcp.py

  # Send a test tone:
  python3 -c "
import struct, math, sys
sr=48000; dur=10; freq=440
for i in range(sr*dur):
    s = int(16000 * math.sin(2*math.pi*freq*i/sr))
    sys.stdout.buffer.write(struct.pack('<hh', s, s))
" | python3 send_audio_tcp.py
"""

import socket
import sys
import os
import time
import argparse
import signal


def main():
    parser = argparse.ArgumentParser(description='Send audio to M-A202 TX device via TCP')
    parser.add_argument('--tx-ip', default='192.168.1.100', help='TX device IP (default: 192.168.1.100)')
    parser.add_argument('--port', type=int, default=7005, help='TCP port (default: 7005)')
    parser.add_argument('--rate', type=int, default=48000, help='Sample rate (default: 48000)')
    args = parser.parse_args()

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    stderr = sys.stderr
    stdin = sys.stdin.buffer

    # Connect to TX device
    print("Connecting to TX at %s:%d..." % (args.tx_ip, args.port), file=stderr)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        sock.connect((args.tx_ip, args.port))
    except ConnectionRefusedError:
        print("Connection refused. Is the TX device running?", file=stderr)
        print("Note: TX may only accept one connection (from the paired RX).", file=stderr)
        sys.exit(1)
    except OSError as e:
        print("Connection failed: %s" % e, file=stderr)
        sys.exit(1)

    print("Connected! Streaming audio... (Ctrl+C to stop)", file=stderr)
    print("Format: S16LE stereo %dHz" % args.rate, file=stderr)

    # Stream raw PCM in chunks matching the RX device's pattern
    # RX sends ~4096 bytes per ~21ms (1024 stereo pairs at 48kHz)
    chunk_size = 4096
    frame_duration = chunk_size / 4 / args.rate

    byte_count = 0
    frame_start = time.monotonic()

    try:
        while True:
            data = stdin.read(chunk_size)
            if not data:
                break
            if len(data) < chunk_size:
                data += b'\x00' * (chunk_size - len(data))

            sock.sendall(data)
            byte_count += len(data)

            # Pace to real-time
            frame_start += frame_duration
            sleep_time = frame_start - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)
            elif sleep_time < -0.1:
                frame_start = time.monotonic()

            # Read and discard TX's 6-byte ACKs
            sock.setblocking(False)
            try:
                sock.recv(64)
            except BlockingIOError:
                pass
            sock.setblocking(True)

    except KeyboardInterrupt:
        print("\nStopped. (%d bytes sent)" % byte_count, file=stderr)
    except BrokenPipeError:
        print("\nConnection closed by TX.", file=stderr)
    finally:
        sock.close()


if __name__ == '__main__':
    main()
