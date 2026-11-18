"""Read-only WooCommerce import. No credentials are ever included in exceptions or logs."""
import hashlib
import errno
from . import zamky
import re
import json
import os
import posixpath
import stat
import tempfile
from contextlib import contextmanager, ExitStack
from datetime import date, datetime, timezone
from . import cas
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app, g

from .db import execute, query

class SyncConfigurationError(RuntimeError):
    pass


class InvoicePdfUnavailable(RuntimeError):
    """A pre-existing WPO archive PDF cannot be read safely."""
    def __init__(self, message, path=None, status=None):
        super().__init__(message)
        self.path=path
        self.status=status


def source_settings():
    # vše běží uvnitř provider(source).runtime() – zdroj je vždy nastavený.
    return getattr(g, 'income_source', None) or {}

def runtime_config(key):
    settings=source_settings()
    if not settings:return None
    from .connectors import unpack,secrets_for
    c=unpack(settings.get('configuration'));secret=secrets_for(settings)
    mapping={'WC_CONSUMER_KEY':secret.get('consumer_key'),'WC_CONSUMER_SECRET':secret.get('consumer_secret'),
      'WPO_INVOICE_SFTP_HOST':c.get('sftp_host'),'WPO_INVOICE_SFTP_PORT':c.get('sftp_port',22),
      'WPO_INVOICE_SFTP_USER':c.get('sftp_user'),'WPO_INVOICE_SFTP_PASSWORD_FILE':secret.get('sftp_password_file'),
      'WPO_INVOICE_SFTP_KNOWN_HOSTS':secret.get('known_hosts'),'WPO_INVOICE_REMOTE_DIR':c.get('legacy_dir'),
      'INVOICE_PRIVATE_DIR':c.get('private_dir')}
    return mapping.get(key)

def source_documents():
    settings=source_settings()
    if not settings:return []
    return query("SELECT d.id,d.number,d.source_ref,r.external_id FROM documents d JOIN income_source_records r ON r.document_id=d.id WHERE r.source_id=%s AND d.deleted_at IS NULL",(settings['id'],))

def invoice_filename(order_id):
    sid=source_settings().get('id')
    return f"source-{sid}-order-{int(order_id)}-invoice.pdf" if sid else f"order-{int(order_id)}-invoice.pdf"

def import_documents():
    return bool(source_settings().get('import_documents', True))

def configured():
    return bool(_base_url()) and all(runtime_config(k) for k in ('WC_CONSUMER_KEY', 'WC_CONSUMER_SECRET'))


def sync_from_date():
    settings = source_settings()
    value = settings.get('sync_from')
    if isinstance(value, date): return value
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def sync_ready():
    return configured() and sync_from_date() is not None


def invoice_archive_ready():
    required = ('WPO_INVOICE_SFTP_HOST', 'WPO_INVOICE_SFTP_USER', 'WPO_INVOICE_SFTP_PASSWORD_FILE', 'WPO_INVOICE_SFTP_KNOWN_HOSTS', 'WPO_INVOICE_REMOTE_DIR')
    return all(runtime_config(key) for key in required)


def _base_url():
    settings = source_settings()
    return (settings.get('url') or '').rstrip('/')


def _wpo_invoice_number(order):
    value = order.get('wpo_wcpdf_invoice_number')
    if value:
        return str(value)
    for meta in order.get('meta_data') or []:
        if isinstance(meta, dict) and meta.get('key') == '_wcpdf_invoice_number' and meta.get('value'):
            return str(meta['value'])
    return None


@contextmanager
def invoice_sftp_session():
    """One SFTP connection for a whole sync: opened lazily on the first PDF, closed at the end.
    A failed login is remembered, so the remaining documents do not retry it (the server rejects bursts of logins)."""
    if getattr(g, 'invoice_sftp_session', None) is not None:
        yield; return
    session = {'stack': ExitStack(), 'sftp': None, 'error': None, 'has_invoice': {}}
    g.invoice_sftp_session = session
    try:
        yield
    finally:
        g.invoice_sftp_session = None
        session['stack'].close()


