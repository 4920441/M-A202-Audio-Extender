#!/usr/bin/env python3
"""
TCP server that accepts audio from M-A202 RX device on port 7005.

The RX sends raw 48kHz stereo 16-bit PCM over TCP. No headers.
Auto-reconnects when the RX device drops and reconnects.

Usage:
  python3 receive_tcp_server.py | play -t raw -r 48000 -e signed -b 16 -c 2 -

  # Via SSH (keep stderr separate!):
  ssh root@host "python3 receive_tcp_server.py" 2>/dev/null | play -t raw -r 48000 -e signed -b 16 -c 2 -
"""

import socket
import sys
import os
import signal
import argparse
import threading
import time


def ack_sender(conn, stop_event):
    """Send 6-byte ACKs periodically like the TX does."""
    ack = b'\x00\x00\x00\x00\x00\x00'
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
            conn.sendall(ack)
    except:
        pass


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

    print("Listening on %s:%d..." % (args.bind, args.port), file=stderr)

    while True:
        conn, addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print("Connected from %s:%d" % addr, file=stderr)

        stop_event = threading.Event()
        ack_thread = threading.Thread(target=ack_sender, args=(conn, stop_event), daemon=True)
        ack_thread.start()

        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                os.write(out_fd, data)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            stop_event.set()
            conn.close()

        print("Disconnected. Waiting for reconnect..." , file=stderr)


if __name__ == '__main__':
    main()
