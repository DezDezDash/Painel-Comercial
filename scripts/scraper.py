#!/usr/bin/env python3
"""
Scraper – Trivia F-Loja › Painel de Vendas
Extrai 12 combinações (4 lojas × 3 filtros "Por").
Valor líquido = coluna "Valor" − coluna "Dev."
"""

import os
import json
import re
import time
from datetime import date
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

LOGIN_URL  = "http://app.comercialdezdez.com.br:8080/loja/publico/login.jsf"
ADMIN_URL  = "http://app.comercialdezdez.com.br:8080/loja/admin/default.jsf"

SITE_LOGIN = os.environ.get("SITE_LOGIN", "")
SITE_SENHA = os.environ.get("SITE_SENHA", "")

LOJAS = {
    "CAM": "Vendedor Camaragibe",
    "CAV": "Vendedor Cavaleiro",
    "SLM": "Vendedor São Lourenço",
    "CAX": "Vendedor Caxangá",
}

POR_OPTIONS = ["Linha de Produto", "Fornecedor", "Vendedor"]
OUTPUT_FILE = Path(__file__).parent / "scraped_data.json"


def make_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=pt-BR")
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    except Exception:
        driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    return driver


def wait_ajax(driver, timeout=15):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script(
                "return document.readyState === 'complete' && "
                "(typeof $ === 'undefined' || $.active === 0) && "
                "(typeof PrimeFaces === 'undefined' || PrimeFaces.ajax.Queue.isEmpty())"
            )
        )
    except Exception:
        time.sleep(2)


def screenshot(driver, name):
    try:
        driver.save_screenshot(f"/tmp/debug_{name}.png")
    except Exception:
        pass


def select_pf_dropdown(driver, option_text):
    """Select option_text in whichever PrimeFaces selectOneMenu contains it."""

    # Strategy 1: directly set the hidden <select> whose options include option_text
    for sel_el in driver.find_elements(By.TAG_NAME, "select"):
        try:
            s = Select(sel_el)
            opts = {o.text.strip(): o.get_attribute("value") for o in s.options}
            if option_text not in opts:
                continue
            opt_val = opts[option_text]
            driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                sel_el, opt_val,
            )
            wait_ajax(driver)
            time.sleep(0.3)
            print(f"    [select] '{option_text}' via hidden <select>")
            return True
        except Exception:
            continue

    # Strategy 2: click PrimeFaces trigger → find item in open panel
    for menu in driver.find_elements(By.CSS_SELECTOR, "div.ui-selectonemenu"):
        try:
            trigger = menu.find_element(By.CSS_SELECTOR, ".ui-selectonemenu-trigger")
            driver.execute_script("arguments[0].click();", trigger)
            time.sleep(0.5)
            try:
                panel = WebDriverWait(driver, 5).until(
                    EC.visibility_of_element_located(
                        (By.CSS_SELECTOR, ".ui-selectonemenu-panel:not([style*='display: none'])")
                    )
                )
                for item in panel.find_elements(By.CSS_SELECTOR, "li.ui-selectonemenu-item"):
                    if item.text.strip() == option_text:
                        driver.execute_script("arguments[0].click();", item)
                        wait_ajax(driver)
                        print(f"    [select] '{option_text}' via PrimeFaces panel")
                        return True
                # option not in this panel — close it and continue
                driver.execute_script("arguments[0].click();", trigger)
                time.sleep(0.2)
            except Exception:
                pass
        except Exception:
            continue

    print(f"    [select] FALHOU para '{option_text}'")
    return False


def set_date_field(driver, date_str, is_end=False):
    try:
        date_inputs = driver.find_elements(By.XPATH,
            "//input[@type='text'][contains(@id,'period') or contains(@id,'data') "
            "or contains(@id,'date') or contains(@id,'inicio') or contains(@id,'fim')]")
        if not date_inputs:
            date_inputs = [i for i in driver.find_elements(By.XPATH, "//input[@type='text']")
                           if re.match(r"\d{2}/\d{2}/\d{4}", i.get_attribute("value") or "")]
        idx = 1 if is_end else 0
        if len(date_inputs) > idx:
            driver.execute_script(
                "arguments[0].value=arguments[1];"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                date_inputs[idx], date_str)
            return True
    except Exception:
        pass
    return False


def parse_br_float(text):
    t = re.sub(r"\.(?=\d{3}(?:[,\s]|$))", "", text.strip().replace(" ", "")).replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return 0.0


def extract_table(driver):
    wait_ajax(driver)
    time.sleep(2)
    results = {}
    try:
        for tbl in driver.find_elements(By.XPATH, "//table[.//tr[td]]"):
            rows = tbl.find_elements(By.TAG_NAME, "tr")
            if len(rows) < 2:
                continue
            headers = [th.text.strip() for th in rows[0].find_elements(By.XPATH, ".//th | .//td")]
            idx_valor, idx_dev = None, None
            for i, h in enumerate(headers):
                hl = h.lower()
                if "valor" in hl and idx_valor is None:
                    idx_valor = i
                elif "dev" in hl and idx_dev is None:
                    idx_dev = i
            if idx_valor is None:
                continue
            for row in rows[1:]:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < 2:
                    continue
                name = cells[0].text.strip()
                # skip blank, total rows (handle "Total", "Total:", "TOTAL", etc.)
                if not name or name.upper().rstrip(":").strip() == "TOTAL":
                    continue
                try:
                    valor = parse_br_float(cells[idx_valor].text) if idx_valor < len(cells) else 0.0
                    dev   = parse_br_float(cells[idx_dev].text) if idx_dev is not None and idx_dev < len(cells) else 0.0
                    net   = round(valor - dev, 2)
                    if net != 0:
                        results[name] = net
                except Exception:
                    continue
            if results:
                break
    except Exception as e:
        print(f"    [extract_table] {e}")
    return results


