# SUBMISSION/app.py
from flask import Flask, render_template, jsonify
import requests
import time
import json
import os
import logging
import random
import threading
import subprocess
from datetime import datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

# --- Flask App Setup ---
app = Flask(__name__, template_folder='templates')

# --- Configuration & Logging ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ArbitrageApp")

# --- Constants ---
PORTIA_SCRIPT = "portia_strategy_agent.py"
INPUT_TOKEN_FILE = "identified_tokens.json"
OUTPUT_ARBITRAGE_FILE = "found_arbitrage.json"
RUN_DURATION_MINUTES = 15
SCAN_INTERVAL_SECONDS = 90
MIN_PROFIT_THRESHOLD = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = 1

# --- Token Mappings & Fees (Copied/Adapted from previous analyzer) --- 
SOLANA_TOKENS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "JTO": "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "RENDER": "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof",
}

COINGECKO_IDS = {
    "SOL": "solana",
    "USDC": "usd-coin",
    "USDT": "tether",
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "JTO": "jito",
    "PYTH": "pyth-network",
    "RENDER": "render-token",
}

EXCHANGE_FEES = {
    "coingecko": 0.002,
    "birdeye": 0.001,
    "default": 0.002
}

SUPPORTED_SOURCES = ["coingecko", "birdeye"]
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY")
COINGECKO_PRO_KEY = os.getenv("COINGECKO_PRO_KEY")

if not COINGECKO_PRO_KEY:
    logger.warning("COINGECKO_PRO_KEY not found. Using public API (heavy rate limits expected).")
if not BIRDEYE_API_KEY:
    logger.warning("BIRDEYE_API_KEY not found. Birdeye fetching will fail.")

# --- Define Known Mapped Tokens ---
KNOWN_MAPPED_TOKENS = [t for t in COINGECKO_IDS if t in SOLANA_TOKENS]
logger.info(f"Identified {len(KNOWN_MAPPED_TOKENS)} tokens with known mappings: {KNOWN_MAPPED_TOKENS}")
# --------------------------------

# --- Global State & Lock ---
status_info = {
    "status": "Initializing",
    "start_time": None,
    "end_time": None,
    "last_scan_time": None,
    "target_tokens": [],
    "opportunities_found_session": 0,
    "portia_run_output": "Not run yet.",
    "portia_run_error": None
}
found_opportunities: List[Dict[str, Any]] = [] # In-memory list for UI
state_lock = threading.Lock()


@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=RETRY_BACKOFF, min=1, max=10),
    retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError, TimeoutError)),
    reraise=True
)
def fetch_from_coingecko(symbol: str) -> Optional[float]:
    time.sleep(random.uniform(2.0, 5.0))
    
    coin_id = COINGECKO_IDS.get(symbol)
    if not coin_id: coin_id = symbol.lower()
    url = f"https://pro-api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&x_cg_pro_api_key={COINGECKO_PRO_KEY}" if COINGECKO_PRO_KEY else f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        if coin_id in data and "usd" in data[coin_id]: return float(data[coin_id]["usd"])
        logger.warning(f"Invalid Coingecko format {symbol}: {data}")
        return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error Coingecko {symbol}: {e}")
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', '45'))
            wait_duration = retry_after + random.uniform(1, 5)
            logger.warning(f"CoinGecko rate limit hit for {symbol}. Waiting {wait_duration:.1f}s based on Retry-After header.")
            time.sleep(wait_duration)
            return None
        return None
    except Exception as e: logger.error(f"Error Coingecko {symbol}: {e}"); return None

@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=RETRY_BACKOFF, min=1, max=10),
    retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError, TimeoutError)),
    reraise=True
)
def fetch_from_birdeye(symbol: str) -> Optional[float]:
    time.sleep(random.uniform(2.0, 4.0))

    token_address = SOLANA_TOKENS.get(symbol)
    if not token_address: logger.warning(f"No address for {symbol}"); return None
    if not BIRDEYE_API_KEY: logger.error("BIRDEYE_API_KEY missing"); return None
    url = f"https://public-api.birdeye.so/defi/price?address={token_address}"
    headers = {"X-API-KEY": BIRDEYE_API_KEY}
    time.sleep(random.uniform(1.0, 2.5))
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("success") and data.get("data") and data["data"].get("value") is not None:
            return float(data["data"]["value"])
        logger.warning(f"Invalid Birdeye format {symbol}: {data}")
        return None
    except Exception as e: logger.error(f"Error Birdeye {symbol}: {e}"); return None

def get_prices_for_token(symbol: str) -> Dict[str, float]:
    prices = {}
    for source in SUPPORTED_SOURCES:
        try:
            fetch_func = None
            if source == "coingecko": fetch_func = fetch_from_coingecko
            elif source == "birdeye": fetch_func = fetch_from_birdeye
            
            if fetch_func:
                price = fetch_func(symbol)
                if price is not None: prices[source] = price
            else: logger.warning(f"Source {source} not implemented.")
        except Exception as e: logger.error(f"Final fetch fail {symbol}/{source}: {e}")
    return prices

