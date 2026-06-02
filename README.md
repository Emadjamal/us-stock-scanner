# US Stock Scanner

Python CLI to screen US equities (S&P 500 or Nasdaq-100) by price, volume, daily change, and RSI. Uses [yfinance](https://github.com/ranaroussi/yfinance) for market data (no API key required).

## Setup

```powershell
cd C:\Users\Emad\Documents\Source\Repos\us-stock-scanner
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "src"
```

## Quick scan (CLI flags)

```powershell
# Top movers: daily gain >= 3%, price $10–$300, liquid names
python -m us_stock_scanner -u sp500 --limit 50 --min-price 10 --max-price 300 --min-change-pct 3 --min-avg-volume-20d 1000000
```

## Config file

```powershell
Copy-Item config.example.yaml config.yaml
python -m us_stock_scanner -c config.yaml
```

## Universes

| Flag | Market |
|------|--------|
| `sp500` | S&P 500 |
| `nasdaq100` | Nasdaq-100 |

## Notes

- First full S&P 500 run downloads ~500 symbols and can take several minutes.
- Use `--limit 30` while tuning filters.
- Data is delayed/free tier from Yahoo Finance; not for live trading without verification.