"""Shared letterheaded, searchable PDF reports and animal profiles."""
import io
from pathlib import Path
from xml.sax.saxutils import escape
from datetime import datetime,timedelta,timezone
from PIL import Image
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,Spacer,KeepTogether
from .models import now

ASSET=Path(__file__).resolve().parents[1]/'static'/'report-letterhead.png'
PORTRAIT={'Growth','Births/deaths'}

def letterhead_parts():
    with Image.open(ASSET) as image:
        image=image.convert('RGB');w,h=image.size
        return (ImageReader(image.crop((0,0,w,230))),ImageReader(image.crop((0,230,w,h-70))),ImageReader(image.crop((0,h-70,w,h))),w,h)

def build_pdf(data,sample_label=None):
    portrait=data['type'] in PORTRAIT or data['type'].startswith('Animal profile')
    size=A4 if portrait else landscape(A4)
    width,height=size
    header,watermark,footer,source_w,source_h=letterhead_parts()
    header_h=(width-48)*230/source_w
    buffer=io.BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=size,leftMargin=30,rightMargin=30,topMargin=header_h+34,bottomMargin=65,title='Simbanai Brahmans - '+data['type'],author='Simbanai Brahmans')
    font='Helvetica'
    tahoma=Path('C:/Windows/Fonts/tahoma.ttf')
    if tahoma.exists():
        if 'ReportTahoma' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('ReportTahoma',str(tahoma)))
        font='ReportTahoma'
    styles=getSampleStyleSheet()
    for name in ['Normal','Heading1','Heading2','Heading3']:
        styles[name].fontName=font
    styles['Normal'].fontSize=9;styles['Normal'].leading=12
    styles['Heading2'].keepWithNext=True;styles['Heading3'].keepWithNext=True
    styles.add(ParagraphStyle(name='Cell',parent=styles['Normal'],fontSize=8.5,leading=11,wordWrap='CJK'))
    generated=datetime.fromisoformat(data.get('generated_at') or now()).astimezone(timezone(timedelta(hours=2))).strftime('%d %b %Y, %H:%M')
    elements=[Paragraph(escape(data['type']),styles['Heading1'])]
    if sample_label:elements.append(Paragraph('SAMPLE - '+escape(sample_label),styles['Heading3']))
    filters=' | '.join(f'{k}: {v}' for k,v in data.get('filters',{}).items() if v) or 'All stations | All dates'
    elements.extend([Paragraph(escape(filters)+'<br/>Official records | Africa/Harare | Generated '+generated,styles['Normal']),Spacer(1,10)])
    if data.get('summary'):
        elements.append(Paragraph(escape(data['summary']),styles['Normal']));elements.append(Spacer(1,8))
    sections=data.get('sections') or [(data['type']+' records',data['columns'],data['rows'])]
    for title,columns,rows in sections:
        if not rows:
            elements.append(KeepTogether([Paragraph(escape(title),styles['Heading2']),Paragraph('No records match these filters.',styles['Normal'])]));continue
        display_rows = [list(row) for row in rows]
        if 'Participating cattle' in columns:
            column = columns.index('Participating cattle')
            for row in display_rows:
                count = len([value for value in str(row[column]).split(', ') if value])
                row[column] = f'{count} cattle; full IDs in appendix'
        content=[[Paragraph(escape(str(value)),styles['Cell']) for value in row] for row in [columns]+display_rows]
        content.insert(0,[Paragraph(escape(title),styles['Heading2'])]+['']*(len(columns)-1))
        ratios=[1/len(columns)]*len(columns)
        if len(columns)==2:ratios=[.30,.70]
        elif len(columns)==6:ratios=[.10,.12,.12,.24,.34,.08]
        elif len(columns)==4:ratios=[.15,.20,.13,.52] if portrait and 'profile' in data['type'] else [.20,.35,.25,.20]
        table=Table(content,colWidths=[doc.width*r for r in ratios],repeatRows=2,splitInRow=1,hAlign='LEFT')
        table.setStyle(TableStyle([('SPAN',(0,0),(-1,0)),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#F5F5F5')),('BACKGROUND',(0,1),(-1,1),colors.HexColor('#DDEED8')),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#808080')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        elements.extend([table,Spacer(1,12)])
    # Every participant remains readable in an ID grid, even for long sessions.
    groups = data.get('participant_groups', [])
    if groups:
        elements.append(Paragraph('Participating cattle appendix', styles['Heading2']))
    for group in groups:
        elements.append(Paragraph(escape(group['title']), styles['Heading3']))
        for label, identifiers in [('Participating', group['ids']), ('Recorded absent', group['absent'])]:
            if not identifiers:
                continue
            elements.append(Paragraph(f'{label}: {len(identifiers)}', styles['Normal']))
            cells = [Paragraph(escape(identifier), styles['Cell']) for identifier in identifiers]
            per_row = 3 if portrait else 5
            grid_rows = [cells[i:i+per_row]+['']*((per_row-len(cells[i:i+per_row]))%per_row) for i in range(0,len(cells),per_row)]
            grid_rows.insert(0,[Paragraph(escape(group['title']+' - '+label),styles['Cell'])]+['']*(per_row-1))
            grid = Table(grid_rows,colWidths=[doc.width/per_row]*per_row,splitInRow=1,repeatRows=1)
            grid.setStyle(TableStyle([('SPAN',(0,0),(-1,0)),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#DDEED8')),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#808080')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
            elements.extend([grid,Spacer(1,10)])
    def page(canvas,document):
        canvas.saveState()
        canvas.drawImage(header,24,height-header_h-14,width=width-48,height=header_h,mask='auto')
        available=height-doc.topMargin-doc.bottomMargin
        scale=min((width-60)/source_w,available/(source_h-300))
        mark_w=source_w*scale;mark_h=(source_h-300)*scale
        canvas.drawImage(watermark,(width-mark_w)/2,doc.bottomMargin+(available-mark_h)/2,width=mark_w,height=mark_h,mask='auto')
        footer_h=(width-48)*70/source_w
        canvas.drawImage(footer,24,14,width=width-48,height=footer_h,mask='auto')
        canvas.setFillColor(colors.HexColor('#404040'));canvas.setFont(font,8)
        canvas.drawString(30,12,'SAMPLE - Fictional demonstration records' if sample_label else 'Simbanai Brahmans | Official records')
        canvas.drawRightString(width-30,12,f'Page {document.page}')
        canvas.restoreState()
    while elements and isinstance(elements[-1],Spacer):
        elements.pop()
    doc.build(elements,onFirstPage=page,onLaterPages=page)
    buffer.seek(0)
    return buffer


def report_summary(report, columns, rows):
    from collections import Counter, defaultdict
    from decimal import Decimal
    notes = [f'{len(rows)} official record rows.']
    if report == 'Herd':
        counts = Counter(row[columns.index('Lifecycle')] for row in rows)
        notes.append('Registered cattle: '+', '.join(f'{state} {counts[state]}' for state in ['Active','Sold','Dead','Lost'])+'.')
    elif report == 'Finances':
        for currency in ['USD','ZiG']:
            income=sum((Decimal(row[3]) for row in rows if row[4]==currency and row[1]=='Income'),Decimal(0))
            expense=sum((Decimal(row[3]) for row in rows if row[4]==currency and row[1]=='Expense'),Decimal(0))
            notes.append(f'{currency}: recorded income {income}; expenses {expense}; net {income-expense} (includes explicit reversals).')
    elif report == 'Supplies':
        totals=defaultdict(Decimal)
        for row in rows:totals[(row[1],row[4])]+=Decimal(row[3])
        notes.append('Net stock movements in selected period (not necessarily current balances): '+('; '.join(f'{name}: {quantity} {unit}' for (name,unit),quantity in totals.items()) or 'none')+'.')
    elif report == 'Growth':
        notes.append(f'{len(set(row[1] for row in rows))} cattle with recorded measurements in this selection. Weight unit: kg; no growth estimate without paired dated weights.')
    elif 'Record' in columns:
        counts=Counter(row[columns.index('Record')] for row in rows)
        notes.append('Sessions: '+('; '.join(f'{name}: {count}' for name,count in sorted(counts.items())) or 'none')+'. Session counts are not individual animal counts.')
    notes.append('Unknown historical details are not inferred. Currencies and product units remain separate.')
    return ' '.join(notes)
