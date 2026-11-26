import uuid
from hashlib import sha256
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import select, func
from flask import current_app, g, has_request_context
from itsdangerous import URLSafeSerializer, BadData
from .models import db, Animal, Station, Product, Event, EventAnimal, StockTransaction, FinancialTransaction, HealthCase, Audit, User, UserStation, FarmSetting, now

KINDS = ['procedure', 'weight', 'health', 'treatment', 'resolve_health', 'movement', 'birth', 'death', 'breeding', 'purchase', 'sale', 'stock_in', 'stock_use', 'expense', 'income', 'lost', 'found']
FIELD_KINDS = ['procedure', 'weight', 'health', 'treatment', 'movement', 'birth', 'death', 'lost', 'found']
CATEGORIES = ['Calf', 'Heifer', 'Cow', 'Bull', 'Steer']
PROCEDURES = ['Dipping', 'Deworming', 'Vaccination', 'Other authorised procedure']
UNITS = ['L', 'mL', 'kg', 'g', 'dose', 'bag', 'unit']
FINANCE_CATEGORIES = ['Medicine', 'Feed', 'Fuel', 'Veterinary', 'Transport', 'Other cattle expense', 'Other cattle income']

class RuleError(Exception):
    def __init__(self, message, status=422):
        self.message, self.status = message, status

def require(condition, message, status=422):
    if not condition:
        raise RuleError(message, status)

def today():
    return datetime.now(timezone(timedelta(hours=2))).date()

def valid_date(value, label='Date'):
    try:
        parsed = date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise RuleError(f'{label} must be a valid date.')
    require(parsed <= today(), f'{label} cannot be in the future.')
    return parsed.isoformat()

def number(value, label, allow_zero=False, precision=3):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise RuleError(f'{label} must be a number.')
    require(amount.is_finite() and amount < Decimal('1000000000') and (amount >= 0 if allow_zero else amount > 0), f'{label} must be {"zero or " if allow_zero else ""}greater than zero and below one billion.')
    require(amount == amount.quantize(Decimal(10) ** -precision), f'{label} supports at most {precision} decimal places.')
    return amount

def integer(value, label):
    try:
        result = int(value)
        require(str(result) == str(value), f'{label} is invalid.')
        return result
    except (ValueError, TypeError):
        raise RuleError(f'{label} is required.')

def text(value, label, required=False, limit=1000):
    require(value is None or isinstance(value, str), f'{label} must be text.')
    value = str(value or '').strip()
    require(not required or bool(value), f'{label} is required.')
    require(len(value) <= limit, f'{label} is too long (maximum {limit} characters).')
    return value

def audit(user, action, event=None, details=None):
    db.session.add(Audit(user_id=user.id if user else None, action=action, event_id=event.id if event else None, details=details or {}))

def stock_balance(product_id):
    return db.session.scalar(select(func.coalesce(func.sum(StockTransaction.quantity), 0)).where(StockTransaction.product_id == product_id)) or Decimal(0)

def animal_json(animal):
    station = db.session.get(Station, animal.station_id)
    return dict(id=animal.id, identifier=animal.identifier, temporary=animal.temporary,
                brand=animal.brand, sex=animal.sex, category=animal.category, breed=animal.breed,
                dob=animal.dob, birth_place=animal.birth_place, dam_id=animal.dam_id, sire_id=animal.sire_id,
                station_id=animal.station_id, station=station.name if station else '',
                lifecycle=animal.lifecycle, health=animal.health, version=animal.version, attention=attention_for(animal), category_review_due=category_review_due(animal))

def event_json(event, include_finance=True):
    from .models import User
    author = db.session.get(User, event.author_id)
    reviewer = db.session.get(User, event.reviewer_id) if event.reviewer_id else None
    return dict(id=event.id, name=record_name(event), kind=event.kind, date=event.date, station_id=event.station_id,
                payload=event.payload, state=event.state, author=author.name, author_id=event.author_id,
                reviewer=reviewer.name if reviewer else None, reviewed_at=event.reviewed_at,
                created_at=event.created_at, reason=event.reason, revision=event.revision, replaces_id=event.replaces_id, conflicts=proposal_conflicts(event))

def creation_animal(event):
    root = event
    while root.replaces_id:
        root = db.session.get(Event, root.replaces_id)
    created = next((effect for effect in root.effects if effect.get('created') and effect['model'] == 'Animal'), None)
    require(created, 'The original animal registration is missing.', 409)
    return db.session.get(Animal, created['id'])

