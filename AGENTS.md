# AGENTS.md — AI Agent Development & Workflow Guide

> [!IMPORTANT]
> **MANDATORY MEMORY MANAGEMENT DIRECTIVE**
> All AI agents working in this repository **MUST** read [MEMORY.md](MEMORY.md) at the start of every task or session to load existing state, context, and project notes.
> **Dense Key-Value Formats:** Store codebase facts, quirks, and configuration settings exclusively in markdown tables or single-line bullet points. Do not write multi-sentence narrative paragraphs.
> **Milestone Summarization:** Record completed development tasks strictly as single-line date-stamped summaries (Format: `YYYY-MM-DD: <Action taken>`). Do not retain intermediate debugging logs or multi-step execution histories.
> **Rule Consolidation:** Combine overlapping or redundant instructions into a single unified rule statement.
> **Maximum Line Count**: Maintain `MEMORY.md` at or below **150 lines**.
> **Mandatory Pruning Trigger:** If `MEMORY.md` reaches **150 lines**, the agent **MUST** notify the user and ask for permission to prune and compress the file prior to completing the current session turn.

---

## 1. Project Overview & Context

**GNSS-Product-Comparator** is a specialized Python and CustomTkinter desktop application for comparing, evaluating, and visualizing GNSS (Global Navigation Satellite Systems: GPS, Galileo, BeiDou, GLONASS) satellite orbit and clock products.

### Primary Capabilities:
1. **SP3 Orbit Comparison**: Computes 3D satellite position differences and decomposes errors into Radial, Along-track, and Cross-track (RAC) components relative to a designated reference SP3 file.
2. **CLK Clock Comparison**: Evaluates satellite clock bias differences, aligned to reference clock products.
3. **SISRE (Signal-in-Space Range Error) Calculation**: Evaluates combined orbit and clock error metrics using satellite-specific weight factors (e.g., GPS vs Galileo weights), supporting SP3+CLK, RINEX+SSR (Galileo HAS), and BRDC/NAV pairs with PCO (Phase Center Offset) antenna corrections from ATX files.
4. **Elevation Masking & Receiver Location**: Computes topocentric satellite elevation angles for a given ground receiver position and masks satellites below specified cutoff angles.
5. **Covariance Simulation**: Simulates positioning accuracy limits (Horizontal/Vertical threshold violations over specified durations).

---

## 2. Codebase Architecture & File Map

```
GNSS-Product-Comparator/
│
├── main_app.py                 # CustomTkinter GUI interface & application state controller
├── main_app.spec               # PyInstaller executable build specification
├── requirements.txt            # Python dependencies (UTF-8)
├── requirements_linux.txt      # Linux environment dependencies
│
├── tests/                      # Headless unit test suite
│   ├── test_elevation_perf.py  # Elevation masking and vectorization tests
│   ├── test_file_date_extraction.py # Product filename date extraction tests
│   ├── test_interpolation.py   # Barycentric interpolation tests
│   └── test_sat_filter.py      # Satellite discovery and pattern filter tests
│
├── scripts/                    # Core calculation engines & file parsing routines
│   ├── file_parsers.py         # Parsers for SP3, CLK, RINEX NAV, ATX (PCV/PCO), Galileo HAS/SSR
│   ├── comparison_logic.py     # RAC transformations, clock bias, SISRE, elevation masking, barycentric interpolation
│   ├── covariance_sim.py       # Covariance positioning simulation engine
│   ├── export_logic.py         # Excel result export and aggregation
│   └── orchestrator.py         # End-to-end analysis workflow orchestration
│
└── cssrlib/                    # Low-level GNSS algorithms library
    ├── cssrlib.py              # SSR decoder & compact state routines
    ├── ephemeris.py            # Keplerian/broadcast ephemeris propagation & clock calculation
    ├── gnss.py                 # Constants, time conversions (GPS time, epoch2time), satellite ID mappings
    ├── peph.py                 # Precise ephemeris & ATX antenna parser functions (searchpcv, apc2com)
    └── rinex.py                # RINEX navigation & observation file decoders
```

---

## 3. Guidelines for AI Agents

### Rule 1: Always Maintain and Consult `MEMORY.md`
- **Session Startup**: Always read [MEMORY.md](MEMORY.md) to recall past decisions, known technical quirks, and ongoing tasks.
- **Session Wrap-Up**: Record significant changes, unresolved issues, and status updates in [MEMORY.md](MEMORY.md).

### Rule 2: Keep GUI and Core Logic Decoupled
- **[main_app.py](main_app.py)** should only handle UI state, user interaction, progress updates, and plotting (Matplotlib integration).
- **[scripts/](scripts/)** contains pure data processing logic. Algorithms and file parsers MUST remain independent of `customtkinter` or UI widgets so they can be run programmatically or unit-tested headlessly.

### Rule 3: Robust Numerical Handling (Pandas & NumPy)
- GNSS datasets frequently contain missing epochs or unsynchronized satellite data.
- Always handle `NaN` values gracefully using `skipna=True`, `np.isnan()`, or interpolation checks.
- Maintain MultiIndex DataFrames with `(Epoch, SatID)` where appropriate to preserve time-series data structures.

### Rule 4: Verification Before Declaring Tasks Done
- Run unit tests via `python -m unittest discover tests` after refactoring numerical functions or parsers.
- Ensure all file paths in imported modules support both Windows (`\`) and POSIX (`/`) path formats cleanly.

### Rule 5: Testing Constraint
- Do not run `python main_app.py` directly as it launches the CustomTkinter event loop.
- Test non-UI logic using `unittest` or `pytest`.

---

## 6. File Referencing Convention
When referencing files in communication or plan artifacts, use relative markdown links:
- Main GUI: [main_app.py](main_app.py)
- Parsers: [scripts/file_parsers.py](scripts/file_parsers.py)
- Comparison Engine: [scripts/comparison_logic.py](scripts/comparison_logic.py)
- Ephemeris Library: [cssrlib/ephemeris.py](cssrlib/ephemeris.py)
- Memory File: [MEMORY.md](MEMORY.md)
