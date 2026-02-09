#!/usr/bin/env python3
"""
Search Epstein files for mentions of LinkedIn connections.

Usage:
    python EpsteIn.py --connections <linkedin_csv> [--output <report.html>]

Prerequisites:
    pip install requests
"""

import argparse
import base64
import csv
import html
import os
import sys
import threading
import time
import urllib.parse

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

API_BASE_URL = "https://analytics.dugganusa.com/api/v1/search"
PDF_BASE_URL = "https://www.justice.gov/epstein/files/"

# Retry configuration
MAX_RETRIES = 5          # Maximum number of retry attempts for transient errors
MAX_BACKOFF_DELAY = 60   # Maximum seconds to wait between retries
INITIAL_RETRY_DELAY = 2  # Starting delay for exponential backoff on transient errors


def parse_linkedin_contacts(csv_path):
    """
    Parse LinkedIn connections CSV export.
    LinkedIn exports have columns: First Name, Last Name, Email Address, Company, Position, Connected On
    """
    contacts = []

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        # Skip lines until we find the header row
        # LinkedIn includes a "Notes" section at the top that must be skipped.
        header_line = None
        for line in f:
            if 'First Name' in line and 'Last Name' in line:
                header_line = line
                break

        if not header_line:
            return contacts

        # Create a reader from the header line onwards
        remaining_content = header_line + f.read()
        reader = csv.DictReader(remaining_content.splitlines())

        for row in reader:
            first_name = row.get('First Name', '').strip()
            last_name = row.get('Last Name', '').strip()

            # Remove credentials/certifications (everything after the first comma)
            if ',' in last_name:
                last_name = last_name.split(',')[0].strip()

            if first_name and last_name:
                full_name = f"{first_name} {last_name}"
                contacts.append({
                    'first_name': first_name,
                    'last_name': last_name,
                    'full_name': full_name,
                    'company': row.get('Company', ''),
                    'position': row.get('Position', '')
                })

    return contacts


def _request_with_spinner(url, timeout=30):
    """Make an HTTP GET request with a spinner animation while waiting."""
    result = {}

    def do_request():
        try:
            result['response'] = requests.get(url, timeout=timeout)
        except Exception as e:
            result['error'] = e

    thread = threading.Thread(target=do_request)
    thread.start()

    spinner = '|/-\\'
    i = 0
    while thread.is_alive():
        print(f' {spinner[i % len(spinner)]}', end='\b\b', flush=True)
        time.sleep(0.15)
        i += 1
        thread.join(timeout=0)

    print('  ', end='\b\b', flush=True)  # clear spinner

    if 'error' in result:
        raise result['error']
    return result['response']


def _countdown_sleep(seconds):
    """Sleep with a visible second-by-second countdown."""
    seconds = int(seconds)
    if seconds <= 0:
        return
    for remaining in range(seconds, 0, -1):
        print(f"{remaining}...", end='', flush=True)
        time.sleep(1)


