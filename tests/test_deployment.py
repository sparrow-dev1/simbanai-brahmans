"""Backup identity checks use disposable SQLite databases, never installed farm data."""
import unittest
from pathlib import Path
from cattle import create_app
from cattle.models import db, Station
from test_accounts import account_test_directory

class BackupVerificationTests(unittest.TestCase):
    def test_restored_backup_matches_selected_farm_before_scheduling(self):
        with account_test_directory() as directory:
            root=Path(directory).resolve()
            application=create_app({'TESTING':True,'SECRET_KEY':'isolated-backup-test','SQLALCHEMY_DATABASE_URI':'sqlite:///'+(root/'source.sqlite').as_posix()})
            with application.app_context():
                station=Station(name='Fictional verification station')
                db.session.add(station);db.session.commit()
                runner=application.test_cli_runner()
                result=runner.invoke(args=['backup','--directory',str(root/'backups')])
                self.assertEqual(result.exit_code,0,result.output)
                backup=next((root/'backups').glob('*.sqlite'))
                result=runner.invoke(args=['verify-sqlite-backup','--compare-current',str(backup)])
                self.assertEqual(result.exit_code,0,result.output)
                station.name='Different source';db.session.commit()
                result=runner.invoke(args=['verify-sqlite-backup','--compare-current',str(backup)])
                self.assertNotEqual(result.exit_code,0)
                self.assertIn('does not match',result.output)
                db.session.remove();db.engine.dispose()
