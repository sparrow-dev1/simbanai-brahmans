import os
import subprocess
import sqlite3
from pathlib import Path
from contextlib import closing
from datetime import datetime, timedelta, timezone
import click
from werkzeug.security import generate_password_hash
from sqlalchemy import select
from .models import db, User, Station, Animal, Product, Event
from .service import audit, apply_event, today
import uuid

def register_commands(app):
    @app.cli.command('upgrade-accounts')
    @click.option('--backup-directory', default='backups', type=click.Path(path_type=Path))
    @click.pass_context
    def upgrade_account_schema(context, backup_directory):
        """Back up and apply account schema revision 001 without altering farm tables."""
        from .account_schema import schema_ready, upgrade_accounts
        if schema_ready():
            click.echo('Account schema 001 is already installed; no changes made.')
            app.config['ACCOUNTS_SCHEMA_READY'] = True
            return
        context.invoke(backup, directory=backup_directory)
        try:
            upgrade_accounts()
        except ValueError as error:
            raise click.ClickException(str(error))
        app.config['ACCOUNTS_SCHEMA_READY'] = True
        click.echo('Account schema 001 installed. Existing users and farm records are preserved.')

    @app.cli.command('upgrade-farm')
    @click.option('--backup-directory', default='backups', type=click.Path(path_type=Path))
    @click.pass_context
    def upgrade_farm_schema(context, backup_directory):
        """Back up then install farm workflow revision 003, preserving existing data."""
        from .farm_schema import schema_ready, upgrade_farm
        if schema_ready():
            click.echo('Farm schema 003 is already installed; no changes made.')
            app.config['FARM_SCHEMA_READY'] = True
            return
        from .account_schema import schema_ready as accounts_ready
        if not accounts_ready():
            raise click.ClickException('Run upgrade-accounts before upgrade-farm.')
        context.invoke(backup, directory=backup_directory)
        upgrade_farm()
        app.config['FARM_SCHEMA_READY'] = True
        click.echo('Farm schema 003 installed. Existing identities, ledgers and credentials preserved.')

    @app.cli.command('issue-manager-reset')
    @click.argument('username')
    def issue_manager_reset(username):
        """Issue a one-use code for an active Manager; display it once to the operator."""
        from .accounts import issue_code
        user = db.session.scalar(select(User).where(User.username == username.strip().lower()))
        if not user or user.role != 'manager' or not user.active:
            raise click.ClickException('Choose an existing active Farm Manager account.')
        try:
            code, expiry = issue_code(user, administrator=True)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise click.ClickException('Could not issue a Manager recovery code. Verify the account schema and database availability.')
        local_expiry = datetime.fromisoformat(expiry).astimezone(timezone(timedelta(hours=2))).strftime('%Y-%m-%d %H:%M')
        click.echo(f'One-time code: {code}\nExpires (Africa/Harare): {local_expiry}\nShare privately. Enter it on the Reset password screen; do not save it in application logs.')

    @app.cli.command('setup')
    @click.option('--manager', default='manager', help='Manager username')
    @click.option('--owner', default='owner', help='Owner username')
    @click.option('--station', default='Main Station')
    def setup(manager, owner, station):
        """Create initial accounts. Passwords are requested securely."""
        if db.session.scalar(select(User.id).limit(1)):
            raise click.ClickException('Accounts already exist. Setup will not overwrite them.')
        manager_password = click.prompt('Manager password (12+ characters)', hide_input=True, confirmation_prompt=True)
        owner_password = click.prompt('Owner password (12+ characters)', hide_input=True, confirmation_prompt=True)
        if min(len(manager_password), len(owner_password)) < 12 or manager == owner:
            raise click.ClickException('Use distinct usernames and passwords of at least 12 characters.')
        db.session.add(Station(name=station))
        for username, role, password in [(manager, 'manager', manager_password), (owner, 'owner', owner_password)]:
            db.session.add(User(username=username.strip().lower(), name=role.title(), role=role, password_hash=generate_password_hash(password)))
        audit(None, 'Initial manager, owner, and station provisioned')
        db.session.commit()
        click.echo('Setup complete. Sign in and import the opening herd.')

    @app.cli.command('demo')
    def demo():
        """Create fictional pilot data in an EMPTY local development database."""
        if db.session.scalar(select(User.id).limit(1)):
            raise click.ClickException('Demo requires an empty database. Existing records are never overwritten.')
        station = Station(name='Station A')
        db.session.add_all([station, Station(name='Station B')])
        db.session.flush()
        password = 'Simbanai-Demo-2026!'
        manager = User(username='manager', name='Farm Manager', role='manager', password_hash=generate_password_hash(password))
        owner = User(username='owner', name='Farm Owner', role='owner', password_hash=generate_password_hash(password))
        hand = User(username='hand', name='General Hand', role='hand', station_id=station.id, password_hash=generate_password_hash(password))
        db.session.add_all([manager, owner, hand])
        for i in range(1, 88):
            category = 'Cow' if i <= 45 else ('Heifer' if i <= 65 else ('Bull' if i <= 70 else 'Calf'))
            db.session.add(Animal(identifier=f'SB-{i:04}', sex='Male' if category == 'Bull' else 'Female', category=category,
                                  breed='Brahman', station_id=station.id, dob='2022-01-01' if category != 'Calf' else '2026-06-01', birth_place='Station A'))
        products = [Product(name='Dip concentrate', category='Medicine', unit='L', minimum=5),
                    Product(name='Dewormer', category='Medicine', unit='mL', minimum=200),
                    Product(name='Stock feed', category='Feed', unit='kg', minimum=100),
                    Product(name='Diesel', category='Fuel', unit='L', minimum=20)]
        db.session.add_all(products)
        db.session.flush()
        for product, quantity in zip(products, ['20', '1000', '500', '100']):
            payload = dict(kind='stock_in', date=today().isoformat(), station_id=station.id, animal_ids=[], versions={}, products=[dict(product_id=product.id, quantity=quantity, dosage='')], notes='Fictional demo opening stock', receipt_type='Opening balance', amount='0', currency=None, reference='Demo')
            event = Event(id=str(uuid.uuid4()), kind='stock_in', date=payload['date'], station_id=station.id, payload=payload, state='Pending approval', author_id=manager.id)
            db.session.add(event)
            db.session.flush()
            apply_event(event, manager)
        audit(None, 'Loaded fictional demo: 87 cattle at Station A')
        db.session.commit()
        click.echo('Fictional demo ready. Usernames: manager, owner, hand. Password: Simbanai-Demo-2026!')

    @app.cli.command('backup')
    @click.option('--directory', default='backups', type=click.Path(path_type=Path))
    def backup(directory):
        """Back up the database. Schedule daily through Task Scheduler."""
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = __import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        engine = db.engine
        if engine.dialect.name == 'sqlite':
            target = directory / f'cattle-{timestamp}.sqlite'
            with closing(sqlite3.connect(engine.url.database)) as source, closing(sqlite3.connect(target)) as dest:
                source.backup(dest)
                result = dest.execute('PRAGMA integrity_check').fetchone()[0]
                if result != 'ok':
                    raise click.ClickException('Backup integrity check failed.')
            click.echo(f'Backup created and integrity checked: {target.resolve()}')
        else:
            target = directory / f'cattle-{timestamp}.dump'
            url = engine.url
            env = os.environ.copy()
            if url.password:
                env['PGPASSWORD'] = url.password
            command = ['pg_dump', '--format=custom', '--file', str(target), '--host', url.host or 'localhost', '--port', str(url.port or 5432), '--username', url.username or 'postgres', url.database]
            try:
                subprocess.run(command, env=env, check=True, capture_output=True)
                subprocess.run(['pg_restore', '--list', str(target)], check=True, capture_output=True)
            except (OSError, subprocess.CalledProcessError):
                raise click.ClickException('PostgreSQL backup failed. Check pg_dump/pg_restore installation and connection permissions.')
            click.echo(f'Backup created and archive checked: {target.resolve()}. Perform a full restore into a separate database before launch.')

    @app.cli.command('verify-sqlite-backup')
    @click.option('--compare-current', is_flag=True, help='Confirm restored farm identities match the configured database.')
    @click.argument('backup_file', type=click.Path(exists=True, path_type=Path))
    def verify_sqlite_backup(backup_file, compare_current=False):
        """Restore a local backup into memory and validate its contents."""
        with closing(sqlite3.connect(f'file:{backup_file.resolve().as_posix()}?mode=ro', uri=True)) as source, closing(sqlite3.connect(':memory:')) as restored:
            source.backup(restored)
            if restored.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or restored.execute('PRAGMA foreign_key_check').fetchall():
                raise click.ClickException('Restored backup failed integrity checks.')
            counts = {table: restored.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in ['animal', 'event', 'user']}
            if compare_current:
                if db.engine.dialect.name != 'sqlite':
                    raise click.ClickException('Selected deployment database is not SQLite.')
                with closing(sqlite3.connect(db.engine.url.database)) as current:
                    for table, columns in [('animal', 'id,identifier'), ('event', 'id'), ('station', 'id,name'), ('user', 'id,username')]:
                        sql = f'SELECT {columns} FROM {table} ORDER BY id'
                        if current.execute(sql).fetchall() != restored.execute(sql).fetchall():
                            raise click.ClickException('Backup does not match the configured farm identities. Make a fresh backup before scheduling.')
        click.echo(f'Restore verified: {counts}')