@contextmanager
def _invoice_sftp():
    """Shared connection inside invoice_sftp_session(), otherwise a connection of its own."""
    session = getattr(g, 'invoice_sftp_session', None)
    if session is None:
        with _open_invoice_sftp() as sftp:
            yield sftp
        return
    if session['error'] is not None:
        raise InvoicePdfUnavailable(str(session['error']), status=session['error'].status)
    if session['sftp'] is None:
        try:
            session['sftp'] = session['stack'].enter_context(_open_invoice_sftp())
        except InvoicePdfUnavailable as exc:
            session['error'] = exc
            raise
    try:
        yield session['sftp']
    except InvoicePdfUnavailable:
        raise
    except OSError as exc:
        if exc.errno is not None: raise  # file-level SFTP error (missing path, permissions); connection is fine
        session['error'] = InvoicePdfUnavailable('Archiv faktur není momentálně dostupný: '+type(exc).__name__, status=type(exc).__name__)
        raise session['error'] from exc
    except Exception as exc:
        # Broken transport: no further attempts in this sync.
        session['error'] = InvoicePdfUnavailable('Archiv faktur není momentálně dostupný: '+type(exc).__name__, status=type(exc).__name__)
        raise session['error'] from exc


@contextmanager
def _open_invoice_sftp():
    """Pinned-host-key, read-only SFTP connection to the existing WPO archive."""
    try:
        import paramiko
    except ImportError as exc:
        raise InvoicePdfUnavailable('SFTP client není lokálně dostupný.') from exc
    password_file = Path(runtime_config('WPO_INVOICE_SFTP_PASSWORD_FILE'))
    known_hosts = Path(runtime_config('WPO_INVOICE_SFTP_KNOWN_HOSTS'))
    if not password_file.is_file() or stat.S_IMODE(password_file.stat().st_mode) != 0o600 or not known_hosts.is_file():
        raise InvoicePdfUnavailable('SFTP přístup k archivu faktur není bezpečně dostupný.')
    client = paramiko.SSHClient()
    client.load_host_keys(str(known_hosts))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(
            runtime_config('WPO_INVOICE_SFTP_HOST'),
            port=runtime_config('WPO_INVOICE_SFTP_PORT'),
            username=runtime_config('WPO_INVOICE_SFTP_USER'),
            password=password_file.read_text(encoding='utf-8').rstrip('\n'),
            look_for_keys=False,
            allow_agent=False,
            timeout=30,
            banner_timeout=30,
            auth_timeout=30,
        )
        sftp = client.open_sftp()
        sftp.get_channel().settimeout(60)  # a stalled stat/read must not hang verification or sync forever
        try:
            yield sftp
        finally:
            sftp.close()
    except InvoicePdfUnavailable:
        raise
    except Exception as exc:
        raise InvoicePdfUnavailable('Archiv faktur není momentálně dostupný: '+type(exc).__name__, status=type(exc).__name__) from exc
    finally:
        client.close()


def _invoice_sources(order):
    """Paths to existing files only. Never invoke an invoice generator."""
    order_id=int(order['id'])
    from .connectors import unpack
    c=unpack(source_settings().get('configuration'))
    if c.get('invoice_mode')=='sftp_template':
        path=c.get('invoice_template','').replace('{order_id}',str(order_id))
        if not path.startswith('/') or '..' in path.split('/'):raise InvoicePdfUnavailable('Neplatná šablona cesty PDF.')
        return [path]
    private=runtime_config('INVOICE_PRIVATE_DIR')
    meta={m.get('key'):m.get('value') for m in order.get('meta_data') or [] if isinstance(m,dict)}
    # meta klíč s názvem PDF v soukromé složce e-shopu je v nastavení zdroje (configuration.invoice_meta_key)
    meta_key=c.get('invoice_meta_key')
    filename=meta.get(meta_key) if meta_key else None
    if filename:
        if not isinstance(filename,str) or not re.fullmatch(r'invoice-'+str(order_id)+r'-[a-f0-9]+\.pdf',filename):
            raise InvoicePdfUnavailable('Neplatná cesta nového PDF; soubor nebyl načten.')
        return [posixpath.join(private,filename)]
    return [posixpath.join(private,'legacy-wpo',f'faktura-{order_id}.pdf'),
            posixpath.join(runtime_config('WPO_INVOICE_REMOTE_DIR'),f'faktura-{order_id}.pdf')]


