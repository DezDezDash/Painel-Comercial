#!/usr/bin/env python3
"""
Scraper - Trivia F-Loja - Painel de Vendas
Extrai 12 combinacoes (4 lojas x 3 filtros "Por").
Valor liquido = coluna "Valor" - coluna "Dev."
"""

import os
import json
import re
import time
from datetime import date

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

LOGIN_URL = "http://app.comercialdezdez.com.br:8080/loja/publico/login.jsf"
ADMIN_URL = "http://app.comercialdezdez.com.br:8080/loja/admin/default.jsf"

SITE_LOGIN = os.environ.get("SITE_LOGIN", "")
SITE_SENHA = os.environ.get("SITE_SENHA", "")

LOJAS = {
    "CAM": "Vendedor Camaragibe",
    "CAV": "Vendedor Cavaleiro",
    "SLM": "Vendedor Sao Lourenco",
    "CAX": "Vendedor Caxanga",
}

POR_OPTIONS = ["Linha de Produto", "Fornecedor", "Vendedor"]
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "scraped_data.json")


def make_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
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
        print(f"  Screenshot: /tmp/debug_{name}.png")
    except Exception:
        pass


def select_pf_dropdown(driver, label_text, option_text):
    """Seleciona opcao em dropdown PrimeFaces."""
    try:
        container = driver.find_element(
            By.XPATH,
            f"//label[normalize-space(text())='{label_text}']/following-sibling::div[contains(@class,'ui-selectonemenu')]"
            f" | //span[normalize-space(text())='{label_text}']/following-sibling::div[contains(@class,'ui-selectonemenu')]"
            f" | //*[normalize-space(text())='{label_text}']/parent::*/following-sibling::*[contains(@class,'ui-selectonemenu')]"
        )
        driver.execute_script("arguments[0].click();", container)
        time.sleep(0.6)
        panel = WebDriverWait(driver, 8).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, ".ui-selectonemenu-panel:not([style*='display: none'])")
            )
        )
        option = panel.find_element(By.XPATH, f".//li[normalize-space(text())='{option_text}']")
        driver.execute_script("arguments[0].click();", option)
        wait_ajax(driver)
        return True
    except Exception as e:
        print(f"    [pf fallback] {label_text}={option_text}: {e}")

    # Fallback: select oculto
    try:
        for sel_el in driver.find_elements(By.TAG_NAME, "select"):
            try:
                s = Select(sel_el)
                if option_text in [o.text.strip() for o in s.options]:
                    driver.execute_script("arguments[0].style.display='block';", sel_el)
                    s.select_by_visible_text(option_text)
                    driver.execute_script(
                        "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", sel_el
                    )
                    wait_ajax(driver)
                    return True
            except Exception:
                continue
    except Exception as e2:
        print(f"    [select fallback] {e2}")
    return False


def set_date_field(driver, date_str, is_end=False):
    try:
        date_inputs = driver.find_elements(
            By.XPATH,
            "//input[@type='text'][contains(@id,'period') or contains(@id,'data') "
            "or contains(@id,'date') or contains(@id,'inicio') or contains(@id,'fim')]"
        )
        if not date_inputs:
            all_inputs = driver.find_elements(By.XPATH, "//input[@type='text']")
            date_inputs = [i for i in all_inputs
                           if re.match(r"\d{2}/\d{2}/\d{4}", i.get_attribute("value") or "")]
        idx = 1 if is_end else 0
        if len(date_inputs) > idx:
            inp = date_inputs[idx]
            driver.execute_script(
                "arguments[0].value=arguments[1];"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                inp, date_str
            )
            return True
    except Exception as e:
        print(f"    [set_date] {e}")
    return False


def parse_br_float(text):
    t = text.strip().replace(" ", "")
    t = re.sub(r"\.(?=\d{3}(?:[,\s]|$))", "", t)
    t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return 0.0


