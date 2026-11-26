"""Explicit additive account schema revision; never alters farm/user tables."""
from sqlalchemy import inspect
from .models import db, SchemaMigration, RegistrationRequest, PasswordResetRequest, AuthThrottle

VERSION = '001_accounts'
TABLES = [SchemaMigration.__table__, RegistrationRequest.__table__, PasswordResetRequest.__table__, AuthThrottle.__table__]


def schema_ready():
    inspector = inspect(db.engine)
    names = set(inspector.get_table_names())
    if not all(table.name in names for table in TABLES):
        return False
    return db.session.get(SchemaMigration, VERSION) is not None


def upgrade_accounts():
    # Refuse conflicting partial schemas before performing any DDL.
    inspector = inspect(db.engine)
    names = set(inspector.get_table_names())
    for table in TABLES:
        if table.name in names:
            actual = {column['name'] for column in inspector.get_columns(table.name)}
            if actual != set(table.columns.keys()):
                raise ValueError(f'Account table {table.name} has an incompatible schema.')
    if schema_ready():
        return False
    db.session.rollback()
    with db.engine.begin() as connection:
        for table in TABLES:
            table.create(connection, checkfirst=True)
        connection.execute(SchemaMigration.__table__.insert().values(version=VERSION))
    return True