def normalize(payload, user, identity_exception_id=None):
    require(isinstance(payload, dict), 'Submission must be an object.')
    p = dict(payload)
    kind = p.get('kind')
    require(kind in KINDS, 'Choose a supported event type.')
    if user.role == 'hand':
        require(kind in FIELD_KINDS, 'You cannot record this event type.', 403)
    p['date'] = valid_date(p.get('date'))
    p['notes'] = text(p.get('notes'), 'Notes', limit=3000)
    if kind not in ['expense', 'income']:
        p['station_id'] = integer(p.get('station_id'), 'Station')
        require(db.session.get(Station, p['station_id']), 'Choose an existing station.')
        if user.role == 'hand':
            require(p['station_id'] in user_station_ids(user), 'Only your assigned station is available.', 403)
    else:
        p['station_id'] = None
    raw_ids = p.get('animal_ids', [])
    require(isinstance(raw_ids, list), 'Cattle selection is invalid.')
    p['animal_ids'] = [integer(i, 'Animal') for i in raw_ids]
    require(len(p['animal_ids']) == len(set(p['animal_ids'])), 'A cattle selection contains duplicates.')
    if kind in ['procedure', 'weight', 'health', 'treatment', 'resolve_health', 'movement', 'death', 'breeding', 'sale', 'lost', 'found']:
        require(p['animal_ids'], 'Select at least one animal.')
    else:
        require(not p['animal_ids'], 'This event does not take an existing cattle selection.')
    if kind in ['health', 'treatment', 'resolve_health', 'death', 'lost', 'found']:
        require(len(p['animal_ids']) == 1, 'Select one animal for this event.')
    versions = p.get('versions', {})
    require(isinstance(versions, dict), 'Cattle versions are invalid.')
    p['versions'] = versions
    p['products'] = p.get('products', [])
    require(isinstance(p['products'], list), 'Products must be a list.')
    require(len(p['products']) <= 50, 'Too many products in one event.')
    normalized_products = []
    for item in p['products']:
        require(isinstance(item, dict), 'Product entry is invalid.')
        product_id = integer(item.get('product_id'), 'Product')
        require(db.session.get(Product, product_id), 'Choose an existing product.')
        product = db.session.get(Product, product_id)
        entered_unit = item.get('entered_unit') or item.get('unit') or product.unit
        entered_quantity = item.get('entered_quantity', item.get('quantity'))
        quantity = convert_quantity(entered_quantity, entered_unit, product.unit)
        source = item.get('source') or 'Farm stock'
        require(source in ['Farm stock', 'Outside source'], 'Choose medicine source.')
        source_note = text(item.get('source_note'), 'Outside source', required=source == 'Outside source', limit=180)
        normalized_products.append(dict(product_id=product_id, quantity=str(quantity),
                                        entered_quantity=str(number(entered_quantity, 'Quantity')), entered_unit=entered_unit,
                                        source=source, source_note=source_note, receipt_id=(text(item.get('receipt_id'), 'Receipt ID', limit=36) or None) if source == 'Outside source' else None,
                                        dosage=text(item.get('dosage'), 'Dosage / concentration', limit=180)))
    p['products'] = normalized_products
    if kind in ['stock_in', 'stock_use', 'treatment']:
        require(p['products'], 'Select at least one product and quantity.')
    elif kind != 'procedure':
        require(not p['products'], 'Products are not applicable to this event.')
    if kind == 'procedure':
        require(p.get('procedure') in PROCEDURES, 'Choose a procedure.')
        if p['procedure'] != 'Other authorised procedure':
            require(p['products'], 'Select the products and quantities used.')
        require(isinstance(p.get('absent_ids', []), list), 'Absent cattle must be a list.')
        p['absent_ids'] = [integer(i, 'Absent animal') for i in p.get('absent_ids', [])]
        require(len(set(p['absent_ids'])) == len(p['absent_ids']), 'Absent cattle contain duplicates.')
        require(not set(p['absent_ids']) & set(p['animal_ids']), 'An animal cannot be both present and absent.')
        require(p.get('next_due') is None or isinstance(p['next_due'], str), 'Next due date must be a date.')
        p['next_due'] = p.get('next_due') or None
        if p['next_due']:
            try:
                require(date.fromisoformat(p['next_due']) > date.fromisoformat(p['date']), 'Next due date must be after the procedure.')
            except (ValueError, TypeError):
                raise RuleError('Next due date is invalid.')
    if kind == 'weight':
        weights = p.get('weights', {})
        require(isinstance(weights, dict), 'Weight entries are invalid.')
        require(set(weights) == {str(i) for i in p['animal_ids']}, 'Enter one weight for each selected animal.')
        p['weights'] = {str(i): str(number(weights.get(str(i)), 'Weight')) for i in p['animal_ids']}
        require(all(Decimal(w) < 3000 for w in p['weights'].values()), 'A weight must be below 3,000 kg.')
    if kind == 'movement':
        p['destination_id'] = integer(p.get('destination_id'), 'Destination')
        require(p['destination_id'] != p['station_id'], 'Source and destination must differ.')
        require(db.session.get(Station, p['destination_id']), 'Choose an existing destination.')
        require(p.get('movement_reason') in ['Grazing', 'Breeding', 'Treatment', 'Station transfer', 'Other'], 'Choose a movement reason.')
    if kind == 'purchase' and 'acquisition_source' in p:
        require(p['acquisition_source'] in ['Purchase', 'Gift'], 'Choose Purchase or Gift.')
        p['reference'] = text(p.get('reference'), 'Supplier / donor / source', required=True, limit=180)
    if kind == 'purchase' and 'purchase_rows' in p:
        rows = p['purchase_rows']
        require(isinstance(rows, list) and 0 < len(rows) <= 500, 'Enter between one and 500 purchased cattle.')
        normalized = []
        for row in rows:
            require(isinstance(row, dict), 'Purchased animal must be an object.')
            row = dict(row)
            if row.get('animal_id') is not None:
                row['animal_id'] = integer(row['animal_id'], 'Purchased animal ID')
            row_payload = {**p, **{k: row.get(k) for k in ['identifier','sex','category','dob','breed','brand','birth_place','dam_id','sire_id']}, 'amount': ('0' if p.get('acquisition_source') == 'Gift' else row.get('price')), 'animal_ids': []}
            row_payload.pop('purchase_rows', None)
            entry = normalize(row_payload, user, row.get('animal_id') if identity_exception_id else None)
            normalized.append({k: entry.get(k) for k in ['identifier','sex','category','dob','breed','brand','birth_place','dam_id','sire_id']} | {'price': entry['amount'], 'animal_id': row.get('animal_id')})
        require(len({r['identifier'] for r in normalized}) == len(normalized), 'Purchase tags must be unique within the invoice.')
        p['purchase_rows'] = normalized
        p['amount'] = str(sum(Decimal(r['price']) for r in normalized))
    if kind in ['birth', 'purchase'] and not p.get('purchase_rows'):
        p['identifier'] = text(p.get('identifier'), 'Tag', limit=80).upper()
        require(p['identifier'] or kind == 'birth', 'A purchased animal requires a tag.')
        if p['identifier'] and user.role != 'hand':
            require(not db.session.scalar(select(Animal).where(Animal.identifier == p['identifier'], Animal.id != identity_exception_id if identity_exception_id else True)), f'Tag {p["identifier"]} already belongs to another animal.', 409)
        require(p.get('sex') in ['Female', 'Male'], 'Choose the sex.')
        if kind == 'birth':
            p['category'] = 'Calf'
            p['dob'] = p['date']
            require(p.get('outcome') in ['Live calf', 'Stillborn'], 'Choose the calving outcome.')
            p['dam_id'] = integer(p.get('dam_id'), 'Dam')
        else:
            require(p.get('category') in CATEGORIES, 'Choose a cattle category.')
            validate_category(p['sex'], p['category'])
            p['dob'] = valid_date(p['dob'], 'Birth date') if p.get('dob') else None
            require(not p['dob'] or p['dob'] <= p['date'], 'Birth date cannot follow the purchase date.')
        p['breed'] = text(p.get('breed') or 'Brahman', 'Breed', limit=80)
        p['brand'] = text(p.get('brand'), 'Brand', limit=80)
        p['birth_place'] = text(p.get('birth_place'), 'Birth place', limit=120)
        for field in ['dam_id', 'sire_id']:
            if p.get(field):
                p[field] = integer(p[field], field)
                parent = db.session.get(Animal, p[field])
                require(parent and parent.sex == ('Female' if field == 'dam_id' else 'Male'), f'Choose a valid {field[:-3]}.')
                require(not parent.dob or parent.dob < (p.get('dob') or p['date']), 'Parent birth date must precede the calf birth date.')
    if kind == 'health':
        p['observation'] = text(p.get('observation'), 'Observation', required=True, limit=3000)
    if kind in ['treatment', 'resolve_health']:
        p['case_id'] = integer(p.get('case_id'), 'Health case')
    if kind in ['lost', 'found']:
        p['lifecycle_reason'] = text(p.get('lifecycle_reason'), 'Reason', required=True, limit=1000)
        if kind == 'found':
            p['found_station_id'] = integer(p.get('found_station_id') or p['station_id'], 'Found station')
            require(db.session.get(Station, p['found_station_id']), 'Choose an existing found station.')
            require(user.role != 'hand' or p['found_station_id'] in user_station_ids(user), 'Only your assigned station is available.', 403)
    if kind == 'death':
        p['cause'] = text(p.get('cause'), 'Suspected cause', required=True, limit=500)
        p['carcass'] = text(p.get('carcass'), 'Carcass information', limit=500)
    if kind == 'breeding':
        require(p.get('breeding_action') in ['Bull exposure', 'Pregnancy check'], 'Choose a breeding action.')
        if p['breeding_action'] == 'Bull exposure':
            require(all(p.get(key) is None or p.get(key) == '' for key in ['pregnancy_results', 'pregnancy_result', 'expected_calving', 'estimate_basis']), 'Bull exposure cannot contain pregnancy-check results or calving estimates.')
            p['sire_id'] = integer(p.get('sire_id'), 'Bull')
    if kind == 'breeding' and p.get('breeding_action') == 'Pregnancy check' and 'pregnancy_results' in p:
        results = p['pregnancy_results']
        require(isinstance(results, dict) and set(results) == {str(i) for i in p['animal_ids']}, 'Enter one pregnancy result for each animal.')
        p['pregnancy_results'] = {}
        for animal_id, result in results.items():
            require(isinstance(result, dict), 'Pregnancy result must be an object.')
            one = {**p, **{k: result.get(k) for k in ['pregnancy_result','expected_calving','estimate_basis']}, 'animal_ids': [int(animal_id)]}
            one.pop('pregnancy_results', None)
            checked = normalize(one, user)
            p['pregnancy_results'][animal_id] = {k: checked.get(k) for k in ['pregnancy_result', 'expected_calving', 'estimate_basis']}
        for key in ['pregnancy_result', 'expected_calving', 'estimate_basis']:
            p.pop(key, None)
    if kind == 'breeding' and not p.get('pregnancy_results'):
        require(p.get('breeding_action') in ['Bull exposure', 'Pregnancy check'], 'Choose a breeding action.')
        if p['breeding_action'] == 'Bull exposure':
            p['sire_id'] = integer(p.get('sire_id'), 'Bull')
        else:
            require(p.get('pregnancy_result') in ['Pregnant', 'Not pregnant', 'Uncertain'], 'Choose a pregnancy result.')
        require(p.get('expected_calving') is None or isinstance(p['expected_calving'], str), 'Estimated calving date must be a date.')
        p['expected_calving'] = p.get('expected_calving') or None
        if p['expected_calving']:
            require(p['breeding_action'] == 'Pregnancy check' and p['pregnancy_result'] == 'Pregnant', 'A calving estimate requires a pregnant check result.')
            try:
                require(date.fromisoformat(p['expected_calving']) > date.fromisoformat(p['date']), 'Estimated calving must follow the check date.')
            except (ValueError, TypeError):
                raise RuleError('Estimated calving date is invalid.')
            p['estimate_basis'] = text(p.get('estimate_basis'), 'Estimate basis', required=True, limit=500)
    if kind in ['sale', 'purchase', 'stock_in', 'expense', 'income']:
        if kind == 'stock_in':
            require(p.get('receipt_type') in ['Purchase', 'Opening balance', 'External supply'], 'Choose receipt type.')
        if kind == 'purchase' and p.get('acquisition_source') == 'Gift':
            p['amount'] = '0'
            p['currency'] = None
        elif kind != 'stock_in' or p['receipt_type'] == 'Purchase':
            require(p.get('currency') in ['USD', 'ZiG'], 'Choose USD or ZiG.')
            p['amount'] = str(number(p.get('amount'), 'Total amount', allow_zero=kind in ['purchase', 'sale'], precision=2))
        else:
            p['amount'] = '0'
            p['currency'] = None
        p['reference'] = text(p.get('reference'), 'Buyer / supplier / reference', required=(kind == 'stock_in' and p['receipt_type'] == 'External supply'), limit=180)
        if kind == 'purchase' and p.get('acquisition_source') == 'Purchase':
            require(Decimal(p['amount']) > 0, 'A Purchase needs a positive price. Choose Gift for a free animal.')
        if kind in ['expense', 'income']:
            require(p.get('finance_category') in FINANCE_CATEGORIES, 'Choose a financial category.')
        if kind == 'stock_in':
            categories = {db.session.get(Product, x['product_id']).category for x in p['products']}
            require(len(categories) == 1, 'Receive one supply category per receipt so the expense category stays accurate.')
    return p

