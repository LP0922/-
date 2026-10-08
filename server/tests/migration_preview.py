"""Read-only UI verification server. Never opens serial ports; rejects ALL POSTs."""
import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote
import mimetypes
from test_migration_api import offline_service, server

DIST = Path(__file__).resolve().parents[2] / 'web' / 'dist'
Base = server.make_handler(offline_service())


class ReadOnlyPreview(Base):
    def do_POST(self):
        self._send_json(403, {'error':'离线验证模式：所有设备写入已禁用'})

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith('/api/'):
            return super().do_GET()
        file = (DIST / unquote(path).lstrip('/')).resolve()
        if not file.is_relative_to(DIST.resolve()):
            return self.send_error(403)
        if not file.is_file():
            file = DIST / 'index.html'
        body = file.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8876)
    args = parser.parse_args()
    http = ThreadingHTTPServer(('127.0.0.1', args.port), ReadOnlyPreview)
    print('Read-only preview on http://127.0.0.1:' + str(args.port), flush=True)
    try:
        http.serve_forever()
    finally:
        http.server_close()
