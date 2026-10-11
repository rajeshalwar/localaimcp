# Design Doc — "Don't Mess With My Data: Local AI + MCP on Linux"

Status: **draft v2 — decisions resolved, ready for review**
Owner: Rajesh
Last updated: 2026-09-12
Companion artifact for `proposal.txt` (conference talk + demo repo)

---

## 1. What we are actually building

Two deliverables, kept distinct:

1. **`localaimcp` — a public demo repo.** Reproducible on Mac, Windows or Linux: `git clone` → `make setup` (builds, pulls the model once) → `make demo`.
2. **A ≤40 minute talk** with a live demo. The repo serves the narrative; where they conflict, the narrative wins.

**The thesis, stated precisely enough to defend on stage:** *the reasoning happens on hardware you own, and the only bytes that leave your network are ones you can enumerate and justify.* We are not claiming "zero network." We claim **auditable, minimal, non-identifying egress**, and we prove it live (§7).

### Success criteria

| # | Criterion | Verified by |
|---|---|---|
| S1 | `make setup && make demo` → working agent on a clean box, ≤15 min **excluding the model pull** | Fresh-VM rehearsal ×2, timed |
| S2 | NL question → correct grounded answer, no hand-holding | 10 rehearsal runs, ≥9 clean |
| S3 | Demo works with Wi-Fi **off** | Replay mode (§6.4) |
| S4 | Every outbound request logged and printable in one command | `make egress-report` |
| S5 | Whole stack runs as systemd units, **host-OS independent** | `podman exec appliance systemctl status` |
| S6 | Attendee adds their own MCP tool by editing one file | `tools/` package, one decorator |
| S7 | **Median demo turn ≤45s, p90 ≤90s on the demo box** | Benchmark harness, phase 6 |

S7 is new and is the criterion most likely to fail. See §3.3 and §11.

### Explicit non-goals

- Not a production product. No auth, no multi-tenancy.
- Not fine-tuning or RAG. Off-the-shelf Ollama models only.
- Not roof geometry or shading (no LiDAR, no Google Solar API — cloud dependency *and* a different talk).
- Not Kubernetes. Podman + compose + systemd only.
- No web UI. CLI only (decided).

---

## 2. Decision log

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | Language | **Python 3** (3.14 in the Fedora 44 images) | Official MCP SDK / FastMCP; shortest on-stage code; most reproducible |
| D2 | Agent host | **Custom CLI, ~180 LOC** | Every tool call visible and printable; teaches the loop instead of hiding it |
| D3 | Geocoding | **US Census Geocoder** | Free, no API key, no signup. Privacy cost handled honestly in §7 |
| D4 | Containers | **Podman + `podman compose`**, rootless | No Portainer. Daemonless rootless is itself part of the "on your terms" story |
| D5 | UI | **CLI only** | The trace output is more compelling than a chat box; reclaims build time |
| D6 | Savings math | **Flat $/kWh**, ERCOT TOU as a slide | Defensible; TOU invites accuracy questions we can't win from stage |
| D7 | Talk length | **≤40 min** | Drives the timing budget in §12 |
| D8 | Compute | **CPU-only, everything in containers** | Host may be Mac/PC/Linux. Forces §3.2 and makes S7 the top risk |
| D9 | Model | **`qwen2.5:7b-instruct`** — reversed on correctness, not speed | 3B is 2.6× faster but **cannot do the granular chain at all**: it fabricates coordinates or skips tools entirely. See §3.3.3 |
| D10 | Transport | **Streamable HTTP** on `:8000/mcp` | stdio can't cross container boundaries; see §3.1 |
| D11 | systemd | **Inside the appliance container**, Quadlet as a Linux-only bonus | Host-agnostic; see §9 |
| D12 | Repo visibility | **Public before the talk** | README and hygiene move to phase 2, not phase 6 (§10) |

---

## 3. Architecture

Three containers, **two networks**. The network split is the load-bearing design element — it turns the privacy claim from a code convention into a kernel-enforced guarantee.

```
┌─────────────────── host (Mac / Windows / Linux — podman machine or native) ────────────────────┐
│                                                                                                │
│  netint  (internal: true — NO gateway, cannot route off-box)                                   │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐      │
│  │                                                                                       │      │
│  │   ┌────────────────────┐              ┌──────────────────────────────────────────┐    │      │
│  │   │  ollama            │◄──HTTP───────┤  agent  (podman compose run --rm)        │    │      │
│  │   │  qwen2.5:7b q4     │   :11434     │  ───────────────────────────────────     │    │      │
│  │   │  CPU inference     │              │  REPL · tool loop · trace printer        │    │      │
│  │   │  volume: models    │              └─────────────────┬────────────────────────┘    │      │
│  │   │  NO ROUTE OUT ✕    │                                │ MCP Streamable HTTP :8000   │      │
│  │   └────────────────────┘                                ▼                             │      │
│  │                              ┌──────────────────────────────────────────────────┐     │      │
│  │                              │  appliance   (systemd PID 1, --systemd=always)   │     │      │
│  │                              │  ─────────────────────────────────────────────   │     │      │
│  │                              │   postgresql.service                             │     │      │
│  │                              │   migrate.service     (oneshot, Before=mcp)      │     │      │
│  │                              │   mcp-solar.service   (Requires/After postgres)  │     │      │
│  │                              │   warm-cache.timer                               │     │      │
│  └──────────────────────────────┤                                                  ├─────┘      │
│                                 └─────────────────────┬────────────────────────────┘            │
│  netext (bridge)  ──── ONLY the appliance is attached ┘                                         │
└─────────────────────────────────────────────────────┼──────────────────────────────────────────┘
                                                      │  all egress via net.py, logged
                              ┌───────────────────────┴─────────────────────┐
                              ▼                                             ▼
                   geocoding.geo.census.gov                      developer.nlr.gov 
                   (address → lat/lon)                           (rounded lat/lon → PVWatts)
```

