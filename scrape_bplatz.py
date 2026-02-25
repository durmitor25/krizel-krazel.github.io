import re, json, requests

URL = "https://bplatz.de/products/afnan-9-pm-eau-de-parfum-100ml?variant=54336510722316"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def parse_prices(html: str):
    # 1) pokušaj naći "Regulärer Preis ... Verkaufspreis ..."
    m_disc = re.search(
        r"Regulärer Preis\s*€\s*([\d\.,]+).*?Verkaufspreis\s*€\s*([\d\.,]+)",
        html,
        flags=re.DOTALL,
    )
    if m_disc:
        old_p = float(m_disc[1].replace(".", "").replace(",", "."))
        new_p = float(m_disc[2].replace(".", "").replace(",", "."))
        return old_p, new_p

    # 2) ako nema regularne cijene, uzmi prvu "Verkaufspreis €xx,xx"
    m_simple = re.search(r"Verkaufspreis[^€]*€\s*([\d\.,]+)", html, flags=re.DOTALL)
    if m_simple:
        new_p = float(m_simple[1].replace(".", "").replace(",", "."))
        return None, new_p

    # 3) fallback: prva € cijena na stranici
    m_any = re.search(r"€\s*([\d]{1,3}(?:[.,][\d]{2})?)", html)
    if m_any:
        new_p = float(m_any.group(1).replace(".", "").replace(",", "."))
        return None, new_p

    return None, None
r = requests.get(URL, headers=HEADERS, timeout=30)
r.raise_for_status()
old_price, new_price = parse_prices(r.text)

data = {
    "url": URL,
    "regular_price": old_price,
    "current_price": new_price,
}

with open("prices.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
