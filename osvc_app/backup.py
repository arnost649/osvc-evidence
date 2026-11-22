"""Self-contained user-data ZIPs. No SQL from an archive is ever executed."""
import base64, hashlib, json, os, re, shutil, stat, tempfile, uuid, zipfile
from . import zamky
from contextlib import contextmanager
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path, PurePosixPath
from flask import current_app
from .db import connection, engine

# Formát 2 (2026-11-17, přechod na SQLite): struktura jen jako seznam sloupců (nezávisle na databázi), v manifestu navíc součty peněz
# po letech a hodnoty Ročního přehledu pro srovnávací tabulku po obnově. Formát 1 (ZIPy z MySQL) se dál přijímá.
FORMAT='osvc-user-data-2'
FORMATY={'osvc-user-data-1','osvc-user-data-2'}
APP_VERSION='osvc-local-data-1'
EXCLUDED_TABLES={'app_accounts'}
MAX_ZIP=512*1024*1024
MAX_EXPANDED=2*1024*1024*1024
class BackupError(ValueError):pass

def state_dir():
    p=Path(current_app.config.get('DATA_STATE_DIR',Path(current_app.root_path).parent/'instance'));p.mkdir(parents=True,exist_ok=True);return p

def settings_paths():
    from .themes import preference_path
    from .moduly import cesta as moduly_path
    return {'appearance.json':preference_path(),'woocommerce_sync.json':state_dir()/'woocommerce_sync.json','browser-drafts.json':state_dir()/'browser-drafts.json','insurers.json':state_dir()/'insurers.json','moduly.json':moduly_path()}

# Průběh vytvoření a obnovy zálohy pro ukazatel v Nastavení → Záloha: stav v state_dir/prubeh/<job>.json, čte ho
# GET /settings/backup/progress/<job> (bez zámku dat, aby šel číst i během výhradně zamčené obnovy).
JOB_RE=re.compile(r'[0-9a-f]{32}')
def progress_path(job):
    if not job or not JOB_RE.fullmatch(job):return None
    return state_dir()/'prubeh'/(job+'.json')

def reporter(job):
    """Vrátí funkci krok(krok, popis, procento) zapisující průběh; bez platného job nic nedělá."""
    path=progress_path(job)
    if not path:return lambda *a,**k:None
    path.parent.mkdir(mode=0o700,exist_ok=True)
    now=datetime.now(timezone.utc).timestamp()
    for old in path.parent.glob('*.json'):   # staré záznamy (> 1 h) pryč
        try:
            if now-old.stat().st_mtime>3600:old.unlink()
        except OSError:pass
    def krok(nazev,popis,procento):
        try:write_atomic(path,json.dumps({'krok':nazev,'popis':popis,'procento':max(0,min(100,int(procento)))},ensure_ascii=False).encode())
        except OSError:pass
    return krok

def read_progress(job):
    path=progress_path(job)
    if not path:return None
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return None

@contextmanager
def data_lock(exclusive=False):
    with (state_dir()/'.data.lock').open('ab') as f:
        zamky.zamkni(f,vyhradni=exclusive)
        try:yield
        finally:zamky.uvolni(f)

def write_atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.backup-')
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        zamky.nahrad(tmp,path)
        zamky.zapis_slozku(path.parent)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def encode(value):
    if isinstance(value,(datetime,date)):return value.isoformat(sep=' ') if isinstance(value,datetime) else value.isoformat()
    if isinstance(value,Decimal):return str(value)
    if isinstance(value,bytes):return {'$binary':base64.b64encode(value).decode()}
    raise TypeError(type(value).__name__)

