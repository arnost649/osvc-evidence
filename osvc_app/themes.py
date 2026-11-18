"""Semantic palettes and the local application's persisted appearance preference."""
import json
import os
import tempfile
from . import zamky
from pathlib import Path
from flask import current_app

PALETTES = [
 ('cisty','ČISTÝ','F6F7F9 FFFFFF F0F2F5 D8DEE7 1D2733 667085 2563EB 1D4ED8 475569'),
 ('modry','MODRÝ','F3F7FB FFFFFF EAF1F8 CBD8E6 172B3A 607689 1769AA 12568D 3C8DBC'),
 ('tyrkysovy','TYRKYSOVÝ','F2F8F7 FFFFFF E5F1EF C5DCD8 19332F 607873 0F766E 0B5F59 14A394'),
 ('lesni','LESNÍ','F4F7F3 FFFFFF E9F0E7 CFDCCB 223126 657368 397052 2D5B42 6C8E67'),
 ('olivovy','OLIVOVÝ','F7F7F1 FFFFFF EEEEE4 D8D8C6 292C22 717366 65743A 505D2F 89945C'),
 ('piskovy','PÍSKOVÝ','F8F5EF FFFDFC EFE8DC DDD2C2 302B25 786F65 A65D2B 884B23 8A7158'),
 ('vinovy','VÍNOVÝ','F9F5F6 FFFFFF F1E7EA DFCBCD 332326 756468 8E2943 732137 AA5368'),
 ('indigo','INDIGO','F5F5FA FFFFFF EBEAF5 D4D2E6 25243A 6B6980 4F46A5 40388A 7068C4'),
 ('nordic','SEVERSKÝ','F3F6F8 FFFFFF E7EDF1 CBD5DC 263642 657985 3A6D8C 305B75 63889F'),
 ('grafit','GRAFIT','171A1F 20242B 272C34 3A414C F1F3F5 AAB1BA 4C8DFF 6A9FFF 778392'),
 ('nocni-modra','NOČNÍ MODRÁ','111821 18222E 202D3B 344557 F0F4F8 A2B1BF 4DA3E8 70B6ED 54819E'),
 ('temny-tyrkys','TEMNÝ TYRKYS','121B1B 192626 203130 38504E EFF7F6 A5B8B6 35B5A6 51C5B7 57958D'),
 # Tmavé podle nejrozšířenějších otevřených barevných schémat (editory, terminály, aplikace); barvy z jejich palet,
 # pozadí seřazená od nejtmavšího (stránka → karta → zvýraznění); 4. položka = vlastní barvy stavů schématu (úspěch, upozornění,
 # chyba, informace). Kontrast textu, odkazů i stavů dorovná build_theme (WCAG 4.5:1).
 ('cerny','ČERNÝ','000000 0E0E10 18181B 2E2E33 F4F4F5 A1A1AA 4C9AFF 6EADFF 8B8B94'),
 ('one-dark','ONE DARK','21252B 282C34 2C313A 3E4451 DCDFE4 9DA5B4 61AFEF 82C0F3 C678DD','98C379 E5C07B E06C75 61AFEF'),
 ('dracula','DRACULA','21222C 282A36 343746 44475A F8F8F2 A4A9C9 BD93F9 CBA6FA FF79C6','50FA7B F1FA8C FF5555 8BE9FD'),
 ('nord','NORD','2E3440 3B4252 434C5E 4C566A ECEFF4 B6C0CF 88C0D0 A3D3DF 81A1C1','A3BE8C EBCB8B BF616A 81A1C1'),
 ('tokyo-night','TOKYO NIGHT','1A1B26 1F2335 292E42 3B4261 C0CAF5 9AA5CE 7AA2F7 8FB3F9 BB9AF7','9ECE6A E0AF68 F7768E 7DCFFF'),
 ('catppuccin','CATPPUCCIN','181825 1E1E2E 313244 45475A CDD6F4 A6ADC8 CBA6F7 DDC4FA F5C2E7','A6E3A1 F9E2AF F38BA8 89DCEB'),
 ('gruvbox','GRUVBOX','1D2021 282828 32302F 504945 EBDBB2 BDAE93 FABD2F FCCB57 8EC07C','B8BB26 FABD2F FB4934 83A598'),
 ('solarized','SOLARIZED','002B36 073642 0A404E 2A5A66 EEE8D5 93A1A1 268BD2 7DB9E5 2AA198','859900 B58900 DC322F 268BD2'),
 ('rose-pine','ROSÉ PINE','191724 1F1D2E 26233A 403D52 E0DEF4 908CAA C4A7E7 D3BDEE EBBCBA','9CCFD8 F6C177 EB6F92 C4A7E7'),
 ('monokai','MONOKAI','1E1F1C 272822 31322C 49483E F8F8F2 A59F85 A6E22E B8E85A F92672','A6E22E E6DB74 F92672 66D9EF'),
]
def rgb(value): return tuple(int(value[i:i+2],16)/255 for i in (1,3,5))
def luminance(value):
 return sum(w*(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4) for w,v in zip((.2126,.7152,.0722),rgb(value)))
