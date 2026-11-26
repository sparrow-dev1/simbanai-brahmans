import json
import sqlite3
import threading
import unittest
import uuid
from contextlib import contextmanager, closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select, func
from werkzeug.security import generate_password_hash, check_password_hash

from cattle import create_app
from cattle.models import db, User, Station, Animal, Audit, RegistrationRequest, PasswordResetRequest, AuthThrottle, SchemaMigration
from cattle.account_schema import TABLES, VERSION

PASSWORD = 'original-password-123'
NEW_PASSWORD = 'replacement-password-456'
PUBLIC = {'X-Requested-With': 'Simbanai'}


@contextmanager
def account_test_directory():
    # Ordinary inherited Windows permissions also work in the restricted runner.
    folder = Path('test-output') / ('accounts-' + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    yield folder


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.app=create_app({'TESTING':True,'SECRET_KEY':'accounts-test-only','SQLALCHEMY_DATABASE_URI':'sqlite://',
                             'AUTH_REQUESTS_PER_USERNAME':100,'AUTH_REQUESTS_PER_IP':1000})
        self.context=self.app.app_context();self.context.push()
        self.seed()
        self.client=self.app.test_client()
        self.manager,self.csrf=self.login('manager')

    def seed(self):
        self.station=Station(name='Station A');db.session.add(self.station);db.session.flush()
        hashed=generate_password_hash(PASSWORD,method='pbkdf2:sha256:1000')
        for role in ('manager','owner','hand'):
            db.session.add(User(username=role,name=role.title(),role=role,password_hash=hashed,
                                station_id=self.station.id if role=='hand' else None))
        db.session.add(Animal(identifier='SB-TEST',sex='Female',category='Cow',station_id=self.station.id))
        db.session.commit()

    def tearDown(self):
        db.session.remove();db.drop_all();db.engine.dispose();self.context.pop()

    def login(self,username,password=PASSWORD):
        client=self.app.test_client()
        result=client.post('/api/login',json={'username':username,'password':password},headers=PUBLIC)
        self.assertEqual(result.status_code,200,result.json)
        return client,result.json['csrf']

    def public(self,path,data):
        return self.client.post(path,json=data,headers=PUBLIC)

    def review(self,path,data,client=None,csrf=None):
        return (client or self.manager).post(path,json=data,headers={'X-CSRF-Token':csrf or self.csrf})

    def register(self,username='candidate',role='hand'):
        return self.public('/api/register',dict(name='Candidate',username=username,role=role,password=PASSWORD,confirmation=PASSWORD))

    def registration(self,username='candidate'):
        db.session.expire_all()
        return db.session.scalar(select(RegistrationRequest).where(RegistrationRequest.username==username).order_by(RegistrationRequest.created_at.desc()))

    def approve(self,row,**extra):
        payload={'action':'approve','station_id':self.station.id,'confirm_manager':True,**extra}
        return self.review(f'/api/registration-requests/{row.id}/review',payload)

    def recovery(self,username='hand'):
        result=self.public('/api/password-reset/request',{'username':username});self.assertEqual(result.status_code,200)
        db.session.expire_all()
        user=db.session.scalar(select(User).where(User.username==username))
        return db.session.scalar(select(PasswordResetRequest).where(PasswordResetRequest.open_user_id==user.id))

    def issue(self,row,number=123456789):
        db.session.expire_all()
        with patch('cattle.accounts.secrets.randbelow',return_value=number):
            result=self.review(f'/api/password-reset-requests/{row.id}/review',
                               {'action':'issue','revision':row.revision,'verified_identity':True})
        self.assertEqual(result.status_code,200,result.json)
        return result.json['code']

    def complete(self,code,username='hand',password=NEW_PASSWORD):
        return self.public('/api/password-reset/complete',{'username':username,'code':code,'password':password,'confirmation':password})

    def test_registration_each_role_requires_approval_and_preserves_permissions(self):
        for role in ('hand','owner','manager'):
            username='new-'+role
            self.assertEqual(self.register(username,role).status_code,201)
            self.assertIsNone(db.session.scalar(select(User).where(User.username==username)))
            denied=self.client.post('/api/login',json={'username':username,'password':PASSWORD},headers=PUBLIC)
            self.assertEqual(denied.status_code,401)
            row=self.registration(username);self.assertTrue(check_password_hash(row.password_hash,PASSWORD))
            self.assertEqual(self.approve(row).status_code,200)
            client,token=self.login(username)
            registered=db.session.scalar(select(User).where(User.username==username))
            self.assertEqual(registered.role,role)
            self.assertEqual(registered.station_id,self.station.id if role=='hand' else None)
            self.assertEqual(client.get('/api/account-requests').status_code,200 if role=='manager' else 403)
            self.assertEqual(client.get('/api/money').status_code,403 if role=='hand' else 200)
            if role=='owner':
                denied=client.post('/api/stations',json={'name':'Forbidden'},headers={'X-CSRF-Token':token})
                self.assertEqual(denied.status_code,403)
            db.session.expire_all();self.assertIsNone(db.session.get(RegistrationRequest,row.id).password_hash)
        self.assertEqual(db.session.scalar(select(func.count(Animal.id))),1)

    def test_approval_requires_station_and_manager_confirmation(self):
        self.register();row=self.registration()
        self.assertEqual(self.approve(row,station_id=None).status_code,422)
        self.assertEqual(self.approve(row,station_id=99999).status_code,422)
        self.register('newmanager','manager');row=self.registration('newmanager')
        self.assertEqual(self.approve(row,confirm_manager=False).status_code,422)
        self.assertEqual(self.approve(row).status_code,200)

    def test_reject_reason_and_reapplication(self):
        self.register();row=self.registration()
        path=f'/api/registration-requests/{row.id}/review'
        self.assertEqual(self.review(path,{'action':'reject'}).status_code,422)
        self.assertEqual(self.review(path,{'action':'reject','reason':'Apply with the correct name'}).status_code,200)
        db.session.expire_all();self.assertIsNone(db.session.get(RegistrationRequest,row.id).password_hash)
        self.assertEqual(self.register().status_code,201)
        self.assertEqual(db.session.scalar(select(func.count(RegistrationRequest.id))),2)

    def test_duplicate_username_case_normalisation_and_repeat_approval(self):
        self.assertEqual(self.register(' MANAGER ').status_code,409)
        self.assertEqual(self.register(' Candidate ').status_code,201)
        self.assertEqual(self.register('CANDIDATE').status_code,409)
        row=self.registration();self.assertEqual(self.approve(row).status_code,200)
        self.assertEqual(self.approve(row).status_code,409)
        self.assertEqual(db.session.scalar(select(func.count(User.id)).where(User.username=='candidate')),1)

    def test_manual_account_cannot_occupy_pending_username(self):
        self.register()
        result=self.review('/api/users',dict(name='Other',username='candidate',password=PASSWORD,station_id=self.station.id))
        self.assertEqual(result.status_code,409)

    def test_review_permissions_and_csrf(self):
        self.register();row=self.registration()
        path=f'/api/registration-requests/{row.id}/review'
        self.assertEqual(self.client.post(path,json={'action':'approve'}).status_code,401)
        self.assertEqual(self.manager.post(path,json={'action':'approve'}).status_code,403)
        self.assertEqual(self.manager.post(path,json=['invalid-review'],headers={'X-CSRF-Token':self.csrf}).status_code,422)
        for role in ('owner','hand'):
            client,token=self.login(role)
            self.assertEqual(client.get('/api/account-requests').status_code,403)
            self.assertEqual(self.review(path,{'action':'approve'},client,token).status_code,403)

    def test_public_validation_and_no_initial_manager_bootstrap(self):
        self.assertEqual(self.client.post('/api/register',json={}).status_code,403)
        self.assertEqual(self.client.post('/api/register',json={},headers={**PUBLIC,'Origin':'https://untrusted.example'}).status_code,403)
        for change in ({'role':'administrator'},{'password':'short'},{'confirmation':'wrong'},{'name':''}):
            payload=dict(name='Candidate',username='candidate',role='hand',password=PASSWORD,confirmation=PASSWORD,**{})
            payload.update(change)
            self.assertEqual(self.public('/api/register',payload).status_code,422)
        db.session.scalar(select(User).where(User.role=='manager')).active=False;db.session.commit()
        self.assertEqual(self.register(role='manager').status_code,503)

    def test_recovery_acknowledgement_known_unknown_disabled_and_manager(self):
        results=[self.public('/api/password-reset/request',{'username':name}).json for name in ('hand','unknown','manager')]
        self.assertEqual(results[0],results[1]);self.assertEqual(results[0],results[2])
        user=db.session.scalar(select(User).where(User.username=='owner'));user.active=False;db.session.commit()
        self.assertEqual(self.public('/api/password-reset/request',{'username':'owner'}).json,results[0])
        self.assertEqual(db.session.scalar(select(func.count(PasswordResetRequest.id))),1)
        self.public('/api/password-reset/request',{'username':'hand'})
        self.assertEqual(db.session.scalar(select(func.count(PasswordResetRequest.id))),1)

    def test_owner_and_hand_reset_leading_zeros_single_use_and_session_revocation(self):
        for username in ('hand','owner'):
            old_client,_=self.login(username)
            row=self.recovery(username);code=self.issue(row,123)
            self.assertEqual(code,'0000 0000 0123')
            self.assertEqual(self.complete(code.replace(' ','-'),username).status_code,200)
            self.assertEqual(self.complete(code,username).status_code,422)
            self.assertEqual(old_client.get('/api/reference').status_code,401)
            new_client,_=self.login(username,NEW_PASSWORD)
            self.assertEqual(new_client.get('/api/reference').status_code,200)
            db.session.expire_all();user=db.session.scalar(select(User).where(User.username==username))
            self.assertEqual(user.role,username);self.assertTrue(user.active);self.assertEqual(user.session_version,2)
            self.assertEqual(user.station_id,self.station.id if username=='hand' else None)

    def test_code_wrong_username_password_confirmation_and_expiry(self):
        row=self.recovery();code=self.issue(row)
        self.assertEqual(self.complete(code,'owner').status_code,422)
        self.assertEqual(self.complete('9999 9999 9999').status_code,422)
        payload={'username':'hand','code':code,'password':NEW_PASSWORD,'confirmation':'different'}
        self.assertEqual(self.public('/api/password-reset/complete',payload).status_code,422)
        db.session.expire_all();row=db.session.get(PasswordResetRequest,row.id)
        row.expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat();db.session.commit()
        self.assertEqual(self.complete(code).status_code,422)
        self.login('hand')

    def test_reissue_invalidates_previous_and_duplicate_review_is_blocked(self):
        row=self.recovery();old_revision=row.revision;code=self.issue(row,123)
        stale=self.review(f'/api/password-reset-requests/{row.id}/review',{'action':'issue','revision':old_revision,'verified_identity':True})
        self.assertEqual(stale.status_code,409)
        new_code=self.issue(row,456)
        self.assertEqual(self.complete(code).status_code,422)
        self.assertEqual(self.complete(new_code).status_code,200)

    def test_credential_changes_and_disabled_accounts_invalidate_codes(self):
        row=self.recovery();code=self.issue(row)
        client,csrf=self.login('hand')
        self.assertEqual(client.post('/api/account/password',json={'current':PASSWORD,'password':NEW_PASSWORD},headers={'X-CSRF-Token':csrf}).status_code,200)
        self.assertEqual(self.complete(code).status_code,422)
        row=self.recovery('owner');code=self.issue(row)
        user=db.session.scalar(select(User).where(User.username=='owner'));user.active=False;db.session.commit()
        self.assertEqual(self.complete(code,'owner').status_code,422)
        db.session.expire_all();self.assertFalse(db.session.get(User,user.id).active)

    def test_recovery_requires_verified_identity_and_rejection_reason(self):
        row=self.recovery();path=f'/api/password-reset-requests/{row.id}/review'
        self.assertEqual(self.review(path,{'action':'issue','revision':row.revision}).status_code,422)
        self.assertEqual(self.review(path,{'action':'reject','revision':row.revision}).status_code,422)
        self.assertEqual(self.review(path,{'action':'reject','revision':row.revision,'reason':'Unable to verify identity'}).status_code,200)
        self.assertEqual(self.review(path,{'action':'issue','revision':row.revision,'verified_identity':True}).status_code,409)

    def test_manager_cli_recovery_and_web_restriction(self):
        with patch('cattle.accounts.secrets.randbelow',return_value=123):
            result=self.app.test_cli_runner().invoke(args=['issue-manager-reset','manager'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertIn('0000 0000 0123',result.output)
        user=db.session.scalar(select(User).where(User.username=='manager'))
        row=db.session.scalar(select(PasswordResetRequest).where(PasswordResetRequest.user_id==user.id))
        self.assertEqual(self.review(f'/api/password-reset-requests/{row.id}/review',{'action':'issue','revision':row.revision,'verified_identity':True}).status_code,403)
        self.assertEqual(self.complete('0000 0000 0123','manager').status_code,200)
        self.login('manager',NEW_PASSWORD)
        self.assertNotEqual(self.app.test_cli_runner().invoke(args=['issue-manager-reset','owner']).exit_code,0)

    def test_secret_values_never_appear_in_lists_or_audit(self):
        self.register();row=self.recovery();code=self.issue(row,123)
        response=self.manager.get('/api/account-requests');self.assertEqual(response.status_code,200)
        serialised=json.dumps(response.json)+json.dumps([a.details for a in db.session.scalars(select(Audit))])
        for secret in (PASSWORD,code,'code_hash','password_hash'):
            self.assertNotIn(secret,serialised)
        db.session.expire_all();self.assertNotEqual(db.session.get(PasswordResetRequest,row.id).code_hash,code.replace(' ',''))
        self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_request_throttles_are_database_backed_and_configurable(self):
        self.app.config['AUTH_REQUESTS_PER_USERNAME']=5
        for _ in range(5):self.assertEqual(self.public('/api/password-reset/request',{'username':'unknown'}).status_code,200)
        result=self.public('/api/password-reset/request',{'username':'unknown'})
        self.assertEqual(result.status_code,429);self.assertIn('Retry-After',result.headers)
        self.assertGreater(db.session.scalar(select(func.count(AuthThrottle.key))),0)
        self.app.config['AUTH_REQUESTS_PER_IP']=7
        self.assertEqual(self.public('/api/password-reset/request',{'username':'another'}).status_code,200)
        self.assertEqual(self.public('/api/password-reset/request',{'username':'third'}).status_code,200)
        self.assertEqual(self.public('/api/password-reset/request',{'username':'fourth'}).status_code,429)

    def test_failed_attempt_limit_does_not_disable_account(self):
        row=self.recovery();self.issue(row)
        for _ in range(5):self.assertEqual(self.complete('9999 9999 9999').status_code,422)
        self.assertEqual(self.complete('9999 9999 9999').status_code,429)
        db.session.expire_all();self.assertTrue(db.session.scalar(select(User).where(User.username=='hand')).active)
        self.login('hand')


class AccountMigrationTests(unittest.TestCase):
    def test_installed_schema_is_only_upgraded_explicitly_and_repeatably(self):
        with account_test_directory() as folder:
            filename=Path(folder)/'installed.sqlite'
            config={'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+filename.resolve().as_posix(),'SECRET_KEY':'migration-test'}
            app=create_app(config)
            with app.app_context():
                station=Station(name='Existing');db.session.add(station);db.session.flush()
                user=User(name='Existing manager',username='existing',role='manager',password_hash='unchanged-hash')
                db.session.add(user);db.session.add(Animal(identifier='EXISTING-1',sex='Female',category='Cow',station_id=station.id));db.session.commit()
                db.session.remove()
                for table in reversed(TABLES):table.drop(db.engine)
                db.engine.dispose()
            def contents():
                with closing(sqlite3.connect(filename)) as connection:
                    return {name:connection.execute(f'SELECT * FROM "{name}"').fetchall() for name in ('user','station','animal','audit')}
            before=contents();app=create_app(config)
            self.assertFalse(app.config['ACCOUNTS_SCHEMA_READY'])
            with closing(sqlite3.connect(filename)) as connection:
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='registration_request'").fetchone())
            first=app.test_cli_runner().invoke(args=['upgrade-accounts','--backup-directory',str(Path(folder)/'backups')])
            self.assertEqual(first.exit_code,0,first.output);self.assertEqual(contents(),before)
            second=app.test_cli_runner().invoke(args=['upgrade-accounts','--backup-directory',str(Path(folder)/'backups')])
            self.assertEqual(second.exit_code,0,second.output);self.assertIn('no changes',second.output)
            backups=list((Path(folder)/'backups').glob('*.sqlite'));self.assertEqual(len(backups),1)
            with closing(sqlite3.connect(backups[0])) as connection:
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(connection.execute('SELECT * FROM user').fetchall(),before['user'])
            with app.app_context():db.session.remove();db.engine.dispose()


class AccountConcurrencyTests(unittest.TestCase):
    def test_simultaneous_approval_and_redemption_apply_once(self):
        with account_test_directory() as folder:
            filename=Path(folder)/'concurrent.sqlite'
            app=create_app({'TESTING':True,'SECRET_KEY':'concurrency-test','SQLALCHEMY_DATABASE_URI':'sqlite:///'+filename.resolve().as_posix()})
            with app.app_context():
                hashed=generate_password_hash(PASSWORD,method='pbkdf2:sha256:1000')
                station=Station(name='Test');db.session.add(station);db.session.flush();station_id=station.id
                db.session.add_all([User(name='Manager',username='manager',role='manager',password_hash=hashed),User(name='Hand',username='hand',role='hand',station_id=station_id,password_hash=hashed)])
                db.session.commit()
            # Manual creation and public registration share one username namespace.
            barrier=threading.Barrier(2)
            def claim_username(manual):
                client=app.test_client()
                if manual:
                    login=client.post('/api/login',json={'username':'manager','password':PASSWORD},headers=PUBLIC)
                barrier.wait(timeout=10)
                if manual:
                    return client.post('/api/users',json=dict(name='Manual',username='contested',password=PASSWORD,station_id=station_id),headers={'X-CSRF-Token':login.json['csrf']}).status_code
                return client.post('/api/register',json=dict(name='Applicant',username='contested',role='hand',password=PASSWORD,confirmation=PASSWORD),headers=PUBLIC).status_code
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(claim_username,(True,False)))
            self.assertEqual(sorted(statuses),[201,409])
            with app.app_context():
                accounts=db.session.scalar(select(func.count(User.id)).where(User.username=='contested'))
                requests=db.session.scalar(select(func.count(RegistrationRequest.id)).where(RegistrationRequest.pending_username=='contested'))
                self.assertEqual(accounts+requests,1)
            anonymous=app.test_client()
            self.assertEqual(anonymous.post('/api/register',json=dict(name='Candidate',username='candidate',role='hand',password=PASSWORD,confirmation=PASSWORD),headers=PUBLIC).status_code,201)
            with app.app_context():registration_id=db.session.scalar(select(RegistrationRequest.id).where(RegistrationRequest.username=='candidate'))
            barrier=threading.Barrier(2)
            def approve(_):
                client=app.test_client();login=client.post('/api/login',json={'username':'manager','password':PASSWORD},headers=PUBLIC)
                barrier.wait(timeout=10)
                return client.post(f'/api/registration-requests/{registration_id}/review',json={'action':'approve','station_id':station_id},headers={'X-CSRF-Token':login.json['csrf']}).status_code
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(approve,range(2)))
            self.assertEqual(sorted(statuses),[200,409])
            with app.app_context():
                self.assertEqual(db.session.scalar(select(func.count(User.id)).where(User.username=='candidate')),1)
            manager=app.test_client();login=manager.post('/api/login',json={'username':'manager','password':PASSWORD},headers=PUBLIC)
            anonymous.post('/api/password-reset/request',json={'username':'hand'},headers=PUBLIC)
            with app.app_context():row=db.session.scalar(select(PasswordResetRequest));reset_id=row.id;revision=row.revision
            result=manager.post(f'/api/password-reset-requests/{reset_id}/review',json={'action':'issue','revision':revision,'verified_identity':True},headers={'X-CSRF-Token':login.json['csrf']})
            self.assertEqual(result.status_code,200);code=result.json['code'];barrier=threading.Barrier(2)
            def redeem(_):
                client=app.test_client();barrier.wait(timeout=10)
                return client.post('/api/password-reset/complete',json={'username':'hand','code':code,'password':NEW_PASSWORD,'confirmation':NEW_PASSWORD},headers=PUBLIC).status_code
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(redeem,range(2)))
            self.assertEqual(sorted(statuses),[200,422])
            barrier=threading.Barrier(2)
            def change_password(_):
                client=app.test_client()
                login=client.post('/api/login',json={'username':'hand','password':NEW_PASSWORD},headers=PUBLIC)
                barrier.wait(timeout=10)
                return client.post('/api/account/password',json={'current':NEW_PASSWORD,'password':PASSWORD},headers={'X-CSRF-Token':login.json['csrf']}).status_code
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(change_password,range(2)))
            self.assertEqual(sorted(statuses),[200,401])
            with app.app_context():
                self.assertEqual(db.session.scalar(select(User).where(User.username=='hand')).session_version,3)
                self.assertEqual(db.session.scalar(select(func.count(Audit.id)).where(Audit.action=='Password recovered')),1)
                db.session.remove();db.engine.dispose()


if __name__=='__main__':unittest.main()
