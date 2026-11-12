"""Serve screen/gallery/site on one address (the tailnet IP), Markdown as plain text.

  python3 screen/gallery/serve.py --bind 100.x.y.z --port 8790
"""

import argparse
import functools
import http.server
import pathlib

SITE = pathlib.Path(__file__).resolve().parent / "site"


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".md": "text/plain; charset=utf-8", ".json": "application/json; charset=utf-8",
                      ".html": "text/html; charset=utf-8"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", required=True)
    ap.add_argument("--port", type=int, default=8790)
    a = ap.parse_args()
    handler = functools.partial(Handler, directory=str(SITE))
    with http.server.ThreadingHTTPServer((a.bind, a.port), handler) as srv:
        print(f"serving {SITE} on http://{a.bind}:{a.port}/", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
