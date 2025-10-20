#!/usr/bin/env python3
"""
Monitor Binance + On-chain BTC + Trading + Blockchain interno
Logs em logs/logs_binance.log
API rodando na porta 1533
Requisitos:
pip install requests tabulate python-dotenv colorama pyfiglet flask
"""
import os
import time
import hmac
import hashlib
import requests
import logging
from urllib.parse import urlencode
from datetime import datetime, timezone
from tabulate import tabulate
from dotenv import load_dotenv
from colorama import Fore, Style, init
from pyfiglet import Figlet
import json
from threading import Thread
from flask import Flask, jsonify, request

# Inicializa cores e dotenv
init(autoreset=True)
load_dotenv()

# Banner estiloso
fig = Figlet(font='slant')
banner_text = fig.renderText('FERRARI Bitcoins')
BANNER = Fore.RED + banner_text + Fore.YELLOW + " 🚀🪙🪙🪙Organização Ferrari🪙🪙🪙🚀 \n" + Style.RESET_ALL
BANNER1 = Fore.RED + banner_text + Fore.YELLOW + " Empresa Localizada \n" + Style.RESET_ALL
# Logger
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/logs_binance.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# Configs Binance e loop
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
BINANCE_API_SECRET = os.environ.get("BINANCE_SECRET_KEY")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))

BINANCE_BASE = "https://api.binance.com"
ACCOUNT_ENDPOINT = "/api/v3/account"
TICKER_ENDPOINT = "/api/v3/ticker/price"
BLOCKCHAIR_BASE = "https://api.blockchair.com/bitcoin/dashboards/address"

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise SystemExit("Defina BINANCE_API_KEY e BINANCE_SECRET_KEY no .env ou variável de ambiente.")

# Blockchain interno
blockchain = []

def create_block(operation: dict):
    prev_hash = blockchain[-1]["hash"] if blockchain else "0"*64
    block_data = json.dumps(operation, sort_keys=True)
    block_hash = hashlib.sha256((prev_hash + block_data).encode()).hexdigest()
    block = {
        "timestamp": time.time(),
        "operation": operation,
        "hash": block_hash,
        "prev_hash": prev_hash
    }
    blockchain.append(block)
    return block

# Funções Binance
def sign(query_string: str, secret: str) -> str:
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def get_spot_account():
    ts = int(time.time() * 1000)
    params = {"timestamp": ts}
    qs = urlencode(params)
    signature = sign(qs, BINANCE_API_SECRET)
    qs_signed = qs + "&signature=" + signature
    url = BINANCE_BASE + ACCOUNT_ENDPOINT + "?" + qs_signed
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

def get_nonzero_balances(account_json):
    out = {}
    for b in account_json.get("balances", []):
        free = float(b.get("free", 0) or 0)
        locked = float(b.get("locked", 0) or 0)
        total = free + locked
        if total > 0:
            out[b["asset"]] = total
    return out

def get_brl_price(asset: str):
    if asset == "BRL":
        return 1.0
    pair = asset + "BRL"
    try:
        r = requests.get(f"{BINANCE_BASE}{TICKER_ENDPOINT}?symbol={pair}", timeout=10)
        r.raise_for_status()
        price = float(r.json().get("price", 0))
        return price
    except:
        return 0.0

