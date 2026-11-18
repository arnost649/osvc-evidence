"""Only two operations on the root-owned host helper; no Docker/root shell access."""
import json,socket
from flask import current_app

def request_action(action):
 if action not in ('stop','poweroff'):raise ValueError('Neplatná akce.')
 with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
  client.settimeout(3)
  client.connect(current_app.config.get('SYSTEM_CONTROL_SOCKET','/run/osvc-control/control.sock'))
  client.sendall((action+'\n').encode())
  with client.makefile('rb') as stream:result=json.loads(stream.readline(1024))
 if not result.get('ok'):raise ValueError(result.get('error','Akci nelze provést.'))
