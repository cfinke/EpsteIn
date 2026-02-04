#!/usr/bin/env python3
"""
Search Epstein files for mentions of LinkedIn contacts.

Usage:
    python EpsteIn.py --contacts <linkedin_csv> [--output <report.html>]

Prerequisites:
    pip install requests
"""

import argparse
import base64
import csv
import html
import os
import sys
import time
import urllib.parse

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

API_BASE_URL = "https://analytics.dugganusa.com/api/v1/search"
PDF_BASE_URL = "https://www.justice.gov/epstein/files/"


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


def search_epstein_files(name):
    """
    Search the Epstein files API for a name.
    Returns the total number of hits and hit details.
    """
    # Wrap name in quotes for exact phrase matching
    quoted_name = f'"{name}"'
    encoded_name = urllib.parse.quote(quoted_name)
    url = f"{API_BASE_URL}?q={encoded_name}&indexes=epstein_files"

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get('success'):
            return {
                'total_hits': data.get('data', {}).get('totalHits', 0),
                'hits': data.get('data', {}).get('hits', [])
            }
    except requests.exceptions.RequestException as e:
        print(f"Warning: API request failed for '{name}': {e}", file=sys.stderr)
        return {'total_hits': 0, 'hits': [], 'error': str(e)}

    return {'total_hits': 0, 'hits': []}


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
    <title>LinkedIn Contacts in Epstein Files</title>
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
        <strong>Total contacts searched:</strong> {len(results)}<br>
        <strong>Contacts with mentions:</strong> {contacts_with_mentions}
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
            {f'<a class="hit-link" href="{html.escape(pdf_url)}" target="_blank">View PDF: {html.escape(file_path)}</a>' if pdf_url else ''}
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
        description='Search Epstein files for mentions of LinkedIn contacts'
    )
    parser.add_argument(
        '--contacts', '-c',
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
    if not args.contacts:
        print("""
No contacts file specified.

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

     python EpsteIn.py --contacts /path/to/Connections.csv
""")
        sys.exit(1)

    if not os.path.exists(args.contacts):
        print(f"Error: Contacts file not found: {args.contacts}", file=sys.stderr)
        sys.exit(1)

    # Parse LinkedIn contacts
    print(f"Reading LinkedIn contacts from: {args.contacts}")
    contacts = parse_linkedin_contacts(args.contacts)
    print(f"Found {len(contacts)} contacts")

    if not contacts:
        print("No contacts found in CSV. Check the file format.", file=sys.stderr)
        sys.exit(1)

    # Search for each contact
    print("Searching Epstein files API...")
    results = []

    delay = 0.25

    for i, contact in enumerate(contacts):
        print(f"  [{i+1}/{len(contacts)}] {contact['full_name']}", end='', flush=True)

        search_result = search_epstein_files(contact['full_name'])
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
    print(f"Total contacts searched: {len(contacts)}")
    print(f"Contacts with mentions: {len(contacts_with_mentions)}")

    if contacts_with_mentions:
        print(f"\nTop mentions:")
        for r in contacts_with_mentions[:20]:
            print(f"  {r['total_mentions']:6,} - {r['name']}")
    else:
        print("\nNo contacts found in the Epstein files.")

    print(f"\nFull report saved to: {args.output}")


if __name__ == '__main__':
    main()
