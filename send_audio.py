#!/usr/bin/env python3
"""
Send audio TO the HDMI-over-IP extender RX unit, mimicking the TX protocol.

Protocol: Proprietary UDP multicast with DEADBEEF magic header.
Format: 16-bit signed PCM, little-endian, stereo interleaved, 48000 Hz.

Reads raw PCM from stdin. Generate it with ffmpeg, sox, VLC, etc.

Usage examples:
  # Send a WAV file:
  ffmpeg -i music.wav -f s16le -ar 48000 -ac 2 - | python3 send_audio.py

  # Send MP3/FLAC/any format:
  ffmpeg -i music.mp3 -f s16le -ar 48000 -ac 2 - | python3 send_audio.py

  # Send from ALSA microphone:
  arecord -f S16_LE -c 2 -r 48000 | python3 send_audio.py

  # Send with VLC:
  cvlc input.mp3 --sout '#transcode{acodec=s16l,channels=2,samplerate=48000}:std{access=file,mux=raw,dst=-}' | python3 send_audio.py

  # Send from PulseAudio monitor (desktop audio):
  parec --format=s16le --channels=2 --rate=48000 | python3 send_audio.py

  # Generate a test tone:
  python3 -c "
import struct, math
sr=48000; dur=5; freq=440
for i in range(sr*dur):
    s = int(16000 * math.sin(2*math.pi*freq*i/sr))
    print(end='', flush=False)
    import sys; sys.stdout.buffer.write(struct.pack('<hh', s, s))
" | python3 send_audio.py

  # Custom multicast:
  python3 send_audio.py --mcast 224.0.0.100 --port 7001
"""

import socket
import struct
import sys
import time
import argparse
import signal

MAGIC = 0xDEADBEEF
HEADER_SIZE = 16
STREAM_HEADER_SIZE = 20
PAYLOAD_SIZE = 1400  # Total UDP payload per packet
PACKETS_PER_FRAME = 3
STREAM_NAME = b'hdmi_rx\x00'  # 8 bytes, null-padded


def build_header_packet(audio_chunk, total_audio_len, sample_rate):
    """Build seq=0 packet with stream metadata + audio data."""
    hdr = struct.pack('<IIII', MAGIC, 0, PAYLOAD_SIZE, PACKETS_PER_FRAME)
    stream_hdr = STREAM_NAME + struct.pack('<III', total_audio_len, 0, sample_rate)
    audio_space = PAYLOAD_SIZE - HEADER_SIZE - STREAM_HEADER_SIZE
    audio_data = audio_chunk[:audio_space]
    # Pad if needed
    if len(audio_data) < audio_space:
        audio_data += b'\x00' * (audio_space - len(audio_data))
    return hdr + stream_hdr + audio_data, audio_space


def build_data_packet(seq, audio_chunk):
    """Build seq=1 or seq=2 continuation packet."""
    hdr = struct.pack('<IIII', MAGIC, seq, PAYLOAD_SIZE, PACKETS_PER_FRAME)
    audio_space = PAYLOAD_SIZE - HEADER_SIZE
    audio_data = audio_chunk[:audio_space]
    if len(audio_data) < audio_space:
        audio_data += b'\x00' * (audio_space - len(audio_data))
    return hdr + audio_data, audio_space


def main():
    parser = argparse.ArgumentParser(description='Send audio to HDMI-over-IP extender RX')
    parser.add_argument('--mcast', default='224.0.0.100', help='Multicast group (default: 224.0.0.100)')
    parser.add_argument('--port', type=int, default=7001, help='UDP port (default: 7001)')
    parser.add_argument('--rate', type=int, default=48000, help='Sample rate (default: 48000)')
    parser.add_argument('--ttl', type=int, default=255, help='Multicast TTL (default: 255)')
    parser.add_argument('--src-port', type=int, default=62510, help='Source UDP port (default: 62510)')
    args = parser.parse_args()

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, args.ttl)
    sock.bind(('', args.src_port))

    # Calculate audio bytes per frame to match original device timing
    # Original: 4116 bytes per frame = 1029 stereo sample pairs ≈ 21.4ms at 48kHz
    audio_per_header = PAYLOAD_SIZE - HEADER_SIZE - STREAM_HEADER_SIZE  # 1364
    audio_per_data = PAYLOAD_SIZE - HEADER_SIZE  # 1384
    total_audio_per_frame = audio_per_header + audio_per_data * (PACKETS_PER_FRAME - 1)  # 4132
    # Use 4116 to match original device (last 16 bytes of frame are zero-padded)
    AUDIO_PER_FRAME = 4116
    frame_samples = AUDIO_PER_FRAME // 4  # stereo 16-bit = 4 bytes per sample pair
    frame_duration = frame_samples / args.rate

    dest = (args.mcast, args.port)
    stdin = sys.stdin.buffer
    stderr = sys.stderr

    print(f"Sending audio to {args.mcast}:{args.port}", file=stderr)
    print(f"Format: S16LE stereo {args.rate}Hz", file=stderr)
    print(f"Frame: {AUDIO_PER_FRAME} bytes ({frame_duration*1000:.1f}ms)", file=stderr)
    print(f"Reading PCM from stdin... (Ctrl+C to stop)", file=stderr)

    try:
        frame_start = time.monotonic()
        while True:
            # Read one frame of audio
            audio = stdin.read(AUDIO_PER_FRAME)
            if not audio:
                break
            if len(audio) < AUDIO_PER_FRAME:
                audio += b'\x00' * (AUDIO_PER_FRAME - len(audio))

            offset = 0

            # Packet 0: header + audio
            pkt0, consumed = build_header_packet(audio[offset:], AUDIO_PER_FRAME, args.rate)
            sock.sendto(pkt0, dest)
            offset += consumed

            # Packets 1..N-1: data
            for seq in range(1, PACKETS_PER_FRAME):
                pkt, consumed = build_data_packet(seq, audio[offset:])
                sock.sendto(pkt, dest)
                offset += consumed

            # Pace to real-time
            frame_start += frame_duration
            sleep_time = frame_start - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)
            elif sleep_time < -0.1:
                # Fell behind, reset timing
                frame_start = time.monotonic()

    except KeyboardInterrupt:
        print("\nStopped.", file=stderr)
    except BrokenPipeError:
        pass
    finally:
        sock.close()


if __name__ == '__main__':
    main()
