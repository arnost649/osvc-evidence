"""Explicit classification changes only; never modifies accounting amounts."""
import json
from flask import Blueprint,request,render_template,redirect,flash,abort
from .routes import login_required
from .annual_routes import year_arg
from .db import connection,query
from . import expense_tax
bp=Blueprint('expense_tax',__name__)

@bp.get('/payments/expense/tax')
@login_required
def review():
 return redirect(f'/payments/expense?year={year_arg()}')

@bp.post('/payments/expense/<int:ident>/tax')
@bp.post('/settings/categories/<int:ident>/tax',defaults={'category':True})
@login_required
def save(ident,category=False):
 if not category:return redirect(f'/payments/expense/{ident}?year={year_arg()}')
 abort(410,description='Daňové uplatnění se ukládá přímo u výdaje.')
