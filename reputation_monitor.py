# reputation_monitor.py
# Sistema de Monitoramento de Reputação - Google Reviews + Reclame Aqui
# Requer: pip install vaderSentiment python-dotenv requests beautifulsoup4

import os
import sqlite3
import json
import math
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from pathlib import Path
from dotenv import load_dotenv
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from reclame_aqui import fetch_reclame_aqui, get_mock_complaints

load_dotenv(Path(__file__).parent / ".env", override=True)

# ============================================================
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
DEMO_MODE             = True   # False = usa APIs reais
USE_RECLAME_AQUI      = True   # inclui Reclame Aqui na coleta
DB_PATH               = "reputation.db"
ANOMALY_THRESHOLD     = 2.0
# ============================================================

analyser = SentimentIntensityAnalyzer()

PT_SENTIMENT = {
    # positivos
    "otimo": 2.5, "otima": 2.5, "incrivel": 2.8, "perfeito": 2.6, "excelente": 2.7,
    "recomendo": 2.5, "atencioso": 2.3, "amo": 2.6, "bom": 1.8, "boa": 1.8,
    "barato": 1.5, "melhor": 2.0, "maravilhoso": 2.8, "fantastico": 2.8,
    "gostei": 1.8, "adorei": 2.5, "parabens": 2.0, "custo-beneficio": 1.8,
    "satisfeito": 1.8, "satisfeita": 1.8, "agradavel": 1.6, "eficiente": 1.6,
    "rapido": 1.2, "amei": 2.6, "nota 10": 2.8, "top": 1.8,
    # negativos
    "pessimo": -2.8, "pessima": -2.8, "absurdo": -2.8, "horrivel": -2.8,
    "terrivel": -2.8, "inadmissivel": -2.6, "precario": -2.4, "precaria": -2.4,
    "reclamacao": -2.0, "problema": -1.8, "odio": -2.8, "ruim": -2.0,
    "caro": -1.5, "lento": -1.2, "lenta": -1.2, "descaso": -2.2,
    "cancelou": -1.5, "multa": -1.8, "cobrou": -1.2, "enrolando": -2.0,
    "lotado": -1.5, "lotada": -1.5, "impossivel": -1.8, "sujeira": -2.2,
    "sujo": -2.2, "suja": -2.2, "quebrado": -2.0, "quebrada": -2.0,
    "nao funciona": -2.2, "nao funcionam": -2.2, "sem manutencao": -2.4,
    "demora": -1.6, "demorou": -1.6, "falta": -1.4, "faltou": -1.4,
    "desrespeitoso": -2.4, "grosseiro": -2.4, "incompetente": -2.6,
    "fraude": -3.0, "enganou": -2.8, "mentira": -2.6, "pessimo atendimento": -3.0,
}

TOPIC_MAP = {
    "atendimento": ["atendimento", "funcionario", "funcionaria", "recepcao", "staff",
                    "grosseiro", "educado", "simpatico", "desrespeitoso"],
    "limpeza":     ["limpeza", "sujo", "suja", "sujeira", "higiene", "banheiro", "vestiario"],
    "equipamentos":["equipamento", "maquina", "aparelho", "quebrado", "quebrada",
                    "manutencao", "nao funciona"],
    "preco":       ["preco", "caro", "barato", "mensalidade", "cobranca", "cobrou",
                    "taxa", "valor", "custo"],
    "espera":      ["demora", "demorou", "fila", "espera", "lento", "rapido"],
    "espaco":      ["lotado", "lotada", "cheio", "cheia", "espaco", "lugar"],
    "cancelamento":["cancelou", "cancelar", "multa", "contrato", "clausula"],
    "infraestrutura": ["ar condicionado", "chuveiro", "vestiario", "estacionamento",
                       "instalacao", "reforma"],
}


# ---------- banco de dados ----------------------------------

