"""Official-record charts and animal summaries; no forecasts or currency conversion."""
from collections import defaultdict
from datetime import date, timedelta
import calendar
from decimal import Decimal
from flask import request, jsonify, send_file, current_app
from sqlalchemy import select
from .models import db, Animal, Event, EventAnimal, Station, User, FinancialTransaction
from .service import today, valid_date, require, record_name, animal_json


def profile_summary(animal, history):
    official = [event for event in history if event.state == 'Approved']
    return dict(dipping=sum(e.kind == 'procedure' and e.payload.get('procedure') == 'Dipping' for e in official),
                vaccinations=sum(e.kind == 'procedure' and e.payload.get('procedure') == 'Vaccination' for e in official),
                pregnancy_checks=sum(e.kind == 'breeding' and e.payload.get('breeding_action') == 'Pregnancy check' for e in official),
                registered_offspring=db.session.query(Animal).filter((Animal.dam_id == animal.id) | (Animal.sire_id == animal.id)).count(),
                note='Official records only. Checks are not separate pregnancies; registered offspring are not an assumed lifetime total.')


def period_key(value, grouping):
    return value[:4] if grouping == 'years' else value[:7] if grouping == 'months' else value


def chart_range(earliest):
    start = valid_date(request.args['from'], 'From date') if request.args.get('from') else earliest or today().isoformat()
    end = valid_date(request.args['to'], 'To date') if request.args.get('to') else today().isoformat()
    require(start <= end, 'From date must precede To date.')
    grouping = request.args.get('group', 'auto')
    require(grouping in ['auto','days','months','years'], 'Choose valid grouping.')
    span = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    if grouping == 'auto':
        first = date.fromisoformat(start)
        anniversary = date(first.year + 2, first.month, min(first.day, calendar.monthrange(first.year + 2, first.month)[1]))
        grouping = 'days' if span <= 90 else 'months' if date.fromisoformat(end) < anniversary else 'years'
    require(grouping != 'days' or span <= 4000, 'Choose Auto, Months or Years for this long range.')
    return start, end, grouping


