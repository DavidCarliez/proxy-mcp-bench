#!/usr/bin/env python3
"""Send a deterministic ~20k-request corpus through an HTTP proxy.

Usage: gen_traffic.py --proxy 127.0.0.1:8080 [--count 20000] [--threads 32] [--port 18080]
       gen_traffic.py --expected            # print expected needle counts as JSON, send nothing

The corpus is generated from a fixed seed, so Burp and Caido receive identical requests
(arrival order differs slightly under concurrency). The very last request is sent alone, after
all workers finish: GET http://api.localhost:18080/api/v1/health?final=1
"""
import argparse
import base64
import http.client
import json
import random
import sys
import threading
import time
from collections import Counter
from urllib.parse import urlsplit

SEED = 1337


def jwt(sub):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc({'sub': sub, 'role': 'user'})}.c2lnbmF0dXJl"


def build_corpus(count, port):
    rng = random.Random(SEED)
    out = []
    base = lambda h: f"http://{h}.localhost:{port}"
    for i in range(count):
        r = rng.random()
        hdrs = {"User-Agent": "Mozilla/5.0 bench", "Accept": "*/*"}
        method, url, body = "GET", None, b""
        if r < 0.30:
            url = f"{base('shop')}/product/{rng.randrange(1, 3000)}"
        elif r < 0.38:
            url = f"{base('shop')}/search?q={rng.choice(['shoes', 'hat', 'red+dress', 'bag', 'sale'])}"
        elif r < 0.43:
            url = f"{base('shop')}/category/{rng.choice(['men', 'women', 'kids', 'home'])}"
        elif r < 0.46:
            method, url = "POST", f"{base('shop')}/cart/add"
            body = f"product={rng.randrange(1, 3000)}&qty={rng.randrange(1, 5)}".encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        elif r < 0.71:
            uid = rng.randrange(1, 10000)
            if uid == 7777:
                uid = 7776
            url = f"{base('api')}/api/v1/users/{uid}"
            if rng.random() > 0.05:
                hdrs["Authorization"] = f"Bearer {jwt(rng.randrange(1, 500))}"
        elif r < 0.79:
            url = f"{base('api')}/api/v1/orders?user={rng.randrange(1, 10000)}&page={rng.randrange(1, 20)}"
            hdrs["Authorization"] = f"Bearer {jwt(rng.randrange(1, 500))}"
        elif r < 0.82:
            method, url = "POST", f"{base('api')}/api/v1/orders"
            body = json.dumps({"sku": f"SKU-{rng.randrange(10**5)}", "qty": rng.randrange(1, 9)}).encode()
            hdrs["Content-Type"] = "application/json"
            hdrs["Authorization"] = f"Bearer {jwt(rng.randrange(1, 500))}"
        elif r < 0.83:
            method, url = "DELETE", f"{base('api')}/api/v1/orders/{rng.randrange(10**6)}"
            hdrs["Authorization"] = f"Bearer {jwt(rng.randrange(1, 500))}"
        elif r < 0.85:
            method, url = "PUT", f"{base('api')}/api/v1/users/{rng.randrange(1, 10000)}"
            body = json.dumps({"bio": "updated"}).encode()
            hdrs["Content-Type"] = "application/json"
            hdrs["Authorization"] = f"Bearer {jwt(rng.randrange(1, 500))}"
        elif r < 0.89:
            url = f"{base('admin')}/admin/{rng.choice(['users', 'settings', 'logs', 'billing', 'login'])}"
            if rng.random() < 0.1:
                hdrs["Cookie"] = "role=admin; sid=abc"
        elif r < 0.965:
            url = f"{base('static')}/assets/" + rng.choice(
                [f"chunk.{rng.randrange(400):03x}.js", f"img/{rng.randrange(900)}.png", f"style.{rng.randrange(50)}.css"])
        elif r < 0.985:
            method, url = "POST", f"{base('auth')}/login"
            body = f"username=user{rng.randrange(100)}&password={'correct' if rng.random() < 0.2 else 'wrong'}".encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        elif r < 0.995:
            method, url = "POST", f"{base('graphql')}/graphql"
            body = json.dumps({"query": "{ me { id } }"}).encode()
            hdrs["Content-Type"] = "application/json"
        else:
            url = rng.choice([f"{base('shop')}/crash/{rng.randrange(100)}",
                              f"{base('api')}/api/v1/legacy/{rng.randrange(100)}"])
        out.append({"method": method, "url": url, "headers": hdrs, "body": body})

    # Planted needles at fixed positions (overwrite, so the count stays exact).
    def put(idx, **spec):
        hdrs = {"User-Agent": "Mozilla/5.0 bench", "Accept": "*/*", **spec.pop("headers", {})}
        out[idx] = {"method": spec.get("method", "GET"), "url": spec["url"], "headers": hdrs,
                    "body": spec.get("body", b"")}

    bearer = {"Authorization": f"Bearer {jwt(42)}"}
    put(13777, url=f"{base('api')}/api/v1/users/7777", headers=bearer)          # FLAG in response body
    put(4100, url=f"{base('static')}/assets/vendor.3c9e.js")                    # AWS-like key in big JS
    put(16020, url=f"{base('static')}/assets/vendor.3c9e.js")
    for j, idx in enumerate([2500, 9100, 15500, 19000, 19950]):                 # reflected marker
        put(idx, url=f"{base('shop')}/search?q=%3Csvg%2Fonload%3Domp{j}%3E")
    put(8888, url=f"{base('shop')}/product/1", headers={"X-Debug-Token": "dbg-41c2"})  # unique request header
    for j, idx in enumerate([300, 7000, 12000]):                                 # ~1MB responses
        put(idx, url=f"{base('static')}/big/report.json?n={j}")
    ssrf = [f"{base('shop')}/fetch?url=http%3A%2F%2F169.254.169.254%2Flatest%2Fmeta-data%2F",
            f"{base('api')}/api/v1/webhooks?callback=http%3A%2F%2Finternal.corp%3A8080%2Fhook",
            f"{base('auth')}/oauth/authorize?client_id=web&redirect_uri=https%3A%2F%2Fevil.example%2Fcb"]
    for j, idx in enumerate(range(500, 20000, 800)):                              # SSRF/redirect params
        spec = {"url": ssrf[j % 3]}
        if "api." in spec["url"]:
            spec["headers"] = bearer
        put(idx % len(out), **spec)
    return out