def search_epstein_files(name, delay):
    """
    Search the Epstein files API for a name.
    Returns (result_dict, delay) where delay may be increased on 429 responses.

    Retries up to MAX_RETRIES times on transient errors (timeouts, connection
    errors, 5xx server errors, and 429 rate limits).
    """
    quoted_name = f'"{name}"'
    encoded_name = urllib.parse.quote(quoted_name)
    url = f"{API_BASE_URL}?q={encoded_name}&indexes=epstein_files"

    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = _request_with_spinner(url, timeout=30)

            # Handle 429 Rate Limiting
            if response.status_code == 429:
                if attempt >= MAX_RETRIES:
                    print(f" | HTTP 429 | FAILED after {MAX_RETRIES} retries", end='', flush=True)
                    last_error = "429 Too Many Requests"
                    break

                retry_after = response.headers.get('Retry-After')
                if retry_after:
                    try:
                        wait_time = int(retry_after)
                    except (ValueError, TypeError):
                        wait_time = min(delay * 2, MAX_BACKOFF_DELAY)
                    delay = max(delay, wait_time)
                else:
                    delay = min(delay * 2, MAX_BACKOFF_DELAY)
                    wait_time = delay

                wait_time = min(wait_time, MAX_BACKOFF_DELAY)
                retry_hdr = f"Retry-After: {retry_after}" if retry_after else f"delay={wait_time}s"
                print(f" | HTTP 429 | {retry_hdr} | attempt {attempt + 1}/{MAX_RETRIES} | waiting ", end='', flush=True)
                _countdown_sleep(wait_time)
                continue

            # Handle 5xx Server Errors
            if response.status_code >= 500:
                if attempt >= MAX_RETRIES:
                    print(f" | HTTP {response.status_code} | FAILED after {MAX_RETRIES} retries", end='', flush=True)
                    last_error = f"HTTP {response.status_code}"
                    break

                retry_delay = min(INITIAL_RETRY_DELAY * (2 ** attempt), MAX_BACKOFF_DELAY)
                print(f" | HTTP {response.status_code} | backoff={retry_delay}s | attempt {attempt + 1}/{MAX_RETRIES} | waiting ", end='', flush=True)
                _countdown_sleep(retry_delay)
                continue

            # Handle other HTTP errors (4xx except 429)
            response.raise_for_status()

            # Parse successful response
            data = response.json()

            if data.get('success'):
                if attempt > 0:
                    print(f" | recovered on attempt {attempt + 1}", end='', flush=True)
                return {
                    'total_hits': data.get('data', {}).get('totalHits', 0),
                    'hits': data.get('data', {}).get('hits', [])
                }, delay

            return {'total_hits': 0, 'hits': []}, delay

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = str(e)

            if attempt >= MAX_RETRIES:
                print(f" | {type(e).__name__} | FAILED after {MAX_RETRIES} retries", end='', flush=True)
                break

            retry_delay = min(INITIAL_RETRY_DELAY * (2 ** attempt), MAX_BACKOFF_DELAY)
            print(f" | {type(e).__name__} | backoff={retry_delay}s | attempt {attempt + 1}/{MAX_RETRIES} | waiting ", end='', flush=True)
            _countdown_sleep(retry_delay)
            continue

        except requests.exceptions.RequestException as e:
            print(f" | ERROR: {type(e).__name__}: {e}", end='', flush=True)
            return {'total_hits': 0, 'hits': [], 'error': str(e)}, delay

    # All retries exhausted
    error_msg = last_error or "max retries exhausted"
    print(f"\nWarning: API request failed for '{name}' after {MAX_RETRIES} retries: {error_msg}", file=sys.stderr)
    return {'total_hits': 0, 'hits': [], 'error': error_msg}, delay


