"""End-to-end self test. No network, no API key, no deployment needed.

    python selftest.py

Builds synthetic case files in the same layout the graded corpus uses, drives
the whole A2A flow, and asserts every behaviour the marks depend on: the agent
card, auth, protocol version, media type, proposal exactness, idempotency,
conflicts, principal isolation, the receipt continuation, replay and the
cancel/receipt race.
"""
import json
import os
import sys
import tempfile
import uuid

os.environ.setdefault("A2A_DB", os.path.join(tempfile.mkdtemp(), "selftest.db"))
os.environ.pop("LLM_API_KEY", None)  # prove it works with no model at all

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

client = TestClient(app)

A2A = "application/a2a+json"
TOKEN_A = "tenant-a-token"
TOKEN_B = "tenant-b-token"
BATCH_MODE = "application/vnd.ga5.invoice-claim-batch+json"
RESULT_MODE = "application/vnd.ga5.invoice-action-results+json"

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(("  ok   " if condition else "  FAIL ") + name + (
        "" if condition or not detail else "\n         " + str(detail)))


def headers(token=TOKEN_A, ctype=A2A, version="1.0"):
    h = {"authorization": "Bearer " + token}
    if version is not None:
        h["a2a-version"] = version
    if ctype:
        h["content-type"] = ctype
    return h


FILLER = (
    "\n\nRoutine correspondence retained for chronology. A scanning worker "
    "reprocessed the attachment set and no content changed. This paragraph is "
    "repeated across the corpus and carries no decisive reference [R_FILL001]."
)

# The five decisive paragraphs, one per action. Each is exactly three
# sentences, each sentence carrying exactly one bracketed reference - which is
# how the generator states the answer.
DECISIVE = {
    "settle_invoice": (
        "The ledger shows a clean three-way match between the invoice, the "
        "controlling order and the goods receipt [R_AAA111]. There is no "
        "earlier posting for this commercial identity [R_AAA222]. The totals "
        "reconcile without an exception and no discrepancy remains [R_AAA333]."
    ),
    "request_approval": (
        "The ledger reconciles with the controlling order and the goods "
        "receipt with no exception [R_BBB111]. The amount sits above the "
        "delegation ceiling for this operator [R_BBB222]. The delegation "
        "schedule assigns it to a named financial approver [R_BBB333]."
    ),
    "hold_invoice": (
        "The remittance instruction carries a newly supplied bank account "
        "[R_CCC111]. That destination-account change replaces the established "
        "beneficiary of record [R_CCC222]. Payment-change control pauses "
        "disbursement until the known-number callback closes [R_CCC333]."
    ),
    "reject_duplicate": (
        "The ledger contains an earlier posting for the same supplier and "
        "amount [R_DDD111]. Both entries share the same commercial key and "
        "the earlier settled entry is already paid [R_DDD222]. The "
        "duplicate-control policy requires rejection of the second "
        "disbursement [R_DDD333]."
    ),
    "open_exception": (
        "The claimed total does not reconcile with the controlling order "
        "[R_EEE111]. The variance sits beyond tolerance and the file holds "
        "contradictory signed records [R_EEE222]. Incompatible contract "
        "interpretations route this to the exception workflow [R_EEE333]."
    ),
}


def package(pkg_id, action, vendor, invoice, currency, amount):
    return {
        "packageId": pkg_id,
        "documents": [
            {"name": "intake-and-cover-sheet.txt",
             "text": (f"Case-file extract. Supplier {vendor}; invoice {invoice}; "
                      f"stated total {currency} {amount}. Reference [R_COVER01] "
                      "identifies the intake scan only." + FILLER)},
            {"name": "ledger-and-correspondence.txt",
             "text": DECISIVE[action] + FILLER},
            {"name": "policy-and-audit-notes.txt",
             "text": ("Archived training example retained for auditor "
                      "onboarding [R_ARCH001]. A worked appendix case is "
                      "included for reference [R_TRAIN01]." + FILLER)},
        ],
    }