def json_bytes(value):return json.dumps(value,default=encode,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def digest(data):return hashlib.sha256(data).hexdigest()
def identifier(name):
    if not re.fullmatch(r'[A-Za-z0-9_]+',name):raise BackupError('Neplatný identifikátor databáze.')
    return '`'+name+'`'

def schema(cur):
    """Struktura databáze nezávisle na úložišti: {tabulka: {'columns': [...]}} (bez app_accounts)."""
    result={}
    if engine()=='sqlite':
        cur.execute("SELECT name,type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%%' ORDER BY name")
        objekty=[(r['name'],r['type']) for r in cur.fetchall()]
        for name,kind in objekty:
            if name in EXCLUDED_TABLES:continue
            if kind!='table':raise BackupError('Nepodporovaný typ databázového objektu: '+name)
            cur.execute('SELECT name FROM pragma_table_info(%s) ORDER BY cid',(name,));result[name]={'columns':[c['name'] for c in cur.fetchall()]}
        return result
    cur.execute('SHOW FULL TABLES');tables=cur.fetchall()
    for item in tables:
        name,kind=list(item.values())
        if name in EXCLUDED_TABLES:continue
        if kind!='BASE TABLE':raise BackupError('Nepodporovaný typ databázového objektu: '+name)
        cur.execute('SHOW COLUMNS FROM '+identifier(name));result[name]={'columns':[c['Field'] for c in cur.fetchall()]}
    return dict(sorted(result.items()))

def jen_sloupce(structure):
    """Struktura ze zálohy formátu 1 (MySQL, i s DDL) → jen sloupce."""
    return {k:{'columns':list(v['columns'])} for k,v in sorted(structure.items())}

def foreign_keys(cur):
    """Cizí klíče [{TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME}] v obou úložištích."""
    if engine()=='sqlite':
        out=[]
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%%'")
        for (t,) in [(r['name'],) for r in cur.fetchall()]:
            cur.execute('SELECT "from" c,"table" rt,"to" rc FROM pragma_foreign_key_list(%s)',(t,))
            out+=[{'TABLE_NAME':t,'COLUMN_NAME':r['c'],'REFERENCED_TABLE_NAME':r['rt'],'REFERENCED_COLUMN_NAME':r['rc']} for r in cur.fetchall()]
        return out
    cur.execute('SELECT TABLE_NAME,COLUMN_NAME,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL')
    return cur.fetchall()

def sequences(cur,structure):
    """Další id každé tabulky (jako MySQL AUTO_INCREMENT; None = tabulka bez automatického číslování)."""
    if engine()=='sqlite':
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%%AUTOINCREMENT%%'")
        auto={r['name'] for r in cur.fetchall()}
        cur.execute('SELECT name,seq FROM sqlite_sequence');seq={r['name']:r['seq'] for r in cur.fetchall()}
        return {t:(int(seq.get(t,0))+1 if t in auto else None) for t in structure}
    cur.execute('SET SESSION information_schema_stats_expiry=0')   # MySQL 8 jinak vrací hodnotu z mezipaměti
    cur.execute('SELECT TABLE_NAME,AUTO_INCREMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')
    return {r['TABLE_NAME']:r['AUTO_INCREMENT'] for r in cur.fetchall() if r['TABLE_NAME'] in structure}

SECRET=re.compile(r'password|secret|token|cookie|session|credential',re.I)
def clean_json(value):
    if isinstance(value,dict):return {k:clean_json(v) for k,v in value.items() if not SECRET.search(k)}
    if isinstance(value,list):return [clean_json(v) for v in value]
    return value

def drafts_value(value):
    if not isinstance(value,dict) or len(json_bytes(value))>2*1024*1024:raise BackupError('Neplatná rozepsaná data.')
    out={}
    for key,raw in value.items():
        if not re.fullmatch(r'osvc-draft:[A-Za-z0-9_-]{1,100}',key):raise BackupError('Neplatný klíč rozepsaného formuláře.')
        obj=json.loads(raw) if isinstance(raw,str) else raw
        if not isinstance(obj,dict):raise BackupError('Neplatný rozepsaný formulář.')
        out[key]=json.dumps(clean_json(obj),ensure_ascii=False)
    return out

def internal_file(rel):
    return rel.name=='.gitkeep' or bool(re.fullmatch(r'\.invoice-\d+\.lock',rel.name)) or rel.name.startswith('.invoice-') and rel.name.endswith('.pdf')

def inventory():
    root=Path(current_app.config['UPLOAD_FOLDER']);files=[]
    if not root.is_dir():raise BackupError('Úložiště dokumentů neexistuje.')
    for p in sorted(root.rglob('*')):
        rel=p.relative_to(root)
        if internal_file(rel):continue
        if p.is_symlink():raise BackupError('Úložiště obsahuje symbolický odkaz: '+str(rel))
        if p.is_file():files.append((rel.as_posix(),p))
    return files

def snapshot():
    conn=connection()
    try:
        with conn.cursor() as cur:
            if engine()=='sqlite':conn.begin_read()   # jeden konzistentní stav (WAL snímek)
            else:cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ');cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
            structure=schema(cur);tables={}
            seqs=sequences(cur,structure)
            for name,info in structure.items():
                cur.execute('SELECT * FROM '+identifier(name)+' ORDER BY '+identifier(info['columns'][0]));rows=cur.fetchall()
                if name=='audit_log':
                    rows=[r for r in rows if not re.search(r'account|auth|session|login',r.get('entity_type',''),re.I)]
                    for r in rows:
                        for key in ['old_data','new_data']:
                            if r.get(key):
                                obj=json.loads(r[key]);clean=clean_json(obj)
                                if obj!=clean:r[key]=json.dumps(clean,ensure_ascii=False)
                tables[name]=rows
        conn.rollback();return structure,{'tables':tables,'sequences':seqs}
    finally:conn.close()

def attachment_warnings(data,files):
    warnings=[];paths={f['path']:f for f in files}
    documents={r['id'] for r in data['tables'].get('documents',[])}
    for a in data['tables'].get('attachments',[]):
        key='files/uploads/'+a['stored_filename']
        if key not in paths:warnings.append({'kind':'missing_document','attachment_id':a['id'],'path':key})
        elif a.get('sha256') and paths[key]['sha256']!=a['sha256']:warnings.append({'kind':'document_hash_mismatch','attachment_id':a['id'],'path':key})
        if a['document_id'] not in documents:warnings.append({'kind':'missing_document_record','attachment_id':a['id']})
    return warnings

def record_counts(data):
    payments=data['tables']['payments']
    return {'income':sum(r['direction']=='income' and not r['deleted_at'] for r in payments),'expenses':sum(r['direction']=='expense' and not r['deleted_at'] for r in payments),'trips':sum(not r['deleted_at'] for r in data['tables']['trips']),'fuel':sum(not r['deleted_at'] for r in data['tables']['fuel_purchases']),'contacts':sum(not r['deleted_at'] for r in data['tables']['counterparties']),'documents':len(data['tables']['documents'])}

ROK_SLOUPEC={'payments':'payment_date','trips':'trip_date','fuel_purchases':'purchase_date','documents':'issue_date'}
PENIZE={'payments':'amount','trips':'travel_cost_total','fuel_purchases':'total_amount','documents':'gross_total'}
NAZVY={'payments':'Platby','trips':'Jízdy','fuel_purchases':'PHM','documents':'Doklady'}

def money_totals(tables):
    """Součty peněz (nezrušené záznamy) celkem a po letech – z dat zálohy (text) i z databáze (Decimal, date)."""
    out={}
    for t,col in PENIZE.items():
        for r in tables.get(t,[]):
            if r.get('deleted_at') or r.get(col) is None:continue
            castka=Decimal(str(r[col]));d=r.get(ROK_SLOUPEC[t]);rok=str(d)[:4] if d else '?'
            druh=NAZVY[t]+(' – příjmy' if t=='payments' and r.get('direction')=='income' else ' – výdaje' if t=='payments' else '')
            for k in (druh+' celkem',f'{druh} {rok}'):out[k]=str(Decimal(out.get(k,'0'))+castka)
    return dict(sorted(out.items()))

def comparison(m,data):
    """Řádky srovnávací tabulky po obnově: [(položka, v záloze, po obnově, OK/ROZDÍL)]."""
    from .db import query
    from .prevod import rocni_prehled
    tables={t:query('SELECT * FROM '+identifier(t)) for t in PENIZE}|{'counterparties':query('SELECT deleted_at FROM counterparties')}
    po={'counts':record_counts({'tables':{**data['tables'],**tables}}),'money':money_totals(tables)}
    pred={'counts':m['counts'],'money':money_totals(data['tables'])}
    roky=sorted(int(r) for r in (m.get('rocni') or {}))
    po_rocni={k:(str(v) if v is not None else None) for k,v in rocni_prehled(roky).items()} if roky else {}
    radky=[]
    popisky={'income':'Příjmy (počet)','expenses':'Výdaje (počet)','trips':'Jízdy (počet)','fuel':'PHM (počet)','contacts':'Kontakty (počet)','documents':'Doklady (počet)'}
    for k,label in popisky.items():radky.append((label,pred['counts'].get(k),po['counts'].get(k)))
    for k in sorted(set(pred['money'])|set(po['money'])):radky.append((k+' (Kč)',pred['money'].get(k),po['money'].get(k)))
    from .annual import LABELS,FORMS
    for y,vals in sorted((m.get('rocni') or {}).items()):
        for k,v in vals.items():
            sekce,pole=k.split('.',1)
            radky.append((f'Roční přehled {y} – {FORMS[sekce][0]}: {LABELS[pole][0]} (Kč)',v,po_rocni.get(f'{y} {k}')))
    def stejne(a,b):
        try:return Decimal(str(a))==Decimal(str(b)) if a is not None and b is not None else a==b
        except ArithmeticError:return a==b
    return [(a,b,c,'OK' if stejne(b,c) else 'ROZDÍL') for a,b,c in radky]

def export_comparison(m,data):
    """Řádky po vytvoření zálohy: [(položka, v aplikaci, v záloze, OK/ROZDÍL)] – záloha přečtená zpět ze ZIPu."""
    from .db import query
    tables={t:query('SELECT * FROM '+identifier(t)) for t in PENIZE}|{'counterparties':query('SELECT deleted_at FROM counterparties')}
    zive={'counts':record_counts({'tables':{**data['tables'],**tables}}),'money':money_totals(tables)}
    zaloha={'counts':record_counts(data),'money':money_totals(data['tables'])}
    popisky={'income':'Příjmy (počet)','expenses':'Výdaje (počet)','trips':'Jízdy (počet)','fuel':'PHM (počet)','contacts':'Kontakty (počet)','documents':'Doklady (počet)'}
    radky=[(label,zive['counts'].get(k),zaloha['counts'].get(k)) for k,label in popisky.items()]
    radky.append(('Soubory dokladů (počet)',len(list(inventory())),m['document_count']))
    for k in sorted(k for k in set(zive['money'])|set(zaloha['money']) if k.endswith(' celkem')):radky.append((k+' (Kč)',zive['money'].get(k),zaloha['money'].get(k)))
    def stejne(a,b):
        try:return Decimal(str(a))==Decimal(str(b)) if a is not None and b is not None else a==b
        except ArithmeticError:return a==b
    return [(a,b,c,'OK' if stejne(b,c) else 'ROZDÍL') for a,b,c in radky]

def create_backup(path,browser_drafts=None,krok=None):
    krok=krok or (lambda *a:None)
    krok('databaze','Připravuji data…',5)
    structure,data=snapshot();entries=[];warnings=[]
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        def add(name,payload,kind):
            z.writestr(name,payload);entries.append({'path':name,'size':len(payload),'sha256':digest(payload),'type':kind})
        add('database/schema.json',json_bytes(structure),'database_schema')
        add('database/data.json',json_bytes(data),'database_data')
        soubory=list(inventory())
        for i,(rel,file) in enumerate(soubory,1):
            krok('doklady',f'Přidávám doklady… ({i} z {len(soubory)})',20+50*i/max(1,len(soubory)))
            try:
                h=hashlib.sha256();size=0
                with file.open('rb') as source,z.open('files/uploads/'+rel,'w',force_zip64=True) as target:
                    while chunk:=source.read(1024*1024):target.write(chunk);h.update(chunk);size+=len(chunk)
                entries.append({'path':'files/uploads/'+rel,'size':size,'sha256':h.hexdigest(),'type':'document'})
            except OSError as exc:raise BackupError('Dokument není čitelný: '+rel) from exc
        from .insurers import directory
        if not (state_dir()/'insurers.json').exists():write_atomic(state_dir()/'insurers.json',json_bytes(directory()))
        for name,file in settings_paths().items():
            if name=='browser-drafts.json' and browser_drafts is not None:add('settings/'+name,json_bytes(drafts_value(browser_drafts)),'browser_drafts')
            elif file.exists():
                payload=file.read_bytes();json.loads(payload);add('settings/'+name,payload,'settings')
        warnings+=attachment_warnings(data,entries)
        known={'files/uploads/'+a['stored_filename'] for a in data['tables']['attachments']}
        orphans=[f['path'] for f in entries if f['type']=='document' and f['path'] not in known]
        payments=data['tables']['payments']
        from .prevod import rocni_prehled
        roky=sorted({int(str(r['payment_date'])[:4]) for r in data['tables']['payments'] if r.get('payment_date')})
        rocni={}
        for k,v in rocni_prehled(roky).items():
            y,pole=k.split(' ',1);rocni.setdefault(y,{})[pole]=str(v) if v is not None else None
        manifest={'backup_format':FORMAT,'money':money_totals(data['tables']),'rocni':rocni,'created_at':datetime.now(timezone.utc).isoformat(),'app_version':APP_VERSION,'schema_version':digest(json_bytes(structure)),'table_counts':{k:len(v) for k,v in data['tables'].items()},'counts':record_counts(data),'document_count':sum(f['type']=='document' for f in entries),'document_bytes':sum(f['size'] for f in entries if f['type']=='document'),'files':entries,'warnings':warnings,'orphan_files':orphans,'excluded':['app_accounts','authentication audit data','credentials','session/cookies','code/cache/logs','historical SQL snapshots']}
        z.writestr('manifest.json',json_bytes(manifest))
    os.chmod(path,0o600)
    zamky.zapis_soubor(path)
    zamky.zapis_slozku(Path(path).parent)
    return manifest

def safe_path(name):
    p=PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and str(p)==name

def validate_backup(path):
    try:
        with zipfile.ZipFile(path) as z:
            infos=z.infolist();names=[i.filename for i in infos]
            if len(infos)>100000 or len(set(names))!=len(names) or sum(i.file_size for i in infos)>MAX_EXPANDED:raise BackupError('Neplatná velikost nebo duplicitní soubory ZIPu.')
            if any(not safe_path(i.filename) or stat.S_ISLNK(i.external_attr>>16) or i.flag_bits&1 for i in infos):raise BackupError('Neplatná cesta nebo nepodporovaný obsah ZIPu.')
            if z.getinfo('manifest.json').file_size>16*1024*1024:raise BackupError('Příliš velký manifest.')
            m=json.loads(z.read('manifest.json'))
            if m['backup_format'] not in FORMATY or m['app_version']!=APP_VERSION:raise BackupError('Nepodporovaná verze zálohy.')
            index={f['path']:f for f in m['files']}
            if len(index)!=len(m['files']) or set(names)!=set(index)|{'manifest.json'}:raise BackupError('Obsah ZIPu neodpovídá manifestu.')
            for name,item in index.items():
                if name.startswith('files/uploads/') and internal_file(PurePosixPath(name)):raise BackupError('ZIP obsahuje interní dočasný soubor.')
                if not (name in ['database/schema.json','database/data.json'] or name.startswith('files/uploads/') or name in ['settings/'+k for k in settings_paths()]):raise BackupError('Neočekávaný soubor v záloze.')
                h=hashlib.sha256();size=0
                with z.open(name) as f:
                    while chunk:=f.read(1024*1024):h.update(chunk);size+=len(chunk)
                if h.hexdigest()!=item['sha256'] or size!=item['size']:raise BackupError('Nesouhlasí kontrolní součet: '+name)
            if z.getinfo('database/data.json').file_size>128*1024*1024:raise BackupError('Databázová část překračuje podporovanou velikost.')
            puvodni=json.loads(z.read('database/schema.json'));data=json.loads(z.read('database/data.json'))
            if m['backup_format']=='osvc-user-data-2' and m['schema_version']!=digest(json_bytes(puvodni)):raise BackupError('Nesouhlasí popis struktury zálohy.')
            structure=jen_sloupce(puvodni)
            conn=connection()
            try:
                with conn.cursor() as cur:
                    current=schema(cur)
                    fks=foreign_keys(cur)
            finally:conn.close()
            # Accept exactly the additive system-types predecessor, never arbitrary DDL.
            if structure!=current:
                from copy import deepcopy
                from .system_types import TYPES
                predecessor=deepcopy(current);predecessor.pop('system_types',None)
                if 'system_type' in predecessor.get('payments',{}).get('columns',[]):
                    predecessor['payments']['columns'].remove('system_type')
                if structure!=predecessor:
                    raise BackupError('Tuto zálohu nejde obnovit: vznikla v jiné verzi aplikace (jiná struktura databáze). Obnovit ji jde jen ve stejné verzi aplikace.')
                # Validate original shapes/counts before extending the in-memory payload.
                if set(data['tables'])!=set(structure) or set(data['sequences'])!=set(structure):raise BackupError('Neúplná databáze.')
                for name,rows in data['tables'].items():
                    if len(rows)!=m['table_counts'][name] or any(set(row)!=set(structure[name]['columns']) for row in rows):raise BackupError('Neplatná původní struktura.')
                imported={row['document_id'] for row in data['tables']['income_source_records']}
                for row in data['tables']['payments']:
                    row['system_type']='fuel' if row['fuel_purchase_id'] else 'income_connector' if row['direction']=='income' and row['document_id'] in imported else row['direction']
                data['tables']['system_types']=[{'type_key':key,'display_label':value[0]} for key,value in TYPES.items()]
                data['sequences']['system_types']=None;m['table_counts']['system_types']=len(TYPES)
                structure=current
            if set(data['tables'])!=set(current) or set(data['sequences'])!=set(current):raise BackupError('Neúplná databáze.')
            for name,rows in data['tables'].items():
                if len(rows)!=m['table_counts'][name] or any(set(r)!=set(current[name]['columns']) for r in rows):raise BackupError('Neplatná struktura tabulky: '+name)
            for name,rows in data['tables'].items():
                value=data['sequences'][name]
                if value is not None and (type(value) is not int or value<1):raise BackupError('Neplatné číslování databáze.')
                if 'id' in current[name]['columns'] and len({r['id'] for r in rows})!=len(rows):raise BackupError('Duplicitní ID v databázi.')
            for fk in fks:
                if fk['TABLE_NAME'] not in data['tables']:continue
                parents={r[fk['REFERENCED_COLUMN_NAME']] for r in data['tables'][fk['REFERENCED_TABLE_NAME']]}
                if any(r[fk['COLUMN_NAME']] is not None and r[fk['COLUMN_NAME']] not in parents for r in data['tables'][fk['TABLE_NAME']]):raise BackupError('Neplatná databázová vazba.')
            if m['counts']!=record_counts(data):raise BackupError('Nesouhlasí počty záznamů.')
            if 'money' in m and m['money']!=money_totals(data['tables']):raise BackupError('Nesouhlasí součty částek v záloze.')
            docs=[item for name,item in index.items() if name.startswith('files/uploads/')]
            if len(docs)!=m['document_count'] or sum(i['size'] for i in docs)!=m['document_bytes']:raise BackupError('Nesouhlasí počet nebo velikost dokumentů.')
            for a in data['tables']['attachments']:
                if not safe_path(a['stored_filename']):raise BackupError('Neplatná cesta dokumentu v databázi.')
            if 'settings/appearance.json' in index:
                from .themes import THEME_IDS
                if json.loads(z.read('settings/appearance.json'))['theme'] not in THEME_IDS:raise BackupError('Neplatný motiv.')
            if 'settings/moduly.json' in index:
                from .moduly import platna_data
                platna_data(json.loads(z.read('settings/moduly.json')))
            if 'settings/browser-drafts.json' in index:drafts_value(json.loads(z.read('settings/browser-drafts.json')))
            for name in index:
                if name.startswith('settings/'):json.loads(z.read(name))
            actual=attachment_warnings(data,m['files'])
            if actual!=m['warnings']:raise BackupError('Nesouhlasí kontrola vazeb dokumentů.')
            return m,data
    except BackupError:raise
    except (ValueError,KeyError,TypeError,zipfile.BadZipFile,RuntimeError) as exc:raise BackupError('ZIP není platná kompletní záloha OSVČ.') from exc

def unpack_files(path,staging):
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.startswith(('files/uploads/','settings/')):
                target=Path(staging)/name;target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(name) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)

