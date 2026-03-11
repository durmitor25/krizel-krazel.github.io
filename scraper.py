import re
import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
import yaml

# Selenium import - opcionalan
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

STATE_FILE = Path("prices.json")
WATCH_FILE = Path("watch.yml")
SOURCES_FILE = Path("sources.yml")


def load_items():
    cfg = yaml.safe_load(WATCH_FILE.read_text(encoding="utf-8"))
    return cfg.get("items", [])


def load_sources():
    if not SOURCES_FILE.exists():
        return {}
    cfg = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8"))
    return cfg.get("sources", {})


def fetch_with_selenium(url, timeout=10):
    """Uzmi HTML sa JavaScript sajta koristeći Selenium"""
    if not SELENIUM_AVAILABLE:
        print(f"❌ Selenium nije instaliran! Instaliraj: pip install selenium")
        return None
    
    try:
        options = Options()
        options.add_argument("--headless")  # Bez GUI
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        driver = webdriver.Chrome(options=options)
        driver.get(url)
        
        # Čekaj da se slike učitaju
        try:
            WebDriverWait(driver, timeout).until(
                EC.presence_of_all_elements_located((By.TAG_NAME, "img"))
            )
        except:
            pass  # Timeout je OK, nastavi sa onim što ima
        
        html = driver.page_source
        driver.quit()
        return html
    except Exception as e:
        print(f"❌ Selenium greška za {url}: {e}")
        return None


def get_source_config(url, sources_config):
    """Pronađi konfiguraciju izvora za dati URL"""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    # Ukloni 'www.' ako postoji
    if domain.startswith("www."):
        domain = domain[4:]
    
    return sources_config.get(domain, sources_config.get("default", {}))


def normalize_price(text: str) -> float | None:
    """Normalizuj cijenu iz teksta"""
    if not text:
        return None
    
    # Prvo pokušaj sa € simbolom
    m = re.search(r"€\s*([\d]{1,3}(?:[.,][\d]{2})?)", text)
    if m:
        return float(m.group(1).replace(".", "").replace(",", "."))
    
    # Ako nema €, pokušaj sa brojevima (format: "23,89")
    m = re.search(r"([\d]{1,3}(?:[.,][\d]{2})?)", text)
    if m:
        return float(m.group(1).replace(".", "").replace(",", "."))
    
    return None


def extract_price(soup, selectors, item_name="", debug=False):
    """Ekstrakuj cijenu prema definiranim selectorima"""
    price = None
    
    for selector in selectors:
        selector_type = selector.get("type", "").lower()
        
        if debug:
            print(f"  Price pokušaj: {selector_type}")
        
        if selector_type == "tag":
            tag = selector.get("tag")
            class_name = selector.get("class")
            class_contains = selector.get("class_contains")
            
            if class_name:
                elem = soup.find(tag, class_=class_name)
            elif class_contains:
                elem = soup.find(tag, class_=lambda x: x and class_contains.lower() in x.lower())
            else:
                elem = soup.find(tag)
            
            if elem:
                price_text = elem.get_text(strip=True)
                if debug:
                    print(f"    Pronađeno: {price_text[:50]}")
                if price_text:
                    price = normalize_price(price_text)
                    if price:
                        if debug:
                            print(f"    ✓ Cijena: {price}")
                        break
        
        elif selector_type == "css_selector":
            # CSS selector support
            css = selector.get("selector")
            selectors_list = [s.strip() for s in css.split(",")]
            
            for css_sel in selectors_list:
                try:
                    elem = soup.select_one(css_sel)
                    if elem:
                        price_text = elem.get_text(strip=True)
                        if debug:
                            print(f"    CSS '{css_sel}': {price_text[:50]}")
                        if price_text:
                            price = normalize_price(price_text)
                            if price:
                                if debug:
                                    print(f"    ✓ Cijena: {price}")
                                break
                except:
                    pass
            
            if price:
                break
        
        elif selector_type == "meta":
            prop = selector.get("property")
            elem = soup.find("meta", property=prop)
            if elem and elem.get("content"):
                if debug:
                    print(f"    Meta: {elem.get('content')[:50]}")
                price = normalize_price(elem.get("content", ""))
                if price:
                    if debug:
                        print(f"    ✓ Cijena: {price}")
                    break
        
        elif selector_type == "span_with_euro":
            # Pokušaj bilo koji element sa € simbolom
            if debug:
                print(f"    Tražim sve € u stranici...")
            
            for elem in soup.find_all():
                text = elem.get_text(strip=True)
                if "€" in text and len(text) < 50 and len(text) > 2:
                    if debug:
                        print(f"      Pronađeno: '{text}'")
                    temp_price = normalize_price(text)
                    if temp_price and 1 < temp_price < 500:
                        if debug:
                            print(f"    ✓ Cijena: {temp_price}")
                        price = temp_price
                        break
            if price:
                break
    
    return price


