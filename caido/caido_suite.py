#!/usr/bin/env python3
"""Deterministic MCP benchmark for the two Caido MCP builds (stdio JSON-RPC).

  caido_suite.py --label caido-official --binary ./caido-mcp-server-v4.4.0 \
                 --url http://127.0.0.1:8080 --token-file caido.token \
                 --part 1|2|3 [--k 1] --out runs/caido.json

Part 1 = T1-T14 at 20k, Part 2 = S1-S4 sweep point (k = number of corpus loads),
Part 3 = tools/list size. Bytes = text returned to the model by tools/call.
Each task runs the best strategy available on that tool surface; the strategy is
recorded next to the numbers.
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from urllib.parse import urlsplit

TARGET = "http://127.0.0.1:18080"


class MCP:
    def __init__(self, binary, url, token):
        env = dict(os.environ, CAIDO_URL=url, CAIDO_ACCESS_TOKEN=token)
        self.p = subprocess.Popen([binary, "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env=env, text=True, bufsize=1)
        self.n = 0
        self.log = []
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "bench", "version": "1"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()
        self.url, self.token = url, token

    def newest_id(self):
        """Ground truth straight from Caido's GraphQL (not counted as an MCP call)."""
        q = '{ requests(first:1, order:{by:ID, ordering:DESC}) { nodes { id } } }'
        req = urllib.request.Request(self.url + "/graphql", data=json.dumps({"query": q}).encode(),
                                     headers={"content-type": "application/json",
                                              "authorization": f"Bearer {self.token}"})
        return json.load(urllib.request.urlopen(req, timeout=30))["data"]["requests"]["nodes"][0]["id"]

    def rpc(self, method, params):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        while True:
            m = json.loads(self.p.stdout.readline())
            if m.get("id") == self.n:
                return m

    def call(self, task, name, args):
        t = time.perf_counter()
        m = self.rpc("tools/call", {"name": name, "arguments": args})
        dt = time.perf_counter() - t
        r = m.get("result") or {}
        text = "".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")
        if "error" in m:
            text = json.dumps(m["error"])
        self.log.append({"task": task, "tool": name, "sec": dt, "bytes": len(text),
                         "err": bool(r.get("isError")) or "error" in m})
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def stats(self, task):
        rows = [l for l in self.log if l["task"] == task]
        return {"calls": len(rows), "wall": round(sum(r["sec"] for r in rows), 3),
                "bytes": sum(r["bytes"] for r in rows), "errors": sum(r["err"] for r in rows)}

    def close(self):
        self.p.stdin.close()
        self.p.terminate()
        self.p.wait()


def target(host, path_query):
    req = urllib.request.Request(TARGET + path_query, headers={"Host": host})
    return urllib.request.urlopen(req, timeout=30).read()


# ---------------------------------------------------------------- strategies
def page_all(m, task, httpql=None, extra=None):
    """Page every match with the largest page; returns rows."""
    rows, after = [], None
    while True:
        a = {"limit": 100, **(extra or {})}
        if httpql:
            a["httpql"] = httpql
        if after:
            a["after"] = after
        d = m.call(task, "caido_list_requests", a)
        if not isinstance(d, dict):
            return rows, d
        rows += d.get("requests", [])
        if not d.get("hasMore"):
            return rows, None
        after = d["nextCursor"]


def count(m, task, httpql, fork):
    if fork:
        d = m.call(task, "caido_list_requests", {"httpql": httpql, "limit": 1})
        return d["totalCount"], "limit:1 + totalCount"
    rows, _ = page_all(m, task, httpql)
    return len(rows), "page every match (limit 100) and count"