def register_farm_views(app, authenticated):
    @app.get('/api/supply-receipts')
    @authenticated('manager')
    def supply_receipts():
        from .service import event_json
        receipts = db.session.scalars(select(Event).where(Event.kind == 'stock_in', Event.state == 'Approved').order_by(Event.date.desc(), Event.created_at.desc(), Event.id))
        return jsonify(events=[event_json(event) for event in receipts])

    @app.get('/api/charts/expenses')
    @authenticated('manager','owner')
    def expenses_chart():
        currency = request.args.get('currency','USD')
        require(currency in ['USD','ZiG'], 'Choose one currency.')
        transactions = list(db.session.scalars(select(FinancialTransaction).join(Event).where(Event.state.in_(['Approved','Corrected']), FinancialTransaction.type == 'Expense', FinancialTransaction.currency == currency).order_by(FinancialTransaction.date)))
        start,end,grouping = chart_range(transactions[0].date if transactions else None)
        totals = defaultdict(Decimal)
        counts = defaultdict(int)
        selected = [t for t in transactions if start <= t.date <= end]
        for transaction in selected:
            key = period_key(transaction.date, grouping)
            totals[key] += transaction.amount
            counts[key] += 1
        if selected:
            cursor = date.fromisoformat(start)
            while cursor.isoformat() <= end:
                key = period_key(cursor.isoformat(),grouping)
                totals[key] += Decimal(0)
                if grouping == 'days':
                    cursor += timedelta(days=1)
                elif grouping == 'months':
                    cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
                else:
                    cursor = date(cursor.year + 1, 1, 1)
        return jsonify(currency=currency,unit=currency,group=grouping,filters={'from':start,'to':end},points=[dict(date=key,value=str(totals[key]),count=counts[key]) for key in sorted(totals)],total=str(sum((t.amount for t in selected),Decimal(0))),records=len(selected),note='Recorded expenses including explicit reversals. Empty data is not proof of zero spending. Currencies are separate.')

    @app.get('/api/charts/performance')
    @authenticated('manager','owner')
    def performance_chart():
        metric = request.args.get('metric')
        require(metric in ['daily_gain','births','deaths','pregnancy'], 'Choose a performance metric.')
        events = list(db.session.scalars(select(Event).where(Event.state == 'Approved').order_by(Event.date,Event.created_at,Event.id)))
        start,end,grouping = chart_range(events[0].date if events else None)
        values = defaultdict(Decimal)
        days = defaultdict(int)
        counts = defaultdict(set)
        pregnancy = {}
        weights = {}
        for event in events:
            p = event.payload
            key = period_key(event.date, grouping)
            inside = start <= event.date <= end
            if metric == 'daily_gain' and event.kind == 'weight':
                for animal_id, weight in p['weights'].items():
                    previous = weights.get(animal_id)
                    if inside and previous and previous[0] < event.date:
                        values[key] += Decimal(weight)-previous[1]
                        days[key] += (date.fromisoformat(event.date)-date.fromisoformat(previous[0])).days
                        counts[key].add(animal_id)
                    weights[animal_id] = (event.date,Decimal(weight))
            elif inside and metric == 'births' and event.kind == 'birth' and p.get('outcome') == 'Live calf':
                values[key] += 1
            elif inside and metric == 'deaths' and event.kind == 'death':
                values[key] += len(p['animal_ids'])
            elif inside and metric == 'pregnancy' and event.kind == 'breeding' and p['breeding_action'] == 'Pregnancy check':
                for animal_id in p['animal_ids']:
                    result = p.get('pregnancy_results',{}).get(str(animal_id),p)
                    pregnancy[(key,animal_id)] = result['pregnancy_result']
        if metric == 'pregnancy':
            points = []
            for key in sorted({key for key,animal_id in pregnancy}):
                results = [v for (period,animal_id),v in pregnancy.items() if period == key]
                points.append(dict(date=key,value=len(results),count=len(results),results={state:results.count(state) for state in ['Pregnant','Not pregnant','Uncertain']}))
        else:
            points = [dict(date=key,value=str((values[key]/Decimal(days[key])).quantize(Decimal('0.001'))) if metric == 'daily_gain' else str(values[key]),count=len(counts[key]) if metric == 'daily_gain' else int(values[key])) for key in sorted(values) if metric != 'daily_gain' or days[key]]
        note = 'Growth: summed weight changes divided by summed interval days, grouped by the final weighing date; paired dates must differ. Pregnancy: latest recorded result per animal in each period, not separate pregnancies or a whole-herd fertility rate.'
        return jsonify(metric=metric,unit='kg/day' if metric == 'daily_gain' else 'animals',group=grouping,filters={'from':start,'to':end},points=points,note=note)

    @app.get('/api/animals/<int:animal_id>/profile.pdf')
    @authenticated('manager','owner')
    def animal_profile_pdf(animal_id):
        from .reporting import build_pdf
        animal = db.session.get(Animal,animal_id)
        require(animal,'Animal not found.',404)
        history = list(db.session.scalars(select(Event).join(EventAnimal).where(EventAnimal.animal_id == animal_id,Event.state.in_(['Approved','Corrected'])).order_by(Event.date.desc(),Event.created_at.desc())))
        summary = profile_summary(animal,history)
        identity = animal_json(animal)
        for key in ['dam_id','sire_id']:
            parent = db.session.get(Animal,identity[key]) if identity.get(key) else None
            identity[key[:-3]] = parent.identifier if parent else 'Unknown'
            identity.pop(key,None)
        labels = [('identifier','Tag / ID'),('lifecycle','Lifecycle'),('health','Current health'),('station','Current / last-known station'),('sex','Sex'),('category','Category'),('breed','Breed'),('dob','Date of birth'),('birth_place','Birth place'),('brand','Brand'),('dam','Dam'),('sire','Sire')]
        rows = [[label,str(identity[key]) if identity.get(key) not in [None,''] else 'Unknown'] for key,label in labels]
        rows.append(['Temporary tag','Yes' if animal.temporary else 'No'])
        if identity.get('category_review_due'):
            rows.append(['Category review due',identity['category_review_due']])
        rows.extend([['Dipping records',str(summary['dipping'])],['Vaccination records',str(summary['vaccinations'])],['Pregnancy checks',str(summary['pregnancy_checks'])],['Registered offspring',str(summary['registered_offspring'])],['Summary basis',summary['note']]])
        offspring = list(db.session.scalars(select(Animal).where((Animal.dam_id == animal.id)|(Animal.sire_id == animal.id))))
        sections = [('Identity and recorded totals',['Field','Value'],rows),('Registered offspring',['Tag','Sex','Birth date'],[[a.identifier,a.sex,a.dob or 'Unknown'] for a in offspring]),('Chronological history',['Date','Record','State','Details'],[[e.date,record_name(e),e.state,profile_event_details(e, animal.id)] for e in history])]
        from .models import Audit
        changes = [a for a in db.session.scalars(select(Audit).order_by(Audit.at.desc())) if a.details.get('original',{}).get('id') == animal.id]
        sections.append(('Identity and category history',['When','Change','Original / replacement'],[[a.at,a.action,readable_identity_change(a)] for a in changes]))
        data = dict(type='Animal profile - '+animal.identifier,columns=[],rows=[],filters={'animal':animal.identifier},sections=sections)
        return send_file(build_pdf(data, sample_label=current_app.config.get('SAMPLE_REPORT_LABEL')),mimetype='application/pdf',as_attachment=request.args.get('inline') != '1',download_name='simbanai-profile-'+str(animal.id)+'.pdf')


