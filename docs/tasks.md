# Tasks

All tasks run against the same history: the corpus from `corpus/gen_traffic.py` (seed 1337), 20,000 requests plus one final marker request, `GET http://api.localhost:18080/api/v1/health?final=1`, sent after every worker has finished. `python3 corpus/gen_traffic.py --expected` prints the ground truth (`corpus/expected.json`).

## Part 1: scripted tasks, 20,001 requests

Each task runs the best strategy the server's tools allow, using MCP tool calls only. If a server has no count, the strategy pages through every match. If it cannot sort, it uses the best workaround available (for example bisecting on row IDs), and the strategy is recorded next to the numbers.

| ID | Task | Ground truth |
|----|------|--------------|
| T1 | Find the most recent request | the `final=1` request |
| T2 | Find responses whose body contains `FLAG{needle-7f3a91}` | 1 (`/api/v1/users/7777`) |
| T3 | Find the AWS-style key `AKIAQ3EXAMPLEKEY7777`, about 80 KB into a 150 KB JavaScript file, and show it | 2 (`/assets/vendor.3c9e.js`) |
| T4 | Find the request carrying the header `X-Debug-Token: dbg-41c2` | 1 (`shop /product/1`) |
| T5 | Count `admin.localhost` responses with status 403 | 554 |
| T6 | Find responses reflecting `<svg/onload=omp` | 5 |
| T7 | Find requests with URL-carrying parameters (`url=`, `callback=`, `redirect_uri=`) | 25 |
| T8 | Count 500 responses containing `Traceback`, and those containing `NullPointerException` | 42 and 52 |
| T9 | List the hosts | 6 |
| T10 | Read bytes 600,000 to 602,000 of a 1.3 MB response (`/big/report.json`) | exact slice |
| T11 | Count `POST api.localhost /api/v1/orders` | 598 |
| T12 | Count responses matching `user\d+@example\.test` | 5,211 |
| T13 | Replay a captured request with one header changed and read the status | works or not |
| T14 | Read a binary response (`.png`) byte for byte | sha256 matches the target |

## Part 2: scale sweep

The corpus is loaded five times into the same project (20,001 to 100,005 requests). After each load, with k the number of loads:

| ID | Task | Ground truth |
|----|------|--------------|
| S1 | Find the most recent request | the latest `final=1` request |
| S2 | Count `admin.localhost` 403s | 554 × k |
| S3 | Find responses containing `FLAG{needle-7f3a91}` | k |
| S4 | List the hosts | 6 |

## Part 4: agent tasks

Plain-language prompts from `agents/agent_tasks.json`. An answer passes when every check regex matches it.

| ID | Prompt (shortened) | Checks |
|----|--------------------|--------|
| A1 | What is the most recent request? Reply with its method and full URL. | `GET`, `health?final=1` |
| A2 | How many requests to admin.localhost received a 403? | `554` |
| A3 | A JavaScript file leaks an AWS access key. Reply with the key and the file URL. | the key, `vendor.3c9e.js` |
| A4 | Find requests whose parameters carry a URL; reply with each endpoint and parameter. | `/fetch`, `/api/v1/webhooks`, `/oauth/authorize`, `redirect_uri`, `callback` |
| A6 | List every host with its exact number of requests. | all six counts |
| A5 | Resend the captured `GET /api/v1/users/7777` without its Authorization header; reply with the status. | `401` |

A5 writes to the history, so it always runs last.