def install_files(staging,krok=None):
    krok=krok or (lambda *a:None)
    root=Path(current_app.config['UPLOAD_FOLDER']);source=Path(staging)/'files/uploads'
    wanted={p.relative_to(source).as_posix():p for p in source.rglob('*') if p.is_file()} if source.exists() else {}
    for rel,path in inventory():
        if rel not in wanted:path.unlink()
    for i,(rel,path) in enumerate(wanted.items(),1):
        krok('doklady',f'Obnovuji doklady… ({i} z {len(wanted)})',60+35*i/max(1,len(wanted)))
        write_atomic(root/rel,path.read_bytes())
    for name,dst in settings_paths().items():
        src=Path(staging)/'settings'/name
        if src.exists():write_atomic(dst,src.read_bytes())
        else:dst.unlink(missing_ok=True)
    # Persist deletions as well as replacements before committing the database.
    for directory in {root,*[p for p in root.rglob('*') if p.is_dir()],*[p.parent for p in settings_paths().values()]}:
        zamky.zapis_slozku(directory)

def write_database(conn,data):
    lite=engine()=='sqlite'
    with conn.cursor() as cur:
        cur.execute('PRAGMA defer_foreign_keys=ON' if lite else 'SET FOREIGN_KEY_CHECKS=0')   # SQLite: vazby se ověří při potvrzení
        for name in data['tables']:cur.execute('DELETE FROM '+identifier(name))
        for name,rows in data['tables'].items():
            if not rows:continue
            cols=list(rows[0]);values=[]
            for row in rows:values.append(tuple(base64.b64decode(row[c]['$binary'],validate=True) if isinstance(row[c],dict) and set(row[c])=={'$binary'} else row[c] for c in cols))
            cur.executemany('INSERT INTO '+identifier(name)+' ('+','.join(map(identifier,cols))+') VALUES ('+','.join(['%s']*len(cols))+')',values)
        for fk in foreign_keys(cur):
            if fk['TABLE_NAME'] not in data['tables']:continue
            table,col,parent,pk=map(identifier,[fk['TABLE_NAME'],fk['COLUMN_NAME'],fk['REFERENCED_TABLE_NAME'],fk['REFERENCED_COLUMN_NAME']])
            cur.execute(f'SELECT COUNT(*) n FROM {table} c LEFT JOIN {parent} p ON c.{col}=p.{pk} WHERE c.{col} IS NOT NULL AND p.{pk} IS NULL')
            if cur.fetchone()['n']:raise BackupError('Záloha obsahuje neplatnou databázovou vazbu.')
        if lite:   # čítače id v téže transakci (sqlite_sequence nemá jedinečný klíč → UPDATE, jinak INSERT)
            for name,value in data['sequences'].items():
                if value is None:continue
                if not isinstance(value,int) or value<1:raise BackupError('Neplatné číslování databáze.')
                cur.execute('UPDATE sqlite_sequence SET seq=%s WHERE name=%s',(value-1,name))
                if not cur.rowcount:cur.execute('INSERT INTO sqlite_sequence (name,seq) VALUES (%s,%s)',(name,value-1))
        else:cur.execute('SET FOREIGN_KEY_CHECKS=1')
        # Zdroje příjmů po obnově vypnuté, dokud je uživatel znovu neověří (přístupové údaje v záloze nejsou).
        cur.execute('UPDATE income_sources SET active=0 WHERE active<>0')

