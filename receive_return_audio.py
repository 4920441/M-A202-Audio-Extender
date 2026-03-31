#!/usr/bin/env python3
"""
Receive return-direction audio from M-A202 RX device via TCP sniffing.

The RX device sends raw PCM audio to the TX on TCP port 7005.
Format: 48kHz, 16-bit signed LE, stereo interleaved. No headers.

This script sniffs the TCP stream from the bridge interface.
Must run on the bridge host (Orange Pi) with both devices connected.

Outputs raw PCM to stdout.

Usage examples:
  # Play directly:
  python3 receive_return_audio.py | play -t raw -r 48000 -e signed -b 16 -c 2 -

  # Record to WAV:
  python3 receive_return_audio.py | sox -t raw -r 48000 -e signed -b 16 -c 2 - output.wav

  # Record to FLAC:
  python3 receive_return_audio.py | ffmpeg -f s16le -ar 48000 -ac 2 -i - output.flac
"""

import subprocess
import struct
import sys
import os
import signal
import argparse


def main():
    parser = argparse.ArgumentParser(description='Receive return audio from M-A202 RX device')
    parser.add_argument('--iface', default='br0', help='Network interface to sniff (default: br0)')
    parser.add_argument('--rx-ip', default='192.168.1.108', help='RX device IP (default: 192.168.1.108)')
    parser.add_argument('--tx-ip', default='192.168.1.100', help='TX device IP (default: 192.168.1.100)')
    parser.add_argument('--port', type=int, default=7005, help='TCP control port (default: 7005)')
    args = parser.parse_args()

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    stderr = sys.stderr
    out_fd = sys.stdout.fileno()

    # Use tcpdump to capture the raw TCP stream
    # Filter: RX->TX on port 7005 (audio direction)
    bpf = "src host %s and dst host %s and tcp port %d" % (args.rx_ip, args.tx_ip, args.port)

    print("Sniffing return audio on %s (%s -> %s:%d)..." % (args.iface, args.rx_ip, args.tx_ip, args.port), file=stderr)
    print("Format: 48kHz stereo 16-bit LE (raw PCM over TCP, no headers)", file=stderr)
    print("Ctrl+C to stop", file=stderr)

    proc = subprocess.Popen(
        ["tcpdump", "-nn", "-i", args.iface, "-w", "-", "-U", bpf],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )

    try:
        # Read pcap global header
        pcap_hdr = proc.stdout.read(24)
        if len(pcap_hdr) < 24:
            print("Failed to start capture", file=stderr)
            return

        frame_count = 0
        byte_count = 0

        while True:
            # Read pcap packet header
            phdr = proc.stdout.read(16)
            if len(phdr) < 16:
                break
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack("<IIII", phdr)
            data = proc.stdout.read(incl_len)
            if len(data) < incl_len:
                break

            # Parse ethernet + IP + TCP to extract payload
            if len(data) < 54:
                continue
            ip_hdr_len = (data[14] & 0x0F) * 4
            tcp_off = 14 + ip_hdr_len
            tcp_hdr_len = ((data[tcp_off + 12] >> 4) & 0xF) * 4
            payload = data[tcp_off + tcp_hdr_len:]

            if len(payload) > 0:
                os.write(out_fd, payload)
                frame_count += 1
                byte_count += len(payload)

    except KeyboardInterrupt:
        print("\nStopped. (%d segments, %d bytes)" % (frame_count, byte_count), file=stderr)
    except BrokenPipeError:
        pass
    finally:
        proc.terminate()
        proc.wait()


if __name__ == '__main__':
    main()
