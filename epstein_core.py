#!/usr/bin/env python3
"""
Core utilities for searching Epstein files.
"""

import base64
import csv
import html
import os
import sys
import urllib.parse

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

API_BASE_URL = "https://analytics.dugganusa.com/api/v1/search"
PDF_BASE_URL = "https://www.justice.gov/epstein/files/"


def ensure_requests():
    if not HAS_REQUESTS:
        raise RuntimeError("'requests' library is required. Install with: pip install requests")


def parse_linkedin_contacts_stream(stream):
    """
    Parse LinkedIn connections CSV export from a text stream.
    LinkedIn exports have columns: First Name, Last Name, Email Address, Company, Position, Connected On
    """
    contacts = []

    header_line = None
    for line in stream:
        if 'First Name' in line and 'Last Name' in line:
            header_line = line
            break

    if not header_line:
        return contacts

    remaining_content = header_line + stream.read()
    reader = csv.DictReader(remaining_content.splitlines())

    for row in reader:
        first_name = (row.get('First Name') or '').strip()
        last_name = (row.get('Last Name') or '').strip()

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


def search_epstein_files(name, timeout=30):
    """
    Search the Epstein files API for a name.
    Returns the total number of hits and hit details.
    """
    ensure_requests()

    quoted_name = f'"{name}"'
    encoded_name = urllib.parse.quote(quoted_name)
    url = f"{API_BASE_URL}?q={encoded_name}&indexes=epstein_files"

    try:
        response = requests.get(url, timeout=timeout)
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


def build_pdf_url(file_path):
    if not file_path:
        return ''
    file_path = file_path.replace('dataset', 'DataSet')
    base_url = PDF_BASE_URL.rstrip('/') if file_path.startswith('/') else PDF_BASE_URL
    return base_url + urllib.parse.quote(file_path, safe='/')


def extract_hit_preview(hit):
    return hit.get('content_preview') or (hit.get('content') or '')[:500]


def normalize_hit(hit):
    file_path = hit.get('file_path', '')
    return {
        'preview': extract_hit_preview(hit),
        'file_path': file_path,
        'pdf_url': build_pdf_url(file_path)
    }


def generate_html_report(results, output_path, partial_notice=None):
    contacts_with_mentions = len([r for r in results if r['total_mentions'] > 0])

    script_dir = os.path.dirname(os.path.abspath(__file__))
    logo_path = os.path.join(script_dir, 'assets', 'logo.png')
    if os.path.exists(logo_path):
        with open(logo_path, 'rb') as f:
            logo_base64 = base64.b64encode(f.read()).decode('utf-8')
        logo_html = f'<img src="data:image/png;base64,{logo_base64}" alt="EpsteIn" class="logo">'
    else:
        logo_html = '<h1 class="logo" style="text-align: center;">EpsteIn</h1>'

    partial_notice_html = ""
    if partial_notice:
        partial_notice_html = f"""
    <div class="partial-notice">
        {html.escape(partial_notice)}
    </div>
"""

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
        .partial-notice {{
            background: #fff3cd;
            border: 1px solid #ffe69c;
            color: #664d03;
            padding: 14px 16px;
            border-radius: 8px;
            margin-bottom: 20px;
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
    {partial_notice_html}

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
                preview = extract_hit_preview(hit)
                file_path = hit.get('file_path', '')
                pdf_url = build_pdf_url(file_path) if file_path else ''

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