def set_sequences(data):
    if engine()=='sqlite':return   # SQLite: nastaveno v write_database (v téže transakci)
    conn=connection()
    try:
        with conn.cursor() as cur:
            for name,value in data['sequences'].items():
                if value is not None:
                    if not isinstance(value,int) or value<1:raise BackupError('Neplatné číslování databáze.')
                    cur.execute('ALTER TABLE '+identifier(name)+' AUTO_INCREMENT='+str(value))
    finally:conn.close()

def apply_data(path,data,krok=None):
    krok=krok or (lambda *a:None)
    with tempfile.TemporaryDirectory(prefix='osvc-restore-') as staging:
        unpack_files(path,staging)
        conn=connection()
        try:
            krok('databaze','Obnovuji databázi…',35)
            conn.begin();write_database(conn,data)
            krok('doklady','Obnovuji doklady…',60)
            install_files(staging,krok)
            hook=current_app.config.get('BACKUP_TEST_BEFORE_COMMIT')
            if hook:hook()
            conn.commit()
        except Exception:conn.rollback();raise
        finally:conn.close()
    set_sequences(data)

def recover_pending():
    journal=state_dir()/'restore-journal.json'
    if not journal.exists():return
    record=json.loads(journal.read_text(encoding='utf-8'));path=state_dir()/'backups'/record['snapshot']
    if not re.fullmatch(r'pre-restore-[A-Za-z0-9-]+\.zip',record['snapshot']):raise BackupError('Neplatný recovery snapshot.')
    m,data=validate_backup(path)
    # Test failure hooks never apply to the recovery operation.
    hook=current_app.config.pop('BACKUP_TEST_BEFORE_COMMIT',None)
    try:apply_data(path,data)
    finally:
        if hook:current_app.config['BACKUP_TEST_BEFORE_COMMIT']=hook
    journal.unlink()
    zamky.zapis_slozku(journal.parent)