BATCH = {
    "batchId": "BATCH-SELFTEST-1",
    "policyRevision": "2026-05-01",
    "packages": [
        package("PKG-1", "settle_invoice", "Northwind Supplies Ltd", "INV-4401", "EUR", "38,721.92"),
        package("PKG-2", "request_approval", "Contoso Industrial", "INV-4402", "USD", "95,000.00"),
        package("PKG-3", "hold_invoice", "Fabrikam Logistics", "INV-4403", "GBP", "12,300.50"),
        package("PKG-4", "reject_duplicate", "Tailspin Freight", "INV-4404", "USD", "7,410.00"),
        package("PKG-5", "open_exception", "Adventure Works", "INV-4405", "JPY", "480,000"),
    ],
}

EXPECTED = {
    "PKG-1": ("settle_invoice", 3872192, "EUR", ["R_AAA111", "R_AAA222", "R_AAA333"]),
    "PKG-2": ("request_approval", 9500000, "USD", ["R_BBB111", "R_BBB222", "R_BBB333"]),
    "PKG-3": ("hold_invoice", 1230050, "GBP", ["R_CCC111", "R_CCC222", "R_CCC333"]),
    "PKG-4": ("reject_duplicate", 741000, "USD", ["R_DDD111", "R_DDD222", "R_DDD333"]),
    "PKG-5": ("open_exception", 480000, "JPY", ["R_EEE111", "R_EEE222", "R_EEE333"]),
}


def send(message, token=TOKEN_A, ctype=A2A, version="1.0"):
    return client.post("/a2a/message:send",
                       headers=headers(token, ctype, version),
                       content=json.dumps({"message": message}))


def batch_message(message_id, batch=None):
    return {"messageId": message_id, "role": "ROLE_USER",
            "parts": [{"mediaType": BATCH_MODE, "data": batch or BATCH}]}


def proposals_of(task):
    for art in task.get("artifacts") or []:
        for part in art.get("parts") or []:
            data = part.get("data") or {}
            if "proposals" in data:
                return data["proposals"]
    return []


def executions_of(task):
    for art in task.get("artifacts") or []:
        for part in art.get("parts") or []:
            data = part.get("data") or {}
            if "executions" in data:
                return data["executions"]
    return []


print("\n--- discovery and guards ---")
card = client.get("/.well-known/agent-card.json")
check("agent card is served at the origin", card.status_code == 200)
body = card.json()
check("card declares protocol 1.0", body.get("protocolVersion") == "1.0")
check("card declares HTTP+JSON transport", body.get("preferredTransport") == "HTTP+JSON")
check("card advertises a bearer security scheme", "bearerAuth" in (body.get("securitySchemes") or {}))
check("legacy /.well-known/agent.json also answers",
      client.get("/.well-known/agent.json").status_code == 200)

r = client.post("/a2a/message:send", headers={"content-type": A2A, "a2a-version": "1.0"},
                content=json.dumps({"message": batch_message("m0")}))
check("missing bearer token is 401", r.status_code == 401, r.text[:120])
r = send(batch_message("m0"), version=None)
check("missing A2A-Version is 400", r.status_code == 400, r.text[:120])
r = send(batch_message("m0"), version="2.0")
check("wrong A2A-Version is 400", r.status_code == 400, r.text[:120])
r = send(batch_message("m0"), ctype="application/json")
check("application/json body is refused with 415", r.status_code == 415, r.text[:120])
check("responses use the A2A media type",
      send(batch_message("probe-ct")).headers.get("content-type", "").startswith(A2A))