def newest(m, task, fork):
    if fork:
        d = m.call(task, "caido_list_requests", {"limit": 1, "order": "desc"})
        return d["requests"][0], "order:desc limit:1"
    # best known trick on the official surface: gallop/bisect on row.id
    def exists_gt(n):
        return bool(m.call(task, "caido_list_requests", {"httpql": f"row.id.gt:{n}", "limit": 1}).get("requests"))
    lo, hi = 0, 1000
    while exists_gt(hi):
        lo, hi = hi, hi * 2
    while hi - lo > 100:
        mid = (lo + hi) // 2
        if exists_gt(mid):
            lo = mid
        else:
            hi = mid
    d = m.call(task, "caido_list_requests", {"httpql": f"row.id.gt:{lo}", "limit": 100})
    return d["requests"][-1], "row.id bisection (undocumented trick), then last page"


def part1(m, fork, snippet_args=None, binary_args=None):
    res = {}

    def rec(task, ok, strategy, **extra):
        res[task] = {**m.stats(task), "correct": ok, "strategy": strategy, **extra}

    truth_id = m.newest_id()
    row, strat = newest(m, "T1", fork)
    rec("T1", row["id"] == truth_id, strat)
    if not fork:
        rows, _ = page_all(m, "T1_naive")
        rec("T1_naive", rows[-1]["id"] == truth_id, "page from the oldest row to the end")

    for task, q, exp in [("T2", 'resp.body.cont:"FLAG{needle-7f3a91}"', 1),
                         ("T4", 'req.header["X-Debug-Token"].cont:"dbg-41c2"', 1),
                         ("T6", 'resp.body.cont:"<svg/onload=omp"', 5),
                         ("T7", 'req.query.cont:"url=" or req.query.cont:"callback=" or req.query.cont:"redirect_uri="', 25)]:
        d = m.call(task, "caido_list_requests", {"httpql": q, "limit": 100})
        rec(task, len(d["requests"]) == exp, "one HTTPQL query")

    # T3: identify the two files AND show the leaked value
    q3 = 'resp.body.cont:"AKIAQ3EXAMPLEKEY7777"'
    if fork and snippet_args is not None:
        d = m.call("T3", "caido_list_requests", {"httpql": q3, "limit": 10, **snippet_args})
        rec("T3", "AKIAQ3EXAMPLEKEY7777" in json.dumps(d) and len(d["requests"]) == 2,
            "one query with a regex snippet")
    else:
        d = m.call("T3", "caido_list_requests", {"httpql": q3, "limit": 10})
        seen = 0
        for r in d["requests"]:
            g = m.call("T3", "caido_get_request", {"ids": [r["id"]], "include": ["responseBody"], "bodyLimit": 200000})
            seen += "AKIAQ3EXAMPLEKEY7777" in json.dumps(g)
        rec("T3", seen == 2, "find rows, then pull each ~160 KB body to read the key")

    for task, q, exp in [("T5", 'req.host.eq:"admin.localhost" and resp.code.eq:403', 554),
                         ("T11", 'req.method.eq:"POST" and req.host.eq:"api.localhost" and req.path.eq:"/api/v1/orders"', 598),
                         ("T12", 'resp.body.regex:"user[0-9]+@example.test"', 5211)]:
        n, strat = count(m, task, q, fork)
        rec(task, n == exp, strat, value=n)
    n1, s = count(m, "T8", 'resp.code.eq:500 and resp.body.cont:"Traceback"', fork)
    n2, _ = count(m, "T8", 'resp.code.eq:500 and resp.body.cont:"NullPointerException"', fork)
    rec("T8", (n1, n2) == (42, 52), s + " (x2)")

    d = m.call("T9", "caido_get_sitemap", {})
    rec("T9", len(d.get("entries", [])) == 6, "sitemap roots")

    d = m.call("T10", "caido_list_requests", {"httpql": 'req.path.eq:"/big/report.json"', "limit": 1})
    r = d["requests"][0]
    g = m.call("T10", "caido_get_request", {"ids": [r["id"]], "include": ["responseBody"], "bodyOffset": 600000, "bodyLimit": 2000})
    truth = target("static.localhost", urlsplit(r["url"]).path + "?" + urlsplit(r["url"]).query)
    rec("T10", (g.get("response") or {}).get("body") == truth[600000:602000].decode(), "find row, read a byte window")

    d = m.call("T13", "caido_list_requests", {"httpql": 'req.path.cont:"/api/v1/users/" and resp.code.eq:200', "limit": 1})
    e = m.call("T13", "caido_edit_request", {"requestId": d["requests"][0]["id"], "removeHeaders": ["Authorization"], "bodyLimit": 200})
    rec("T13", isinstance(e, dict) and e.get("statusCode") == 401, "edit_request removeHeaders")

    d = m.call("T14", "caido_list_requests", {"httpql": 'req.ext.eq:".png"', "limit": 1})
    r = d["requests"][0]
    g = m.call("T14", "caido_get_request", {"ids": [r["id"]], "include": ["responseBody"], "bodyLimit": 9000, **(binary_args or {})})
    truth = target("static.localhost", urlsplit(r["url"]).path)
    resp = (g or {}).get("response", {}) if isinstance(g, dict) else {}
    body = resp.get("body", "")
    if "bodyBase64" in resp:
        got = base64.b64decode(resp["bodyBase64"])
    elif resp.get("bodyEncoding") == "base64":
        got = base64.b64decode(body)
    else:
        got = body.encode("utf-8", "surrogatepass")
    rec("T14", hashlib.sha256(got).hexdigest() == hashlib.sha256(truth).hexdigest(),
        "get_request body" + (" (base64)" if binary_args else " (text)"))
    return res


