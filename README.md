# GNSS-Product-Comparator

[![Python Version](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

**GNSS-Product-Comparator** is a high-performance Python desktop application for comparing, evaluating, and visualizing Global Navigation Satellite System (GNSS) satellite orbit and clock products. It supports GPS, Galileo, BeiDou, GLONASS, and QZSS constellations across precise and broadcast formats.

---

## Key Capabilities

1. **SP3 Orbit Comparison**:
   * Computes 3D satellite position differences between test and reference SP3 ephemerides.
   * Decomposes spatial orbital errors into **Radial, Along-track, and Cross-track (RAC)** components.
   * Supports barycentric polynomial interpolation to align differing product sampling intervals.

2. **CLK Clock Comparison**:
   * Computes satellite clock bias differences aligned to reference clock products.
   * Calculates per-epoch constellation reference offsets and relative clock drift.

3. **SISRE (Signal-in-Space Range Error) Calculation**:
   * Evaluates combined orbit and clock error metrics using constellation-specific weight factors (e.g., GPS vs Galileo weights).
   * Supports mixed-product workflows: **SP3+CLK**, **RINEX NAV + SSR (Galileo HAS / E6-B)**, and **BRDC/NAV pairs**.
   * Applies Phase Center Offset (PCO) satellite antenna corrections from ANTEX (`.atx`) files.

4. **Elevation Masking & Receiver Topocentric Filtering**:
   * Calculates instantaneous topocentric satellite elevation angles relative to a user-defined ground station position (`Lat, Lon, Alt`).
   * Vectorized elevation filtering masks out low-elevation satellites below customizable cutoff angles.

5. **Covariance Positioning Simulation**:
   * Simulates positioning accuracy limits (Horizontal and Vertical error threshold violations over customizable time windows).
   * Models theoretical convergence curves with anti-collision staggered tier labels and summary metrics.

6. **Dynamic Satellite Discovery & Filtering**:
   * Auto-discovers satellites present in loaded datasets with constellation presets (`G*`, `E*`, `R*`, `C*`, `J*`).
   * Interactive docked satellite filter dialog with real-time inclusion/exclusion selection and single-product availability indicators.

7. **Excel Export & Visual Analytics**:
   * Interactive multi-panel Matplotlib plotting with per-satellite and per-constellation RMS summaries.
   * Comprehensive Excel export (`.xlsx`) structured with summary statistics, constellation metrics, and per-satellite breakdowns.

---

## Supported Formats

| Format | Extension | Description |
| :--- | :--- | :--- |
| **SP3 Precise Orbit** | `.sp3`, `.eph` | Precise satellite ephemerides (SP3-a, SP3-c, SP3-d) |
| **RINEX Clock** | `.clk`, `.clk_30s` | Precise satellite clock bias files |
| **RINEX Navigation** | `.rnx`, `.nav`, `.*n`, `.*p` | Broadcast navigation ephemerides (RINEX 2.x, 3.x, 4.x) |
| **ANTEX Antenna** | `.atx` | IGS ANTEX antenna phase center offset and variation models |
| **Galileo HAS / SSR** | `.has`, `.dat`, `.e6b` | High Accuracy Service (HAS) SSR orbit and clock corrections |

---

## Installation & Setup

### Prerequisites
* Python **3.9** or newer
* `pip` package manager

### 1. Clone the Repository
```bash
git clone https://github.com/vkerker5/GNSS-Product-Comparator.git
cd GNSS-Product-Comparator
```

### 2. Create and Activate a Virtual Environment
* **Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  ```
* **Linux / macOS:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## Running the Application

Launch the CustomTkinter GUI:
```bash
python main_app.py
```
*(Or install in editable mode: `pip install -e .` and run `gnss-comparator`)*.

---

## Project Structure

```
GNSS-Product-Comparator/
│
├── main_app.py                 # CustomTkinter GUI interface & plotting canvas controller
├── pyproject.toml              # Modern Python packaging configuration & build metadata
├── requirements.txt            # Python dependencies (cross-platform)
├── requirements_linux.txt      # Linux environment dependencies
├── main_app.spec               # PyInstaller executable build specification
│
├── scripts/                    # Core calculation engines & file parsing routines
│   ├── __init__.py             # Scripts package initializer
│   ├── file_parsers.py         # Parsers for SP3, CLK, RINEX NAV, ATX (PCV/PCO), Galileo HAS/SSR
│   ├── comparison_logic.py     # RAC decomposition, SISRE, clock bias, elevation masking, interpolation
│   ├── covariance_sim.py       # Covariance positioning simulation engine
│   ├── export_logic.py         # Multi-sheet Excel result export and aggregation
│   └── orchestrator.py         # End-to-end analysis workflow orchestration
│
├── cssrlib/                    # Low-level GNSS algorithms and ephemeris library
│   ├── __init__.py             # cssrlib package initializer
│   ├── cssrlib.py              # SSR decoder & compact state routines
│   ├── ephemeris.py            # Keplerian/broadcast ephemeris propagation & clock calculation
│   ├── gnss.py                 # Constants, time conversions, satellite ID mappings
│   ├── peph.py                 # Precise ephemeris & ATX antenna parser functions
│   └── rinex.py                # RINEX navigation & observation file decoders
│
└── tests/                      # Headless automated unit test suite
    ├── __init__.py             # Tests package initializer
    ├── test_elevation_perf.py  # Topocentric elevation masking and vectorization tests
    ├── test_file_date_extraction.py # Product filename date extraction tests
    ├── test_interpolation.py   # Barycentric interpolation accuracy tests
    └── test_sat_filter.py      # Satellite discovery and pattern filter tests
```

---

## Running Tests

To run the full automated test suite headlessly:

```bash
python -m unittest discover tests
```

Or using `pytest`:
```bash
pytest tests/
```

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
