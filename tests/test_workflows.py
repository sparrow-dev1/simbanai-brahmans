import io
import uuid
import unittest
from copy import deepcopy
from decimal import Decimal
from sqlalchemy import select, func
from werkzeug.security import generate_password_hash
from cattle import create_app
from cattle.models import db, User, Station, Animal, Product, Event, EventAnimal, StockTransaction, FinancialTransaction, HealthCase, Audit, ProfileAvatar
from cattle.service import today, stock_balance


class FarmWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'SECRET_KEY': 'test-only'})
        self.context = self.app.app_context()
        self.context.push()
        self.station = Station(name='Station A')
        self.destination = Station(name='Station B')
        db.session.add_all([self.station, self.destination])
        db.session.flush()
        password_hash = generate_password_hash('test-password-123', method='pbkdf2:sha256:1000')
        self.manager = User(username='manager', name='Manager', role='manager', password_hash=password_hash)
        self.owner = User(username='owner', name='Owner', role='owner', password_hash=password_hash)
        self.hand = User(username='hand', name='Hand', role='hand', password_hash=password_hash, station_id=self.station.id)
        db.session.add_all([self.manager, self.owner, self.hand])
        self.animals = [Animal(identifier=f'SB-{i:04}', sex='Female', category='Cow', station_id=self.station.id, dob='2020-01-01') for i in range(1, 88)]
        db.session.add_all(self.animals)
        self.product = Product(name='Dip', category='Medicine', unit='L', minimum=5)
        self.feed = Product(name='Feed', category='Feed', unit='kg', minimum=10)
        db.session.add_all([self.product, self.feed])
        db.session.commit()
        self.clients = {}
        for role in ['manager', 'owner', 'hand']:
            client = self.app.test_client()
            result = client.post('/api/login', json={'username': role, 'password': 'test-password-123'}, headers={'X-Requested-With': 'Simbanai'})
            self.assertEqual(result.status_code, 200)
            self.clients[role] = (client, result.json['csrf'])

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def post(self, path, data, role='manager'):
        client, token = self.clients[role]
        return client.post(path, json=data, headers={'X-CSRF-Token': token})

    def get(self, path, role='manager'):
        return self.clients[role][0].get(path)

    def payload(self, kind, ids=None, **fields):
        animal_ids = ids if ids is not None else [self.animals[0].id]
        versions = {str(i): db.session.get(Animal, i).version for i in animal_ids}
        return dict(kind=kind, date=today().isoformat(), station_id=self.station.id,
                    animal_ids=animal_ids, versions=versions, products=[], notes='', **fields)

    def submit(self, payload, role='manager', event_id=None):
        return self.post('/api/events', {'id': event_id or str(uuid.uuid4()), 'payload': payload}, role)

    def review(self, event, action='approve', reason=''):
        return self.post('/api/events/'+event['id']+'/review', {'revision': event['revision'], 'action': action, 'reason': reason})

    def opening_stock(self, quantity='20'):
        p = self.payload('stock_in', [], receipt_type='Opening balance')
        p['products'] = [{'product_id': self.product.id, 'quantity': quantity}]
        result = self.submit(p)
        self.assertEqual(result.status_code, 201, result.json)
        return result.json['event']

    def test_offline_83_of_87_dipping_journey(self):
        self.opening_stock()
        ids = [a.id for a in self.animals[:83]]
        p = self.payload('procedure', ids, procedure='Dipping', absent_ids=[a.id for a in self.animals[83:]], next_due=(today()+__import__('datetime').timedelta(days=7)).isoformat())
        p['products'] = [{'product_id': self.product.id, 'quantity': '4', 'dosage': 'Recorded concentration'}]
        result = self.submit(p, 'hand')
        self.assertEqual(result.status_code, 201, result.json)
        e = result.json['event']
        self.assertEqual(e['state'], 'Pending approval')
        self.assertEqual(stock_balance(self.product.id), Decimal('20'))
        self.assertEqual(db.session.scalar(select(func.count(EventAnimal.id)).where(EventAnimal.event_id == e['id'])), 0)
        self.assertEqual(self.get('/api/events', 'owner').json['events'][-1]['kind'], 'stock_in')
        result = self.review(e)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(stock_balance(self.product.id), Decimal('16'))
        self.assertEqual(db.session.scalar(select(func.count(EventAnimal.id)).where(EventAnimal.event_id == e['id'])), 83)
        self.assertEqual(len(result.json['event']['payload']['absent_ids']), 4)
        self.assertTrue(any(x['id'] == e['id'] for x in self.get('/api/events', 'owner').json['events']))
        self.assertEqual(self.get('/api/overview', 'owner').json['active'], 87)
        self.assertEqual(len(self.get('/api/reports?type=Health').json['rows']), 1)
        self.assertTrue(db.session.scalar(select(Audit.id).where(Audit.event_id == e['id'])))

    def test_sync_idempotency(self):
        self.opening_stock()
        p = self.payload('procedure', procedure='Dipping')
        p['products'] = [{'product_id': self.product.id, 'quantity': '4'}]
        event_id = str(uuid.uuid4())
        first = self.submit(p, 'hand', event_id)
        second = self.submit(p, 'hand', event_id)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json['duplicate'])
        self.assertEqual(self.review(first.json['event']).status_code, 200)
        third = self.submit(p, 'hand', event_id)
        self.assertEqual(third.json['event']['state'], 'Approved')
        self.assertEqual(stock_balance(self.product.id), Decimal('16'))
        self.assertEqual(self.review(first.json['event']).status_code, 409)

    def test_general_hand_profile_picture_is_validated_and_private(self):
        from PIL import Image
        picture = io.BytesIO()
        Image.new('RGB', (360, 180), '#2F5D3A').save(picture, 'JPEG')
        picture.seek(0)
        hand, csrf = self.clients['hand']
        uploaded = hand.post('/api/account/avatar', data={'avatar': (picture, 'profile.jpg')},
                             content_type='multipart/form-data', headers={'X-CSRF-Token': csrf})
        self.assertEqual(uploaded.status_code, 200, uploaded.json)
        self.assertTrue(uploaded.json['user']['has_avatar'])
        avatar = db.session.get(ProfileAvatar, self.hand.id)
        self.assertEqual(avatar.mime_type, 'image/png')
        self.assertLessEqual(len(avatar.image), 512 * 1024)
        image = Image.open(io.BytesIO(avatar.image))
        self.assertEqual(image.size, (256, 256))
        self.assertEqual(hand.get('/api/account/avatar').status_code, 200)
        self.assertEqual(self.clients['manager'][0].get('/api/account/avatar').status_code, 403)
        self.assertEqual(self.clients['owner'][0].get('/api/account/avatar').status_code, 403)
        invalid = io.BytesIO(b'not an image')
        rejected = hand.post('/api/account/avatar', data={'avatar': (invalid, 'bad.png')},
                             content_type='multipart/form-data', headers={'X-CSRF-Token': csrf})
        self.assertEqual(rejected.status_code, 422, rejected.json)
        removed = hand.delete('/api/account/avatar', headers={'X-CSRF-Token': csrf})
        self.assertEqual(removed.status_code, 200, removed.json)
        self.assertFalse(removed.json['user']['has_avatar'])
        self.assertEqual(hand.get('/api/account/avatar').status_code, 404)

    def test_return_correct_resubmit_preserves_history(self):
        p = self.payload('health', observation='Needs review')
        e = self.submit(p, 'hand').json['event']
        result = self.review(e, 'return', 'Describe symptoms')
        self.assertEqual(result.json['event']['state'], 'Returned')
        p['observation'] = 'Limping on left hind leg'
        returned = result.json['event']
        result = self.post('/api/events/'+e['id']+'/resubmit', {'payload': p, 'revision': returned['revision']}, 'hand')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.review(result.json['event']).status_code, 200)
        logs = list(db.session.scalars(select(Audit).where(Audit.event_id == e['id'])))
        self.assertTrue(any(log.details.get('original', {}).get('observation') == 'Needs review' for log in logs))

    def test_rejection_and_return_require_reason(self):
        e = self.submit(self.payload('health', observation='Limping'), 'hand').json['event']
        self.assertEqual(self.review(e, 'reject').status_code, 422)
        self.assertEqual(self.review(e, 'return').status_code, 422)
        self.assertEqual(self.review(e, 'reject', 'Duplicate report').status_code, 200)

    def test_temporary_calf_gets_tag_without_second_animal(self):
        dam = self.animals[0]
        p = self.payload('birth', [], dam_id=dam.id, sex='Female', outcome='Live calf')
        p['versions'] = {str(dam.id): dam.version}
        e = self.submit(p, 'hand').json['event']
        self.assertEqual(db.session.scalar(select(func.count(Animal.id))), 87)
        self.assertEqual(self.review(e).status_code, 200)
        calf = db.session.scalar(select(Animal).where(Animal.temporary.is_(True)))
        self.assertEqual(calf.dam_id, dam.id)
        self.assertEqual(self.get('/api/overview').json['active'], 88)
        result = self.post(f'/api/animals/{calf.id}/identity', {'identifier': 'SB-NEW', 'category': 'Calf', 'brand': '', 'version': calf.version, 'reason': 'Permanent tagging'})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(db.session.scalar(select(func.count(Animal.id))), 88)
        self.assertEqual(self.get(f'/api/animals/{dam.id}').json['offspring'][0]['identifier'], 'SB-NEW')

    def test_stillbirth_retained_without_active_herd_increase(self):
        dam = self.animals[0]
        p = self.payload('birth', [], dam_id=dam.id, sex='Male', outcome='Stillborn')
        p['versions'] = {str(dam.id): dam.version}
        result = self.submit(p)
        self.assertEqual(result.status_code, 201, result.json)
        self.assertEqual(self.get('/api/overview').json['active'], 87)
        self.assertEqual(db.session.scalar(select(func.count(Animal.id))), 88)

    def test_duplicate_tag_blocked(self):
        p = self.payload('purchase', [], identifier=self.animals[0].identifier, sex='Female', category='Cow', amount='100', currency='USD')
        self.assertEqual(self.submit(p).status_code, 409)
        self.assertEqual(db.session.scalar(select(func.count(FinancialTransaction.id))), 0)

    def test_insufficient_stock_rolls_back_all_effects(self):
        self.opening_stock('2')
        p = self.payload('procedure', [a.id for a in self.animals[:83]], procedure='Dipping')
        p['products'] = [{'product_id': self.product.id, 'quantity': '4'}]
        e = self.submit(p, 'hand').json['event']
        result = self.review(e)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(stock_balance(self.product.id), Decimal('2'))
        self.assertEqual(db.session.get(Event, e['id']).state, 'Pending approval')
        self.assertEqual(db.session.get(Animal, self.animals[0].id).version, 1)
        self.assertEqual(db.session.scalar(select(func.count(EventAnimal.id)).where(EventAnimal.event_id == e['id'])), 0)

    def test_offline_movement_conflict(self):
        p = self.payload('movement', destination_id=self.destination.id, movement_reason='Grazing')
        pending = self.submit(p, 'hand').json['event']
        self.assertEqual(self.submit(p).status_code, 201)
        result = self.review(pending)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(db.session.get(Animal, self.animals[0].id).station_id, self.destination.id)

    def test_pending_death_does_not_change_lifecycle(self):
        e = self.submit(self.payload('death', cause='Suspected illness'), 'hand').json['event']
        self.assertEqual(db.session.get(Animal, self.animals[0].id).lifecycle, 'Active')
        self.assertEqual(self.review(e).status_code, 200)
        self.assertEqual(db.session.get(Animal, self.animals[0].id).lifecycle, 'Dead')
        self.assertEqual(self.get('/api/overview').json['active'], 86)

    def test_dead_and_sold_animals_reject_incompatible_event(self):
        for kind in ['death', 'sale']:
            a = self.animals[0] if kind == 'death' else self.animals[1]
            fields = {'cause': 'Reported cause'} if kind == 'death' else {'amount': '500', 'currency': 'USD'}
            self.assertEqual(self.submit(self.payload(kind, [a.id], **fields)).status_code, 201)
            p = self.payload('health', [a.id], observation='Offline late observation')
            e = self.submit(p, 'hand').json['event']
            self.assertEqual(self.review(e).status_code, 409)

    def test_health_case_multiple_treatments_and_resolution(self):
        self.opening_stock()
        self.assertEqual(self.submit(self.payload('health', observation='Limping')).status_code, 201)
        case = db.session.scalar(select(HealthCase))
        for _ in range(2):
            p = self.payload('treatment', case_id=case.id)
            p['products'] = [{'product_id': self.product.id, 'quantity': '1', 'dosage': 'Recorded dose'}]
            self.assertEqual(self.submit(p).status_code, 201)
        self.assertEqual(db.session.get(Animal, self.animals[0].id).health, 'Under treatment')
        self.assertEqual(self.submit(self.payload('resolve_health', case_id=case.id)).status_code, 201)
        self.assertEqual(db.session.get(Animal, self.animals[0].id).health, 'No concerns')
        self.assertEqual(db.session.scalar(select(func.count(HealthCase.id))), 1)
        self.assertEqual(stock_balance(self.product.id), Decimal('18'))

    def test_resolving_one_case_keeps_other_health_concern(self):
        self.submit(self.payload('health', observation='Limping'))
        self.submit(self.payload('health', observation='Eye irritation'))
        case = db.session.scalar(select(HealthCase).order_by(HealthCase.id))
        self.submit(self.payload('resolve_health', case_id=case.id))
        self.assertEqual(db.session.get(Animal, self.animals[0].id).health, 'Under observation')

    def test_weights_append_and_correction_preserves_original(self):
        p = self.payload('weight')
        p['weights'] = {str(self.animals[0].id): '200'}
        first = self.submit(p).json['event']
        p = self.payload('weight')
        p['weights'] = {str(self.animals[0].id): '220'}
        second = self.submit(p).json['event']
        p['weights'] = {str(self.animals[0].id): '225'}
        result = self.post('/api/events/'+second['id']+'/correct', {'revision': second['revision'], 'reason': 'Scale reading correction', 'payload': p})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(db.session.get(Event, second['id']).state, 'Corrected')
        self.assertEqual(db.session.get(Event, second['id']).payload['weights'][str(self.animals[0].id)], '220')
        rows = self.get('/api/reports?type=Growth').json['rows']
        self.assertEqual(sorted(float(r[2]) for r in rows), [200, 225])
        self.assertEqual(db.session.get(Event, first['id']).state, 'Approved')

    def test_older_event_correction_blocked_after_dependent_change(self):
        first = self.submit(self.payload('health', observation='Limping')).json['event']
        self.submit(self.payload('health', observation='Eye irritation'))
        result = self.post('/api/events/'+first['id']+'/correct', {'revision': first['revision'], 'reason': 'Correction', 'payload': self.payload('health', observation='Corrected')})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(db.session.get(Event, first['id']).state, 'Approved')

    def test_sale_purchase_and_stock_cost_recorded_once(self):
        purchase = self.payload('purchase', [], identifier='SB-NEW', sex='Male', category='Bull', amount='1000', currency='USD', reference='Supplier')
        self.assertEqual(self.submit(purchase).status_code, 201)
        sale = self.payload('sale', amount='1500', currency='ZiG', reference='Buyer')
        self.assertEqual(self.submit(sale).status_code, 201)
        stock = self.payload('stock_in', [], receipt_type='Purchase', amount='100', currency='USD', reference='Medicine supplier')
        stock['products'] = [{'product_id': self.product.id, 'quantity': '20'}]
        self.assertEqual(self.submit(stock).status_code, 201)
        usage = self.payload('stock_use', [])
        usage['products'] = [{'product_id': self.product.id, 'quantity': '4'}]
        self.assertEqual(self.submit(usage).status_code, 201)
        self.assertEqual(db.session.scalar(select(func.count(FinancialTransaction.id))), 3)
        money = self.get('/api/overview').json['money']
        self.assertEqual(Decimal(money['USD']['Expense']), Decimal('1100'))
        self.assertEqual(Decimal(money['ZiG']['Income']), Decimal('1500'))

    def test_stock_and_money_correction_reversals(self):
        stock = self.payload('stock_in', [], receipt_type='Purchase', amount='100', currency='USD')
        stock['products'] = [{'product_id': self.product.id, 'quantity': '20'}]
        original = self.submit(stock).json['event']
        for qty, cost in [('30', '200'), ('40', '300')]:
            stock['products'][0]['quantity'] = qty
            stock['amount'] = cost
            result = self.post('/api/events/'+original['id']+'/correct', {'revision': original['revision'], 'reason': 'Receipt correction', 'payload': stock})
            self.assertEqual(result.status_code, 200, result.json)
            original = result.json['event']
            self.assertEqual(stock_balance(self.product.id), Decimal(qty))
            self.assertEqual(Decimal(self.get('/api/overview').json['money']['USD']['Expense']), Decimal(cost))
        self.assertTrue(db.session.scalar(select(StockTransaction.id).where(StockTransaction.reversal_of.is_not(None))))

    def test_consumed_receipt_cannot_be_reversed_into_negative_stock(self):
        original = self.opening_stock('20')
        p = self.payload('stock_use', [])
        p['products'] = [{'product_id': self.product.id, 'quantity': '5'}]
        self.submit(p)
        corrected = deepcopy(original['payload'])
        corrected['products'][0]['quantity'] = '25'
        result = self.post('/api/events/'+original['id']+'/correct', {'revision': original['revision'], 'reason': 'Correction', 'payload': corrected})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(stock_balance(self.product.id), Decimal('15'))

    def test_permissions_and_csrf(self):
        self.assertEqual(self.get('/api/money', 'hand').status_code, 403)
        self.assertEqual(self.get('/api/activity', 'hand').status_code, 403)
        self.assertEqual(self.submit(self.payload('health', observation='Issue'), 'owner').status_code, 403)
        self.assertEqual(self.submit(self.payload('expense', [], amount='1', currency='USD', finance_category='Feed'), 'hand').status_code, 403)
        self.assertEqual(self.clients['manager'][0].post('/api/stations', json={'name': 'New'}).status_code, 403)
        e = self.submit(self.payload('health', observation='Issue'), 'hand').json['event']
        self.assertEqual(self.post('/api/events/'+e['id']+'/review', {'action':'approve','revision':e['revision']}, 'hand').status_code, 403)

    def test_stale_version_and_future_date_blocked(self):
        p = self.payload('health', observation='First')
        self.submit(p)
        self.assertEqual(self.submit(p).status_code, 409)
        p = self.payload('health', observation='Future')
        p['date'] = (today()+__import__('datetime').timedelta(days=1)).isoformat()
        self.assertEqual(self.submit(p).status_code, 422)

    def test_movement_health_warning(self):
        self.submit(self.payload('health', observation='Limping'))
        p = self.payload('movement', destination_id=self.destination.id, movement_reason='Treatment')
        self.assertEqual(self.submit(p).status_code, 422)
        p['acknowledge_health'] = True
        self.assertEqual(self.submit(p).status_code, 201)

    def test_import_preview_commit_and_duplicate_recheck(self):
        raw = 'identifier,sex,category,station,dob,dam_identifier\nNEW-DAM,Female,Cow,Station A,2020-01-01,\nNEW-CALF,Female,Calf,Station A,,NEW-DAM\n'
        result = self.post('/api/import/preview', {'csv':raw})
        self.assertTrue(result.json['can_import'], result.json)
        self.assertEqual(self.post('/api/import/commit', {'csv':raw}).status_code, 201)
        calf = db.session.scalar(select(Animal).where(Animal.identifier == 'NEW-CALF'))
        self.assertTrue(calf.dam_id)
        self.assertEqual(db.session.scalar(select(func.count(FinancialTransaction.id))), 0)
        self.assertEqual(self.post('/api/import/commit', {'csv':raw}).status_code, 422)

    def test_import_errors_do_not_partially_commit(self):
        raw = 'identifier,sex,category,station\nGOOD,Female,Cow,Station A\nBAD,Female,Cow,Unknown\n'
        result = self.post('/api/import/preview', {'csv':raw})
        self.assertFalse(result.json['can_import'])
        self.assertEqual(self.post('/api/import/commit', {'csv':raw}).status_code, 422)
        self.assertFalse(db.session.scalar(select(Animal).where(Animal.identifier == 'GOOD')))

    def test_pdf_and_report_filters(self):
        self.submit(self.payload('health', observation='Limping'))
        result = self.get('/api/reports.pdf?type=Health', 'owner')
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.data.startswith(b'%PDF'))
        self.assertEqual(len(self.get('/api/reports?type=Health&station='+str(self.destination.id)).json['rows']), 0)
        self.assertEqual(self.get('/api/reports.pdf', 'hand').status_code, 403)

    def test_owner_sees_official_only_and_unauthenticated_denied(self):
        self.submit(self.payload('health', observation='Pending'), 'hand')
        self.assertEqual(self.get('/api/events', 'owner').json['events'], [])
        self.assertEqual(self.app.test_client().get('/api/reference').status_code, 401)

    def test_product_quantity_aggregation_blocks_overuse(self):
        self.opening_stock('5')
        p = self.payload('stock_use', [])
        p['products'] = [{'product_id':self.product.id,'quantity':'3'}, {'product_id':self.product.id,'quantity':'3'}]
        self.assertEqual(self.submit(p).status_code, 409)
        self.assertEqual(stock_balance(self.product.id), Decimal('5'))

    def test_purchase_correction_preserves_animal_and_reverses_expense(self):
        p = self.payload('purchase', [], identifier='NEW-BULL', sex='Male', category='Bull', amount='1000', currency='USD')
        original = self.submit(p).json['event']
        animal = db.session.scalar(select(Animal).where(Animal.identifier == 'NEW-BULL'))
        animal_id = animal.id
        for amount_value in ['1100', '1200']:
            p['amount'] = amount_value
            result = self.post('/api/events/'+original['id']+'/correct', {'revision':original['revision'],'reason':'Correct purchase price','payload':p})
            self.assertEqual(result.status_code, 200, result.json)
            original = result.json['event']
            self.assertEqual(db.session.scalar(select(func.count(Animal.id))), 88)
            self.assertEqual(db.session.get(Animal, animal_id).identifier, 'NEW-BULL')
            self.assertEqual(Decimal(self.get('/api/overview').json['money']['USD']['Expense']), Decimal(amount_value))

    def test_birth_correction_preserves_calf_id_and_parentage(self):
        dam = self.animals[0]
        p = self.payload('birth', [], dam_id=dam.id, sex='Female', outcome='Live calf')
        p['versions'] = {str(dam.id):dam.version}
        original = self.submit(p).json['event']
        calf = db.session.scalar(select(Animal).where(Animal.temporary.is_(True)))
        calf_id = calf.id
        p['sex'] = 'Male'
        result = self.post('/api/events/'+original['id']+'/correct', {'revision':original['revision'],'reason':'Correct calf sex','payload':p})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(db.session.scalar(select(func.count(Animal.id))), 88)
        self.assertEqual(db.session.get(Animal, calf_id).sex, 'Male')
        self.assertEqual(db.session.get(Animal, calf_id).dam_id, dam.id)
        self.assertEqual(self.get('/api/overview').json['births'], 1)

    def test_import_cyclic_parentage_blocked(self):
        raw='identifier,sex,category,station,dam_identifier\nNEW-A,Female,Cow,Station A,NEW-B\nNEW-B,Female,Cow,Station A,NEW-A\n'
        result=self.post('/api/import/preview', {'csv':raw})
        self.assertFalse(result.json['can_import'])
        self.assertEqual(self.post('/api/import/commit', {'csv':raw}).status_code, 422)

    def test_deactivating_hand_revokes_existing_session(self):
        result = self.post(f'/api/users/{self.hand.id}', {'station_id':self.station.id,'active':False})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.get('/api/reference','hand').status_code, 401)

    def test_lifecycle_counts_include_historical_animals_without_health_overlap(self):
        self.animals[0].lifecycle = 'Sold'
        self.animals[1].lifecycle = 'Dead'
        self.animals[2].lifecycle = 'Lost'
        self.animals[3].health = 'Under treatment'
        db.session.commit()
        result = self.get('/api/overview', 'owner').json
        self.assertEqual(result['registered_total'], 87)
        self.assertEqual(result['lifecycle_counts'], {'Active':84, 'Sold':1, 'Dead':1, 'Lost':1})
        self.assertEqual(sum(result['lifecycle_counts'].values()), result['registered_total'])
        self.assertEqual(result['active'], 84)

    def test_empty_herd_lifecycle_totals(self):
        for animal in self.animals:
            db.session.delete(animal)
        db.session.commit()
        result = self.get('/api/overview', 'owner').json
        self.assertEqual(result['registered_total'], 0)
        self.assertEqual(result['lifecycle_counts'], {'Active':0, 'Sold':0, 'Dead':0, 'Lost':0})

    def test_lifecycle_totals_change_only_after_approval_and_follow_corrections(self):
        p = self.payload('death', cause='Reported cause')
        proposed = self.submit(p, 'hand').json['event']
        self.assertEqual(self.get('/api/overview', 'owner').json['lifecycle_counts']['Dead'], 0)
        approved = self.review(proposed).json['event']
        counts = self.get('/api/overview', 'owner').json
        self.assertEqual(counts['lifecycle_counts']['Dead'], 1)
        self.assertEqual(counts['registered_total'], 87)
        p['cause'] = 'Verified cause'
        result = self.post('/api/events/'+approved['id']+'/correct', {'payload':p,'revision':approved['revision'],'reason':'Confirmed cause'})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.get('/api/overview', 'owner').json['lifecycle_counts'], counts['lifecycle_counts'])

    def test_sample_pdf_marks_fictional_source_and_empty_report(self):
        self.app.config['SAMPLE_REPORT_LABEL'] = 'Fictional demonstration records'
        response = self.get('/api/reports.pdf?type=Growth', 'owner')
        import pypdfium2 as pdfium
        document = pdfium.PdfDocument(response.data)
        text = document[0].get_textpage().get_text_range()
        self.assertIn('SAMPLE', text)
        self.assertIn('Fictional demonstration records', text)
        self.assertIn('No records match these filters.', text)
        document.close()


    def test_malformed_submission_is_validation_error(self):
        self.assertEqual(self.post('/api/events', ['invalid']).status_code, 422)
        self.assertEqual(self.submit(self.payload('procedure', procedure='Other authorised procedure', next_due=[])).status_code, 422)
        self.assertEqual(self.submit(self.payload('procedure', procedure='Other authorised procedure', next_due=['invalid'])).status_code, 422)
        self.assertEqual(self.submit(self.payload('health', observation={'invalid':'object'})).status_code, 422)

    def test_lost_found_requires_approval_and_preserves_identity(self):
        animal = self.animals[0]
        event = self.submit(self.payload('lost', lifecycle_reason='Missing after search'), 'hand').json['event']
        self.assertEqual(animal.lifecycle, 'Active')
        self.assertEqual(self.review(event).status_code, 200)
        self.assertEqual(animal.lifecycle, 'Lost')
        self.assertEqual(self.get('/api/overview','owner').json['lifecycle_counts']['Lost'], 1)
        found = self.submit(self.payload('found', lifecycle_reason='Located at station'), 'hand').json['event']
        self.assertEqual(self.review(found).status_code, 200)
        self.assertEqual(animal.lifecycle, 'Active')
        self.assertEqual(animal.identifier, 'SB-0001')
        self.assertEqual(db.session.scalar(select(func.count(FinancialTransaction.id))), 0)
        self.assertEqual(self.submit(self.payload('lost', lifecycle_reason='No permission'), 'owner').status_code, 403)

    def test_duplicate_field_calf_tag_reaches_conflict_queue(self):
        p = self.payload('birth', [], identifier='DUPLICATE', sex='Female', outcome='Live calf', dam_id=self.animals[0].id)
        p['versions'] = {str(self.animals[0].id): self.animals[0].version}
        self.assertEqual(self.submit(p).status_code, 201)
        p['versions'][str(self.animals[0].id)] = self.animals[0].version
        result = self.submit(p, 'hand')
        self.assertEqual(result.status_code, 201, result.json)
        self.assertTrue(result.json['event']['conflicts'])
        self.assertEqual(self.review(result.json['event']).status_code, 409)

    def test_bulk_purchase_sum_correction_identity_and_single_expense(self):
        p = self.payload('purchase', [], currency='ZiG', reference='Batch invoice', purchase_rows=[
            dict(identifier='BUY-A',sex='Female',category='Heifer',price='123.45'),
            dict(identifier='BUY-B',sex='Male',category='Bull',price='234.56')])
        result = self.submit(p)
        self.assertEqual(result.status_code, 201, result.json)
        event = result.json['event']
        self.assertEqual(event['payload']['amount'], '358.01')
        rows = event['payload']['purchase_rows']
        ids = [r['animal_id'] for r in rows]
        self.assertEqual(db.session.scalar(select(func.count(FinancialTransaction.id))), 1)
        rows[0]['price'] = '100.00'
        corrected = self.post('/api/events/'+event['id']+'/correct',dict(payload=event['payload'],revision=event['revision'],reason='Correct invoice'))
        self.assertEqual(corrected.status_code, 200, corrected.json)
        self.assertEqual([r['animal_id'] for r in corrected.json['event']['payload']['purchase_rows']],ids)
        self.assertEqual(db.session.scalar(select(func.sum(FinancialTransaction.amount))), Decimal('334.56'))
        self.assertEqual(db.session.scalar(select(func.count(Animal.id))), 89)

    def test_bulk_purchase_duplicate_is_atomic(self):
        p = self.payload('purchase', [], currency='USD', purchase_rows=[dict(identifier='NEW',sex='Female',category='Cow',price='1'),dict(identifier='NEW',sex='Female',category='Cow',price='2')])
        self.assertEqual(self.submit(p).status_code, 422)
        self.assertEqual(db.session.scalar(select(func.count(Animal.id))),87)
        self.assertEqual(db.session.scalar(select(func.count(FinancialTransaction.id))),0)

    def test_bulk_pregnancy_results_and_steer_exposure(self):
        ids = [a.id for a in self.animals[:2]]
        p = self.payload('breeding',ids,breeding_action='Pregnancy check',pregnancy_results={str(ids[0]):dict(pregnancy_result='Pregnant',expected_calving=(today()+__import__('datetime').timedelta(days=60)).isoformat(),estimate_basis='Veterinary examination'),str(ids[1]):dict(pregnancy_result='Not pregnant')})
        self.assertEqual(self.submit(p).status_code,201)
        steer = Animal(identifier='STEER',sex='Male',category='Steer',station_id=self.station.id)
        db.session.add(steer);db.session.commit()
        self.assertEqual(self.submit(self.payload('breeding',ids,breeding_action='Bull exposure',sire_id=steer.id)).status_code,422)
        steer.category='Bull';db.session.commit()
        self.assertEqual(self.submit(self.payload('breeding',ids,breeding_action='Bull exposure',sire_id=steer.id)).status_code,201)

    def test_reminders_are_per_animal_and_report_contains_usage(self):
        self.opening_stock()
        for i,days in [(0,2),(1,30)]:
            p=self.payload('procedure',[self.animals[i].id],procedure='Dipping',next_due=(today()+__import__('datetime').timedelta(days=days)).isoformat(),absent_ids=[self.animals[2].id])
            p['products']=[dict(product_id=self.product.id,quantity='2.375',dosage='Recorded dose')]
            self.assertEqual(self.submit(p).status_code,201)
        due=self.get('/api/overview','owner').json['due']
        self.assertEqual([r['animal_id'] for r in due],[self.animals[0].id])
        report=str(self.get('/api/reports?type=Health','owner').json)
        for expected in ['Dip','2.375','Recorded dose','SB-0003']:
            self.assertIn(expected,report)

    def test_pending_queues_are_not_hidden_by_history(self):
        p=self.payload('health',observation='Queue fixture')
        for i in range(2101):
            db.session.add(Event(id=str(uuid.uuid4()),kind='health',date=p['date'],station_id=self.station.id,payload=p,state='Rejected',author_id=self.hand.id,created_at=f'2026-10-14T12:{i:04}'))
        pending=Event(id=str(uuid.uuid4()),kind='health',date=p['date'],station_id=self.station.id,payload=p,state='Pending approval',author_id=self.hand.id,created_at='2020-01-01')
        db.session.add(pending);db.session.commit()
        result=self.get('/api/events').json
        self.assertEqual(result['outstanding'],1)
        self.assertIn(pending.id,[r['id'] for r in result['events']])
        self.assertTrue(result['has_more'])


    def test_account_pending_not_hidden_and_history_paginated(self):
        from cattle.models import RegistrationRequest
        for i in range(230):
            db.session.add(RegistrationRequest(id=str(uuid.uuid4()),name='Reviewed fixture',username=f'old-{i}',requested_role='hand',state='Rejected',created_at=f'2026-10-14T12:{i:04}'))
        pending=RegistrationRequest(id=str(uuid.uuid4()),name='Pending fixture',username='pending-old',pending_username='pending-old',requested_role='hand',state='Pending',created_at='2020-01-01')
        db.session.add(pending);db.session.commit()
        result=self.get('/api/account-requests').json
        self.assertTrue(result['has_more'])
        self.assertIn(pending.id,[r['id'] for r in result['registrations']])
        self.assertEqual(len(result['registrations']),101)

    def test_trusted_proxy_https_origin_and_untrusted_headers(self):
        import sys
        from pathlib import Path
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.runtime'))
        from waitress.proxy_headers import proxy_headers_middleware
        original=self.app.wsgi_app
        self.app.wsgi_app=proxy_headers_middleware(original,trusted_proxy='127.0.0.1',trusted_proxy_headers={'x-forwarded-for','x-forwarded-host','x-forwarded-proto'})
        client=self.app.test_client()
        headers={'X-Requested-With':'Simbanai','Origin':'https://farm.example','X-Forwarded-Proto':'https','X-Forwarded-Host':'farm.example','X-Forwarded-For':'192.0.2.50'}
        try:
            response=client.post('/api/password-reset/request',json={'username':'unknown'},headers=headers,environ_overrides={'REMOTE_ADDR':'127.0.0.1'})
            self.assertEqual(response.status_code,200,response.json)
            response=client.post('/api/password-reset/request',json={'username':'unknown'},headers=headers,environ_overrides={'REMOTE_ADDR':'192.0.2.99'})
            self.assertEqual(response.status_code,403)
        finally:
            self.app.wsgi_app=original


    def test_found_station_and_lifecycle_correction(self):
        lost=self.submit(self.payload('lost',lifecycle_reason='Search completed')).json['event']
        found=self.submit(self.payload('found',lifecycle_reason='Located',found_station_id=self.destination.id)).json['event']
        self.assertEqual(self.animals[0].station_id,self.destination.id)
        self.assertEqual(self.animals[0].lifecycle,'Active')
        repeated=self.submit(found['payload'],event_id=found['id'])
        self.assertTrue(repeated.json['duplicate'])
        self.assertEqual(self.post('/api/events/'+lost['id']+'/correct',dict(payload=lost['payload'],revision=lost['revision'],reason='Dependent correction')).status_code,409)

    def test_sex_category_consistency_and_growth_values(self):
        self.assertEqual(self.submit(self.payload('purchase',[],identifier='WRONG',sex='Female',category='Bull',amount='10',currency='USD')).status_code,422)
        animal=self.animals[0]
        result=self.post('/api/animals/'+str(animal.id)+'/identity',dict(identifier=animal.identifier,category='Bull',version=animal.version,reason='Invalid category'))
        self.assertEqual(result.status_code,422)
        past=(today()-__import__('datetime').timedelta(days=10)).isoformat()
        p=self.payload('weight',weights={str(animal.id):'200'});p['date']=past
        self.assertEqual(self.submit(p).status_code,201)
        self.assertEqual(self.submit(self.payload('weight',weights={str(animal.id):'210'})).status_code,201)
        growth=self.get('/api/overview','owner').json['growth']
        self.assertEqual(growth[0]['change'],'10')
        self.assertEqual(growth[0]['daily_gain'],'1.000')


    def capture_proofs(self, payload):
        reference = self.get('/api/reference', 'hand').json['animals']
        payload['capture_proofs'] = {str(a['id']): a['capture_proof'] for a in reference if str(a['id']) in payload['versions']}
        return payload

    def test_breeding_action_always_validated_before_results(self):
        for action in ['Unsupported action', None, '']:
            for results in [{'unexpected':'unvalidated'}, [], {'1':{'pregnancy_result':'Pregnant'}}]:
                with self.subTest(action=action,results=results):
                    result=self.submit(self.payload('breeding',breeding_action=action,pregnancy_results=results))
                    self.assertEqual(result.status_code,422,result.json)
        self.assertEqual(db.session.scalar(select(func.count(Event.id))),0)
        self.assertEqual(self.animals[0].version,1)

    def test_exposure_rejects_check_fields_and_preserves_legacy(self):
        bull=Animal(identifier='PROOF-BULL',sex='Male',category='Bull',station_id=self.station.id)
        db.session.add(bull);db.session.commit()
        for field,value in [('pregnancy_results',{}),('pregnancy_results',{'1':'Forged'}),('pregnancy_result','Pregnant'),('expected_calving','2027-01-01'),('estimate_basis','Unrelated')]:
            p=self.payload('breeding',breeding_action='Bull exposure',sire_id=bull.id)
            p[field]=value
            self.assertEqual(self.submit(p).status_code,422)
        p=self.payload('breeding',breeding_action='Bull exposure',sire_id=bull.id,expected_calving=None,estimate_basis='')
        self.assertEqual(self.submit(p).status_code,201)
        self.assertEqual(self.submit(self.payload('breeding',breeding_action='Pregnancy check',pregnancy_result='Not pregnant')).status_code,201)

    def test_signed_capture_allows_moved_proposal_not_approval(self):
        p=self.capture_proofs(self.payload('health',observation='Captured before movement'))
        movement=self.payload('movement',destination_id=self.destination.id,movement_reason='Grazing')
        self.assertEqual(self.submit(movement).status_code,201)
        result=self.submit(p,'hand')
        self.assertEqual(result.status_code,201,result.json)
        self.assertTrue(result.json['event']['conflicts'])
        self.assertEqual(self.review(result.json['event']).status_code,409)
        self.assertEqual(db.session.scalar(select(func.count(HealthCase.id))),0)

    def test_forged_station_version_or_proof_is_denied(self):
        p=self.capture_proofs(self.payload('health',observation='Capture'))
        key=str(self.animals[0].id)
        original=p['capture_proofs'][key]
        for token in [original+'tampered',123,'not-signed','',chr(0xD800)]:
            p['capture_proofs'][key]=token
            self.assertEqual(self.submit(p,'hand').status_code,403)
        p['capture_proofs'][key]=original
        p['versions'][key]+=1
        self.assertEqual(self.submit(p,'hand').status_code,403)
        p['versions'][key]-=1
        self.animals[0].station_id=self.destination.id;db.session.commit()
        p.pop('capture_proofs')
        self.assertEqual(self.submit(p,'hand').status_code,403)
        self.assertEqual(db.session.scalar(select(func.count(Event.id))),0)

    def test_capture_proof_bound_to_user_station_animal(self):
        from cattle.service import capture_signer
        p=self.capture_proofs(self.payload('health',observation='Capture'))
        key=str(self.animals[0].id)
        claims=dict(user_id=self.hand.id,station_id=self.station.id,animal_id=self.animals[0].id,version=self.animals[0].version)
        for field,value in [('user_id',self.owner.id),('station_id',self.destination.id),('animal_id',self.animals[1].id)]:
            p['capture_proofs'][key]=capture_signer().dumps({**claims,field:value})
            self.assertEqual(self.submit(p,'hand').status_code,403)

    def test_birth_dam_and_resubmission_use_station_proof(self):
        dam=self.animals[0]
        p=self.payload('birth',[],dam_id=dam.id,sex='Female',outcome='Live calf')
        p['versions']={str(dam.id):dam.version}
        self.capture_proofs(p)
        event=self.submit(p,'hand').json['event']
        returned=self.review(event,'return','Review the changed dam').json['event']
        self.assertEqual(self.submit(self.payload('movement',destination_id=self.destination.id,movement_reason='Grazing')).status_code,201)
        no_proof=deepcopy(p);no_proof.pop('capture_proofs')
        result=self.post('/api/events/'+event['id']+'/resubmit',dict(payload=no_proof,revision=returned['revision']),'hand')
        self.assertEqual(result.status_code,403)
        self.assertEqual(db.session.get(Event,event['id']).state,'Returned')
        result=self.post('/api/events/'+event['id']+'/resubmit',dict(payload=p,revision=returned['revision']),'hand')
        self.assertEqual(result.status_code,200,result.json)
        self.assertTrue(result.json['event']['conflicts'])
        self.assertEqual(self.review(result.json['event']).status_code,409)
        self.assertEqual(db.session.scalar(select(func.count(Animal.id))),87)

    def test_legacy_draft_station_policy(self):
        p=self.payload('health',observation='Legacy draft')
        self.assertEqual(self.submit(p,'hand').status_code,201)
        self.animals[0].station_id=self.destination.id;db.session.commit()
        result=self.submit(p,'hand')
        self.assertEqual(result.status_code,403)
        self.assertIn('older draft',result.json['error'])

    def test_proof_survives_credential_change_and_absences_need_permission(self):
        p=self.capture_proofs(self.payload('health',observation='Before password change'))
        response=self.post('/api/account/password',{'current':'test-password-123','password':'Changed-password-123!'},'hand')
        self.assertEqual(response.status_code,200,response.json)
        self.animals[0].station_id=self.destination.id;db.session.commit()
        self.assertEqual(self.submit(p,'hand').status_code,201)
        p=self.payload('procedure',[self.animals[1].id],procedure='Other authorised procedure',absent_ids=[self.animals[0].id])
        self.assertEqual(self.submit(p,'hand').status_code,403)

    def test_compatible_units_fractional_and_mixed_aggregation(self):
        self.opening_stock('1')
        p=self.payload('procedure',procedure='Dipping')
        p['products']=[dict(product_id=self.product.id,quantity='0.1',entered_unit='mL'),dict(product_id=self.product.id,quantity='0.1',entered_unit='L')]
        result=self.submit(p)
        self.assertEqual(result.status_code,201,result.json)
        self.assertEqual(stock_balance(self.product.id),Decimal('0.899900'))
        self.assertEqual(result.json['event']['payload']['products'][0]['quantity'],'0.0001')
        for unit,qty in [('kg','1'),('mL','-0.1')]:
            p=self.payload('procedure',procedure='Dipping');p['products']=[dict(product_id=self.product.id,quantity=qty,entered_unit=unit)]
            self.assertEqual(self.submit(p).status_code,422)

    def test_outside_source_requires_receipt_and_allocates_once(self):
        self.opening_stock('10')
        p=self.payload('procedure',procedure='Dipping');p['products']=[dict(product_id=self.product.id,quantity='1',source='Outside source',source_note='Neighbour')]
        response=self.submit(p,'hand');self.assertEqual(response.status_code,201,response.json)
        event=response.json['event'];self.assertEqual(self.review(event).status_code,409)
        receipt=self.payload('stock_in',[],receipt_type='External supply',reference='Neighbour free medicine');receipt['products']=[dict(product_id=self.product.id,quantity='1')]
        received=self.submit(receipt);self.assertEqual(received.status_code,201,received.json)
        result=self.post('/api/events/'+event['id']+'/review',dict(action='approve',revision=event['revision'],product_receipts={'0':received.json['event']['id']}))
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(db.session.query(FinancialTransaction).count(),0)
        p=self.payload('procedure',procedure='Dipping');p['products']=[dict(product_id=self.product.id,quantity='1',source='Outside source',source_note='Neighbour',receipt_id=received.json['event']['id'])]
        self.assertEqual(self.submit(p).status_code,409)

    def test_archive_restoration_preserves_balance_and_pending(self):
        self.opening_stock()
        p=self.payload('procedure',procedure='Dipping');p['products']=[dict(product_id=self.product.id,quantity='1')]
        event=self.submit(p,'hand').json['event']
        self.assertEqual(self.post('/api/products/'+str(self.product.id),{'active':False}).status_code,200)
        self.assertEqual(stock_balance(self.product.id),Decimal('20'))
        self.assertEqual(self.review(event).status_code,409)
        self.post('/api/products/'+str(self.product.id),{'active':True})
        self.assertEqual(self.review(event).status_code,200)

    def test_multiple_station_authorization_and_signed_capture(self):
        from cattle.service import assign_stations
        assign_stations(self.hand,{'station_ids':[self.station.id,self.destination.id]})
        self.animals[0].station_id=self.destination.id;db.session.commit()
        reference=self.get('/api/reference','hand').json
        animal=next(a for a in reference['animals'] if a['id']==self.animals[0].id)
        self.assertEqual(set(reference['user']['station_ids']),{self.station.id,self.destination.id}) if 'user' in reference else None
        p=self.payload('health',observation='At second assigned station');p['station_id']=self.destination.id;p['capture_proofs']={str(animal['id']):animal['capture_proof']}
        self.assertEqual(self.submit(p,'hand').status_code,201)
        third=Station(name='Unassigned');db.session.add(third);db.session.commit();p['station_id']=third.id
        self.assertEqual(self.submit(p,'hand').status_code,403)

    def test_gift_has_no_expense_and_reports_acquisition_source(self):
        p=self.payload('purchase',[],identifier='GIFT-1',sex='Female',category='Heifer',acquisition_source='Gift',reference='Donor ranch')
        response=self.submit(p);self.assertEqual(response.status_code,201,response.json)
        self.assertEqual(db.session.query(FinancialTransaction).count(),0)
        report=self.get('/api/reports?type=Acquisitions/sales');self.assertEqual(report.status_code,200)
        self.assertIn('Gift',str(report.json['rows']))
        p=self.payload('purchase',[],identifier='BUY-1',sex='Female',category='Heifer',acquisition_source='Purchase',reference='Supplier',amount='0',currency='USD')
        self.assertEqual(self.submit(p).status_code,422)

    def test_category_review_does_not_change_classification(self):
        from cattle.service import category_review_due
        self.animals[0].category='Calf';self.animals[0].dob='2020-08-31';db.session.commit()
        self.assertEqual(category_review_due(self.animals[0]),'2021-02-28')
        self.assertEqual(self.post('/api/settings',{'calf_review_months':9}).status_code,200)
        self.assertEqual(category_review_due(self.animals[0]),'2021-05-31')
        self.assertEqual(self.animals[0].category,'Calf')
        self.assertEqual(self.post('/api/settings',{'calf_review_months':6},'owner').status_code,403)

    def test_chart_currency_grouping_empty_and_profile_permissions(self):
        empty=self.get('/api/charts/expenses?currency=USD').json;self.assertEqual(empty['points'],[])
        for currency,value in [('USD','12'),('ZiG','90')]:
            response=self.submit(self.payload('expense',[],amount=value,currency=currency,finance_category='Other cattle expense',reference='Chart check'))
            self.assertEqual(response.status_code,201,response.json)
        self.assertEqual(Decimal(self.get('/api/charts/expenses?currency=USD').json['total']),Decimal('12'))
        self.assertEqual(self.get('/api/charts/expenses?from=2020-01-01&group=auto').json['group'],'years')
        self.assertEqual(self.get('/api/charts/performance').status_code,422)
        self.assertEqual(self.get('/api/charts/expenses','hand').status_code,403)
        pdf=self.get('/api/animals/'+str(self.animals[0].id)+'/profile.pdf','owner')
        self.assertEqual(pdf.status_code,200);self.assertTrue(pdf.data.startswith(b'%PDF'))
        self.assertEqual(self.get('/api/animals/'+str(self.animals[0].id)+'/profile.pdf','hand').status_code,403)

    def test_mass_conversion_and_paid_outside_receipt_one_expense(self):
        p=self.payload('stock_in',[],receipt_type='Purchase',amount='9',currency='USD',reference='Outside supplier')
        p['products']=[dict(product_id=self.feed.id,quantity='2',entered_unit='kg')]
        receipt=self.submit(p).json['event']
        usage=self.payload('stock_use',[]);usage['products']=[dict(product_id=self.feed.id,quantity='100',entered_unit='g',source='Outside source',source_note='Outside supplier',receipt_id=receipt['id'])]
        response=self.submit(usage);self.assertEqual(response.status_code,201,response.json)
        self.assertEqual(stock_balance(self.feed.id),Decimal('1.9'))
        self.assertEqual(db.session.query(FinancialTransaction).count(),1)
        self.assertEqual(Decimal(self.get('/api/charts/expenses?currency=USD').json['total']),Decimal('9'))

    def test_chart_reversals_and_profile_counts_exclude_superseded(self):
        self.opening_stock()
        p=self.payload('procedure',procedure='Dipping');p['products']=[dict(product_id=self.product.id,quantity='1')]
        original=self.submit(p).json['event'];p=self.payload('procedure',procedure='Vaccination');p['products']=[dict(product_id=self.product.id,quantity='1')]
        changed=self.post('/api/events/'+original['id']+'/correct',dict(revision=original['revision'],reason='Recorded wrong procedure',payload=p));self.assertEqual(changed.status_code,200,changed.json)
        summary=self.get('/api/animals/'+str(self.animals[0].id)).json['summary']
        self.assertEqual(summary['dipping'],0);self.assertEqual(summary['vaccinations'],1)
        p=self.payload('expense',[],amount='12',currency='USD',finance_category='Feed');original=self.submit(p).json['event'];p['amount']='7'
        changed=self.post('/api/events/'+original['id']+'/correct',dict(revision=original['revision'],reason='Receipt corrected',payload=p));self.assertEqual(changed.status_code,200,changed.json)
        chart=self.get('/api/charts/expenses?currency=USD').json
        self.assertEqual(Decimal(chart['total']),Decimal('7'));self.assertEqual(chart['records'],3)

    def test_measured_gain_and_pregnancy_chart_contributions(self):
        ids=[a.id for a in self.animals[:2]]
        p=self.payload('weight',ids,weights={str(ids[0]):'100',str(ids[1]):'120'});p['date']=(today()-__import__('datetime').timedelta(days=10)).isoformat()
        self.assertEqual(self.submit(p).status_code,201)
        p=self.payload('weight',ids,weights={str(ids[0]):'110',str(ids[1]):'130'});self.assertEqual(self.submit(p).status_code,201)
        chart=self.get('/api/charts/performance?metric=daily_gain').json
        self.assertEqual(Decimal(chart['points'][0]['value']),Decimal('1'));self.assertEqual(chart['points'][0]['count'],2)
        p=self.payload('breeding',ids,breeding_action='Pregnancy check',pregnancy_results={str(ids[0]):{'pregnancy_result':'Pregnant'},str(ids[1]):{'pregnancy_result':'Not pregnant'}})
        self.assertEqual(self.submit(p).status_code,201)
        results=self.get('/api/charts/performance?metric=pregnancy').json['points'][0]['results']
        self.assertEqual(results,{'Pregnant':1,'Not pregnant':1,'Uncertain':0})

    def test_invalid_assignment_and_receipt_structures_are_readable(self):
        self.assertEqual(self.post('/api/settings',['wrong shape']).status_code,422)
        self.assertEqual(self.post('/api/users',dict(name='Invalid',username='invalid',password='test-password-123',station_ids={'wrong':'shape'})).status_code,422)
        p=self.payload('procedure',procedure='Dipping');p['products']=[dict(product_id=self.product.id,quantity='1',source='Outside source',source_note='Neighbour',receipt_id=[])]
        self.assertEqual(self.submit(p,'hand').status_code,422)

    def test_gift_marker_cannot_suppress_sale_or_expense_finances(self):
        sale=self.submit(self.payload('sale',amount='500',currency='USD',acquisition_source='Gift'))
        self.assertEqual(sale.status_code,201,sale.json)
        expense=self.submit(self.payload('expense',[],amount='8',currency='ZiG',finance_category='Feed',acquisition_source='Gift'))
        self.assertEqual(expense.status_code,201,expense.json)
        self.assertEqual(db.session.query(FinancialTransaction).count(),2)
        self.assertEqual(Decimal(self.get('/api/charts/expenses?currency=ZiG').json['total']),Decimal('8'))


if __name__ == '__main__':
    unittest.main()
