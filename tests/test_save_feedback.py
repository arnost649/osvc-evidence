import unittest
from flask import flash,redirect
from osvc_app import create_app
class Feedback(unittest.TestCase):
 def test_only_confirmed_redirect_save_is_silent(self):
  app=create_app({'TESTING':True,'WTF_CSRF_ENABLED':False})
  @app.post('/_test-save')
  def save():flash('Uloženo','success');return redirect('/login')
  @app.post('/_test-error')
  def error():flash('Chyba','error');return redirect('/login')
  @app.post('/_test-preview')
  def preview():return {'ok':True}
  with app.test_client() as client:
   client.post('/_test-save',data={'_save_action':'yes'})
   with client.session_transaction() as s:self.assertEqual(s['_flashes'][0][0],'saved');s.pop('_flashes')
   client.post('/_test-save')
   with client.session_transaction() as s:self.assertEqual(s['_flashes'][0][0],'success');s.pop('_flashes')
   client.post('/_test-error',data={'_save_action':'yes'})
   with client.session_transaction() as s:self.assertEqual(s['_flashes'][0][0],'error');s.pop('_flashes')
   client.post('/_test-preview',data={'_save_action':'yes'})
   with client.session_transaction() as s:self.assertNotIn('_flashes',s)
if __name__=='__main__':unittest.main()