def validate_current(p, user, check_versions=True):
    animals = []
    for animal_id in sorted(p['animal_ids']):
        animal = db.session.scalar(select(Animal).where(Animal.id == animal_id).with_for_update())
        require(animal, 'An animal no longer exists.', 409)
        require(animal.lifecycle == ('Lost' if p['kind'] == 'found' else 'Active'), f'{animal.identifier} is {animal.lifecycle}; this event cannot be applied.', 409)
        require(animal.station_id == p['station_id'], f'{animal.identifier} is no longer at the selected station. Manager review is required.', 409)
        require(not animal.dob or animal.dob <= p['date'], f'{animal.identifier}: event date is before birth.')
        if check_versions:
            require(str(p['versions'].get(str(animal.id))) == str(animal.version), f'{animal.identifier} changed since capture. Refresh cattle and review the session.', 409)
        later = db.session.scalar(select(Event.id).join(EventAnimal, Event.id == EventAnimal.event_id).where(EventAnimal.animal_id == animal.id, Event.state == 'Approved', Event.date > p['date']).limit(1))
        require(not later, f'{animal.identifier} has a later official event. Use a controlled correction or enter events in date order.', 409)
        animals.append(animal)
    for absent_id in p.get('absent_ids', []):
        absent = db.session.get(Animal, absent_id)
        require(absent and absent.station_id == p['station_id'], 'An absent animal is not at this station.', 409)
    if p['kind'] == 'movement' and any(a.health != 'No concerns' for a in animals):
        require(p.get('acknowledge_health') is True, 'Some selected cattle have health concerns. Acknowledge the movement warning.')
    if p['kind'] == 'birth':
        dam = db.session.scalar(select(Animal).where(Animal.id == p['dam_id']).with_for_update())
        require(dam and dam.sex == 'Female' and dam.lifecycle == 'Active' and dam.station_id == p['station_id'], 'The dam must be active at the selected station.', 409)
        if check_versions:
            require(str(p['versions'].get(str(dam.id))) == str(dam.version), 'The dam changed since capture. Refresh and review the birth.', 409)
        later = db.session.scalar(select(Event.id).join(EventAnimal).where(EventAnimal.animal_id == dam.id, Event.state == 'Approved', Event.date > p['date']).limit(1))
        require(not later, 'The dam has a later official event. Review the birth date.', 409)
    if p['kind'] == 'breeding':
        require(all(a.sex == 'Female' and a.category in ['Cow', 'Heifer'] for a in animals), 'Breeding records require a cow or heifer.')
        if p['breeding_action'] == 'Bull exposure':
            sire = db.session.scalar(select(Animal).where(Animal.id == p['sire_id']).with_for_update())
            require(sire and sire.sex == 'Male' and sire.category == 'Bull' and sire.lifecycle == 'Active' and sire.station_id == p['station_id'], 'Choose an active bull.')
    if p['kind'] in ['treatment', 'resolve_health']:
        case = db.session.scalar(select(HealthCase).where(HealthCase.id == p['case_id']).with_for_update())
        require(case and case.animal_id == animals[0].id and not case.closed_at, 'Select an open health case for this animal.', 409)
        require(p['date'] >= db.session.get(Event, case.event_id).date, 'Treatment or resolution cannot precede the observation.')
    quantities = defaultdict(Decimal)
    for item in p['products']:
        quantities[item['product_id']] += Decimal(item['quantity'])
    for product_id in sorted(quantities):
        product = db.session.scalar(select(Product).where(Product.id == product_id).with_for_update())
        require(product, 'Product no longer exists.', 409)
        require(product.active, f'{product.name} is archived. The Manager must restore it before approving usage or receipts.', 409)
        if p['kind'] in ['procedure', 'treatment']:
            require(product.category == 'Medicine', 'Health procedures and treatments require medicine products.')
        if p['kind'] != 'stock_in':
            require(stock_balance(product_id) >= quantities[product_id], f'Insufficient {product.name}. Record missing stock or correct the quantity.', 409)
    validate_outside_receipts(p)
    return animals

