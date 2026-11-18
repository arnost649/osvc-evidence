"""Validate the payment settlement contract exported by an e-shop (optional, per income source). No bank client or matcher.

The order field with the settlement payload is configured per source (configuration.settlement_field);
the expected evidence_source is configuration.settlement_evidence_source, or the source host name without "www.".
Sources without settlement_field export no contract and their incomes are not marked for review."""
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

CENT = Decimal('0.01')
MAX_MONEY = Decimal('999999999999.99')

def money(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > MAX_MONEY or number != number.quantize(CENT):
            return None
        return number.quantize(CENT)
    except (InvalidOperation, ValueError, TypeError):
        return None


def evidence_host(source_url):
    host = (urlsplit(source_url or '').hostname or '').lower()
    return host[4:] if host.startswith('www.') else host


def settlement(order, source_url='', field=None, evidence_source=None):
    """Missing or invalid evidence keeps the nominal amount explicitly provisional (only for sources with a contract)."""
    nominal = money(order.get('total'))
    if nominal is None or nominal < 0:
        raise ValueError('Neplatná nominální částka objednávky.')
    payload = order.get(field) if field else None
    expected_source = evidence_source or evidence_host(source_url)
    result = {'invoice_amount_czk': nominal, 'payment_received_czk': None,
              'payment_currency': None, 'fx_settlement_diff_czk': None,
              'payment_needs_review': bool(field), 'settlement_evidence': None}
    if not isinstance(payload, dict):
        return result
    currency = payload.get('payment_currency')
    result['payment_currency'] = currency if currency in ('CZK', 'EUR') else None
    received = money(payload.get('payment_received_czk'))
    ids = payload.get('transaction_ids')
    valid = (payload.get('schema_version') == 1 and bool(expected_source) and payload.get('evidence_source') == expected_source
             and str(payload.get('order_id')) == str(order.get('id'))
             and money(payload.get('invoice_amount_czk')) == nominal
             and payload.get('evidence_kind') == 'fio_czk_account_movement'
             and isinstance(ids, list) and 0 < len(ids) <= 100
             and all(isinstance(v, str) and v.isdigit() for v in ids) and len(set(ids)) == len(ids)
             and received is not None and received > 0
             and money(payload.get('fx_settlement_diff_czk')) == received - nominal)
    if valid:
        result.update(payment_received_czk=received, fx_settlement_diff_czk=received - nominal,
                      payment_needs_review=payload.get('verification_required') is not False or currency not in ('CZK', 'EUR'),
                      settlement_evidence={'kind': 'fio_czk_account_movement', 'transaction_ids': ids})
    else:
        result['payment_needs_review'] = True
    return result


def preserve_verified(values, previous):
    """A temporary loss of upstream evidence must never replace a proven cash amount."""
    if previous and previous.get('payment_received_czk') is not None and values['payment_received_czk'] is None:
        received = previous['payment_received_czk']
        values.update(payment_received_czk=received, payment_currency=previous.get('payment_currency'),
                      fx_settlement_diff_czk=received - values['invoice_amount_czk'], payment_needs_review=True)
    return values
