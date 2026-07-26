"""Entry point. Mounts the A2A agent and a couple of liveness routes.

Run locally:   uvicorn app:app --host 0.0.0.0 --port 8000
"""
import os
import re

from fastapi import FastAPI

import a2a_agent

app = FastAPI(title="A2A Invoice Action Agent")


@app.middleware("http")
async def normalise_path(request, call_next):
    """Collapse repeated slashes and drop a stray trailing one before routing.

    The base URL you submit ends in a slash, so a client that joins it to
    "a2a/message:send" by plain concatenation can ask for "//a2a/...", which
    matches no route. A trailing slash otherwise earns a 307, and a redirected
    POST is at the mercy of whether the client replays the body. Neither is
    worth a lost request.
    """
    path = request.scope.get("path") or "/"
    fixed = re.sub(r"/{2,}", "/", path)
    if len(fixed) > 1 and fixed.endswith("/"):
        fixed = fixed.rstrip("/") or "/"
    if fixed != path:
        request.scope["path"] = fixed
        raw = request.scope.get("raw_path")
        if isinstance(raw, bytes):
            request.scope["raw_path"] = fixed.encode("utf-8")
    return await call_next(request)


app.include_router(a2a_agent.router)


@app.get("/")
async def root():
    return {"service": "a2a-invoice-action-agent", "protocol": "1.0",
            "agentCard": "/.well-known/agent-card.json",
            "base": a2a_agent.BASE_URL}


@app.get("/health")
async def health():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
