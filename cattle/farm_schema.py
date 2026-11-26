"""Explicit revision 003: dashboard profile avatars, plus prior farm workflow tables."""
from sqlalchemy import inspect, text, select
from .models import db, SchemaMigration, UserStation, FarmSetting, ProfileAvatar

VERSION = '003_dashboard_avatar'

def schema_ready():
    inspector = inspect(db.engine)
    names = set(inspector.get_table_names())
    if not {'schema_migration','user_station','farm_setting','profile_avatar','product'} <= names:
        return False
    return 'active' in {c['name'] for c in inspector.get_columns('product')} and db.session.get(SchemaMigration, VERSION) is not None

def upgrade_farm():
    if schema_ready():
        return False
    inspector = inspect(db.engine)
    columns = {c['name'] for c in inspector.get_columns('product')}
    db.session.rollback()
    with db.engine.begin() as connection:
        if 'active' not in columns:
            connection.execute(text('ALTER TABLE product ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE'))
        for table in [UserStation.__table__, FarmSetting.__table__, ProfileAvatar.__table__]:
            table.create(connection, checkfirst=True)
        if connection.dialect.name == 'postgresql':
            connection.execute(text('ALTER TABLE stock_transaction ALTER COLUMN quantity TYPE NUMERIC(18,6)'))
        # SQLite NUMERIC affinity already preserves the additional decimal places.
        connection.execute(text("INSERT INTO user_station(user_id,station_id) SELECT id,station_id FROM \"user\" WHERE role='hand' AND station_id IS NOT NULL ON CONFLICT DO NOTHING"))
        connection.execute(text("INSERT INTO farm_setting(key,value) VALUES ('calf_review_months','6') ON CONFLICT DO NOTHING"))
        connection.execute(SchemaMigration.__table__.insert().values(version=VERSION))
    return True