### 3.1 Transport: Streamable HTTP, not stdio

Most MCP tutorials use stdio, where the client spawns the server as a child process. **That cannot cross a container boundary** — it needs a shared process tree.

| Option | Verdict |
|---|---|
| Agent + server in one container, stdio | Rejected. Collapses "expose tools to *any* MCP client," which is the whole point of MCP |
| Separate containers, **Streamable HTTP** | **Chosen.** The server is a real network service; an attendee can point Claude Desktop, Cline, or their own client at it |
| stdio, no containers | Rejected. Fails D8 |

We ship a `--stdio` flag on the same server (three lines) so one slide can say *"same code, two transports — here's the Claude Desktop config."* It also stays tested as the fallback if HTTP misbehaves at rehearsal.

### 3.2 Ollama: containerized, CPU-only, and deliberately unrouted

D8 removes the "run Ollama on the host" escape hatch. CPU-only actually makes this *easier* — no GPU passthrough, no CDI, no nvidia-container-toolkit. The stack is identical on every host.

**The model-pull problem.** `ollama` sits on an internal network with no route out, so it cannot download a model. Two ways to solve it:

| Approach | Verdict |
|---|---|
| Bake the model into the image at build time | Rejected. ~4.7GB image, slow rebuilds, and it hides the step |
| **One-shot `model-pull` service** (compose profile `setup`) attached to `netext`, writing into the shared `ollama-models` volume; the runtime `ollama` service mounts the same volume on `netint` only | **Chosen.** Small images, and the separation is visible and explainable |

`make pull-model` runs it once. This is a genuinely good stage beat: *"the model is downloaded once, by a container that is then thrown away. The container that runs it has no route to the internet — and I'll prove that in a minute."*

### 3.3 Model and the latency problem (the top risk)

`qwen2.5:7b-instruct` q4_K_M, ~4.7GB. On CPU — and on a Mac, inside a Linux VM with no Metal — expect roughly **5–12 tok/s** depending on core count. Every tool round trip costs a prefill plus a generation, so a naive 4-step chain can run into minutes. Against a 10-minute demo budget (§12) that is the single most likely way this talk fails.

Mitigations, in order of impact:

1. **`OLLAMA_KEEP_ALIVE=-1`** — keep the model resident. A cold reload mid-demo is ~30s of dead air, and it's the most embarrassing possible failure.
2. **Prefix caching.** Ollama reuses the KV cache for a stable prompt prefix. Keep the system prompt and tool schemas byte-identical across turns so only new tokens are prefilled. This is worth a slide — it's the difference between a 4-step chain being usable or not.
3. **`num_predict` cap (~350)** on the final narration. Prevents the model rambling for 90 seconds. Apply it *only* to the narration turn — and rehearse it, because a cap that truncates the closing paragraph mid-sentence on stage is worse than a slow one.
4. **Terse tool schemas.** Every token of JSON schema is prefill on the first turn. Short descriptions, no verbose examples.
5. **`num_ctx: 8192`.** Ollama defaults to 4096; our schemas plus a 12-month PVWatts result will silently truncate past it. Costs memory, non-negotiable.
6. **Non-streaming during the tool loop**, stream only the final answer. Simpler, and avoids partial tool-call parsing.
7. **The composite tool** (§4.1) collapses four round trips into one — the strongest latency lever we have.
8. **`podman machine` sizing.** Default is often 2 CPU / 2GB, which makes a 7B model unusable or OOM. On Windows/WSL2, the `.wslconfig` equivalent.

**Sizing as actually provisioned (verified 2026-09-13):** the dev Mac is 10-core / 16GB with ~31GB free disk. The VM is `--cpus 8 --memory 8192 --disk-size 40`. Note what that leaves: **8GB for macOS**, and the model alone wants ~4.7GB plus ~0.5GB KV cache at 8k context. Running 7B *and* a browser *and* slides on a 16GB machine is tight — this materially raises the odds that the §3.3 fallback to `qwen2.5:3b-instruct` becomes the real answer, and the phase-6 benchmark should be treated as likely-to-bite rather than a formality. **Disk is the other constraint:** 31GB free against a 4.7GB model, a ~1GB VM image and several GB of container images.

### 3.3.1 Measured, not estimated (2026-09-13)

Dev Mac: 10-core / 16 GB Apple Silicon, Podman VM at 8 CPU / 8 GB, CPU-only.
`qwen2.5:7b-instruct` q4, model resident (`keep_alive` verified as `Forever`).

| Metric | Measured |
|---|---|
| Cold model load | 6.2 s |
| Warm-up turn | 7.9 s |
| Prefill | ~76 tok/s |
| Generation | ~20 tok/s |
| **Turn latency** | **44 s, 63 s, 66 s, 97 s** — and one 1054 s runaway |

The 1054 s outlier was an uncapped tool-selection turn: the model rambled
instead of emitting a tool call, at 20 tok/s, for seventeen minutes. Fixed by
capping tool turns at 700 tokens (§14). But even excluding it:

> **S7 FAILS on 7B.** Median ≈ 66 s against a 45 s target; p90 ≈ 97 s against 90 s.

Generation speed is better than the 5–12 tok/s originally estimated; the
problem is that *every* turn re-prefills ~1.5 k tokens of system prompt plus
tool schemas, and a turn is prefill + generation.

### 3.3.2 7B vs 3B, measured (4 runs each, model resident, nothing else loaded)

