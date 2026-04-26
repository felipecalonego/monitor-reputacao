# generate_pdf.py
# Exporta o relatório de reputação para PDF profissional
# Requer: pip install reportlab

import sqlite3
import json
from datetime import datetime, timezone
from collections import Counter, defaultdict
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ── paleta de cores ──────────────────────────────────────────
C_PRIMARY   = colors.HexColor("#1A1A2E")  # azul escuro
C_ACCENT    = colors.HexColor("#E94560")  # vermelho
C_GREEN     = colors.HexColor("#0F9B58")  # verde
C_YELLOW    = colors.HexColor("#F5A623")  # amarelo/laranja
C_LIGHT     = colors.HexColor("#F4F6F8")  # fundo claro
C_MID       = colors.HexColor("#DDE3EA")  # cinza médio
C_TEXT      = colors.HexColor("#2D2D2D")  # texto principal
C_SUBTEXT   = colors.HexColor("#6B7280")  # texto secundário
C_WHITE     = colors.white
# ─────────────────────────────────────────────────────────────

DAY_NAMES = ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"]


def load_data_from_db(db_path: str, place_name: str) -> tuple:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    reviews = [dict(r) for r in conn.execute(
        "SELECT * FROM reviews WHERE place_name = ? ORDER BY review_date DESC",
        (place_name,)
    ).fetchall()]

    anomalies = [dict(a) for a in conn.execute(
        "SELECT * FROM anomaly_log WHERE place_name = ? ORDER BY detected_at DESC",
        (place_name,)
    ).fetchall()]

    conn.close()
    return reviews, anomalies


def build_temporal(reviews):
    neg = [r for r in reviews if r["sentiment"] == "negative"]
    by_day    = Counter(r["day_of_week"] for r in neg)
    by_period = Counter()
    for r in neg:
        h = r["hour_of_day"]
        if 6 <= h < 12:   by_period["Manha"] += 1
        elif 12 <= h < 18: by_period["Tarde"] += 1
        else:              by_period["Noite"] += 1
    all_topics = []
    for r in neg:
        all_topics.extend(json.loads(r.get("topics") or "[]"))
    return by_day, by_period, Counter(all_topics).most_common(5)


def mini_bar(value, max_val, width=14):
    if max_val == 0:
        return ""
    filled = max(1, round(value / max_val * width)) if value else 0
    return "█" * filled + "░" * (width - filled)


