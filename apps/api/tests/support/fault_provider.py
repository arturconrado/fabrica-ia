import asyncio
import json
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse


app = FastAPI(title="ASF Homologation Fault Provider")


@app.get("/health")
def health():
    return {"status": "ok", "purpose": "isolated-homologation-only"}


def _completion(content: str) -> dict:
    return {
        "id": f"fault-{time.time_ns()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "asf-fault-provider",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@app.post("/{mode}/v1/chat/completions")
async def chat_completions(mode: str, request: Request):
    # Consume the body so client/proxy behaviour matches an OpenAI-compatible
    # upstream. The body is never logged or persisted by this fixture.
    await request.body()
    if mode == "rate_limit":
        return JSONResponse(status_code=429, content={"error": {"message": "deterministic rate limit", "type": "rate_limit"}}, headers={"Retry-After": "1"})
    if mode == "timeout":
        await asyncio.sleep(float(os.getenv("ASF_FAULT_TIMEOUT_SECONDS", "5")))
        return JSONResponse(_completion("{}"))
    if mode == "schema_invalid":
        return JSONResponse(_completion("{}"))
    if mode == "truncated":
        return PlainTextResponse('{"id":"truncated","choices":[', media_type="application/json")
    if mode == "connection_interrupted":
        async def partial():
            yield b'{"id":"partial","choices":['
            raise RuntimeError("deterministic interrupted upstream")
        return StreamingResponse(partial(), media_type="application/json")
    if mode == "unavailable":
        return JSONResponse(status_code=503, content={"error": {"message": "deterministic unavailable"}})
    if mode == "success":
        return JSONResponse(_completion(json.dumps({"status": "ok"})))
    return JSONResponse(status_code=404, content={"error": {"message": "unknown fault mode"}})