| | `qwen2.5:7b-instruct` | `qwen2.5:3b-instruct` |
|---|---|---|
| min | 58.9 s | **35.1 s** |
| **median** | 67.3 s | **49.5 s** |
| p90 | 67.8 s | **51.9 s** |
| max | 74.0 s | 56.4 s |
| tool calls/turn | 1 | 2 |
| resident size | 5.5 GB | 2.7 GB |
| S7 median ≤ 45 s | **FAIL** | **FAIL** |
| S7 p90 ≤ 90 s | PASS | PASS |

3B is ~26% faster and half the memory. It is also *less* efficient at tool
choice — it took two calls where 7B took one, which partly eats the speed win.

**Neither model meets a 45 s median on this hardware.** That is a real result
and it forces a choice:

1. **Relax S7 to ≤60 s median and design around it.** Defensible: the trace
   prints tool calls within a couple of seconds, so the audience sees activity
   almost immediately — the dead time is the final generation, which is exactly
   when you should be talking over it. Rehearse the patter.
2. **Present from a machine with more cores.** This is CPU-bound; more cores is
   close to linear. A 16-core Linux box would likely land under 30 s.
3. **Pre-record the demo** and narrate it live. Safest, least impressive.

### 3.3.3 Correctness beats speed — the result that reversed D9

Latency was the wrong thing to optimise first. The *same question*, across both
models and both tool profiles:

| | `qwen2.5:3b-instruct` | `qwen2.5:7b-instruct` |
|---|---|---|
| **composite** | ✅ correct, **16.7 s** | ✅ correct, 43.8 s |
| **granular** | ❌ **fabricates coordinates**, or answers with hand-rolled physics and zero tool calls | ✅ correct chain, 33 s |

The 3B failures would be fatal on stage:

- `TOOL_PROFILE=all`: skipped geocoding, **invented** `lat=30.262638,
  lon=-97.729672`, did the savings arithmetic itself, called $0.13/kWh "the
  federal tax credit rate", and described 11,976 kWh/yr as "about 88 kWh per
  month" (it is 998).
- `TOOL_PROFILE=granular`: **zero tool calls**, invented an irradiance figure,
  produced 31.5 kWh/year — off by ~330×.

7B needed help too, and got it from three changes (§14): a hardened numbered
system prompt (coordinates are now copied digit-for-digit), removing array
geometry from `assess_property`, and validation on `estimate_savings` that turns
a guessed input into an error-with-hint rather than a plausible lie.

**Decision: `qwen2.5:7b-instruct`.** The talk needs the granular chain to teach
MCP and 3B cannot do it. 33–44 s/turn, every number tool-computed. Relax S7 to
≤60 s median and rehearse talking over the generation — the trace prints tool
calls within a second or two, so the audience sees activity immediately.

**If you want 3B's 16.7 s**, stay in `TOOL_PROFILE=composite` for the whole demo
and show the granular chain as a code walkthrough rather than live.

**Residual, worth a slide:** 7B still passes *plausible* invented assumptions
($0.12/kWh, $25,000, 26% ITC). They survive validation precisely because they
are plausible. Every number is still tool-computed and the tool reports its own
assumptions — which is why `estimate_savings` returns an `assumptions` string.
Honest framing: the model picks inputs, the tools own the arithmetic.

---

## 4. The MCP server

`mcp-solar`, built on `FastMCP`. One module per tool under `src/mcp_solar/tools/`, registered by a decorator — that's the S6 story. For "one file" to be literally true, `tools/__init__.py` must auto-import every module in the package at startup; otherwise adding a tool is two edits and the claim is false on stage.

### 4.1 Tools

| Tool | Signature | Egress? |
|---|---|---|
| `geocode_address` | `(address) → {lat, lon, matched_address, county, state, match_count}` | Census (cached) |
| `estimate_solar_production` | `(lat, lon, system_capacity_kw=7.0, tilt=None, azimuth=180, array_type=1, losses=14) → {ac_annual_kwh, ac_monthly[12], capacity_factor, solrad_annual}` | NREL (cached) |
| `estimate_savings` | `(annual_kwh, rate_per_kwh=0.15, system_cost=None, capacity_kw=None, itc_rate=0.0) → {annual_savings, net_cost, simple_payback_years, twenty_year_savings}` | **None** |
| `save_assessment` | `(address, lat, lon, inputs, results, summary) → {id}` | None |
| `list_assessments` | `(limit=10, address_like=None) → [rows]` | None |
| `assess_property` | composite: geocode → production → savings → save | Census + NREL |

`tilt=None` defaults to `abs(lat)` — the standard rule of thumb, and a nice detail to mention.

`estimate_savings` is deliberately separated so the model can't fudge arithmetic, and so we have one obviously-offline tool to point at.

> **`assess_property` is now the primary path, not just insurance.** Under D8/D9 it's both the reliability mitigation (a 7B model chaining four tools live is a coin flip) *and* the latency mitigation (§3.3). Demo plan: show the granular chain once — that's the interesting part — then use the composite for everything after. The honest framing is content, not apology: *"here's where small local models get shaky, here's the standard mitigation, and notice it also made the demo 3× faster."*

**How we actually get the granular chain to happen.** If `assess_property` is exposed, a 7B model will pick it essentially every time — it is the obviously-cheaper option — so "show the granular chain once, then the composite" does not happen by itself. We need a switch: `TOOL_PROFILE=granular|composite|all` on the MCP server, controlling which tools are advertised in `list_tools`. The demo opens in `granular`, then restarts the agent in `composite` for the rest. Two consequences to design for: the restart must be fast and scripted (`TOOL_PROFILE=composite make up`), and changing the advertised tool set changes the prompt prefix, which **invalidates the KV cache** (§3.3 item 2) — so budget one cold prefill at the switch point rather than being surprised by it live.

