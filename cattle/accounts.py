"""Approved registration and manually delivered, single-use recovery codes."""
import hashlib
import hmac
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app, request, jsonify, g, session
from sqlalchemy import select, update, delete, func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from .models import db, User, Station, RegistrationRequest, PasswordResetRequest, AuthThrottle, now
from .service import RuleError, require, text, integer, audit, station_ids_from_data

ROLES = ('hand', 'owner', 'manager')
ACKNOWLEDGEMENT = 'If your account is eligible, your manager can issue a reset code. Farm Managers should contact the server administrator.'


def require_account_schema():
    require(current_app.config.get('ACCOUNTS_SCHEMA_READY'), 'Account requests are temporarily unavailable. Contact the farm administrator.', 503)


def keyed_hash(value):
    key = current_app.config['SECRET_KEY']
    if isinstance(key, str):
        key = key.encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def code_hash(user_id, code):
    return keyed_hash(f'recovery:{user_id}:{code}')


def quota_key(kind, identity, seconds):
    timestamp = int(time.time())
    start = timestamp // seconds * seconds
    return f'{kind}:{start}:{keyed_hash(identity)}', start + seconds


def reserve_quota(kind, identity, seconds, limit):
    key, end = quota_key(kind, identity, seconds)
    if db.engine.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(AuthThrottle).values(key=key, count=1, expires_at=end)
    statement = statement.on_conflict_do_update(
        index_elements=['key'], set_={'count': AuthThrottle.count + 1},
        where=AuthThrottle.count < max(1, int(limit))).returning(AuthThrottle.count)
    count = db.session.execute(statement).scalar()
    if count is None:
        db.session.rollback()
        error = RuleError('Too many attempts. Please try again later.', 429)
        error.retry_after = max(1, end - int(time.time()))
        raise error
    return key


def take_public_quota(username, recovery_attempt=False):
    require_account_schema()
    ip = request.remote_addr or 'unknown'
    reserve_quota('requests-ip', ip, 3600, current_app.config['AUTH_REQUESTS_PER_IP'])
    key = reserve_quota('requests-user', username, 3600, current_app.config['AUTH_REQUESTS_PER_USERNAME'])
    if recovery_attempt:
        key = reserve_quota('code-attempt', username, 900, current_app.config['AUTH_CODE_ATTEMPTS'])
    db.session.execute(delete(AuthThrottle).where(AuthThrottle.expires_at < int(time.time())))
    # Quotas survive rejected requests and transaction rollbacks below.
    db.session.commit()
    return key


def public_data():
    require_account_schema()
    require(request.headers.get('X-Requested-With') == 'Simbanai', 'Invalid account request.', 403)
    origin = request.headers.get('Origin')
    require(not origin or origin == request.host_url.rstrip('/'), 'Invalid account request.', 403)
    data = request.get_json(silent=True)
    require(isinstance(data, dict), 'Enter the required account details.')
    return data


def username_value(data):
    return text(data.get('username'), 'Username', True, 80).lower()


def new_password(data):
    password = data.get('password')
    require(isinstance(password, str) and 12 <= len(password) <= 200, 'Use a password of 12 to 200 characters.')
    require(password == data.get('confirmation'), 'The passwords do not match.')
    return password


def lock_username(username):
    """Serialize claims across the user and pending-request tables."""
    connection = db.session.connection()
    if connection.dialect.name == 'postgresql':
        key = int.from_bytes(hashlib.sha256(('account-username:' + username).encode()).digest()[:8], 'big', signed=True)
        db.session.execute(select(func.pg_advisory_xact_lock(key)))
    elif not connection.connection.dbapi_connection.in_transaction:
        connection.exec_driver_sql('BEGIN IMMEDIATE')


def lock_user_credentials(user_id):
    connection = db.session.connection()
    if connection.dialect.name == 'sqlite' and not connection.connection.dbapi_connection.in_transaction:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
    return db.session.scalar(select(User).where(User.id == user_id).with_for_update()
                             .execution_options(populate_existing=True))