def find_arbitrage_opportunities(token_prices: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    opportunities = []
    processed_pairs = set()
    for symbol, prices in token_prices.items():
        if len(prices) < 2: continue
        sources = list(prices.keys())
        for i in range(len(sources)):
            for j in range(i + 1, len(sources)):
                source_a, source_b = sources[i], sources[j]
                price_a, price_b = prices[source_a], prices[source_b]
                pair_key = tuple(sorted((source_a, source_b)))
                if (symbol, pair_key) in processed_pairs: continue
                fee_a = EXCHANGE_FEES.get(source_a, EXCHANGE_FEES["default"])
                fee_b = EXCHANGE_FEES.get(source_b, EXCHANGE_FEES["default"])
                
                # Check A -> B
                buy_price_eff_a = price_a * (1 + fee_a)
                sell_price_eff_b = price_b * (1 - fee_b)
                if sell_price_eff_b > buy_price_eff_a and buy_price_eff_a > 0:
                    profit = ((sell_price_eff_b / buy_price_eff_a) - 1) * 100
                    if profit >= MIN_PROFIT_THRESHOLD:
                        opp = {"timestamp": datetime.now().isoformat(), "symbol": symbol, "buy_exchange": source_a, "buy_price": price_a, "sell_exchange": source_b, "sell_price": price_b, "profit_percent": round(profit, 4)}
                        opportunities.append(opp)
                        logger.info(f"ARB: {symbol} | Buy {source_a} (${price_a:.6f}) Sell {source_b} (${price_b:.6f}) | Profit: {profit:.2f}%")
                        processed_pairs.add((symbol, pair_key))
                        continue
                        
                # Check B -> A
                buy_price_eff_b = price_b * (1 + fee_b)
                sell_price_eff_a = price_a * (1 - fee_a)
                if sell_price_eff_a > buy_price_eff_b and buy_price_eff_b > 0:
                    profit = ((sell_price_eff_a / buy_price_eff_b) - 1) * 100
                    if profit >= MIN_PROFIT_THRESHOLD:
                        opp = {"timestamp": datetime.now().isoformat(), "symbol": symbol, "buy_exchange": source_b, "buy_price": price_b, "sell_exchange": source_a, "sell_price": price_a, "profit_percent": round(profit, 4)}
                        opportunities.append(opp)
                        logger.info(f"ARB: {symbol} | Buy {source_b} (${price_b:.6f}) Sell {source_a} (${price_a:.6f}) | Profit: {profit:.2f}%")
                        processed_pairs.add((symbol, pair_key))
    return opportunities

def load_target_tokens() -> List[str]:
    try:
        with open(INPUT_TOKEN_FILE, 'r') as f: data = json.load(f)
        tokens = data.get("identified_tokens", [])
        if tokens: logger.info(f"Loaded {len(tokens)} tokens from {INPUT_TOKEN_FILE}: {tokens}"); return tokens
        logger.warning(f"{INPUT_TOKEN_FILE} empty/invalid. Default: ['SOL']"); return ["SOL"]
    except Exception as e: logger.error(f"Error loading {INPUT_TOKEN_FILE}: {e}. Default: ['SOL']"); return ["SOL"]

def save_arbitrage_opportunities(opportunities: List[Dict[str, Any]]):
    if not opportunities: return
    try:
        existing_data = []
        if os.path.exists(OUTPUT_ARBITRAGE_FILE):
            try:
                with open(OUTPUT_ARBITRAGE_FILE, 'r') as f: existing_data = json.load(f)
                if not isinstance(existing_data, list): existing_data = []
            except json.JSONDecodeError: logger.warning(f"Overwrite invalid {OUTPUT_ARBITRAGE_FILE}"); existing_data = []
        all_opportunities = existing_data + opportunities
        with open(OUTPUT_ARBITRAGE_FILE, 'w') as f: json.dump(all_opportunities, f, indent=2)
        logger.info(f"Appended {len(opportunities)} opps to {OUTPUT_ARBITRAGE_FILE}")
    except Exception as e: logger.error(f"Failed to save opps: {e}")

# --- Background Analysis Thread ---

def run_arbitrage_analysis():
    global status_info, found_opportunities
    
    logger.info("Background arbitrage analysis thread started.")
    start_time = datetime.now()
    end_time = start_time + timedelta(minutes=RUN_DURATION_MINUTES)
    
    # Load tokens identified by Portia
    portia_tokens = load_target_tokens() # This handles file not found, defaults etc.
    
    # Combine known tokens with Portia-identified tokens and deduplicate
    target_tokens = list(set(KNOWN_MAPPED_TOKENS + portia_tokens))
    logger.info(f"Combined list for analysis (Known + Portia - Duplicates): {target_tokens}")

    with state_lock:
        status_info["status"] = "Running Analysis"
        status_info["start_time"] = start_time.isoformat()
        status_info["end_time"] = end_time.isoformat()
        status_info["target_tokens"] = target_tokens
        status_info["opportunities_found_session"] = 0
        
    if not target_tokens:
        logger.error("No target tokens defined (Known or Identified). Background thread exiting.")
        with state_lock:
            status_info["status"] = "Finished: No Tokens To Analyze"
        return

    session_opportunities_count = 0
    while datetime.now() < end_time:
        loop_start_time = time.time()
        
        current_prices: Dict[str, Dict[str, float]] = {}
        shuffled_tokens = random.sample(target_tokens, len(target_tokens))
        for token in shuffled_tokens:
            prices = get_prices_for_token(token)
            if prices: current_prices[token] = prices
            time.sleep(0.5)
            if datetime.now() >= end_time: break # Exit loop early if time is up
        
        if datetime.now() >= end_time: break 

        new_opportunities = find_arbitrage_opportunities(current_prices)
        
        if new_opportunities:
            with state_lock:
                 # Append to in-memory list for UI
                 found_opportunities.extend(new_opportunities)
                 # Keep only last N opportunities in memory if needed
                 # found_opportunities = found_opportunities[-100:]
                 session_opportunities_count += len(new_opportunities)
                 status_info["opportunities_found_session"] = session_opportunities_count
            save_arbitrage_opportunities(new_opportunities)
            
        with state_lock:
            status_info["last_scan_time"] = datetime.now().isoformat()
            
        elapsed_time = time.time() - loop_start_time
        wait_time = max(0, SCAN_INTERVAL_SECONDS - elapsed_time)
        remaining_duration = (end_time - datetime.now()).total_seconds()
        actual_wait = min(wait_time, remaining_duration)
        
        logger.info(f"Scan cycle done ({elapsed_time:.1f}s). Waiting {actual_wait:.1f}s.")
        if actual_wait > 0:
            time.sleep(actual_wait)
            
    with state_lock:
        status_info["status"] = "Analysis Finished"
    logger.info(f"Background analysis finished after {RUN_DURATION_MINUTES} mins.")

# --- Flask Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    with state_lock:
        return jsonify(status_info)

@app.route('/api/opportunities')
def get_opportunities():
    with state_lock:
        # Return opportunities found so far in this session
        return jsonify(found_opportunities)

# --- Main Execution ---

def run_portia_agent():
    global status_info
    logger.info(f"Running Portia agent script: {PORTIA_SCRIPT}...")
    try:
        # Run the script from the current directory (SUBMISSION)
        # Ensure python executable from venv is used if possible
        python_executable = sys.executable # Get path to current python interpreter
        process = subprocess.run(
            [python_executable, PORTIA_SCRIPT], 
            capture_output=True, 
            text=True, 
            check=True, # Raises CalledProcessError on non-zero exit code
            timeout=300 # 5 minute timeout
        )
        logger.info(f"Portia agent finished successfully.")
        output = process.stdout[-1000:] # Get last 1000 chars of output
        with state_lock:
             status_info["portia_run_output"] = f"Success:\n...\n{output}"
             status_info["portia_run_error"] = None
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Portia agent script failed with exit code {e.returncode}.")
        logger.error(f"Portia stdout: {e.stdout}")
        logger.error(f"Portia stderr: {e.stderr}")
        with state_lock:
             status_info["portia_run_output"] = f"Failed (Code {e.returncode}). See logs."
             status_info["portia_run_error"] = e.stderr[-1000:] # Last 1000 chars
    except subprocess.TimeoutExpired:
        logger.error(f"Portia agent script timed out.")
        with state_lock:
             status_info["portia_run_output"] = "Failed (Timeout)."
             status_info["portia_run_error"] = "Timeout after 300 seconds."
    except FileNotFoundError:
         logger.error(f"Could not find Portia script: {PORTIA_SCRIPT} or python executable {python_executable}")
         with state_lock:
             status_info["portia_run_output"] = f"Failed (Script not found)."
             status_info["portia_run_error"] = f"File {PORTIA_SCRIPT} not found."
    except Exception as e:
        logger.error(f"Error running Portia agent: {e}", exc_info=True)
        with state_lock:
             status_info["portia_run_output"] = f"Failed (Exception). See logs."
             status_info["portia_run_error"] = str(e)
    return False

if __name__ == "__main__":
    import sys 
    print(f"Starting application... CWD: {os.getcwd()}")
    
    # Create templates directory if it doesn't exist
    if not os.path.exists("templates"):
        os.makedirs("templates")
        print("Created templates directory.")

    # Run Portia agent first to generate the token list
    if run_portia_agent():
        # If Portia agent succeeded, start the background analysis
        analysis_thread = threading.Thread(target=run_arbitrage_analysis, daemon=True)
        analysis_thread.start()
    else:
        print("Portia agent failed to run. Arbitrage analysis will not start.")
        with state_lock:
            status_info["status"] = "Error: Portia Failed"

    # Run Flask app
    print("Starting Flask server on http://0.0.0.0:5001")
    app.run(host='0.0.0.0', port=5001, debug=False) 