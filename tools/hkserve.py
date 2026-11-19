#!/usr/bin/env python3
"""tools/ipa/serve.py FILE ADDRESS PORT SECONDS: FILE, at /NAME and nowhere else, over plain HTTP, bound to this Mac's ADDRESS on the local network alone, for the phone's hkinstall to fetch.

The other end checks its SHA-256, and what is served is a public open-source build, so plain HTTP carries nothing to protect. It stops by itself after SECONDS, or after one
complete transfer, so that it runs only for a ticket and does not stay listening.
"""
import http.server
import os
import sys
import threading


def main():
    path, address, port, seconds = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
    name = "/" + os.path.basename(path)
    size = os.path.getsize(path)
    here = os.path.dirname(os.path.abspath(path))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != name:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            sent = 0
            try:
                with open(path, "rb") as source:
                    while piece := source.read(1 << 20):
                        self.wfile.write(piece)
                        sent += len(piece)
            except OSError as error:
                print("a transfer ended early:", sent, "bytes handed to the network,", type(error).__name__, flush=True)
                return
            print("served", size, "bytes", flush=True)
            # the phone posts its diagnose report next: keep listening for it

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            target = os.path.join(here, "diag.txt")
            with open(target, "wb") as out:
                out.write(body)
            print("----- POST %s, %d bytes -> %s -----" % (self.path, len(body), target), flush=True)
            print(body.decode("utf-8", "replace"), flush=True)
            print("----- end of POST -----", flush=True)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer((address, port), Handler)
    timer = threading.Timer(seconds, server.shutdown)
    timer.daemon = True
    timer.start()
    print("serving", name, size, "bytes on the local address, port", port, "for at most", seconds, "s", flush=True)
    server.serve_forever()
    print("stopped", flush=True)


if __name__ == "__main__":
    main()
