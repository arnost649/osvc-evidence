"""Doklady a přílohy (/documents, /uploads, /attachments).
Stránky jsou na blueprintu 'main' z routes.py, takže URL a názvy endpointů (url_for('main.…')) zůstávají."""
import hashlib, uuid
from flask import abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_wtf.csrf import validate_csrf
from pathlib import Path
from werkzeug.utils import secure_filename
from wtforms.validators import ValidationError
from .db import execute, query
from .forms import DocumentForm
from .pagination import paginate
from .routes import bp, ALLOWED, choices, login_required, val


@bp.route('/documents',methods=['GET','POST'])
@bp.route('/documents/<int:ident>/edit',methods=['GET','POST'])
@login_required
def documents(ident=None):
 form=DocumentForm(); choices(form,'counterparty_id','SELECT id,name FROM counterparties WHERE deleted_at IS NULL ORDER BY name')
 existing=query('SELECT * FROM documents WHERE id=%s',(ident,),True) if ident else None
 if ident and not existing: abort(404)
 if existing and existing.get('system_type')=='income_connector':abort(409,description='Příjem spravuje jeho externí zdroj.')
 if request.method=='GET' and existing: form.process(data=existing)
 if form.validate_on_submit():
  args=(form.document_type.data,val(form.number.data),val(form.variable_symbol.data),val(form.counterparty_id.data),form.issue_date.data,val(form.taxable_date.data),val(form.due_date.data),form.gross_total.data,val(form.note.data))
  if ident: execute('UPDATE documents SET document_type=%s,number=%s,variable_symbol=%s,counterparty_id=%s,issue_date=%s,taxable_date=%s,due_date=%s,gross_total=%s,note=%s WHERE id=%s',args+(ident,)); doc_id=ident
  else: doc_id=execute("INSERT INTO documents (document_type,number,variable_symbol,counterparty_id,issue_date,taxable_date,due_date,gross_total,note,source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual')",args)
  file=form.upload.data
  if file and file.filename:
   if file.mimetype not in ALLOWED: flash('Povolený je pouze PDF, JPG nebo PNG.','error'); return redirect(request.url)
   ext=Path(secure_filename(file.filename)).suffix.lower()
   if ext not in {'.pdf','.jpg','.jpeg','.png'}: flash('Neplatná přípona souboru.','error'); return redirect(request.url)
   stored=f'{uuid.uuid4().hex}{ext}'; target=Path(current_app.config['UPLOAD_FOLDER'])/stored; file.save(target)
   execute('INSERT INTO attachments (document_id,original_filename,stored_filename,mime_type,sha256) VALUES (%s,%s,%s,%s,%s)',(doc_id,secure_filename(file.filename),stored,file.mimetype,hashlib.sha256(target.read_bytes()).hexdigest()))
  flash('Doklad uložen.','success'); return redirect(url_for('main.document_detail',ident=doc_id))
 from . import moduly
 rows,pager=paginate('SELECT d.*,c.name counterparty,(SELECT s.name FROM income_source_records r JOIN income_sources s ON s.id=r.source_id WHERE r.document_id=d.id LIMIT 1) source_name FROM documents d LEFT JOIN counterparties c ON c.id=d.counterparty_id WHERE d.deleted_at IS NULL'+moduly.skryt_doklady_sql()+' ORDER BY d.issue_date DESC,d.id DESC')
 return render_template('documents.html',form=form,rows=rows,pager=pager,editing=bool(ident))
@bp.route('/documents/<int:ident>')
@login_required
def document_detail(ident):
 doc=query('SELECT d.*,c.name counterparty FROM documents d LEFT JOIN counterparties c ON c.id=d.counterparty_id WHERE d.id=%s',(ident,),True)
 if not doc: abort(404)
 source=query('SELECT s.name FROM income_source_records r JOIN income_sources s ON s.id=r.source_id WHERE r.document_id=%s LIMIT 1',(ident,),one=True)
 return render_template('document_detail.html',doc=doc,source_name=source['name'] if source else None,items=query('SELECT i.* FROM document_items i WHERE i.document_id=%s AND i.deleted_at IS NULL',(ident,)),attachments=query('SELECT * FROM attachments WHERE document_id=%s AND deleted_at IS NULL',(ident,)),receipt_fuel=query('SELECT f.id,f.station FROM fuel_purchases f WHERE f.document_id=%s AND f.deleted_at IS NULL LIMIT 1',(ident,),one=True))
@bp.post('/documents/<int:ident>/items')
@login_required
def add_document_item(ident):
 try: validate_csrf(request.form.get('csrf_token'))
 except ValidationError: abort(400)
 doc=query('SELECT id FROM documents WHERE id=%s AND deleted_at IS NULL',(ident,),True)
 if not doc: abort(404)
 description=(request.form.get('description') or '').strip()
 try: gross=round(float(request.form.get('gross_amount','')),2); quantity=float(request.form.get('quantity') or 1)
 except ValueError: gross=-1; quantity=0
 category=None  # legacy column, no accounting classification
 if not description or gross < 0 or quantity <= 0: flash('Vyplňte popis, kladné množství a částku.','error'); return redirect(url_for('main.document_detail',ident=ident))
 execute('INSERT INTO document_items (document_id,category_id,description,quantity,gross_amount) VALUES (%s,%s,%s,%s,%s)',(ident,category,description,quantity,gross))
 flash('Položka přidána.','success'); return redirect(url_for('main.document_detail',ident=ident))
@bp.post('/documents/<int:ident>/cancel')
@login_required
def cancel_document(ident): execute('UPDATE documents SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s AND deleted_at IS NULL',(ident,)); flash('Doklad zrušen.','success'); return redirect(url_for('main.documents'))
@bp.route('/uploads/<name>')
@login_required
def upload(name): return send_from_directory(current_app.config['UPLOAD_FOLDER'],secure_filename(name),as_attachment=True)

@bp.route('/attachments/<int:ident>/view')
@login_required
def attachment_view(ident):
 attachment=query('SELECT stored_filename,mime_type FROM attachments WHERE id=%s AND deleted_at IS NULL',(ident,),one=True)
 if not attachment: abort(404)
 safe=secure_filename(attachment['stored_filename'])
 if not safe or safe != attachment['stored_filename']: abort(404)
 return send_from_directory(current_app.config['UPLOAD_FOLDER'],safe,as_attachment=False,mimetype=attachment['mime_type'] or None)
