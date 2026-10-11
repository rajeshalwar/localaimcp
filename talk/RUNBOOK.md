# Demo runbook

Everything here has been executed on the dev machine. Times are real, measured
on a 10-core / 16 GB Apple Silicon Mac with an 8 CPU / 8 GB Podman VM, CPU-only.

---

## T-24 hours

```bash
make doctor                 # podman, cgroups, VM memory, disk, .env
make check-nrel             # REQUIRED: validates the key AND the response shape
make seed-cache             # committed fixtures into the caches
make bench                  # S7 gate: is the demo fast enough?
```

`make check-nrel` passed on 2026-09-13 against **`developer.nlr.gov`** — NLR
renamed the developer network, and the old `developer.nrel.gov` no longer
resolves. v8 is still current (v6 is the deprecated one). Re-run it on the
presentation machine anyway; it is the difference between real numbers and
confident nonsense.

## T-1 hour

```bash
make up
make prove-isolation        # must print Internal: true, ollama on netint only
podman exec appliance systemctl is-system-running     # expect: running
podman exec ollama ollama ps                          # expect: UNTIL = Forever
podman exec appliance systemctl is-enabled warm-cache.timer   # expect: masked
make egress-reset           # start from an empty log
```

The model must already be resident. A cold load is ~6–8 s of silence.

## T-5 minutes

```bash
TOOL_PROFILE=granular make up    # open in granular; composite hidden
make demo
```

Ask one throwaway question to confirm the loop runs, then `make egress-reset`
again so the on-stage log starts clean.

---

## The demo

> **Model: `qwen2.5:7b-instruct`.** 3B is 2.6× faster and fine in
> `composite`, but on the granular path it fabricates coordinates or skips
> tools entirely (one run produced 31.5 kWh/year — off by ~330×). Do not take
> 3B into the granular segment. Measured on the dev Mac: granular 33 s,
> composite 27–44 s per turn.

### 1. The granular chain (~1 min)

> "What would solar look like on the Texas State Capitol, 1100 Congress Ave,
> Austin TX 78701? Assume a 7 kW system."

Watch the three tool calls scroll. This is the teaching moment — the model
choosing tools, one at a time.

### 2. Switch to the composite (~30 s, includes a cold prefill)

```bash
TOOL_PROFILE=composite make up && make demo
```

> "Changing which tools are advertised changes the prompt prefix, which throws
> away the model's KV cache. That pause is the price of the switch — and it is
> exactly why a stable tool list matters."

Then ask the same question. One call instead of three.

### 3. The privacy proof (~2 min)

```bash
make prove-isolation     # topology. Works offline. This is the primary proof.
make prove-egress        # contrast. ONLY if the network is healthy.
make egress-report       # the receipt
```

Say the claim precisely:

> "The model never touched the network — it has no route to touch it. Two
> requests left this machine: an address to a US government geocoder, and a
> *rounded* coordinate to a US government solar API. No prompt, no
> conversation, no reasoning, no stored result. Here is the log."

### 4. systemd (~2 min)

```bash
make systemd-status
podman exec appliance systemctl restart mcp-solar.service    # watch it come back
```

---

## If it goes wrong

| Symptom | Do this |
|---|---|
| Wi-Fi is dead | `REPLAY_ONLY=true make up && make demo` (the server enforces it, not the agent). Skip `prove-egress`; `prove-isolation` still works. |
| Model is slow / not resident | `podman exec ollama ollama ps`. If empty, the keep-alive lapsed — ask a throwaway question to reload. |
| Two models resident at once | `keep_alive=-1` does not evict on switch. `podman exec ollama ollama ps`; if both are listed, `podman exec ollama ollama stop <the-one-you-are-not-using>`. On an 8 GB VM, 7B + 3B together will swap. |
| Model loops on tool calls | Switch to `TOOL_PROFILE=composite`. One call, no chaining to get wrong. |
| Model quotes a number no tool returned | Stop and switch to `TOOL_PROFILE=composite`. Do **not** try to correct it live. |
| Agent errors on start | `podman exec appliance systemctl status mcp-solar.service`, then `make logs`. |
| A tool returns an error on stage | Read the `hint` aloud. Tool errors are prompts — it is a slide, not a failure. |
| Everything is broken | `make down && make up` takes ~40 s. Have the trace JSON from rehearsal open as a fallback. |

## Never do on stage

- `make clean` — destroys the volumes, including the seeded cache.
- Enable `warm-cache.timer` — it adds rows to the egress log mid-talk.
- Ask about an address that is not seeded, while in `REPLAY_ONLY`. Punctuation
  no longer matters (keys ignore it), but the street number and city must be on
  the list in `fixtures/seed_addresses.txt`.
- Use your home address. The egress log is on the projector.
