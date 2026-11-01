import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp import MCP
name = sys.argv[1]; args = json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")
to = int(sys.argv[3]) if len(sys.argv) > 3 else 300
c = MCP(); c.init(); t0 = time.time()
r = c.call(name, args, timeout=to); dt = time.time() - t0
res = r.get("result", {}); txt = "".join(x.get("text", "") for x in res.get("content", []))
print(json.dumps({"tool": name, "args": args, "wall": round(dt, 3), "bytes": len(txt.encode()),
                  "isError": res.get("isError"), "text": txt}))