def _download_archived_invoice(order_id, order=None):
    order_id=int(order_id)
    sources=_invoice_sources(order or {'id':order_id})
    maximum=int(current_app.config['WPO_INVOICE_MAX_BYTES'])
    with _invoice_sftp() as sftp:
        for remote in sources:
            try:
                info=sftp.lstat(remote)
            except OSError as exc:
                if exc.errno==errno.ENOENT: continue
                raise InvoicePdfUnavailable('Archiv nelze přečíst.',remote,exc.errno) from exc
            if not stat.S_ISREG(info.st_mode) or not 1024 <= info.st_size <= maximum:
                raise InvoicePdfUnavailable('Archivovaný soubor faktury nemá bezpečnou velikost.',remote)
            try:
                with sftp.open(remote,'rb') as source:data=source.read(info.st_size+1)
            except OSError as exc:
                raise InvoicePdfUnavailable('Stažení PDF selhalo.',remote,exc.errno) from exc
            if len(data)!=info.st_size or not data.startswith(b'%PDF-') or b'%%EOF' not in data[-2048:]:
                raise InvoicePdfUnavailable('Archivovaný soubor není úplné PDF.',remote)
            return invoice_filename(order_id),data
    raise InvoicePdfUnavailable('Archivovaná faktura pro objednávku neexistuje.',sources[-1],errno.ENOENT)


def _valid_invoice_attachment(attachment):
    path=Path(current_app.config['UPLOAD_FOLDER'])/attachment['stored_filename']
    if path.parent.resolve()!=Path(current_app.config['UPLOAD_FOLDER']).resolve():return False
    try:
        if not path.is_file() or path.is_symlink() or not 1024<=path.stat().st_size<=current_app.config['WPO_INVOICE_MAX_BYTES']:return False
        data=path.read_bytes()
        return data.startswith(b'%PDF-') and b'%%EOF' in data[-2048:] and hashlib.sha256(data).hexdigest()==attachment['sha256']
    except OSError:return False


def _document_has_invoice(document_id):
    """Platné lokální PDF (velikost, začátek/konec PDF, SHA z DB). V rámci jedné synchronizace
    (invoice_sftp_session) se každý doklad čte a kontroluje jen jednou."""
    session = getattr(g, 'invoice_sftp_session', None)
    cache = session['has_invoice'] if session is not None else None
    if cache is not None and document_id in cache: return cache[document_id]
    result = any(_valid_invoice_attachment(a) for a in query('SELECT id,stored_filename,sha256 FROM attachments WHERE document_id=%s AND deleted_at IS NULL',(document_id,)))
    if cache is not None: cache[document_id] = result
    return result


def _remember_invoice(document_id):
    session = getattr(g, 'invoice_sftp_session', None)
    if session is not None: session['has_invoice'][document_id] = True


