"""The triage step as a web service: one FastAPI app that runs on your laptop (uvicorn) and
on AWS Lambda (through Mangum, see handler.py) without changing a line.

    POST /chat     {"message": "...", "system": "..."}  ->  {"reply": "...", ...}: one turn with the model
    POST /triage   {"ticket": ..., "account": {...}, "policy_in": "user"}  ->  the triage record,
                   plus what only the function can know: cold start, import time, its own elapsed time
    GET  /         a health check: the same metadata, no model call
    GET  /docs     Swagger UI, locally and on the deployed API

The model call, the retries and the fake provider are unchanged: src/system/triage.py and
src/system/plumbing.py are the same files as in the project repository.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Literal

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:  # the repository root, so "src.system" resolves here and inside the deployment package
    sys.path.insert(0, _ROOT)

_T0 = time.perf_counter()
from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.security import APIKeyHeader  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from src.system.triage import DEFAULT_MODEL, triage  # noqa: E402
from google import genai  # noqa: E402, F401  (load the SDK now, so import time is part of the cold start)

INIT_MS = round((time.perf_counter() - _T0) * 1000)
BUILD = os.environ.get("BUILD", os.environ.get("DEPLOYED_AT", "local"))
_TABLE = os.environ.get("INFERENCES_TABLE")
_DDB = None


def record_inference(request: Request, route: str, started: float, cold: bool, **fields) -> None:
    """One item per call, into the inference table. What happened, never what was said: no
    ticket text, no reply text. A failed write is logged and never fails the request."""
    import datetime as dt
    global _DDB
    ctx = request.scope.get("aws.context")
    rid = getattr(ctx, "aws_request_id", None) if ctx else None
    now = dt.datetime.now(dt.timezone.utc)
    item = {"day": now.strftime("%Y-%m-%d"), "ts": now.strftime("%H:%M:%S.%f") + "#" + (rid or "local"),
            "request_id": rid or "local", "route": route, "build": BUILD, "cold_start": cold,
            "elapsed_ms": round((time.perf_counter() - started) * 1000), **fields}
    print("INFERENCE " + json.dumps(item))
    if not _TABLE:
        return
    try:
        import boto3  # in the Lambda runtime; optional on a laptop
        from decimal import Decimal
        if _DDB is None:
            _DDB = boto3.resource("dynamodb").Table(_TABLE)
        _DDB.put_item(Item={k: (Decimal(str(v)) if isinstance(v, float) else v) for k, v in item.items() if v is not None})
    except Exception as e:
        print(json.dumps({"level": "warn", "inference_table": f"{type(e).__name__}: {e}"[:200]}))
INVOCATIONS = 0   # module state survives between warm invocations of the same sandbox

app = FastAPI(title="triage-api", version="1.0", description="A chat turn and the support-ticket triage step, behind a public API.")


def chat_sample(message: str, temperature: float | None, model: str, system: str | None) -> str:
    """One text turn with the model. Unlike the triage step, this asks for plain text, not JSON."""
    if os.environ.get("PROVIDER") == "fake":
        return f"(fake provider) You said: {message[:80]}"
    from google import genai
    from google.genai import types
    client = genai.Client()  # reads GEMINI_API_KEY from the environment
    config = types.GenerateContentConfig(system_instruction=system, temperature=temperature, max_output_tokens=400)
    resp = client.models.generate_content(model=model, contents=message, config=config)
    return resp.text or ""


class ChatRequest(BaseModel):
    message: str = Field(..., examples=["My water bottle leaks from the lid. What are my options?"])
    system: str | None = Field(default="You are the support assistant for an online store. Be brief and concrete.",
                               description="the system instruction; leave it out for the default")
    temperature: float | None = Field(default=0.7, ge=0, le=2)


class TriageRequest(BaseModel):
    ticket: str = Field(..., examples=["The water bottle from O-55010 leaks from the lid. I'd like a refund for it ($34)."])
    account: dict = Field(..., examples=[{"account_id": "A-11002", "status": "active", "tenure_months": 9,
                                          "recent_orders": [{"order_id": "O-55010", "total": 34.0, "items": ["water bottle"]}],
                                          "open_refunds": 0}])
    policy_in: Literal["user", "system"] = "user"


_token_header = APIKeyHeader(name="x-lab-token", auto_error=False, description="the LAB_TOKEN deploy.sh saved in .env")


def check_token(x_lab_token: str | None = Depends(_token_header)) -> None:
    """The one secret a caller holds. Declared as an API key so the Swagger page shows an Authorize button."""
    expected = os.environ.get("LAB_TOKEN")
    if expected and x_lab_token != expected:
        raise HTTPException(status_code=401, detail="bad or missing x-lab-token header")


def _meta(started: float, cold: bool) -> dict:
    return {"cold_start": cold, "init_ms": INIT_MS, "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "invocation": INVOCATIONS, "model": DEFAULT_MODEL, "provider": os.environ.get("PROVIDER", "gemini"), "build": BUILD}


@app.get("/")
def health() -> dict:
    global INVOCATIONS
    started = time.perf_counter(); cold = INVOCATIONS == 0; INVOCATIONS += 1
    return {"ok": True, "function": _meta(started, cold)}


@app.post("/chat")
def chat(req: ChatRequest, request: Request, _: None = Depends(check_token)) -> dict:
    """One turn with the model: your message in, its reply out. No memory between calls: a
    conversation is a list of turns the caller keeps and sends back, which is a later lesson."""
    global INVOCATIONS
    started = time.perf_counter(); cold = INVOCATIONS == 0; INVOCATIONS += 1
    t0 = time.perf_counter()
    try:
        reply = chat_sample(req.message, req.temperature, DEFAULT_MODEL, req.system)
    except SystemExit as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # the vendor said no: say what it said, in the status the caller can act on
        record_inference(request, "chat", started, cold, error=type(e).__name__, model=DEFAULT_MODEL)
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}"[:300])
    latency_ms = round((time.perf_counter() - t0) * 1000)
    record_inference(request, "chat", started, cold, latency_ms=latency_ms, chars=len(reply), model=DEFAULT_MODEL)
    return {"reply": reply, "model": DEFAULT_MODEL, "latency_ms": latency_ms, "function": _meta(started, cold)}


@app.post("/triage")
def triage_endpoint(req: TriageRequest, request: Request, _: None = Depends(check_token)) -> dict:
    global INVOCATIONS
    started = time.perf_counter(); cold = INVOCATIONS == 0; INVOCATIONS += 1
    provider = os.environ.get("PROVIDER", "gemini")   # PROVIDER=fake for a dry run with no key
    try:
        rec = triage(req.ticket, req.account, provider=provider, policy_in=req.policy_in)
    except SystemExit as e:  # plumbing.py gives up on a daily cap or a dead provider
        record_inference(request, "triage", started, cold, error="provider", model=DEFAULT_MODEL)
        raise HTTPException(status_code=503, detail=str(e))
    rec["function"] = _meta(started, cold)
    record_inference(request, "triage", started, cold, latency_ms=rec["latency_ms"], action=rec["action"],
                     refund_amount=rec.get("refund_amount"), parsed=rec["action"] != "error", model=rec.get("model"), policy_in=req.policy_in)
    return rec