def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id              TEXT PRIMARY KEY,
            place_id        TEXT,
            place_name      TEXT,
            author          TEXT,
            rating          INTEGER,
            text            TEXT,
            review_date     TEXT,
            day_of_week     INTEGER,
            hour_of_day     INTEGER,
            sentiment       TEXT,
            sentiment_score REAL,
            topics          TEXT,
            is_anomaly      INTEGER DEFAULT 0,
            source          TEXT DEFAULT 'google_reviews',
            collected_at    TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS anomaly_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id        TEXT,
            place_name      TEXT,
            detected_at     TEXT,
            window_start    TEXT,
            window_end      TEXT,
            negative_count  INTEGER,
            baseline_avg    REAL,
            severity        TEXT
        )
    """)
    conn.commit()
    return conn


# ---------- mock de reviews do Google -----------------------

def get_mock_reviews(place_name: str = "Smart Fit - Unidade Centro") -> list[dict]:
    now = datetime.now(timezone.utc)

    # reviews espalhados pelas ultimas 8 semanas com padrao proposital:
    # - reclamacoes de limpeza concentradas nas segundas (pos-fim-de-semana)
    # - pico de reclamacoes na semana 2 (anomalia simulada)
    raw = [
        # semana 8 (mais antiga)
        (-55, 5, "Excelente academia! Equipamentos novos e atendimento otimo.", "Ana Lima"),
        (-54, 4, "Boa academia, preco justo. Recomendo para quem quer treinar bem.", "Carlos M."),
        (-53, 2, "Vestiario sujo e mal cheiroso. Esperava mais de uma rede grande.", "Patricia F."),
        (-52, 5, "Melhor custo-beneficio da cidade. Professores atenciosos.", "Rodrigo S."),
        # semana 7
        (-48, 4, "Academia boa, equipamentos em bom estado. Unica reclamacao e que fica lotada no horario de pico.", "Fernanda A."),
        (-47, 1, "Pessimo atendimento! Funcionaria foi grossa e nao resolveu meu problema.", "Marco P."),
        (-46, 5, "Incrivel! Perdi 6kg em 2 meses treinando aqui. Equipe motivada.", "Juliana R."),
        (-45, 3, "Regular. Alguns equipamentos estao quebrados ha semanas sem manutencao.", "Bruno K."),
        # semana 6
        (-41, 5, "Top demais! Ambiente otimo e musica animada.", "Thiago N."),
        (-40, 2, "Ar condicionado quebrado ha 3 semanas. Insuportavel treinar no calor.", "Mariana C."),
        (-39, 4, "Gostei bastante. Estrutura boa e professores presentes.", "Lucas T."),
        (-38, 1, "Cobraram mensalidade indevida e o atendimento foi um absurdo. Vou cancelar.", "Camila V."),
        # semana 5
        (-34, 5, "Academia maravilhosa, recomendo sem hesitar!", "Diego M."),
        (-33, 4, "Bom custo-beneficio. Poderia ter mais espaco livre.", "Renata L."),
        (-32, 3, "Banheiro precisando de reforma urgente. Resto e ok.", "Felipe G."),
        (-31, 5, "Melhor academia que ja frequentei. Atendimento excelente.", "Aline B."),
        # semana 4
        (-27, 2, "Lotado demais! Impossivel usar os equipamentos no horario comercial.", "Paulo R."),
        (-26, 1, "Equipamentos quebrados, banheiro sujo, atendimento pessimo. Que decapacao!", "Silvia O."),
        (-25, 5, "Perfeito! Espaco limpo, professores dedicados. Nota 10.", "Eduardo F."),
        (-24, 2, "Sujeira nos vestiarios toda segunda-feira. Parece que nao limpam no fim de semana.", "Amanda C."),
        # semana 3  ← ANOMALIA: semana com pico de reclamacoes
        (-20, 1, "Fraude! Cancelei o plano e continuaram cobrando. Absurdo!", "Roberto A."),
        (-19, 1, "Pessimo! Maquinas quebradas, ninguem resolve. Vou processar.", "Tatiana B."),
        (-18, 2, "Atendimento horrivel, funcionarios mal treinados. Muito ruim.", "Gustavo L."),
        (-17, 1, "Nao funciona nenhuma maquina de musculacao. Inadmissivel pagar por isso.", "Vanessa P."),
        (-16, 2, "Vestiario sujo de novo numa segunda. Esse padrao e recorrente.", "Rafael M."),
        (-15, 1, "Terrivel! Cobranca indevida e sem resposta do SAC ha 10 dias.", "Luciana T."),
        (-14, 3, "Hoje estava ok. Mas ja tive problemas antes com atendimento.", "Pedro H."),
        # semana 2
        (-13, 5, "Voltei a treinar aqui depois de uma pausa. Melhorou muito!", "Beatriz C."),
        (-11, 4, "Bom ambiente, so falta mais equipamentos de cardio.", "Henrique S."),
        (-10, 2, "Segunda-feira de novo com vestiario uma bagunca. Consistente no negativo.", "Isabela R."),
        (-9,  5, "Excelente! Professores otimos e estrutura de qualidade.", "Mauricio V."),
        # semana 1 (mais recente)
        (-6,  4, "Gostei bastante, preco acessivel e bom atendimento.", "Natalia F."),
        (-5,  2, "Equipamento de supino quebrado ha dias. Quando vao consertar?", "Alexandre M."),
        (-4,  5, "Fantástico! Melhor academia da regiao sem duvida.", "Priscila A."),
        (-3,  1, "Horrivel! Cobrou taxa indevida e recusa a estornar. Vou ao Procon.", "Leandro B."),
        (-2,  4, "Boa academia. Atendimento melhorou muito ultimamente.", "Claudia N."),
        (-1,  5, "Incrivel! Adorei o novo espaco de alongamento.", "Vinicius P."),
    ]

    reviews = []
    for i, (days_ago, rating, text, author) in enumerate(raw):
        # adiciona variacao de hora: reclamacoes tendem a ocorrer de manha (pos-treino)
        if rating <= 2:
            hour = 8 + (i % 4)   # 8h-11h
        else:
            hour = 12 + (i % 10) # 12h-21h

        dt = now + timedelta(days=days_ago, hours=hour - now.hour)
        reviews.append({
            "id":          f"review_{i+1:04d}",
            "place_id":    "mock_place_001",
            "place_name":  place_name,
            "author":      author,
            "rating":      rating,
            "text":        text,
            "review_date": dt.isoformat(),
            "day_of_week": dt.weekday(),   # 0=segunda, 6=domingo
            "hour_of_day": hour,
        })

    print(f"[DEMO] {len(reviews)} reviews simulados carregados ({place_name}).")
    return reviews


# ---------- busca real via Google Places API ----------------

def fetch_google_reviews_api(place_id: str, place_name: str) -> list[dict]:
    import requests
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields":   "name,reviews",
        "language": "pt-BR",
        "key":      GOOGLE_PLACES_API_KEY,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    reviews = []
    now = datetime.now(timezone.utc)
    for i, r in enumerate(data.get("result", {}).get("reviews", [])):
        ts = datetime.fromtimestamp(r["time"], tz=timezone.utc)
        reviews.append({
            "id":          f"{place_id}_{r['time']}",
            "place_id":    place_id,
            "place_name":  place_name,
            "author":      r.get("author_name", "Anonimo"),
            "rating":      r.get("rating", 3),
            "text":        r.get("text", ""),
            "review_date": ts.isoformat(),
            "day_of_week": ts.weekday(),
            "hour_of_day": ts.hour,
        })

    print(f"{len(reviews)} reviews obtidos para '{place_name}'.")
    return reviews


# ---------- análise de sentimento ---------------------------

def analyse_review(text: str, rating: int) -> dict:
    scores = analyser.polarity_scores(text)
    text_lower = text.lower()

    boost = 0.0
    for word, weight in PT_SENTIMENT.items():
        if word in text_lower:
            boost += weight

    # rating ancora o sentimento (1-2 estrelas = negativo, 4-5 = positivo)
    rating_signal = (rating - 3) * 0.4

    compound = scores["compound"] + boost * 0.12 + rating_signal
    compound = max(-1.0, min(1.0, compound))

    if compound >= 0.05:
        sentiment = "positive"
    elif compound <= -0.05:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    topics = []
    for topic, keywords in TOPIC_MAP.items():
        if any(kw in text_lower for kw in keywords):
            topics.append(topic)
    if not topics:
        topics = ["geral"]

    return {"sentiment": sentiment, "score": round(compound, 3), "topics": topics}


def analyse_all_reviews(reviews: list[dict]) -> list[dict]:
    for i, r in enumerate(reviews, 1):
        print(f"  Analisando review {i}/{len(reviews)}...", end="\r")
        result = analyse_review(r["text"], r["rating"])
        r["sentiment"]       = result["sentiment"]
        r["sentiment_score"] = result["score"]
        r["topics"]          = json.dumps(result["topics"], ensure_ascii=False)
    print(f"\nAnalise concluida.           ")
    return reviews


# ---------- detecção de anomalias ---------------------------

def detect_anomalies(reviews: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    weeks = defaultdict(list)

    for r in reviews:
        dt = datetime.fromisoformat(r["review_date"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days_ago = (now - dt).days
        week_num = days_ago // 7
        if week_num < 8:
            weeks[week_num].append(r)

    anomalies = []

    for week_num, week_reviews in weeks.items():
        neg_count = sum(1 for r in week_reviews if r["sentiment"] == "negative")
        total     = len(week_reviews)
        if total == 0:
            continue

        # baseline: media das semanas anteriores (excluindo a semana atual)
        baseline_weeks = [v for k, v in weeks.items() if k > week_num]
        if not baseline_weeks:
            continue

        baseline_neg = [
            sum(1 for r in w if r["sentiment"] == "negative")
            for w in baseline_weeks
        ]
        avg_baseline = sum(baseline_neg) / len(baseline_neg)

        if avg_baseline > 0 and neg_count >= avg_baseline * ANOMALY_THRESHOLD:
            week_end   = now - timedelta(days=week_num * 7)
            week_start = week_end - timedelta(days=7)
            severity   = "CRITICA" if neg_count >= avg_baseline * 3 else "ALTA"

            anomalies.append({
                "week_num":      week_num,
                "week_start":    week_start.strftime("%d/%m/%Y"),
                "week_end":      week_end.strftime("%d/%m/%Y"),
                "negative_count": neg_count,
                "baseline_avg":  round(avg_baseline, 1),
                "severity":      severity,
                "reviews":       week_reviews,
            })

            # marca os reviews dessa semana como anomalia
            for r in week_reviews:
                if r["sentiment"] == "negative":
                    r["is_anomaly"] = 1

    return anomalies


# ---------- análise temporal --------------------------------

DAY_NAMES = ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"]

def temporal_analysis(reviews: list[dict]) -> dict:
    neg_reviews = [r for r in reviews if r["sentiment"] == "negative"]

    # por dia da semana
    by_day = Counter(r["day_of_week"] for r in neg_reviews)

    # por periodo do dia
    def period(hour):
        if 6 <= hour < 12:  return "Manha (6h-12h)"
        if 12 <= hour < 18: return "Tarde (12h-18h)"
        if 18 <= hour < 23: return "Noite (18h-23h)"
        return "Madrugada"

    by_period = Counter(period(r["hour_of_day"]) for r in neg_reviews)

    # topicos mais reclamados
    all_topics = []
    for r in neg_reviews:
        all_topics.extend(json.loads(r.get("topics", "[]")))
    top_topics = Counter(all_topics).most_common(5)

    return {
        "by_day":    by_day,
        "by_period": by_period,
        "top_topics": top_topics,
        "total_neg": len(neg_reviews),
    }


# ---------- persistência ------------------------------------

def save_results(conn: sqlite3.Connection, reviews: list[dict],
                 anomalies: list[dict], place_name: str):
    now = datetime.now(timezone.utc).isoformat()
    place_id = reviews[0]["place_id"] if reviews else "unknown"

    for r in reviews:
        conn.execute("""
            INSERT OR REPLACE INTO reviews
            (id, place_id, place_name, author, rating, text, review_date,
             day_of_week, hour_of_day, sentiment, sentiment_score, topics,
             is_anomaly, source, collected_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            r["id"], r["place_id"], r["place_name"], r["author"],
            r["rating"], r["text"], r["review_date"],
            r["day_of_week"], r["hour_of_day"],
            r["sentiment"], r["sentiment_score"], r["topics"],
            r.get("is_anomaly", 0), r.get("source", "google_reviews"), now,
        ))

    for a in anomalies:
        conn.execute("""
            INSERT INTO anomaly_log
            (place_id, place_name, detected_at, window_start, window_end,
             negative_count, baseline_avg, severity)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            place_id, place_name, now,
            a["week_start"], a["week_end"],
            a["negative_count"], a["baseline_avg"], a["severity"],
        ))

    conn.commit()
    print(f"Dados salvos em '{DB_PATH}'.")


# ---------- relatório no terminal ---------------------------

def bar(value, max_value, width=20, char="#"):
    filled = int(round(value / max_value * width)) if max_value else 0
    return char * filled + "." * (width - filled)


def print_report(reviews: list[dict], anomalies: list[dict],
                 temporal: dict, place_name: str):
    total    = len(reviews)
    positive = sum(1 for r in reviews if r["sentiment"] == "positive")
    negative = sum(1 for r in reviews if r["sentiment"] == "negative")
    neutral  = sum(1 for r in reviews if r["sentiment"] == "neutral")
    avg_rating = sum(r["rating"] for r in reviews) / total if total else 0

    print("\n" + "=" * 62)
    print(f"  RELATORIO DE REPUTACAO")
    print(f"  {place_name}")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  Ultimas 8 semanas")
    print("=" * 62)

    # resumo geral
    print(f"\n  RESUMO GERAL")
    print(f"  Reviews analisados : {total}")
    print(f"  Nota media         : {avg_rating:.1f} / 5.0")
    print(f"  Positivos : {positive:3d}  ({positive/total*100:.1f}%)")
    print(f"  Negativos : {negative:3d}  ({negative/total*100:.1f}%)")
    print(f"  Neutros   : {neutral:3d}   ({neutral/total*100:.1f}%)")

    # anomalias
    print(f"\n  DETECCAO DE ANOMALIAS")
    print("-" * 62)
    if not anomalies:
        print("  Nenhuma anomalia detectada nas ultimas 8 semanas.")
    else:
        for a in sorted(anomalies, key=lambda x: x["week_num"]):
            print(f"\n  [{a['severity']}] Semana {a['week_start']} a {a['week_end']}")
            print(f"  Reclamacoes: {a['negative_count']}  |  Media historica: {a['baseline_avg']:.1f}")
            print(f"  Variacao: +{(a['negative_count']/a['baseline_avg'] - 1)*100:.0f}% acima do normal")
            neg_in_week = [r for r in a["reviews"] if r["sentiment"] == "negative"]
            top_week_topics = Counter()
            for r in neg_in_week:
                top_week_topics.update(json.loads(r.get("topics", "[]")))
            if top_week_topics:
                print(f"  Temas: {', '.join(t for t, _ in top_week_topics.most_common(3))}")

    # analise temporal
    print(f"\n  PADROES TEMPORAIS DAS RECLAMACOES")
    print("-" * 62)

    print(f"\n  Por dia da semana (total: {temporal['total_neg']} reclamacoes):")
    max_day = max(temporal["by_day"].values()) if temporal["by_day"] else 1
    for day_idx, day_name in enumerate(DAY_NAMES):
        count = temporal["by_day"].get(day_idx, 0)
        marker = " <<" if count == max_day and max_day > 0 else ""
        print(f"    {day_name:8s} {bar(count, max_day):20s} {count:2d}{marker}")

    print(f"\n  Por periodo do dia:")
    max_period = max(temporal["by_period"].values()) if temporal["by_period"] else 1
    for period_name in ["Manha (6h-12h)", "Tarde (12h-18h)", "Noite (18h-23h)"]:
        count = temporal["by_period"].get(period_name, 0)
        marker = " <<" if count == max_period and max_period > 0 else ""
        print(f"    {period_name:18s} {bar(count, max_period):20s} {count:2d}{marker}")

    # temas mais reclamados
    print(f"\n  TEMAS MAIS RECLAMADOS")
    print("-" * 62)
    if temporal["top_topics"]:
        max_topic = temporal["top_topics"][0][1]
        for topic, count in temporal["top_topics"]:
            print(f"    {topic:15s} {bar(count, max_topic):20s} {count}")

    # reviews mais relevantes
    print(f"\n  TOP 5 REVIEWS MAIS RELEVANTES")
    print("-" * 62)
    scored = sorted(reviews, key=lambda r: abs(r["sentiment_score"]), reverse=True)
    for i, r in enumerate(scored[:5], 1):
        stars   = "*" * r["rating"] + "." * (5 - r["rating"])
        label   = {"positive": "POS", "negative": "NEG", "neutral": "NEU"}.get(r["sentiment"])
        anomaly = " [ANOMALIA]" if r.get("is_anomaly") else ""
        dt      = datetime.fromisoformat(r["review_date"]).strftime("%d/%m")
        print(f"\n  {i}. [{label}]{anomaly} {stars} ({dt}) - {r['author']}")
        print(f"     \"{r['text'][:100]}{'...' if len(r['text']) > 100 else ''}\"")

    print("\n" + "=" * 62 + "\n")


# ---------- main --------------------------------------------

def main(place_name: str = "Smart Fit - Unidade Centro"):
    mode = "[DEMO]" if DEMO_MODE else "[APIs reais]"
    print(f"\nMonitoramento de Reputacao {mode}")
    print(f"Estabelecimento: {place_name}\n")

    conn = init_db(DB_PATH)

    # ── coleta Google Reviews ────────────────────────────────
    if DEMO_MODE:
        reviews = get_mock_reviews(place_name)
    else:
        place_id = os.getenv("GOOGLE_PLACE_ID", "")
        if not place_id or not GOOGLE_PLACES_API_KEY:
            raise EnvironmentError("Defina GOOGLE_PLACE_ID e GOOGLE_PLACES_API_KEY no .env")
        reviews = fetch_google_reviews_api(place_id, place_name)

    # ── coleta Reclame Aqui ──────────────────────────────────
    if USE_RECLAME_AQUI:
        if DEMO_MODE:
            ra_reviews = get_mock_complaints(place_name)
        else:
            # usa o nome base da empresa (sem " - Unidade X")
            company_search = place_name.split(" - ")[0].strip()
            ra_reviews = fetch_reclame_aqui(company_search, limit=30)

        if ra_reviews:
            reviews = reviews + ra_reviews
            print(f"\nTotal combinado: {len(reviews)} itens "
                  f"(Google Reviews + Reclame Aqui)")

    if not reviews:
        print("Nenhum review encontrado.")
        return

    # ── análise ──────────────────────────────────────────────
    print(f"\nAnalisando sentimentos...")
    reviews = analyse_all_reviews(reviews)

    print(f"Detectando anomalias...")
    anomalies = detect_anomalies(reviews)

    print(f"Analisando padroes temporais...")
    temporal = temporal_analysis(reviews)

    save_results(conn, reviews, anomalies, place_name)
    print_report(reviews, anomalies, temporal, place_name)
    conn.close()


if __name__ == "__main__":
    main()