def _store_archived_invoice(document_id, order_id, order=None):
    """Idempotent under concurrent local syncs; repair DB/file inconsistencies."""
    upload_dir=Path(current_app.config['UPLOAD_FOLDER'])
    upload_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (upload_dir/f'.invoice-{int(document_id)}.lock').open('ab') as lock:
        zamky.zamkni(lock,vyhradni=True)
        session=getattr(g,'invoice_sftp_session',None)
        if session is not None and session['has_invoice'].get(document_id):return 'already'
        existing=query('SELECT id,stored_filename,sha256 FROM attachments WHERE document_id=%s AND deleted_at IS NULL ORDER BY id',(document_id,))
        if any(_valid_invoice_attachment(a) for a in existing):_remember_invoice(document_id);return 'already'
        filename,data=_download_archived_invoice(order_id,order)
        digest=hashlib.sha256(data).hexdigest()
        target=upload_dir/filename
        if target.exists() and (not target.is_file() or target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest):
            target=upload_dir/(Path(invoice_filename(order_id)).stem+'-'+digest[:12]+'.pdf')
        created=False
        if not target.exists():
            descriptor,temporary_name=tempfile.mkstemp(prefix='.invoice-',suffix='.pdf',dir=upload_dir)
            try:
                with os.fdopen(descriptor,'wb') as temporary:
                    temporary.write(data);temporary.flush();os.fsync(temporary.fileno())
                zamky.nahrad(temporary_name,target);created=True
            finally:
                if os.path.exists(temporary_name):os.unlink(temporary_name)
        elif target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
            raise InvoicePdfUnavailable('Kolize lokálního názvu PDF; soubor nebyl přepsán.')
        values=(filename,target.name,'application/pdf',digest)
        try:
            if existing:
                attachment_id=existing[0]['id']
                execute('UPDATE attachments SET original_filename=%s,stored_filename=%s,mime_type=%s,sha256=%s WHERE id=%s',values+(attachment_id,))
            else:
                attachment_id=execute('INSERT INTO attachments (document_id,original_filename,stored_filename,mime_type,sha256) VALUES (%s,%s,%s,%s,%s)',(document_id,)+values)
        except Exception:
            if created:target.unlink(missing_ok=True)
            raise
        # DB now owns the file; a later audit error must never remove it.
        _remember_invoice(document_id)
        _audit('attachment',attachment_id,'update' if existing else 'insert',new={'document_id':document_id,'stored_filename':target.name})
        return 'added'


def _sync_invoice_for_document(document_id, order):
    order_id=order.get('id')
    if not order_id:return 'missing'
    try:return _store_archived_invoice(document_id,order_id,order)
    except InvoicePdfUnavailable as exc:
        if exc.status==errno.ENOENT:return 'missing'
        current_app.logger.warning('Invoice order=%s path=%s status=%s reason=%s',order_id,exc.path or 'SFTP archive',exc.status or 'validation',str(exc))
        return 'error'
    except Exception as exc:
        current_app.logger.warning('Invoice order=%s status=%s reason=download/storage failure',order_id,getattr(exc,'code',type(exc).__name__))
        return 'error'


def backfill_invoices(orders):
    """Attachment-only repair: never modify payments, orders, or counterparties."""
    by_id={str(o['id']):o for o in orders}
    results=[]
    docs=source_documents()
    with invoice_sftp_session():
     for doc in docs:
        order_id=str(doc['external_id'])
        if _document_has_invoice(doc['id']):status='already'
        elif order_id not in by_id:status='source_unavailable'
        else:status=_sync_invoice_for_document(doc['id'],by_id[order_id])
        results.append({'document_id':doc['id'],'order_id':order_id,'status':status})
    return results


def api_request(endpoint, params=None, method='GET'):
    """Same-origin HTTPS only; never forward credentials across redirects."""
    import base64
    from urllib.request import build_opener, HTTPRedirectHandler
    from .connectors import unpack
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    root=unpack(source_settings().get('configuration')).get('api_root','wp-json/wc/v3').strip('/')
    url=f"{_base_url()}/{root}/{endpoint}"
    if params:url+='?'+urlencode(params)
    token=base64.b64encode(f"{runtime_config('WC_CONSUMER_KEY')}:{runtime_config('WC_CONSUMER_SECRET')}".encode()).decode()
    req=Request(url,headers={'Accept':'application/json','Authorization':f'Basic {token}'},method=method)
    with build_opener(NoRedirect).open(req,timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))

def test_connection():return fetch_orders(test_only=True) is not None