def contrast(a,b):
 x,y=sorted((luminance(a),luminance(b)))
 return (y+.05)/(x+.05)
def mix(a,b,amount):
 return '#'+''.join(f'{round((x*(1-amount)+y*amount)*255):02X}' for x,y in zip(rgb(a),rgb(b)))
def accessible(color, backgrounds, minimum, dark):
 for step in range(101):
  candidate=mix(color,'#FFFFFF' if dark else '#000000',step/100)
  if min(contrast(candidate,b) for b in backgrounds)>=minimum: return candidate
 raise ValueError('No accessible color')
def build_theme(key,name,values,status=None):
 t=dict(zip(('bg','surface','surface-alt','border','text','muted','primary','primary-hover','accent'),('#'+v for v in values.split())))
 dark=luminance(t['bg'])<.1
 backgrounds=[t[k] for k in ('bg','surface','surface-alt')]
 for k in ('muted','primary','primary-hover'):
  t[k]=accessible(t[k],backgrounds,4.5,dark)
 t['primary-text']='#111821' if dark else '#FFFFFF'
 t['input-border']=accessible(t['border'],backgrounds,3,dark)
 t.update({'secondary':t['surface-alt'],'secondary-text':t['text'],'text-muted':t['muted'],'input-bg':t['surface'],'table-header':t['surface-alt'],'table-row-hover':t['surface-alt'],'sidebar':t['surface-alt'],'sidebar-active':t['primary'],'primary-active':t['primary-hover'],'focus':t['primary'],'on-header':t['text'],'header':t['surface'],'overlay':'rgba(0,0,0,.65)','shadow':'rgba(0,0,0,.18)'})
 for role,value in zip(('success','warning','danger','info'),(status or ('4ADE80 FBBF24 F87171 60A5FA' if dark else '15803D B45309 B91C1C 0369A1')).split()):
  bg=mix(t['surface'],'#'+value,.09)
  t[role+'-bg']=bg
  t[role]=accessible('#'+value,backgrounds+[bg],4.5,dark)
 return {'id':key,'name':name,'dark':dark,'tokens':t}
THEMES=[build_theme(*p) for p in PALETTES]
THEME_GROUPS=[('Světlé',[x for x in THEMES if not x['dark']]),('Tmavé',[x for x in THEMES if x['dark']])]
THEME_IDS={t['id'] for t in THEMES}
def preference_path():
 return Path(current_app.config.get('THEME_SETTINGS_FILE',Path(current_app.root_path).parent/'instance'/'appearance.json'))
def saved_theme():
 try:
  value=json.loads(preference_path().read_text(encoding='utf-8')).get('theme')
  return value if value in THEME_IDS else 'cisty'
 except (OSError,ValueError,AttributeError,TypeError): return 'cisty'
def save_theme(value):
 path=preference_path(); path.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(prefix='.appearance-',dir=path.parent)
 try:
  os.fchmod(fd,0o644)  # This file contains only the non-secret shared theme identifier.
  with os.fdopen(fd, 'w', encoding='utf-8') as out:
   json.dump({'theme':value},out); out.flush(); os.fsync(out.fileno())
  zamky.nahrad(name,path)
 finally:
  if os.path.exists(name): os.unlink(name)
