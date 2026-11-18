"""Přihlášení, odhlášení a napájení (/login, /logout, /system/*).
Stránky jsou na blueprintu 'main' z routes.py, takže URL a názvy endpointů (main.login, main.logout, …) zůstávají."""
from flask import render_template, redirect, url_for, flash, session, request, current_app, jsonify
from flask_wtf.csrf import validate_csrf
from werkzeug.security import check_password_hash
from .forms import LoginForm
from .routes import bp, login_required
from . import ucet


@bp.route('/login',methods=['GET','POST'])
def login():
 form=LoginForm()
 if form.validate_on_submit():
  u=ucet.overit(form.username.data,form.password.data)   # účet v aplikaci (I2), před převzetím z nastavení serveru
  if u:
   session.clear()
   session['user']=u['username']
   session['auth']=u['auth_version']
   session['local_auth']=1
   return redirect(url_for('main.dashboard'))
  flash('Nesprávné uživatelské jméno nebo heslo.','error')
 return render_template('login.html',form=form)

@bp.post('/logout')
@login_required
def logout(): session.clear(); return redirect(url_for('main.login'))

@bp.post('/system/shutdown')
@login_required
def shutdown_system():
 return system_action('poweroff')

@bp.post('/system/stop')
@login_required
def stop_application():
 return system_action('stop')

def system_action(action):
 from .system_control import request_action
 validate_csrf(request.form.get('csrf_token'))
 zastav=current_app.config.get('OSVC_ZASTAV')   # samostatná instalace: spouštěč ukončí sám sebe (I4)
 if action=='stop' and zastav:
  zastav()
  return jsonify(ok=True,message='OSVČ aplikace se ukončuje.'+(' Znovu ji spustíte zástupcem v nabídce Start.' if current_app.config.get('OSVC_WINDOWS') else ' Znovu ji spustíte příkazem sudo systemctl start osvc-evidence.')),202
 if action=='poweroff' and not current_app.config.get('SYSTEM_SHUTDOWN_ENABLED'):
  return jsonify(ok=False,message='Vypnutí počítače není povoleno.'),503
 try:request_action(action)
 except (OSError,ValueError):
  current_app.logger.warning('Host control request failed: %s',action)
  return jsonify(ok=False,message='Akci se nepodařilo předat správci systému. Zkuste to znovu.'),503
 return jsonify(ok=True,message='OSVČ aplikace se zastavuje. Počítač zůstává spuštěný.' if action=='stop' else 'Počítač se vypíná.'),202
