from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, DateField, DecimalField, SelectField, TextAreaField, IntegerField, FileField, HiddenField
from wtforms.validators import DataRequired, Optional, Length, NumberRange
from decimal import Decimal, DecimalException, ROUND_HALF_UP

class LoginForm(FlaskForm):
    # správce hesel: přihlašovací formulář = username + current-password
    username=StringField('Uživatelské jméno', validators=[DataRequired(), Length(max=100)], render_kw={'autocomplete': 'username', 'autocapitalize': 'none', 'spellcheck': 'false'})
    password=PasswordField('Heslo', validators=[DataRequired()], render_kw={'autocomplete': 'current-password'})

class PaymentForm(FlaskForm):
    payment_date=DateField('Datum úhrady', validators=[DataRequired()])
    counterparty_name=StringField('Dodavatel', validators=[DataRequired(),Length(max=200)])
    counterparty_id=HiddenField(validators=[Optional()])
    description=StringField('Za co jsem platil', validators=[DataRequired(),Length(max=255)])
    amount=DecimalField('Částka', validators=[DataRequired()])
    upload=FileField('Příloha (PDF/JPG/PNG)')
    note=TextAreaField('Poznámka', validators=[Optional()])

class ManualExpenseForm(PaymentForm):
    tax_mode=SelectField('Daňové uplatnění',choices=[('100','100 %'),('50','50 %'),('custom','Vlastní…')],default='100',validators=[DataRequired()])
    tax_pct=StringField('Vlastní podíl (%)')

    def validate(self, extra_validators=None):
        valid=super().validate(extra_validators)
        from .expense_tax import resolve_submission
        try:resolve_submission({'tax_mode':self.tax_mode.data,'tax_pct':self.tax_pct.data or ''})
        except ValueError as exc:
            field=self.tax_pct if self.tax_mode.data=='custom' else self.tax_mode
            field.errors=list(field.errors)+[str(exc)];valid=False
        return valid

class DocumentForm(FlaskForm):
    document_type=SelectField('Typ', choices=[('issued_invoice','Vydaná faktura'),('received_invoice','Přijatá faktura'),('receipt','Účtenka'),('credit_note','Dobropis'),('other','Ostatní')])
    number=StringField('Číslo dokladu', validators=[Optional(),Length(max=100)]); variable_symbol=StringField('VS', validators=[Optional(),Length(max=20)])
    counterparty_id=SelectField('Protistrana', coerce=int, choices=[(0,'— nevybráno —')]); issue_date=DateField('Datum vystavení', validators=[DataRequired()]); taxable_date=DateField('DUZP', validators=[Optional()]); due_date=DateField('Splatnost', validators=[Optional()])
    gross_total=DecimalField('Částka celkem', validators=[DataRequired()]); note=TextAreaField('Poznámka', validators=[Optional()]); upload=FileField('Příloha (PDF/JPG/PNG)')

class TripForm(FlaskForm):
    trip_date=DateField('Datum', validators=[DataRequired()]); trip_end_date=DateField('Datum ukončení', validators=[Optional()]); vehicle_id=SelectField('Vozidlo', coerce=int, validators=[DataRequired()]); origin=StringField('Odkud', validators=[DataRequired(),Length(max=255)]); destination=StringField('Kam', validators=[DataRequired(),Length(max=255)]); purpose=StringField('Účel', validators=[DataRequired(),Length(max=255)]); distance_km=DecimalField('Km', validators=[Optional(),NumberRange(min=0)]); fuel_purchase_id=SelectField('Cena PHM', coerce=int, validators=[Optional()]); note=TextAreaField('Poznámka', validators=[Optional()])

class FuelForm(FlaskForm):
    purchase_date=DateField('Datum', validators=[DataRequired()]); vehicle_id=SelectField('Vozidlo', coerce=int, validators=[DataRequired()]); liters=DecimalField('Litry', places=None, validators=[Optional()]); price_per_liter=DecimalField('Cena/l', validators=[DataRequired(),NumberRange(min=0)]); total_amount=DecimalField('Celkem', validators=[DataRequired(),NumberRange(min=0)]); counterparty_name=StringField('Čerpací stanice', validators=[DataRequired(),Length(max=200)]); counterparty_id=HiddenField(validators=[Optional()]); upload=FileField('Účtenka (PDF/JPG/PNG)'); note=TextAreaField('Poznámka', validators=[Optional()])

    def process(self, *args, **kwargs):
        super().process(*args, **kwargs)
        for field in (self.price_per_liter, self.total_amount):
            if field.raw_data and ',' in field.raw_data[0]:
                try:
                    field.process_formdata([field.raw_data[0].replace(',', '.')])
                    field.process_errors=[]
                except ValueError:
                    pass
        # Litry ve formuláři nejsou: vždy Cena celkem ÷ Cena za litr (2 des. místa); odeslaná hodnota se ignoruje.
        # U úpravy beze změny ceny zůstanou uložené litry (řeší trasa uložení).
        self.liters.raw_data=None
        self.liters.process_errors=[]
        self.liters.data=None
        price,total=self.price_per_liter.data,self.total_amount.data
        if price is not None and total is not None and price.is_finite() and total.is_finite() and price>0 and total>=0:
            try:
                self.liters.data=(total/price).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
            except DecimalException:
                pass

class EventForm(FlaskForm):
    event_date=DateField('Datum', validators=[DataRequired()]); name=StringField('Název', validators=[DataRequired(),Length(max=200)]); location=StringField('Místo', validators=[Optional(),Length(max=200)]); note=TextAreaField('Poznámka', validators=[Optional()])
