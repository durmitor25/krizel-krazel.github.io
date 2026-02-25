import re
import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import yaml  # pip install pyyaml

STATE_FILE = Path("prices.json")
WATCH_FILE = Path("watch.yml")

def load_config():
    cfg = yaml.safe_load(WATCH_FILE.read_text(encoding="utf-8"))
    search_url = cfg["search_url"]
    watch_names = [item["name"] for item in cfg.get("items", [])]
    return search_url, watch_names

def normalize_price(s: str) -> float | None:
    m = re.search(r"€\s*([\d]{1,3}(?:[.,][\d]{2})?)", s)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))

def fetch_products(search_url: str):
    resp = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    products = []
    for a in soup.select("a[href*='/products/']"):
        name = a.get_text(strip=True)
        if not name:
            continue
        href = a["href"]
        if not href.startswith("http"):
            href = "https://bplatz.de" + href

        card = a.find_parent("article") or a.find_parent("div")
        text = card.get_text(" ", strip=True) if card else a.get_text(" ", strip=True)
        price = normalize_price(text)
        if price is None:
            continue

        products.append({"name": name, "url": href, "price": price})

    return products

def send_email(name: str, url: str, old_price: float | None, new_price: float):
    user = os.environ.get("EMAIL_USER")
    pwd = os.environ.get("EMAIL_PASS")
    to = os.environ.get("EMAIL_TO")
    if not (user and pwd and to):
        print("EMAIL_* env var nisu podešene, preskačem e-mail.")
        return

    msg = EmailMessage()
    msg["Subject"] = f"[BPlatz] Nova cijena: {name} {new_price} €"
    msg["From"] = user
    msg["To"] = to
    body = (
        f"Proizvod: {name}\n"
        f"URL: {url}\n"
        f"Stara cijena: {old_price} €\n"
        f"Nova cijena: {new_price} €\n"
    )
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, pwd)
        smtp.send_message(msg)

def load_state():
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    search_url, watch_names = load_config()
    old_state = load_state()  # { name: {price, url} }
    products = fetch_products(search_url)
    by_name = {p["name"]: p for p in products}

    new_state = {}
    for name in watch_names:
        p = by_name.get(name)
        if not p:
            print(f"[WARN] Nema proizvoda na search stranici: {name}")
            continue

        new_price = p["price"]
        url = p["url"]

        prev = old_state.get(name)
        old_price = prev["price"] if prev else None

        if old_price is not None and old_price != new_price:
            print(f"Cijena se promijenila za {name}: {old_price} -> {new_price}")
            send_email(name, url, old_price, new_price)
        else:
            print(f"Nema promjene za {name}: {new_price} €")

        new_state[name] = {"price": new_price, "url": url}

    save_state(new_state)

if __name__ == "__main__":
    main()