# reclame_aqui.py
# Coleta reclamações do Reclame Aqui para um estabelecimento
# Requer: pip install requests beautifulsoup4

import re
import json
import time
import random
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

# headers que imitam um navegador real
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "application/json, text/html, */*",
    "Referer": "https://www.reclameaqui.com.br/",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ---------- busca o ID interno da empresa -------------------

def search_company(company_name: str) -> dict | None:
    """Busca a empresa no Reclame Aqui e retorna {id, name, slug}."""
    url = "https://iosearch.reclameaqui.com.br/raichu-io-site-search-v1/query/companyByName/1/0"
    try:
        resp = SESSION.get(url, params={"name": company_name}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        companies = data.get("hits", {}).get("hits", [])
        if not companies:
            return None
        src = companies[0].get("_source", {})
        return {
            "id":   src.get("id"),
            "name": src.get("fantasyName") or src.get("name"),
            "slug": src.get("slug"),
        }
    except Exception as e:
        print(f"  [busca] Erro ao procurar empresa: {e}")
        return None


# ---------- coleta reclamações via API interna --------------

def fetch_complaints_api(company_id: str, limit: int = 30) -> list[dict]:
    """Usa a API interna do Reclame Aqui para buscar reclamações."""
    url = (
        f"https://iosearch.reclameaqui.com.br/raichu-io-site-search-v1/"
        f"query/companyComplains/{limit}/0"
    )
    params = {"companyId": company_id, "status": "ALL"}
    try:
        resp = SESSION.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("hits", {}).get("hits", [])
    except Exception as e:
        print(f"  [api] Falha na API interna: {e}")
        return []


# ---------- fallback: scraping da página HTML ---------------

def fetch_complaints_html(slug: str, limit: int = 20) -> list[dict]:
    """Fallback: raspa a página de reclamações diretamente."""
    url = f"https://www.reclameaqui.com.br/{slug}/lista-reclamacoes/"
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # tenta extrair JSON embutido no __NEXT_DATA__
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script:
            payload = json.loads(script.string)
            complains = (
                payload.get("props", {})
                       .get("pageProps", {})
                       .get("complains", {})
                       .get("data", {})
                       .get("complains", {})
                       .get("data", [])
            )
            return complains[:limit]
    except Exception as e:
        print(f"  [html] Fallback HTML falhou: {e}")
    return []


# ---------- normaliza para o formato padrão do sistema ------

def normalize(raw: dict, place_name: str, source_id: str) -> dict | None:
    """Converte um item bruto do RA para o formato reviews do sistema."""
    try:
        # suporte aos dois formatos (API e HTML)
        src = raw.get("_source", raw)

        text = src.get("description") or src.get("complain") or ""
        if not text:
            return None

        title  = src.get("title", "")
        status = src.get("status", "")          # RESPONDIDA, NAO_RESPONDIDA, etc.

        # data — aceita timestamp unix ou string ISO
        raw_date = src.get("complainDate") or src.get("date") or ""
        if isinstance(raw_date, (int, float)):
            dt = datetime.fromtimestamp(raw_date / 1000, tz=timezone.utc)
        elif raw_date:
            raw_date = re.sub(r"\.\d+", "", str(raw_date))  # remove microssegundos
            try:
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        complain_id = str(src.get("id") or src.get("complaintId") or hash(text))

        return {
            "id":          f"ra_{source_id}_{complain_id}",
            "place_id":    f"ra_{source_id}",
            "place_name":  place_name,
            "author":      src.get("name") or src.get("userName") or "Anonimo",
            "rating":      1,          # reclamações no RA sempre contam como negativo
            "text":        f"{title}. {text}".strip(". ") if title else text,
            "review_date": dt.isoformat(),
            "day_of_week": dt.weekday(),
            "hour_of_day": dt.hour,
            "source":      "reclame_aqui",
            "ra_status":   status,
        }
    except Exception:
        return None


# ---------- função principal --------------------------------

def fetch_reclame_aqui(company_name: str, limit: int = 30) -> list[dict]:
    """
    Busca reclamações do Reclame Aqui para a empresa informada.
    Retorna lista no formato padrão do sistema (mesmo schema de reviews).
    """
    print(f"\n[Reclame Aqui] Buscando empresa: '{company_name}'...")

    company = search_company(company_name)
    if not company:
        print(f"  Empresa nao encontrada. Verifique o nome exato no Reclame Aqui.")
        return []

    print(f"  Encontrada: {company['name']} (id={company['id']}, slug={company['slug']})")

    # tenta API primeiro, depois fallback HTML
    raw_items = fetch_complaints_api(company["id"], limit)
    if not raw_items:
        print("  Tentando fallback HTML...")
        time.sleep(1)
        raw_items = fetch_complaints_html(company["slug"], limit)

    if not raw_items:
        print("  Nenhuma reclamacao obtida.")
        return []

    reviews = []
    for item in raw_items:
        normalized = normalize(item, company["name"], company["id"])
        if normalized:
            reviews.append(normalized)
        time.sleep(random.uniform(0.1, 0.3))  # evita bloqueio por rate limit

    print(f"  {len(reviews)} reclamacoes coletadas do Reclame Aqui.")
    return reviews


# ---------- mock para demo sem internet ---------------------

MOCK_RA_COMPLAINTS = [
    ("Cobrança indevida após cancelamento",
     "Cancelei meu plano há 30 dias e continuaram debitando no cartão. Liguei 3 vezes e ninguém resolve.",
     -45),
    ("Equipamentos quebrados há semanas",
     "A esteira e dois aparelhos de musculação estão quebrados há mais de 20 dias sem previsão de conserto.",
     -38),
    ("Atendimento péssimo na recepção",
     "Fui mal atendida pela funcionária da recepção, que foi grosseira e se recusou a ajudar.",
     -30),
    ("Vestiário sem condições de uso",
     "Os chuveiros estão com pressão baixíssima e o vestiário está sempre com mau cheiro. Inadmissível.",
     -22),
    ("Cancelamento negado e multa abusiva",
     "Tentei cancelar dentro do prazo e querem cobrar multa de 3 meses. Cláusula abusiva, vou ao Procon.",
     -18),
    ("App não funciona faz dias",
     "O aplicativo trava na hora de marcar aula. Já desinstalei e reinstalei várias vezes. Sem solução.",
     -12),
    ("Lotação excessiva no horário de pico",
     "Impossível treinar entre 18h e 20h. Não tem equipamento disponível e a academia não limita acesso.",
     -8),
    ("Sem resposta do SAC há 15 dias",
     "Enviei 4 e-mails e abri 2 chamados. Nenhuma resposta. Pago mensalidade e não tenho suporte.",
     -5),
]


def get_mock_complaints(place_name: str = "Smart Fit") -> list[dict]:
    """Retorna reclamações simuladas do Reclame Aqui para demo."""
    now = datetime.now(timezone.utc)
    reviews = []
    for i, (title, text, days_ago) in enumerate(MOCK_RA_COMPLAINTS):
        dt = now + timedelta(days=days_ago, hours=9 + i % 6)
        reviews.append({
            "id":          f"ra_mock_{i+1:04d}",
            "place_id":    "ra_mock_001",
            "place_name":  place_name,
            "author":      f"Usuario_RA_{1000+i}",
            "rating":      1,
            "text":        f"{title}. {text}",
            "review_date": dt.isoformat(),
            "day_of_week": dt.weekday(),
            "hour_of_day": dt.hour,
            "source":      "reclame_aqui",
            "ra_status":   "NAO_RESPONDIDA" if i % 3 != 0 else "RESPONDIDA",
        })
    print(f"[DEMO Reclame Aqui] {len(reviews)} reclamacoes simuladas carregadas.")
    return reviews


# ---------- teste direto ------------------------------------

if __name__ == "__main__":
    import sys

    company = sys.argv[1] if len(sys.argv) > 1 else "Smart Fit"
    demo    = "--demo" in sys.argv

    if demo:
        results = get_mock_complaints(company)
    else:
        results = fetch_reclame_aqui(company, limit=20)

    print(f"\nResultado: {len(results)} reclamacoes")
    for r in results[:3]:
        print(f"\n  [{r['ra_status']}] {r['author']} - {r['review_date'][:10]}")
        print(f"  \"{r['text'][:120]}\"")
