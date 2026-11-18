"""Legacy category data must have no accounting effect after decoupling."""
import unittest
from osvc_app.expense_tax import classification,resolve_submission
class LegacyCategories(unittest.TestCase):
 def test_no_implicit_classification(self):
  for category in [None,0,50,100]:
   self.assertEqual(classification({'tax_deductible_pct':None,'category_tax_pct':category})['state'],'pending')
 def test_confirmed_snapshot_independent(self):
  for category in [None,0,100]:
   self.assertEqual(classification({'tax_deductible_pct':50,'tax_mode':'category','category_tax_pct':category})['ratio'],50)
 def test_legacy_submission_not_supported(self):
  with self.assertRaises(ValueError):resolve_submission({'tax_mode':'category'})
