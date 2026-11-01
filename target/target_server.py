#!/usr/bin/env python3
"""Deterministic multi-vhost target for proxy/MCP benchmarks.

Listens on [::]:18080 (dual-stack). Virtual hosts are selected by the Host header:
shop/api/admin/static/auth/graphql/internal .localhost. Responses are a pure function of
(method, host, path, query, body) so Burp and Caido capture identical traffic.

Planted needles (see corpus/gen_traffic.py):
  GET  api.localhost /api/v1/users/7777        -> body contains FLAG{needle-7f3a91}
  GET  static.localhost /assets/vendor.3c9e.js  -> body contains AKIAQ3EXAMPLEKEY7777 (AWS-like key)
  GET  shop.localhost /search?q=<marker>        -> reflects q unescaped (XSS-style reflection)
  *    any /crash* path                          -> 500 with Python traceback
  GET  api.localhost /api/v1/legacy/*           -> 500 with java.lang.NullPointerException
"""
import hashlib
import json
import random
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18080


def seeded(*parts):
    return random.Random(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest())


def html_page(title, body):
    return f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>"


LOREM = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
         "incididunt ut labore et dolore magna aliqua ").split()


def lorem(rng, words):
    return " ".join(rng.choice(LOREM) for _ in range(words))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BenchTarget/1.0"

    def log_message(self, *args):
        pass

    def _send(self, status, body, ctype="text/html; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _handle(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        u = urlsplit(self.path)
        path, q = u.path, parse_qs(u.query)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        rng = seeded(self.command, host, path, u.query, body)
        auth = self.headers.get("Authorization", "")

        if path.startswith("/crash"):
            tb = ("Traceback (most recent call last):\n  File \"/srv/app/views.py\", line 88, in handle\n"
                  "    return render(obj.items)\nAttributeError: 'NoneType' object has no attribute 'items'\n")
            return self._send(500, html_page("500 Internal Server Error", f"<pre>{tb}</pre>"))

        if host.startswith("shop."):
            if path.startswith("/product/"):
                pid = path.rsplit("/", 1)[-1]
                return self._send(200, html_page(f"Product {pid} | Shop",
                                                 f"<h1>Product {pid}</h1><p>{lorem(rng, 120)}</p>"),
                                  headers={"X-Cache": rng.choice(["HIT", "MISS"])})
            if path == "/search":
                term = q.get("q", [""])[0]
                return self._send(200, html_page("Search", f"<p>Results for {term}</p><p>{lorem(rng, 40)}</p>"))
            if path.startswith("/category/"):
                return self._send(200, html_page(f"Category {path.rsplit('/',1)[-1]}", lorem(rng, 200)))
            if path == "/cart/add" and self.command == "POST":
                return self._send(302, "", headers={"Location": "/cart", "Set-Cookie": f"cart={rng.randrange(10**9)}; Path=/"})
            if path == "/cart":
                return self._send(200, html_page("Cart", lorem(rng, 30)))
            if path == "/fetch":
                target = q.get("url", [""])[0]
                return self._send(200, json.dumps({"fetched": target, "status": "queued"}), "application/json")
            return self._send(404, html_page("404 Not Found", "nope"))

        if host.startswith("api."):
            if path.startswith("/api/v1/legacy/"):
                return self._send(500, "java.lang.NullPointerException\n\tat com.acme.LegacyController.get(LegacyController.java:42)\n",
                                  "text/plain")
            if path == "/api/v1/health":
                return self._send(200, json.dumps({"ok": True, "final": q.get("final", ["0"])[0]}), "application/json")
            if not auth.startswith("Bearer "):
                return self._send(401, json.dumps({"error": "missing bearer token"}), "application/json",
                                  headers={"WWW-Authenticate": "Bearer"})
            if path.startswith("/api/v1/users/"):
                uid = path.rsplit("/", 1)[-1]
                doc = {"id": uid, "email": f"user{uid}@example.test", "role": rng.choice(["user", "user", "admin"]),
                       "bio": lorem(rng, 60)}
                if uid == "7777":
                    doc["note"] = "FLAG{needle-7f3a91}"
                if self.command in ("PUT", "PATCH"):
                    doc["updated"] = True
                return self._send(200, json.dumps(doc), "application/json")
            if path == "/api/v1/orders":
                if self.command == "POST":
                    return self._send(201, json.dumps({"order": rng.randrange(10**6), "echo": body.decode(errors="replace")}),
                                      "application/json")
                items = [{"order": rng.randrange(10**6), "total": round(rng.random() * 500, 2)} for _ in range(25)]
                return self._send(200, json.dumps({"page": q.get("page", ["1"])[0], "items": items}), "application/json")
            if path.startswith("/api/v1/orders/") and self.command == "DELETE":
                return self._send(204, "")
            if path == "/api/v1/webhooks":
                return self._send(200, json.dumps({"callback": q.get("callback", [""])[0], "registered": True}),
                                  "application/json")
            return self._send(404, json.dumps({"error": "not found"}), "application/json")

        if host.startswith("admin."):
            if path == "/admin/login":
                return self._send(200, html_page("Admin Login", "<form method=post><input name=u></form>"))
            role = self.headers.get("Cookie", "")
            if "role=admin" in role:
                return self._send(200, html_page("Admin Panel", lorem(rng, 80)))
            return self._send(403, html_page("403 Forbidden", "Access denied"))

        if host.startswith("static."):
            if path.endswith(".js"):
                size = 20_000 if "chunk" in path else 150_000
                js = ("/*! bundle */\n" + "".join(f"var a{i}=\"{lorem(rng, 3)}\";\n" for i in range(size // 30)))
                if path == "/assets/vendor.3c9e.js":
                    mid = len(js) // 2
                    js = js[:mid] + 'var awsKey="AKIAQ3EXAMPLEKEY7777";\n' + js[mid:]
                return self._send(200, js, "application/javascript")
            if path.endswith(".png"):
                blob = bytes(rng.randrange(256) for _ in range(8000))
                return self._send(200, b"\x89PNG\r\n\x1a\n" + blob, "image/png")
            if path.endswith(".css"):
                return self._send(200, "body{margin:0}" * 500, "text/css")
            if path == "/big/report.json":
                rows = [{"i": i, "v": lorem(rng, 8)} for i in range(18000)]
                return self._send(200, json.dumps(rows), "application/json")
            return self._send(404, "not found", "text/plain")

        if host.startswith("auth."):
            if path == "/login" and self.command == "POST":
                ok = b"password=correct" in body
                return self._send(302 if ok else 200, "" if ok else html_page("Login failed", "bad creds"),
                                  headers={"Location": "/home", "Set-Cookie": "session=s3cr3t-sess; HttpOnly"} if ok else {})
            if path == "/oauth/authorize":
                return self._send(302, "", headers={"Location": q.get("redirect_uri", ["/"])[0]})
            return self._send(200, html_page("Auth", "ok"))

        if host.startswith("graphql."):
            return self._send(200, json.dumps({"data": {"me": {"id": rng.randrange(10**5)}}}), "application/json")

        return self._send(404, "unknown vhost", "text/plain")

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _handle


class DualStackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True
    request_queue_size = 512

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


if __name__ == "__main__":
    print(f"bench target listening on [::]:{PORT}", flush=True)
    DualStackServer(("::", PORT), Handler).serve_forever()
