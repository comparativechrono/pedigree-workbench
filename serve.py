#!/usr/bin/env python3
"""Serve the workbench on http://localhost:PORT, as GitHub Pages would.

Open the page from a server rather than from the file itself: browsers do not
let a page opened as a file (file://...) start the web worker that runs Python,
or show Pedigree Studio in its frame.

usage:  python3 serve.py [PORT]      (then open http://localhost:PORT/)
"""
import http.server
import os
import socketserver
import sys


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map,
                          **{".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json",
                             ".wasm": "application/wasm", ".ped": "text/plain", ".mped": "text/plain",
                             ".obo": "text/plain", ".ipynb": "application/json"})

    def end_headers(self):
        # (while you change the files, the browser fetches them anew each time)
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("Serving on http://localhost:{}  (Ctrl+C to stop)".format(port))
    Server(("127.0.0.1", port), Handler).serve_forever()
