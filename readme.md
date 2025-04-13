# Solana Flash Loan Arbitrage Bot & Analysis Suite

This project was desgined for encode club's London Ai Hackathon a dcombines a Solana smart contract for executing flash loan arbitrage with a backend analysis engine and a frontend UI for interaction/simulation.

## Overview

The system consists of three main parts:

1.  **Flask Backend (`app.py`):** Continuously scans cryptocurrency prices from sources like CoinGecko and Birdeye (or uses simulated data) to identify potential arbitrage opportunities between different markets. It serves a simple web interface to display the status and found opportunities and can run a separate strategy agent (`portia_strategy_agent.py`).
2.  **Solana Smart Contract (`SmartContract/`):** A Rust-based smart contract built with the Anchor framework, designed to perform flash loan arbitrage transactions on the Solana blockchain by borrowing from a lending protocol, swapping on two different DEXes, and repaying the loan within a single transaction.

## Directory Structure

```
├── SmartContract/         
│   ├── programs/           
│   ├── tests/              
│   ├── scripts/        
│   ├── flash-loan-ui/     
│   │   ├── src/
│   │   ├── public/
│   │   ├── package.json
│   │   └── README.md       
│   ├── src/                
│   ├── Anchor.toml     
│   ├── Cargo.toml        
│   └── README.md        
├── templates/           
│   └── index.html       
├── .git/                  
├── .gitmodules           
├── .portia/                  
├── app.py                   
├── portia_strategy_agent.py  
├── requirements.txt        
├── found_arbitrage.json     
├── identified_tokens.json   
├── .env.example            
└── README.md               
```

## Components Deep Dive

### Backend (Flask - `app.py`)

*   **Functionality:** Runs an arbitrage analysis loop, fetches/simulates prices, identifies opportunities based on configured thresholds, optionally runs `portia_strategy_agent.py`, and serves a web UI (`index.html`).
*   **Dependencies:** Python 3.x, Flask, Requests, etc. (see `requirements.txt`).
*   **Configuration:** Requires API keys for CoinGecko Pro and Birdeye, configured via a `.env` file (based on `.env.example`). Can run in `live` or `simulation` mode.
*   **Technology:** portia


### Smart Contract (Solana/Anchor - `SmartContract/`)

*   **Functionality:** Executes flash loan arbitrage logic on Solana. Interacts with lending protocols and DEXes via CPIs.
*   **Technology:** Rust, Anchor Framework, Solana Blockchain.
*   **Setup:** Requires Rust, Solana CLI, and Anchor toolchain. See `SmartContract/README.md` for details.
*   **Deployment:** Various scripts (`.sh`) are provided for local testing, testnet deployment, and persistent wallet deployment.


## Setup Instructions

### 1. Backend Setup

```bash
# Create and activate a virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`

# Install Python dependencies
pip install -r requirements.txt

# Create the .env file from the example
cp .env.example .env

# Edit .env and add your API keys (BIRDEYE_API_KEY, COINGECKO_PRO_KEY)
nano .env # Or use your preferred editor
```

### 2. Smart Contract & UI Setup

Refer to the detailed instructions in the respective READMEs:

*   **Smart Contract:** `SUBMISSION/SmartContract/README.md` (Requires Rust, Solana CLI, Anchor installation)
*   **UI:** `SUBMISSION/SmartContract/flash-loan-ui/README.md` (Requires Node.js/npm installation)

A typical workflow might involve:

```bash
# From /SmartContract/
anchor build

# From /SmartContract/flash-loan-ui/
npm install
```

## Running the System

The components generally run independently but are designed to work together conceptually.

### 1. Running the Backend

```bash

python app.py # Add --simulate flag if you want to use synthetic data initially

# Access the backend's web interface (usually http://localhost:5000)
```
Check `app.py` for potential command-line arguments (like `--simulate` or port specification).

### 2. Running the Smart Contract & UI

Use the scripts provided within the `/SmartContract/` directory. These handle deployment and UI startup together.

```bash
cd /SmartContract/

# Example: Run locally (starts local validator, deploys, starts UI)
./run-gui-and-test.sh

# Example: Deploy to testnet and start UI
./deploy_to_testnet.sh

# Access the React UI (usually http://localhost:3000)
```
Consult the scripts and `/README.md` for specifics on different deployment options.

