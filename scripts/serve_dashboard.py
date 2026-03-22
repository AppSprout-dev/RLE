"""Tiny CORS-enabled file server for dashboard tick data."""
import http.server
import sys
from pathlib import Path


class CORSHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else "results/live"
    Path(directory).mkdir(parents=True, exist_ok=True)
    def handler(*a, **kw):
        return CORSHandler(*a, directory=directory, **kw)
    server = http.server.HTTPServer(("", 9000), handler)
    print(f"Serving {directory}/ on http://localhost:9000 (CORS enabled)")
    server.serve_forever()
