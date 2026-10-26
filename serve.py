#!/usr/bin/env python3
"""Local preview server with live reload and edit mode.

Run:  python3 serve.py        then open http://localhost:8765
- Any saved change to a file in this folder reloads the open page.
- The site's Edit button (shown only here, never on the public site)
  saves text to content.json and uploads documents and pictures to files/.
  Every save keeps the previous content.json in .backups/.
Only for local editing; GitHub Pages ignores this file.
"""
import datetime, http.server, json, os, re, shutil, socketserver, sys, urllib.parse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(ROOT, "content.json")
BACKUPS = os.path.join(ROOT, ".backups")
MAX_UPLOAD = 100 * 1024 * 1024
ALLOWED_HOSTS = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}

RELOAD = b"""<script>(()=>{let last=null;setInterval(async()=>{try{const r=await fetch('/__mtime',{cache:'no-store'});const t=await r.text();if(last&&t!==last&&!window.__noReload)location.reload();last=t;}catch(e){}},800);})();</script>"""


def latest_mtime():
    m = 0.0
    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            try:
                m = max(m, os.path.getmtime(os.path.join(dirpath, f)))
            except OSError:
                pass
    return m


def safe_name(name):
    name = os.path.basename(name or "").strip()
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.") or "file"
    ext = re.sub(r"[^A-Za-z0-9.]+", "", ext).lower()
    return stem[:80] + ext[:10]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def local_only(self):
        # Only accept edits made from this computer's own browser tab.
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        ok = host in ALLOWED_HOSTS and (not origin or urllib.parse.urlparse(origin).netloc in ALLOWED_HOSTS)
        if not ok:
            self.send_json(403, {"error": "Edits are only allowed from localhost."})
        return ok

    def do_GET(self):
        if self.path == "/__mtime":
            body = str(latest_mtime()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/__ping":
            if self.local_only():
                self.send_json(200, {"edit": True})
            return
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            path = os.path.join(path, "index.html")
        if path.endswith(".html") and os.path.isfile(path):
            with open(path, "rb") as f:
                html = f.read().replace(b"</body>", RELOAD + b"</body>", 1)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        super().do_GET()

    def do_POST(self):
        if not self.local_only():
            return
        url = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            self.send_json(413, {"error": "File is larger than 100 MB."})
            return
        body = self.rfile.read(length)

        if url.path == "/__save":
            try:
                data = json.loads(body)
                assert isinstance(data.get("pins"), list)
            except Exception:
                self.send_json(400, {"error": "Not valid site content."})
                return
            if os.path.exists(CONTENT):
                os.makedirs(BACKUPS, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(CONTENT, os.path.join(BACKUPS, f"content-{stamp}.json"))
            tmp = CONTENT + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONTENT)
            self.send_json(200, {"saved": True})
            return

        if url.path == "/__upload":
            q = urllib.parse.parse_qs(url.query)
            name = safe_name((q.get("name") or [""])[0])
            folder = os.path.join(ROOT, "files")
            os.makedirs(folder, exist_ok=True)
            stem, ext = os.path.splitext(name)
            final, n = name, 2
            if (q.get("replace") or ["0"])[0] != "1":
                while os.path.exists(os.path.join(folder, final)):
                    final = f"{stem}-{n}{ext}"
                    n += 1
            with open(os.path.join(folder, final), "wb") as f:
                f.write(body)
            self.send_json(200, {"path": "files/" + final, "name": final})
            return

        self.send_json(404, {"error": "Unknown action."})

    def log_message(self, *a):
        pass


socketserver.ThreadingTCPServer.allow_reuse_address = True
with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as httpd:
    print(f"Serving {ROOT} at http://localhost:{PORT}  (live reload + edit mode on)")
    httpd.serve_forever()
