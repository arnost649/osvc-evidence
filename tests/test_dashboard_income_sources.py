"""Dashboard source labels; fixture records stay in memory, no sync or DB writes."""
import unittest
from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import template_rendered
from osvc_app import create_app, system_types


class DashboardIncomeSources(unittest.TestCase):
    def setUp(self):
        self.state=TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        self.app=create_app({'TESTING':True,'SECRET_KEY':'test-only','APP_USER':'test',
                             'APP_PASSWORD_HASH':'test-only','DATA_STATE_DIR':self.state.name})
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:
            session['user']='test'
            session['local_auth']=1
        self.names={key:value[0] for key,value in system_types.TYPES.items()}
        # Dřívější chyba: název typu „Ruční příjem“ uložený omylem u income_connector se nesmí ukázat u importu se zdrojem.
        self.names['income_connector']='Ruční příjem'

    def payment(self,ident,source=None,kind='income_connector',description='Synchronizovaná položka'):
        return dict(id=ident,payment_date=date(2026,10,5),direction='income',
                    system_type=kind,description=description,amount=Decimal('100'),
                    document_source='woocommerce' if kind=='income_connector' else 'manual',
                    income_source_id=source[0] if source else None,
                    income_source_name=source[1] if source else None)

    def dashboard(self,payments,fuels=None,trips=None):
        def query(sql,*args,**kwargs):
            if 'FROM payments p ' in sql:return payments
            if 'SELECT distance_km FROM trips' in sql:return []   # součet km počítá Python (S2)
            if 'FROM fuel_purchases f ' in sql:return fuels or []
            if 'FROM trips t ' in sql:return trips or []
            raise AssertionError('Unexpected database query')
        report={'sections':[{'key':'tax','fields':[{'field_key':key,'value':Decimal('0')}
                                                 for key in ('income','expenses','result')]}]}
        captured=[]
        def capture(sender,template,context,**kwargs):captured.append(context)
        with patch('osvc_app.routes.query',side_effect=query), \
             patch('osvc_app.system_types.labels',return_value=self.names), \
             patch('osvc_app.annual.year_report',return_value=(None,None,None,None,report)), \
             patch('osvc_app.routes.wc_sync_ready',return_value=False), \
             patch('osvc_app.income_sources.default_source',return_value=None), \
             patch('osvc_app.db.connection',side_effect=AssertionError('No database access')), \
             patch('osvc_app.ucet.aktualni',return_value={'id':None,'username':self.app.config['APP_USER'],'password_hash':'','auth_version':0}), \
             template_rendered.connected_to(capture,self.app):
            response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        return captured[-1]['recent_items'],response.text

    def test_orders_and_manual_income(self):
        rows=[self.payment(3306,(1,'muj-eshop.example'),description='Objednávka 6919'),
              self.payment(3214,(1,'muj-eshop.example'),description='Objednávka 6521'),
              self.payment(1,kind='income',description='Ručně zadaný příjem')]
        items,html=self.dashboard(rows)
        self.assertEqual({i['id']:i['kind_label'] for i in items},
                         {3306:'muj-eshop.example',3214:'muj-eshop.example',1:'Ruční příjem'})
        self.assertEqual(html.count('>muj-eshop.example</span>'),2)
        self.assertIn('>Ruční příjem</span>',html)

    def test_source_relation_takes_precedence_over_legacy_type(self):
        for kind in ('income',None,'income_connector'):
            with self.subTest(kind=kind):
                items,_=self.dashboard([self.payment(1,(2,'Další uložený zdroj'),kind)])
                self.assertEqual(items[0]['kind_label'],'Další uložený zdroj')
                self.assertEqual(items[0]['kind'],'income_connector')

    def test_description_does_not_define_source(self):
        items,_=self.dashboard([self.payment(1,kind='income',description='Objednávka 6919')])
        self.assertEqual(items[0]['kind_label'],'Ruční příjem')
        items,_=self.dashboard([self.payment(1,(1,'muj-eshop.example'),description='Neutrální popis')])
        self.assertEqual(items[0]['kind_label'],'muj-eshop.example')

    def test_unlinked_import_never_uses_manual_label(self):
        for kind in ('income_connector','income',None):
            row=self.payment(1,kind=kind)
            row['document_source']='woocommerce'
            self.names['income_connector']='Příjem z e-shopu'   # bez zdroje se použije název typu z Nastavení
            items,_=self.dashboard([row])
            self.assertEqual(items[0]['kind_label'],'Příjem z e-shopu')

    def test_other_dashboard_record_labels_and_links_unchanged(self):
        self.names.update(expense='Uložený nákup',fuel='Uložené PHM',trip='Uložená doprava')
        expense=self.payment(1,kind='expense')
        expense['direction']='expense'
        items,_=self.dashboard([expense],
                              fuels=[dict(id=2,purchase_date=date(2026,10,5),station='Test',total_amount=Decimal('10'))],
                              trips=[dict(id=3,trip_date=date(2026,10,5),origin='A',destination='B',distance_km=Decimal('5'))])
        self.assertEqual({i['id']:i['kind_label'] for i in items},
                         {1:'Uložený nákup',2:'Uložené PHM',3:'Uložená doprava'})
        self.assertEqual({i['id']:i['href'] for i in items},
                         {1:'/payments/expense/1',2:'/fuel/2/edit',3:'/trips/3/edit'})


if __name__=='__main__':
    unittest.main()
