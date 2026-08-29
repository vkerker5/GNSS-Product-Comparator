# MEMORY.md — Agent Persistent Context & Project Memory

> [!NOTE]
> This document is maintained by AI coding agents across development sessions to retain knowledge about codebase architecture, design choices, known bugs, environment quirks, and ongoing tasks.

---

## 1. Project Overview & Current State

* **Project Name**: GNSS-Product-Comparator
* **Repository Target**: `vkerker5/GNSS-Product-Comparator`
* **Primary Tech Stack**: Python 3.x, CustomTkinter, Matplotlib, Pandas, NumPy, SciPy, cssrlib
* **Status**: Core features implemented (SP3 orbit RAC comparison, CLK comparison, SISRE computation with PCO/ATX support, elevation masking, covariance simulation).

---

## 2. Component Map

| Component / File | Purpose | Key Classes & Functions |
|---|---|---|
| [main_app.py](main_app.py) | Main CustomTkinter UI & plot canvas integration (View/Controller only) | `App(ctk.CTk)`, `toggle_mode()`, `run_comparison()`, `draw_plots()` |
| [scripts/orchestrator.py](scripts/orchestrator.py) | End-to-end analysis workflow orchestration | `run_analysis_workflow()` |
| [scripts/export_logic.py](scripts/export_logic.py) | Excel export generation and aggregation | `export_results_to_excel()` |
| [scripts/file_parsers.py](scripts/file_parsers.py) | Decoders for SP3, CLK, RINEX NAV, ATX antenna files, Galileo HAS | `parse_sp3()`, `parse_clk()`, `parse_rnx_nav()`, `get_pco()` |
| [scripts/comparison_logic.py](scripts/comparison_logic.py) | Mathematical engine for RAC decomposition, SISRE, clock bias | `calculate_elevation_from_ref()`, `filter_results_by_elevation()`, `compute_rac_differences()`, `calculate_sisre()` |
| [scripts/covariance_sim.py](scripts/covariance_sim.py) | Covariance position accuracy simulation | Covariance simulation algorithms and error threshold testing |
| [cssrlib/](cssrlib/) | Low-level GNSS algorithms and ephemeris routines | `ephemeris.py` (`findeph`, `eph2pos`, `eph2clk`), `gnss.py` (`epoch2time`, `id2sat`), `peph.py` |
| [tests/](tests/) | Headless unit test suite | `test_elevation_perf.py`, `test_file_date_extraction.py`, `test_interpolation.py`, `test_sat_filter.py` |

---

## 3. Known Technical Quirks & Constraints

* **SP3 Satellite Filtering**: Automatically excludes designated GEO/IGSO satellites (e.g. `C01`-`C10`, `C13`, `C16`, `C38`-`C40`) during specific constellation evaluations when configured.
* **PCO / ATX Antenna Correction**: Dual-signal combinations (`GC1C`/`GC2P` for GPS, `EC1C`/`EC7Q` for Galileo) applied in `get_pco()` when `use_sis_corrections=True`.
* **Matplotlib Canvas Management**: Redraws in CustomTkinter require explicit figure clearing (`fig.clear()`) with `FigureCanvasTkAgg` / `NavigationToolbar2Tk` to prevent memory leaks.

---

## 4. Maintenance & Task History

