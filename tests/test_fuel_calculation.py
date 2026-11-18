"""PHM calculation and save checks with all database access mocked."""
import unittest
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from osvc_app import create_app
from osvc_app.forms import FuelForm


class FuelCalculationTests(unittest.TestCase):
    def setUp(self):
        self.state=TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        self.app=create_app({'TESTING':True, 'SECRET_KEY':'test-only',
                             'APP_USER':'test', 'APP_PASSWORD_HASH':'test-only',
                             'WTF_CSRF_ENABLED':False, 'DATA_STATE_DIR':self.state.name})
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:
            session['user']='test'
            session['local_auth']=1

    def test_calculation_and_untrusted_liters(self):
        cases=[('', '', None), ('43.59', '', None), ('', '1576', None),
               ('43.59', '1576.00', Decimal('36.16')),
               ('43,59', '1576,00', Decimal('36.16')),
               ('40', '450', Decimal('11.25')), ('8', '1', Decimal('0.13')),
               ('0', '1576', None), ('invalid', '1576', None)]
        for price,total,expected in cases:
            for liters in (None, '999', 'invalid'):
                with self.subTest(price=price,total=total,liters=liters):
                    data={'price_per_liter':price, 'total_amount':total}
                    if liters is not None:
                        data['liters']=liters
                    with self.app.test_request_context(method='POST',data=data):
                        form=FuelForm()
                        self.assertEqual(form.liters.data,expected)
                        self.assertEqual(form.liters.process_errors,[])
                        self.assertIn('readonly',str(form.liters()))

    def test_edit_recalculates_existing_liters(self):
        with self.app.test_request_context():
            form=FuelForm()
            form.process(data={'liters':Decimal('999'), 'price_per_liter':Decimal('43.59'),
                               'total_amount':Decimal('1576.00')})
            self.assertEqual(form.liters.data,Decimal('36.16'))
            self.assertIn('value="36.16"',str(form.liters()))

    def test_create_and_edit_save_derived_liters_without_amount_tolerance(self):
        fuel={'id':7, 'document_id':None, 'counterparty_id':None,
              'station':None, 'station_name':'Test', 'note':None,
              'purchase_date':date(2026,10,5), 'vehicle_id':1,
              'liters':Decimal('999'), 'price_per_liter':Decimal('43.59'),
              'total_amount':Decimal('1576')}
        with ExitStack() as stack:
            stack.enter_context(patch('osvc_app.db.connection',side_effect=AssertionError('No database')))
            stack.enter_context(patch('osvc_app.ucet.aktualni',return_value={'id':None,'username':self.app.config['APP_USER'],'password_hash':'','auth_version':0}))   # I2: účet bez DB
            stack.enter_context(patch('osvc_app.trips_fuel_routes.vehicles',side_effect=lambda f:setattr(f.vehicle_id,'choices',[(0,'—'),(1,'Test')])) )
            stack.enter_context(patch('osvc_app.trips_fuel_routes.fuel_counterparty_choices',side_effect=lambda f:setattr(f,'counterparty_options',[])))
            stack.enter_context(patch('osvc_app.trips_fuel_routes.resolve_fuel_counterparty',return_value=None))
            stack.enter_context(patch('osvc_app.trips_fuel_routes.query',return_value=fuel))
            execute=stack.enter_context(patch('osvc_app.trips_fuel_routes.execute',return_value=7))
            stack.enter_context(patch('osvc_app.trips_fuel_routes.audit'))
            stack.enter_context(patch('osvc_app.trips_fuel_routes.sync_fuel_payment'))
            for path in ('/fuel','/fuel/7/edit'):
                for liters in (None,'999','invalid'):
                    data={'purchase_date':'2026-10-05','vehicle_id':'1',
                          'counterparty_name':'Test','price_per_liter':'43.59','total_amount':'1576.00'}
                    if liters is not None:
                        data['liters']=liters
                    response=self.client.post(path,data=data)
                    self.assertEqual(response.status_code,302)
                    sql,values=execute.call_args.args
                    self.assertIn('fuel_purchases',sql)
                    self.assertEqual(values[5:8],(Decimal('36.16'),Decimal('43.59'),Decimal('1576.00')))


if __name__=='__main__':
    unittest.main()