def expected(corpus):
    """Ground truth for docs/tasks.md, computed from the corpus itself."""
    def host(c):
        return urlsplit(c["url"]).hostname

    def path(c):
        return urlsplit(c["url"]).path

    hosts = Counter(c["url"].split("/")[2].split(":")[0] for c in corpus)
    methods = Counter(c["method"] for c in corpus)
    return {
        "total_including_final": len(corpus) + 1,
        "hosts": dict(hosts),
        "methods": dict(methods),
        "flag_in_response": sum("/api/v1/users/7777" in c["url"] for c in corpus),
        "aws_key_in_response": sum(c["url"].endswith("/vendor.3c9e.js") for c in corpus),
        "reflected_marker_requests": sum("onload%3Domp" in c["url"] for c in corpus),
        "x_debug_token_requests": sum("X-Debug-Token" in c["headers"] for c in corpus),
        "big_responses": sum("/big/report.json" in c["url"] for c in corpus),
        "ssrf_param_requests": sum(any(k in c["url"] for k in ("url=", "callback=", "redirect_uri=")) for c in corpus),
        "admin_cookie_requests": sum("role=admin" in c["headers"].get("Cookie", "") for c in corpus),
        "final_request": "GET http://api.localhost:PORT/api/v1/health?final=1",
        "T5_admin_403": sum(1 for c in corpus if host(c) == "admin.localhost" and path(c) != "/admin/login"
                            and "role=admin" not in c["headers"].get("Cookie", "")),
        "T8_500_traceback": sum(1 for c in corpus if path(c).startswith("/crash")),
        "T8_500_npe": sum(1 for c in corpus if path(c).startswith("/api/v1/legacy/")),
        "T11_post_orders": sum(1 for c in corpus if c["method"] == "POST" and host(c) == "api.localhost"
                               and path(c) == "/api/v1/orders"),
        "T12_user_email_regex_matches": sum(1 for c in corpus if host(c) == "api.localhost"
                                            and path(c).startswith("/api/v1/users/")
                                            and "Authorization" in c["headers"] and c["method"] in ("GET", "PUT")),
        "api_401_no_bearer": sum(1 for c in corpus if host(c) == "api.localhost"
                                 and not path(c).startswith("/api/v1/legacy/") and "Authorization" not in c["headers"]),
    }


def send_all(corpus, proxy, threads):
    phost, pport = proxy.split(":")
    lock = threading.Lock()
    idx = [0]
    stats = Counter()

    def worker():
        conn = http.client.HTTPConnection(phost, int(pport), timeout=60)
        while True:
            with lock:
                i = idx[0]
                idx[0] += 1
            if i >= len(corpus):
                break
            c = corpus[i]
            for attempt in range(3):
                try:
                    conn.request(c["method"], c["url"], body=c["body"] or None, headers=c["headers"])
                    resp = conn.getresponse()
                    resp.read()
                    stats[resp.status // 100] += 1
                    break
                except Exception:
                    conn.close()
                    conn = http.client.HTTPConnection(phost, int(pport), timeout=60)
                    if attempt == 2:
                        stats["err"] += 1

    t0 = time.time()
    ts = [threading.Thread(target=worker) for _ in range(threads)]
    for t in ts:
        t.start()
    last_report = t0
    while any(t.is_alive() for t in ts):
        time.sleep(1)
        if time.time() - last_report > 10:
            print(f"  {idx[0]}/{len(corpus)} sent, {time.time()-t0:.0f}s", file=sys.stderr, flush=True)
            last_report = time.time()
    for t in ts:
        t.join()
    return stats, time.time() - t0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy")
    ap.add_argument("--count", type=int, default=20000)
    ap.add_argument("--threads", type=int, default=32)
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--expected", action="store_true")
    a = ap.parse_args()
    corpus = build_corpus(a.count, a.port)
    if a.expected:
        print(json.dumps(expected(corpus), indent=1))
        sys.exit(0)
    stats, dt = send_all(corpus, a.proxy, a.threads)
    final = http.client.HTTPConnection(*a.proxy.split(":"), timeout=60)
    final.request("GET", f"http://api.localhost:{a.port}/api/v1/health?final=1", headers={"User-Agent": "bench-final"})
    fr = final.getresponse(); fr.read()
    print(json.dumps({"sent": len(corpus) + 1, "status_classes": dict(stats), "final_status": fr.status,
                      "seconds": round(dt, 1)}))
