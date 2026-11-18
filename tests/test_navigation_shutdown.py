import unittest
from unittest.mock import patch
from osvc_app import create_app
class Control(unittest.TestCase):
 def test_routes_delegate_only_known_actions(self):
  app=create_app({'TESTING':True,'WTF_CSRF_ENABLED':False,'SYSTEM_SHUTDOWN_ENABLED':True})
  with app.test_client() as client:
   with client.session_transaction() as session:session['user']='osvc';session['local_auth']=1
   with patch('osvc_app.system_routes.validate_csrf'),patch('osvc_app.system_control.request_action') as call:
    for path,action in [('/system/stop','stop'),('/system/shutdown','poweroff')]:
     response=client.post(path);self.assertEqual(response.status_code,202);call.assert_called_with(action)
if __name__=='__main__':unittest.main()