def generate_html_report(results, output_path):
    contacts_with_mentions = len([r for r in results if r['total_mentions'] > 0])

    # Read and encode logo as base64 data URI, or fall back to text header
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logo_path = os.path.join(script_dir, 'assets', 'logo.png')
    if os.path.exists(logo_path):
        with open(logo_path, 'rb') as f:
            logo_base64 = base64.b64encode(f.read()).decode('utf-8')
        logo_html = f'<img src="data:image/png;base64,{logo_base64}" alt="EpsteIn" class="logo">'
    else:
        logo_html = '<h1 class="logo" style="text-align: center;">EpsteIn</h1>'

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EpsteIn: Which LinkedIn Connections Appear in the Epstein Files?</title>
    <style>
        * {{
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .logo {{
            display: block;
            max-width: 300px;
            margin: 0 auto 20px auto;
        }}
        .summary {{
            background: #fff;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .contact {{
            background: #fff;
            padding: 20px;
            margin-bottom: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .contact-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #eee;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }}
        .contact-name {{
            font-size: 1.4em;
            font-weight: bold;
            color: #333;
        }}
        .contact-info {{
            color: #666;
            font-size: 0.9em;
        }}
        .hit-count {{
            background: #e74c3c;
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
        }}
        .hit {{
            background: #f9f9f9;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 4px;
            border-left: 3px solid #3498db;
        }}
        .hit-preview {{
            color: #444;
            margin-bottom: 10px;
            font-size: 0.95em;
        }}
        .hit-link {{
            display: inline-block;
            color: #3498db;
            text-decoration: none;
            font-size: 0.85em;
        }}
        .hit-link:hover {{
            text-decoration: underline;
        }}
        .no-results {{
            color: #999;
            font-style: italic;
        }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            text-align: center;
            color: #666;
            font-size: 0.9em;
        }}
        .footer a {{
            color: #3498db;
            text-decoration: none;
        }}
        .footer a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    {logo_html}

    <div class="summary">
        <strong>Total connections searched:</strong> {len(results)}<br>
        <strong>Connections with mentions:</strong> {contacts_with_mentions}
    </div>
"""

    for result in results:
        if result['total_mentions'] == 0:
            continue

        contact_info = []
        if result['position']:
            contact_info.append(html.escape(result['position']))
        if result['company']:
            contact_info.append(html.escape(result['company']))

        html_content += f"""
    <div class="contact">
        <div class="contact-header">
            <div>
                <div class="contact-name">{html.escape(result['name'])}</div>
                <div class="contact-info">{' at '.join(contact_info) if contact_info else ''}</div>
            </div>
            <div class="hit-count">{result['total_mentions']:,} mentions</div>
        </div>
"""

        if result['hits']:
            for hit in result['hits']:
                preview = hit.get('content_preview') or (hit.get('content') or '')[:500]

                pdf_url = hit.get('doj_url', '')

                if not pdf_url:
                    file_path = hit.get('file_path', '')
                    if file_path:
                        file_path = file_path.replace('dataset', 'DataSet')
                        base_url = PDF_BASE_URL.rstrip('/') if file_path.startswith('/') else PDF_BASE_URL
                        pdf_url = base_url + urllib.parse.quote(file_path, safe='/')
                    else:
                        pdf_url = ''

                html_content += f"""
        <div class="hit">
            <div class="hit-preview">{html.escape(preview)}</div>
            {f'<a class="hit-link" href="{html.escape(pdf_url)}" target="_blank">View PDF: {html.escape(pdf_url)}</a>' if pdf_url else ''}
        </div>
"""
        else:
            html_content += """
        <div class="no-results">Hit details not available</div>
"""

        html_content += """
    </div>
"""

    html_content += """
    <div class="footer">
        Epstein files indexed by <a href="https://dugganusa.com" target="_blank">DugganUSA.com</a>
    </div>
</body>
</html>
"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)


def main():
    if not HAS_REQUESTS:
        print("Error: 'requests' library is required. Install with: pip install requests", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description='Search Epstein files for mentions of LinkedIn connections'
    )
    parser.add_argument(
        '--connections', '-c',
        required=False,
        help='Path to LinkedIn connections CSV export'
    )
    parser.add_argument(
        '--output', '-o',
        default='EpsteIn.html',
        help='Output HTML file for the report (default: EpsteIn.html)'
    )
    args = parser.parse_args()

    # Validate inputs
    if not args.connections:
        print("""
No connections file specified.

To export your LinkedIn connections:
  1. Go to linkedin.com and log in
  2. Click your profile icon in the top right
  3. Select "Settings & Privacy"
  4. Click "Data privacy" in the left sidebar
  5. Under "How LinkedIn uses your data", click "Get a copy of your data"
  6. Select "Connections" (or "Want something in particular?" and check Connections)
  7. Click "Request archive"
  8. Wait for LinkedIn's email (may take up to 24 hours)
  9. Download and extract the ZIP file
  10. Use the Connections.csv file with this script:

     python EpsteIn.py --connections /path/to/Connections.csv
""")
        sys.exit(1)

    if not os.path.exists(args.connections):
        print(f"Error: Connections file not found: {args.connections}", file=sys.stderr)
        sys.exit(1)

    # Parse LinkedIn connections
    print(f"Reading LinkedIn connections from: {args.connections}")
    contacts = parse_linkedin_contacts(args.connections)
    print(f"Found {len(contacts)} connections")

    if not contacts:
        print("No connections found in CSV. Check the file format.", file=sys.stderr)
        sys.exit(1)

    # Search for each contact
    print("Searching Epstein files API...")
    print("(Press Ctrl+C to stop and generate a partial report)\n")
    results = []

    delay = 0.25

    try:
        for i, contact in enumerate(contacts):
            print(f"  [{i+1}/{len(contacts)}] {contact['full_name']}", end='', flush=True)

            search_result, delay = search_epstein_files(contact['full_name'], delay)
            total_mentions = search_result['total_hits']

            print(f" -> {total_mentions} hits")

            results.append({
                'name': contact['full_name'],
                'first_name': contact['first_name'],
                'last_name': contact['last_name'],
                'company': contact['company'],
                'position': contact['position'],
                'total_mentions': total_mentions,
                'hits': search_result['hits']
            })

            # Rate limiting
            if i < len(contacts) - 1:
                time.sleep(delay)

    except KeyboardInterrupt:
        print("\n\nSearch interrupted by user (Ctrl+C).")
        if not results:
            print("No results collected yet. Exiting without generating report.")
            sys.exit(0)
        print(f"Generating partial report with {len(results)} of {len(contacts)} contacts searched...")

    # Sort by mentions (descending)
    results.sort(key=lambda x: x['total_mentions'], reverse=True)

    # Write HTML report
    print(f"\nWriting report to: {args.output}")
    generate_html_report(results, args.output)

    # Print summary
    contacts_with_mentions = [r for r in results if r['total_mentions'] > 0]
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Total connections searched: {len(results)}")
    print(f"Connections with mentions: {len(contacts_with_mentions)}")

    if contacts_with_mentions:
        print(f"\nTop mentions:")
        for r in contacts_with_mentions[:20]:
            print(f"  {r['total_mentions']:6,} - {r['name']}")
    else:
        print("\nNo connections found in the Epstein files.")

    print(f"\nFull report saved to: {args.output}")


if __name__ == '__main__':
    main()
