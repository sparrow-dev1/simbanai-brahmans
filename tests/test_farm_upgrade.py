"""Revision 002 is explicit, backed up and repeatable on a disposable database."""
import sqlite3
import uuid
from contextlib import contextmanager, closing
import unittest
from pathlib import Path
from cattle import create_app
from cattle.models import db, User, Station, Animal, Product, SchemaMigration, UserStation, FarmSetting
from cattle.farm_schema import VERSION

@contextmanager
def farm_test_directory(root):
    folder=root/('upgrade-002-'+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    yield folder

class FarmUpgradeTests(unittest.TestCase):
    def test_explicit_backed_up_revision_preserves_existing_data(self):
        root=Path(__file__).resolve().parents[1]/'test-output'
        root.mkdir(exist_ok=True)
        with farm_test_directory(root) as folder:
            filename=Path(folder)/'fictional.sqlite'
            config={'TESTING':True,'SECRET_KEY':'isolated-upgrade','SQLALCHEMY_DATABASE_URI':'sqlite:///'+filename.as_posix()}
            app=create_app(config)
            with app.app_context():
                station=Station(name='Existing fictional station');db.session.add(station);db.session.flush()
                db.session.add_all([User(name='Existing Hand',username='existing',role='hand',station_id=station.id,password_hash='preserve-this-hash'),Animal(identifier='EXISTING-ONLY',sex='Female',category='Cow',station_id=station.id),Product(name='Existing product',category='Medicine',unit='L',minimum=2)])
                db.session.commit();db.session.delete(db.session.get(SchemaMigration,VERSION));db.session.commit()
                UserStation.__table__.drop(db.engine);FarmSetting.__table__.drop(db.engine)
                with db.engine.begin() as connection:connection.exec_driver_sql('ALTER TABLE product DROP COLUMN active')
                db.session.remove();db.engine.dispose()
            def original_rows(path):
                with closing(sqlite3.connect(path)) as connection:
                    return {table:connection.execute('SELECT * FROM "'+table+'" ORDER BY id').fetchall() for table in ['user','station','animal','stock_transaction','financial_transaction']}
            before=original_rows(filename)
            app=create_app(config);self.assertFalse(app.config['FARM_SCHEMA_READY'])
            self.assertEqual(app.test_client().get('/api/reference').status_code,503)
            result=app.test_cli_runner().invoke(args=['upgrade-farm','--backup-directory',str(Path(folder)/'backups')])
            self.assertEqual(result.exit_code,0,result.output);self.assertEqual(before,original_rows(filename))
            repeated=app.test_cli_runner().invoke(args=['upgrade-farm','--backup-directory',str(Path(folder)/'backups')])
            self.assertEqual(repeated.exit_code,0,repeated.output);self.assertIn('no changes',repeated.output)
            backups=list((Path(folder)/'backups').glob('*.sqlite'));self.assertEqual(len(backups),1);self.assertEqual(before,original_rows(backups[0]))
            with app.app_context():
                self.assertEqual(db.session.query(UserStation).count(),1)
                self.assertTrue(db.session.query(Product).one().active)
                self.assertEqual(db.session.get(FarmSetting,'calf_review_months').value,'6')
                db.session.remove();db.engine.dispose()