def login(driver):
    print("Acessando login...")
    driver.get(LOGIN_URL)
    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.XPATH, "//input[@type='password']")))
    time.sleep(1)
    user_field = None
    for xpath in ["//input[@type='text'][1]",
                  "//input[contains(@id,'login') or contains(@id,'user') or contains(@id,'usuario')]",
                  "//input[@name='j_username']"]:
        try:
            user_field = driver.find_element(By.XPATH, xpath)
            break
        except Exception:
            continue
    pass_field = driver.find_element(By.XPATH, "//input[@type='password']")
    if not user_field:
        raise RuntimeError("Campo de usuário não encontrado")
    user_field.clear()
    user_field.send_keys(SITE_LOGIN)
    pass_field.clear()
    pass_field.send_keys(SITE_SENHA)
    driver.find_element(By.XPATH,
        "//button[@type='submit'] | //input[@type='submit']"
        " | //button[contains(.,'Entrar') or contains(.,'Login') or contains(.,'Acessar')]").click()
    wait_ajax(driver)
    time.sleep(3)
    if "login" in driver.current_url.lower():
        screenshot(driver, "login_failed")
        raise RuntimeError(f"Login falhou — URL: {driver.current_url}")
    print(f"  Login OK → {driver.current_url}")


def navigate_to_painel_vendas(driver):
    driver.get(ADMIN_URL)
    wait_ajax(driver)
    time.sleep(2)
    for xpath in [
        "//*[contains(text(),'Painel de Vendas') or contains(@title,'Painel de Vendas')][not(contains(@class,'ui-tabmenuitem-active'))]",
        "//*[contains(text(),'Painel de Vendas')]"]:
        try:
            driver.execute_script("arguments[0].click();", driver.find_element(By.XPATH, xpath))
            wait_ajax(driver)
            time.sleep(2)
            print("  Painel de Vendas aberto")
            return
        except Exception:
            continue
    try:
        driver.find_element(By.XPATH, "//*[contains(text(),'Pedido')]").click()
        time.sleep(1)
        driver.find_element(By.XPATH, "//*[contains(text(),'Painel de Vendas')]").click()
        wait_ajax(driver)
        time.sleep(2)
        print("  Painel de Vendas aberto via menu Pedido")
    except Exception as e:
        print(f"  AVISO: {e}")
        screenshot(driver, "nav_failed")


def run_extraction(driver, loja_code, loja_label, por_option, start_str, end_str):
    print(f"  [{loja_code}] Por: {por_option} ...")
    try:
        select_pf_dropdown(driver, loja_label)
        time.sleep(0.5)
        select_pf_dropdown(driver, por_option)
        time.sleep(0.5)
        set_date_field(driver, start_str, is_end=False)
        set_date_field(driver, end_str,   is_end=True)
        time.sleep(0.3)
        btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(.,'Pesquisar')] | //a[contains(.,'Pesquisar')]")))
        driver.execute_script("arguments[0].click();", btn)
        wait_ajax(driver)
        time.sleep(3)
        data = extract_table(driver)
        print(f"    → {len(data)} registros")
        return data
    except Exception as e:
        print(f"    ERRO: {e}")
        screenshot(driver, f"{loja_code}_{por_option.replace(' ','_')}")
        return {}


def main():
    if not SITE_LOGIN or not SITE_SENHA:
        raise RuntimeError("SITE_LOGIN e SITE_SENHA não definidos nas variáveis de ambiente.")
    today     = date.today()
    start_str = f"01/{today.month:02d}/{today.year}"
    end_str   = f"{today.day:02d}/{today.month:02d}/{today.year}"
    print(f"Período: {start_str} → {end_str}")
    output = {"date": today.isoformat(), "day": today.day,
              "month_key": f"{today.year}-{today.month:02d}-01", "extractions": {}}
    driver = make_driver()
    try:
        login(driver)
        navigate_to_painel_vendas(driver)
        for loja_code, loja_label in LOJAS.items():
            print(f"\nLoja: {loja_code} ({loja_label})")
            output["extractions"][loja_code] = {}
            for por in POR_OPTIONS:
                output["extractions"][loja_code][por] = run_extraction(
                    driver, loja_code, loja_label, por, start_str, end_str)
    finally:
        driver.quit()
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSalvo em: {OUTPUT_FILE}")
    for loja in LOJAS:
        vend = output["extractions"].get(loja, {}).get("Vendedor", {})
        print(f"  {loja}: R$ {sum(vend.values()):,.2f}  ({len(vend)} vendedores)")


if __name__ == "__main__":
    main()
