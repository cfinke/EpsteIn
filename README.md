![EpsteIn](assets/logo.png)

Search the publicly released Epstein court documents for mentions of your LinkedIn connections.

## Requirements

- Python 3.6+
- `requests` library

## Setup

```bash
python3 -m venv project_venv
source project_venv/bin/activate
pip install -r requirements.txt
```

## Getting Your LinkedIn Contacts

1. Go to [linkedin.com](https://www.linkedin.com) and log in
2. Click your profile icon in the top right
3. Select **Settings & Privacy**
4. Click **Data privacy** in the left sidebar
5. Under "How LinkedIn uses your data", click **Get a copy of your data**
6. Select **Connections** (or click "Want something in particular?" and check Connections)
7. Click **Request archive**
8. Wait for LinkedIn's email (may take up to 24 hours)
9. Download and extract the ZIP file
10. Locate the `Connections.csv` file

## Usage

```bash
python EpsteIn.py --contacts /path/to/Connections.csv
```

### Options

| Flag | Description |
|------|-------------|
| `--contacts`, `-c` | Path to LinkedIn Connections.csv export (required) |
| `--output`, `-o` | Output HTML file path (default: `EpsteIn.html`) |

### Examples

Basic usage:
```bash
python EpsteIn.py --contacts ~/Downloads/Connections.csv
```

Custom output file:
```bash
python EpsteIn.py --contacts ~/Downloads/Connections.csv --output my_report.html
```

## Reading the Output

The script generates an HTML report (`EpsteIn.html` by default) that you can open in any web browser.

![A screenshot of the HTML report.](assets/screenshot.png)

The report contains:

- **Summary**: Total contacts searched and how many had mentions
- **Contact cards**: Each contact with mentions is displayed as a card showing:
  - Name, position, and company
  - Total number of mentions across all documents
  - Excerpts from each matching document
  - Links to the source PDFs on justice.gov

Contacts are sorted by number of mentions (highest first).

## Notes

- The search uses exact phrase matching on full names, so "John Smith" won't match documents that only contain "John" or "Smith" separately
- Common names may produce false positives—review the context excerpts to verify relevance
- Epstein files indexed by [DugganUSA.com](https://dugganusa.com)