def fetch_order(ident):
    result=api_request('orders/'+str(int(ident)))
    if not isinstance(result,dict) or str(result.get('id'))!=str(ident):raise RuntimeError('Neplatný detail objednávky.')
    return result

def fetch_orders(test_only=False, modified_after=None):
    if not configured():raise SyncConfigurationError('Přístup k API není nastavený.')
    orders=[];page=1
    while True:
        params={'per_page':1 if test_only else 100,'page':page,'orderby':'modified','order':'asc'}
        if modified_after:params.update(modified_after=modified_after,dates_are_gmt='true')
        data=api_request('orders',params)
        if not isinstance(data,list):raise RuntimeError('API vrátilo neočekávaný formát.')
        orders.extend(data)
        if test_only or len(data)<100:break
        page+=1
    return orders


def _date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date().isoformat()
    except (TypeError, ValueError):
        return None


def _money(value):
    try:
        return Decimal(str(value or '0')).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return Decimal('0.00')


def _customer(order):
    billing = order.get('billing') or {}
    name = ' '.join(x for x in (billing.get('first_name'), billing.get('last_name')) if x).strip()
    return {
        'name': name or f"Zákazník objednávky #{order.get('id')}",
        'email': billing.get('email') or None,
        'phone': billing.get('phone') or None,
        'street': billing.get('address_1') or None,
        'city': billing.get('city') or None,
        'postal_code': billing.get('postcode') or None,
        'country_code': (billing.get('country') or 'CZ')[:2].upper(),
    }


def _audit(entity, ident, action, old=None, new=None):
    def encoded(value):
        return json.dumps(value, default=str, ensure_ascii=False) if value is not None else None
    execute('INSERT INTO audit_log (entity_type,entity_id,action,old_data,new_data) VALUES (%s,%s,%s,%s,%s)', (entity, ident, action, encoded(old), encoded(new)))


def _upsert_counterparty(order, existing=None):
    customer = _customer(order)
    if existing:
        old = query('SELECT * FROM counterparties WHERE id=%s', (existing,), one=True)
        execute("UPDATE counterparties SET name=%s,email=%s,phone=%s,street=%s,city=%s,postal_code=%s,country_code=%s,source='woocommerce',role='customer' WHERE id=%s", tuple(customer.values()) + (existing,))
        new = query('SELECT * FROM counterparties WHERE id=%s', (existing,), one=True)
        if old != new:
            _audit('counterparty', existing, 'update', old, new)
        return existing
    row=query("SELECT c.id FROM counterparties c JOIN documents d ON d.counterparty_id=c.id JOIN income_source_records r ON r.document_id=d.id WHERE r.source_id=%s AND c.name=%s AND c.email <=> %s AND c.deleted_at IS NULL LIMIT 1",(source_settings()['id'],customer['name'],customer['email']),one=True)
    if row:
        return _upsert_counterparty(order, row['id'])
    ident = execute("INSERT INTO counterparties (name,email,phone,street,city,postal_code,country_code,source,role) VALUES (%s,%s,%s,%s,%s,%s,%s,'woocommerce','customer')", tuple(customer.values()))
    _audit('counterparty', ident, 'insert', new=query('SELECT * FROM counterparties WHERE id=%s', (ident,), one=True))
    return ident


def _line_data(order):
    out = []
    for item in order.get('line_items') or []:
        out.append((str(item.get('name') or 'Položka objednávky')[:255], _money(item.get('quantity') or 1), _money(item.get('total'))))
    return out


