import asyncio, sys, time, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'apps', 'api'))

from app.core.webhooks import deliver_webhook

# Spin up a tiny in-process HTTP server that returns 401, count requests
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

COUNT = {'n': 0, 'status': 401}

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        COUNT['n'] += 1
        length = int(self.headers.get('Content-Length', 0))
        _ = self.rfile.read(length)
        self.send_response(COUNT['status'])
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'unauthorized')
    def log_message(self, *a, **k): pass

srv = HTTPServer(('127.0.0.1', 0), H)
port = srv.server_address[1]
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()

async def main():
    for status in (401, 404, 410, 422):
        COUNT['n'] = 0
        COUNT['status'] = status
        t0 = time.time()
        r = await deliver_webhook(
            url=f'http://127.0.0.1:{port}/hook',
            signing_secret='s',
            event='exec.done',
            data={'k': 'v'},
            max_retries=3,
            backoff_schedule=(1, 1, 1),
        )
        dt = time.time() - t0
        print(f'status={status} attempts={r.get("attempts")} delivered={r.get("delivered")} server_hits={COUNT["n"]} elapsed={dt:.2f}s')

asyncio.run(main())
srv.shutdown()
