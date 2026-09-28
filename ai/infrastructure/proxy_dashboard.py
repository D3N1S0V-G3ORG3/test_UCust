"""
proxy_dashboard.py
Реверс-прокси для Octopoda Dashboard.

Запускается на порту 7843 и проксирует все запросы к localhost:7842.
Для HTML-ответов автоматически инжектирует скрипт авторизации в localStorage,
чтобы React SPA не перекидывал на /login.

Запуск:
    python proxy_dashboard.py

Затем открыть: http://localhost:7843/dashboard
"""
import http.server
import urllib.request
import urllib.error
import urllib.parse
import sys

FLASK_PORT = 7842
API_PORT   = 8741
PROXY_PORT = 7843

AUTH_SCRIPT = f"""
<script>
(function(){{
  var keys = {{
    'octopoda_api_key':   'local-dev',
    'octopoda_tenant_id': 'dev',
    'octopoda_email':     'dev@ucust.local',
    'octopoda_base_url':  'http://localhost:{PROXY_PORT}'
  }};
  for (var k in keys) {{
    if (!localStorage.getItem(k) || localStorage.getItem(k) !== keys[k]) {{
        localStorage.setItem(k, keys[k]);
    }}
  }}
  if (window.location.pathname === '/login' || window.location.pathname === '/') {{
    window.location.replace('/dashboard/agents');
  }}
}})();
</script>
"""


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Quiet logging

    def _proxy(self, method):
        # Если это запрос к API (/v1/...) — шлём на Uvicorn (8741)
        # Всё остальное (дашборд и /api/...) — на Flask (7842)
        if self.path.startswith("/v1/"):
            url = f"http://127.0.0.1:{API_PORT}{self.path}"
            target_port = API_PORT
        else:
            url = f"http://127.0.0.1:{FLASK_PORT}{self.path}"
            target_port = FLASK_PORT

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""

        headers = {}
        for k, v in self.headers.items():
            if k.lower() not in ("host", "connection", "transfer-encoding"):
                headers[k] = v
        headers["Host"] = f"127.0.0.1:{target_port}"
        if "authorization" not in [k.lower() for k in headers]:
            headers["Authorization"] = "Bearer local-dev"

        req = urllib.request.Request(url, data=body or None, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as e:
            resp = e
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"Bad Gateway: {e}".encode("utf-8"))
            return

        raw = resp.read()
        content_type = resp.headers.get("Content-Type", "")

        if "text/html" in content_type:
            try:
                html = raw.decode("utf-8")
                if "</head>" in html:
                    html = html.replace("</head>", AUTH_SCRIPT + "</head>", 1)
                elif "<body" in html:
                    html = html.replace("<body", AUTH_SCRIPT + "<body", 1)
                raw = html.encode("utf-8")
            except Exception:
                pass

        self.send_response(resp.status if hasattr(resp, "status") else resp.code)
        skip = {"transfer-encoding", "content-encoding", "content-length", "connection"}
        for k, v in resp.headers.items():
            if k.lower() not in skip:
                self.send_header(k, v)
        if raw:
            self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def do_GET(self):    self._proxy("GET")
    def do_POST(self):   self._proxy("POST")
    def do_PUT(self):    self._proxy("PUT")
    def do_DELETE(self): self._proxy("DELETE")
    def do_OPTIONS(self):self._proxy("OPTIONS")
    def do_PATCH(self):  self._proxy("PATCH")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print()
    print("=" * 56)
    print("  UCust.AI - Smart Dashboard Proxy")
    print("=" * 56)
    print(f"  Proxy (You are here): http://localhost:{PROXY_PORT}")
    print(f"  -> UI Traffic:        http://localhost:{FLASK_PORT}")
    print(f"  -> API Traffic (/v1): http://localhost:{API_PORT}")
    print("=" * 56)
    print(f"  Dashboard: http://localhost:{PROXY_PORT}/dashboard")
    print(f"  Agents:    http://localhost:{PROXY_PORT}/dashboard/agents")
    print("=" * 56)
    print("  Ready.")

    server = http.server.ThreadingHTTPServer(("0.0.0.0", PROXY_PORT), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

