"""Dead-simple CoT listener over plain TCP (port 8087).

Connects to a TAK server and prints the CoT XML it streams back to you.
Great for confirming the server is alive and seeing what other clients emit.
Raw sockets on purpose: zero surprises, no library internals to debug at 2am.

Usage:
    python recv_cot.py SERVER_IP 8087
"""
import socket
import sys


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8087

    print(f"[recv] connecting to {host}:{port} ...")
    with socket.create_connection((host, port), timeout=10) as s:
        print("[recv] connected. streaming CoT (Ctrl-C to stop):\n")
        buf = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                print("[recv] server closed connection")
                break
            buf += chunk
            # CoT events over plain TCP are delimited by the closing tag.
            while b"</event>" in buf:
                event, buf = buf.split(b"</event>", 1)
                print((event + b"</event>").decode("utf-8", "replace").strip())
                print("-" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[recv] bye")
