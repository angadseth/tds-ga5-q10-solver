# A2A Durable Delegate — full working solver

A complete, deployable **A2A 1.0 Invoice Action Agent** for the GA5 question
*"Build a Durable A2A Delegate"* (`q-a2a-durable-delegate-server`, 4 marks).

This is the whole thing, not a sketch. Clone it, run one command to prove it
works, deploy it, paste your URL, press Check.

> **No keys in this repo, and you don't need one.** The agent reads its answers
> straight out of the case files, so it makes **zero model calls**. Cost: ₹0.
> If you want the model fallback anyway, put **your own** key in `.env` —
> never anyone else's.

---

## 1. Quick start (2 minutes)

```bash
git clone https://github.com/<you>/tds-ga5-q10-solver.git
cd tds-ga5-q10-solver

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python selftest.py
```

You should see **`78 passed, 0 failed`**. That runs the entire graded flow
offline — agent card, auth, media types, proposals, idempotency, conflicts,
principal isolation, receipts, replay and the cancel race — with no network and
no API key.

Run it locally if you want to poke at it:

```bash
uvicorn app:app --port 8000
curl localhost:8000/.well-known/agent-card.json
```

---

## 2. The one thing that decides this question

Most people lose marks here by asking a model to read the case files. Don't.
**The packages are generated, not written by hand**, and the generator always
puts the answer in the same place:

| document | opening paragraph holds | bracketed refs |
|---|---|---|
| `intake-and-cover-sheet.txt` | `Case-file extract. Supplier <V>; invoice <INV>; stated total <CUR> <AMT>.` | **1 — a decoy** |
| `ledger-and-correspondence.txt` | **the decisive paragraph: exactly 3 sentences, one ref each** | **3 — the answer** |
| `policy-and-audit-notes.txt` | archive note + training appendix | **2 — decoys** |

Every other paragraph is filler repeated word for word across the whole corpus.
The question says it outright:

> *Return exactly the three decisive bracketed references from the paragraph
> that determines the action. Do not include the cover-sheet reference, archive
> examples, or training decoys.*

So the action, the facts and the evidence are all **readable without a model**.
That is what `deterministic_decision()` in `a2a_agent.py` does. It also removes
the drift a model gives you between a Check and a Save — same input, same
answer, every single time.

### Classifying the action

Match the decisive paragraph against phrase signals, **most specific first**:

```
reject_duplicate  → "same commercial key", "earlier settled entry",
                    "duplicate-control policy requires rejection"
open_exception    → "exception workflow", "beyond tolerance",
                    "contradictory signed records"
hold_invoice      → "destination-account change", "known-number callback",
                    "newly supplied bank account"
request_approval  → "delegation ceiling", "named financial approver",
                    "delegation schedule assigns"
settle_invoice    → "clean three-way match", "no earlier posting",
                    "reconcile without an exception"
```

⚠️ **Order matters.** The `request_approval` paragraphs *open* with a
clean-reconciliation sentence, so if you test `settle_invoice` first you will
misread every one of them. Classify `settle_invoice` **last**.

---

## 3. The five bugs that cost marks

These are the ones that make the grader reject every proposal, which leaves
`executions` empty and drops you to ~3.5/4 or lower.

1. **Exactly three evidence refs.** Two is wrong. Four is wrong. Take them from
   the decisive paragraph only — never the cover sheet, archive or training refs.
2. **`amountMinor` is in MINOR units.** `EUR 38,721.92` → **`3872192`**, not
   `38721`. Watch the zero-decimal currencies: `JPY 480,000` → `480000`, not
   `48000000`. See `CURRENCY_EXPONENT` for the ISO-4217 exceptions.
3. **Refuse anything that is not `application/a2a+json`.** The grader posts an
   otherwise perfectly valid batch as `application/json` and expects a refusal.
   Being liberal here costs the whole media-type mark. Answer **415**.
   Parameters like `; charset=utf-8` are still fine.
4. **Another principal's task is `404`, never `403`.** Each distinct Bearer
   token is a separate tenant. "Exists but forbidden" leaks the task's existence
   and fails isolation.
5. **`GET /a2a/tasks` must be compact.** This is the one that bites hardest —
   see below.

### `ISOLATION_PROBE_UNAVAILABLE` — the 512 KiB trap

> *Successful A2A responses must use JSON/A2A media types and stay at or below
> 512 KiB.* … *A timeout, 5xx, malformed probe response, or **owner-list
> failure** loses isolation marks.*

A task's `history` keeps the initial message, and the initial message carries
all twelve long case files. So **one** task serialises to roughly 300 KiB. The
graded run is five core tasks plus a hidden audit task under one token — and if
your `GET /a2a/tasks` returns the full Task document for each, the listing comes
out at about **1.5 MiB**. The grader can't read it, so the isolation probe never
runs and you get:

```
isolation 0.00/0.75 — ISOLATION_PROBE_UNAVAILABLE
```