def _sync_items(document_id, order):
    wanted = _line_data(order)
    existing = query('SELECT id,description,quantity,gross_amount FROM document_items WHERE document_id=%s AND deleted_at IS NULL ORDER BY id', (document_id,))
    current = [(r['description'], _money(r['quantity']), _money(r['gross_amount'])) for r in existing]
    if current == wanted:
        return False
    for row in existing:
        old = query('SELECT * FROM document_items WHERE id=%s', (row['id'],), one=True)
        execute('UPDATE document_items SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s AND deleted_at IS NULL', (row['id'],))
        _audit('document_item', row['id'], 'cancel', old, query('SELECT * FROM document_items WHERE id=%s', (row['id'],), one=True))
    for description, quantity, gross in wanted:
        item_id = execute('INSERT INTO document_items (document_id,description,quantity,gross_amount) VALUES (%s,%s,%s,%s)', (document_id, description, quantity, gross))
        _audit('document_item', item_id, 'insert', new=query('SELECT * FROM document_items WHERE id=%s', (item_id,), one=True))
    return True


def _cancel_import(doc):
    old_doc = query('SELECT * FROM documents WHERE id=%s', (doc['id'],), one=True)
    if old_doc and old_doc['deleted_at'] is None:
        execute('UPDATE documents SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s AND deleted_at IS NULL', (doc['id'],))
        _audit('document', doc['id'], 'cancel', old_doc, query('SELECT * FROM documents WHERE id=%s', (doc['id'],), one=True))
    payment = query("SELECT * FROM payments WHERE document_id=%s AND direction='income' ORDER BY id LIMIT 1", (doc['id'],), one=True)
    if payment and payment['deleted_at'] is None:
        execute('UPDATE payments SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s AND deleted_at IS NULL', (payment['id'],))
        _audit('payment', payment['id'], 'cancel', payment, query('SELECT * FROM payments WHERE id=%s', (payment['id'],), one=True))


def normalize_income(order):
    from .income_sources import ExternalIncome, IncomeDocument
    settings=source_settings()
    from .payment_settlement import settlement
    from .connectors import unpack
    c = unpack(settings.get('configuration'))
    values = settlement(order, _base_url(), c.get('settlement_field') or None, c.get('settlement_evidence_source') or None)
    metadata = {'status': str(order.get('status') or ''), **values}
    metadata = json.loads(json.dumps(metadata, default=str))
    return ExternalIncome(
        source_id=settings.get('id',0), source_name=settings.get('name',''),
        external_id=str(order['id']), date=_date(order.get('date_paid')),
        customer_name=_customer(order)['name'],
        description=f"Objednávka {order.get('number') or order['id']}",
        amount=values['payment_received_czk'] if values['payment_received_czk'] is not None else values['invoice_amount_czk'],
        document=IncomeDocument(str(order['id']),source_reference=str(order['id'])),
        source_metadata=metadata,
        **{key: values[key] for key in ('invoice_amount_czk', 'payment_received_czk', 'payment_currency', 'fx_settlement_diff_czk', 'payment_needs_review')})

def _existing_import(source_ref):
    settings=source_settings()
    if settings.get('id'):
        doc=query("SELECT d.* FROM documents d JOIN income_source_records r ON r.document_id=d.id WHERE r.source_id=%s AND r.external_id=%s",
                  (settings['id'],source_ref.split(':')[-1]),one=True)
        if doc: return doc
    # Backward compatibility for legacy records not yet linked after an interrupted import.
    return query("SELECT * FROM documents WHERE source='woocommerce' AND source_ref=%s LIMIT 1",(source_ref,),one=True)

def sync_orders(orders, dry_run=False):
    """Synchronize supplied order dictionaries. dry_run performs classification only and never writes."""
    with invoice_sftp_session():
        return _sync_orders(orders, dry_run)


