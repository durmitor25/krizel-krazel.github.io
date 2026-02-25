import re, json, requests, os, smtplib
from email.message import EmailMessage
from pathlib import Path

URL = "https://bplatz.de/products/afnan-9-pm-eau-de-parfum-100ml?variant=54336510722316"
HEADERS = {"User-Agent": "Mozilla/5.0"}
STATE_FILE = Path("prices.json")

def parse_prices(html: str):
    m_disc = re.search(
        r"Regulärer Preis\s*€\s*([\d\.,]+).*?Verkaufspreis\s*€\s*([\d\.,]+)",
        html, flags=re.DOTALL
    )
    if m_disc:
        old_p = float(m_disc[1].replace(".", "").replace(",", "."))
        new_p = float(m_disc[2].replace(".", "").replace(",", "."))
        return old_p, new_p
    m_simple = re.search(r"Verkaufspreis[^€]*€\s*([\d\.,]+)", html, flags=re.DOTALL)
    if m_simple:
        new_p = float(m_simple[1].replace(".", "").replace(",", "."))
        return None, new_p
    m_any = re.search(r"€\s*([\d]{1,3}(?:[.,][\d]{2})?)", html)
    if m_any:
        new_p = float(m_any.group(1).replace(".", "").replace(",", "."))
        return None, new_p
    return None, None

def send_email(old_price, new_price):
    user = os.environ.get("EMAIL_USER")
    pwd = os.environ.get("EMAIL_PASS")
    to  = os.environ.get("EMAIL_TO")
    if not (user and pwd and to):
        print("EMAIL_* env var nisu podešene, preskačem e-mail.")
        return

    msg = EmailMessage()
    msg["Subject"] = f"[BPlatz] Nova cijena: {new_price} €"
    msg["From"] = user
    msg["To"] = to
    body = (
        f"Proizvod: {URL}\n"
        f"Stara cijena: {old_price} €\n"
        f"Nova cijena: {new_price} €\n"
    )
    msg.set_content(body)

    # primjer za Gmail SMTP s app passwordom
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, pwd)
        smtp.send_message(msg)

# --- glavni dio ---
resp = requests.get(URL, headers=HEADERS, timeout=30)
resp.raise_for_status()
old_p, new_p = parse_prices(resp.text)

new_state = {
    "url": URL,
    "regular_price": old_p,
    "current_price": new_p,
}

old_state = None
if STATE_FILE.exists():
    old_state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

# ako se promijenila current_price -> pošalji mail
if old_state and old_state.get("current_price") != new_p:
    print("Cijena se promijenila, šaljem e-mail...")
    send_email(old_state.get("current_price"), new_p)
else:
    print("Nema promjene cijene.")

STATE_FILE.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")