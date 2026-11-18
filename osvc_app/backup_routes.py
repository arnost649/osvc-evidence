import json, os, tempfile, uuid
from pathlib import Path
from flask import Blueprint, request, session, render_template, send_file, jsonify, current_app
from .routes import login_required
from . import backup as b
bp=Blueprint('backup',__name__,url_prefix='/settings/backup')

@bp.post('/export')
@login_required
def export():
    fd,name=tempfile.mkstemp(suffix='.zip');os.close(fd)
    try:
        drafts=json.loads(request.form.get('drafts','{}'))
        m=b.create_backup(name,drafts)
        b.validate_backup(name)
        response=send_file(name,as_attachment=True,download_name='osvc-'+m['created_at'][:10]+'.zip',mimetype='application/zip')
        response.headers['X-Backup-Warnings']=str(len(m['warnings']))
        return response
    except (b.BackupError,ValueError):return jsonify(error='Zálohu nelze vytvořit. Zkontrolujte dostupnost dat a dokumentů.'),400
    finally:os.unlink(name)

@bp.post('/validate')
@login_required
def validate():
    folder=b.state_dir()/'restore-staging';folder.mkdir(mode=0o700,exist_ok=True)
    token=uuid.uuid4().hex;path=folder/(token+'.zip')
    try:
        upload=request.files.get('backup')
        if not upload:raise b.BackupError('Vyberte ZIP zálohu.')
        upload.save(path);path.chmod(0o600)
        m,data=b.validate_backup(path)
        old=session.get('backup_token')
        if old and len(old)==32:(folder/(old+'.zip')).unlink(missing_ok=True)
        session['backup_token']=token
        return render_template('_backup_summary.html' if request.headers.get('X-Backup-Fragment')=='1' else 'backup_preview.html',backup=m,token=token,archive_bytes=path.stat().st_size)
    except (b.BackupError,ValueError) as exc:
        path.unlink(missing_ok=True)
        return render_template('_backup_summary.html' if request.headers.get('X-Backup-Fragment')=='1' else 'backup_preview.html',error=str(exc)),400

@bp.post('/restore')
@login_required
def restore():
    token=request.form.get('token','')
    if not token or token!=session.get('backup_token'):return jsonify(error='Neplatný požadavek obnovy.'),400
    path=b.state_dir()/'restore-staging'/(token+'.zip')
    try:
        m,snapshot=b.restore_backup(path,json.loads(request.form.get('drafts','{}')))
        session.pop('backup_token',None);path.unlink(missing_ok=True)
        drafts=b.settings_paths()['browser-drafts.json']
        return jsonify(ok=True,drafts=json.loads(drafts.read_text(encoding='utf-8')) if drafts.exists() else {})
    except (b.BackupError,ValueError) as exc:return jsonify(error=str(exc)),400
