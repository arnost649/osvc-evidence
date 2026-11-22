"""Annual summary uses the same completeness state as its component sections."""
import unittest
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import render_template
from osvc_app import annual, create_app, profile_presentation


class SummaryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_summary=False
        self.state=None
        self.title=None

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='span' and attrs.get('id')=='annual-stav':   # 1.0.3: souhrnný stav u nadpisu podkladu
            self.state=attrs['class'].split()[-1]
            self.title=attrs['aria-label']   # důvod je jen pro čtečky (bez bubliny po najetí myší)


class AnnualSummaryTests(unittest.TestCase):
    def setUp(self):
        self.state=TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        self.app=create_app({'TESTING':True,'SECRET_KEY':'test-only','APP_USER':'test',
                             'APP_PASSWORD_HASH':'test-only','DATA_STATE_DIR':self.state.name})
        self.identity=dict(ico='12345678',name='Test',number='1',city='Test',zip='10000',country='CZ')
        self.p=dict(months=[dict(month=m,activity='yes' if m>=9 else 'no',employment='insured',
                                social='secondary',reason='employment',minimum='auto',health_employment='yes')
                            for m in range(1,13)],vehicles={},social_paid='0',health_paid='0',
                    social_case='standard',social_voluntary='no',insurer='Test',insurer_code='111',
                    health_from='2026-01-01',health_to='2026-12-31',health_case='standard',
                    expense_method='actual',expense_adjustment='0',base_adjustment='0',
                    tax_case='standard',tax_review='yes')
        self.ev=dict(income=Decimal('100'),ordinary=Decimal('200'),vehicles={},issues=[],
                     counts={'Příjmy':1,'Výdaje':1,'Jízdy':0,'PHM':0})

    def render(self,today=date(2026,10,5)):
        class FrozenDate(date):
            @classmethod
            def today(cls):return today
        with self.app.test_request_context('/annual?year=2026'), \
             patch('osvc_app.annual.date',FrozenDate), patch('osvc_app.cas.today',return_value=today), \
             patch('osvc_app.profile.vehicles',return_value=[]), \
             patch('osvc_app.income_sources.default_source',return_value=None), \
             patch('osvc_app.db.connection',side_effect=AssertionError('No database access')):
            report=annual.build(2026,self.identity,self.p,self.ev)
            view=profile_presentation.build(self.identity,self.p,report,[])
            from osvc_app.annual_podklad import podklad
            from osvc_app import urady
            html=render_template('annual.html',profile_report=report,profile_view=view,podklad=podklad(report),urady=urady.karty(self.identity,self.p,2026,sit=False),
                                 profile_year=2026,year_profile=self.p,display=annual.display)
        summary=SummaryParser()
        summary.feed(html)
        self.assertEqual(summary.state,view['profile_state'])
        return summary,report,html

    def test_period_counts_are_informational(self):
        for today,counts in [(date(2026,8,5),(0,0,4)),(date(2026,9,5),(0,1,3)),
                             (date(2026,10,5),(1,1,2)),(date(2026,12,5),(3,1,0)),
                             (date(2027,1,5),(4,0,0))]:
            with self.subTest(today=today):
                summary,report,html=self.render(today)
                self.assertEqual(summary.state,'known')
                self.assertTrue(all(s['status']=='known' for s in report['sections']))
                self.assertEqual(tuple(report['period_counts'][k] for k in ('completed','current','future')),counts)
                if report['period_note']:
                    self.assertIn(report['period_note'],html)

    def test_general_applicability_advisory_does_not_override_complete_inputs(self):
        self.p['tax_case']='other'
        summary,report,html=self.render()
        self.assertTrue(report['reviews'])
        self.assertEqual(summary.state,'known')
        self.assertEqual(summary.title,'Hotovo')
        self.assertIn('Podklady ke kontrole',html)

    def test_concrete_section_review_without_global_warning(self):
        self.p['months'][8]['social']='main'
        summary,report,_=self.render()
        self.assertFalse(report['reviews'])
        self.assertEqual(summary.state,'review')
        self.assertIn('Kombinace hlavní a vedlejší SVČ',summary.title)

    def test_required_inputs_are_missing(self):
        for key,reason in [('social_paid','Zaplacené zálohy ČSSZ'),
                           ('tax_review','Potvrďte kontrolu'),('insurer_code','Kód pojišťovny')]:
            old=self.p[key]
            with self.subTest(key=key):
                self.p[key]=''
                summary,_,_=self.render()
                self.assertEqual(summary.state,'missing')
                self.assertIn(reason,summary.title)
            self.p[key]=old

    def test_concrete_evidence_issue_requires_review(self):
        self.ev['issues']=['Konkrétní nesoulad příjmů v evidenci.']
        summary,_,_=self.render()
        self.assertEqual(summary.state,'review')
        self.assertIn('Konkrétní nesoulad příjmů',summary.title)

    def test_missing_input_takes_precedence_over_review(self):
        self.p['months'][8]['social']='main'
        self.p['health_paid']=''
        summary,_,_=self.render()
        self.assertEqual(summary.state,'missing')
        self.assertIn('Zaplacené zálohy zdravotního pojištění',summary.title)


if __name__=='__main__':
    unittest.main()