def _sync_orders(orders, dry_run=False):
    if not source_settings().get('id'):
        raise SyncConfigurationError('Synchronizace běží jen pro nastavený zdroj příjmů.')
    cutoff = sync_from_date() or date.min
    summary = {'seen': len(orders), 'imported': 0, 'updated': 0, 'cancelled': 0, 'skipped': 0, 'warnings': [], 'pdf_added': 0, 'pdf_missing': 0, 'pdf_errors': 0, 'pdf_missing_orders': []}
    orders_by_id = {str(order.get('id')): order for order in orders if order.get('id')}
    invoice_attempted = set()
    for order in orders:
        if order.get('currency','CZK') != 'CZK':
            summary['skipped']+=1
            summary['warnings'].append(f"Objednávka {order.get('id')}: měna není CZK; vyžaduje ruční převod.")
            continue
        source_ref = f"source:{source_settings()['id']}:order:{order.get('id')}"
        status = str(order.get('status') or '').lower()
        if status == 'trash':
            summary['skipped'] += 1
            continue
        paid = _date(order.get('date_paid'))
        # A cancellation may omit date_paid; use only an already imported date.
        if not paid and not dry_run and (status=='cancelled' or _fully_refunded(order)):
            old_import=_existing_import(source_ref)
            if old_import:paid=str(old_import['issue_date'])
        if not paid or date.fromisoformat(paid) < cutoff:
            summary['skipped'] += 1
            continue
        existing_doc = _existing_import(source_ref) if not dry_run else None
        # A cancelled order may no longer expose date_paid; an already imported
        # document must still be soft-cancelled in that case.
        if dry_run and status == 'cancelled':
            summary['cancelled'] += 1
            continue
        if not dry_run and status == 'cancelled' and existing_doc:
            _cancel_import(existing_doc)
            summary['cancelled'] += 1
            continue
        if dry_run:
            summary['cancelled' if status == 'cancelled' or _fully_refunded(order) else 'imported'] += 1
            if _partial_refund(order): summary['warnings'].append(f"Objednávka {order.get('id')}: částečný refund k ruční kontrole")
            continue
        doc = existing_doc or _existing_import(source_ref)
        if status == 'cancelled' or _fully_refunded(order):
            if doc:
                _cancel_import(doc); summary['cancelled'] += 1
            continue
        counterparty_id = _upsert_counterparty(order, doc['counterparty_id'] if doc else None)
        normalized = normalize_income(order)
        total = normalized.invoice_amount_czk
        items = order.get('line_items') or []
        order_date = paid or _date(order.get('date_created')) or cas.today().isoformat()
        if doc:
            old = query('SELECT * FROM documents WHERE id=%s', (doc['id'],), one=True)
            execute("UPDATE documents SET number=%s,counterparty_id=%s,issue_date=%s,taxable_date=%s,gross_total=%s,note=%s,deleted_at=NULL WHERE id=%s", (str(order.get('number') or order.get('id')), counterparty_id, order_date, order_date, total, f"woo_status:{status}; WooCommerce objednávka {order.get('id')}", doc['id']))
            new = query('SELECT * FROM documents WHERE id=%s', (doc['id'],), one=True)
            if old != new: _audit('document', doc['id'], 'update', old, new)
            document_id = doc['id']; summary['updated'] += 1
        else:
            document_id = execute("INSERT INTO documents (document_type,number,counterparty_id,issue_date,taxable_date,gross_total,source,source_ref,note) VALUES ('issued_invoice',%s,%s,%s,%s,%s,'woocommerce',%s,%s)", (str(order.get('number') or order.get('id')), counterparty_id, order_date, order_date, total, source_ref, f"woo_status:{status}; WooCommerce objednávka {order.get('id')}"))
            _audit('document', document_id, 'insert', new=query('SELECT * FROM documents WHERE id=%s', (document_id,), one=True)); summary['imported'] += 1
        _sync_items(document_id, order)
        payment = query("SELECT * FROM payments WHERE document_id=%s AND direction='income' ORDER BY id LIMIT 1", (document_id,), one=True)
        from .payment_settlement import preserve_verified
        values = preserve_verified({key: getattr(normalized, key) for key in (
            'invoice_amount_czk', 'payment_received_czk', 'payment_currency', 'fx_settlement_diff_czk', 'payment_needs_review')}, payment)
        cash_amount = values['payment_received_czk'] if values['payment_received_czk'] is not None else total
        payment_args = (document_id, counterparty_id, order_date, 'income', 'other', cash_amount, normalized.description, None)
        settlement_args = tuple(values[key] for key in ('invoice_amount_czk', 'payment_received_czk', 'payment_currency', 'fx_settlement_diff_czk', 'payment_needs_review'))
        if values['payment_needs_review']:
            summary['warnings'].append(f"Objednávka {order['id']}: připsaná částka / měna vyžaduje ověření; bez odhadu kurzu.")
        if payment:
            old = payment
            execute('UPDATE payments SET document_id=%s,counterparty_id=%s,payment_date=%s,direction=%s,method=%s,amount=%s,description=%s,note=%s,invoice_amount_czk=%s,payment_received_czk=%s,payment_currency=%s,fx_settlement_diff_czk=%s,payment_needs_review=%s,deleted_at=NULL WHERE id=%s', payment_args + settlement_args + (payment['id'],))
            new = query('SELECT * FROM payments WHERE id=%s', (payment['id'],), one=True)
            if old != new: _audit('payment', payment['id'], 'update', old, new)
        else:
            payment_id = execute("INSERT INTO payments (system_type,document_id,counterparty_id,payment_date,direction,method,amount,description,note,invoice_amount_czk,payment_received_czk,payment_currency,fx_settlement_diff_czk,payment_needs_review) VALUES ('income_connector',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", payment_args + settlement_args)
            _audit('payment', payment_id, 'insert', new=query('SELECT * FROM payments WHERE id=%s', (payment_id,), one=True))
        settings=source_settings()
        if settings.get('id'):
            from .income_sources import link_document
            metadata = {**normalized.source_metadata, **json.loads(json.dumps(values, default=str)),
                        'order_number': str(order.get('number') or order['id'])}
            if payment and normalized.payment_received_czk is None and payment.get('payment_received_czk') is not None:
                prior = query('SELECT source_metadata FROM income_source_records WHERE source_id=%s AND external_id=%s', (settings['id'], str(order['id'])), one=True)
                if prior:
                    previous_metadata = json.loads(prior['source_metadata']) if isinstance(prior['source_metadata'], str) else prior['source_metadata'] or {}
                    metadata['settlement_evidence'] = previous_metadata.get('settlement_evidence')
            link_document(settings['id'],order['id'],document_id,metadata)
        result = _sync_invoice_for_document(document_id, order) if import_documents() else 'disabled'
        invoice_attempted.add(document_id)
        if result == 'added': summary['pdf_added'] += 1
        elif result == 'error': summary['pdf_errors'] += 1
        if _partial_refund(order): summary['warnings'].append(f"Objednávka {order.get('id')}: částečný refund k ruční kontrole")
    if not dry_run and import_documents():
        missing_docs = source_documents()
        for doc in missing_docs:
            if doc['id'] in invoice_attempted or _document_has_invoice(doc['id']):
                continue
            order_id = str(doc['external_id'])
            result = _sync_invoice_for_document(doc['id'], orders_by_id.get(order_id) or {})
            if result == 'added': summary['pdf_added'] += 1
            elif result == 'error': summary['pdf_errors'] += 1
        still_missing=source_documents()
        summary['pdf_missing_orders']=[str(row['number']) for row in still_missing if not _document_has_invoice(row['id'])]
        summary['pdf_missing']=len(summary['pdf_missing_orders'])
        if summary['pdf_errors']:
            summary['warnings'].append(f"Nepodařilo se stáhnout {summary['pdf_errors']} dokladů. Příští synchronizace pokus zopakuje.")
    return summary


def _refund_total(order):
    return sum((_money(abs(_money(r.get('total')))) for r in (order.get('refunds') or [])), Decimal('0.00'))


def _fully_refunded(order):
    total = _money(order.get('total'))
    return total > 0 and _refund_total(order) >= total


def _partial_refund(order):
    refunded = _refund_total(order); total = _money(order.get('total'))
    return refunded > 0 and refunded < total


# Stav synchronizace je u zdroje (income_sources.last_sync).
