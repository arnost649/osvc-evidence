from .year_periods import year_period_text
from .insurers import description as insurer_description
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,KeepTogether,PageBreak
from reportlab.lib.pagesizes import A4
from .annual import display
from .profile import IDENTITY,OPTIONS,MONTHS

def generate(report):
 font=Path(__file__).parent/'static/fonts'
 for name,file in [('OSVC','DejaVuSans.ttf'),('OSVC-Bold','DejaVuSans-Bold.ttf')]:
  if name not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont(name,str(font/file)))
 pdfmetrics.registerFontFamily('OSVC',normal='OSVC',bold='OSVC-Bold')
 styles=getSampleStyleSheet();styles.add(ParagraphStyle(name='BodyCZ',fontName='OSVC',fontSize=9,leading=13,spaceAfter=5));styles.add(ParagraphStyle(name='SmallCZ',parent=styles['BodyCZ'],fontSize=8,leading=11,textColor=colors.HexColor('#444444')));styles.add(ParagraphStyle(name='HeadingCZ',parent=styles['BodyCZ'],fontName='OSVC-Bold',fontSize=15,leading=19,spaceAfter=12))
 out=BytesIO();doc=SimpleDocTemplate(out,pagesize=A4,leftMargin=40,rightMargin=40,topMargin=38,bottomMargin=38,title=f'Podklady pro přiznání a přehledy {report["year"]}',author='OSVČ evidence');story=[]
 def text(s,style='BodyCZ'):return Paragraph(escape(str(s)).replace('\n','<br/>'),styles[style])
 story.extend([text('PODKLADY PRO PŘIZNÁNÍ A PŘEHLEDY','HeadingCZ'),text('Rok '+str(report['year']))])
 pending=any(s['missing'] or s['review'] for s in report['sections']) or report.get('profile_status',{}).get('state','known')!='known' or any(report['missing'].values())
 story.append(text('PRACOVNÍ PODKLAD – obsahuje chybějící údaje nebo položky vyžadující kontrolu.' if pending else 'Kontrolní podklady pro ruční přepis; nejde o úřední formulář.'))
 story.append(text('IDENTIFIKACE OSVČ','HeadingCZ'))
 for k,label in IDENTITY.items():story.append(text(label+': '+(report['identity'].get(k) or '—')))
 p=report['profile']
 if p.get('profile_version')==2:
  story.append(text('Platnost podnikání v roce '+str(report['year'])+': '+(year_period_text(report['year'],p.get('business_periods') or [{}]) if p.get('business_status')=='yes' else 'Celý rok bez činnosti' if p.get('business_status')=='no' else 'Nepotvrzeno')))
  story.append(text('Platnost zaměstnání v roce '+str(report['year'])+': '+(year_period_text(report['year'],p.get('employment_periods') or [{}]) if p.get('employment_status')=='yes' else 'Bez zaměstnání / nepotvrzeno')))
  if p.get('overrides_enabled'):story.append(text('Použity ruční měsíční korekce.','SmallCZ'))
 else:story.append(text('Období podnikání: '+(p.get('start') or 'dle měsíců')+' – '+(p.get('end') or 'dle měsíců')))
 for m in p['months']:
  story.append(text(f"{MONTHS[m['month']-1]}: aktivita {OPTIONS['activity'].get(m.get('activity'),'chybí')}; zaměstnání {OPTIONS['employment'].get(m.get('employment'),'chybí')}; ČSSZ {OPTIONS['social'].get(m.get('social'),'—')}; zdravotní minimum {OPTIONS['minimum'].get(m.get('minimum'),'—')}",'SmallCZ'))
 story.append(text('Zdravotní pojišťovna: '+insurer_description(p)))
 story.append(text('Daňové výdaje: '+OPTIONS['expense_method'].get(p.get('expense_method'),'chybí')))
 for v in report['vehicles']:story.append(text('Doprava – '+v['name']+': '+v['method']))
 for key,items in report['missing'].items():
  if items:story.append(text(('Vyřešit daňové podklady (Profil OSVČ / editace výdajů): ' if key=='tax' else 'Doplnit v Profilu OSVČ: ')+', '.join(items),'SmallCZ'))
 if report.get('nezapocteno'):story.append(text('Nezapočteno (vypnutý modul): '+report['nezapocteno']+'.','SmallCZ'))
 for warning in report['reviews']:story.append(text('Kontrola: '+warning,'SmallCZ'))
 for s in report['sections']:
  story.extend([PageBreak(),text(s['title'],'HeadingCZ'),text('Oficiální formulář: '+s['form'])])
  if s['key']=='tax' and report.get('expense_summary'):
   e=report['expense_summary']
   for label,key in [('Evidované výdaje celkem','recorded'),('Běžné nákupy','ordinary_total'),('Jízdy','travel'),('Potvrzené podle zvoleného režimu dopravy','confirmed'),('Neuznatelné části nákupů','excluded'),('Čeká na posouzení','pending')]:story.append(text(label+': '+display({'value':e[key],'unit':'Kč'})))
   if e['pending_count']:story.append(text(str(e['pending_count'])+' výdajů čeká na posouzení ve Výdaje → Chybí posouzení.','SmallCZ'))
  for f in s['fields']:
   status={'known':'Vypočteno / známé','missing':'Chybí údaj','review':'Vyžaduje kontrolu','info':'Jen pro informaci'}[f['status']]
   story.append(KeepTogether([text(f['label']+': '+display(f)),text('Stav: '+status,'SmallCZ'),text('Kam patří: '+f['destination'],'SmallCZ'),text('Co to je / zdroj: '+f['tooltip'].split(' Kam patří:')[0],'SmallCZ'),text(f['note'],'SmallCZ'),Spacer(1,8)]))
 story.extend([Spacer(1,12),text('Použitá pravidla: '+(report['rules']['id'] if report['rules'] else 'Pro tento rok neověřena'),'SmallCZ'),text('Čísla řádků nebyla potvrzena pro tento rok; používáme významové názvy. Nové zálohy ověřte podle pravidel následujícího roku.','SmallCZ')])
 for url in (report['rules'] or {}).get('sources',[]):story.append(text(url,'SmallCZ'))
 def footer(canvas,doc):canvas.setFont('OSVC',8);canvas.drawRightString(A4[0]-40,22,f'OSVČ · {report["year"]} · {doc.page}')
 doc.build(story,onFirstPage=footer,onLaterPages=footer);out.seek(0);return out
