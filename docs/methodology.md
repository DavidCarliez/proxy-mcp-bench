# Methodology

## Target and corpus

`target/target_server.py` is a deterministic lab application on `[::]:18080`. The `Host` header selects one of six virtual hosts: `shop`, `api`, `admin`, `static`, `auth` and `graphql`, all under `.localhost`. Responses are a pure function of method, host, path, query and body, so every proxy records the same traffic. They include HTML pages, JSON APIs, 150 KB JavaScript bundles, PNG images, three 1.3 MB JSON documents, 401 and 403 responses, and 500 responses with Python tracebacks or Java stack traces.

`corpus/gen_traffic.py` sends 20,000 requests from a fixed seed through a proxy, with 32 threads, then sends one final marker request on its own. Values planted at fixed positions make every answer checkable: a flag in one user record, an AWS-style key in the middle of a 150 KB bundle, five reflected `<svg/onload=...>` payloads, one unique request header, 25 URL-carrying parameters and three 1.3 MB responses. `--expected` prints the ground truth without sending anything.

The hostnames must resolve to loopback. systemd-resolved does this for `*.localhost`; otherwise add the six names to `/etc/hosts`.

## Isolation

- Every server is measured on a fresh project that holds only the corpus. Nothing else is sent before the corpus.
- Caido: a separate `caido-cli` instance with its own `--data-path` and an empty project.
- Burp: a copied home directory under a virtual X display, with exactly one MCP extension loaded at a time. Its identity is confirmed through the MCP `serverInfo` before each part.

## Part 1: scripted tasks

A small MCP client runs the 14 tasks in `docs/tasks.md` against one server: `caido/caido_suite.py` over stdio for Caido, and the scripts in `burp/` over SSE for Burp. For each task it records:

- the number of tool calls;
- the size of the tool output returned to the model, which is what the model reads (divide by about four for tokens);
- the wall time of the calls;
- whether the answer matches the ground truth;
- the strategy used.

`caido_suite.py` measures output size in characters and the Burp scripts in UTF-8 bytes. The two only differ for non-ASCII output, such as a corrupted binary body.

## Part 2: scale sweep

The same corpus is loaded four more times into the project used for part 1, up to 100,005 requests. After each load the client runs S1 to S4 and the proxy's resident memory is read from `/proc/<pid>/status`. A strategy that would need more than 2,000 calls, or a single response above 50 MB, would be recorded as infeasible; no strategy reached either limit.

## Part 3: tool definitions

The size of the `tools` array from `tools/list`, serialised as JSON, and the number of tools. Tool definitions are sent to the model on every turn, so this is a fixed cost per turn. Tokens are estimated as bytes divided by four.

`caido_suite.py --part 3` measures it for Caido. For Burp, `burp/mcp.py` gives the same number when run from the `burp/` directory:

```python
from mcp import MCP
import json
c = MCP(); c.init()
print(len(json.dumps(c.tools()["result"]["tools"])))
```

## Part 4: real agents

`agents/agent_run.py` gives each task in `agents/agent_tasks.json` to a fresh headless Claude Code session (`claude -p`) whose only proxy access is the MCP server under test. `--strict-mcp-config` loads no other MCP server. `--restricted` removes the shell and web tools and confines the file tools to an empty temporary working directory; the agent can still use them on Claude Code's own saved tool output, and one Burp run did. `--allowedTools mcp__<server>` lets the MCP tools run without prompts.

- Model: Sonnet. Budget cap: $3 per run. Timeout: 900 s.
- The same system prompt for every run: answer with the proxy tools only, and say so rather than guess when an exact answer isn't possible.
- Six tasks, three runs each, so 18 runs per server. A5 runs last because it writes to the history.
- Recorded per run:
  - wall time, turns and tool calls;
  - bytes of tool output fed back to the model;
  - tokens: input, cache creation, cache reads and output;
  - the API-equivalent cost Claude Code reports;
  - the answer;
  - in later runs, the tools used (`tools_used`) and a short per-call trace (`trace`: tool name and the first 300 characters of input and result). `round1.jsonl` has neither; `burp-fork-enhanced2.jsonl` has `tools_used` only.
- An answer is correct when every check regex for the task matches.

### Burp approvals

Both Burp extensions ask a human to approve the first history read in a project and every new target host. Those dialogs block a tool call until someone clicks, with no timeout. Before the agent runs, `burp/warm_approvals.py <host>` was run once per host and the dialogs were answered with "Always Allow", so no run waited on a dialog. Requests sent by the extension do not enter Burp's proxy history, so this changes no counts.

### The replay task on Caido

A5 resends a captured request, which adds a Replay row to the history. Rows left by earlier runs change what "newest" means, so the published Caido A5 runs all start from one snapshot of the Caido data directory: the 20k corpus plus four earlier Replay entries of the target request, sent without the `Authorization` header. Each run copies the snapshot, starts `caido-cli` on the copy, runs the task and stops the instance. Both Caido servers ran from the same snapshot.

### Which runs are in the figures

`results/agents/final.jsonl` is built by `charts/make_figure_data.py`:

| Server | Source |
|---|---|
| burp-official | `round1.jsonl` |
| burp-fork | `burp-fork-enhanced2.jsonl` (1.3.0-enhanced.2) |
| caido-official | `round1.jsonl` for A1-A4 and A6, `replay-snapshot.jsonl` for A5 |
| caido-fork | `caido-fork-final.jsonl` for A1-A4 and A6, `replay-snapshot.jsonl` for A5 |

`round1.jsonl` also holds the first-round runs of both forks, before the last changes. `replay-traced.jsonl` holds the traced A5 runs that showed why the Caido fork needed more calls on that task before the `source` field was added.

Totals in the figures are the sum, over the six tasks, of each task's median over three runs.

## Limits

- Everything runs on loopback, so there is no network latency.
- The corpus is synthetic.
- One model and three runs per task: enough to show variance, not a statistical study.
- The Burp scripts in `burp/` are the ones used for the published runs. Since then they have only been changed to use paths inside this repository; they have not been re-run in this layout.
