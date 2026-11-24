"""HTTP API and web page.  Run: .venv/bin/uvicorn serve.api:app --port 8008

Demo mode (for recording the injection demo):
  DEMO=attack            use the clone databases with planted injections
                         (./data/setup_attack_dbs.sh first)
  GROUNDING=0            turn off the answer grounding check
"""
import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent.service import Agent

WEB = Path(__file__).resolve().parent / "web"
app = FastAPI(title="SQL Analyst")
DEMO = os.environ.get("DEMO", "")
GROUNDING = os.environ.get("GROUNDING", "1") != "0"


@lru_cache
def agent() -> Agent:
    clones = {"bird": "bird_attack", "pagila": "pagila_attack"} if DEMO == "attack" else None
    return Agent(databases=clones, grounding=GROUNDING)


@app.get("/api/mode")
def mode() -> dict:
    return {"demo": DEMO or None, "grounding": GROUNDING}


class AskIn(BaseModel):
    database: str
    question: str = Field(min_length=3, max_length=500)
    evidence: str | None = Field(default=None, max_length=1000)


@app.get("/api/databases")
def databases() -> list[str]:
    return agent().databases()


@app.get("/api/schema/{database}")
def schema(database: str) -> dict:
    try:
        return agent().describe_schema(database)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/ask")
def ask(body: AskIn) -> dict:  # sync: FastAPI runs it in a worker thread
    try:
        return agent().ask(body.database, body.question, body.evidence or None)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")