def place_order(symbol: str, side: str, quantity: float):
    ts = int(time.time() * 1000)
    params = {
        "symbol": symbol,
        "side": side.upper(),
        "type": "MARKET",
        "quantity": quantity,
        "timestamp": ts
    }
    qs = urlencode(params)
    signature = sign(qs, BINANCE_API_SECRET)
    qs_signed = qs + "&signature=" + signature
    url = BINANCE_BASE + "/api/v3/order?" + qs_signed
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    r = requests.post(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

# BTC On-chain
def get_btc_onchain_balance(address: str):
    url = f"{BLOCKCHAIR_BASE}/{address}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    balance_sats = data["data"][address]["address"]["balance"]
    return balance_sats / 1e8

# Helpers
def pretty_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# Loop principal
prev_balances = {}
prev_onchain_btc = {}
BTC_ADDRESSES = os.environ.get("BTC_ADDRESSES", "")
btc_addresses = [a.strip() for a in BTC_ADDRESSES.split(",") if a.strip()]

def monitor_loop():
    print(BANNER)
    print(f"Iniciando loop de saldo. Intervalo: {POLL_INTERVAL}s. Hora: {pretty_now()}")
    logging.info("Iniciando loop de saldo Binance.")

    while True:
        try:
            # Spot Binance
            acct = get_spot_account()
            nonzero = get_nonzero_balances(acct)
            table = []
            for asset, amount in nonzero.items():
                prev = prev_balances.get(asset, 0.0)
                diff = amount - prev
                price_brl = get_brl_price(asset)
                value_brl = amount * price_brl
                ativo_color = Fore.CYAN + asset + Style.RESET_ALL
                valor_color = Fore.GREEN + f"R$ {value_brl:,.2f}" + Style.RESET_ALL
                change = Fore.GREEN+f"+{diff:.8f}" if diff>0 else (Fore.RED+f"{diff:.8f}" if diff<0 else "-")
                table.append([ativo_color, f"{amount:.8f}", valor_color, change])
                prev_balances[asset] = amount
                logging.info(f"{asset}: {amount:.8f} (~R$ {value_brl:,.2f}) Variação: {diff:.8f}")

            if table:
                print(f"\n[{pretty_now()}] Saldo Spot Binance:")
                print(tabulate(table, headers=["Ativo", "Saldo", "Valor BRL", "Variação"], tablefmt="grid"))

            # On-chain BTC
            if btc_addresses:
                table_onchain = []
                for addr in btc_addresses:
                    try:
                        bal = get_btc_onchain_balance(addr)
                    except Exception as e:
                        print(f"Erro ao consultar {addr}: {e}")
                        logging.error(f"Erro on-chain {addr}: {e}")
                        continue
                    prev = prev_onchain_btc.get(addr, 0.0)
                    delta = bal - prev
                    change = Fore.GREEN + f"+{delta:.8f}" + Style.RESET_ALL if delta>0 else "-"
                    table_onchain.append([addr[:10]+"...", f"{bal:.8f}", change])
                    prev_onchain_btc[addr] = bal
                    logging.info(f"On-chain {addr[:10]}...: {bal:.8f} BTC variação: {delta:.8f}")
                if table_onchain:
                    print(f"\n[{pretty_now()}] Saldo BTC On-chain:")
                    print(tabulate(table_onchain, headers=["Endereço", "Saldo BTC", "Variação"], tablefmt="grid"))

            # Decisão de compra/venda BTC usando saldo real
            btc_price = get_brl_price("BTC")
            if btc_price > 0:
                # Compra
                if btc_price < 100000:
                    brl_balance = prev_balances.get("BRL", 0)
                    if brl_balance > 10:  # mínimo de segurança
                        qty_to_buy = brl_balance / btc_price
                        try:
                            order = place_order("BTCBRL", "BUY", qty_to_buy)
                            block = create_block({"side":"BUY","asset":"BTC","quantity":qty_to_buy,"price":btc_price})
                            print(Fore.GREEN + f"Compra executada: {order}")
                            logging.info(f"Compra BTC registrada no blockchain interno: {block}")
                        except Exception as e:
                            print(Fore.RED + f"Erro ao comprar BTC: {e}")
                            logging.error(f"Erro ao comprar BTC: {e}")
                # Venda
                elif btc_price > 120000:
                    btc_balance = prev_balances.get("BTC", 0)
                    if btc_balance > 0.0001:  # mínimo de segurança
                        try:
                            order = place_order("BTCBRL", "SELL", btc_balance)
                            block = create_block({"side":"SELL","asset":"BTC","quantity":btc_balance,"price":btc_price})
                            print(Fore.YELLOW + f"Venda executada: {order}")
                            logging.info(f"Venda BTC registrada no blockchain interno: {block}")
                        except Exception as e:
                            print(Fore.RED + f"Erro ao vender BTC: {e}")
                            logging.error(f"Erro ao vender BTC: {e}")

        except Exception as e:
            print("Erro geral:", e)
            logging.error(f"Erro geral: {e}")

        time.sleep(POLL_INTERVAL)

# API Flask na porta 1533
app = Flask(__name__)

@app.route("/saldo", methods=["GET"])
def api_saldo():
    return jsonify({"spot": prev_balances, "onchain": prev_onchain_btc})

@app.route("/blockchain", methods=["GET"])
def api_blockchain():
    return jsonify(blockchain)

@app.route("/ordem", methods=["POST"])
def api_ordem():
    data = request.json
    if not data or "side" not in data or "quantity" not in data:
        return jsonify({"erro":"Envie JSON com 'side' e 'quantity'"}), 400
    side = data["side"].upper()
    qty = float(data["quantity"])
    try:
        price = get_brl_price("BTC")
        order = place_order("BTCBRL", side, qty)
        block = create_block({"side":side,"asset":"BTC","quantity":qty,"price":price})
        return jsonify({"order": order, "block": block})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

if __name__ == "__main__":
    # Roda loop de monitoramento em thread separada
    t = Thread(target=monitor_loop, daemon=True)
    t.start()
    print(f"API rodando na porta 1533")
    app.run(host="0.0.0.0", port=1533)
