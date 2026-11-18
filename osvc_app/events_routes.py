"""Akce / účel (/events).
Stránky jsou na blueprintu 'main' z routes.py, takže URL a názvy endpointů (main.events, main.new_event, main.event_detail) zůstávají."""
from flask import render_template, redirect, url_for, abort
from .db import query, execute
from .forms import EventForm
from .pagination import paginate
from .routes import bp, login_required, audit
from . import system_types


@bp.route('/events')
@login_required
def events():
 rows,pager=paginate('SELECT * FROM business_events WHERE deleted_at IS NULL ORDER BY event_date DESC,name,id DESC')
 return render_template('events.html',events=rows,pager=pager)

@bp.route('/events/new',methods=['GET','POST'])
@login_required
def new_event():
 form=EventForm()
 if form.validate_on_submit():
  ident=execute('INSERT INTO business_events (event_date,name,location,note) VALUES (%s,%s,%s,%s)',(form.event_date.data,form.name.data,form.location.data,form.note.data)); audit('business_event',ident,'insert',new=query('SELECT * FROM business_events WHERE id=%s',(ident,),one=True)); return redirect(url_for('main.event_detail',ident=ident))
 return render_template('event_new.html',form=form)

@bp.route('/events/<int:ident>')
@login_required
def event_detail(ident):
 event=query('SELECT * FROM business_events WHERE id=%s AND deleted_at IS NULL',(ident,),one=True)
 if not event: abort(404)
 from . import moduly
 doprava=moduly.zapnuto('doprava')   # vypnutá Doprava: jízdy a PHM akce se neukazují
 platby=query("SELECT p.*,c.name counterparty FROM payments p LEFT JOIN counterparties c ON c.id=p.counterparty_id WHERE p.event_id=%s AND p.deleted_at IS NULL"+moduly.skryt_platby_sql()+" ORDER BY p.payment_date",(ident,))
 for x in platby: x['kind']=system_types.payment_kind(x)   # štítek z Nastavení → Názvy typů
 return render_template('event_detail.html',event=event,trips=[] if not doprava else query('SELECT t.*,v.name vehicle FROM trips t JOIN vehicles v ON v.id=t.vehicle_id WHERE t.event_id=%s AND t.deleted_at IS NULL ORDER BY t.trip_date',(ident,)),fuels=[] if not doprava else query('SELECT f.*,v.name vehicle FROM fuel_purchases f JOIN vehicles v ON v.id=f.vehicle_id WHERE f.event_id=%s AND f.deleted_at IS NULL ORDER BY f.purchase_date',(ident,)),payments=platby,type_labels=system_types.labels())
