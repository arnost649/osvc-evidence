"""PDF „Podklady pro přiznání a přehledy“ (1.0.3): podklad k opsání do formulářů na jednu stranu A4.
Obsah sestaví annual_podklad.podklad – stejný jako na stránce Roční přehled."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from . import cas
from .annual_podklad import podklad

SEDA, LINKA, ZVYRAZNENI = colors.HexColor('#555555'), colors.HexColor('#C9CED6'), colors.HexColor('#F1F3F6')
OKRAJ = 42


def _pisma():
    slozka = Path(__file__).parent / 'static/fonts'
    for name, soubor in (('OSVC', 'DejaVuSans.ttf'), ('OSVC-Bold', 'DejaVuSans-Bold.ttf')):
        if name not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont(name, str(slozka / soubor)))
    pdfmetrics.registerFontFamily('OSVC', normal='OSVC', bold='OSVC-Bold')


def generate(report):
    _pisma()
    data = podklad(report)
    s = {'nadpis': ParagraphStyle('nadpis', fontName='OSVC-Bold', fontSize=14, leading=18, spaceAfter=2),
         'pod': ParagraphStyle('pod', fontName='OSVC', fontSize=8, leading=10, textColor=SEDA, spaceAfter=8),
         'bunka': ParagraphStyle('bunka', fontName='OSVC', fontSize=9, leading=11.5),
         'hodnota': ParagraphStyle('hodnota', fontName='OSVC-Bold', fontSize=9, leading=11.5, alignment=2),
         'chybi': ParagraphStyle('chybi', fontName='OSVC-Bold', fontSize=9, leading=11.5, alignment=2, textColor=colors.HexColor('#B42318')),
         'info': ParagraphStyle('info', fontName='OSVC', fontSize=8, leading=11.5, alignment=2, textColor=SEDA),
         'urad': ParagraphStyle('urad', fontName='OSVC-Bold', fontSize=10.5, leading=13),
         'formular': ParagraphStyle('formular', fontName='OSVC', fontSize=8, leading=10, textColor=SEDA),
         'pozor': ParagraphStyle('pozor', fontName='OSVC-Bold', fontSize=9, leading=12, textColor=colors.HexColor('#8A4B00')),
         'paticka': ParagraphStyle('paticka', fontName='OSVC', fontSize=7.5, leading=9.5, textColor=SEDA)}
    t = lambda text, styl: Paragraph(escape(str(text)), s[styl])
    sirka = A4[0] - 2 * OKRAJ - 12   # rámec stránky má vnitřní okraj 6 pt na každé straně
    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=OKRAJ, rightMargin=OKRAJ, topMargin=36, bottomMargin=36,
                            title=f'Podklady pro přiznání a přehledy {data["rok"]}', author='OSVČ evidence')
    story = [t(f'Podklady pro přiznání a přehledy {data["rok"]}', 'nadpis'),
             t('Hodnoty k opsání do formulářů. Nejde o úřední formulář.', 'pod')]
    # hlavička: dvojice „popis | hodnota“ ve dvou sloupcích
    hl = [(t(k, 'formular'), t(v or '—', 'bunka')) for k, v in data['hlavicka']]
    radky = [[*hl[i], *(hl[i + 1] if i + 1 < len(hl) else ('', ''))] for i in range(0, len(hl), 2)]
    hlavicka = Table(radky, colWidths=[sirka * 0.15, sirka * 0.35, sirka * 0.17, sirka * 0.33])
    hlavicka.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 3), ('TOPPADDING', (0, 0), (-1, -1), 1),
                                  ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    story += [hlavicka, Spacer(1, 6)]
    if data['upozorneni']:
        pozor = Table([[t(data['upozorneni'], 'pozor')]], colWidths=[sirka])
        pozor.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF4E0')), ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#E3B062')),
                                   ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, -1), 4),
                                   ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
        story += [pozor, Spacer(1, 4)]
    for tab in data['tabulky']:
        bunky = [[t(r['nazev'], 'bunka'), t(r['hodnota'], {'chybi': 'chybi', 'info': 'info'}.get(r['stav'], 'hodnota'))] for r in tab['radky']]
        tabulka = Table(bunky, colWidths=[sirka * 0.62, sirka * 0.38])
        styl = [('LINEBELOW', (0, 0), (-1, -1), 0.4, LINKA), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 2.5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3), ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('LINEABOVE', (0, 0), (-1, 0), 0.8, colors.HexColor('#8A93A0'))]
        for i, r in enumerate(tab['radky']):
            if r['klic'].endswith(('.base', '.balance')): styl.append(('BACKGROUND', (0, i), (-1, i), ZVYRAZNENI))
        tabulka.setStyle(TableStyle(styl))
        story.append(KeepTogether([Spacer(1, 8), t(tab['urad'], 'urad'), t(tab['formular'], 'formular'), Spacer(1, 3), tabulka]))
    zalohy = (f'Nová záloha podle pravidel {data["rok"] + 1}: průměrná mzda – {data["zalohy"][0][1]} (vyhlášeno {data["zalohy"][0][2]}); '
              'výpočet podle zákonů č. 589/1992 Sb. a 592/1992 Sb.; platí při stejném režimu činnosti.') if data['zalohy'] else f'Novou zálohu ověřte podle pravidel roku {data["rok"] + 1}.'
    story += [Spacer(1, 12), t('Čísla řádků se pro tento rok neuvádějí (nejsou ověřená) – hledejte řádek podle názvu. ' + zalohy +
                               f' Pravidla: {data["pravidla"] or "pro tento rok zatím nejsou"}.', 'paticka')]

    def paticka(canvas, doc):
        canvas.setFont('OSVC', 7.5); canvas.setFillColor(SEDA)
        canvas.drawString(OKRAJ, 20, f'OSVČ evidence · vytvořeno {cas.datum(cas.local(cas.utc_now_naive()), s_casem=True)}')
        canvas.drawRightString(A4[0] - OKRAJ, 20, f'{data["rok"]} · strana {doc.page}')
    doc.build(story, onFirstPage=paticka, onLaterPages=paticka)
    out.seek(0)
    return out