def apply_event(event, user, check_versions=True):
    p = event.payload
    animals = validate_current(p, user, check_versions)
    effects = []
    def change(obj, changes):
        effects.append({'model': obj.__class__.__name__, 'id': obj.id, 'before': {k: getattr(obj, k) for k in changes}, 'after': changes})
        for key, value in changes.items():
            setattr(obj, key, value)
    links = {a.id for a in animals}
    if event.kind == 'purchase' and p.get('purchase_rows'):
        existing_rows = {}
        if event.replaces_id:
            root = db.session.get(Event, event.replaces_id)
            while root.replaces_id:
                root = db.session.get(Event, root.replaces_id)
            existing_rows = {effect['id']: db.session.get(Animal, effect['id']) for effect in root.effects if effect.get('created') and effect['model'] == 'Animal'}
            require({r.get('animal_id') for r in p['purchase_rows']} == set(existing_rows), 'A purchase correction must preserve every registered animal ID.', 409)
        rows = []
        for row in p['purchase_rows']:
            existing = existing_rows.get(row.get('animal_id'))
            require(not db.session.scalar(select(Animal.id).where(Animal.identifier == row['identifier'], Animal.id != existing.id if existing else True)), 'Purchased tag already exists.', 409)
            attributes = {k: row.get(k) for k in ['identifier','sex','category','dob','breed','brand','birth_place','dam_id','sire_id']}
            attributes.update(station_id=p['station_id'], lifecycle='Active', temporary=False)
            if existing:
                calf = existing
                change(calf, {**attributes, 'version': calf.version + 1})
            else:
                calf = Animal(**attributes)
                db.session.add(calf)
                db.session.flush()
                effects.append({'model':'Animal','id':calf.id,'created':True,'after':{**attributes,'version':calf.version,'health':calf.health}})
            rows.append({**row, 'animal_id': calf.id})
            links.add(calf.id)
        event.payload = p = {**p, 'purchase_rows': rows}
    if event.kind in ['birth', 'purchase'] and not p.get('purchase_rows'):
        existing = creation_animal(db.session.get(Event, event.replaces_id)) if event.replaces_id else None
        if p.get('identifier'):
            require(not db.session.scalar(select(Animal.id).where(Animal.identifier == p['identifier'], Animal.id != existing.id if existing else True)), f'Tag {p["identifier"]} already belongs to another animal.', 409)
        temporary = not p.get('identifier')
        identifier = p.get('identifier') or (existing.identifier if existing else f'TEMP-{event.id[:8].upper()}')
        attributes = dict(identifier=identifier, temporary=temporary, sex=p['sex'], category=p['category'], breed=p['breed'], brand=p['brand'],
                          dob=p['dob'], birth_place=p['birth_place'], dam_id=p.get('dam_id') or None, sire_id=p.get('sire_id') or None,
                          station_id=p['station_id'], lifecycle='Dead' if p.get('outcome') == 'Stillborn' else 'Active')
        if existing:
            calf = existing
            change(calf, {**attributes, 'version': calf.version + 1})
        else:
            calf = Animal(**attributes)
            db.session.add(calf)
            db.session.flush()
            snapshot = {key: getattr(calf, key) for key in attributes}
            snapshot.update(version=calf.version, health=calf.health)
            effects.append({'model': 'Animal', 'id': calf.id, 'created': True, 'after': snapshot})
        links.add(calf.id)
        if event.kind == 'birth':
            dam = db.session.get(Animal, p['dam_id'])
            change(dam, {'version': dam.version + 1})
            links.add(dam.id)
    for animal in animals:
        changes = {'version': animal.version + 1}
        if event.kind == 'movement':
            changes['station_id'] = p['destination_id']
        if event.kind in ['lost', 'found']:
            changes['lifecycle'] = 'Lost' if event.kind == 'lost' else 'Active'
            if event.kind == 'found':
                changes['station_id'] = p['found_station_id']
        if event.kind in ['death', 'sale']:
            changes['lifecycle'] = 'Dead' if event.kind == 'death' else 'Sold'
        if event.kind == 'health':
            changes['health'] = 'Under observation' if animal.health == 'No concerns' else animal.health
            case = HealthCase(animal_id=animal.id, event_id=event.id, observation=p['observation'])
            db.session.add(case)
            db.session.flush()
            effects.append({'model': 'HealthCase', 'id': case.id, 'created': True})
        if event.kind in ['treatment', 'resolve_health']:
            case = db.session.get(HealthCase, p['case_id'])
            if event.kind == 'treatment':
                changes['health'] = 'Under treatment'
                change(case, {'status': 'Under treatment'})
            else:
                change(case, {'status': 'Resolved', 'closed_at': p['date']})
                db.session.flush()
                remaining = list(db.session.scalars(select(HealthCase).where(HealthCase.animal_id == animal.id, HealthCase.closed_at.is_(None))))
                changes['health'] = 'Under treatment' if any(c.status == 'Under treatment' for c in remaining) else ('Under observation' if remaining else 'No concerns')
        change(animal, changes)
    for animal_id in links:
        db.session.add(EventAnimal(event_id=event.id, animal_id=animal_id))
    for item in p['products']:
        qty = Decimal(item['quantity']) * (1 if event.kind == 'stock_in' else -1)
        db.session.add(StockTransaction(product_id=item['product_id'], event_id=event.id, quantity=qty, description=event.kind.replace('_', ' ')))
    if (event.kind in ['sale', 'purchase', 'expense', 'income'] and not (event.kind == 'purchase' and p.get('acquisition_source') == 'Gift')) or (event.kind == 'stock_in' and p['receipt_type'] == 'Purchase'):
        category = {'sale': 'Cattle sale', 'purchase': 'Cattle purchase'}.get(event.kind, p.get('finance_category'))
        if event.kind == 'stock_in':
            category = db.session.get(Product, p['products'][0]['product_id']).category
        db.session.add(FinancialTransaction(event_id=event.id, date=event.date,
                         type='Income' if event.kind in ['sale', 'income'] else 'Expense', category=category,
                         amount=Decimal(p['amount']), currency=p['currency'], reference=p['reference'], source=event.kind))
    event.effects = effects
    event.state = 'Approved'
    event.reviewer_id = user.id
    event.reviewed_at = now()
    audit(user, f'Approved {event.kind.replace("_", " ")} for {len(links)} cattle', event)