### 4.2 Beyond tools

Almost every MCP talk covers only tools. ~30 LOC of cheap differentiation:

- **Resource** `solar://assessments/recent` — last 10 assessments as JSON, pullable without a tool call.
- **Prompt** `solar_assessment(address)` — a server-provided prompt template, making the point that *the server can ship the prompt engineering*, not just the functions.

### 4.3 Error contract

Tools never raise across the MCP boundary. Every tool returns its result shape or `{"error": str, "hint": str}`, where `hint` is written **for the model** ("no match found; ask the user for city and ZIP"). Under-discussed and worth a slide: **tool errors are prompts.**

---

## 5. The agent host

`src/agent/main.py`, ≤180 LOC, readable at 20pt on a projector.

```
fetch MCP tool list → convert to Ollama function schema → loop (max 6):
    POST /api/chat (messages, tools, num_ctx=8192, num_predict=350, stream=False)
    if tool_calls: for each → print trace → call MCP → append result → continue
    else: stream final answer → done
```

- **Trace output is the demo, not debug noise.** Each call prints `→ geocode_address(address="…")` / `← {lat: 30.26, lon: -97.74}` in dim text, with elapsed ms. Watching the agent *decide* is the payoff.
- Elapsed-ms per call doubles as the S7 benchmark instrument — no separate harness needed.
- `--json-trace` dumps the transcript for post-mortem after a bad run.
- `--replay` reads cache only and refuses egress (§6.4).
- `schema_bridge.py` maps MCP tool schemas → Ollama's OpenAI-style format. Small, and attendees will ask about it, so show it.

---

## 6. Data layer (PostgreSQL, inside the appliance)

