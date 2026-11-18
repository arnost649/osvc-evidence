"""Run: docker compose exec -T app python < tests/test_themes.py"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from osvc_app import create_app
from osvc_app.themes import THEMES, contrast

class ThemeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.path=Path(self.tmp.name)/'appearance.json'
  self.app=create_app({'TESTING':True,'THEME_SETTINGS_FILE':str(self.path)})
  self.client=self.app.test_client()
 def tearDown(self): self.tmp.cleanup()
 def token(self):
  return re.search(r'name="csrf_token"[^>]*value="([^"]+)"',self.client.get('/login').text).group(1)
 def login(self):
  return self.client.post('/login',data={'username':'osvc','password':'osvc','csrf_token':self.token()})
 def save(self,value):
  return self.client.post('/settings/appearance',json={'theme':value},headers={'X-CSRFToken':self.token()})
 def test_persistence_and_validation(self):
  self.assertEqual(self.save('grafit').status_code,302)
  self.login()
  self.assertEqual(self.client.post('/settings/appearance',json={'theme':'grafit'}).status_code,400)
  self.assertEqual(self.save('unknown').status_code,400)
  self.assertEqual(self.save(['grafit']).status_code,400)
  for t in THEMES:
   self.assertEqual(self.save(t['id']).status_code,200)
   self.assertEqual(json.loads(self.path.read_text())['theme'],t['id'])
   self.assertIn('data-theme="'+t['id']+'"',self.client.get('/settings').text)
  self.save('grafit')
  self.client.post('/logout',data={'csrf_token':self.token()})
  self.assertIn('data-theme="grafit"',self.client.get('/login').text)
  self.login()
  self.assertIn('data-theme="grafit"',self.client.get('/settings').text)
  fresh=self.app.test_client()
  self.assertIn('data-theme="grafit"',fresh.get('/login').text)
  with patch('osvc_app.themes.os.replace',side_effect=OSError('test')):
   self.assertEqual(self.save('piskovy').status_code,500)
  self.assertEqual(json.loads(self.path.read_text())['theme'],'grafit')
 def test_contrast(self):
  self.assertEqual(len(THEMES),22)
  self.assertEqual(len({x['id'] for x in THEMES}),22); self.assertEqual(len({x['name'] for x in THEMES}),22)
  # původní id zůstávají (uložená volba a ZIP zálohy), tmavých je víc než světlých
  for old in ('cisty','modry','tyrkysovy','lesni','olivovy','piskovy','vinovy','indigo','nordic','grafit','nocni-modra','temny-tyrkys'):
   self.assertIn(old,{x['id'] for x in THEMES})
  self.assertGreater(sum(x['dark'] for x in THEMES),sum(not x['dark'] for x in THEMES))
  for theme in THEMES:
   t=theme['tokens']
   for bg in ['bg','surface','surface-alt']:
    for fg in ['text','muted','primary','primary-hover','success','warning','danger','info']:
     self.assertGreaterEqual(contrast(t[fg],t[bg]),4.5,(theme['id'],fg,bg))
    self.assertGreaterEqual(contrast(t['input-border'],t[bg]),3)
   for bg in ['primary','primary-hover']:
    self.assertGreaterEqual(contrast(t['primary-text'],t[bg]),4.5)
   for status in ['success','warning','danger','info']:
    self.assertGreaterEqual(contrast(t[status],t[status+'-bg']),4.5)

unittest.main(verbosity=2)