def reverse_event(original, replacement, user):
    require(original.state == 'Approved', 'Only an approved record can be corrected.', 409)
    if original.kind == 'birth':
        require(original.payload['dam_id'] == replacement.payload['dam_id'], 'Changing the dam requires parentage reconciliation; this correction must preserve the dam.', 409)
    if original.kind == 'stock_in':
        require(not any(item.get('receipt_id') == original.id for event in db.session.scalars(select(Event).where(Event.state == 'Approved', Event.id != original.id)) for item in event.payload.get('products', [])), 'Reconcile linked outside-supply usage before correcting this receipt.', 409)
    # A correction must not rewrite projections underneath subsequent dependent work.
    for effect in original.effects:
        model = {'Animal': Animal, 'HealthCase': HealthCase}[effect['model']]
        obj = db.session.scalar(select(model).where(model.id == effect['id']).with_for_update())
        require(obj, 'A dependent record is missing.', 409)
        if effect.get('created'):
            if model == Animal:
                require(effect.get('after') and all(getattr(obj, key) == value for key, value in effect['after'].items()), 'Later changes depend on this animal registration. Correct the later records first.', 409)
            else:
                require(obj.status == 'Under observation' and not obj.closed_at, 'This health case has later treatment; correct those records first.', 409)
        else:
            require(all(getattr(obj, key) == value for key, value in effect['after'].items()), 'Later changes depend on this record. Correct the later records first.', 409)
    # Only reverse this revision's forward entries. Prior reversals must remain
    # in the ledger to cancel the earlier revisions they refer to.
    stock_rows = list(db.session.scalars(select(StockTransaction).where(StockTransaction.event_id == original.id, StockTransaction.reversal_of.is_(None))))
    totals = defaultdict(Decimal)
    for row in stock_rows:
        totals[row.product_id] += row.quantity
    for product_id in sorted(totals):
        db.session.scalar(select(Product).where(Product.id == product_id).with_for_update())
        require(stock_balance(product_id) - totals[product_id] >= 0, 'This receipt has been consumed. Reconcile dependent usage before correcting it.', 409)
    for effect in reversed(original.effects):
        obj = db.session.get({'Animal': Animal, 'HealthCase': HealthCase}[effect['model']], effect['id'])
        if effect.get('created'):
            if effect['model'] == 'HealthCase':
                # Keep the original health case for the historical record.
                obj.status = 'Corrected'
                obj.closed_at = replacement.date
            # An animal registration correction preserves the original animal.
        else:
            for key, value in effect['before'].items():
                setattr(obj, key, value)
    for row in stock_rows:
        db.session.add(StockTransaction(event_id=replacement.id, product_id=row.product_id, quantity=-row.quantity, description='Correction reversal', reversal_of=row.id))
    for row in list(db.session.scalars(select(FinancialTransaction).where(FinancialTransaction.event_id == original.id, FinancialTransaction.reversal_of.is_(None)))):
        db.session.add(FinancialTransaction(event_id=replacement.id, date=replacement.date, type=row.type, category=row.category, amount=-row.amount, currency=row.currency, reference=row.reference, source='Correction reversal', reversal_of=row.id))
    original.state = 'Corrected'
    db.session.flush()
    # Versions remain monotonic even when an approved event is replaced.
    restored = list(db.session.scalars(select(Animal).join(EventAnimal).where(EventAnimal.event_id == original.id)))
    for animal in restored:
        animal.version += 2
    apply_event(replacement, user, check_versions=False)
    audit(user, f'Corrected {original.kind}: {replacement.reason}', replacement, {'original_id': original.id, 'original': original.payload, 'corrected': replacement.payload})