* **2026-07-27**: Established agent guidelines in [AGENTS.md](AGENTS.md) and persistent state memory in [MEMORY.md](MEMORY.md).
* **2026-07-27**: Decoupled GUI from calculation logic by introducing [scripts/orchestrator.py](scripts/orchestrator.py) and [scripts/export_logic.py](scripts/export_logic.py).
* **2026-07-27**: Expanded satellite filter pattern matching (`G*`, `E*`, etc.) and per-constellation RMS plotting in [main_app.py](main_app.py) and [scripts/comparison_logic.py](scripts/comparison_logic.py).
* **2026-07-27**: Vectorized elevation calculations using 2D NumPy operations (~100x speedup) in [scripts/comparison_logic.py](scripts/comparison_logic.py).
* **2026-07-27**: Implemented per-mode state retention (`self.mode_states`) in [main_app.py](main_app.py) and added unit tests in [tests/test_elevation_perf.py](tests/test_elevation_perf.py) and [tests/test_sat_filter.py](tests/test_sat_filter.py).
* **2026-07-27**: Restricted Covariance Simulation controls, execution, and plotting strictly to SISRE mode in [main_app.py](main_app.py).
* **2026-07-27**: Optimized [cssrlib/ephemeris.py](cssrlib/ephemeris.py) routines: `findeph` with satellite-indexed caching (4.5x speedup) and `eph2pos` with scalar math and Newton-Raphson Kepler solver (2.2x speedup).
* **2026-07-27**: Refactored `interpolate_to_reference` in [scripts/comparison_logic.py](scripts/comparison_logic.py) (8.4x speedup, invariant denominator caching, 1D@2D matrix column evaluation) and added [tests/test_interpolation.py](tests/test_interpolation.py).
* **2026-07-27**: Refactored `calculate_sisre_combined` in [scripts/comparison_logic.py](scripts/comparison_logic.py) (4.75x speedup, boundary epoch preservation, vectorized weight lookup `assign_weights_vectorized`).
* **2026-08-19**: Reworked satellite filter UI in [main_app.py](main_app.py) from text input boxes to interactive modal dialog (`SatelliteFilterDialog`) with constellation toggles and per-mode state persistence; added unit tests in [tests/test_sat_filter.py](tests/test_sat_filter.py).
* **2026-08-19**: Implemented dynamic satellite discovery from loaded files and yellow warning highlights for satellites available in only one test product in [main_app.py](main_app.py), [scripts/file_parsers.py](scripts/file_parsers.py), and [tests/test_sat_filter.py](tests/test_sat_filter.py).
* **2026-08-19**: Reworked SatelliteFilterDialog into a docked non-modal companion window, added full GLONASS ephemeris propagation and PCO support, and optimized `geph2pos` scalar RK4 integrator (>400x speedup) in [cssrlib/ephemeris.py](cssrlib/ephemeris.py) and [scripts/file_parsers.py](scripts/file_parsers.py).
* **2026-08-19**: Documented covariance simulation architecture and scientific analysis in [COVARIANCE_SIMULATION_ANALYSIS.md](COVARIANCE_SIMULATION_ANALYSIS.md).
* **2026-08-20**: Configured console output (`console=True`) in [main_app.spec](main_app.spec) and built application executable using PyInstaller.
* **2026-08-20**: Fixed elevation masking pipeline order in [scripts/comparison_logic.py](scripts/comparison_logic.py) (postponed elevation filtering after global RAC, clock bias alignment, and SISRE computation) and added unit test in [tests/test_elevation_perf.py](tests/test_elevation_perf.py).
* **2026-08-20**: Implemented date-filtered SP3+CLK test pair selection dialog in [main_app.py](main_app.py) and added date extraction routines in [scripts/file_parsers.py](scripts/file_parsers.py) with unit tests in [tests/test_file_date_extraction.py](tests/test_file_date_extraction.py).
* **2026-08-20**: Reworked theoretical convergence plot in [main_app.py](main_app.py) with anti-collision staggered tier labels, color-matched markers, legend integration, and a top-left summary card.
* **2026-08-28**: Prepared repository for GitHub publishing: updated [.gitignore](.gitignore), purged obsolete files and git-tracked pycache/deleted binary docs, standardized [requirements.txt](requirements.txt) to UTF-8, and enabled tracking for the [tests/](tests/) test suite.
* **2026-08-28**: Enhanced button typography across all sidebar controls and dialogs with crisp bold CTkFonts and modernized concise test pair button labels in [main_app.py](main_app.py).
* **2026-08-29**: Cleaned local Git configuration to single `main` branch tracking `origin` (removed local `dev` branch and `private` remote).
* **2026-08-29**: Modernized repository architecture: cleaned `requirements.txt` to core runtime dependencies, added standard package initializers (`__init__.py`), configured `pyproject.toml`, added `main()` entrypoint, and expanded `README.md`.

---

## 5. Active Roadmap & Future Tasks

- [x] Add unit tests for satellite filtering pattern matching ([tests/test_sat_filter.py](tests/test_sat_filter.py)).
- [x] Standardize [requirements.txt](requirements.txt) encoding across environments (UTF-8).
- [ ] Add unit tests for remaining functions in [scripts/comparison_logic.py](scripts/comparison_logic.py) and [scripts/file_parsers.py](scripts/file_parsers.py).
- [ ] Optimize memory usage when reading large multi-day SP3/CLK files.