print("\n--- proposals ---")
mid = "msg-" + uuid.uuid4().hex[:8]
r = send(batch_message(mid))
check("batch accepted", r.status_code == 200, r.text[:200])
task = r.json().get("task") or r.json()
check("task waits for receipts (INPUT_REQUIRED)",
      task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", task["status"])
props = proposals_of(task)
check("one proposal per package", len(props) == 5, len(props))
for p in props:
    want = EXPECTED.get(p["packageId"])
    if not want:
        check("unknown packageId " + str(p.get("packageId")), False)
        continue
    action, minor, currency, refs = want
    check(f"{p['packageId']} action = {action}", p["action"] == action, p["action"])
    check(f"{p['packageId']} exactly three evidence refs", len(p["evidenceRefs"]) == 3,
          p["evidenceRefs"])
    check(f"{p['packageId']} refs are the decisive ones", p["evidenceRefs"] == refs,
          p["evidenceRefs"])
    check(f"{p['packageId']} no cover-sheet or training decoy",
          not ({"R_COVER01", "R_ARCH001", "R_TRAIN01"} & set(p["evidenceRefs"])))
    check(f"{p['packageId']} amountMinor in minor units",
          p["facts"]["amountMinor"] == minor, p["facts"]["amountMinor"])
    check(f"{p['packageId']} currency", p["facts"]["currency"] == currency)

print("\n--- idempotency, conflict, isolation ---")
again = send(batch_message(mid))
task2 = again.json().get("task") or again.json()
check("replaying the same messageId returns the same task", task2["id"] == task["id"])
changed = dict(BATCH, batchId="BATCH-SELFTEST-CHANGED")
r = send(batch_message(mid, changed))
check("same messageId with changed content is 409", r.status_code == 409, r.text[:120])
r = client.get(f"/a2a/tasks/{task['id']}", headers=headers(TOKEN_B, ctype=None))
check("another principal gets 404, not 403", r.status_code == 404, r.status_code)
r = client.get("/a2a/tasks", headers=headers(TOKEN_B, ctype=None))
check("another principal's task list is empty", r.json().get("tasks") == [])
r = client.get(f"/a2a/tasks/{task['id']}", headers=headers(TOKEN_A, ctype=None))
check("owner can read the task", r.status_code == 200)

print("\n--- receipts and finalisation ---")
results = []
for i, p in enumerate(props):
    accepted = i != 1  # reject one, to prove only accepted actions execute
    row = {"packageId": p["packageId"], "actionId": p["actionId"],
           "action": p["action"],
           "outcome": "ACCEPTED" if accepted else "REJECTED"}
    if accepted:
        row["receiptNonce"] = "nonce-" + uuid.uuid4().hex[:10]
    results.append(row)

cont = {"messageId": "msg-" + uuid.uuid4().hex[:8], "role": "ROLE_USER",
        "taskId": task["id"], "contextId": task["contextId"],
        "parts": [{"mediaType": RESULT_MODE,
                   "data": {"batchId": BATCH["batchId"], "results": results}}]}
r = send(cont)
check("continuation accepted", r.status_code == 200, r.text[:200])
final = r.json().get("task") or r.json()
check("task completed", final["status"]["state"] == "TASK_STATE_COMPLETED",
      final["status"])
execs = executions_of(final)
check("only accepted actions executed", len(execs) == 4, len(execs))
check("the rejected package was not executed",
      props[1]["packageId"] not in {e["packageId"] for e in execs})
check("executions carry the receipt nonce", all(e.get("receiptNonce") for e in execs))

r = send(cont)
check("identical receipt replay returns the same task",
      r.status_code == 200 and (r.json().get("task") or r.json())["id"] == final["id"],
      r.status_code)
other = json.loads(json.dumps(cont))
other["messageId"] = "msg-" + uuid.uuid4().hex[:8]
other["parts"][0]["data"]["results"] = results[:1]
r = send(other)
check("a different receipt set on a terminal task is 409", r.status_code == 409,
      r.text[:120])
r = client.post(f"/a2a/tasks/{final['id']}:cancel", headers=headers(ctype=None))
check("cancelling a completed task is 409", r.status_code == 409, r.status_code)

print("\n--- cancel before finalisation ---")
mid2 = "msg-" + uuid.uuid4().hex[:8]
t2 = (send(batch_message(mid2, dict(BATCH, batchId="BATCH-SELFTEST-2"))).json().get("task")
      or {})
r = client.post(f"/a2a/tasks/{t2['id']}:cancel", headers=headers(ctype=None))
check("cancel before finalisation succeeds", r.status_code == 200, r.status_code)
state = (r.json().get("task") or r.json())["status"]["state"]
check("state is CANCELED", state == "TASK_STATE_CANCELED", state)
late = {"messageId": "msg-" + uuid.uuid4().hex[:8], "role": "ROLE_USER",
        "taskId": t2["id"], "contextId": t2["contextId"],
        "parts": [{"mediaType": RESULT_MODE,
                   "data": {"batchId": "BATCH-SELFTEST-2", "results": results}}]}
r = send(late)
check("receipts after a cancel are refused", r.status_code == 409, r.status_code)

print("\n" + "=" * 60)
print(f"{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for name in FAIL:
        print("  FAILED:", name)
    sys.exit(1)
print("All good. Deploy it and submit <your-url>/a2a/")
