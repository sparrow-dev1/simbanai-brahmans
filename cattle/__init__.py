import os
import secrets
from pathlib import Path
from datetime import timedelta
from flask import Flask, jsonify, request
from sqlalchemy import event as sql_event, inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from .models import db

def create_app(config=None):
    app = Flask(__name__, static_folder='../static', template_folder='../templates')
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    secret = os.getenv('SECRET_KEY')
    if not secret:
        secret_file = Path(app.instance_path) / 'session-secret'
        if not secret_file.exists():
            secret_file.write_text(secrets.token_hex(32), encoding='utf-8')
        secret = secret_file.read_text(encoding='utf-8').strip()
    url = os.getenv('DATABASE_URL', 'sqlite:///' + str(Path(app.instance_path) / 'cattle.db'))
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    app.config.update(SECRET_KEY=secret, SQLALCHEMY_DATABASE_URI=url,
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, MAX_CONTENT_LENGTH=5*1024*1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
                      SESSION_COOKIE_SECURE=os.getenv('HTTPS_ONLY') == '1',
                      PERMANENT_SESSION_LIFETIME=timedelta(days=7),
                      SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters': True},
                      AUTH_REQUESTS_PER_USERNAME=int(os.getenv('AUTH_REQUESTS_PER_USERNAME', '5')),
                      AUTH_REQUESTS_PER_IP=int(os.getenv('AUTH_REQUESTS_PER_IP', '30')),
                      AUTH_CODE_ATTEMPTS=int(os.getenv('AUTH_CODE_ATTEMPTS', '5')))
    if config:
        app.config.update(config)
    db.init_app(app)
    from .routes import register_routes
    from .commands import register_commands
    register_routes(app)
    register_commands(app)
    with app.app_context():
        if db.engine.dialect.name == 'sqlite':
            @sql_event.listens_for(db.engine, 'connect')
            def sqlite_fk(connection, record):
                connection.execute('PRAGMA foreign_keys=ON')
        if not inspect(db.engine).get_table_names():
            db.create_all()
            from .account_schema import VERSION
            from .models import SchemaMigration
            db.session.add(SchemaMigration(version=VERSION))
            from .farm_schema import VERSION as FARM_VERSION
            db.session.add(SchemaMigration(version=FARM_VERSION))
            db.session.commit()
        from .account_schema import schema_ready
        app.config['ACCOUNTS_SCHEMA_READY'] = schema_ready()
        from .farm_schema import schema_ready as farm_ready
        app.config['FARM_SCHEMA_READY'] = farm_ready()

    @app.before_request
    def installed_farm_schema():
        if request.path.startswith('/api/') and request.path not in ['/api/session','/api/login','/api/logout'] and not request.path.startswith(('/api/register','/api/password-reset','/api/account','/api/registration-requests')):
            if not app.config.get('FARM_SCHEMA_READY'):
                return jsonify(error='Farm schema upgrade required. Run flask --app app upgrade-farm; your saved drafts are unchanged.'), 503

    @app.errorhandler(IntegrityError)
    def integrity_error(error):
        db.session.rollback()
        return jsonify(error='A duplicate identifier or concurrent change was detected. Refresh and review the record.'), 409

    @app.errorhandler(OperationalError)
    def database_error(error):
        db.session.rollback()
        app.logger.exception('Database operation failed')
        return jsonify(error='The database is unavailable or busy. Your saved draft is safe; try again.'), 503

    @app.errorhandler(404)
    def missing(error):
        if request.path.startswith('/api/'):
            return jsonify(error='Record or endpoint not found.'), 404
        return error

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return jsonify(error='The operation could not be completed. Nothing was committed; try again.'), 500

    return app
