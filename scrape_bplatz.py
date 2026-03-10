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
    # Prvo pokušaj sa € simbolom
    m = re.search(r"€\s*([\d]{1,3}(?:[.,][\d]{2})?)", text)
    if m:
        return float(m.group(1).replace(".", "").replace(",", "."))
    
    # Ako nema €, pokušaj sa brojevima (format: "23,89")
    m = re.search(r"([\d]{1,3}(?:[.,][\d]{2})?)", text)
    if m:
        return float(m.group(1).replace(".", "").replace(",", "."))
    
    return None


def fetch_product(item):
    url = item["url"]
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # CIJENA - traži hdt-price element (aktivna cijena)
    price = None
    price_elem = soup.find("hdt-price", class_="hdt-price")
    if price_elem:
        price_text = price_elem.get_text(strip=True)
        if price_text:
            price = normalize_price(price_text)
    
    # Ako nije pronađena, pokušaj og:price:amount meta tag
    if not price:
        meta_price = soup.find("meta", property="og:price:amount")
        if meta_price:
            price = normalize_price(meta_price.get("content", ""))
    
    # STARA CIJENA - traži hdt-compare-at-price i onda hdt-money span
    old_price = None
    compare_elem = soup.find("hdt-compare-at-price")
    if compare_elem:
        # Traži hdt-money span koji sadrži cijenu
        money_elem = compare_elem.find("span", class_="hdt-money")
        if money_elem:
            old_price_text = money_elem.get_text(strip=True)
            # Ignoriraj prazne stringove
            if old_price_text:
                old_price = normalize_price(old_price_text)
    
    # Ako je old_price ista kao price, nema popusta - postavi na null
    if old_price and price and old_price == price:
        old_price = None

    # slika - prvo pokušaj og:image, zatim product image, zatim bilo koja slika
    img_url = None
    
    # 1. Pokušaj og:image (Shopify meta tag)
    img_tag = soup.find("meta", property="og:image")
    if img_tag and img_tag.get("content"):
        img_url = img_tag["content"]
    
    # 2. Ako nije pronađena, pokušaj direktno img tag sa src
    if not img_url:
        img = soup.find("img")
        if img and img.get("src"):
            img_url = img["src"]
    
    # 3. Pokušaj data-src (lazy loading slike)
    if not img_url:
        img = soup.find("img", {"data-src": True})
        if img and img.get("data-src"):
            img_url = img["data-src"]
    
    # Normalizuj URL slike - dinamički hvata domenu
    if img_url:
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("http://"):
            img_url = img_url.replace("http://", "https://")
        elif not img_url.startswith("http"):
            # Dinamički hvata domenu umjesto fiksnog bplatz.de
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            base_url = f"https://{parsed_url.netloc}"
            img_url = base_url + img_url

    return {
        "name": item["name"],
        "url": url,
        "price": price,
        "image": img_url,
        "old_price": old_price,
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
    old_state = load_state()
    new_state = {}

    for item in items:
        prod = fetch_product(item)
        name = prod["name"]
        new_price = prod["price"]
        url = prod["url"]
        scraped_old_price = prod.get("old_price")

        prev = old_state.get(name)
        current_price = prev["price"] if prev else None
        previous_old_price = prev.get("old_price") if prev else None
        
        # Koristi scraped_old_price ako postoji, inače prethodnu
        old_price = scraped_old_price if scraped_old_price else previous_old_price

        if current_price is not None and new_price is not None and current_price != new_price:
            print(f"Cijena se promijenila za {name}: {current_price} -> {new_price}")
            send_email(name, url, current_price, new_price)
            old_price = current_price
        elif current_price is None and scraped_old_price and scraped_old_price != new_price:
            # Prvi put - koristi old_price sa stranice SAMO ako je različita od nove
            old_price = scraped_old_price
            print(f"Prvi put - {name}: nova {new_price} €, stara {scraped_old_price} €")
        else:
            print(f"Nema promjene za {name}: {new_price} €")

        new_state[name] = {
            "price": new_price,
            "url": url,
            "image": prod["image"],
            "old_price": old_price,
        }

    save_state(new_state)


if __name__ == "__main__":
    main()