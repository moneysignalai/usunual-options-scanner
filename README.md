# Unusual Options Scanner

A Python-based scanner that surfaces unusual options activity across a universe of symbols. The project is designed to ingest options chain data, compute signals that indicate unusual volume/open interest behavior, and present a concise, filterable output for research and alerting.

> **Note**: This README focuses on how to run and work with the project. It does not change any application code.

---

## Table of Contents

- [Overview](#overview)
- [Key Capabilities](#key-capabilities)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Setup](#setup)
- [Configuration](#configuration)
- [Usage](#usage)
- [Output](#output)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

The **Unusual Options Scanner** aggregates options chain data, evaluates the activity against configurable thresholds, and outputs a list of candidates that meet “unusual” criteria. This is useful for:

- Monitoring spikes in options volume relative to open interest
- Highlighting contracts with large notional value
- Scanning a broad universe of tickers quickly

---

## Key Capabilities

- **Automated scanning** of options chains for unusual activity
- **Configurable thresholds** for volume, open interest, and notional value
- **Batch processing** of multiple symbols
- **Human-readable output** (e.g., printed tables) and/or machine-friendly formats

---

## Project Structure

```
.
├─ README.md
├─ requirements.txt
└─ src/
   └─ ...
```

- `README.md` — Project documentation (this file)
- `requirements.txt` — Python dependencies
- `src/` — Application source code

---

## Requirements

- **Python**: 3.10+ recommended
- **pip**: recent version

All dependencies are defined in `requirements.txt`.

---

## Setup

1. **Create a virtual environment** (recommended):

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

---

## Configuration

Depending on your environment and data source, you may need to provide configuration values such as API keys, a list of tickers, or thresholds for what counts as “unusual.”

Typical configuration methods include:

- **Environment variables** (e.g., `API_KEY`, `SYMBOLS`, `THRESHOLD_*`)
- **Configuration files** (if the project provides any)

If you’re unsure where configuration is read, inspect the `src/` directory to locate any config modules or `.env` support.

---

## Usage

> The exact entry point depends on the scripts provided in `src/`. Common patterns include a `main.py` or a CLI runner.

Example invocation (update as appropriate for your project entry point):

```bash
python -m src.main
```

Or if a script exists:

```bash
python src/main.py
```

---

## Output

The scanner typically emits results to:

- **Stdout** — a table of unusual contracts
- **CSV/JSON** — if supported by the code
- **Logs** — to help with debugging and data provenance

The output should include key fields such as:

- Ticker / underlying
- Expiration date
- Strike price
- Call/put
- Volume
- Open interest
- Volume-to-open-interest ratio
- Notional value

---

## Examples

### Scan a list of symbols

```bash
# Example only — replace with actual CLI if present
python src/main.py --symbols AAPL,MSFT,NVDA
```

### Tune thresholds

```bash
# Example only — replace with actual config flags or env vars
export MIN_VOLUME=500
export MIN_OI=200
export MIN_NOTIONAL=100000
python src/main.py
```

---

## Troubleshooting

- **Import errors**: Ensure your virtual environment is active and dependencies are installed.
- **Data/API errors**: Confirm API keys and quotas are valid.
- **No results**: Lower thresholds or expand the symbol list.

---

## Development

- Follow standard Python best practices (virtualenv, linting, and testing).
- Prefer small, isolated changes and commit with clear messages.

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Open a pull request

---

## License

Add license information here (e.g., MIT, Apache-2.0, GPL-3.0). If no license is specified, assume the project is private or proprietary.