def make_pdf(place_name: str, db_path: str = "reputation.db", output_path: str = None):
    reviews, anomalies = load_data_from_db(db_path, place_name)
    if not reviews:
        print(f"Nenhum dado encontrado para '{place_name}' no banco.")
        return

    if output_path is None:
        safe = place_name.replace(" ", "_").replace("/", "-")
        output_path = str(Path(db_path).parent / f"relatorio_{safe}.pdf")

    total    = len(reviews)
    positive = sum(1 for r in reviews if r["sentiment"] == "positive")
    negative = sum(1 for r in reviews if r["sentiment"] == "negative")
    neutral  = sum(1 for r in reviews if r["sentiment"] == "neutral")
    avg_rat  = sum(r["rating"] for r in reviews) / total if total else 0

    by_day, by_period, top_topics = build_temporal(reviews)
    neg_total = sum(by_day.values())

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    base   = getSampleStyleSheet()
    story  = []

    # ── estilos ──────────────────────────────────────────────
    def style(name, **kw):
        s = ParagraphStyle(name, parent=base["Normal"], **kw)
        return s

    s_title    = style("title",    fontSize=22, textColor=C_WHITE,    fontName="Helvetica-Bold",
                       alignment=TA_CENTER, spaceAfter=4)
    s_subtitle = style("sub",      fontSize=11, textColor=C_WHITE,    fontName="Helvetica",
                       alignment=TA_CENTER)
    s_section  = style("section",  fontSize=13, textColor=C_PRIMARY,  fontName="Helvetica-Bold",
                       spaceBefore=14, spaceAfter=6)
    s_body     = style("body",     fontSize=9,  textColor=C_TEXT,     fontName="Helvetica",
                       leading=13)
    s_small    = style("small",    fontSize=8,  textColor=C_SUBTEXT,  fontName="Helvetica",
                       leading=11)
    s_quote    = style("quote",    fontSize=8.5,textColor=C_TEXT,     fontName="Helvetica-Oblique",
                       leading=12, leftIndent=6)
    s_label    = style("label",    fontSize=8,  textColor=C_SUBTEXT,  fontName="Helvetica",
                       alignment=TA_RIGHT)

    # ── cabeçalho colorido ───────────────────────────────────
    header_data = [[
        Paragraph("RELATORIO DE REPUTACAO", s_title),
    ],[
        Paragraph(place_name, s_subtitle),
    ],[
        Paragraph(
            f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  Ultimas 8 semanas",
            s_subtitle
        ),
    ]]
    header_table = Table(header_data, colWidths=[17*cm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_PRIMARY),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [C_PRIMARY]),
        ("TOPPADDING",    (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING",   (0,0), (-1,-1), 16),
        ("RIGHTPADDING",  (0,0), (-1,-1), 16),
        ("ROUNDEDCORNERS", [6]),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.5*cm))

    # ── KPIs ─────────────────────────────────────────────────
    def kpi_cell(label, value, color=C_PRIMARY):
        return [
            Paragraph(f'<font size="20" color="{color.hexval()}">'
                      f'<b>{value}</b></font>', style("kv", fontSize=20,
                      fontName="Helvetica-Bold", alignment=TA_CENTER,
                      textColor=color)),
            Paragraph(label, style("kl", fontSize=8, fontName="Helvetica",
                      alignment=TA_CENTER, textColor=C_SUBTEXT)),
        ]

    star_str = "★" * round(avg_rat) + "☆" * (5 - round(avg_rat))
    kpi_data = [[
        kpi_cell("Reviews analisados", str(total)),
        kpi_cell("Nota media", f"{avg_rat:.1f}  {star_str}", C_YELLOW),
        kpi_cell("Positivos", f"{positive} ({positive/total*100:.0f}%)", C_GREEN),
        kpi_cell("Negativos", f"{negative} ({negative/total*100:.0f}%)", C_ACCENT),
    ]]
    kpi_flat = [[cell for col in kpi_data[0] for cell in col]]
    kpi_table = Table(
        [[c[0] for c in kpi_data[0]],
         [c[1] for c in kpi_data[0]]],
        colWidths=[4.25*cm]*4
    )
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_LIGHT),
        ("BOX",           (0,0), (-1,-1), 0.5, C_MID),
        ("INNERGRID",     (0,0), (-1,-1), 0.5, C_MID),
        ("TOPPADDING",    (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 0.4*cm))

    # ── anomalias ────────────────────────────────────────────
    story.append(Paragraph("DETECCAO DE ANOMALIAS", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=C_MID))
    story.append(Spacer(1, 0.2*cm))

    if not anomalies:
        story.append(Paragraph("Nenhuma anomalia detectada nas ultimas 8 semanas.", s_body))
    else:
        for a in anomalies:
            sev_color = C_ACCENT if a["severity"] == "CRITICA" else C_YELLOW
            variacao  = (a["negative_count"] / a["baseline_avg"] - 1) * 100 if a["baseline_avg"] else 0

            anom_data = [
                [
                    Paragraph(
                        f'<b><font color="{sev_color.hexval()}">[{a["severity"]}]</font>'
                        f'  {a["window_start"]} a {a["window_end"]}</b>',
                        style("ah", fontSize=10, fontName="Helvetica-Bold", textColor=C_TEXT)
                    ),
                ],[
                    Paragraph(
                        f'Reclamacoes na semana: <b>{a["negative_count"]}</b>'
                        f'  |  Media historica: <b>{a["baseline_avg"]:.1f}</b>'
                        f'  |  Variacao: <b>+{variacao:.0f}%</b> acima do normal',
                        s_body
                    ),
                ]
            ]
            anom_table = Table(anom_data, colWidths=[17*cm])
            anom_table.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,-1), C_LIGHT),
                ("LEFTPADDING",   (0,0), (-1,-1), 10),
                ("RIGHTPADDING",  (0,0), (-1,-1), 10),
                ("TOPPADDING",    (0,0), (-1,-1), 8),
                ("BOTTOMPADDING", (0,0), (-1,-1), 8),
                ("LINEAFTER",     (0,0), (0,-1), 3, sev_color),
            ]))
            story.append(KeepTogether(anom_table))
            story.append(Spacer(1, 0.2*cm))

    # ── análise temporal ─────────────────────────────────────
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph("PADROES TEMPORAIS DAS RECLAMACOES", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=C_MID))
    story.append(Spacer(1, 0.2*cm))

    max_day = max(by_day.values()) if by_day else 1
    day_rows = [
        [Paragraph("<b>Dia da semana</b>", s_small),
         Paragraph("<b>Volume de reclamacoes</b>", s_small),
         Paragraph("<b>Qtd</b>", s_label)]
    ]
    for idx, name in enumerate(DAY_NAMES):
        cnt = by_day.get(idx, 0)
        highlight = cnt == max_day and max_day > 0
        bar_str = mini_bar(cnt, max_day)
        bar_color = C_ACCENT.hexval() if highlight else C_PRIMARY.hexval()
        day_rows.append([
            Paragraph(name, s_body),
            Paragraph(f'<font color="{bar_color}" face="Courier"><b>{bar_str}</b></font>',
                      style("bar", fontSize=8, fontName="Courier")),
            Paragraph(f"<b>{cnt}</b>" if highlight else str(cnt), s_label),
        ])

    day_table = Table(day_rows, colWidths=[3.5*cm, 11*cm, 2.5*cm])
    day_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), C_PRIMARY),
        ("TEXTCOLOR",     (0,0), (-1,0), C_WHITE),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("GRID",          (0,0), (-1,-1), 0.3, C_MID),
        ("ALIGN",         (2,0), (2,-1), "RIGHT"),
    ]))
    story.append(day_table)
    story.append(Spacer(1, 0.3*cm))

    # periodo do dia
    max_per = max(by_period.values()) if by_period else 1
    period_rows = [
        [Paragraph("<b>Periodo</b>", s_small),
         Paragraph("<b>Volume</b>", s_small),
         Paragraph("<b>Qtd</b>", s_label)]
    ]
    for period in ["Manha", "Tarde", "Noite"]:
        cnt = by_period.get(period, 0)
        highlight = cnt == max_per and max_per > 0
        bar_color = C_ACCENT.hexval() if highlight else C_PRIMARY.hexval()
        period_rows.append([
            Paragraph(period, s_body),
            Paragraph(f'<font color="{bar_color}" face="Courier"><b>{mini_bar(cnt, max_per)}</b></font>',
                      style("bar2", fontSize=8, fontName="Courier")),
            Paragraph(f"<b>{cnt}</b>" if highlight else str(cnt), s_label),
        ])
    period_table = Table(period_rows, colWidths=[3.5*cm, 11*cm, 2.5*cm])
    period_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), C_PRIMARY),
        ("TEXTCOLOR",     (0,0), (-1,0), C_WHITE),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("GRID",          (0,0), (-1,-1), 0.3, C_MID),
        ("ALIGN",         (2,0), (2,-1), "RIGHT"),
    ]))
    story.append(period_table)

    # ── temas mais reclamados ────────────────────────────────
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("TEMAS MAIS RECLAMADOS", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=C_MID))
    story.append(Spacer(1, 0.2*cm))

    if top_topics:
        max_t = top_topics[0][1]
        topic_rows = [
            [Paragraph("<b>Tema</b>", s_small),
             Paragraph("<b>Frequencia</b>", s_small),
             Paragraph("<b>Qtd</b>", s_label)]
        ]
        for topic, cnt in top_topics:
            topic_rows.append([
                Paragraph(topic.capitalize(), s_body),
                Paragraph(
                    f'<font color="{C_ACCENT.hexval()}" face="Courier">'
                    f'<b>{mini_bar(cnt, max_t)}</b></font>',
                    style("tbar", fontSize=8, fontName="Courier")),
                Paragraph(str(cnt), s_label),
            ])
        topic_table = Table(topic_rows, colWidths=[3.5*cm, 11*cm, 2.5*cm])
        topic_table.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), C_PRIMARY),
            ("TEXTCOLOR",     (0,0), (-1,0), C_WHITE),
            ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",      (0,0), (-1,0), 8),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("GRID",          (0,0), (-1,-1), 0.3, C_MID),
            ("ALIGN",         (2,0), (2,-1), "RIGHT"),
        ]))
        story.append(topic_table)

    # ── reviews selecionados ─────────────────────────────────
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("REVIEWS EM DESTAQUE", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=C_MID))
    story.append(Spacer(1, 0.2*cm))

    neg_reviews = sorted(
        [r for r in reviews if r["sentiment"] == "negative"],
        key=lambda r: abs(r["sentiment_score"]), reverse=True
    )[:3]
    pos_reviews = sorted(
        [r for r in reviews if r["sentiment"] == "positive"],
        key=lambda r: r["sentiment_score"], reverse=True
    )[:2]

    for section_label, section_reviews, color in [
        ("Reclamacoes mais criticas", neg_reviews, C_ACCENT),
        ("Elogios em destaque",       pos_reviews, C_GREEN),
    ]:
        if not section_reviews:
            continue
        story.append(Paragraph(
            f'<font color="{color.hexval()}"><b>{section_label}</b></font>',
            style("rl", fontSize=9, fontName="Helvetica-Bold", spaceBefore=6)
        ))
        for r in section_reviews:
            stars  = "★" * r["rating"] + "☆" * (5 - r["rating"])
            date   = datetime.fromisoformat(r["review_date"]).strftime("%d/%m/%Y")
            anomaly_tag = "  [ANOMALIA]" if r.get("is_anomaly") else ""
            text   = r["text"][:220] + ("..." if len(r["text"]) > 220 else "")

            rev_data = [
                [Paragraph(
                    f'<b>{r["author"]}</b>  <font color="{C_YELLOW.hexval()}">{stars}</font>'
                    f'  <font color="{C_SUBTEXT.hexval()}">{date}{anomaly_tag}</font>',
                    style("rh", fontSize=8.5, fontName="Helvetica-Bold", textColor=C_TEXT)
                )],
                [Paragraph(f'"{text}"', s_quote)],
            ]
            rev_table = Table(rev_data, colWidths=[17*cm])
            rev_table.setStyle(TableStyle([
                ("BACKGROUND",   (0,0), (-1,-1), C_LIGHT),
                ("LEFTPADDING",  (0,0), (-1,-1), 10),
                ("RIGHTPADDING", (0,0), (-1,-1), 10),
                ("TOPPADDING",   (0,0), (-1,-1), 7),
                ("BOTTOMPADDING",(0,0), (-1,-1), 7),
                ("LINEAFTER",    (0,0), (0,-1), 3, color),
            ]))
            story.append(KeepTogether(rev_table))
            story.append(Spacer(1, 0.15*cm))

    # ── rodapé ───────────────────────────────────────────────
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_MID))
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph(
        "Relatorio gerado automaticamente pelo Sistema de Monitoramento de Reputacao  |  Dados: Google Reviews",
        style("footer", fontSize=7, textColor=C_SUBTEXT, alignment=TA_CENTER)
    ))

    doc.build(story)
    print(f"\nPDF gerado: {output_path}")
    return output_path


if __name__ == "__main__":
    import sys
    place = sys.argv[1] if len(sys.argv) > 1 else "Smart Fit - Unidade Centro"
    make_pdf(place)
