"""Build and serve the synthetic static workspace on loopback for browser checks."""
import argparse
import functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from build_site import build, OUTPUT

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8951)
    args = parser.parse_args()
    build()
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(OUTPUT))
    ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()