def part2(m, fork, k):
    res = {}
    truth_id = m.newest_id()
    row, strat = newest(m, "S1", fork)
    res["S1"] = {**m.stats("S1"), "correct": row["id"] == truth_id, "strategy": strat}
    if not fork:
        rows, _ = page_all(m, "S1_naive")
        res["S1_naive"] = {**m.stats("S1_naive"), "correct": rows[-1]["id"] == truth_id, "strategy": "page to the end"}
    n, strat = count(m, "S2", 'req.host.eq:"admin.localhost" and resp.code.eq:403', fork)
    res["S2"] = {**m.stats("S2"), "correct": n == 554 * k, "strategy": strat, "value": n}
    d = m.call("S3", "caido_list_requests", {"httpql": 'resp.body.cont:"FLAG{needle-7f3a91}"', "limit": 100})
    res["S3"] = {**m.stats("S3"), "correct": len(d["requests"]) == k, "strategy": "one HTTPQL query"}
    d = m.call("S4", "caido_get_sitemap", {})
    res["S4"] = {**m.stats("S4"), "correct": len(d.get("entries", [])) == 6, "strategy": "sitemap roots"}
    return res


def part3(m):
    tl = m.rpc("tools/list", {})["result"]["tools"]
    raw = json.dumps(tl)
    return {"tools": len(tl), "bytes": len(raw), "approx_tokens": len(raw) // 4}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--part", type=int, required=True)
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--fork", action="store_true")
    ap.add_argument("--snippet-args", help="JSON merged into list_requests for T3 (fork only)")
    ap.add_argument("--binary-args", help="JSON merged into get_request for T14 (fork only)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    m = MCP(os.path.expanduser(a.binary), a.url, open(a.token_file).read().strip())
    try:
        if a.part == 1:
            data = part1(m, a.fork, json.loads(a.snippet_args) if a.snippet_args else None,
                         json.loads(a.binary_args) if a.binary_args else None)
        elif a.part == 2:
            data = part2(m, a.fork, a.k)
        else:
            data = part3(m)
    finally:
        m.close()
    out = json.load(open(a.out)) if os.path.exists(a.out) else {}
    key = f"part{a.part}" + (f"_k{a.k}" if a.part == 2 else "")
    out.setdefault(a.label, {})[key] = data
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps({a.label: {key: data}}, indent=1)[:4000])


if __name__ == "__main__":
    main()
