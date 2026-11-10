# AI SRE Agent

An alert fires, a team of agents investigates it like an on-call engineer, a human approves the fix, and a postmortem is written and remembered for next time.

```
Alert -> FastAPI webhook -> Redis Stream -> Worker -> LangGraph
   triage (RAG over runbooks + past incidents)
   -> 4 investigators in parallel (logs, metrics, deploys, database) via MCP servers
   -> hypothesis <-> critic loop
   -> propose fix -> HUMAN APPROVAL (graph pauses, state saved in Postgres)
   -> execute (docker MCP, needs approval token) -> verify
   -> postmortem -> stored + embedded (pgvector)
Dashboard: live timeline over SSE, approve / reject buttons.
```

## Requirements

- Docker Desktop (with Docker Compose)
- Python 3.12 only if you want to run the tests or the evaluation outside Docker

## Run it

1. Stop the old M1 containers if they are still running (different folder, different ports, but no need to keep them):
   ```bash
   cd ~/ai-sre-agent && docker compose down
   ```
2. In this folder:
   ```bash
   cp .env.example .env
   docker compose up --build
   ```
   The first build takes a few minutes. Wait until you see `worker ready` in the logs.
3. Open http://localhost:8000
4. Pick a scenario, press **Break it**, and watch the timeline fill up. When the status becomes "awaiting approval", read the proposal and press **Approve**. The agent runs the action, verifies recovery and writes the postmortem.
5. Try all seven scenarios. Two of them (traffic_spike, false_alarm) correctly end with "no action needed". In dependency_down the right answer is to restart `orders`, not `payments`.

Ports used: 8000 (app), 5434 (Postgres), 6380 (Redis). Change them in `docker-compose.yml` if they clash.

## Optional: use a real LLM

Without a key the agents use a built-in rule engine, so everything works offline and results are deterministic. To let an LLM write the hypothesis, review it as the critic, and write the postmortem, put your key in `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

then `docker compose up -d --force-recreate api worker`. If a call fails the system falls back to the rule engine and says so in the timeline. The LLM is always given the rule engine's answer as a hint, and the critic only accepts when both agree.

## Run the tests

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
```

The tests need no database. `test_offline_pipeline.py` replays all seven scenarios through the real investigator code with a fake tool layer and checks the diagnosis, the critic, and the proposed action against the answer key.

## Evaluate the whole system

With `docker compose up` running:

```bash
python -m eval.run_eval --runs 3
```

It breaks each scenario, approves the proposal, waits for the end, compares the diagnosis with the answer key, and prints accuracy and time. Results are saved to `eval/results.json`. Put the numbers in your resume or README.

## Send a real signed alert by hand

```bash
python -m victim.chaos run bad_config --send
```

Loads the scenario data into Postgres, then posts the alert to the webhook with an HMAC signature, exactly like a monitoring tool would. Posting the same alert twice while the first is open attaches to the same incident instead of creating a new one.

## How the pieces map to the code

| Piece | Where |
|---|---|
| Webhook, signature check, dedupe | `app/api/webhooks.py`, `app/core/tokens.py`, `app/services/incidents.py` |
| Queue and worker | `app/queue/stream.py`, `app/worker.py` |
| LangGraph workflow | `app/orchestrator/graph.py`, `nodes.py`, `state.py` |
| What each investigator concludes | `app/orchestrator/analysis.py` |
| Rule engine (classify, critic, fix, postmortem template) | `app/orchestrator/heuristics.py` |
| MCP servers (tools) | `mcp_servers/*.py` |
| SQL safety guard | `mcp_servers/sqlguard.py` |
| RAG (embeddings, pgvector search) | `app/rag/`, `runbooks/` |
| Fake world and scenarios | `victim/generate.py` |
| Dashboard | `dashboard/` |
| Evaluation | `eval/run_eval.py` |

## Safety design

- All tools are read-only except the docker server, which is a separate process.
- Docker tools refuse to act without an approval token. The token is an HMAC of incident id + action + target, created only when a human approves that exact action.
- `readonly_query` accepts a single SELECT, blocks writes and the answer-key table, and has a 3 second timeout.
- Only allowlisted services can be restarted or rolled back.
- Logs are shown to the LLM as data, and the prompts tell it never to follow instructions found inside them. The dashboard renders everything with `textContent`.
- Every tool call is stored in `tool_calls`, every decision in `approvals`, every step in `agent_events`.

## Known limits

- The "world" is simulated (Level 1): fixing an incident means the docker server writes healthy data. Swapping in real containers means changing only `mcp_servers/`.
- Tables are created with `create_all` at startup. Add Alembic when the schema starts changing.
- Redis Streams, not Kafka. One worker processes incidents one at a time.
- A rejected proposal escalates to a human instead of looping back to the hypothesis step.
- No login on the dashboard.
- Two identical alerts in the same millisecond could create two incidents. A unique partial index on open fingerprints would fix it.

## Troubleshooting

- `docker compose logs worker` and `docker compose logs api` show what is going on.
- "address already in use": change the host port in `docker-compose.yml`.
- Incident stuck on "open": the worker is not running or cannot reach Redis.
- Changed the SQL in `db/init`: run `docker compose down -v` so Postgres re-initialises.
- `redis-cli -p 6380 XLEN sre:dead` shows how many messages failed processing.