def open_reset_request(user):
    existing = db.session.scalar(select(PasswordResetRequest).where(PasswordResetRequest.open_user_id == user.id))
    if existing:
        return existing
    row = PasswordResetRequest(id=str(uuid.uuid4()), user_id=user.id, open_user_id=user.id)
    try:
        with db.session.begin_nested():
            db.session.add(row)
            db.session.flush()
        audit(None, 'Password recovery requested', details={'request_id': row.id, 'username': user.username})
        return row
    except IntegrityError:
        return db.session.scalar(select(PasswordResetRequest).where(PasswordResetRequest.open_user_id == user.id))


def issue_code(user, row=None, actor=None, administrator=False, revision=None):
    require_account_schema()
    user = lock_user_credentials(user.id)
    require(user and user.active, 'Only active accounts can receive a reset code.')
    require(user.role == 'manager' if administrator else user.role in ('hand', 'owner'),
            'Manager recovery requires the server administrator.', 403)
    if row is None:
        row = open_reset_request(user)
    row = db.session.scalar(select(PasswordResetRequest).where(PasswordResetRequest.id == row.id).with_for_update())
    require(row and row.user_id == user.id and row.state in ('Pending', 'Issued'), 'This recovery request is already closed.', 409)
    if revision is not None:
        require(row.revision == revision, 'This request changed. Refresh before reviewing.', 409)
    raw = f'{secrets.randbelow(10 ** 12):012d}'
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    changed = db.session.execute(update(PasswordResetRequest).where(
        PasswordResetRequest.id == row.id, PasswordResetRequest.revision == row.revision,
        PasswordResetRequest.state.in_(('Pending', 'Issued'))).values(
        state='Issued', revision=row.revision + 1, code_hash=code_hash(user.id, raw), expires_at=expiry,
        issued_version=user.session_version, reviewer_id=actor.id if actor else None,
        reviewed_at=now(), reason='').execution_options(synchronize_session=False))
    require(changed.rowcount == 1, 'This request changed. Refresh before reviewing.', 409)
    audit(actor, 'Recovery code issued' if actor else 'Server administrator issued Manager recovery code',
          details={'request_id': row.id, 'user_id': user.id, 'expires_at': expiry})
    return ' '.join(raw[i:i+4] for i in range(0, 12, 4)), expiry