def validate_category(sex, category):
    require(category == 'Calf' or (sex == 'Female' and category in ['Cow', 'Heifer']) or (sex == 'Male' and category in ['Bull', 'Steer']), 'Sex and cattle category do not agree.')

def proposal_conflicts(event):
    if event.state != 'Pending approval':
        return []
    try:
        p = normalize(event.payload, db.session.get(User, event.author_id))
        validate_current(p, None)
        if p['kind'] == 'birth' and p.get('identifier') and db.session.scalar(select(Animal.id).where(Animal.identifier == p['identifier'])):
            return ['Permanent tag already belongs to another animal.']
        return []
    except RuleError as error:
        return [error.message]


def capture_signer():
    # Stable across credential/session changes; domain-separated from session signing.
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt='simbanai-station-capture-v1', signer_kwargs={'digest_method': sha256})


def capture_reference_animal(animal, user):
    result = animal_json(animal)
    if user.role == 'hand':
        result['capture_proof'] = capture_signer().dumps(dict(user_id=user.id, station_id=animal.station_id, animal_id=animal.id, version=animal.version))
    return result


def authorize_field_capture(p, user):
    if user.role != 'hand':
        return
    proofs = p.get('capture_proofs', {})
    require(isinstance(proofs, dict), 'Capture proofs must be an object.')
    ids = set(p['animal_ids'])
    if p['kind'] == 'procedure':
        ids.update(p.get('absent_ids', []))
    if p['kind'] == 'birth':
        ids.add(p['dam_id'])
    for animal_id in sorted(ids):
        animal = db.session.get(Animal, animal_id)
        require(animal, 'Selected animal does not exist.')
        token = proofs.get(str(animal_id))
        if token is not None:
            require(isinstance(token, str), 'Capture proof is invalid.', 403)
            try:
                claims = capture_signer().loads(token)
            except (BadData, UnicodeError):
                raise RuleError('Capture proof is invalid. Preserve this draft and ask the Manager to reconcile it.', 403)
            matches = (isinstance(claims, dict)
                       and claims.get('user_id') == user.id
                       and claims.get('station_id') == p['station_id'] and p['station_id'] in user_station_ids(user)
                       and claims.get('animal_id') == animal_id
                       and str(claims.get('version')) == str(p['versions'].get(str(animal_id))))
            require(matches, 'Capture proof does not match this account, station, animal and captured version.', 403)
        else:
            require(animal.station_id in user_station_ids(user), 'This older draft has no station proof and the animal is no longer assigned to you. Keep the draft; ask the Manager to reconcile and enter it.', 403)


