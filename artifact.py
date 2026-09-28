"""On-demand, owner-scoped research brief. No model call or persistent duplicate."""
import io
import csv
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import research_http as http
import research_store as db


def brief_text(run):
    when = datetime.fromtimestamp(run['created'], timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lines = ['Zearch', 'A space for discovery.', '', f'Research brief · {when}', '',
             'Question', run['query'], '', 'Answer', run['answer'], '', 'Sources']
    for source in run['sources'][:8]:
        title = str(source.get('title') or 'Source').replace('\n', ' ')[:300]
        label = f"[{source['n']}] {title}"
        lines.append(label)
        if source.get('url'): lines.append(source['url'])
        else: lines.append('Private document' if source.get('document_id') else 'Private note')
        if source.get('source_version_id'): lines.append('Capture: ' + source['source_version_id'])
    lines += ['', 'Check the captured evidence in Zearch before relying on important claims.']
    return '\n'.join(lines) + '\n'


def data_json(run):
    if run.get('depth') not in ('scrape', 'crawl'):
        raise ValueError('No collected-page dataset')
    return json.dumps({'schema_version': 1, 'kind': run['depth'], 'target_url': run['target_url'],
        'question': run['query'], 'answer': run['answer'], 'run_id': run['id'],
        'pages': [{'url': s.get('url'), 'title': s.get('title'), 'description': s.get('description'),
                   'captured_at': s.get('retrieved_at'), 'source_version_id': s.get('source_version_id'),
                   'text': s.get('text'), 'assets': s.get('assets') or [], 'emails': s.get('emails') or []}
                  for s in run['sources'] if s.get('url')]}, ensure_ascii=False, indent=2).encode('utf-8')


def data_csv(run):
    """Flat inventory with source provenance and spreadsheet-safe untrusted cells."""
    if run.get('depth') not in ('scrape', 'crawl'):
        raise ValueError('No collected-page dataset')
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['type', 'page_url', 'page_title', 'value', 'label', 'captured_at', 'source_version_id'])
    def safe(value):
        value = str(value or '')
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else value
    for source in run['sources']:
        if not source.get('url'): continue
        common = [safe(source.get('url')), safe(source.get('title'))]
        tail = [safe(source.get('retrieved_at')), safe(source.get('source_version_id'))]
        writer.writerow(['page', *common, safe(source.get('description')), 'description', *tail])
        for asset in source.get('assets') or []:
            writer.writerow([safe(asset.get('kind') or 'asset'), *common,
                             safe(asset.get('url')), safe(asset.get('label')), *tail])
        for email in source.get('emails') or []:
            writer.writerow(['email', *common, safe(email), 'public contact', *tail])
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def brief_pdf(run):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    pdf.setTitle('Zearch research brief')
    pdf.setAuthor('Zearch')
    width, height = A4
    margin, y, page = 48, height - 54, 1

    def new_page():
        nonlocal y, page
        pdf.setFillColorRGB(.44, .44, .44)
        pdf.setFont('Helvetica', 8)
        pdf.drawString(margin, 30, 'Zearch · A space for discovery.')
        pdf.drawRightString(width - margin, 30, str(page))
        pdf.showPage(); page += 1; y = height - 54

    def line(value, font='Helvetica', size=10, leading=15):
        nonlocal y
        value = ''.join(ch if ch >= ' ' else ' ' for ch in value)[:4000]
        pdf.setFont(font, size)
        pdf.setFillColorRGB(.10, .10, .10)
        segments = []
        for segment in simpleSplit(value or ' ', font, size, width - 2 * margin):
            while stringWidth(segment, font, size) > width - 2 * margin:
                cut = max(1, len(segment) // 2)
                while cut > 1 and stringWidth(segment[:cut], font, size) > width - 2 * margin: cut -= 1
                segments.append(segment[:cut]); segment = segment[cut:]
            segments.append(segment)
        for segment in segments:
            if y < 65: new_page(); pdf.setFont(font, size); pdf.setFillColorRGB(.10, .10, .10)
            pdf.drawString(margin, y, segment)
            y -= leading

    def table(rows):
        nonlocal y
        columns = len(rows[0])
        if not 2 <= columns <= 8 or len(rows) > 31 or any(len(row) != columns for row in rows):
            for row in rows: line(' | '.join(row))
            return
        cell_width = (width - 2 * margin) / columns
        y -= 6
        for row_number, row in enumerate(rows):
            prepared = [simpleSplit(cell[:250], 'Helvetica-Bold' if row_number == 0 else 'Helvetica',
                                    8.5, cell_width - 16) or [''] for cell in row]
            row_height = max(len(cell) for cell in prepared) * 12 + 12
            if y - row_height < 65: new_page()
            pdf.setStrokeColorRGB(.82, .82, .82)
            pdf.line(margin, y + 5, width - margin, y + 5)
            pdf.setFillColorRGB(.12, .12, .12)
            pdf.setFont('Helvetica-Bold' if row_number == 0 else 'Helvetica', 8.5)
            for index, cells in enumerate(prepared):
                for at, value in enumerate(cells):
                    pdf.drawString(margin + index * cell_width + 5, y - 9 - at * 12, value)
            y -= row_height
        pdf.setStrokeColorRGB(.82, .82, .82)
        pdf.line(margin, y + 5, width - margin, y + 5)
        y -= 8

    line('Zearch', 'Helvetica-Bold', 23, 32)
    line('A space for discovery.', 'Helvetica', 10, 22)
    when = datetime.fromtimestamp(run['created'], timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    line('Research brief · ' + when, 'Helvetica', 9, 28)
    line('QUESTION', 'Helvetica-Bold', 9, 17)
    for row in run['query'].splitlines(): line(row)
    y -= 13
    line('ANSWER', 'Helvetica-Bold', 9, 18)
    code = False
    answer_lines = run['answer'].splitlines()
    at = 0
    while at < len(answer_lines):
        row = answer_lines[at]
        if row.startswith('```'):
            code = not code; at += 1; continue
        heading = re.match(r'^#{1,4}\s+(.+)$', row) if not code else None
        if heading:
            y -= 7; line(heading[1], 'Helvetica-Bold', 12, 19); at += 1; continue
        if not code and row.count('|') >= 2 and at + 1 < len(answer_lines) and re.fullmatch(r'[\s|:\-]+', answer_lines[at + 1]):
            cells = lambda value: [item.strip() for item in value.strip().strip('|').split('|')]
            rows = [cells(row)]; at += 2
            while at < len(answer_lines) and answer_lines[at].count('|') >= 2:
                rows.append(cells(answer_lines[at])); at += 1
            table(rows); continue
        line(row, 'Courier' if code else 'Helvetica', 8 if code else 10, 13 if code else 15)
        if not row.strip(): y -= 6
        at += 1
    y -= 12
    line('SOURCES', 'Helvetica-Bold', 9, 19)
    for source in run['sources'][:8]:
        line(f"[{source['n']}] {str(source.get('title') or 'Source')[:300]}", 'Helvetica-Bold', 9, 13)
        line(str(source.get('url') or ('Private document' if source.get('document_id') else 'Private note')), 'Helvetica', 8, 12)
        if source.get('source_version_id'): line('Capture: ' + source['source_version_id'], 'Helvetica', 7, 12)
        y -= 7
    y -= 10
    line('Check the captured evidence in Zearch before relying on important claims.', 'Helvetica', 8, 12)
    new_page()
    pdf.save()
    data = output.getvalue()
    if not data.startswith(b'%PDF-') or len(data) > 1_000_000:
        raise ValueError('Brief exceeded its size limit')
    return data


def handle(handler):
    params = parse_qs(urlsplit(handler.path).query)
    rid = params.get('id', [''])[0]
    kind = params.get('format', ['pdf'])[0]
    if not re.fullmatch(r'[a-f0-9]{32}', rid) or kind not in ('pdf', 'txt', 'json', 'csv'):
        return http.send_json(handler, 404, {'error': 'Document not found'})
    try:
        owner, _ = http.identity(handler.headers)
        run = db.get_run(owner, rid) if owner else None
        if not run or run['status'] != 'complete':
            return http.send_json(handler, 404, {'error': 'Document not found'})
        if kind in ('json', 'csv') and run.get('depth') not in ('scrape', 'crawl'):
            return http.send_json(handler, 404, {'error': 'Document not found'})
        if kind == 'pdf':
            payload, content_type = brief_pdf(run), 'application/pdf'
        elif kind == 'json':
            payload, content_type = data_json(run), 'application/json; charset=utf-8'
        elif kind == 'csv':
            payload, content_type = data_csv(run), 'text/csv; charset=utf-8'
        else:
            payload, content_type = brief_text(run).encode('utf-8'), 'text/plain; charset=utf-8'
        handler.send_response(200)
        handler.send_header('Content-Type', content_type)
        handler.send_header('Content-Length', str(len(payload)))
        handler.send_header('Content-Disposition', f'attachment; filename="zearch-{rid}.{kind}"')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.end_headers()
        handler.wfile.write(payload)
    except Exception:
        return http.send_json(handler, 503, {'error': 'Document export is temporarily unavailable'})
