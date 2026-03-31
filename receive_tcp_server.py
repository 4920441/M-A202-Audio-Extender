#!/usr/bin/env python3
"""
TCP server that accepts connections from M-A202 RX device on port 7005.

The RX sends raw 48kHz stereo 16-bit PCM over TCP. No headers.
This script listens on port 7005, accepts the RX's connection,
and outputs the raw PCM to stdout.

To use: set the RX device's gateway IP to this host's IP,
then the RX will connect here instead of to the TX.

Usage:
  python3 receive_tcp_server.py | play -t raw -r 48000 -e signed -b 16 -c 2 -
  python3 receive_tcp_server.py | sox -t raw -r 48000 -e signed -b 16 -c 2 - output.wav
  python3 receive_tcp_server.py | ffmpeg -f s16le -ar 48000 -ac 2 -i - output.flac
"""

import socket
import sys
import os
import signal
import argparse
import time


def main():
    parser = argparse.ArgumentParser(description='TCP server for M-A202 RX return audio')
    parser.add_argument('--port', type=int, default=7005, help='Listen port (default: 7005)')
    parser.add_argument('--bind', default='0.0.0.0', help='Bind address (default: 0.0.0.0)')
    args = parser.parse_args()

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    stderr = sys.stderr
    out_fd = sys.stdout.fileno()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.bind, args.port))
    srv.listen(1)

    print("Listening on %s:%d - waiting for RX device..." % (args.bind, args.port), file=stderr)

    conn, addr = srv.accept()
    print("Connected from %s:%d" % addr, file=stderr)
    print("Receiving audio... (Ctrl+C to stop)", file=stderr)

    # Send periodic 6-byte ACKs like the TX does
    ack = b'\x00\x00\x00\x00\x00\x00'
    byte_count = 0
    last_ack = time.monotonic()

    try:
        while True:
            data = conn.recv(8192)
            if not data:
                print("Connection closed by RX.", file=stderr)
                break

            # Skip small packets (< 7 bytes might be control, not audio)
            if len(data) > 6:
                os.write(out_fd, data)
                byte_count += len(data)

            # Send ACK every ~20ms like the TX does
            now = time.monotonic()
            if now - last_ack > 0.02:
                try:
                    conn.sendall(ack)
                except BrokenPipeError:
                    break
                last_ack = now

    except KeyboardInterrupt:
        print("\nStopped. (%d bytes received)" % byte_count, file=stderr)
    except BrokenPipeError:
        pass
    finally:
        conn.close()
        srv.close()


if __name__ == '__main__':
    main()