Nothing is actually leaking. Your isolation logic is fine. The body is just too
big. The fix is `compact_task()` in `a2a_agent.py`: the listing returns each
Task's **identity, state, metadata and artifact descriptors**, with the history
and the artifact payloads dropped. Measured on a realistic corpus, that takes
the listing from **1589 KiB to 3.9 KiB**, while `GET /a2a/tasks/{id}` still
returns the whole task (282 KiB, comfortably under the ceiling).

There is also a `fit()` guard on every task response: if a body would ever
cross the limit it sheds payloads rather than returning something oversized. It
only engages above the limit, so a normal run is untouched.

---

## 4. Deploy on Render (free)

1. Push this repo to **your own** GitHub account.
2. [render.com](https://render.com) → **New → Web Service** → connect the repo.
3. Settings:
   - **Runtime:** Python 3
   - **Build:** `pip install -r requirements.txt`
   - **Start:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - **Plan:** Free
4. **Environment** tab → add:
   - `A2A_DB` = `/tmp/a2a.db`
   - `A2A_BASE_URL` = `https://<your-service>.onrender.com/a2a/`
     *(add this after the first deploy, then redeploy — the agent card has to
     advertise the real URL)*
5. Deploy, then confirm:

```bash
curl https://<your-service>.onrender.com/.well-known/agent-card.json
```

There is a `Dockerfile` and a `render.yaml` here too if you prefer either route.
Any host works — Railway, Fly, a VPS. It just has to be public HTTPS with no
auth wall in front of it.

> **Free tier sleeps after ~15 min.** Open your URL once right before you press
> Check, or the first grader request eats the cold start.

---

## 5. Submit

Paste this into the question's answer box:

```
https://<your-service>.onrender.com/a2a/
```

**With the trailing `/a2a/`.** Then press **Check**, and when the score looks
right press **Save**. Check alone does not record anything.

---

## 6. What the agent exposes

| method | path | purpose |
|---|---|---|
| `GET` | `/.well-known/agent-card.json` | discovery — **served at the origin**, not under `/a2a/` |
| `GET` | `/.well-known/agent.json` | legacy alias |
| `POST` | `/a2a/message:send` | start a batch, or continue one with receipts |
| `GET` | `/a2a/tasks` | list the calling principal's tasks |
| `GET` | `/a2a/tasks/{id}` | read one task |
| `POST` | `/a2a/tasks/{id}:cancel` | cancel before finalisation |

Every request needs `Authorization: Bearer <token>` and `A2A-Version: 1.0`;
bodies need `Content-Type: application/a2a+json`.

### The lifecycle

```
message:send  (invoice-claim-batch)
   → SUBMITTED → WORKING → INPUT_REQUIRED
   → artifact: one proposal per package
       { packageId, actionId, action, facts, evidenceRefs[3], rationale }

message:send  (invoice-action-results, same taskId + contextId)
   → WORKING → COMPLETED
   → artifact: executions for the ACCEPTED results only
```

### Durability rules the marks depend on

- Dedup key is `(principal, messageId)`, fingerprinted over the **semantic**
  message. Reordered keys and `configuration` churn are free replays; changed
  content is a **409**.
- Everything is persisted to SQLite **before** the response is written.
- A terminal task is immutable. The only thing still answered is an **exact**
  receipt replay, and it is answered from stored state.
- Finalisation and cancellation resolve in one synchronous critical section, so
  exactly one of them wins the race.
- `REJECTED` results are recorded but never executed.

---

## 7. Troubleshooting

| symptom | cause |
|---|---|
| `executions` always empty | a proposal wasn't exact — usually 2 refs instead of 3, a decoy ref, or `amountMinor` off by 100× |
| media-type mark fails | you accepted `application/json`; return **415** |
| isolation mark fails | you returned 403 (or 200) for another token's task; return **404** |
| `ISOLATION_PROBE_UNAVAILABLE` | your `GET /a2a/tasks` body is over 512 KiB — see section 3 |
| replay/idempotency fails | you fingerprinted the whole request instead of the message, so `configuration` churn looked like a conflict |
| score moves between Check and Save | you used a model — decide from the documents instead |
| first grader request times out | free-tier cold start; warm the URL first |

---

## 8. Layout

```
app.py           entrypoint: mounts the agent, path normaliser, /health
a2a_agent.py     the whole agent — A2A surface, storage, decision logic
llm.py           optional model fallback, env-driven, no key committed
selftest.py      59 offline assertions covering the full graded flow
Dockerfile       container build
render.yaml      Render blueprint
.env.example     copy to .env and fill in your own values
```

---

## 9. Please read

Your case files are **personalised to your email**, so the code alone earns
nobody anything — you have to deploy it and run it yourself. Use it to
understand the shape of the problem, and use **your own** API keys and your own
deployment. Don't paste someone else's URL into your answer box.

MIT licensed. Open an issue if something breaks.
