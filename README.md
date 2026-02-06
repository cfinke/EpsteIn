![EpsteIn](assets/logo.png)

Search the publicly released Epstein court documents for mentions of your LinkedIn connections.

## Requirements

- Python 3.8+
- Dependencies in `requirements.txt`
- Docker + Docker Compose (optional)

## Setup

```bash
python3 -m venv project_venv
source project_venv/bin/activate
pip install -r requirements.txt
```

## Run the API

Create a local env file first:

```bash
cp .env.example .env
```

```bash
uvicorn api:app --reload --port 8000
```

The API auto-loads `.env` at startup. Shell environment variables still take precedence.

`CORS_ALLOW_ORIGINS` must be a comma-separated list of explicit origins (wildcard `*` is rejected).

## Run with Docker

Create your env file:

```bash
cp .env.example .env
```

Build and start:

```bash
docker compose up --build
```

If your Docker install uses the legacy binary, use:

```bash
docker-compose up --build
```

The API will be available at `http://localhost:8000`.

Stop:

```bash
docker compose down
```

Legacy binary:

```bash
docker-compose down
```

## Getting Your LinkedIn Contacts

1. Go to [linkedin.com](https://www.linkedin.com) and log in
2. Click your profile icon in the top right
3. Select **Settings & Privacy**
4. Click **Data privacy** in the left sidebar
5. Under "How LinkedIn uses your data", click **Get a copy of your data**
6. Select **Connections** (or click "Want something in particular?" and check Connections). If **Connections** isn't listed as an option, choose the **Download larger data archive** option.
7. Click **Request archive**
8. Wait for LinkedIn's email (may take up to 24 hours)
9. Download and extract the ZIP file
10. Locate the `Connections.csv` file

## API (FastAPI)

### Endpoints

- `GET /health`
- `POST /search` (multipart form-data, returns JSON)
- `POST /report` (multipart form-data, returns HTML report)

`POST /search` query params:

- `include_hits` (default: `true`)
- `max_hits` (optional)
- `delay_ms` (default: `250`)
- `max_contacts` (optional)

`POST /report` query params:

- `delay_ms` (default: `250`)
- `max_contacts` (optional)

### Example (search)

```bash
curl -X POST \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -F "file=@/path/to/Connections.csv" \
  "http://localhost:8000/search?include_hits=true&delay_ms=250"
```

### Example (HTML report)

```bash
curl -X POST \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -F "file=@/path/to/Connections.csv" \
  "http://localhost:8000/report" \
  -o EpsteIn.html
```

![A screenshot of the HTML report.](assets/screenshot.png)

## Notes

- The search uses exact phrase matching on full names, so "John Smith" won't match documents that only contain "John" or "Smith" separately
- Common names may produce false positives—review the context excerpts to verify relevance
- Epstein files indexed by [DugganUSA.com](https://dugganusa.com)