def profile_event_details(event, animal_id=None):
    from .service import animal_json
    p = event.payload
    station = db.session.get(Station,event.station_id) if event.station_id else None
    parts = ['Station: '+station.name] if station else []
    for key in ['next_due','observation','cause','notes','procedure','outcome','breeding_action','expected_calving','estimate_basis','destination_id','acquisition_source','reference','amount','currency']:
        if p.get(key) is not None and p.get(key) != '':
            value = p[key]
            if key == 'destination_id':
                value = db.session.get(Station, value).name
            parts.append(key.replace('_',' ').title()+': '+str(value))
    if p.get('weights'):
        parts.append('Weights (kg): '+', '.join(f'{db.session.get(Animal,int(i)).identifier}: {w}' for i,w in p['weights'].items() if animal_id is None or int(i)==animal_id))
    for item in p.get('products',[]):
        from .models import Product
        product=db.session.get(Product,item['product_id'])
        parts.append(f"{product.name}: {item.get('entered_quantity',item['quantity'])} {item.get('entered_unit',product.unit)}; session stock quantity {item['quantity']} {product.unit}; dosage {item.get('dosage') or 'not recorded'}; source {item.get('source_note') or 'Farm stock'}")
    selected_animal=animal_id
    for animal_id,result in p.get('pregnancy_results',{}).items():
        if selected_animal is None or int(animal_id)==selected_animal:
            parts.append(db.session.get(Animal,int(animal_id)).identifier+': '+', '.join(str(v) for v in result.values() if v))
    for row in p.get('purchase_rows',[]):
        if selected_animal is None or not row.get('animal_id') or row['animal_id']==selected_animal:
            parts.append(row['identifier']+(': Gift - no expense' if p.get('acquisition_source')=='Gift' else ': '+str(row['price'])+' '+str(p.get('currency') or 'Not recorded')))
    return '; '.join(parts) or 'No additional details recorded.'


def readable_identity_change(change):
    before = change.details.get('original', {})
    after = change.details.get('corrected', {})
    differences = [f"{key.replace('_', ' ').title()}: {before.get(key, 'Unknown')} -> {value}" for key, value in after.items() if before.get(key) != value]
    author = db.session.get(User, change.user_id) if getattr(change, 'user_id', None) else None
    return '; '.join(differences + ['Reason: ' + str(change.details.get('reason', 'Not recorded')), 'Author: ' + (author.name if author else 'See activity history')])
