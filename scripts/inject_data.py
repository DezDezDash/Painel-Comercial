#!/usr/bin/env python3
"""
Lê scraped_data.json e gera data.js na raiz do repositório.
O dashboard (index.html) carrega data.js e sobrescreve os dados padrão.
"""

import json
import os
from pathlib import Path
from datetime import date

SCRAPED_FILE = Path(__file__).parent / "scraped_data.json"
DATA_JS      = Path(__file__).parent.parent / "data.js"


def upsert_month(arr, date_key, new_fields):
    for i, entry in enumerate(arr):
        if entry.get("date") == date_key:
            arr[i] = {**arr[i], **new_fields, "date": date_key}
            return arr
    arr.append({"date": date_key, **new_fields})
    arr.sort(key=lambda x: x.get("date", ""))
    return arr


def main():
    if not SCRAPED_FILE.exists():
        raise FileNotFoundError(f"{SCRAPED_FILE} não encontrado. Execute scraper.py primeiro.")

    with open(SCRAPED_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    today     = date.today()
    month_key = raw.get("month_key", f"{today.year}-{today.month:02d}-01")
    day       = raw.get("day", today.day)
    extr      = raw.get("extractions", {})
    lojas     = ["CAM", "CAV", "SLM", "CAX"]
    META      = 80000

    print(f"Gerando data.js — período: {month_key}, dia {day}")

    vendas_por_vendedor = {}
    parcial = {}
    for loja in lojas:
        vend = extr.get(loja, {}).get("Vendedor", {})
        rows = [{"n": name, "R": round(val, 2)}
                for name, val in sorted(vend.items(), key=lambda x: -x[1]) if val > 0]
        vendas_por_vendedor[loja] = {"dia": day, "meta": META, "rows": rows}
        parcial[loja] = round(sum(v for v in vend.values() if v > 0), 2)

    linha_produto = {"CAM": [], "CAV": [], "SLM": [], "CAX": [], "Rede": []}
    rede_agg: dict = {}
    if DATA_JS.exists():
        try:
            txt = DATA_JS.read_text(encoding="utf-8")
            js = json.loads(txt.split("const dashboardData = ", 1)[1].rstrip().rstrip(";"))
            if isinstance(js, dict) and js.get("linha_produto"):
                linha_produto = js["linha_produto"]
        except Exception as e:
            print(f"  Aviso: {e}")

    for loja in lojas:
        lp = extr.get(loja, {}).get("Linha de Produto", {})
        if not lp:
            continue
        linha_produto[loja] = upsert_month(linha_produto.get(loja, []), month_key,
                                           {k: round(v, 2) for k, v in lp.items() if v > 0})
        for k, v in lp.items():
            rede_agg[k] = round(rede_agg.get(k, 0.0) + v, 2)
    linha_produto["Rede"] = upsert_month(linha_produto.get("Rede", []), month_key,
                                         {k: round(v, 2) for k, v in rede_agg.items() if v > 0})

    fornecedor_arr: list = []
    if DATA_JS.exists():
        try:
            txt = DATA_JS.read_text(encoding="utf-8")
            js = json.loads(txt.split("const dashboardData = ", 1)[1].rstrip().rstrip(";"))
            if isinstance(js, dict) and js.get("fornecedor"):
                fornecedor_arr = js["fornecedor"]
        except Exception:
            pass

    rank: dict = {}
    for loja in lojas:
        for sup, val in extr.get(loja, {}).get("Fornecedor", {}).items():
            rank[sup] = round(rank.get(sup, 0.0) + val, 2)
    fornecedor_arr = upsert_month(fornecedor_arr, month_key,
                                  dict(sorted(rank.items(), key=lambda x: -x[1])))

    dashboard_data = {
        "gerado_em": raw.get("date", today.isoformat()),
        "parcialDia": day,
        "month_key": month_key,
        "parcial": parcial,
        "vendas_por_vendedor": vendas_por_vendedor,
        "linha_produto": linha_produto,
        "fornecedor": fornecedor_arr,
    }

    js_content = (
        "// Auto-gerado pelo GitHub Actions — não editar manualmente.\n"
        f"// Última atualização: {today.isoformat()}, dia {day}\n"
        "const dashboardData = "
        + json.dumps(dashboard_data, ensure_ascii=False, indent=2) + ";\n"
    )
    DATA_JS.write_text(js_content, encoding="utf-8")
    print(f"data.js gerado: {DATA_JS}")

    print("\nResumo parcial:")
    for loja in lojas:
        print(f"  {loja}: R$ {parcial[loja]:>12,.2f}  ({len(vendas_por_vendedor[loja]['rows'])} vendedores)")
    print(f"  REDE: R$ {sum(parcial.values()):>12,.2f}")


if __name__ == "__main__":
    main()
