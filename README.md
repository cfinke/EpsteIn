![EpsteIn](assets/logo.png)

EpsteIn is a FastAPI service that searches publicly released Epstein court document indexes for mentions of names in a LinkedIn `Connections.csv` export.

## Requirements

- Python 3.8+
- Dependencies in `requirements.txt`
- Docker + Docker Compose (optional)

## Environment Variables

Create your env file:

```bash
cp .env.example .env
```

Required variables:

- `CORS_ALLOW_ORIGINS`: comma-separated explicit origins (wildcard `*` is rejected)
- `API_BEARER_TOKEN`: required bearer token for protected endpoints

## Run Locally

```bash
python3 -m venv project_venv
source project_venv/bin/activate
pip install -r requirements.txt
uvicorn api:app --reload --port 8000
```

The API auto-loads `.env` at startup. Shell environment variables still take precedence.

## Run with Docker

```bash
docker compose up --build
```

If your Docker install uses the legacy binary:

```bash
docker-compose up --build
```

Stop:

```bash
docker compose down
```

Legacy binary:

```bash
docker-compose down
```

## Input CSV

The API expects LinkedIn's exported `Connections.csv` file.

How to export:

1. Go to [linkedin.com](https://www.linkedin.com) and log in.
2. Open **Settings & Privacy**.
3. Open **Data privacy**.
4. Open **Get a copy of your data**.
5. Request **Connections**.
6. Download the archive and extract `Connections.csv`.

## API Endpoints

- `GET /health`
- `POST /search` (multipart form-data, returns JSON)
- `POST /report` (multipart form-data, returns HTML report)

Protected endpoints (`/search`, `/report`) require:

- Header: `Authorization: Bearer <API_BEARER_TOKEN>`

### `POST /search` query params

- `include_hits` (default: `true`)
- `max_hits` (optional)
- `delay_ms` (default: `250`)
- `max_contacts` (optional)

### `POST /report` query params

- `delay_ms` (default: `250`)
- `max_contacts` (optional)

## API Examples

Health check:

```bash
curl "http://localhost:8000/health"
```

Search:

```bash
curl -X POST \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -F "file=@/path/to/Connections.csv" \
  "http://localhost:8000/search?include_hits=true&delay_ms=250"
```

HTML report:

```bash
curl -X POST \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -F "file=@/path/to/Connections.csv" \
  "http://localhost:8000/report" \
  -o EpsteIn.html
```

![A screenshot of the HTML report.](assets/screenshot.png)

## Notes

- Search uses exact phrase matching on full names.
- Common names can produce false positives; review preview context.
- Document index source: [DugganUSA.com](https://dugganusa.com)
