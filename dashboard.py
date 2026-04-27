# dashboard.py
# Dashboard de Monitoramento de Reputação — Streamlit
# Rodar: streamlit run dashboard.py

import sqlite3
import json
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

DB_PATH   = Path(__file__).parent / "reputation.db"
DAY_NAMES = ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"]

COLORS = {
    "bg":      "#0F0F1A",
    "card":    "#1A1A2E",
    "card2":   "#16213E",
    "cyan":    "#00D4FF",
    "purple":  "#7B2FBE",
    "green":   "#00C896",
    "red":     "#FF4560",
    "yellow":  "#FFB800",
    "text":    "#E8E8F0",
    "subtext": "#8888AA",
}

# ── configuração da página ────────────────────────────────────
st.set_page_config(
    page_title="Monitor de Reputação",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS global ───────────────────────────────────────────────
st.markdown(f"""
<style>
    .block-container {{ padding-top: 1.2rem; padding-bottom: 1rem; }}

    .kpi-card {{
        background: {COLORS['card']};
        border-radius: 14px;
        padding: 20px 24px;
        text-align: center;
        border-top: 3px solid;
        height: 110px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }}
    .kpi-value {{
        font-size: 30px;
        font-weight: 800;
        line-height: 1.1;
        margin-bottom: 4px;
    }}
    .kpi-label {{
        font-size: 11px;
        color: {COLORS['subtext']};
        text-transform: uppercase;
        letter-spacing: 1px;
    }}
    .review-card {{
        background: {COLORS['card2']};
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 8px;
        border-left: 4px solid;
    }}
    .review-neg  {{ border-left-color: {COLORS['red']}; }}
    .review-pos  {{ border-left-color: {COLORS['green']}; }}
    .review-neu  {{ border-left-color: {COLORS['subtext']}; }}
    .review-author {{ font-weight: 700; font-size: 14px; }}
    .review-meta   {{ font-size: 12px; color: {COLORS['subtext']}; }}
    .review-text   {{ font-size: 13px; margin-top: 6px; line-height: 1.5; }}
    .badge {{
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 700;
        margin-left: 6px;
    }}
    .badge-google  {{ background: #1a3a6e; color: #6ab0f5; }}
    .badge-ra      {{ background: #3a1a1a; color: #f56a6a; }}
    .badge-anomaly {{ background: #3a2a0a; color: {COLORS['yellow']}; }}
    .section-header {{
        font-size: 13px;
        font-weight: 700;
        color: {COLORS['cyan']};
        text-transform: uppercase;
        letter-spacing: 1.5px;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid #2a2a4a;
    }}
    section[data-testid="stSidebar"] {{ background: {COLORS['card']} !important; }}
</style>
""", unsafe_allow_html=True)


# ── seed de dados demo ───────────────────────────────────────
def seed_demo():
    from reputation_monitor import (
        init_db, get_mock_reviews, analyse_all_reviews,
        detect_anomalies, save_results,
    )
    from reclame_aqui import get_mock_complaints
    place = "Smart Fit - Unidade Centro"
    conn  = init_db(str(DB_PATH))
    reviews = get_mock_reviews(place) + get_mock_complaints(place)
    reviews = analyse_all_reviews(reviews)
    anomalies = detect_anomalies(reviews)
    save_results(conn, reviews, anomalies, place)
    conn.close()


# ── carrega dados ────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_data():
    if not DB_PATH.exists():
        seed_demo()
    conn = sqlite3.connect(DB_PATH)
    reviews   = pd.read_sql("SELECT * FROM reviews ORDER BY review_date DESC", conn)
    anomalies = pd.read_sql("SELECT * FROM anomaly_log ORDER BY detected_at DESC", conn)
    conn.close()
    if not reviews.empty:
        reviews["review_date"] = pd.to_datetime(reviews["review_date"], utc=True)
        reviews["week"]        = reviews["review_date"].dt.to_period("W").astype(str)
        reviews["topics_list"] = reviews["topics"].apply(
            lambda x: json.loads(x) if x else []
        )
    return reviews, anomalies


reviews, anomalies = load_data()

CHART_LAYOUT = dict(
    plot_bgcolor  = "rgba(0,0,0,0)",
    paper_bgcolor = "rgba(0,0,0,0)",
    font_color    = COLORS["subtext"],
    margin        = dict(t=10, b=10, l=0, r=0),
    legend        = dict(bgcolor="rgba(0,0,0,0)"),
)


# ── sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
    <div style="text-align:center; padding:10px 0 20px 0">
        <div style="font-size:22px; font-weight:800; color:{COLORS['cyan']}">
            Monitor de Reputação
        </div>
        <div style="font-size:12px; color:{COLORS['subtext']}; margin-top:4px">
            Análise inteligente de reviews
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    if reviews.empty:
        st.warning("Banco de dados vazio. Rode o `reputation_monitor.py` primeiro.")
        st.stop()

    places = reviews["place_name"].unique().tolist()
    place  = st.selectbox("Estabelecimento", places)

    sources_avail = reviews[reviews["place_name"] == place]["source"].unique().tolist()
    source_labels = {"google_reviews": "Google Reviews", "reclame_aqui": "Reclame Aqui"}
    selected_sources = st.multiselect(
        "Fontes",
        options=sources_avail,
        default=sources_avail,
        format_func=lambda x: source_labels.get(x, x),
    )

    st.divider()
    st.caption(f"Atualizado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    if st.button("Atualizar dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ── filtro ───────────────────────────────────────────────────
df = reviews[
    (reviews["place_name"] == place) &
    (reviews["source"].isin(selected_sources))
].copy()

if df.empty:
    st.warning("Nenhum dado para os filtros selecionados.")
    st.stop()

total    = len(df)
positive = int((df["sentiment"] == "positive").sum())
negative = int((df["sentiment"] == "negative").sum())
neutral  = int((df["sentiment"] == "neutral").sum())
avg_rat  = df["rating"].mean()
place_anomalies = anomalies[anomalies["place_name"] == place]
anom_count   = len(place_anomalies)
health_score = max(0, min(100, int(100 - (negative / total * 100))))


# ── cabeçalho ────────────────────────────────────────────────
st.markdown(f"""
<div style="margin-bottom:20px">
    <h1 style="margin:0; font-size:26px; font-weight:800">{place}</h1>
    <p style="margin:0; color:{COLORS['subtext']}; font-size:14px">
        Últimas 8 semanas &nbsp;·&nbsp; {total} reviews analisados &nbsp;·&nbsp;
        {len(selected_sources)} fonte(s) ativa(s)
    </p>
</div>
""", unsafe_allow_html=True)


# ── KPIs ─────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)

def kpi(col, label, value, color):
    col.markdown(f"""
    <div class="kpi-card" style="border-top-color:{color}">
        <div class="kpi-value" style="color:{color}">{value}</div>
        <div class="kpi-label">{label}</div>
    </div>
    """, unsafe_allow_html=True)

kpi(c1, "Índice de Saúde",   f"{health_score}%",                        COLORS["cyan"])
kpi(c2, "Nota Média",        f"{avg_rat:.1f} / 5.0",                    COLORS["yellow"])
kpi(c3, "Positivos",         f"{positive} ({positive/total*100:.0f}%)", COLORS["green"])
kpi(c4, "Negativos",         f"{negative} ({negative/total*100:.0f}%)", COLORS["red"])
kpi(c5, "Anomalias",         str(anom_count),
    COLORS["red"] if anom_count > 0 else COLORS["green"])

st.markdown("<br>", unsafe_allow_html=True)


# ── tendência semanal + distribuição ─────────────────────────
col_l, col_r = st.columns([3, 1])

with col_l:
    st.markdown('<div class="section-header">Tendência Semanal de Sentimento</div>', unsafe_allow_html=True)
    weekly = df.groupby(["week", "sentiment"]).size().reset_index(name="count")
    sent_map  = {"positive": "Positivo", "negative": "Negativo", "neutral": "Neutro"}
    color_map = {"Positivo": COLORS["green"], "Negativo": COLORS["red"], "Neutro": COLORS["subtext"]}
    weekly["Sentimento"] = weekly["sentiment"].map(sent_map)

    fig_trend = px.bar(
        weekly, x="week", y="count", color="Sentimento",
        color_discrete_map=color_map,
        labels={"week": "Semana", "count": "Reviews"},
        barmode="stack",
    )
    fig_trend.update_layout(**CHART_LAYOUT, height=260,
                            xaxis=dict(tickangle=-30, gridcolor="#2a2a4a"),
                            yaxis=dict(gridcolor="#2a2a4a"))
    fig_trend.update_traces(marker_line_width=0)
    st.plotly_chart(fig_trend, use_container_width=True)

with col_r:
    st.markdown('<div class="section-header">Distribuição</div>', unsafe_allow_html=True)
    fig_donut = go.Figure(go.Pie(
        labels=["Positivo", "Negativo", "Neutro"],
        values=[positive, negative, neutral],
        hole=0.65,
        marker_colors=[COLORS["green"], COLORS["red"], COLORS["subtext"]],
        textinfo="percent",
        textfont_size=12,
    ))
    fig_donut.add_annotation(
        text=f"<b>{health_score}%</b><br>Saúde",
        x=0.5, y=0.5, showarrow=False,
        font_size=16, font_color=COLORS["cyan"],
    )
    donut_layout = {**CHART_LAYOUT, "height": 260, "showlegend": True,
                    "legend": dict(orientation="h", y=-0.15)}
    fig_donut.update_layout(**donut_layout)
    st.plotly_chart(fig_donut, use_container_width=True)


# ── reclamações por dia + temas ──────────────────────────────
col_a, col_b = st.columns(2)
neg_df = df[df["sentiment"] == "negative"]

with col_a:
    st.markdown('<div class="section-header">Reclamações por Dia da Semana</div>', unsafe_allow_html=True)
    day_counts = neg_df["day_of_week"].value_counts().reindex(range(7), fill_value=0)
    max_day    = day_counts.max() or 1
    bar_colors = [COLORS["red"] if v == max_day else COLORS["purple"] for v in day_counts.values]

    fig_day = go.Figure(go.Bar(
        x=DAY_NAMES, y=day_counts.values,
        marker_color=bar_colors,
        text=day_counts.values, textposition="outside",
        textfont_color=COLORS["text"],
    ))
    fig_day.update_layout(**CHART_LAYOUT, height=250,
                          xaxis=dict(gridcolor="rgba(0,0,0,0)"),
                          yaxis=dict(gridcolor="#2a2a4a"))
    fig_day.update_traces(marker_line_width=0)
    st.plotly_chart(fig_day, use_container_width=True)

with col_b:
    st.markdown('<div class="section-header">Principais Temas de Reclamação</div>', unsafe_allow_html=True)
    all_topics = []
    for tl in neg_df["topics_list"]:
        all_topics.extend(tl)
    top_topics = Counter(all_topics).most_common(7)
    if top_topics:
        t_labels = [t[0].capitalize() for t in top_topics][::-1]
        t_values = [t[1] for t in top_topics][::-1]
        max_t    = max(t_values) or 1
        bar_cols = [COLORS["red"] if v == max_t else COLORS["purple"] for v in t_values]

        fig_topics = go.Figure(go.Bar(
            x=t_values, y=t_labels, orientation="h",
            marker_color=bar_cols,
            text=t_values, textposition="outside",
            textfont_color=COLORS["text"],
        ))
        fig_topics.update_layout(**CHART_LAYOUT, height=250,
                                 xaxis=dict(gridcolor="#2a2a4a"),
                                 yaxis=dict(gridcolor="rgba(0,0,0,0)"))
        fig_topics.update_traces(marker_line_width=0)
        st.plotly_chart(fig_topics, use_container_width=True)


# ── anomalias clicáveis ──────────────────────────────────────
st.markdown('<div class="section-header">Detecção de Anomalias</div>', unsafe_allow_html=True)

if place_anomalies.empty:
    st.success("Nenhuma anomalia detectada nas últimas 8 semanas.")
else:
    for _, a in place_anomalies.iterrows():
        variacao   = (a["negative_count"] / a["baseline_avg"] - 1) * 100 if a["baseline_avg"] else 0
        is_critica = a["severity"] == "CRITICA"
        severidade = "CRITICA" if is_critica else "ALTA"

        with st.expander(
            f"[{severidade}]  {a['window_start']} → {a['window_end']}"
            f"  ·  +{variacao:.0f}% acima da média"
            f"  ·  {a['negative_count']} reclamações",
            expanded=False,
        ):
            m1, m2, m3 = st.columns(3)
            m1.metric("Reclamações na semana", int(a["negative_count"]))
            m2.metric("Média histórica",       f"{a['baseline_avg']:.1f}")
            m3.metric("Variação",              f"+{variacao:.0f}%",
                      delta=f"+{variacao:.0f}%", delta_color="inverse")

            week_reviews = df[df["sentiment"] == "negative"]
            try:
                w_start_ts = pd.to_datetime(a["window_start"], dayfirst=True, utc=True)
                w_end_ts   = pd.to_datetime(a["window_end"],   dayfirst=True, utc=True)
                week_reviews = week_reviews[
                    (week_reviews["review_date"] >= w_start_ts) &
                    (week_reviews["review_date"] <= w_end_ts)
                ]
            except Exception:
                pass

            anom_topics = []
            for tl in week_reviews["topics_list"]:
                anom_topics.extend(tl)
            top_anom = Counter(anom_topics).most_common(5)

            if top_anom:
                st.markdown("**Temas principais neste período:**")
                topic_cols = st.columns(len(top_anom))
                for i, (topic, cnt) in enumerate(top_anom):
                    topic_cols[i].metric(topic.capitalize(), cnt)

            if not week_reviews.empty:
                st.markdown(f"**Reclamações do período ({len(week_reviews)}):**")
                for _, r in week_reviews.head(5).iterrows():
                    src_badge = (
                        '<span class="badge badge-ra">Reclame Aqui</span>'
                        if r.get("source") == "reclame_aqui"
                        else '<span class="badge badge-google">Google</span>'
                    )
                    stars = "★" * int(r["rating"]) if r["rating"] else ""
                    date  = r["review_date"].strftime("%d/%m/%Y")
                    text  = str(r["text"])[:200] + ("..." if len(str(r["text"])) > 200 else "")
                    st.markdown(f"""
                    <div class="review-card review-neg">
                        <div class="review-author">
                            {r['author']} {stars} {src_badge}
                            <span class="review-meta" style="float:right">{date}</span>
                        </div>
                        <div class="review-text">{text}</div>
                    </div>
                    """, unsafe_allow_html=True)


# ── feed de reviews ──────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown('<div class="section-header">Feed de Reviews</div>', unsafe_allow_html=True)

fc1, fc2, fc3 = st.columns(3)
with fc1:
    sent_filter = st.selectbox("Sentimento", ["Todos", "Negativos", "Positivos", "Neutros"])
with fc2:
    src_filter  = st.selectbox("Fonte", ["Todas", "Google Reviews", "Reclame Aqui"])
with fc3:
    sort_by = st.selectbox("Ordenar por", ["Mais recentes", "Mais críticos", "Mais positivos"])

filtered = df.copy()
if sent_filter == "Negativos": filtered = filtered[filtered["sentiment"] == "negative"]
if sent_filter == "Positivos": filtered = filtered[filtered["sentiment"] == "positive"]
if sent_filter == "Neutros":   filtered = filtered[filtered["sentiment"] == "neutral"]
if src_filter == "Google Reviews": filtered = filtered[filtered["source"] == "google_reviews"]
if src_filter == "Reclame Aqui":   filtered = filtered[filtered["source"] == "reclame_aqui"]
if sort_by == "Mais recentes":  filtered = filtered.sort_values("review_date", ascending=False)
if sort_by == "Mais críticos":  filtered = filtered.sort_values("sentiment_score", ascending=True)
if sort_by == "Mais positivos": filtered = filtered.sort_values("sentiment_score", ascending=False)

st.caption(f"Exibindo {min(30, len(filtered))} de {len(filtered)} reviews")

for _, r in filtered.head(30).iterrows():
    sent    = r["sentiment"]
    css_cls = {"positive": "review-pos", "negative": "review-neg"}.get(sent, "review-neu")
    stars   = "★" * int(r["rating"]) if r["rating"] else ""
    date    = r["review_date"].strftime("%d/%m/%Y")
    src     = r.get("source", "google_reviews")
    src_badge = (
        '<span class="badge badge-ra">Reclame Aqui</span>'
        if src == "reclame_aqui"
        else '<span class="badge badge-google">Google</span>'
    )
    anomaly_badge = (
        '<span class="badge badge-anomaly">Anomalia</span>'
        if r.get("is_anomaly") else ""
    )
    text  = str(r["text"])[:250] + ("..." if len(str(r["text"])) > 250 else "")
    score = r["sentiment_score"]
    score_color = COLORS["green"] if score > 0 else COLORS["red"] if score < 0 else COLORS["subtext"]

    st.markdown(f"""
    <div class="review-card {css_cls}">
        <div style="display:flex; justify-content:space-between; align-items:center">
            <span class="review-author">{r['author']} &nbsp; {stars}</span>
            <span class="review-meta">
                {src_badge}{anomaly_badge}
                &nbsp; {date}
                &nbsp; <span style="color:{score_color}; font-weight:700">
                    score {score:+.2f}
                </span>
            </span>
        </div>
        <div class="review-text">{text}</div>
    </div>
    """, unsafe_allow_html=True)
