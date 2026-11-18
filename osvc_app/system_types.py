"""Stable record identities; labels never participate in accounting decisions."""
from .db import query
# druhý údaj říká, CO typ znamená a KDE se jeho název zobrazuje (ukazuje se v Nastavení → Názvy typů).
TYPES={
 'income':('Ruční příjem','Příjem zadaný ručně · Přehled, sloupec Zdroj v Příjmech a detail akce'),
 'expense':('Nákup','Výdaj zadaný ručně · Přehled, sloupec Zdroj ve Výdajích a detail akce'),
 'trip':('Doprava','Jízda z knihy jízd · Přehled'),
 'fuel':('PHM','Tankování · Přehled, sloupec Zdroj ve Výdajích, detail akce a výběr PHM dokladu u jízdy (když chybí stanice)'),
 'income_connector':('Příjem z e-shopu','Příjem stažený ze zdroje příjmů (objednávky z e-shopu) · na Přehledu se místo něj ukazuje název zdroje (např. adresa e-shopu); tento název jen když zdroj chybí, a v detailu akce'),
 'system_adjustment':('Korekce','Vyhrazeno pro systémové korekce · zatím se nikde nezobrazuje'),
}
def labels():
 overrides={r['type_key']:r['display_label'] for r in query('SELECT type_key,display_label FROM system_types')}
 return {key:overrides.get(key,value[0]) for key,value in TYPES.items()}
def entries():
 names=labels()
 return [{'key':key,'label':names[key],'description':value[1],'default':value[0]} for key,value in TYPES.items()]
def payment_kind(row):
 # Relation-based fallback supports old rows and pre-migration fixtures, never category names.
 if row.get('fuel_purchase_id'):return 'fuel'
 if row.get('system_type'):return row['system_type']
 return 'income_connector' if row.get('income_source_id') else row['direction']
