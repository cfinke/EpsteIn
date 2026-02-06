# EpsteIn API Design Guide

This guide describes the FastAPI service interface so a React frontend can integrate cleanly.

## Overview

The API accepts a LinkedIn `Connections.csv` file and returns search results from the Epstein files index. The service provides:

- `POST /search` for JSON results.
- `POST /report` for a full HTML report.
- `GET /health` for readiness checks.

Base URL example: `http://localhost:8000`

## CORS

The server uses CORS middleware. Configure allowed origins via the environment variable `CORS_ALLOW_ORIGINS` as a comma-separated list.

Example:

```bash
export CORS_ALLOW_ORIGINS=http://localhost:3000,https://your-app.com
```

`CORS_ALLOW_ORIGINS` is required. Wildcard `*` is rejected.

## Authentication

Bearer token authentication is required for `POST /search` and `POST /report`.

- Configure token via `API_BEARER_TOKEN`.
- Send `Authorization: Bearer <token>` with requests.
- Missing or invalid tokens return `401`.

## Rate Limiting Behavior

The API calls the upstream Epstein index per contact. The `delay_ms` query parameter adds a pause between calls to reduce upstream load and avoid throttling.

## Endpoint: `GET /health`

Purpose:

- Check server liveness and readiness.

Response:

```json
{ "status": "ok" }
```

## Endpoint: `POST /search`

Purpose:

- Parse the LinkedIn CSV and return JSON results for use in React UI.

Request:

- Method: `POST`
- Content-Type: `multipart/form-data`
- Field name: `file`
- File: LinkedIn `Connections.csv`

Query parameters:

- `include_hits` (boolean, default `true`) to include preview data per contact.
- `max_hits` (integer, optional) to limit hit previews per contact.
- `delay_ms` (integer, default `250`) delay between upstream API calls.
- `max_contacts` (integer, optional) to limit number of contacts scanned.

Example:

```bash
export API_BEARER_TOKEN=replace-with-a-long-random-secret

curl -X POST \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -F "file=@/path/to/Connections.csv" \
  "http://localhost:8000/search?include_hits=true&delay_ms=250"
```

Response shape:

```json
{
  "summary": {
    "total_connections": 123,
    "connections_with_mentions": 7
  },
  "results": [
    {
      "name": "Jane Doe",
      "first_name": "Jane",
      "last_name": "Doe",
      "company": "Example Corp",
      "position": "VP",
      "total_mentions": 2,
      "hits": [
        {
          "preview": "...",
          "file_path": "/DataSet/xxx.pdf",
          "pdf_url": "https://www.justice.gov/epstein/files/..."
        }
      ],
      "error": null
    }
  ]
}
```

Notes:

- `hits` is empty if `include_hits=false`.
- `error` is a string only if an upstream request failed for that contact.

## Endpoint: `POST /report`

Purpose:

- Generate the full HTML report and return it directly.

Request:

- Method: `POST`
- Content-Type: `multipart/form-data`
- Field name: `file`
- File: LinkedIn `Connections.csv`

Query parameters:

- `delay_ms` (integer, default `250`) delay between upstream API calls.
- `max_contacts` (integer, optional) to limit number of contacts scanned.

Example:

```bash
curl -X POST \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -F "file=@/path/to/Connections.csv" \
  "http://localhost:8000/report" \
  -o EpsteIn.html
```

Response:

- `text/html` body containing the report.

## Error Handling

The API uses standard HTTP error codes.

- `400` for invalid input or empty CSV.
- `500` for missing dependencies or server errors.

Error response example:

```json
{ "detail": "No connections found in CSV" }
```

## Frontend Integration Notes

- Use `FormData` to send the file.
- Prefer `max_contacts` for quick previews during UI development.
- Consider showing a progress indicator based on total contacts and request duration.

## Local Development

```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn api:app --reload --port 8000
```

The API auto-loads `.env` at startup. Shell environment variables still take precedence.