Version **follows the base image** rather than being pinned — `ubi9-init` and Fedora ship different PostgreSQL streams, and fighting the base image for a specific major version buys us nothing here. Data lives on a named volume (`pgdata` → the image's data dir); without it, every `podman compose down` wipes the seeded cache and breaks S3.

### 6.1 Schema

```sql
CREATE TABLE assessments (
  id              BIGSERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  address_input   TEXT NOT NULL,
  matched_address TEXT,
  lat             NUMERIC(9,6) NOT NULL,
  lon             NUMERIC(9,6) NOT NULL,
  county          TEXT,
  inputs          JSONB NOT NULL,   -- capacity, tilt, azimuth, losses, rate, cost
  results         JSONB NOT NULL,   -- ac_annual, monthly[], savings, payback
  summary         TEXT              -- the model's plain-English paragraph
);

CREATE TABLE pvwatts_cache (
  cache_key  TEXT PRIMARY KEY,      -- sha256 of rounded params
  lat_r      NUMERIC(6,3), lon_r NUMERIC(6,3),
  params     JSONB NOT NULL,
  response   JSONB NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE geocode_cache (
  address_norm TEXT PRIMARY KEY,
  response     JSONB NOT NULL,
  fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE egress_log (
  id          BIGSERIAL PRIMARY KEY,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  host        TEXT NOT NULL,
  path        TEXT NOT NULL,
  params_sent JSONB NOT NULL,       -- exactly what we transmitted
  status      INT,
  cache_hit   BOOLEAN NOT NULL DEFAULT false,
  duration_ms INT
);
```

### 6.2 Migrations

Numbered `.sql` files in `db/migrations/`, applied by `migrate.service` (`Type=oneshot`, `Before=mcp-solar.service`). **No Alembic** — for a demo repo, reading the schema in one file beats migration tooling.

### 6.3 Caching

Keyed on lat/lon **rounded to 3 decimals** (~110 m) plus system params. NREL's solar resource grid is ~4 km, so rounding costs nothing in accuracy — and it means repeat demo runs make zero network calls.

### 6.4 Replay mode (Wi-Fi insurance)

`REPLAY_ONLY=true` makes `net.py` raise on cache miss and serve everything from `pvwatts_cache` + `geocode_cache`. Before the talk, pre-warm with the demo addresses plus ~15 plausible audience-shouted Texas locations (Austin, Houston, Dallas, San Antonio, El Paso, Lubbock, a couple of rural ZIPs). Conference Wi-Fi failure becomes a non-event.

**The seed must be committed fixtures, not just a warm volume.** A warm `pgdata` volume does not survive `git clone`, so S3 is only reproducible for an attendee if the cached responses ship in the repo: `fixtures/cache/*.json`, loaded by `make seed-cache`. That is also what makes the offline test suite work.

**Because those fixtures are public (D12), seed from public landmarks only — the Texas State Capitol, not your house.** A privacy talk whose repo commits the speaker's home address is the worst available own goal. Concretely: `fixtures/seed_addresses.txt` holds the landmark list, and a pre-commit hook fails the commit if any address in the fixtures is not on that list, and if `egress_log` dumps or `.env` are staged.

---

## 7. The privacy story (the talk's spine — a design requirement, not a slide)

D3 means the user's address **does** leave the machine. We must not soft-pedal it; a privacy audience will catch it, and raising it first is worth more than being caught.

**The honest claim:**

> The model never touches the network — it has no route to touch it. Two requests leave this box per uncached assessment: an address to a US government geocoder, and a *rounded* coordinate to a US government solar API. No API key identifies you to Census. No prompt, no conversation, no reasoning, and no stored result ever leaves. Here is the log.

| ID | Requirement |
|---|---|
| P1 | **Network-layer isolation.** `netint` is `internal: true`; `ollama` is attached to it only. The LLM container has no route off-box — enforced by the kernel, not by our code |
| P2 | **Single egress chokepoint.** Only `appliance` is dual-homed, and inside it all outbound HTTP goes through `net.py`. A unit test greps the tree to ensure nothing else imports `httpx` |
| P3 | **Coordinate truncation.** Round to 3 decimals *before* the NREL call. NREL never receives a precise location |
| P4 | **Full egress logging, session-scoped.** Every call writes `egress_log` with the exact params transmitted. `make egress-report` prints **only the current session** (rows since a marker written by `make demo`); `make egress-reset` truncates. Without this the table shows every row from every rehearsal and the "two requests" claim dies on stage |
| P5 | **Cache-first.** A cached assessment produces zero egress, logged `cache_hit=true` |
| P6 | **Documented path to zero.** README shows swapping in a local Nominatim with a Texas OSM extract to eliminate egress entirely. We don't ship it (~4GB, ~30 min import) but we show the one-file change |

### 7.1 Proving it on stage — and why the obvious proof is a trap

The naive proof is `podman exec ollama curl https://example.com` → fails. **It does not survive contact with S3.** If the conference Wi-Fi is down and we are in replay mode, that command fails from *every* container, including the appliance — so it proves nothing, and a sharp audience member will say so. The two headline mitigations in this doc were in direct conflict; this is the resolution.

> ### ✅ Network model — verified 2026-09-13
>
> | Test | Result |
> |---|---|
> | `--internal` network reports `Internal: true` | confirmed |
> | Isolated container → `https://example.com` | **fails** (no DNS, no route) |
> | Dual-homed container → `https://example.com` | **HTTP 200** |
> | Isolated → isolated, by container name, over the internal net | **HTTP 200** |
>
> The last row is the important one: `internal: true` removes the route *off-box* without affecting container-to-container traffic or DNS. Agent↔Ollama↔appliance work normally.

**Primary proof — structural, works offline, cannot be faked:**

```
make prove-isolation
  # podman network inspect netint --format '{{.Internal}}'      → true
  # podman inspect ollama  --format '{{.NetworkSettings.Networks}}'  → netint only
  # podman inspect agent   --format '{{.NetworkSettings.Networks}}'  → netint only
  # podman inspect appliance ...                                → netint + netext
```

This is a statement about the network topology, not about whether a packet happened to get through. It reads identically with the Wi-Fi off, which is exactly why it is the primary.

**Secondary proof — the contrast demo, only meaningful when the Wi-Fi is up:**

```
make prove-egress
  # from appliance : curl -sS --max-time 5 https://example.com  → 200 OK
  # from ollama    : same command                               → fails, no route
```

The *contrast* is the proof. One container can reach the internet, the one running the model cannot, and the only difference is which network it is attached to. Run this when the network is healthy and skip it when it is not — the runbook must mark it explicitly optional so we are never caught improvising.

**Implementation note:** do not assume `curl` exists in the `ollama` image. `make prove-egress` runs the probe from a throwaway `curl` container attached to `netint` (pre-pulled during `make setup`, since it cannot be pulled with the Wi-Fi down), not via `podman exec` into Ollama itself.

**An unexploited strength worth saying out loud:** the `agent` container is also on `netint` only. Neither the model *nor the thing orchestrating it* can reach the internet. The entire reasoning loop is sealed; only the tool server has a route out. That is a stronger claim than the talk currently makes.

---

## 8. Repo layout

```
localaimcp/
├── compose.yaml              # profiles: default, setup (model-pull)
├── .env.example              # NREL_API_KEY, MODEL_NAME, OLLAMA_KEEP_ALIVE, REPLAY_ONLY
├── Makefile                  # setup up down demo doctor pull-model seed-cache
│                             # prove-isolation prove-egress egress-report egress-reset bench logs
├── README.md                 # 15-min quickstart (S1) — written in phase 2, not phase 6
├── LICENSE                   # Apache-2.0
├── containers/
│   ├── appliance.Containerfile   # ubi9-init or fedora + systemd; postgres + app
│   └── agent.Containerfile
├── systemd/                  # units baked into the appliance image
│   ├── mcp-solar.service  migrate.service  warm-cache.service  warm-cache.timer
├── quadlet/                  # OPTIONAL host units, Linux only (§9.2)
├── fixtures/
│   ├── cache/*.json          # committed cache seed — makes S3 reproducible from a clone
│   └── seed_addresses.txt    # public landmarks only; enforced by pre-commit
├── db/migrations/00{1..4}_*.sql
├── src/
│   ├── mcp_solar/
│   │   ├── server.py         # FastMCP; --http | --stdio
│   │   ├── net.py            # THE egress chokepoint (P2)
│   │   ├── db.py  config.py  resources.py  prompts.py
│   │   └── tools/  geocode.py production.py savings.py storage.py composite.py
│   └── agent/
│       └── main.py  ollama.py  mcp_client.py  schema_bridge.py  trace.py
├── tests/                    # pytest + recorded fixtures; runs fully offline
└── talk/                     # slides, demo script, timed runbook, failure playbook
```

---

## 9. Running it

### 9.1 systemd *inside* the appliance container (primary, host-agnostic)

Podman supports systemd as PID 1 natively: `--systemd=always` mounts tmpfs on `/run`, `/run/lock`, `/var/log/journal`, sets `container=podman`, and delegates cgroups. With cgroups v2 + crun it works **rootless and unprivileged** — unlike Docker, which needs `--privileged` plus cgroup hacks and discourages the pattern entirely. That contrast is on-theme and worth 60 seconds on stage.

Because the systemd lives in the container's Linux userspace, it behaves identically on Mac, Windows and Linux. This is what satisfies D8 and S5, and it's why this replaced host-side Quadlet as the primary approach.

What systemd buys us that compose does poorly, all demoable in one `podman exec`:

- Real ordering: `migrate.service` (`Type=oneshot`) `Before=` `mcp-solar.service`, which `Requires=`/`After=` `postgresql.service`.
- `Restart=on-failure` with backoff — kill the MCP server live and watch it come back.
- `systemctl list-dependencies mcp-solar.service` — the whole stack in one picture.
- `warm-cache.timer` — a systemd timer, **`WantedBy` nothing by default / masked during the talk**. A timer that re-fetches PVWatts generates egress on a schedule; if it fires mid-talk it silently adds rows to `egress_log` and contradicts the claim we just made. It exists to demonstrate timers, and the runbook masks it before the demo.

Two caveats, both good audience material: unit output goes to journald rather than `podman logs` unless we set `StandardOutput=journal+console`; and purists will object to multi-process containers — the rebuttal is that this is a demo *appliance*, and the init-in-container pattern is legitimate enough that Red Hat ships `ubi9/ubi-init` for it.

**Compose cannot express `--systemd=always`** — there is no such key in the compose spec. We rely on Podman's default `--systemd=true`, which auto-enables systemd mode when the entrypoint is `/sbin/init`. The appliance image must therefore declare that entrypoint explicitly.

**Base image: Fedora 41, not `ubi9-init`.** UBI's repositories ship only the
PostgreSQL *client* (13.x), not `postgresql-server` — verified 2026-09-13 — so
an appliance supervising Postgres cannot be built on UBI. Fedora 41 has
postgresql-server 16.11, Python 3.13 and systemd 256.

> ### ✅ Phase 0 gate — CLOSED, verified 2026-09-13
>
> Environment: Podman 6.1.1, `applehv`, **rootless**, **cgroups v2**, **crun**, arm64.
> Compose provider is Docker Desktop's `docker-compose v2.39.1` driving the Podman socket — i.e. the *exact* compat path flagged as likeliest to break.
>
> | Test | Result |
> |---|---|
> | `podman run --systemd=always` + `/sbin/init` → PID 1 | **systemd**, `is-system-running` = `running` |
> | Same image brought up **via `podman compose`**, no systemd flag expressible | **systemd** as PID 1, `is-system-running` = `running` |
>
> Auto-detection survives the compose path. §9.1 stands as designed; no supervisord fallback needed. It is well-established but I have not run it in this environment, and everything in §9.1 depends on it. If it fails, the fallback is supervisord (loses the systemd narrative) or host Quadlet (loses Mac/Windows).

### 9.2 Host Quadlet (optional, Linux only)

On a Linux host we additionally ship `quadlet/*.container` → `~/.config/containers/systemd/` → `systemctl --user enable --now`, plus `loginctl enable-linger $USER` so it survives logout. Gives the "systemd all the way down" beat — systemd supervising services inside the container, systemd supervising the container itself.

Under D7 this is **a backup slide, not a live demo**, and it's explicitly the optional path so nothing breaks on a Mac.

### 9.3 Rootless notes to document (these will bite attendees)

- SELinux on Fedora: bind mounts need `:Z`.
- `podman compose` delegates to `podman-compose` or `docker-compose`; document both and pin the compose spec version we test.
- Ports <1024 need `net.ipv4.ip_unprivileged_port_start`; we deliberately use none.
- `podman machine` CPU/RAM sizing (§3.3 item 8) — the most common reason this feels broken on a Mac.

---

## 10. Build plan

D12 (public repo) moves README and hygiene early — a public repo with a bad README is worse than a private one.

| Phase | Deliverable | Gate |
|---|---|---|
| 0 | ~~Skeleton, compose, networks, systemd-via-compose~~ | ✅ **DONE** — appliance boots, 6 units, zero failures |
| 1 | ~~`net.py`, `egress_log`, `geocode_address`~~ | ✅ **DONE** — live Census calls, caching, egress log |
| 2 | ~~PVWatts tool, cache, `estimate_savings`, README, LICENSE~~ | ⚠️ **code done, PVWatts UNVERIFIED** (§14) |
| 3 | ~~Streamable HTTP, storage tools, resource, prompt~~ | ✅ **DONE** — 6 tools + 1 resource + 1 prompt over HTTP |
| 4 | ~~Agent host + trace printer~~ | ✅ **DONE** — full loop, correct narration |
| 5 | ~~Composite, replay mode, cache seeding, egress report~~ | ✅ **DONE** — 11 landmark fixtures exported |
| 6 | **Benchmark + model decision**; systemd units finalized; clean-VM rehearsal ×2 | **S7**, S1, S5 pass |
| 7 | Slides, demo script, timed runbook, failure playbook | S2 pass (10 runs) |

Phases 1–5 are the engineering; 6–7 are where talks are won or lost. Budget real time for them — especially phase 6, which is now a go/no-go gate on the model choice.

---

## 11. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **3B fabricates data on the granular path** | **Critical** | Do not ship 3B for the teaching segment; use 7B + hardened prompt + validation (§3.3.3) |
| No model meets a 45 s median on this Mac | Med | 7B is 33–44 s/turn with caches warm. Relax S7 to 60 s, or present from a many-core box |
| 7B chains tools unreliably on stage | **High** | Composite tool as primary path; 10 rehearsal runs; fixed demo address |
| Conference Wi-Fi dies | High | Replay mode + pre-seeded cache (§6.4) |
| ~~Rootless systemd-in-container fails~~ | ~~Med~~ | **Closed 2026-09-13** — verified via `podman run` *and* via compose (§9.1) |
| ~~Compose won't trigger Podman's systemd mode~~ | ~~High~~ | **Closed 2026-09-13** — auto-detection survives docker-compose-over-Podman (§9.1) |
| **16GB host + 8GB VM too tight for 7B plus slides** | **High** | Benchmark early; `qwen2.5:3b-instruct` is now the likely landing spot, not the fallback (§3.3) |
| Host disk exhaustion (~31GB free) | Med | `make doctor` checks free space; prune build cache; 3B model halves the footprint |
| `podman machine` defaults OOM the model | Med | Documented sizing; `make doctor` checks CPU/RAM and warns |
| NREL rate limit / outage | Med | Personal key (not `DEMO_KEY`), cache, replay |
| Streamable HTTP transport friction | Med | Pin `mcp>=1.9`; keep stdio path tested |
| Someone challenges the privacy claim | Med | We raise it first (§7) and the isolation is kernel-enforced |
| Public repo leaks a real address via seeded cache | Med | Landmark-only allowlist + pre-commit check (§6.4) |
| Census returns no match for an audience address | Low | `hint` guides the model to ask for ZIP; pre-seeded fallbacks |
| Live coding overruns | Med | No live coding. Pre-written code, revealed and run |
| Isolation proof is vacuous with Wi-Fi off | High | §7.1 topology proof is primary; contrast demo marked optional in the runbook |
| `warm-cache.timer` pollutes `egress_log` mid-talk | Med | Masked by default; runbook verifies before the demo |
| Talk is titled "on Linux" but presented from a Mac | Med | Name it in the first two minutes — the containers *are* Linux; own it rather than let someone catch it |
| Composite tool crowds out the granular demo | Med | `TOOL_PROFILE` switch (§4.1); scripted restart between segments |

---

## 12. Talk timing budget (≤40 min)

The previous version of this table summed to exactly 40:00 with no slack and no Q&A — which is a plan to run over. Most 40-minute slots are ~35 minutes of content plus questions. Retimed to **34 minutes of content**:

| Min | Segment |
|---|---|
| 0–3 | Hook: "is my house good for solar?" + the thesis and what "local" actually means |
| 3–7 | Why now — the shift to cheap optimized inference; ERCOT/Texas framing |
| 7–11 | Ollama + how tool calling actually works |
| 11–18 | Building the MCP server: the tools, the error contract, resources & prompts |
| **18–27** | **LIVE DEMO** — granular chain, then restart in composite profile |
| 27–30 | The privacy proof (§7.1): topology first, contrast demo if the network is up |
| 30–33 | Packaging: systemd inside the container; "and here's Quadlet on Linux" |
| 33–35 | Wrap + repo link + "steal this for your own tools" |
| 35–40 | Q&A / overrun buffer |

**The demo has ~9 minutes**, and one of them is the cold prefill at the profile switch (§4.1). At 7B CPU speeds that leaves roughly 4–5 turns — which is precisely why the composite tool and `OLLAMA_KEEP_ALIVE=-1` are architectural decisions rather than optimizations. Phase 7 must rehearse against this clock with a timer running.

**S2 costs real time:** 10 rehearsal runs at 4–5 turns and ≈45–90s per turn is roughly 90 minutes of pure rehearsal, excluding resets. Schedule it, don't discover it.

---

## 13. Remaining open questions

1. **Model choice — now a measurement, not a preference.** 7B fails S7 on the
   dev Mac (median 67 s vs a 45 s target). 3B is pulled and benchmarking.
   Whatever you present from, run `make bench` there and set `MODEL_NAME` to
   whatever passes. Do not take a failing model on stage.
2. **Presentation machine still undecided.** Everything is specced for the worst
   case and verified on it. A Linux host would improve latency and would let
   §9.2 Quadlet be demoed live; nothing in the design has to change either way.
3. ~~**NREL API key**~~ — resolved; key is in `.env` (600, gitignored before it
   was written). **Still outstanding:** regenerate it before the repo goes
   public, since it came through a chat transcript. And note the key being
   present is not the same as the integration working — see §14.
4. **Repo name and GitHub org** for D12, and whether slides live in `talk/` or
   separately. `git init` is done; nothing is committed.
5. **Demo address.** Fixtures are 11 verified public Texas landmarks. If you
   want to use a real property live, decide now whether the egress log gets
   scrubbed before publishing — the log is on the projector.

## 14. Build log — what was verified, and what broke

Built and executed 2026-09-13 on a 10-core / 16 GB Apple Silicon Mac, Podman
6.1.1 (`applehv`, rootless, cgroups v2, crun), VM at 8 CPU / 8 GB / 40 GB.

### Verified working

| Claim | Evidence |
|---|---|
| systemd as PID 1, rootless, unprivileged, **via compose** | `is-system-running` = `running`, 6 units, 0 failures |
| Unit ordering replaces `depends_on` | container-env → pg-init → postgresql → pg-bootstrap → migrate → mcp-solar |
| `internal: true` blocks egress but not container-to-container | isolated→internet fails; isolated→isolated HTTP 200 |
| Model container has no route out | identical probe: appliance `CONNECTED`, ollama fails |
| Model pulled by a throwaway container, used by an isolated one | shared volume; `ollama list` sees it from `netint` |
| MCP over Streamable HTTP | 6 tools + 1 resource + 1 prompt, from host and from the agent container |
| Live geocoding + caching | 11 landmark addresses, whitespace/case variants hit cache |
| Egress log distinguishes live from cached | report prints "1 left the machine, 1 from cache" |
| Fixture export refuses unsafe data | skipped the synthetic PVWatts entry automatically |
| Full agent loop with correct narration | 3 tool calls → grounded plain-English answer |
| **The model's numbers are exactly right** | $1,442.35 / 9.5 yr / $15,127 — all matched Python to the cent, because `estimate_savings` computes them, not the LLM |
| `keep_alive=-1` keeps the model resident | `ollama ps` → `UNTIL: Forever` |
| 27 offline tests | no network, no database |

### Bugs found by running it (every one would have surfaced at rehearsal)

| # | Bug | Consequence if unfixed |
|---|---|---|
| 1 | `mcp` 2.x renamed `FastMCP` → `MCPServer` | Import error; the plan's `mcp>=1.9` pin was stale |
| 2 | Tool schemas read via `inputSchema`; 2.x exposes `input_schema` | **Silently empty schemas** — model sees tools with no parameters |
| 3 | Optional params emit `anyOf:[type,null]`; Ollama rejects it | HTTP 400 on every chat call |
| 4 | `keep_alive: "-1"` sent as a string | `time: missing unit in duration "-1"` — 400. The top latency mitigation was broken |
| 5 | DNS-rebinding protection defaults on with an empty allow-list | `Invalid Host header` from any other container |
| 6 | Allow-list pinned `:8000` | Broke the moment compose mapped a different host port; fixed with the `host:*` wildcard |
| 7 | Final answer appended, *then* streamed again | **Empty narration** plus a duplicate generation — cost 14 s/turn |
| 8 | Tool-selection turns had no `num_predict` cap | **17-minute runaway** mid-benchmark |
| 9 | `postgresql-setup --initdb` needs D-Bus | pg-init failed; call `initdb` directly |
| 10 | Healthcheck treated HTTP 406 as failure | Stack never reported healthy; 406 is the *correct* answer to a bare GET |
| 11 | UBI9 has no `postgresql-server` | Appliance base switched to Fedora 41; later Fedora 44 + `postgresql16-server` (F41 reached EOL; PG 16 keeps existing volumes readable) |
| 12 | Podman picked Docker Desktop's compose binary | `docker-credential-desktop` not found; installed `podman-compose` and set `compose_providers` |
| 13 | `keep_alive=-1` never evicts the previous model | Benchmarking 7B then 3B left **both** resident: 5.5 + 2.7 = 8.2 GB in an 8 GB VM. Swapping, and every measurement after the switch is wrong. `ollama stop <model>` before switching |
| 14 | **NLR renamed the developer network**; `developer.nrel.gov` no longer resolves | Every PVWatts call failed. New host is `developer.nlr.gov`; v8 is still current (v6 is the deprecated one). `make check-nrel` now PASSES |
| 15 | `podman compose run` attaches to the project's *first* network, not the service's declared one | The agent could not resolve `ollama`. `make demo`/`make bench` now use `podman run --network localaimcp_netint` explicitly |
| 16 | podman-compose `run` tears down sibling containers | The ollama container silently disappeared mid-session. Bring the stack up with `make up`; keep `run` for the agent only |
| 17 | Models invent tool *parameters* | 3B sent `azimuth=235, losses=0.02`; 7B sent `system_cost=0` (payback became null) and `itc_rate=0.22`. Fixed by removing geometry from `assess_property` and validating `estimate_savings` inputs |
| 18 | Prose system prompts are ignored by small models | "Never estimate from memory" was disregarded by both models. A numbered, imperative rule list got 7B copying coordinates digit-for-digit |
| 19 | `egress-report` filtered by its **own** random session id | The script runs as a separate process, so it never matched the server's session and printed "No outbound requests" after a perfectly good demo — i.e. the talk's closing evidence was blank. Now defaults to the newest session in the table |
| 20 | Address cache keys kept punctuation | `"San Antonio TX"` and `"San Antonio, TX"` were different rows. Under `REPLAY_ONLY` one missing comma is a **failed offline demo**. Normalisation now strips punctuation |
| 21 | `make seed-cache` reads fixtures **baked into the image** | Exporting fresh fixtures to the repo changes nothing until `podman compose build appliance`. Caught it seeding 0 PVWatts entries |

Bugs 2, 3, 4 and 7 are each independently fatal and none is visible by reading
the code. This is the argument for building before finalising the talk.

### Not verified — requires action

1. ~~**PVWatts has never been called.**~~ ✅ **RESOLVED.** The host moved to
   `developer.nlr.gov` (NLR, formerly NREL); v8 is still current, v6 is the
   version being deprecated. `make check-nrel` now **PASSES**: v8.5.0, key valid
   (1000 req/hr), and the live response shape matches what the code parses.
   Real figure for the Capitol: 10,433.8 kWh/yr, 17.0% capacity factor.
2. ~~**Model choice is open.**~~ ✅ **RESOLVED** — `qwen2.5:7b-instruct`, on
   correctness grounds (§3.3.3). Re-run `make bench` on the presentation machine.
3. **Quadlet units are written but not executed** — they need a Linux host.

**S3 and S4 are now verified end-to-end.** With `REPLAY_ONLY=true` and the
committed fixtures seeded, a full assessment completes in 26.9 s and
`make egress-report` prints *0 requests actually left this machine, 2 answered
from the local cache*. With the network on and an uncached address, the same
report prints **exactly two rows** — Census and `developer.nlr.gov` — with the
API key shown as `<redacted>`.

### Environment changes made

- Installed `podman` 6.1.1 and `podman-compose` 1.6.0 via Homebrew.
- Created `podman machine` (8 CPU / 8 GB / 40 GB).
- Appended `compose_providers=["podman-compose"]` to
  `~/.config/containers/containers.conf` (existing file backed up).
- Host disk went 31 GB → ~11 GB free: VM image, Fedora layers, and two models.
  **Disk is now a real constraint.**
