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


def load_items():
    cfg = yaml.safe_load(WATCH_FILE.read_text(encoding="utf-8"))
    return cfg.get("items", [])


def normalize_price(text: str) -> float | None:
    m = re.search(r"€\s*([\d]{1,3}(?:[.,][\d]{2})?)", text)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def fetch_product(item):
    url = item["url"]
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # cijenu tražimo u cijelom tekstu stranice
    text = soup.get_text(" ", strip=True)
    price = normalize_price(text)

    # slika (opcijski)
    #img_url = None
    #img = soup.select_one("img")
    #if img and img.get("src"):
        #img_url = img["src"]
        #if not img_url.startswith("http"):
            #img_url = "https://bplatz.de" + img_url

        # slika - preciznije traženje preko meta taga
    img_url = None
    # Shopify stranice imaju og:image tag koji je savršen za ovo
    img_tag = soup.find("meta", property="og:image")
    
    if img_tag and img_tag.get("content"):
        img_url = img_tag["content"]
        # Ako link počinje sa // (čest slučaj na Shopify), dodaj https:
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        # Ako je link relativan (npr. /cdn/...)
        elif img_url.startswith("/"):
            img_url = "https://bplatz.de" + img_url


    return {
        "name": item["name"],
        "url": url,
        "price": price,
        "image": img_url,
    }


def send_email(name: str, url: str, old_price: float | None, new_price: float):
    user = os.environ.get("EMAIL_USER")
    pwd = os.environ.get("EMAIL_PASS")
    to_raw = os.environ.get("EMAIL_TO", "")
    tos = [t.strip() for t in to_raw.split(",") if t.strip()]
    if not (user and pwd and tos):
        print("EMAIL_* env var nisu podešene, preskačem e-mail.")
        return

    msg = EmailMessage()
    msg["Subject"] = f"[BPlatz] Nova cijena: {name} {new_price} €"
    msg["From"] = user
    msg["To"] = ", ".join(tos)
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
    items = load_items()
    old_state = load_state()  # { name: {price, url, image} }
    new_state = {}

    for item in items:
        prod = fetch_product(item)
        name = prod["name"]
        new_price = prod["price"]
        url = prod["url"]

        prev = old_state.get(name)
        old_price = prev["price"] if prev else None

        if old_price is not None and new_price is not None and old_price != new_price:
            print(f"Cijena se promijenila za {name}: {old_price} -> {new_price}")
            send_email(name, url, old_price, new_price)
        else:
            print(f"Nema promjene za {name}: {new_price} €")

        new_state[name] = {
            "price": new_price,
            "url": url,
            "image": prod["image"],
        }

    save_state(new_state)


if __name__ == "__main__":
    main()