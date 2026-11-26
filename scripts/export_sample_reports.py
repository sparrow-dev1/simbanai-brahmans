"""Export the existing report endpoints from a read-only demo snapshot.

No events, users, audit entries, or financial/stock records are created in the
source database. Rendered previews are internal QA artifacts, not deliverables.
"""
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cattle import create_app
from cattle.models import db, User
from sqlalchemy import select
import pypdfium2 as pdfium
from PIL import Image, ImageDraw

REPORTS = ['Herd', 'Health', 'Breeding', 'Growth', 'Movements', 'Births/deaths', 'Purchases/sales', 'Supplies', 'Finances']

def export():
    source = ROOT / 'instance' / 'cattle.db'
    if not source.exists():
        raise SystemExit('Existing demo database not found; no demonstration data will be invented.')
    initial_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    qa = ROOT / 'test-output' / 'sample-report-qa'
    qa.mkdir(parents=True, exist_ok=True)
    snapshot = qa / 'source-snapshot.sqlite'
    with sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True) as original, sqlite3.connect(snapshot) as copy:
        marker = original.execute("SELECT COUNT(*) FROM audit WHERE action LIKE 'Loaded fictional demo:%'").fetchone()[0]
        if not marker:
            raise SystemExit('This source is not marked as a fictional demo. Sample export refused.')
        original.backup(copy)
    application = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + snapshot.as_posix(),
                              'SESSION_COOKIE_SECURE': False, 'SAMPLE_REPORT_LABEL': 'Fictional demonstration records - existing demo snapshot'})
    output = ROOT / 'sample-reports'
    output.mkdir(exist_ok=True)
    with application.app_context():
        from cattle.farm_schema import upgrade_farm
        upgrade_farm()  # Disposable snapshot only; never the source database.
        application.config['FARM_SCHEMA_READY'] = True
        owner = db.session.scalar(select(User).where(User.role == 'owner', User.active.is_(True)))
        if not owner:
            raise SystemExit('An existing owner account is required for read-only report access.')
        client = application.test_client()
        # Bind a test-client session without calling login (which creates an audit entry).
        with client.session_transaction() as session:
            session.update(user_id=owner.id, version=owner.session_version, csrf='read-only-sample-export')
        overview = client.get('/api/overview').json
        exports = []
        thumbnails = []
        for name in REPORTS:
            query = urlencode({'type': 'Acquisitions/sales' if name == 'Purchases/sales' else name})
            data_response = client.get('/api/reports?' + query)
            pdf_response = client.get('/api/reports.pdf?' + query)
            if data_response.status_code != 200 or pdf_response.status_code != 200:
                raise RuntimeError(f'{name} report generation failed: {pdf_response.status_code}')
            assert pdf_response.data.startswith(b'%PDF'), name
            data = data_response.json
            filename = 'sample-' + name.replace('/', '-').lower() + '.pdf'
            target = output / filename
            target.write_bytes(pdf_response.data)
            document = pdfium.PdfDocument(str(target))
            texts = [document[i].get_textpage().get_text_range() for i in range(len(document))]
            assert 'SAMPLE' in texts[0], name
            if not data['rows']:
                assert 'No records match these filters.' in texts[0], name
            for page_index in range(len(document)):
                bitmap = document[page_index].render(scale=1.5)
                image = bitmap.to_pil().convert('RGB')
                image_path = qa / f'{filename[:-4]}-page-{page_index+1}.png'
                image.save(image_path)
                thumb = image.copy()
                thumb.thumbnail((760, 540))
                thumbnails.append((f'{name} / page {page_index+1}', thumb))
            exports.append({'report': 'Acquisitions/sales' if name == 'Purchases/sales' else name, 'filename': filename, 'rows': len(data['rows']), 'pages': len(document)})
            document.close()
    final_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if initial_hash != final_hash:
        raise RuntimeError('The source changed during export. Re-run when the demonstration database is idle.')
    generated = datetime.now(timezone(timedelta(hours=2))).strftime('%d %B %Y at %H:%M (Africa/Harare)')
    lines = ['# Sample reports - Simbanai Brahmans', '', '**Fictional demonstration records. Not real farm data.**', '',
             f'Generated: {generated}', '', 'Source: a read-only snapshot of the existing local demonstration database (`instance/cattle.db`).',
             f'The snapshot contains {overview["registered_total"]} registered cattle. No records or transactions were added to produce these samples.', '',
             'These PDFs use the application’s existing report endpoints, all stations, and all dates. Only official records are included; currencies remain separate.', '',
             '| Report | Records | Pages | Download |', '|---|---:|---:|---|']
    for item in exports:
        lines.append(f'| {item["report"]} | {item["rows"]} | {item["pages"]} | [Open PDF]({item["filename"]}) |')
    lines += ['', 'A zero-record report explicitly states that no records match. No example events were invented to fill empty reports.', '',
              'Source SHA-256 before and after export: `' + final_hash + '` (unchanged).', '']
    (output / 'README.md').write_text('\n'.join(lines), encoding='utf-8')
    (qa / 'manifest.json').write_text(json.dumps({'generated': generated, 'source_unchanged': True, 'reports': exports}, indent=2), encoding='utf-8')
    for batch in range(0, len(thumbnails), 4):
        selected = thumbnails[batch:batch+4]
        sheet = Image.new('RGB', (1580, 1160), '#D2D2D2')
        draw = ImageDraw.Draw(sheet)
        for index, (label, thumb) in enumerate(selected):
            x, y = (index % 2)*790 + 15, (index // 2)*580 + 30
            draw.text((x, y-20), label, fill='#202020')
            sheet.paste(thumb, (x, y))
        sheet.save(qa / f'contact-sheet-{batch//4+1}.png')
    print(json.dumps({'source_unchanged': True, 'output': str(output), 'reports': exports}, indent=2))

if __name__ == '__main__':
    export()
