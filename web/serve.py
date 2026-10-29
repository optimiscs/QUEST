#!/usr/bin/env python3
"""Serve the local QUEST trace workspace without starting an evaluation."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=6080)
    args = parser.parse_args()
    site = Path(__file__).resolve().parent / 'trace-viewer'
    if not site.is_dir():
        raise SystemExit(f'Viewer directory not found: {site}')
    handler = partial(SimpleHTTPRequestHandler, directory=str(site))
    with ThreadingHTTPServer((args.host, args.port), handler) as server:
        print(f'Trace viewer: http://{args.host}:{server.server_port}/trace-viewer-zh/', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

if __name__ == '__main__':
    main()
