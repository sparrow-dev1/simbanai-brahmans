from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def now():
    return datetime.now(timezone.utc).isoformat()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    role = db.Column(db.String(20), nullable=False)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'))
    active = db.Column(db.Boolean, default=True, nullable=False)
    session_version = db.Column(db.Integer, default=1, nullable=False)

class Station(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

class Animal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(80), unique=True, nullable=False)
    temporary = db.Column(db.Boolean, default=False, nullable=False)
    brand = db.Column(db.String(80), default='')
    sex = db.Column(db.String(10), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    breed = db.Column(db.String(80), default='Brahman')
    dob = db.Column(db.String(10))
    birth_place = db.Column(db.String(120), default='')
    dam_id = db.Column(db.Integer, db.ForeignKey('animal.id'))
    sire_id = db.Column(db.Integer, db.ForeignKey('animal.id'))
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=False)
    lifecycle = db.Column(db.String(20), default='Active', nullable=False)
    health = db.Column(db.String(30), default='No concerns', nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(db.String(20), nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True, server_default='true')
    minimum = db.Column(db.Numeric(14, 3), nullable=False, default=0)

class Event(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    kind = db.Column(db.String(30), nullable=False)
    date = db.Column(db.String(10), nullable=False)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'))
    payload = db.Column(db.JSON, nullable=False)
    state = db.Column(db.String(30), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    reviewed_at = db.Column(db.String(40))
    created_at = db.Column(db.String(40), default=now, nullable=False)
    reason = db.Column(db.Text, default='')
    revision = db.Column(db.Integer, default=1, nullable=False)
    effects = db.Column(db.JSON, default=list, nullable=False)
    replaces_id = db.Column(db.String(36), db.ForeignKey('event.id'))

class EventAnimal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(36), db.ForeignKey('event.id'), nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('event_id', 'animal_id'),)

class StockTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    event_id = db.Column(db.String(36), db.ForeignKey('event.id'), nullable=False)
    quantity = db.Column(db.Numeric(18, 6), nullable=False)
    description = db.Column(db.String(180), nullable=False)
    reversal_of = db.Column(db.Integer, db.ForeignKey('stock_transaction.id'))

class FinancialTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(36), db.ForeignKey('event.id'), nullable=False)
    date = db.Column(db.String(10), nullable=False)
    type = db.Column(db.String(10), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    reference = db.Column(db.String(180), default='')
    source = db.Column(db.String(40), nullable=False)
    reversal_of = db.Column(db.Integer, db.ForeignKey('financial_transaction.id'))

class HealthCase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    event_id = db.Column(db.String(36), db.ForeignKey('event.id'), nullable=False)
    observation = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default='Under observation', nullable=False)
    closed_at = db.Column(db.String(10))

class Audit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.String(40), default=now, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.Text, nullable=False)
    event_id = db.Column(db.String(36), db.ForeignKey('event.id'))
    details = db.Column(db.JSON, default=dict, nullable=False)

class SchemaMigration(db.Model):
    version = db.Column(db.String(40), primary_key=True)
    applied_at = db.Column(db.String(40), default=now, nullable=False)

class RegistrationRequest(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), nullable=False)
    pending_username = db.Column(db.String(80), unique=True)
    requested_role = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.Text)
    state = db.Column(db.String(20), default='Pending', nullable=False)
    created_at = db.Column(db.String(40), default=now, nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    reviewed_at = db.Column(db.String(40))
    reason = db.Column(db.Text, default='', nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class PasswordResetRequest(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    open_user_id = db.Column(db.Integer, unique=True)
    state = db.Column(db.String(20), default='Pending', nullable=False)
    revision = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.String(40), default=now, nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    reviewed_at = db.Column(db.String(40))
    reason = db.Column(db.Text, default='', nullable=False)
    code_hash = db.Column(db.String(64))
    expires_at = db.Column(db.String(40))
    issued_version = db.Column(db.Integer)
    used_at = db.Column(db.String(40))

class AuthThrottle(db.Model):
    key = db.Column(db.String(160), primary_key=True)
    count = db.Column(db.Integer, nullable=False)
    expires_at = db.Column(db.BigInteger, nullable=False)


class UserStation(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), primary_key=True)


class ProfileAvatar(db.Model):
    """A small self-service General Hand profile image stored with farm backups."""
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    image = db.Column(db.LargeBinary, nullable=False)
    mime_type = db.Column(db.String(40), nullable=False, default='image/png')
    updated_at = db.Column(db.String(40), default=now, nullable=False)


class FarmSetting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(120), nullable=False)