def user_station_ids(user):
    if user.role != 'hand':
        return []
    if current_app.config.get('FARM_SCHEMA_READY'):
        ids = list(db.session.scalars(select(UserStation.station_id).where(UserStation.user_id == user.id).order_by(UserStation.station_id)))
        if ids:
            return ids
    return [user.station_id] if user.station_id else []


def station_ids_from_data(data):
    ids = data.get('station_ids', [data.get('station_id')])
    require(isinstance(ids, list) and ids, 'Assign at least one station using a station list.')
    ids = list(dict.fromkeys(integer(value, 'Assigned station') for value in ids))
    require(all(db.session.get(Station, station_id) for station_id in ids), 'Choose registered stations.')
    return ids


def assign_stations(user, data):
    ids = station_ids_from_data(data)
    db.session.flush()
    db.session.query(UserStation).filter_by(user_id=user.id).delete(synchronize_session=False)
    for station_id in ids:
        db.session.add(UserStation(user_id=user.id, station_id=station_id))
    user.station_id = ids[0]
    return ids


def compatible_units(unit):
    if unit in ['L', 'mL']:
        return ['mL', 'L']
    if unit in ['kg', 'g']:
        return ['g', 'kg']
    return [unit]


def convert_quantity(value, entered_unit, stock_unit):
    require(entered_unit in compatible_units(stock_unit), 'Unit is incompatible with the product stock unit.')
    amount = number(value, 'Quantity')
    factors = {'L': Decimal('1000'), 'mL': Decimal('1'), 'kg': Decimal('1000'), 'g': Decimal('1')}
    converted = amount * factors.get(entered_unit, Decimal('1')) / factors.get(stock_unit, Decimal('1'))
    require(converted == converted.quantize(Decimal('0.000001')), 'Quantity needs more than six stock-unit decimal places.')
    return converted