def extract_table(driver):
    """Extrai tabela. Valor liquido = Valor - Dev."""
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
                if not name or name.upper() in ("TOTAL", ""):
                    continue
                try:
                    valor = parse_br_float(cells[idx_valor].text) if idx_valor < len(cells) else 0.0
                    dev = parse_br_float(cells[idx_dev].text) if idx_dev is not None and idx_dev < len(cells) else 0.0
                    net = round(valor - dev, 2)
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
    print("Login...")
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
        raise RuntimeError("Campo usuario nao encontrado")
    user_field.clear()
    user_field.send_keys(SITE_LOGIN)
    pass_field.clear()
    pass_field.send_keys(SITE_SENHA)
    btn = driver.find_element(
        By.XPATH,
        "//button[@type='submit'] | //input[@type='submit']"
        " | //button[contains(.,'Entrar') or contains(.,'Login') or contains(.,'Acessar')]"
    )
    btn.click()
    wait_ajax(driver)
    time.sleep(3)
    if "login" in driver.current_url.lower():
        screenshot(driver, "login_failed")
        raise RuntimeError(f"Login falhou: {driver.current_url}")
    print(f"  OK - {driver.current_url}")


def navigate_to_painel_vendas(driver):
    driver.get(ADMIN_URL)
    wait_ajax(driver)
    time.sleep(2)
    try:
        link = driver.find_element(
            By.XPATH,
            "//*[contains(text(),'Painel de Vendas') or contains(@title,'Painel de Vendas')]"
            "[not(contains(@class,'ui-tabmenuitem-active'))]"
        )
        driver.execute_script("arguments[0].click();", link)
        wait_ajax(driver)
        time.sleep(2)
        print("  Painel de Vendas OK")
        return
    except Exception:
        pass
    try:
        driver.execute_script("arguments[0].click();",
                              driver.find_element(By.XPATH, "//*[contains(text(),'Pedido')]"))
        time.sleep(1)
        driver.execute_script("arguments[0].click();",
                              driver.find_element(By.XPATH,
                                                  "//*[contains(text(),'Painel de Vendas') or contains(@title,'Painel de Vendas')]"))
        wait_ajax(driver)
        time.sleep(2)
        print("  Painel de Vendas via menu Pedido OK")
    except Exception as e:
        print(f"  AVISO: {e}")
        screenshot(driver, "nav_failed")


def run_extraction(driver, loja_code, loja_label, por_option, start_str, end_str):
    print(f"  [{loja_code}] {por_option}...")
    try:
        ok = select_pf_dropdown(driver, "TipoVendedor:", loja_label)
        if not ok:
            select_pf_dropdown(driver, "TipoVendedor", loja_label)
        time.sleep(0.5)
        ok2 = select_pf_dropdown(driver, "Por:", por_option)
        if not ok2:
            select_pf_dropdown(driver, "Por", por_option)
        time.sleep(0.5)
        set_date_field(driver, start_str, is_end=False)
        set_date_field(driver, end_str, is_end=True)
        time.sleep(0.3)
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(.,'Pesquisar')] | //a[contains(.,'Pesquisar')]")
            )
        )
        driver.execute_script("arguments[0].click();", btn)
        wait_ajax(driver)
        time.sleep(3)
        data = extract_table(driver)
        print(f"    -> {len(data)} registros")
        return data
    except Exception as e:
        print(f"    ERRO: {e}")
        screenshot(driver, f"{loja_code}_{por_option.replace(' ','_')}")
        return {}


def main():
    if not SITE_LOGIN or not SITE_SENHA:
        raise RuntimeError("SITE_LOGIN e SITE_SENHA nao definidos.")

    today = date.today()
    start_str = f"01/{today.month:02d}/{today.year}"
    end_str = f"{today.day:02d}/{today.month:02d}/{today.year}"
    print(f"Periodo: {start_str} a {end_str}")

    output = {
        "date": today.isoformat(),
        "day": today.day,
        "month_key": f"{today.year}-{today.month:02d}-01",
        "extractions": {},
    }

    driver = make_driver()
    try:
        login(driver)
        navigate_to_painel_vendas(driver)
        for loja_code, loja_label in LOJAS.items():
            print(f"\nLoja: {loja_code}")
            output["extractions"][loja_code] = {}
            for por in POR_OPTIONS:
                data = run_extraction(driver, loja_code, loja_label, por, start_str, end_str)
                output["extractions"][loja_code][por] = data
    finally:
        driver.quit()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSalvo: {OUTPUT_FILE}")
    print("\nResumo:")
    for loja in LOJAS:
        vend = output["extractions"].get(loja, {}).get("Vendedor", {})
        print(f"  {loja}: R$ {sum(vend.values()):,.2f} ({len(vend)} vendedores)")


if __name__ == "__main__":
    main()
