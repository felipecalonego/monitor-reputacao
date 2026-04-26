# dashboard.py
# Dashboard de Reputação — Streamlit
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

DB_PATH    = Path(__file__).parent / "reputation.db"
DAY_NAMES  = ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"]

# ── página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Monitor de Reputação",
    page_icon="📊",
    layout="wide",
)

# ── CSS customizado ──────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .metric-card {
        background: #f8f9fb;
        border-radius: 10px;
        padding: 16px 20px;
        border-left: 4px solid #1A1A2E;
    }
    .anomaly-critica {
        background: #fff1f0;
        border-left: 4px solid #E94560;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 8px;
    }
    .anomaly-alta {
        background: #fffbe6;
        border-left: 4px solid #F5A623;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 8px;
    }
    .review-card {
        background: #f8f9fb;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 6px;
        border-left: 4px solid #ccc;
    }
    .review-neg { border-left-color: #E94560; }
    .review-pos { border-left-color: #0F9B58; }
    .review-neu { border-left-color: #aaa; }
    .fonte-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
    }
    .badge-google { background: #e8f4fd; color: #1a73e8; }
    .badge-ra     { background: #fdecea; color: #d32f2f; }
</style>
""", unsafe_allow_html=True)


# ── carrega dados ────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_data():
    if not DB_PATH.exists():
        return pd.DataFrame(), pd.DataFrame()
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

# ── sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/combo-chart.png", width=60)
    st.title("Monitor de\nReputação")
    st.divider()

    if reviews.empty:
        st.warning("Banco de dados vazio.\nRode o `reputation_monitor.py` primeiro.")
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
    st.caption(f"Última atualização: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    if st.button("🔄 Atualizar dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── filtra dados ─────────────────────────────────────────────
df = reviews[
    (reviews["place_name"] == place) &
    (reviews["source"].isin(selected_sources))
].copy()

if df.empty:
    st.warning("Nenhum dado para os filtros selecionados.")
    st.stop()

total    = len(df)
positive = (df["sentiment"] == "positive").sum()
negative = (df["sentiment"] == "negative").sum()
neutral  = (df["sentiment"] == "neutral").sum()
avg_rat  = df["rating"].mean()
anomaly_count = len(anomalies[anomalies["place_name"] == place])

# ── cabeçalho ────────────────────────────────────────────────
st.title(f"📊 {place}")
st.caption("Monitoramento de reputação — últimas 8 semanas")
st.divider()

# ── KPIs ─────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total de reviews",  total)
k2.metric("Nota média",        f"{avg_rat:.1f} ⭐")
k3.metric("Positivos",         f"{positive} ({positive/total*100:.0f}%)",
          delta=f"{positive/total*100:.0f}%", delta_color="normal")
k4.metric("Negativos",         f"{negative} ({negative/total*100:.0f}%)",
          delta=f"-{negative/total*100:.0f}%", delta_color="inverse")
k5.metric("Anomalias",         anomaly_count,
          delta="atenção" if anomaly_count > 0 else None,
          delta_color="inverse" if anomaly_count > 0 else "off")

st.divider()

# ── linha 1: evolução temporal + distribuição ────────────────
col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("Evolução semanal")
    weekly = (
        df.groupby(["week", "sentiment"])
        .size()
        .reset_index(name="count")
    )
    color_map = {"positive": "#0F9B58", "negative": "#E94560", "neutral": "#aaaaaa"}
    label_map = {"positive": "Positivo", "negative": "Negativo", "neutral": "Neutro"}
    weekly["sentiment_label"] = weekly["sentiment"].map(label_map)

    fig_line = px.bar(
        weekly, x="week", y="count", color="sentiment",
        color_discrete_map=color_map,
        labels={"week": "Semana", "count": "Reviews", "sentiment": "Sentimento"},
        barmode="stack",
    )
    fig_line.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        legend_title="", height=280,
        margin=dict(t=10, b=10, l=0, r=0),
        xaxis=dict(tickangle=-30),
    )
    st.plotly_chart(fig_line, use_container_width=True)

with col_right:
    st.subheader("Distribuição")
    fig_pie = px.pie(
        values=[positive, negative, neutral],
        names=["Positivo", "Negativo", "Neutro"],
        color_discrete_sequence=["#0F9B58", "#E94560", "#aaaaaa"],
        hole=0.55,
    )
    fig_pie.update_layout(
        height=280,
        margin=dict(t=10, b=10, l=0, r=0),
        legend=dict(orientation="h", yanchor="bottom", y=-0.2),
        showlegend=True,
    )
    fig_pie.update_traces(textinfo="percent", textfont_size=13)
    st.plotly_chart(fig_pie, use_container_width=True)

st.divider()

# ── linha 2: temporal + temas ────────────────────────────────
col_a, col_b = st.columns(2)

neg_df = df[df["sentiment"] == "negative"]

with col_a:
    st.subheader("Reclamações por dia da semana")
    day_counts = neg_df["day_of_week"].value_counts().reindex(range(7), fill_value=0)
    fig_day = px.bar(
        x=DAY_NAMES,
        y=day_counts.values,
        color=day_counts.values,
        color_continuous_scale=["#fdecea", "#E94560"],
        labels={"x": "Dia", "y": "Reclamações", "color": "Qtd"},
    )
    fig_day.update_coloraxes(showscale=False)
    fig_day.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        height=260, margin=dict(t=10, b=10, l=0, r=0),
    )
    st.plotly_chart(fig_day, use_container_width=True)

with col_b:
    st.subheader("Temas mais reclamados")
    all_topics = []
    for tl in neg_df["topics_list"]:
        all_topics.extend(tl)
    top_topics = Counter(all_topics).most_common(7)
    if top_topics:
        t_labels = [t[0].capitalize() for t in top_topics][::-1]
        t_values = [t[1] for t in top_topics][::-1]
        fig_topics = px.bar(
            x=t_values, y=t_labels, orientation="h",
            color=t_values,
            color_continuous_scale=["#fdecea", "#E94560"],
            labels={"x": "Frequência", "y": ""},
        )
        fig_topics.update_coloraxes(showscale=False)
        fig_topics.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            height=260, margin=dict(t=10, b=10, l=0, r=0),
        )
        st.plotly_chart(fig_topics, use_container_width=True)

st.divider()

# ── anomalias ────────────────────────────────────────────────
st.subheader("🚨 Anomalias detectadas")
place_anomalies = anomalies[anomalies["place_name"] == place]

if place_anomalies.empty:
    st.success("Nenhuma anomalia detectada nas últimas 8 semanas.")
else:
    for _, a in place_anomalies.iterrows():
        variacao = (a["negative_count"] / a["baseline_avg"] - 1) * 100 if a["baseline_avg"] else 0
        css_class = "anomaly-critica" if a["severity"] == "CRITICA" else "anomaly-alta"
        icon = "🔴" if a["severity"] == "CRITICA" else "🟡"
        st.markdown(f"""
        <div class="{css_class}">
            <b>{icon} [{a['severity']}] &nbsp; {a['window_start']} → {a['window_end']}</b><br>
            <span style="font-size:14px">
                Reclamações na semana: <b>{a['negative_count']}</b> &nbsp;|&nbsp;
                Média histórica: <b>{a['baseline_avg']:.1f}</b> &nbsp;|&nbsp;
                Variação: <b>+{variacao:.0f}%</b> acima do normal
            </span>
        </div>
        """, unsafe_allow_html=True)

st.divider()

# ── reviews recentes ─────────────────────────────────────────
st.subheader("Reviews recentes")

col_filter1, col_filter2, _ = st.columns([1, 1, 3])
with col_filter1:
    sent_filter = st.selectbox(
        "Sentimento",
        ["Todos", "Negativos", "Positivos", "Neutros"],
    )
with col_filter2:
    src_filter = st.selectbox(
        "Fonte",
        ["Todas"] + [source_labels.get(s, s) for s in sources_avail],
    )

filtered = df.copy()
if sent_filter == "Negativos":  filtered = filtered[filtered["sentiment"] == "negative"]
if sent_filter == "Positivos":  filtered = filtered[filtered["sentiment"] == "positive"]
if sent_filter == "Neutros":    filtered = filtered[filtered["sentiment"] == "neutral"]
if src_filter != "Todas":
    src_key = {v: k for k, v in source_labels.items()}.get(src_filter, src_filter)
    filtered = filtered[filtered["source"] == src_key]

filtered = filtered.sort_values("review_date", ascending=False).head(30)

for _, r in filtered.iterrows():
    sent    = r["sentiment"]
    css_cls = {"positive": "review-pos", "negative": "review-neg"}.get(sent, "review-neu")
    icon    = {"positive": "😊", "negative": "😠", "neutral": "😐"}.get(sent, "😐")
    stars   = "⭐" * int(r["rating"]) if r["rating"] else ""
    date    = r["review_date"].strftime("%d/%m/%Y")
    anomaly = " 🚨" if r.get("is_anomaly") else ""
    src     = r.get("source", "google_reviews")
    badge_class = "badge-ra" if src == "reclame_aqui" else "badge-google"
    badge_label = "Reclame Aqui" if src == "reclame_aqui" else "Google"
    text    = str(r["text"])[:280] + ("..." if len(str(r["text"])) > 280 else "")

    st.markdown(f"""
    <div class="review-card {css_cls}">
        <div style="display:flex; justify-content:space-between; margin-bottom:4px">
            <span><b>{icon} {r['author']}</b> &nbsp; {stars}</span>
            <span style="color:#888; font-size:12px">
                {date}{anomaly} &nbsp;
                <span class="fonte-badge {badge_class}">{badge_label}</span>
            </span>
        </div>
        <div style="font-size:14px; color:#333">{text}</div>
    </div>
    """, unsafe_allow_html=True)