def validate_outside_receipts(p):
    allocations = defaultdict(Decimal)
    for item in p['products']:
        if item.get('source') == 'Outside source':
            require(p['kind'] in ['procedure','treatment','stock_use'], 'Outside source applies to usage, not receipts.')
            require(item.get('receipt_id'), 'Outside medicine needs a Manager-recorded receipt linked before approval.', 409)
            allocations[(str(item['receipt_id']), item['product_id'])] += Decimal(item['quantity'])
    for (receipt_id, product_id), needed in allocations.items():
        receipt = db.session.scalar(select(Event).where(Event.id == receipt_id).with_for_update())
        require(receipt and receipt.kind == 'stock_in' and receipt.state == 'Approved', 'Link an official supply receipt.', 409)
        require(receipt.payload.get('receipt_type') in ['Purchase', 'External supply'], 'Outside supplies require a purchase or free-supply receipt, not an opening balance.', 409)
        require(receipt.date <= p['date'], 'The linked receipt cannot follow the usage date.', 409)
        received = sum((Decimal(item['quantity']) for item in receipt.payload['products'] if item['product_id'] == product_id), Decimal(0))
        used = sum((Decimal(item['quantity']) for event in db.session.scalars(select(Event).where(Event.state == 'Approved')) for item in event.payload.get('products', []) if item.get('receipt_id') == receipt_id and item['product_id'] == product_id), Decimal(0))
        require(received - used >= needed, 'Linked receipt does not cover the outside quantity, or has already been allocated.', 409)


def calf_review_months():
    setting = db.session.get(FarmSetting, 'calf_review_months') if current_app.config.get('FARM_SCHEMA_READY') else None
    return int(setting.value) if setting else 6


def category_review_due(animal):
    if animal.category != 'Calf' or animal.lifecycle != 'Active' or not animal.dob:
        return None
    import calendar
    born = date.fromisoformat(animal.dob)
    months = born.year * 12 + born.month - 1 + calf_review_months()
    year, month = divmod(months, 12)
    due = date(year, month + 1, min(born.day, calendar.monthrange(year, month + 1)[1]))
    return due.isoformat() if due <= today() else None


def attention_for(animal):
    concerns = [animal.health] if animal.lifecycle == 'Active' and animal.health != 'No concerns' else []
    if has_request_context() and hasattr(g, '_dip_events'):
        dips = g._dip_events
    else:
        dips = [e for e in db.session.scalars(select(Event).where(Event.kind == 'procedure', Event.state == 'Approved').order_by(Event.date.desc(), Event.created_at.desc())) if e.payload.get('procedure') == 'Dipping']
        if has_request_context():
            g._dip_events = dips
    latest = next((e for e in dips if animal.id in e.payload['animal_ids'] or animal.id in e.payload.get('absent_ids', [])), None)
    if animal.lifecycle == 'Active' and latest:
        if animal.id in latest.payload.get('absent_ids', []):
            concerns.append('Absent from recorded dipping')
        elif latest.payload.get('next_due') and latest.payload['next_due'] < today().isoformat():
            concerns.append('Dipping overdue')
    return concerns


def record_name(event):
    if event.kind == 'procedure':
        return event.payload.get('procedure') or 'Procedure'
    if event.kind == 'purchase':
        return 'Cattle gift' if event.payload.get('acquisition_source') == 'Gift' else 'Cattle purchase'
    return event.kind.replace('_',' ').capitalize()
