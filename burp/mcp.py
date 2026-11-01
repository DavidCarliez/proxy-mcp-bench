import json, threading, queue, urllib.request, time

class MCP:
    def __init__(self, url="http://127.0.0.1:9876"):
        self.base = url; self.q = queue.Queue(); self.msgurl = None
        self.ready = threading.Event(); self.ids = 0
        threading.Thread(target=self._reader, daemon=True).start()
        self.ready.wait(20)
    def _reader(self):
        req = urllib.request.Request(self.base + "/", headers={"Accept": "text/event-stream"})
        with urllib.request.urlopen(req, timeout=3600) as r:
            ev = None; data = []
            for raw in r:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line == "":
                    if ev == "endpoint" and data:
                        d = "".join(data)
                        self.msgurl = self.base + "/" + d if d.startswith("?") else self.base + d
                        self.ready.set()
                    elif ev == "message" and data:
                        self.q.put("".join(data))
                    ev, data = None, []
                elif line.startswith("event:"): ev = line[6:].strip()
                elif line.startswith("data:"): data.append(line[5:].lstrip())
    def _post(self, payload):
        body = json.dumps(payload).encode()
        req = urllib.request.Request(self.msgurl, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r: return r.status
    def request(self, method, params=None, timeout=300):
        self.ids += 1; i = self.ids
        self._post({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}})
        end = time.time() + timeout
        while time.time() < end:
            try: msg = self.q.get(timeout=max(0.1, end - time.time()))
            except queue.Empty: break
            m = json.loads(msg)
            if m.get("id") == i: return m
        raise TimeoutError(method)
    def notify(self, method, params=None):
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})
    def init(self):
        r = self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                        "clientInfo": {"name": "proxy-mcp-bench", "version": "1"}})
        self.notify("notifications/initialized"); return r
    def tools(self): return self.request("tools/list")
    def call(self, name, args=None, timeout=300):
        return self.request("tools/call", {"name": name, "arguments": args or {}}, timeout=timeout)
