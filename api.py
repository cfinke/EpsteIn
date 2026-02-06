#!/usr/bin/env python3
"""
FastAPI service for searching Epstein files using LinkedIn Connections CSV.
"""

import io
import os
import secrets
import tempfile
from typing import Optional
import time

from fastapi import FastAPI, File, HTTPException, UploadFile, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from epstein_core import (
    ensure_requests,
    normalize_hit,
    parse_linkedin_contacts_stream,
    search_epstein_files,
    generate_html_report,
)

app = FastAPI(title="EpsteIn API", version="1.0.0")

def _load_local_env_file():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if not key:
                continue

            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in ("'", '"')
            ):
                value = value[1:-1]

            # Keep explicit shell env higher priority than local .env file.
            os.environ.setdefault(key, value)


_load_local_env_file()


def _load_allowed_origins():
    cors_env = os.getenv("CORS_ALLOW_ORIGINS", "")
    origins = [origin.strip() for origin in cors_env.split(",") if origin.strip()]
    if not origins:
        raise RuntimeError(
            "CORS_ALLOW_ORIGINS is required and must contain at least one explicit origin"
        )
    if any(origin == "*" for origin in origins):
        raise RuntimeError("Wildcard origin '*' is not allowed in CORS_ALLOW_ORIGINS")
    return origins


def _load_bearer_token():
    token = (os.getenv("API_BEARER_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("API_BEARER_TOKEN is required")
    return token


ALLOWED_ORIGINS = _load_allowed_origins()
API_BEARER_TOKEN = _load_bearer_token()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROTECTED_PATHS = {"/search", "/search/", "/report", "/report/"}


@app.middleware("http")
async def require_bearer_token(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    if request.url.path in PROTECTED_PATHS:
        auth_header = request.headers.get("Authorization", "")
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not secrets.compare_digest(token.strip(), API_BEARER_TOKEN):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

    return await call_next(request)


def _load_contacts_from_upload(upload: UploadFile):
    content = upload.file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("utf-8", errors="replace")
    return parse_linkedin_contacts_stream(io.StringIO(text))


def _search_contacts(contacts, delay_ms, include_hits, max_hits: Optional[int]):
    results = []
    delay = max(delay_ms, 0) / 1000.0

    for i, contact in enumerate(contacts):
        search_result = search_epstein_files(contact['full_name'])
        total_mentions = search_result['total_hits']
        hits = search_result.get('hits') or []
        error = search_result.get('error')

        if max_hits is not None:
            hits = hits[:max_hits]

        results.append({
            'name': contact['full_name'],
            'first_name': contact['first_name'],
            'last_name': contact['last_name'],
            'company': contact['company'],
            'position': contact['position'],
            'total_mentions': total_mentions,
            'hits': [normalize_hit(h) for h in hits] if include_hits else [],
            'error': error,
        })

        if i < len(contacts) - 1 and delay > 0:
            time.sleep(delay)

    results.sort(key=lambda x: x['total_mentions'], reverse=True)
    return results


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search")
def search(
    file: UploadFile = File(...),
    include_hits: bool = Query(True, description="Include hit previews in the response"),
    max_hits: Optional[int] = Query(None, ge=1, description="Limit hit previews per contact"),
    delay_ms: int = Query(250, ge=0, le=5000, description="Delay between API calls in ms"),
    max_contacts: Optional[int] = Query(None, ge=1, description="Limit number of contacts to scan"),
):
    try:
        ensure_requests()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="CSV file is required")

    contacts = _load_contacts_from_upload(file)

    if not contacts:
        raise HTTPException(status_code=400, detail="No connections found in CSV")

    if max_contacts is not None:
        contacts = contacts[:max_contacts]

    results = _search_contacts(contacts, delay_ms, include_hits, max_hits)
    contacts_with_mentions = len([r for r in results if r['total_mentions'] > 0])

    return {
        "summary": {
            "total_connections": len(contacts),
            "connections_with_mentions": contacts_with_mentions,
        },
        "results": results,
    }


@app.post("/report", response_class=HTMLResponse)
def report(
    file: UploadFile = File(...),
    delay_ms: int = Query(250, ge=0, le=5000, description="Delay between API calls in ms"),
    max_contacts: Optional[int] = Query(None, ge=1, description="Limit number of contacts to scan"),
):
    try:
        ensure_requests()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="CSV file is required")

    contacts = _load_contacts_from_upload(file)

    if not contacts:
        raise HTTPException(status_code=400, detail="No connections found in CSV")

    if max_contacts is not None:
        contacts = contacts[:max_contacts]

    results = _search_contacts(contacts, delay_ms, include_hits=True, max_hits=None)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        generate_html_report(results, tmp_path)
        with open(tmp_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return HTMLResponse(content=html_content)