def extract_image(soup, selectors, url, debug=False):
    """Ekstrakuj sliku prema definiranim selectorima"""
    img_url = None
    
    def is_valid_image(url_str):
        """Provjeri da li je slika valida (ne watermark/logo)"""
        if not url_str:
            return False
        url_lower = url_str.lower()
        return not any(x in url_lower for x in ["watermark", "logo", "icon", "placeholder"])
    
    for selector in selectors:
        selector_type = selector.get("type", "").lower()
        
        if debug:
            print(f"  Pokušavam: {selector_type}")
        
        if selector_type == "meta":
            prop = selector.get("property")
            elem = soup.find("meta", property=prop)
            if elem and elem.get("content"):
                potential_url = elem["content"]
                if is_valid_image(potential_url):
                    if debug:
                        print(f"    ✓ Pronađena: {potential_url}")
                    img_url = potential_url
                    break
        
        elif selector_type == "tag":
            tag = selector.get("tag")
            class_name = selector.get("class")
            class_contains = selector.get("class_contains")
            attr = selector.get("attr")
            
            if class_name:
                elems = soup.find_all(tag, class_=class_name)
            elif class_contains:
                elems = soup.find_all(tag, class_=lambda x: x and class_contains.lower() in x.lower())
            else:
                elems = soup.find_all(tag)
            
            if debug:
                print(f"    Pronađeno {len(elems)} elementa")
            
            for elem in elems:
                if attr:
                    potential_url = elem.get(attr)
                else:
                    potential_url = elem.get("src") or elem.get("data-src") or elem.get("href")
                
                if potential_url and debug:
                    print(f"      Pokušavam: {potential_url[:80]}")
                
                if is_valid_image(potential_url):
                    if debug:
                        print(f"    ✓ Pronađena: {potential_url[:80]}")
                    img_url = potential_url
                    break
        
        if img_url:
            break
    
    # Normalizuj URL slike
    if img_url:
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("http://"):
            img_url = img_url.replace("http://", "https://")
        elif not img_url.startswith("http"):
            parsed_url = urlparse(url)
            base_url = f"https://{parsed_url.netloc}"
            img_url = base_url + img_url
    
    return img_url


def fetch_product(item, sources_config):
    """Uzmi proizvod sa sajta koristeći konfiguraciju izvora"""
    url = item["url"]
    
    # Debug mode za parfum-zentrum.de
    debug = "parfum-zentrum" in url.lower()
    use_selenium = "parfum-zentrum" in url.lower()  # Koristi Selenium za ovaj sajt
    
    html = None
    
    # Pokušaj sa Selenium za JavaScript sajte
    if use_selenium and SELENIUM_AVAILABLE:
        print(f"🌐 Selenium: {item['name']}")
        html = fetch_with_selenium(url)
    
    # Pokušaj sa regular requests ako Selenium nije dostupan ili nije potreban
    if not html:
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            print(f"❌ Greška pri učitavanju {url}: {e}")
            return None
    
    soup = BeautifulSoup(html, "html.parser")
    source_config = get_source_config(url, sources_config)
    
    # Ekstrakuj cijenu
    price_selectors = source_config.get("price_selectors", [])
    price = extract_price(soup, price_selectors, item.get("name", ""), debug=debug)
    
    # Ekstrakuj staru cijenu
    old_price = None
    old_price_selectors = source_config.get("old_price_selectors", [])
    old_price = extract_price(soup, old_price_selectors, item.get("name", ""))
    
    # Ako je old_price ista kao price, nema popusta
    if old_price and price and old_price == price:
        old_price = None
    
    # Ekstrakuj sliku
    image_selectors = source_config.get("image_selectors", [])
    if debug:
        print(f"\n🔍 DEBUG: {item['name']}")
    img_url = extract_image(soup, image_selectors, url, debug=debug)
    
    return {
        "name": item["name"],
        "url": url,
        "price": price,
        "image": img_url,
        "old_price": old_price,
    }


def send_email(name: str, url: str, old_price: float | None, new_price: float):
    """Pošalji email o promjeni cijene"""
    user = os.environ.get("EMAIL_USER")
    pwd = os.environ.get("EMAIL_PASS")
    to_raw = os.environ.get("EMAIL_TO", "")
    tos = [t.strip() for t in to_raw.split(",") if t.strip()]
    
    if not (user and pwd and tos):
        print(f"EMAIL nije podešen, preskačem email za {name}")
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

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(user, pwd)
            smtp.send_message(msg)
        print(f"✓ Email poslан za {name}")
    except Exception as e:
        print(f"✗ Email greška za {name}: {e}")


def load_state():
    """Učitaj prethodno spravljene cijene"""
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state):
    """Spremi cijene u JSON"""
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    items = load_items()
    sources_config = load_sources()
    old_state = load_state()
    new_state = {}

    for item in items:
        prod = fetch_product(item, sources_config)
        
        if not prod:
            print(f"❌ Nije moguće učitati {item['name']}")
            continue
        
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
            print(f"📍 Cijena se promijenila za {name}: {current_price} → {new_price}")
            send_email(name, url, current_price, new_price)
            old_price = current_price
        elif current_price is None and scraped_old_price and scraped_old_price != new_price:
            print(f"✨ Novi proizvod - {name}: {new_price} € (stara: {scraped_old_price} €)")
            old_price = scraped_old_price
        else:
            print(f"✓ {name}: {new_price} €")

        new_state[name] = {
            "price": new_price,
            "url": url,
            "image": prod["image"],
            "old_price": old_price,
        }

    save_state(new_state)
    print(f"\n✅ Skript završen! Spravljeno {len(new_state)} proizvoda.")


if __name__ == "__main__":
    main()