def restore_backup(path,browser_drafts=None,krok=None):
    krok=krok or (lambda *a:None)
    krok('kontrola','Kontroluji zálohu…',5)
    m,data=validate_backup(path)
    krok('kontrola','Kontroluji… (ukládám pojistnou kopii současných dat)',15)
    folder=state_dir()/'backups';folder.mkdir(mode=0o700,exist_ok=True)
    snapshot_path=folder/('pre-restore-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex+'.zip')
    pre=create_backup(snapshot_path,browser_drafts)
    if pre['warnings']:
        current_app.logger.warning('Pre-restore snapshot: %s problémů dokumentů; původní stav je zaznamenán v manifestu.',len(pre['warnings']))
    validate_backup(snapshot_path)
    journal=state_dir()/'restore-journal.json'
    write_atomic(journal,json_bytes({'snapshot':snapshot_path.name}))
    zdroje=sum(1 for r in data['tables'].get('income_sources',[]) if r.get('active'))
    current_app.logger.info('obnova zálohy: začátek (záloha z %s)',m.get('created_at','?')[:19])
    try:apply_data(path,data,krok)
    except Exception:
        current_app.logger.exception('obnova zálohy selhala – vracím původní data')
        recover_pending();raise BackupError('Obnova selhala. Původní databáze, dokumenty a nastavení byly vráceny.')
    journal.unlink()
    krok('srovnani','Porovnávám data se zálohou…',97)
    m['srovnani']=comparison(m,data);m['zdroje_vypnuto']=zdroje
    current_app.logger.info('obnova zálohy: hotovo, %s položek srovnání, rozdílů %s',len(m['srovnani']),sum(r[3]!='OK' for r in m['srovnani']))
    write_atomic(state_dir()/'posledni-obnova.json',json_bytes({'radky':m['srovnani'],'zdroje_vypnuto':zdroje,'zaloha_z':m['created_at']}))
    zamky.zapis_slozku(journal.parent)
    return m,snapshot_path

def last_restore_result():
    """Výsledek poslední obnovy pro Nastavení → Záloha (ukáže se jednou, pak se soubor smaže)."""
    path=state_dir()/'posledni-obnova.json'
    try:
        value=json.loads(path.read_text(encoding='utf-8'));path.unlink(missing_ok=True)
        value['ok']=all(r[3]=='OK' for r in value['radky']);return value
    except (OSError,ValueError):return None

def init_gate(app):
    from flask import g, request, abort
    @app.before_request
    def acquire():
        if request.endpoint=='backup.progress':return   # jen čtení malého souboru průběhu – nesmí čekat na zámek obnovy
        if request.endpoint=='backup.validate':request.max_content_length=MAX_ZIP
        handle=(state_dir()/'.data.lock').open('ab');g.data_lock_handle=handle
        exclusive=request.endpoint in {'backup.export','backup.restore','annual.pdf'}
        zamky.zamkni(handle,vyhradni=exclusive)
        if (state_dir()/'restore-journal.json').exists():
            zamky.zamkni(handle,vyhradni=True)
            try:recover_pending()
            except Exception:
                app.logger.exception('Obnova konzistence dat selhala');abort(503)
            if not exclusive:zamky.zamkni(handle)
    @app.teardown_request
    def release(error):
        handle=g.pop('data_lock_handle',None)
        if handle:handle.close()


# stav automatických záloh serveru pro Nastavení → Záloha. Jen čtení přes `systemctl show`
# (bez root práv a bez čtení skriptů záloh); když stav nejde zjistit, stránka to řekne a nic jiného neovlivní.
SERVER_BACKUPS=(('osvc-backup','Noční záloha databáze','každou noc ve 3:15',timedelta(hours=30)),
                ('zaloha-osvc-data','Týdenní kopie dat na druhý počítač','každou neděli ve 21:45',timedelta(days=8)))

def _systemctl_show(unit,props):
    import subprocess
    out=subprocess.run(['systemctl','show',unit,'-p',','.join(props),'--timestamp=unix'],capture_output=True,text=True,timeout=3,check=True).stdout
    values=dict(line.split('=',1) for line in out.splitlines() if '=' in line)
    def stamp(value):
        try:return datetime.fromtimestamp(int(value.lstrip('@')),timezone.utc) if value and value.startswith('@') else None
        except ValueError:return None
    return {k:(stamp(v) if v.startswith('@') else v) for k,v in values.items()}

def server_backup_status():
    if current_app.config.get('OSVC_SAMOSTATNA'):   # Windows/Linux bez serveru: zálohy plánovače ve spouštěči (I4)
        from .zaloha_db import stav_samostatne
        return stav_samostatne()
    now=datetime.now(timezone.utc);result=[]
    for unit,label,schedule,max_age in SERVER_BACKUPS:
        item={'label':label,'schedule':schedule,'state':'unknown','at':None,'next':None}
        try:
            service=_systemctl_show(unit+'.service',('ActiveState','Result','ExecMainStatus','ExecMainExitTimestamp'))
            timer=_systemctl_show(unit+'.timer',('LastTriggerUSec','NextElapseUSecRealtime'))
        except Exception:
            item['state']='unavailable';result.append(item);continue
        item['next']=timer.get('NextElapseUSecRealtime') or None
        finished=service.get('ExecMainExitTimestamp')
        if service.get('ActiveState') in ('activating','active'):item['state']='running';item['at']=timer.get('LastTriggerUSec')
        elif isinstance(finished,datetime):
            item['at']=finished
            ok=service.get('Result')=='success' and service.get('ExecMainStatus')=='0'
            item['state']='old' if ok and now-finished>max_age else 'ok' if ok else 'error'
        elif isinstance(timer.get('LastTriggerUSec'),datetime):
            item['at']=timer['LastTriggerUSec'];item['state']='since_boot'   # běžela před restartem serveru, výsledek systemd nepamatuje
        result.append(item)
    return result