def register_account_routes(app, authenticated):
    @app.post('/api/register')
    def register_account():
        data = public_data()
        username = username_value(data)
        name = text(data.get('name'), 'Name', True, 120)
        role = data.get('role')
        require(role in ROLES, 'Choose General Hand, Owner, or Farm Manager.')
        password = new_password(data)
        take_public_quota(username)
        lock_username(username)
        require(db.session.scalar(select(User.id).where(User.role == 'manager', User.active.is_(True))),
                'Registration is unavailable until the initial Manager is provisioned.', 503)
        require(not db.session.scalar(select(User.id).where(User.username == username)) and
                not db.session.scalar(select(RegistrationRequest.id).where(RegistrationRequest.pending_username == username)),
                'This username is already registered or awaiting approval.', 409)
        row = RegistrationRequest(id=str(uuid.uuid4()), name=name, username=username,
                                  pending_username=username, requested_role=role, password_hash=generate_password_hash(password))
        db.session.add(row)
        audit(None, 'Registration requested', details={'request_id': row.id, 'username': username, 'requested_role': role})
        db.session.commit()
        return jsonify(state='Pending', message='Registration submitted. Your manager must approve your account before you can sign in.'), 201

    @app.get('/api/account-requests')
    @authenticated('manager')
    def account_requests():
        require_account_schema()
        page = max(1, integer(request.args.get('page', '1'), 'Page'))
        registration_query = select(RegistrationRequest).order_by(RegistrationRequest.created_at.desc(), RegistrationRequest.id.desc())
        registration_rows = list(db.session.scalars(registration_query.where(RegistrationRequest.state == 'Pending')))
        registration_history = list(db.session.scalars(registration_query.where(RegistrationRequest.state != 'Pending').offset((page-1)*100).limit(101)))
        registration_rows += registration_history[:100]
        registrations = [dict(id=r.id, name=r.name, username=r.username, requested_role=r.requested_role,
                              state=r.state, created_at=r.created_at, reviewed_at=r.reviewed_at, reason=r.reason)
                         for r in registration_rows]
        recoveries = []
        reset_query = select(PasswordResetRequest, User).join(User, PasswordResetRequest.user_id == User.id).where(User.role != 'manager').order_by(PasswordResetRequest.created_at.desc(), PasswordResetRequest.id.desc())
        open_states = ['Pending', 'Issued', 'Expired', 'Invalidated']
        reset_rows = list(db.session.execute(reset_query.where(PasswordResetRequest.state.in_(open_states))))
        reset_history = list(db.session.execute(reset_query.where(~PasswordResetRequest.state.in_(open_states)).offset((page-1)*100).limit(101)))
        for row, user in reset_rows + reset_history[:100]:
            # Manager recovery records are accessible only through server administration.
            if user.role == 'manager':
                continue
            state = row.state
            if state == 'Issued':
                if not user.active or row.issued_version != user.session_version:
                    state = 'Invalidated'
                elif row.expires_at <= now():
                    state = 'Expired'
            recoveries.append(dict(id=row.id, name=user.name, username=user.username, role=user.role,
                                   active=user.active, state=state, revision=row.revision, created_at=row.created_at,
                                   expires_at=row.expires_at, reviewed_at=row.reviewed_at, reason=row.reason))
        return jsonify(registrations=registrations, password_resets=recoveries, page=page, has_more=len(registration_history)>100 or len(reset_history)>100)

    @app.post('/api/registration-requests/<request_id>/review')
    @authenticated('manager')
    def review_registration(request_id):
        require_account_schema()
        data = request.get_json(silent=True) or {}
        require(isinstance(data, dict), 'Enter the required review details.')
        row = db.session.scalar(select(RegistrationRequest).where(RegistrationRequest.id == request_id).with_for_update())
        require(row, 'Registration request not found.', 404)
        require(row.state == 'Pending', 'This registration is already reviewed.', 409)
        lock_username(row.username)
        action = data.get('action')
        require(action in ('approve', 'reject'), 'Choose Approve or Reject.')
        reason = text(data.get('reason'), 'Rejection reason', action == 'reject', 1000)
        account = None
        if action == 'approve':
            require(row.requested_role in ROLES, 'The requested role is invalid.')
            require(row.requested_role != 'manager' or data.get('confirm_manager') is True,
                    'Confirm that this applicant will receive full Farm Manager access.')
            station_id = station_ids_from_data(data)[0] if row.requested_role == 'hand' else None
            require(row.requested_role != 'hand' or db.session.get(Station, station_id), 'Choose an existing station.')
            require(not db.session.scalar(select(User.id).where(User.username == row.username)), 'This username is already registered.', 409)
            account = User(name=row.name, username=row.username, role=row.requested_role,
                           station_id=station_id, password_hash=row.password_hash, active=True)
        changed = db.session.execute(update(RegistrationRequest).where(
            RegistrationRequest.id == request_id, RegistrationRequest.state == 'Pending').values(
            state='Approved' if account else 'Rejected', pending_username=None, password_hash=None,
            reviewer_id=g.user.id, reviewed_at=now(), reason=reason).execution_options(synchronize_session=False))
        require(changed.rowcount == 1, 'This registration is already reviewed.', 409)
        if account:
            db.session.add(account)
            db.session.flush()
            if account.role == 'hand' and app.config.get('FARM_SCHEMA_READY'):
                from .service import assign_stations
                assign_stations(account, data)
            db.session.execute(update(RegistrationRequest).where(RegistrationRequest.id == request_id).values(user_id=account.id))
        audit(g.user, 'Registration approved' if account else 'Registration rejected',
              details={'request_id': request_id, 'username': row.username, 'role': row.requested_role,
                       'user_id': account.id if account else None, 'reason': reason})
        db.session.commit()
        return jsonify(state='Approved' if account else 'Rejected')

    @app.post('/api/password-reset/request')
    def request_recovery():
        started = time.monotonic()
        data = public_data()
        username = username_value(data)
        take_public_quota(username)
        user = db.session.scalar(select(User).where(User.username == username))
        # Both paths do the same cryptographic work and return the same body.
        code_hash(user.id if user else 0, '000000000000')
        if user and user.active and user.role in ('hand', 'owner'):
            open_reset_request(user)
        db.session.commit()
        # Equalise the acknowledgement path, including the first queue insertion.
        time.sleep(max(0, 0.35 - (time.monotonic() - started)))
        return jsonify(message=ACKNOWLEDGEMENT)

    @app.post('/api/password-reset-requests/<request_id>/review')
    @authenticated('manager')
    def review_recovery(request_id):
        require_account_schema()
        data = request.get_json(silent=True) or {}
        require(isinstance(data, dict), 'Enter the required review details.')
        row = db.session.get(PasswordResetRequest, request_id)
        require(row, 'Recovery request not found.', 404)
        user = db.session.get(User, row.user_id)
        require(user.role in ('hand', 'owner'), 'Manager recovery requires the server administrator.', 403)
        revision = integer(data.get('revision'), 'Request revision')
        if data.get('action') == 'issue':
            require(data.get('verified_identity') is True, 'Confirm that you have verified the account holder’s identity.')
            code, expiry = issue_code(user, row, actor=g.user, revision=revision)
            db.session.commit()
            return jsonify(code=code, expires_at=expiry)
        require(data.get('action') == 'reject', 'Choose Issue code or Reject.')
        reason = text(data.get('reason'), 'Rejection reason', True, 1000)
        changed = db.session.execute(update(PasswordResetRequest).where(
            PasswordResetRequest.id == request_id, PasswordResetRequest.revision == revision,
            PasswordResetRequest.state.in_(('Pending', 'Issued'))).values(
            state='Rejected', revision=revision + 1, open_user_id=None, code_hash=None,
            reviewer_id=g.user.id, reviewed_at=now(), reason=reason))
        require(changed.rowcount == 1, 'This request changed or is already closed.', 409)
        audit(g.user, 'Password recovery rejected', details={'request_id': request_id, 'user_id': user.id, 'reason': reason})
        db.session.commit()
        return jsonify(state='Rejected')

    @app.post('/api/password-reset/complete')
    def complete_recovery():
        data = public_data()
        username = username_value(data)
        password = new_password(data)
        attempt_key = take_public_quota(username, recovery_attempt=True)
        supplied = data.get('code')
        code = re.sub(r'[\s-]', '', supplied) if isinstance(supplied, str) else ''
        user_id = db.session.scalar(select(User.id).where(User.username == username))
        user = lock_user_credentials(user_id) if user_id else None
        row = db.session.scalar(select(PasswordResetRequest).where(
            PasswordResetRequest.user_id == user.id, PasswordResetRequest.state == 'Issued').with_for_update()) if user else None
        digest = code_hash(user.id if user else 0, code)
        matches = hmac.compare_digest(digest, row.code_hash if row and row.code_hash else '0' * 64)
        require(re.fullmatch(r'[0-9]{12}', code) and user and user.active and row and matches and
                row.expires_at > now() and row.issued_version == user.session_version,
                'The code is invalid or expired. Ask for a new code.')
        claimed = db.session.execute(update(PasswordResetRequest).where(
            PasswordResetRequest.id == row.id, PasswordResetRequest.state == 'Issued',
            PasswordResetRequest.revision == row.revision, PasswordResetRequest.code_hash == digest).values(
            state='Used', code_hash=None, open_user_id=None, used_at=now()).execution_options(synchronize_session=False))
        require(claimed.rowcount == 1, 'The code is invalid or expired. Ask for a new code.')
        changed = db.session.execute(update(User).where(
            User.id == user.id, User.active.is_(True), User.session_version == row.issued_version).values(
            password_hash=generate_password_hash(password), session_version=User.session_version + 1)
            .execution_options(synchronize_session=False))
        require(changed.rowcount == 1, 'The code is invalid or expired. Ask for a new code.')
        db.session.execute(update(PasswordResetRequest).where(
            PasswordResetRequest.user_id == user.id, PasswordResetRequest.id != row.id,
            PasswordResetRequest.state.in_(('Pending', 'Issued'))).values(state='Superseded', code_hash=None, open_user_id=None))
        db.session.execute(delete(AuthThrottle).where(AuthThrottle.key == attempt_key))
        audit(user, 'Password recovered', details={'request_id': row.id})
        db.session.commit()
        session.clear()
        return jsonify(message='Password updated. Sign in with your new password.')
