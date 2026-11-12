"""The Python side: FastAPI on uvicorn, PyJWT and asyncpg, the most used package for each job.

uvicorn runs one worker process per core (--workers), because one Python process runs Python code on one thread at a
time (the GIL).
"""

import os

import asyncpg
import jwt
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse

SECRET = os.environ.get("JWT_SECRET")
if not SECRET:
    raise RuntimeError("JWT_SECRET is not set")

QUERY = """SELECT id, status, total_cents, items,
  to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at
  FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"""

app = FastAPI()
pool: asyncpg.Pool | None = None


@app.on_event("startup")
async def connect() -> None:
    global pool
    pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"], min_size=4, max_size=32
    )


@app.get("/health", response_class=PlainTextResponse)
async def health() -> str:
    return "ok"


def check_token(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401)
    try:
        claims = jwt.decode(
            authorization[7:],
            SECRET,
            algorithms=["HS256"],
            options={"require": ["exp"]},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401) from None
    if "orders:read" not in str(claims.get("scope", "")).split():
        raise HTTPException(status_code=401)


@app.get("/customers/{customer_id}/orders")
async def orders(customer_id: int, authorization: str | None = Header(default=None)):
    check_token(authorization)
    rows = await pool.fetch(QUERY, customer_id)
    return {"customer_id": customer_id, "orders": [dict(r) for r in rows]}
