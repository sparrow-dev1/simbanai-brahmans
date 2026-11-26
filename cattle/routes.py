import csv
import io
import secrets
import uuid
from decimal import Decimal
from functools import wraps
from datetime import timedelta
from datetime import datetime, timezone
from flask import request, session, jsonify, render_template, send_file, g, make_response
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import select, func
from PIL import Image, ImageOps, UnidentifiedImageError
from .models import db, User, Station, Animal, Product, Event, EventAnimal, StockTransaction, FinancialTransaction, HealthCase, Audit, ProfileAvatar, now
from .service import *

def register_routes(app):
    @app.errorhandler(RuleError)
    def business_error(error):
        db.session.rollback()
        response = make_response(jsonify(error=error.message), error.status)
        if getattr(error, 'retry_after', None):
            response.headers['Retry-After'] = str(error.retry_after)
        return response

    def authenticated(*roles):
        def decorator(fn):
            @wraps(fn)
            def wrapper(*args, **kwargs):
                user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
                require(user and user.active and user.session_version == session.get('version'), 'Please sign in again. Saved drafts remain on this device.', 401)
                require(not roles or user.role in roles, 'Your account cannot perform this action.', 403)
                if request.method not in ['GET', 'HEAD', 'OPTIONS']:
                    require(secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session.get('csrf', '!')), 'Your session changed. Refresh before submitting.', 403)
                g.user = user
                return fn(*args, **kwargs)
            return wrapper
        return decorator

    def user_json(user):
        avatar = db.session.get(ProfileAvatar, user.id) if app.config.get('FARM_SCHEMA_READY') else None
        return dict(id=user.id, name=user.name, username=user.username, role=user.role, station_id=user.station_id,
                    station_ids=user_station_ids(user), active=user.active, has_avatar=bool(avatar),
                    avatar_updated_at=avatar.updated_at if avatar else None)

    from .accounts import register_account_routes
    register_account_routes(app, authenticated)

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/')
    def home():
        return render_template('index.html')

    @app.get('/sw.js')
    def service_worker():
        response = app.send_static_file('sw.js')
        response.headers['Service-Worker-Allowed'] = '/'
        response.headers['Cache-Control'] = 'no-cache'
        return response

    @app.get('/api/session')
    def get_session():
        user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
        if not user or not user.active or user.session_version != session.get('version'):
            return jsonify(user=None, needs_setup=not db.session.scalar(select(User.id).limit(1)))
        return jsonify(user=user_json(user), csrf=session['csrf'])

    @app.post('/api/login')
    def login():
        require(request.headers.get('X-Requested-With') == 'Simbanai', 'Invalid login request.', 403)
        data = request.get_json(silent=True) or {}
        user = db.session.scalar(select(User).where(User.username == str(data.get('username', '')).strip().lower()))
        require(user and user.active and check_password_hash(user.password_hash, str(data.get('password', ''))), 'Username or password is incorrect.', 401)
        session.clear()
        session.update(user_id=user.id, version=user.session_version, csrf=secrets.token_hex(32))
        session.permanent = True
        audit(user, 'Signed in')
        db.session.commit()
        return jsonify(user=user_json(user), csrf=session['csrf'])

    @app.post('/api/logout')
    @authenticated()
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.post('/api/account/password')
    @authenticated()
    def change_password():
        data = request.get_json() or {}
        require(isinstance(data, dict), 'Request must be an object.')
        from .accounts import lock_user_credentials
        g.user = lock_user_credentials(g.user.id)
        require(g.user.active and g.user.session_version == session.get('version'),
                'Please sign in again. Saved drafts remain on this device.', 401)
        require(check_password_hash(g.user.password_hash, str(data.get('current', ''))), 'Current password is incorrect.')
        password = text(data.get('password'), 'New password', required=True, limit=200)
        require(len(password) >= 12, 'Use at least 12 characters.')
        g.user.password_hash = generate_password_hash(password)
        g.user.session_version += 1
        session['version'] = g.user.session_version
        audit(g.user, 'Changed account password')
        db.session.commit()
        return jsonify(ok=True)

    @app.get('/api/account/avatar')
    @authenticated('hand')
    def account_avatar():
        require(app.config.get('FARM_SCHEMA_READY'), 'Farm schema upgrade required. Run flask --app app upgrade-farm.', 503)
        avatar = db.session.get(ProfileAvatar, g.user.id)
        require(avatar, 'No profile picture is set.', 404)
        return send_file(io.BytesIO(avatar.image), mimetype=avatar.mime_type, download_name='profile-picture.png', conditional=False)

    @app.post('/api/account/avatar')
    @authenticated('hand')
    def replace_account_avatar():
        require(app.config.get('FARM_SCHEMA_READY'), 'Farm schema upgrade required. Run flask --app app upgrade-farm.', 503)
        upload = request.files.get('avatar')
        require(upload and upload.filename, 'Choose a profile picture to upload.')
        raw = upload.read(2 * 1024 * 1024 + 1)
        require(len(raw) <= 2 * 1024 * 1024, 'Profile pictures must be 2 MB or smaller.')
        try:
            with Image.open(io.BytesIO(raw)) as source:
                require(source.format in {'PNG', 'JPEG', 'WEBP'}, 'Choose a PNG, JPEG, or WebP image.')
                source.load()
                require(source.width <= 4096 and source.height <= 4096, 'Profile picture dimensions must be 4096 pixels or smaller.')
                image = ImageOps.fit(ImageOps.exif_transpose(source).convert('RGB'), (256, 256), method=Image.Resampling.LANCZOS)
        except (UnidentifiedImageError, OSError, ValueError):
            raise RuleError('Choose a valid PNG, JPEG, or WebP image.')
        encoded = io.BytesIO()
        image.save(encoded, format='PNG', optimize=True)
        require(encoded.tell() <= 512 * 1024, 'This profile picture could not be reduced to a safe size. Choose a simpler image.')
        avatar = db.session.get(ProfileAvatar, g.user.id)
        if not avatar:
            avatar = ProfileAvatar(user_id=g.user.id, image=encoded.getvalue(), mime_type='image/png', updated_at=now())
            db.session.add(avatar)
        else:
            avatar.image, avatar.mime_type, avatar.updated_at = encoded.getvalue(), 'image/png', now()
        audit(g.user, 'Updated profile picture')
        db.session.commit()
        return jsonify(user=user_json(g.user))

    @app.delete('/api/account/avatar')
    @authenticated('hand')
    def remove_account_avatar():
        require(app.config.get('FARM_SCHEMA_READY'), 'Farm schema upgrade required. Run flask --app app upgrade-farm.', 503)
        avatar = db.session.get(ProfileAvatar, g.user.id)
        if avatar:
            db.session.delete(avatar)
            audit(g.user, 'Removed profile picture')
            db.session.commit()
        return jsonify(user=user_json(g.user))

    @app.get('/api/reference')
    @authenticated()
    def reference():
        query = select(Animal)
        if g.user.role == 'hand':
            query = query.where(Animal.station_id.in_(user_station_ids(g.user)), Animal.lifecycle.in_(['Active', 'Lost']))
        return jsonify(updated_at=now(), animals=[capture_reference_animal(a, g.user) for a in db.session.scalars(query.order_by(Animal.identifier))],
            stations=[dict(id=s.id, name=s.name) for s in db.session.scalars(select(Station).order_by(Station.name))],
            products=[dict(id=p.id, name=p.name, category=p.category, unit=p.unit, usage_units=compatible_units(p.unit), active=p.active, low_stock=bool(p.active and stock_balance(p.id) <= p.minimum), minimum=str(p.minimum), balance=str(stock_balance(p.id)) if g.user.role != 'hand' else None) for p in db.session.scalars(select(Product).order_by(Product.name))],
            cases=[dict(id=c.id, animal_id=c.animal_id, observation=c.observation, status=c.status, closed_at=c.closed_at) for c in db.session.scalars(select(HealthCase).join(Animal).where(Animal.station_id.in_(user_station_ids(g.user)) if g.user.role == 'hand' else True))],
            calf_review_months=calf_review_months(), categories=CATEGORIES, procedures=PROCEDURES, units=UNITS, finance_categories=FINANCE_CATEGORIES)

    @app.get('/api/events')
    @authenticated()
    def events():
        ascending = request.args.get('order') == 'oldest'
        query = select(Event).order_by(Event.date.asc() if ascending else Event.date.desc(), Event.created_at.asc() if ascending else Event.created_at.desc(), Event.id.asc() if ascending else Event.id.desc())
        if g.user.role == 'hand':
            query = query.where(Event.author_id == g.user.id)
        elif g.user.role == 'owner':
            query = query.where(Event.state.in_(['Approved', 'Corrected']))
        if request.args.get('state'):
            query = query.where(Event.state == request.args['state'])
        page = max(1, integer(request.args.get('page', '1'), 'Page'))
        pending = list(db.session.scalars(query.where(Event.state == 'Pending approval')))
        history = list(db.session.scalars(query.where(Event.state != 'Pending approval').offset((page - 1) * 100).limit(101)))
        return jsonify(events=[event_json(e) for e in pending + history[:100]], page=page, has_more=len(history)>100, outstanding=len(pending))

    @app.post('/api/events')
    @authenticated('manager', 'hand')
    def submit_event():
        data = request.get_json(silent=True) or {}
        require(isinstance(data, dict), 'Submission must be an object.')
        try:
            event_id = str(uuid.UUID(str(data.get('id'))))
        except ValueError:
            raise RuleError('Submission ID is invalid.')
        existing = db.session.get(Event, event_id)
        if existing:
            require(existing.author_id == g.user.id, 'This submission belongs to another user.', 403)
            return jsonify(event=event_json(existing), duplicate=True)
        payload = normalize(data.get('payload'), g.user)
        authorize_field_capture(payload, g.user)
        for animal_id in payload['animal_ids']:
            require(db.session.get(Animal, animal_id), 'Selected animal does not exist.')
        event = Event(id=event_id, kind=payload['kind'], date=payload['date'], station_id=payload['station_id'], payload=payload, state='Pending approval', author_id=g.user.id)
        db.session.add(event)
        db.session.flush()
        audit(g.user, f'Submitted {event.kind.replace("_", " ")}', event)
        if g.user.role == 'manager':
            apply_event(event, g.user)
        db.session.commit()
        return jsonify(event=event_json(event)), 201

    @app.get('/api/events/<event_id>')
    @authenticated()
    def event_detail(event_id):
        event = db.session.get(Event, event_id)
        require(event, 'Event not found.', 404)
        require(g.user.role != 'hand' or event.author_id == g.user.id, 'This event belongs to another account.', 403)
        require(g.user.role != 'owner' or event.state in ['Approved', 'Corrected'], 'Only official records are visible to the owner.', 403)
        return jsonify(event=event_json(event))

    @app.post('/api/events/<event_id>/resubmit')
    @authenticated('hand')
    def resubmit(event_id):
        event = db.session.scalar(select(Event).where(Event.id == event_id).with_for_update())
        require(event and event.author_id == g.user.id, 'Submission not found.', 404)
        data = request.get_json() or {}
        require(isinstance(data, dict), 'Request must be an object.')
        require(event.revision == data.get('revision'), 'Submission changed. Refresh before resubmitting.', 409)
        require(event.state == 'Returned', 'Only returned records can be resubmitted.', 409)
        old = event.payload
        payload = normalize(data.get('payload'), g.user)
        authorize_field_capture(payload, g.user)
        require(payload['kind'] == event.kind, 'Returned records must keep the same event type.')
        event.payload = payload
        event.date = payload['date']
        event.station_id = payload['station_id']
        event.state = 'Pending approval'
        event.revision += 1
        event.reviewer_id = None
        event.reviewed_at = None
        event.reason = ''
        audit(g.user, 'Corrected and resubmitted returned record', event, {'original': old, 'corrected': payload})
        db.session.commit()
        return jsonify(event=event_json(event))

    @app.post('/api/events/<event_id>/review')
    @authenticated('manager')
    def review(event_id):
        event = db.session.scalar(select(Event).where(Event.id == event_id).with_for_update())
        require(event, 'Submission not found.', 404)
        data = request.get_json() or {}
        require(isinstance(data, dict), 'Request must be an object.')
        require(event.revision == data.get('revision'), 'Submission changed. Refresh before reviewing.', 409)
        require(event.state == 'Pending approval', 'This submission has already been reviewed.', 409)
        require(event.author_id != g.user.id, 'Manager entries are confirmed directly; do not approve your own submissions.', 403)
        action = data.get('action')
        require(action in ['approve', 'return', 'reject'], 'Choose a review action.')
        if action == 'approve':
            # Normalize once more to catch duplicated tags and changed reference data.
            payload = dict(event.payload)
            payload['products'] = [dict(item) for item in payload.get('products', [])]
            links = data.get('product_receipts', {})
            require(isinstance(links, dict), 'Receipt links must be an object.')
            for index, item in enumerate(payload['products']):
                if str(index) in links:
                    item['receipt_id'] = str(links[str(index)])
            event.payload = normalize(payload, g.user)
            apply_event(event, g.user)
        else:
            event.reason = text(data.get('reason'), 'Reason', required=True, limit=1000)
            event.state = 'Returned' if action == 'return' else 'Rejected'
            event.reviewer_id = g.user.id
            event.reviewed_at = now()
            audit(g.user, f'{event.state} {event.kind}: {event.reason}', event)
        event.revision += 1
        db.session.commit()
        return jsonify(event=event_json(event))

    @app.post('/api/events/<event_id>/correct')
    @authenticated('manager')
    def correct(event_id):
        original = db.session.scalar(select(Event).where(Event.id == event_id).with_for_update())
        require(original, 'Record not found.', 404)
        data = request.get_json() or {}
        require(isinstance(data, dict), 'Request must be an object.')
        require(original.revision == data.get('revision'), 'Record changed. Refresh before correcting.', 409)
        reason = text(data.get('reason'), 'Correction reason', required=True, limit=1000)
        registered = creation_animal(original) if original.kind in ['birth', 'purchase'] and not original.payload.get('purchase_rows') else None
        p = normalize(data.get('payload'), g.user, registered.id if registered else (-1 if original.payload.get('purchase_rows') else None))
        require(p['kind'] == original.kind, 'Corrections must preserve the event type.')
        replacement = Event(id=str(uuid.uuid4()), kind=p['kind'], date=p['date'], station_id=p['station_id'], payload=p, author_id=g.user.id, state='Pending approval', reason=reason, replaces_id=original.id)
        db.session.add(replacement)
        db.session.flush()
        reverse_event(original, replacement, g.user)
        original.revision += 1
        db.session.commit()
        return jsonify(event=event_json(replacement))

    @app.get('/api/animals/<int:animal_id>')
    @authenticated()
    def animal_profile(animal_id):
        animal = db.session.get(Animal, animal_id)
        require(animal, 'Animal not found.', 404)
        require(g.user.role != 'hand' or animal.station_id in user_station_ids(g.user), 'Animal is outside your station.', 403)
        history = list(db.session.scalars(select(Event).join(EventAnimal).where(EventAnimal.animal_id == animal_id, Event.state.in_(['Approved', 'Corrected'])).order_by(Event.date.desc(), Event.created_at.desc())))
        if g.user.role == 'hand':
            history = [e for e in history if e.kind in FIELD_KINDS + ['resolve_health', 'breeding']]
        return jsonify(animal=animal_json(animal), summary=profile_summary(animal, history), identity_history=[dict(at=a.at,author_id=a.user_id,action=a.action,details=a.details) for a in db.session.scalars(select(Audit).order_by(Audit.at.desc())) if a.details.get('original', {}).get('id') == animal.id and a.details.get('corrected', {}).get('id') == animal.id], events=[event_json(e) for e in history],
                       offspring=[animal_json(a) for a in db.session.scalars(select(Animal).where((Animal.dam_id == animal_id) | (Animal.sire_id == animal_id)))])

    @app.post('/api/animals/<int:animal_id>/identity')
    @authenticated('manager')
    def identity(animal_id):
        animal = db.session.scalar(select(Animal).where(Animal.id == animal_id).with_for_update())
        require(animal, 'Animal not found.', 404)
        data = request.get_json() or {}
        require(isinstance(data, dict), 'Request must be an object.')
        require(data.get('version') == animal.version, 'Animal changed. Refresh before editing.', 409)
        reason = text(data.get('reason'), 'Correction reason', required=True, limit=1000)
        old = animal_json(animal)
        identifier = text(data.get('identifier'), 'Tag', required=True, limit=80).upper()
        require(not db.session.scalar(select(Animal.id).where(Animal.identifier == identifier, Animal.id != animal.id)), f'Tag {identifier} already belongs to another animal.', 409)
        require(data.get('category') in CATEGORIES, 'Choose a category.')
        validate_category(animal.sex, data['category'])
        animal.identifier = identifier
        animal.temporary = False
        animal.category = data['category']
        animal.brand = text(data.get('brand'), 'Brand', limit=80)
        animal.version += 1
        audit(g.user, f'Updated identity for {identifier}: {reason}', details={'original': old, 'corrected': animal_json(animal)})
        db.session.commit()
        return jsonify(animal=animal_json(animal))

    @app.get('/api/overview')
    @authenticated('manager', 'owner')
    def overview():
        animals = list(db.session.scalars(select(Animal)))
        active = [a for a in animals if a.lifecycle == 'Active']
        lifecycle_counts = {status: sum(a.lifecycle == status for a in animals)
                            for status in ['Active', 'Sold', 'Dead', 'Lost']}
        month = today().replace(day=1).isoformat()
        approved = list(db.session.scalars(select(Event).where(Event.state == 'Approved')))
        totals = {c: {'Income': '0.00', 'Expense': '0.00', 'Net': '0.00'} for c in ['USD', 'ZiG']}
        for currency in totals:
            for direction in ['Income', 'Expense']:
                value = db.session.scalar(select(func.coalesce(func.sum(FinancialTransaction.amount), 0)).where(FinancialTransaction.currency == currency, FinancialTransaction.type == direction, FinancialTransaction.date >= month))
                totals[currency][direction] = str(value)
            totals[currency]['Net'] = str(Decimal(totals[currency]['Income']) - Decimal(totals[currency]['Expense']))
        stations = [dict(id=s.id, name=s.name, count=sum(a.station_id == s.id for a in active)) for s in db.session.scalars(select(Station).order_by(Station.name))]
        shortages = [dict(id=p.id, name=p.name, balance=str(stock_balance(p.id)), unit=p.unit, minimum=str(p.minimum)) for p in db.session.scalars(select(Product)) if p.active and stock_balance(p.id) <= p.minimum]
        weight_events = [e for e in approved if e.kind == 'weight']
        recent_weights = {}
        for e in sorted(weight_events, key=lambda e: (e.date, e.created_at)):
            recent_weights.update(e.payload['weights'])
        growth_history = {}
        for event in sorted(weight_events, key=lambda e: (e.date, e.created_at, e.id)):
            for animal_id, weight in event.payload['weights'].items():
                growth_history.setdefault(int(animal_id), []).append((event.date, Decimal(weight)))
        growth = []
        for animal_id, entries in growth_history.items():
            latest_date, latest_weight = entries[-1]
            previous = next((entry for entry in reversed(entries[:-1]) if entry[0] < latest_date), None)
            delta = latest_weight - previous[1] if previous else None
            days = (date.fromisoformat(latest_date)-date.fromisoformat(previous[0])).days if previous else None
            growth.append(dict(animal_id=animal_id, identifier=db.session.get(Animal, animal_id).identifier, date=latest_date, weight=str(latest_weight), change=str(delta) if delta is not None else None, daily_gain=str((delta/Decimal(days)).quantize(Decimal('0.001'))) if days else None))
        # Latest approved procedure with an explicitly configured next due date.
        schedules = {}
        for e in sorted([e for e in approved if e.kind == 'procedure'], key=lambda e: (e.date, e.created_at)):
            for animal_id in e.payload['animal_ids']:
                schedules[(animal_id, e.payload['procedure'])] = e
        due = [dict(event_id=e.id, animal_id=animal_id, station_id=db.session.get(Animal, animal_id).station_id, procedure=procedure, date=e.payload['next_due']) for (animal_id, procedure), e in schedules.items() if db.session.get(Animal, animal_id).lifecycle == 'Active' and e.payload.get('next_due') and e.payload['next_due'] <= (today() + timedelta(days=7)).isoformat()]
        return jsonify(active=len(active), lifecycle_counts=lifecycle_counts,
                       registered_total=len(animals), concerns=sum(a.health != 'No concerns' for a in active),
                       pending=db.session.scalar(select(func.count(Event.id)).where(Event.state == 'Pending approval')) if g.user.role == 'manager' else None,
                       births=sum(e.kind == 'birth' and e.date >= month and e.payload.get('outcome') == 'Live calf' for e in approved),
                       deaths=sum(e.kind == 'death' and e.date >= month for e in approved),
                       sales=sum(len(e.payload['animal_ids']) for e in approved if e.kind == 'sale' and e.date >= month),
                       purchases=sum(len(e.payload.get('purchase_rows', [1])) for e in approved if e.kind == 'purchase' and e.date >= month),
                       breeding_checks=sum(len(e.payload['animal_ids']) for e in approved if e.kind == 'breeding' and e.payload.get('breeding_action') == 'Pregnancy check' and e.date >= month),
                       animals_weighed=len(recent_weights), growth=growth, stillbirths=sum(e.kind == 'birth' and e.date >= month and e.payload.get('outcome') == 'Stillborn' for e in approved), stations=stations, shortages=shortages, due=due, money=totals,
                       recent=[event_json(e) for e in sorted(approved, key=lambda e: (e.date, e.created_at, e.id), reverse=True)[:8]])

    @app.get('/api/money')
    @authenticated('manager', 'owner')
    def money():
        return jsonify(transactions=[dict(id=t.id, event_id=t.event_id, date=t.date, type=t.type, category=t.category, amount=str(t.amount), currency=t.currency, reference=t.reference, source=t.source, reversal_of=t.reversal_of) for t in db.session.scalars(select(FinancialTransaction).order_by(FinancialTransaction.date.desc(), FinancialTransaction.id.desc()))])

    @app.get('/api/stock')
    @authenticated('manager', 'owner')
    def stock():
        return jsonify(transactions=[dict(id=t.id, product_id=t.product_id, event_id=t.event_id, quantity=str(t.quantity), description=t.description, reversal_of=t.reversal_of, date=db.session.get(Event, t.event_id).date) for t in db.session.scalars(select(StockTransaction).order_by(StockTransaction.id.desc()))])

    @app.get('/api/activity')
    @authenticated('manager', 'owner')
    def activity():
        return jsonify(activity=[dict(id=a.id, at=a.at, user=db.session.get(User, a.user_id).name if a.user_id else 'Setup', action=a.action, event_id=a.event_id, details=a.details) for a in db.session.scalars(select(Audit).order_by(Audit.id.desc()).limit(1000))])

    @app.get('/api/users')
    @authenticated('manager')
    def users():
        return jsonify(users=[user_json(u) for u in db.session.scalars(select(User).order_by(User.name))])

    @app.post('/api/users')
    @authenticated('manager')
    def add_user():
        data = request.get_json() or {}
        require(isinstance(data, dict), 'Request must be an object.')
        name = text(data.get('name'), 'Name', True, 120)
        username = text(data.get('username'), 'Username', True, 80).lower()
        from .accounts import lock_username
        lock_username(username)
        if app.config.get('ACCOUNTS_SCHEMA_READY'):
            from .models import RegistrationRequest
            require(not db.session.scalar(select(RegistrationRequest.id).where(RegistrationRequest.pending_username == username)),
                    'This username is awaiting registration approval.', 409)
        password = text(data.get('password'), 'Password', True, 200)
        require(len(password) >= 12, 'Use a password of at least 12 characters.')
        station_id = station_ids_from_data(data)[0]
        require(db.session.get(Station, station_id), 'Choose an existing station.')
        user = User(name=name, username=username, password_hash=generate_password_hash(password), role='hand', station_id=station_id)
        db.session.add(user)
        assign_stations(user, data)
        audit(g.user, f'Created General Hand account: {name}')
        db.session.commit()
        return jsonify(user=user_json(user)), 201

    @app.post('/api/users/<int:user_id>')
    @authenticated('manager')
    def edit_user(user_id):
        from .accounts import lock_user_credentials
        user = lock_user_credentials(user_id)
        require(user and user.role == 'hand', 'Only General Hand accounts can be managed here.', 403)
        data = request.get_json() or {}
        require(isinstance(data, dict), 'Request must be an object.')
        station_id = station_ids_from_data(data)[0]
        require(db.session.get(Station, station_id), 'Choose a station.')
        require(isinstance(data.get('active'), bool), 'Choose account status.')
        assign_stations(user, data)
        user.active = data['active']
        if data.get('password'):
            password = text(data['password'], 'Password', True, 200)
            require(len(password) >= 12, 'Use at least 12 characters.')
            user.password_hash = generate_password_hash(password)
        user.session_version += 1
        audit(g.user, f'Updated General Hand account: {user.name}')
        db.session.commit()
        return jsonify(user=user_json(user))

    @app.post('/api/stations')
    @authenticated('manager')
    def add_station():
        name = text((request.get_json() or {}).get('name'), 'Station name', True, 120)
        station = Station(name=name)
        db.session.add(station)
        audit(g.user, f'Added station: {name}')
        db.session.commit()
        return jsonify(id=station.id, name=station.name), 201

    @app.post('/api/products')
    @authenticated('manager')
    def add_product():
        data = request.get_json() or {}
        require(isinstance(data, dict), 'Request must be an object.')
        name = text(data.get('name'), 'Product name', True, 120)
        require(data.get('category') in ['Medicine', 'Feed', 'Fuel'], 'Choose a supply category.')
        require(data.get('unit') in UNITS, 'Choose a unit.')
        product = Product(name=name, category=data['category'], unit=data['unit'], minimum=number(data.get('minimum'), 'Minimum stock', True))
        db.session.add(product)
        audit(g.user, f'Added supply product: {name}')
        db.session.commit()
        return jsonify(id=product.id), 201

    @app.post('/api/products/<int:product_id>')
    @authenticated('manager')
    def edit_product(product_id):
        product = db.session.get(Product, product_id)
        require(product, 'Product not found.', 404)
        data = request.get_json() or {}
        require(isinstance(data, dict), 'Product details must be an object.')
        if 'active' in data:
            require(isinstance(data['active'], bool), 'Choose active or archived.')
            product.active = data['active']
            audit(g.user, ('Restored' if product.active else 'Archived') + f' product {product.name}; stock and history retained')
            db.session.commit()
            return jsonify(id=product.id, active=product.active)
        minimum = number(data.get('minimum'), 'Minimum stock', True)
        old = str(product.minimum)
        product.minimum = minimum
        audit(g.user, f'Changed minimum stock for {product.name}', details={'original': old, 'corrected': str(minimum)})
        db.session.commit()
        return jsonify(ok=True)

    @app.get('/api/settings')
    @authenticated('manager')
    def settings():
        return jsonify(calf_review_months=calf_review_months())

    @app.post('/api/settings')
    @authenticated('manager')
    def update_settings():
        data = request.get_json(silent=True) or {}
        require(isinstance(data, dict), 'Settings must be an object.')
        months = integer(data.get('calf_review_months'), 'Review age')
        require(1 <= months <= 60, 'Use a review age between 1 and 60 months.')
        row = db.session.get(FarmSetting, 'calf_review_months')
        if not row:
            row = FarmSetting(key='calf_review_months', value=str(months))
            db.session.add(row)
        else:
            row.value = str(months)
        audit(g.user, f'Changed calf category review age to {months} months')
        db.session.commit()
        return jsonify(calf_review_months=months)

    @app.get('/api/import/template')
    @authenticated('manager')
    def import_template():
        output = 'identifier,sex,category,breed,dob,station,brand,birth_place,dam_identifier,sire_identifier\n'
        return send_file(io.BytesIO(output.encode('utf-8-sig')), mimetype='text/csv', as_attachment=True, download_name='opening-herd-template.csv')

    def parse_import(raw):
        require(isinstance(raw, str) and len(raw) < 2000000, 'Choose a CSV smaller than 2 MB.')
        reader = csv.DictReader(io.StringIO(raw.lstrip('\ufeff')))
        require(reader.fieldnames and {'identifier', 'sex', 'category', 'station'} <= set(reader.fieldnames), 'Required columns: identifier, sex, category, station.')
        rows = list(reader)
        require(0 < len(rows) <= 5000, 'Import between 1 and 5,000 cattle at a time.')
        identifiers = set()
        parsed, errors = [], []
        stations = {s.name.lower(): s.id for s in db.session.scalars(select(Station))}
        known = {a.identifier: a for a in db.session.scalars(select(Animal))}
        incoming = {str(r.get('identifier', '')).strip().upper(): r for r in rows}
        for line, row in enumerate(rows, 2):
            try:
                tag = text(row.get('identifier'), 'Tag', True, 80).upper()
                require(tag not in identifiers and tag not in known, f'Duplicate tag: {tag}.')
                identifiers.add(tag)
                require(row.get('sex') in ['Female', 'Male'], 'Sex must be Female or Male.')
                require(row.get('category') in CATEGORIES, 'Unknown category.')
                validate_category(row.get('sex'), row['category'])
                station_id = stations.get(str(row.get('station', '')).strip().lower())
                require(station_id, 'Station does not exist; create it before importing.')
                dob = valid_date(row['dob'], 'Birth date') if row.get('dob') else None
                parent_tags = {}
                for field, expected in [('dam_identifier', 'Female'), ('sire_identifier', 'Male')]:
                    parent_tag = str(row.get(field) or '').strip().upper()
                    if parent_tag:
                        require(parent_tag != tag, 'Animal cannot be its own parent.')
                        parent = known.get(parent_tag) or incoming.get(parent_tag)
                        require(parent, f'Parent {parent_tag} not found.')
                        parent_sex = parent.sex if isinstance(parent, Animal) else parent.get('sex')
                        require(parent_sex == expected, f'{field} has the wrong sex.')
                        parent_dob = parent.dob if isinstance(parent, Animal) else parent.get('dob')
                        require(not dob or not parent_dob or parent_dob < dob, 'Parent birth date must precede offspring birth date.')
                    parent_tags[field] = parent_tag
                parsed.append(dict(identifier=tag, sex=row['sex'], category=row['category'], station_id=station_id, dob=dob,
                                   breed=text(row.get('breed') or 'Brahman', 'Breed', limit=80), brand=text(row.get('brand'), 'Brand', limit=80),
                                   birth_place=text(row.get('birth_place'), 'Birth place', limit=120), **parent_tags))
            except RuleError as error:
                errors.append({'line': line, 'error': error.message})
        # Unknown birth dates must not allow cyclic parentage in an opening import.
        if not errors:
            graph = {r['identifier']: {r[k] for k in ['dam_identifier', 'sire_identifier'] if r[k] in incoming} for r in parsed}
            remaining = dict(graph)
            while remaining:
                ready = {tag for tag, parents in remaining.items() if not parents}
                if not ready:
                    errors.append({'line': 'Parentage', 'error': 'Parent identifiers form a cycle. Correct the parent relationships before importing.'})
                    break
                remaining = {tag: parents - ready for tag, parents in remaining.items() if tag not in ready}
        return parsed, errors

    @app.post('/api/import/preview')
    @authenticated('manager')
    def preview_import():
        rows, errors = parse_import((request.get_json() or {}).get('csv'))
        return jsonify(rows=rows, errors=errors, count=len(rows), can_import=not errors)

    @app.post('/api/import/commit')
    @authenticated('manager')
    def commit_import():
        raw = (request.get_json() or {}).get('csv')
        rows, errors = parse_import(raw)
        require(not errors, 'Import contains errors. Preview and correct all rows first.')
        parent_map = {a.identifier: a for a in db.session.scalars(select(Animal))}
        added = []
        for row in rows:
            animal = Animal(**{key: value for key, value in row.items() if key not in ['dam_identifier', 'sire_identifier']})
            db.session.add(animal)
            added.append((animal, row))
            parent_map[animal.identifier] = animal
        db.session.flush()
        for animal, row in added:
            animal.dam_id = parent_map[row['dam_identifier']].id if row['dam_identifier'] else None
            animal.sire_id = parent_map[row['sire_identifier']].id if row['sire_identifier'] else None
            audit(g.user, f'Opening herd registration: {animal.identifier}', details=animal_json(animal))
        audit(g.user, f'Imported {len(rows)} opening herd records; no historical financial entries created')
        db.session.commit()
        return jsonify(count=len(rows)), 201

    from .farm_views import register_farm_views, profile_summary
    register_farm_views(app, authenticated)

    REPORT_TYPES = ['Herd', 'Health', 'Breeding', 'Growth', 'Movements', 'Births/deaths', 'Purchases/sales', 'Acquisitions/sales', 'Supplies', 'Finances']
    def report_data():
        report = request.args.get('type', 'Herd')
        require(report in REPORT_TYPES, 'Choose a report type.')
        start, end = request.args.get('from') or None, request.args.get('to') or None
        if start:
            start = valid_date(start, 'From date')
        if end:
            end = valid_date(end, 'To date')
        require(not start or not end or start <= end, 'From date must precede To date.')
        station = request.args.get('station')
        station = integer(station, 'Station') if station else None
        events = select(Event).where(Event.state == 'Approved').order_by(Event.date.desc())
        if start:
            events = events.where(Event.date >= start)
        if end:
            events = events.where(Event.date <= end)
        if station:
            events = events.where(Event.station_id == station)
        rows = []
        participant_groups = []
        if report == 'Herd':
            headings = ['Tag', 'Sex', 'Category', 'Station', 'Lifecycle', 'Health', 'Birth date']
            for a in db.session.scalars(select(Animal).where(Animal.station_id == station if station else True).order_by(Animal.identifier)):
                rows.append([a.identifier, a.sex, a.category, db.session.get(Station, a.station_id).name, a.lifecycle, a.health, a.dob or 'Unknown'])
        elif report == 'Finances':
            headings = ['Date', 'Type', 'Category', 'Amount', 'Currency', 'Reference', 'Source', 'Event']
            query = select(FinancialTransaction).join(Event).order_by(FinancialTransaction.date.desc())
            if start:
                query = query.where(FinancialTransaction.date >= start)
            if end:
                query = query.where(FinancialTransaction.date <= end)
            if station:
                query = query.where(Event.station_id == station)
            rows = [[t.date, t.type, t.category, str(t.amount), t.currency, t.reference, t.source, t.event_id[:8]] for t in db.session.scalars(query)]
        elif report == 'Supplies':
            headings = ['Date', 'Product', 'Category', 'Quantity', 'Unit', 'Description', 'Event']
            query = select(StockTransaction).join(Event).order_by(Event.date.desc(), StockTransaction.id.desc())
            if start:
                query = query.where(Event.date >= start)
            if end:
                query = query.where(Event.date <= end)
            if station:
                query = query.where(Event.station_id == station)
            for t in db.session.scalars(query):
                product = db.session.get(Product, t.product_id)
                rows.append([db.session.get(Event, t.event_id).date, product.name, product.category, str(t.quantity), product.unit, t.description, t.event_id[:8]])
        else:
            kinds = {'Health': ['health', 'treatment', 'resolve_health', 'procedure'], 'Breeding': ['breeding', 'birth'], 'Growth': ['weight'], 'Movements': ['movement', 'lost', 'found'], 'Births/deaths': ['birth', 'death'], 'Purchases/sales': ['purchase', 'sale'], 'Acquisitions/sales': ['purchase', 'sale']}[report]
            if report == 'Growth':
                headings = ['Date', 'Animal', 'Weight (kg)', 'Event']
                for e in db.session.scalars(events.where(Event.kind.in_(kinds))):
                    rows.extend([[e.date, db.session.get(Animal, int(i)).identifier, w, e.id[:8]] for i, w in e.payload['weights'].items()])
            else:
                headings = ['Date', 'Record', 'Station', 'Participating cattle', 'Details', 'Event']
                for e in db.session.scalars(events.where(Event.kind.in_(kinds))):
                    animals = list(db.session.scalars(select(Animal).join(EventAnimal).where(EventAnimal.event_id == e.id)))
                    details = e.payload.get('observation') or e.payload.get('cause') or e.payload.get('procedure') or e.payload.get('breeding_action') or e.payload.get('outcome') or e.payload.get('notes', '')
                    if e.payload.get('expected_calving'):
                        details += ' — estimated calving ' + e.payload['expected_calving']
                    p = e.payload
                    extra = []
                    for item in p.get('products', []):
                        product = db.session.get(Product, item['product_id'])
                        extra.append(f"{product.name}: {item.get('entered_quantity',item['quantity'])} {item.get('entered_unit',product.unit)}; stock {item['quantity']} {product.unit}; dosage {item.get('dosage') or 'not recorded'}; source {item.get('source_note') or 'Farm stock'}")
                    if p.get('absent_ids'):
                        extra.append('Absent: ' + ', '.join(db.session.get(Animal, i).identifier for i in p['absent_ids']))
                    for key in ['next_due','pregnancy_result','estimate_basis','movement_reason','lifecycle_reason','acquisition_source','amount','currency','reference']:
                        if p.get(key) is not None:
                            extra.append(key.replace('_', ' ').title() + ': ' + str(p[key]))
                    for key in ['dam_id','sire_id']:
                        if p.get(key):
                            extra.append(key[:-3].title() + ': ' + db.session.get(Animal, p[key]).identifier)
                    if p.get('found_station_id'):
                        extra.append('Found at: ' + db.session.get(Station, p['found_station_id']).name)
                    if p.get('destination_id'):
                        extra.append('Destination: ' + db.session.get(Station, p['destination_id']).name)
                    for animal_id, result in p.get('pregnancy_results', {}).items():
                        extra.append(db.session.get(Animal, int(animal_id)).identifier + ': ' + '; '.join(str(v) for v in result.values() if v))
                    for row in p.get('purchase_rows', []):
                        extra.append(row['identifier'] + ': ' + (str(row.get('price', '0')) + ' ' + str(p.get('currency')) if p.get('acquisition_source') != 'Gift' else 'Gift - no expense'))
                    participant_groups.append(dict(title=e.date + ' - ' + record_name(e) + ' - ' + e.id[:8], ids=[a.identifier for a in animals], absent=[db.session.get(Animal, i).identifier for i in p.get('absent_ids', [])]))
                    details = '; '.join([details] + extra)
                    rows.append([e.date, record_name(e), db.session.get(Station, e.station_id).name if e.station_id else '', ', '.join(a.identifier for a in animals), details, e.id[:8]])
        from .reporting import report_summary
        return dict(type=report, columns=headings, rows=rows, participant_groups=participant_groups, summary=report_summary(report, headings, rows), filters={'from': start, 'to': end, 'station': station}, generated_at=now())

    @app.get('/api/reports')
    @authenticated('manager', 'owner')
    def reports():
        return jsonify(report_data())

    @app.get('/api/reports.pdf')
    @authenticated('manager', 'owner')
    def reports_pdf():
        from .reporting import build_pdf
        data = report_data()
        buffer = build_pdf(data, sample_label=app.config.get('SAMPLE_REPORT_LABEL'))
        return send_file(buffer, mimetype='application/pdf', as_attachment=request.args.get('inline') != '1', download_name=f'simbanai-{data["type"].replace("/", "-").lower()}.pdf')
