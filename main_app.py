import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import pandas as pd
import numpy as np
import threading
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

# Import local modules
import scripts.file_parsers as file_parsers
import scripts.comparison_logic as comparison_logic
import scripts.orchestrator as orchestrator
import scripts.export_logic as export_logic

def get_default_constellations():
    return {
        'GPS (G)': [f"G{i:02d}" for i in range(1, 33)],
        'Galileo (E)': [f"E{i:02d}" for i in range(1, 37)],
        'GLONASS (R)': [f"R{i:02d}" for i in range(1, 25)],
        'BeiDou (C)': [f"C{i:02d}" for i in range(1, 64)],
        'QZSS (J)': [f"J{i:02d}" for i in range(1, 8)],
    }

def get_all_known_satellites(extra_sats=None):
    all_sats = []
    for sats in get_default_constellations().values():
        all_sats.extend(sats)
    if extra_sats:
        for s in extra_sats:
            if s and s not in all_sats:
                all_sats.append(s)
    return sorted(list(set(all_sats)))

def compute_available_satellites_data(
    mode, 
    filepaths=None, 
    ref_basename=None,
    sisre_ref_sp3=None,
    sisre_ref_clk=None,
    sisre_pairs=None
):
    """
    Scans loaded files / test pairs to extract available satellites and single-test availability.
    """
    ref_sats = set()
    test_sats_list = [] # List of sets, one per test product

    if mode in ["SP3", "CLK"] and filepaths:
        ref_file = None
        test_files = []
        for f in filepaths:
            if ref_basename and os.path.basename(f) == ref_basename:
                ref_file = f
            else:
                test_files.append(f)
        if not ref_file and filepaths:
            ref_file = filepaths[0]
            test_files = filepaths[1:]

        if ref_file:
            ref_sats = file_parsers.extract_satellites_from_file(ref_file)

        for tf in test_files:
            s_test = file_parsers.extract_satellites_from_file(tf)
            test_sats_list.append(s_test)

    elif mode == "SISRE":
        ref_sp3_sats = file_parsers.extract_satellites_from_file(sisre_ref_sp3) if sisre_ref_sp3 else set()
        ref_clk_sats = file_parsers.extract_satellites_from_file(sisre_ref_clk) if sisre_ref_clk else set()
        if ref_sp3_sats and ref_clk_sats:
            ref_sats = ref_sp3_sats & ref_clk_sats
        else:
            ref_sats = ref_sp3_sats | ref_clk_sats

        for p in (sisre_pairs or []):
            sp3_val = p.get('sp3')
            clk_val = p.get('clk')
            if sp3_val == 'BRDC':
                s_pair = file_parsers.extract_satellites_from_file(clk_val)
            elif (isinstance(sp3_val, str) and (sp3_val.lower().endswith('.ssr') or sp3_val.split('.')[-1].lower() == 'ssr')) or p.get('ssr'):
                ssr_file = p.get('ssr') or sp3_val
                s_pair = file_parsers.extract_satellites_from_file(ssr_file)
            else:
                sp3_sats = file_parsers.extract_satellites_from_file(sp3_val) if sp3_val else set()
                clk_sats = file_parsers.extract_satellites_from_file(clk_val) if clk_val else set()
                s_pair = (sp3_sats & clk_sats) if (sp3_sats and clk_sats) else (sp3_sats | clk_sats)
            test_sats_list.append(s_pair)

    # Collect all distinct product satellite sets for comparison
    all_products = []
    if ref_sats:
        all_products.append(ref_sats)
    for s_test in test_sats_list:
        if s_test:
            all_products.append(s_test)

    # Union of all discovered satellites
    all_sats_set = set()
    for s_set in all_products:
        all_sats_set |= s_set

    # Filter for supported constellations only
    CONST_NAMES = {
        'G': 'GPS (G)',
        'E': 'Galileo (E)',
        'R': 'GLONASS (R)',
        'C': 'BeiDou (C)',
        'J': 'QZSS (J)',
    }

    all_sats = sorted([s for s in all_sats_set if s and s[0] in CONST_NAMES])
    total_products = len(all_products)

    sat_status = {}
    for sat in all_sats:
        product_count = sum(1 for s_set in all_products if sat in s_set)
        # If multiple products are loaded and satellite is not in all products -> Yellow warning
        is_yellow = (product_count < total_products) if (total_products > 1) else False

        sat_status[sat] = {
            'is_yellow': is_yellow,
            'product_count': product_count,
            'total_products': total_products,
            'in_ref': (sat in ref_sats) if ref_sats else True
        }

    # Group into constellation tabs based ONLY on available satellites
    const_groups = {}
    for sat in all_sats:
        sys = sat[0] if sat else '?'
        if sys in CONST_NAMES:
            group_name = CONST_NAMES[sys]
            const_groups.setdefault(group_name, []).append(sat)

    for k in const_groups:
        const_groups[k].sort()

    return {
        'all_sats': all_sats,
        'sat_status': sat_status,
        'const_groups': const_groups,
        'has_files': bool(all_products)
    }

def get_filter_summary_text(enabled_sats, all_sats):
    if enabled_sats is None or set(enabled_sats) == set(all_sats):
        return "All Satellites (Default)"
    if not enabled_sats:
        return "No Satellites Selected (0)"

    const_totals = {}
    const_enabled = {}
    for s in all_sats:
        sys = s[0] if s else '?'
        const_totals[sys] = const_totals.get(sys, 0) + 1
        if s in enabled_sats:
            const_enabled[sys] = const_enabled.get(sys, 0) + 1

    parts = []
    for sys in sorted(const_totals.keys()):
        cnt = const_enabled.get(sys, 0)
        tot = const_totals[sys]
        if cnt == tot and tot > 0:
            parts.append(f"{sys}:All")
        elif cnt > 0:
            parts.append(f"{sys}:{cnt}/{tot}")

    if not parts:
        return f"Custom ({len(enabled_sats)} sats)"
    return ", ".join(parts)

def build_sat_filter_structures(enabled_sats, all_sats):
    """
    Converts enabled satellites set into target_sats_filter and excluded_sats_filter
    matching comparison_logic pattern format: {'exact': [...], 'prefix': [...]}.
    """
    if enabled_sats is None or set(enabled_sats) == set(all_sats):
        return None, None

    enabled_set = set(enabled_sats)
    all_set = set(all_sats)

    if not enabled_set:
        return {'exact': ['NONE'], 'prefix': []}, None

    # Group all_sats by constellation prefix
    constellations = {}
    for sat in all_set:
        sys = sat[0] if sat else '?'
        constellations.setdefault(sys, []).append(sat)

    target_exact = []
    target_prefix = []
    excluded_exact = []

    for sys, sats in sorted(constellations.items()):
        sys_sats = set(sats)
        sys_enabled = sys_sats & enabled_set
        sys_disabled = sys_sats - enabled_set

        if len(sys_enabled) == 0:
            continue
        elif len(sys_enabled) == len(sys_sats):
            target_prefix.append(sys)
        elif len(sys_disabled) <= 5:
            target_prefix.append(sys)
            excluded_exact.extend(sorted(sys_disabled))
        elif len(sys_enabled) <= 5:
            target_exact.extend(sorted(sys_enabled))
        else:
            target_prefix.append(sys)
            excluded_exact.extend(sorted(sys_disabled))

    target_filter = {'exact': target_exact, 'prefix': target_prefix} if (target_exact or target_prefix) else None
    excluded_filter = {'exact': excluded_exact, 'prefix': []} if excluded_exact else None

    return target_filter, excluded_filter


class SatelliteFilterDialog(ctk.CTkToplevel):
    def __init__(self, parent, current_enabled_sats=None, available_data=None, on_apply=None):
        super().__init__(parent)
        self.parent = parent
        self.on_apply = on_apply

        self.title("Satellite Filter Configuration")

        if available_data and available_data.get('has_files') and available_data.get('all_sats'):
            self.const_groups = {k: list(v) for k, v in available_data.get('const_groups', {}).items() if v}
            self.all_sats = list(available_data.get('all_sats', []))
            self.sat_status = available_data.get('sat_status', {})
            self.has_files = True
        else:
            default_groups = get_default_constellations()
            self.const_groups = {k: list(v) for k, v in default_groups.items()}
            self.all_sats = get_all_known_satellites()
            self.sat_status = {sat: {'is_yellow': False, 'test_count': 0, 'total_tests': 0, 'in_ref': True} for sat in self.all_sats}
            self.has_files = False

        # Satellite boolean variables
        self.sat_vars = {}
        for sat in self.all_sats:
            if current_enabled_sats is None:
                self.sat_vars[sat] = tk.BooleanVar(value=True)
            else:
                self.sat_vars[sat] = tk.BooleanVar(value=(sat in current_enabled_sats))

        self.sat_checkboxes = {}
        self.const_count_labels = {}

        self._build_ui()

        # Non-modal companion window (keeps on top of parent, allows full interaction with main window)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        # Position sticky to right edge of main window with identical height
        self.parent.update_idletasks()
        parent_x = self.parent.winfo_x()
        parent_y = self.parent.winfo_y()
        parent_w = self.parent.winfo_width()
        parent_h = self.parent.winfo_height()

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        w = 580
        h = max(parent_h, 500)
        x = parent_x + parent_w
        if x + w > screen_w and parent_x - w >= 0:
            x = parent_x - w
        elif x + w > screen_w:
            x = max(screen_w - w, 0)
        y = max(min(parent_y, screen_h - h - 40), 0)

        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(450, 400)

    def _build_ui(self):
        # 1. Header Frame
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(10, 5))

        top_row = ctk.CTkFrame(header_frame, fg_color="transparent")
        top_row.pack(fill="x", pady=(0, 5))

        lbl_title = ctk.CTkLabel(
            top_row,
            text="Satellite Selection Filter",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        lbl_title.pack(side="left")

        self.lbl_global_count = ctk.CTkLabel(
            top_row,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#3498DB"
        )
        self.lbl_global_count.pack(side="right")

        # Search & Global Actions Bar
        actions_row = ctk.CTkFrame(header_frame, fg_color="transparent")
        actions_row.pack(fill="x", pady=2)

        self.search_entry = ctk.CTkEntry(
            actions_row,
            placeholder_text="Search satellites (e.g. G01, E)...",
            width=180,
            height=28
        )
        self.search_entry.pack(side="left", padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", self._on_search)

        btn_all = ctk.CTkButton(
            actions_row, text="Select All", width=75, height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._select_all_global
        )
        btn_all.pack(side="left", padx=2)

        btn_none = ctk.CTkButton(
            actions_row, text="Deselect All", width=80, height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#555", hover_color="#777",
            command=self._deselect_all_global
        )
        btn_none.pack(side="left", padx=2)

        btn_invert = ctk.CTkButton(
            actions_row, text="Invert", width=60, height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#555", hover_color="#777",
            command=self._invert_selection_global
        )
        btn_invert.pack(side="left", padx=2)

        btn_reset = ctk.CTkButton(
            actions_row, text="Reset", width=60, height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#C0392B", hover_color="#E74C3C",
            command=self._select_all_global
        )
        btn_reset.pack(side="left", padx=2)

        # Status / Notice label
        yellow_count = sum(1 for s in self.sat_status.values() if s.get('is_yellow'))
        if yellow_count > 0:
            lbl_notice = ctk.CTkLabel(
                header_frame,
                text=f" {yellow_count} satellite(s) are not available in all files",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#B7950B", "#F1C40F"),
                anchor="w"
            )
            lbl_notice.pack(fill="x", pady=(3, 0))
        elif not self.has_files:
            lbl_notice = ctk.CTkLabel(
                header_frame,
                text="No files loaded yet. Showing standard constellation template.",
                font=ctk.CTkFont(size=11),
                text_color="gray",
                anchor="w"
            )
            lbl_notice.pack(fill="x", pady=(3, 0))

        # 2. Center TabView for Constellations (expands to full available window height)
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=15, pady=5)

        for grp_name, sats in self.const_groups.items():
            self.tabview.add(grp_name)
            tab_frame = self.tabview.tab(grp_name)

            # Toolbar for this constellation
            c_toolbar = ctk.CTkFrame(tab_frame, fg_color="transparent")
            c_toolbar.pack(fill="x", padx=5, pady=(2, 6))

            btn_c_all = ctk.CTkButton(
                c_toolbar, text=f"Select All in {grp_name.split()[0]}",
                width=150, height=26,
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda g=grp_name: self._set_constellation(g, True)
            )
            btn_c_all.pack(side="left", padx=(0, 6))

            btn_c_none = ctk.CTkButton(
                c_toolbar, text=f"Deselect All in {grp_name.split()[0]}",
                width=150, height=26,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#555", hover_color="#777",
                command=lambda g=grp_name: self._set_constellation(g, False)
            )
            btn_c_none.pack(side="left", padx=6)

            cnt_lbl = ctk.CTkLabel(
                c_toolbar, text="", font=ctk.CTkFont(size=12, weight="bold")
            )
            cnt_lbl.pack(side="right", padx=5)
            self.const_count_labels[grp_name] = cnt_lbl

            # Scrollable Checkbox Grid (fills full tab area)
            scroll = ctk.CTkScrollableFrame(tab_frame)
            scroll.pack(fill="both", expand=True, padx=5, pady=2)

            cols = 6
            for idx, sat_id in enumerate(sats):
                row = idx // cols
                col = idx % cols
                stat = self.sat_status.get(sat_id, {})
                is_yellow = stat.get('is_yellow', False)

                cb_color = ("#B7950B", "#F1C40F") if is_yellow else None
                cb_text = f"{sat_id} ⚠️" if is_yellow else sat_id

                cb = ctk.CTkCheckBox(
                    scroll,
                    text=cb_text,
                    variable=self.sat_vars[sat_id],
                    command=self._update_counts,
                    width=85 if is_yellow else 75,
                    text_color=cb_color,
                    font=ctk.CTkFont(size=12, weight="bold")
                )
                cb.grid(row=row, column=col, padx=6, pady=5, sticky="w")
                self.sat_checkboxes[sat_id] = cb

        # 3. Footer Frame
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=15, pady=(5, 12))

        self.lbl_footer_summary = ctk.CTkLabel(
            footer, text="", text_color="gray", font=ctk.CTkFont(size=11), anchor="w"
        )
        self.lbl_footer_summary.pack(side="left", fill="x", expand=True)

        btn_close = ctk.CTkButton(
            footer, text="Close", width=75, height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#555", hover_color="#777",
            command=self.destroy
        )
        btn_close.pack(side="right", padx=(8, 0))

        btn_apply = ctk.CTkButton(
            footer, text="Apply", width=85, height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2E86AB", hover_color="#3B9EC6",
            command=self._apply
        )
        btn_apply.pack(side="right")

        self._update_counts()

    def _update_counts(self):
        total_enabled = sum(1 for v in self.sat_vars.values() if v.get())
        total_sats = len(self.sat_vars)
        self.lbl_global_count.configure(
            text=f"Selected: {total_enabled} / {total_sats} satellites"
        )

        for grp_name, sats in self.const_groups.items():
            cnt = sum(1 for s in sats if self.sat_vars[s].get())
            tot = len(sats)
            self.const_count_labels[grp_name].configure(
                text=f"{cnt} / {tot} enabled"
            )

        enabled_set = {s for s, v in self.sat_vars.items() if v.get()}
        summary = get_filter_summary_text(enabled_set, self.all_sats)
        self.lbl_footer_summary.configure(text=f"Active filter: {summary}")

    def _set_constellation(self, grp_name, enabled):
        sats = self.const_groups.get(grp_name, [])
        for s in sats:
            self.sat_vars[s].set(enabled)
        self._update_counts()

    def _select_all_global(self):
        for v in self.sat_vars.values():
            v.set(True)
        self._update_counts()

    def _deselect_all_global(self):
        for v in self.sat_vars.values():
            v.set(False)
        self._update_counts()

    def _invert_selection_global(self):
        for v in self.sat_vars.values():
            v.set(not v.get())
        self._update_counts()

    def _on_search(self, event=None):
        query = self.search_entry.get().strip().upper()
        for sat_id, cb in self.sat_checkboxes.items():
            if not query or query in sat_id:
                cb.grid()
            else:
                cb.grid_remove()

    def _apply(self):
        enabled_sats = {s for s, v in self.sat_vars.items() if v.get()}
        if self.on_apply:
            self.on_apply(enabled_sats, self.all_sats)

    def destroy(self):
        if hasattr(self.parent, 'sat_filter_dialog') and self.parent.sat_filter_dialog is self:
            self.parent.sat_filter_dialog = None
        super().destroy()

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Data storage
        self.filepaths = []
        self.results = {}
        self.results_metadata = {}  # Store metadata like avg_satellites per result
        self.results_by_mode = {}  # Store results per mode: {'SP3': {...}, 'CLK': {...}, 'SISRE': {...}}
        self.mode_states = {}  # Store complete app state per mode: {'SP3': {...}, 'CLK': {...}, 'SISRE': {...}}
        self._current_mode = "SP3"
        self.cov_results = {} # Covariance simulation results
        
        # SISRE Mode Storage
        self.sisre_ref_sp3 = None
        self.sisre_ref_clk = None
        self.sisre_pairs = [] # List of dicts: {'name': str, 'sp3': path, 'clk': clk, 'atx': path, 'sis_corrections': bool}
        # Satellite Filters
        self.enabled_satellites = None  # None indicates all satellites enabled
        self.target_sats_filter = None
        self.excluded_sats_filter = None
        self.sat_filter_dialog = None

        # Window Configuration
        self.title("GNSS Product Comparator")
        self.geometry("1100x900")
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ==============================
        # LEFT FRAME (Sidebar)
        # ==============================
        self.sidebar_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)
        
        # Create scrollable frame for sidebar content
        self.sidebar_scroll = ctk.CTkScrollableFrame(self.sidebar_frame, width=250)
        self.sidebar_scroll.pack(side="top", fill="both", expand=True)
        self.sidebar_scroll.grid_columnconfigure(0, weight=1)
        
        # 1. Title
        self.logo_label = ctk.CTkLabel(self.sidebar_scroll, text="Configuration", 
                                       font=ctk.CTkFont(size=16, weight="bold"))
        self.logo_label.pack(padx=15, pady=(8, 3), fill="x")

        # 2. Product Type
        self.type_label = ctk.CTkLabel(self.sidebar_scroll, text="Analysis Mode:", anchor="w")
        self.type_label.pack(padx=15, pady=(3, 2), fill="x")

        # Added "SISRE" to values and command callback
        self.product_type_seg = ctk.CTkSegmentedButton(self.sidebar_scroll, 
                                                       values=["SP3", "CLK", "SISRE"],
                                                       command=self.toggle_mode,
                                                       font=ctk.CTkFont(size=12, weight="bold"),
                                                       height=28)
        self.product_type_seg.pack(padx=15, pady=(2, 3), fill="x")
        self.product_type_seg.set("SP3") 

        # --- STANDARD MODE WIDGETS (SP3/CLK) ---
        self.frame_standard = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent")
        self.frame_standard.pack(padx=0, pady=3, fill="x")
        
        self.select_files_btn = ctk.CTkButton(self.frame_standard, text="Select Files...", 
                                              command=self.select_files_standard, 
                                              font=ctk.CTkFont(size=12, weight="bold"), 
                                              height=28) 
        self.select_files_btn.pack(padx=15, pady=3, fill="x")

        self.ref_label = ctk.CTkLabel(self.frame_standard, text="Select Reference File:", anchor="w")
        self.ref_label.pack(padx=15, pady=(3, 2), fill="x")

        self.ref_file_dropdown = ctk.CTkComboBox(self.frame_standard, values=[], state="disabled", height=26, command=self.on_ref_file_dropdown_changed) 
        self.ref_file_dropdown.pack(padx=15, pady=(2, 3), fill="x")

        # --- SISRE MODE WIDGETS (Hidden by default) ---
        self.frame_sisre = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent")
        # Don't pack initially
        
        self.lbl_ref_section = ctk.CTkLabel(self.frame_sisre, text="1. Reference Product", font=ctk.CTkFont(weight="bold"))
        self.lbl_ref_section.pack(padx=15, pady=(3, 2), anchor="w")

        self.btn_ref_sp3 = ctk.CTkButton(self.frame_sisre, text="Select SP3", fg_color="#555", hover_color="#666",
                                         command=self.select_sisre_ref_sp3, 
                                         font=ctk.CTkFont(size=12, weight="bold"), 
                                         height=28)
        self.btn_ref_sp3.pack(padx=15, pady=2, fill="x")
        
        self.btn_ref_clk = ctk.CTkButton(self.frame_sisre, text="Select CLK", fg_color="#555", hover_color="#666",
                                         command=self.select_sisre_ref_clk, 
                                         font=ctk.CTkFont(size=12, weight="bold"), 
                                         height=28)
        self.btn_ref_clk.pack(padx=15, pady=2, fill="x")

        self.lbl_test_section = ctk.CTkLabel(self.frame_sisre, text="2. Test Products", font=ctk.CTkFont(weight="bold"))
        self.lbl_test_section.pack(padx=15, pady=(3, 2), anchor="w")

        self.btn_add_pair = ctk.CTkButton(self.frame_sisre, text="Add SP3/CLK pair", 
                                          command=self.add_sisre_pair, 
                                          font=ctk.CTkFont(size=12, weight="bold"), 
                                          height=28)
        self.btn_add_pair.pack(padx=15, pady=2, fill="x")

        self.btn_add_pair_HAS = ctk.CTkButton(self.frame_sisre, text="Add SSR products", 
                                              command=self.add_HAS_pair, 
                                              font=ctk.CTkFont(size=12, weight="bold"), 
                                              height=28)
        self.btn_add_pair_HAS.pack(padx=15, pady=2, fill="x")

        self.btn_add_pair_BRDC = ctk.CTkButton(self.frame_sisre, text="Add Broadcast ephemeris", 
                                               command=self.add_BRDC_pair, 
                                               font=ctk.CTkFont(size=12, weight="bold"), 
                                               height=28)
        self.btn_add_pair_BRDC.pack(padx=15, pady=2, fill="x")

        self.btn_remove_last = ctk.CTkButton(self.frame_sisre, text="Remove Last", 
                                             fg_color="#A94442", hover_color="#D6655D", 
                                             command=self.remove_last_pair, 
                                             font=ctk.CTkFont(size=11, weight="bold"), 
                                             height=26)
        self.btn_remove_last.pack(padx=15, pady=2, fill="x")
        
        self.pairs_textbox = ctk.CTkTextbox(self.frame_sisre, height=60)
        self.pairs_textbox.pack(padx=15, pady=2, fill="x")
        self.pairs_textbox.insert("0.0", "No pairs added.")
        self.pairs_textbox.configure(state="disabled")

        # --- SATELLITE FILTER WIDGETS ---
        self.btn_sat_filter = ctk.CTkButton(
            self.sidebar_scroll,
            text="Satellite Filter...",
            command=self.open_sat_filter_dialog,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=28
        )
        self.btn_sat_filter.pack(padx=15, pady=(4, 2), fill="x")

        self.sat_filter_status_label = ctk.CTkLabel(
            self.sidebar_scroll,
            text="All Satellites (Default)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#1B5E20", "#2ECC71"),
            wraplength=200
        )
        self.sat_filter_status_label.pack(padx=15, pady=(0, 4), fill="x")

        self.legend_var = tk.BooleanVar(value=True)
        self.legend_checkbox = ctk.CTkCheckBox(self.sidebar_scroll, text="Show Legend", variable=self.legend_var, command=self.draw_plots)
        self.legend_checkbox.pack(padx=15, pady=(3, 6), anchor="w")

        # --- USER LOCATION (For Elevation Masking) ---
        
        self.loc_label = ctk.CTkLabel(self.sidebar_scroll, text="User Location (Degrees), Height in m:", anchor="w")
        self.loc_label.pack(padx=15, pady=(5, 2), fill="x")

        self.loc_frame = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent")
        self.loc_frame.pack(padx=15, pady=(2, 3), fill="x")

        self.lat_entry = ctk.CTkEntry(self.loc_frame, placeholder_text="Latitude", height=26, width=100)
        self.lat_entry.grid(row=0, column=0, padx=5, pady=2)

        self.lon_entry = ctk.CTkEntry(self.loc_frame, placeholder_text="Longitude", height=26, width=100)
        self.lon_entry.grid(row=0, column=1, padx=5, pady=2)

        self.h_entry = ctk.CTkEntry(self.loc_frame, placeholder_text="Height", height=26, width=100)
        self.h_entry.grid(row=1, column=0, padx=5, pady=2)

        self.el_entry = ctk.CTkEntry(self.loc_frame, placeholder_text="Elevation angle cutoff", height=26, width=100)
        self.el_entry.grid(row=1, column=1, padx=5, pady=2)      

        # --- COVARIANCE SIMULATION (SISRE Mode only) ---
        self.cov_frame = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent")
        # Hidden by default; packed only when in SISRE mode
        
        self.cov_var = tk.BooleanVar(value=False)
        self.cov_checkbox = ctk.CTkCheckBox(self.cov_frame, text="Covariance Sim", variable=self.cov_var, state="disabled", command=self.toggle_cov_duration)
        self.cov_checkbox.grid(row=0, column=0, padx=5, pady=2, sticky="w")
        
        self.cov_duration_entry = ctk.CTkEntry(self.cov_frame, placeholder_text="Duration (hrs)", height=26, width=100, state="disabled")
        self.cov_duration_entry.grid(row=0, column=1, padx=5, pady=2, sticky="w")

        self.cov_horiz_thresh_entry = ctk.CTkEntry(self.cov_frame, placeholder_text="H-Thresh (m)", height=26, width=100, state="disabled")
        self.cov_horiz_thresh_entry.grid(row=1, column=0, padx=5, pady=2, sticky="w")
        
        self.cov_vert_thresh_entry = ctk.CTkEntry(self.cov_frame, placeholder_text="V-Thresh (m)", height=26, width=100, state="disabled")
        self.cov_vert_thresh_entry.grid(row=1, column=1, padx=5, pady=2, sticky="w")

        # Bind events to check location inputs
        self.lat_entry.bind("<KeyRelease>", self.check_location_inputs)
        self.lon_entry.bind("<KeyRelease>", self.check_location_inputs)
        self.h_entry.bind("<KeyRelease>", self.check_location_inputs)
        self.el_entry.bind("<KeyRelease>", self.check_location_inputs)

        self.run_btn = ctk.CTkButton(self.sidebar_scroll, text="RUN ANALYSIS", 
                                     fg_color="transparent", border_width=2, 
                                     text_color=("gray10", "#DCE4EE"), state="disabled",
                                     command=self.run_comparison, 
                                     font=ctk.CTkFont(size=12, weight="bold"),
                                     height=28)
        self.run_btn.pack(padx=15, pady=2, fill="x")
        
        self.export_btn = ctk.CTkButton(self.sidebar_scroll, text="EXPORT STATISTICS", 
                                        fg_color="transparent", border_width=2, 
                                        text_color=("gray10", "#DCE4EE"), state='disabled',
                                        command=self.export_statistics, 
                                        font=ctk.CTkFont(size=12, weight="bold"),
                                        height=28)
        self.export_btn.pack(padx=15, pady=2, fill="x")

        self.reset_btn = ctk.CTkButton(self.sidebar_scroll, text="RESET", 
                                       fg_color="#C0392B", hover_color="#E74C3C",
                                       command=self.reset_app, 
                                       font=ctk.CTkFont(size=12, weight="bold"),
                                       height=28)
        self.reset_btn.pack(padx=15, pady=2, fill="x")

        self.status_label = ctk.CTkLabel(self.sidebar_scroll, text="Ready.", text_color="gray", wraplength=200)
        self.status_label.pack(padx=15, pady=2, fill="x")
        
        # Progress bar for parse_rnx (hidden by default)
        self.progress_bar = ctk.CTkProgressBar(self.sidebar_scroll, width=200)
        self.progress_bar.pack(padx=15, pady=2, fill="x")
        self.progress_bar.set(0)
        self.progress_bar.pack_forget()  # Hidden initially

        # ==============================
        # RIGHT FRAME (Plots)
        # ==============================
        self.plots_frame = ctk.CTkFrame(self)
        self.plots_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.plots_frame.grid_rowconfigure(0, weight=1)
        self.plots_frame.grid_columnconfigure(0, weight=1)

        self.plot_tabview = ctk.CTkTabview(self.plots_frame)
        self.plot_tabview.grid(row=0, column=0, sticky="nsew")

    def check_location_inputs(self, event=None):
        mode = getattr(self, '_current_mode', None) or self.product_type_seg.get()
        if mode == "SISRE" and self.lat_entry.get().strip() and self.lon_entry.get().strip() and \
           self.h_entry.get().strip() and self.el_entry.get().strip():
            self.cov_checkbox.configure(state="normal")
        else:
            self.cov_checkbox.configure(state="disabled")
            self.cov_var.set(False)
            self.cov_duration_entry.configure(state="disabled")
            self.cov_horiz_thresh_entry.configure(state="disabled")
            self.cov_vert_thresh_entry.configure(state="disabled")

    def toggle_cov_duration(self):
        if self.cov_var.get():
            self.cov_duration_entry.configure(state="normal")
            self.cov_horiz_thresh_entry.configure(state="normal")
            self.cov_vert_thresh_entry.configure(state="normal")
        else:
            self.cov_duration_entry.configure(state="disabled")
            self.cov_horiz_thresh_entry.configure(state="disabled")
            self.cov_vert_thresh_entry.configure(state="disabled")

    def toggle_mode(self, value):
        """Switches the sidebar interface based on selected mode without resetting existing plots."""
        # 1. Save current mode state
        prev_mode = getattr(self, '_current_mode', None) or self.product_type_seg.get()
        if prev_mode:
            self.mode_states[prev_mode] = {
                'results': self.results,
                'results_metadata': self.results_metadata,
                'cov_results': self.cov_results,
                'filepaths': list(self.filepaths),
                'ref_basename': self.ref_file_dropdown.get() if hasattr(self, 'ref_file_dropdown') else "",
                'sisre_ref_sp3': self.sisre_ref_sp3,
                'sisre_ref_clk': self.sisre_ref_clk,
                'sisre_pairs': list(self.sisre_pairs),
                'enabled_satellites': set(self.enabled_satellites) if self.enabled_satellites is not None else None,
                'target_sats_filter': self.target_sats_filter,
                'excluded_sats_filter': self.excluded_sats_filter,
            }

        self._current_mode = value

        # 2. Switch Sidebar UI Frames
        if value == "SISRE":
            self.frame_standard.pack_forget()
            self.frame_sisre.pack(padx=0, pady=3, fill="x", before=self.btn_sat_filter)
            self.cov_frame.pack(padx=15, pady=(2, 3), fill="x", before=self.run_btn)
            self.status_label.configure(text="SISRE Mode: Select Reference SP3 & CLK, then add Test Pairs.")
        else:
            self.frame_sisre.pack_forget()
            self.frame_standard.pack(padx=0, pady=3, fill="x", before=self.btn_sat_filter)
            self.cov_frame.pack_forget()
            self.status_label.configure(text=f"{value} Mode: Select files to compare.")

        self.check_location_inputs()

        # 3. Load target mode state
        target_state = self.mode_states.get(value, {})
        self.results = target_state.get('results', {})
        self.results_metadata = target_state.get('results_metadata', {})
        self.cov_results = target_state.get('cov_results', {})
        self.filepaths = target_state.get('filepaths', [])
        self.sisre_ref_sp3 = target_state.get('sisre_ref_sp3', None)
        self.sisre_ref_clk = target_state.get('sisre_ref_clk', None)
        self.sisre_pairs = target_state.get('sisre_pairs', [])
        self.enabled_satellites = target_state.get('enabled_satellites', None)
        self.target_sats_filter = target_state.get('target_sats_filter', None)
        self.excluded_sats_filter = target_state.get('excluded_sats_filter', None)

        all_sats = self.get_available_satellites()
        summary = get_filter_summary_text(self.enabled_satellites, all_sats)
        self.sat_filter_status_label.configure(
            text=summary,
            text_color=("#1B5E20", "#2ECC71")
        )

        # Update UI Controls for target mode
        if value in ["SP3", "CLK"]:
            if self.filepaths:
                basenames = [os.path.basename(f) for f in self.filepaths]
                ref_bname = target_state.get('ref_basename', basenames[0] if basenames else "")
                self.ref_file_dropdown.configure(values=basenames, state="normal")
                self.ref_file_dropdown.set(ref_bname if ref_bname in basenames else (basenames[0] if basenames else ""))
                self.run_btn.configure(state="normal")
            else:
                self.ref_file_dropdown.set("")
                self.ref_file_dropdown.configure(values=[], state="disabled")
                self.run_btn.configure(state="disabled")
            self.export_btn.configure(state="normal" if self.results else "disabled")
        else: # SISRE
            self.btn_ref_sp3.configure(text=f"SP3: {os.path.basename(self.sisre_ref_sp3)}" if self.sisre_ref_sp3 else "Select Ref SP3")
            self.btn_ref_clk.configure(text=f"CLK: {os.path.basename(self.sisre_ref_clk)}" if self.sisre_ref_clk else "Select Ref CLK")
            self._refresh_pairs_text()
            self.check_sisre_ready()
            self.export_btn.configure(state="normal" if self.results else "disabled")

        self._refresh_sat_filter_for_loaded_files()

        # 4. Redraw plots for target mode if results exist
        if self.results:
            self.draw_plots()

    def get_current_available_satellites_data(self):
        """Extracts available satellites and single-test flags from uploaded files/pairs."""
        mode = getattr(self, '_current_mode', None) or self.product_type_seg.get()
        ref_bname = self.ref_file_dropdown.get() if hasattr(self, 'ref_file_dropdown') else ""
        return compute_available_satellites_data(
            mode=mode,
            filepaths=self.filepaths,
            ref_basename=ref_bname,
            sisre_ref_sp3=self.sisre_ref_sp3,
            sisre_ref_clk=self.sisre_ref_clk,
            sisre_pairs=self.sisre_pairs
        )

    def get_available_satellites(self):
        """Returns any satellite IDs present in currently loaded files or results."""
        avail_data = self.get_current_available_satellites_data()
        sats = set(avail_data.get('all_sats', []))
        if self.results:
            for df in self.results.values():
                if isinstance(df.index, pd.MultiIndex) and 'SatID' in df.index.names:
                    sats.update(df.index.get_level_values('SatID').unique().tolist())
                elif 'SatID' in df.columns:
                    sats.update(df['SatID'].unique().tolist())
        return sorted(list(sats)) if sats else get_all_known_satellites()

    def _refresh_sat_filter_for_loaded_files(self):
        """Refreshes active satellite filters and status label based on loaded files."""
        avail_data = self.get_current_available_satellites_data()
        all_sats = avail_data.get('all_sats', [])
        if avail_data.get('has_files') and all_sats:
            if self.enabled_satellites is not None:
                valid_enabled = self.enabled_satellites & set(all_sats)
                if valid_enabled and valid_enabled != set(all_sats):
                    self.enabled_satellites = valid_enabled
                else:
                    self.enabled_satellites = None
            self._update_sat_filter_structures(all_sats)
            summary = get_filter_summary_text(self.enabled_satellites, all_sats)
            self.sat_filter_status_label.configure(
                text=summary,
                text_color=("#1B5E20", "#2ECC71")
            )

    def on_ref_file_dropdown_changed(self, choice=None):
        """Called when user changes reference file in SP3/CLK mode."""
        self._refresh_sat_filter_for_loaded_files()

    def open_sat_filter_dialog(self):
        if getattr(self, 'sat_filter_dialog', None) is not None:
            try:
                if self.sat_filter_dialog.winfo_exists():
                    self.sat_filter_dialog.lift()
                    self.sat_filter_dialog.focus()
                    return
            except Exception:
                self.sat_filter_dialog = None

        avail_data = self.get_current_available_satellites_data()
        self.sat_filter_dialog = SatelliteFilterDialog(
            parent=self,
            current_enabled_sats=self.enabled_satellites,
            available_data=avail_data,
            on_apply=self.on_sat_filter_applied
        )

    def on_sat_filter_applied(self, enabled_sats, all_sats):
        if enabled_sats is not None and set(enabled_sats) == set(all_sats):
            self.enabled_satellites = None
        else:
            self.enabled_satellites = set(enabled_sats) if enabled_sats is not None else None

        self._update_sat_filter_structures(all_sats)
        summary = get_filter_summary_text(self.enabled_satellites, all_sats)
        self.sat_filter_status_label.configure(
            text=summary,
            text_color=("#1B5E20", "#2ECC71")
        )

        if self.results:
            self.draw_plots()

    def _update_sat_filter_structures(self, all_sats=None):
        if all_sats is None:
            all_sats = self.get_available_satellites()
        self.target_sats_filter, self.excluded_sats_filter = build_sat_filter_structures(
            self.enabled_satellites, all_sats
        )
    
    def update_rnx_progress(self, current, total, sat_id):
        """Callback for parse_rnx or orchestrator to update progress bar (thread-safe)."""
        def update():
            if not self.progress_bar.winfo_ismapped():
                self.progress_bar.pack(padx=15, pady=(4, 4), fill="x", before=self.status_label)
            progress = (current + 1) / total if total > 0 else 0
            self.progress_bar.set(progress)
            self.status_label.configure(text=f"Processing {sat_id} ({current + 1}/{total})", text_color="blue")
            self.update_idletasks()
        # Schedule UI update on main thread
        self.after(0, update)
    
    def update_status_threadsafe(self, text, color="blue"):
        """Thread-safe status label update."""
        def update():
            self.status_label.configure(text=text, text_color=color)
            self.update_idletasks()
        self.after(0, update)

    # --- STANDARD MODE HANDLERS ---
    def select_files_standard(self):
        ftype = self.product_type_seg.get()
        ext = ["*.sp3", "*.SP3"] if ftype == "SP3" else ["*.clk", "*.CLK"]
        files = filedialog.askopenfilenames(title=f"Select {ftype} Files", filetypes=[(f"{ftype} Files", ext)])
        if files:
            self.filepaths = list(files)
            basenames = [os.path.basename(f) for f in self.filepaths]
            self.ref_file_dropdown.configure(values=basenames, state="normal")
            self.ref_file_dropdown.set(basenames[0])
            self.run_btn.configure(state="normal")
            self.status_label.configure(text=f"Selected {len(files)} files.", text_color="green")
            self._refresh_sat_filter_for_loaded_files()

    # --- SISRE MODE HANDLERS ---
    def select_sisre_ref_sp3(self):
        f = filedialog.askopenfilename(title="Select Reference SP3", filetypes=[("SP3", ["*.sp3", "*.SP3"])])
        if f:
            self.sisre_ref_sp3 = f
            self.btn_ref_sp3.configure(text=f"SP3: {os.path.basename(f)}")
            self.check_sisre_ready()
            self._refresh_sat_filter_for_loaded_files()

    def select_sisre_ref_clk(self):
        f = filedialog.askopenfilename(title="Select Reference CLK", filetypes=[("CLK", ["*.clk", "*.CLK"])])
        if f:
            self.sisre_ref_clk = f
            self.btn_ref_clk.configure(text=f"CLK: {os.path.basename(f)}")
            self.check_sisre_ready()
            self._refresh_sat_filter_for_loaded_files()

    def add_sisre_pair(self):
        # 1. Ensure reference files are selected to determine the target date
        ref_file = self.sisre_ref_sp3 or self.sisre_ref_clk
        if not ref_file or not os.path.exists(ref_file):
            messagebox.showwarning(
                "Reference File Required",
                "Please select a Reference SP3 or Reference CLK file first so the reference date can be established."
            )
            return

        ref_date = file_parsers.extract_file_date(ref_file)
        if not ref_date:
            messagebox.showwarning(
                "Unknown Reference Date",
                f"Could not determine the date from the reference file:\n{os.path.basename(ref_file)}\n\n"
                "Please ensure the reference file contains standard header/epoch data or standard naming."
            )
            return

        from datetime import date
        date_str = ref_date.strftime('%Y-%m-%d')
        doy = ref_date.timetuple().tm_yday
        gps_epoch = date(1980, 1, 6)
        gps_days = (ref_date - gps_epoch).days
        gps_week = gps_days // 7
        gps_dow = gps_days % 7
        date_badge = f"{date_str} (DOY {doy:03d} | GPS Week {gps_week}-{gps_dow})"

        initial_dir = os.path.dirname(ref_file)
        current_dir = [initial_dir]

        ref_sp3_norm = os.path.normpath(os.path.abspath(self.sisre_ref_sp3)) if self.sisre_ref_sp3 else None
        ref_clk_norm = os.path.normpath(os.path.abspath(self.sisre_ref_clk)) if self.sisre_ref_clk else None

        # Basename -> Full Path mappings
        sp3_files_map = {}
        clk_files_map = {}

        def scan_files_for_date(folder):
            sp3_map = {}
            clk_map = {}
            if os.path.isdir(folder):
                try:
                    for entry in os.scandir(folder):
                        if entry.is_file():
                            entry_path_norm = os.path.normpath(os.path.abspath(entry.path))
                            # Hide reference files from test selection
                            if ref_sp3_norm and entry_path_norm == ref_sp3_norm:
                                continue
                            if ref_clk_norm and entry_path_norm == ref_clk_norm:
                                continue

                            lower = entry.name.lower()
                            if lower.endswith(('.sp3', '.sp3c', '.sp3d')):
                                f_date = file_parsers.extract_file_date(entry.path)
                                if f_date == ref_date:
                                    sp3_map[entry.name] = entry.path
                            elif lower.endswith(('.clk', '.clk_30s', '.clk_05s')):
                                f_date = file_parsers.extract_file_date(entry.path)
                                if f_date == ref_date:
                                    clk_map[entry.name] = entry.path
                except Exception as e:
                    print(f"Error scanning directory {folder}: {e}")
            return sp3_map, clk_map

        # Dialog Setup
        dlg = tk.Toplevel(self)
        dlg.title(f"Add SP3 + CLK Test Pair — Date: {date_str}")
        self.update_idletasks()
        parent_x = self.winfo_rootx()
        parent_y = self.winfo_rooty()
        parent_width = self.winfo_width()
        parent_height = self.winfo_height()
        dlg.transient(self)

        container = ctk.CTkFrame(dlg)
        container.pack(fill="both", expand=True, padx=14, pady=14)

        # Header Info Card
        header_card = ctk.CTkFrame(container, fg_color=("gray85", "gray20"), corner_radius=6)
        header_card.pack(fill="x", pady=(0, 10))

        lbl_date_info = ctk.CTkLabel(
            header_card, 
            text=f"Reference Date: {date_badge}", 
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#1B5E20", "#2ECC71")
        )
        lbl_date_info.pack(anchor="w", padx=10, pady=(8, 4))

        folder_frame = ctk.CTkFrame(header_card, fg_color="transparent")
        folder_frame.pack(fill="x", padx=10, pady=(2, 8))

        lbl_folder = ctk.CTkLabel(
            folder_frame, 
            text=f"Folder: {os.path.abspath(initial_dir)}", 
            font=ctk.CTkFont(size=12),
            text_color=("gray20", "gray80"),
            anchor="w",
            justify="left",
            wraplength=420
        )
        lbl_folder.pack(side="left", fill="x", expand=True)

        def on_change_folder():
            new_f = filedialog.askdirectory(initialdir=current_dir[0], title="Select Folder Containing SP3/CLK Files")
            if new_f and os.path.isdir(new_f):
                current_dir[0] = os.path.abspath(new_f)
                lbl_folder.configure(text=f"Folder: {current_dir[0]}")
                refresh_dropdowns()

        btn_chg_folder = ctk.CTkButton(
            folder_frame, 
            text="Change Folder...", 
            width=115, 
            height=26, 
            font=ctk.CTkFont(size=11, weight="bold"),
            command=on_change_folder
        )
        btn_chg_folder.pack(side="right", padx=(6, 0))

        # SP3 Row
        lbl_sp3_sec = ctk.CTkLabel(container, text="1. Select Test SP3 File:", font=ctk.CTkFont(weight="bold"), anchor="w")
        lbl_sp3_sec.pack(fill="x", pady=(4, 2))

        sp3_row = ctk.CTkFrame(container, fg_color="transparent")
        sp3_row.pack(fill="x", pady=(0, 6))

        sp3_var = tk.StringVar()
        sp3_combo = ctk.CTkComboBox(sp3_row, variable=sp3_var, values=[], width=320, height=28)
        sp3_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def on_browse_sp3():
            f = filedialog.askopenfilename(
                title=f"Select SP3 File (Date: {date_str})", 
                initialdir=current_dir[0],
                filetypes=[("SP3", ["*.sp3", "*.SP3", "*.sp3c", "*.sp3d"])]
            )
            if f:
                if ref_sp3_norm and os.path.normpath(os.path.abspath(f)) == ref_sp3_norm:
                    messagebox.showwarning(
                        "Reference File",
                        f"The selected file:\n{os.path.basename(f)}\n\nis currently set as the Reference SP3 and cannot be added as a test product."
                    )
                    return
                f_date = file_parsers.extract_file_date(f)
                if f_date != ref_date:
                    f_date_str = f_date.strftime('%Y-%m-%d') if f_date else 'Unknown'
                    messagebox.showerror(
                        "Date Mismatch",
                        f"The selected file:\n{os.path.basename(f)}\n\n"
                        f"File Date: {f_date_str}\n"
                        f"Required Reference Date: {date_str}\n\n"
                        "Only files matching the reference date can be added."
                    )
                    return
                bname = os.path.basename(f)
                sp3_files_map[bname] = f
                values = sorted(list(sp3_files_map.keys()))
                sp3_combo.configure(values=values)
                sp3_var.set(bname)
                on_sp3_changed(bname)

        btn_browse_sp3 = ctk.CTkButton(sp3_row, text="Browse...", width=80, height=28, 
                                       font=ctk.CTkFont(size=11, weight="bold"), command=on_browse_sp3)
        btn_browse_sp3.pack(side="right")

        # CLK Row
        lbl_clk_sec = ctk.CTkLabel(container, text="2. Select Test CLK File:", font=ctk.CTkFont(weight="bold"), anchor="w")
        lbl_clk_sec.pack(fill="x", pady=(4, 2))

        clk_row = ctk.CTkFrame(container, fg_color="transparent")
        clk_row.pack(fill="x", pady=(0, 6))

        clk_var = tk.StringVar()
        clk_combo = ctk.CTkComboBox(clk_row, variable=clk_var, values=[], width=320, height=28)
        clk_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def on_browse_clk():
            f = filedialog.askopenfilename(
                title=f"Select CLK File (Date: {date_str})", 
                initialdir=current_dir[0],
                filetypes=[("CLK", ["*.clk", "*.CLK", "*.clk_30s", "*.clk_05s"])]
            )
            if f:
                if ref_clk_norm and os.path.normpath(os.path.abspath(f)) == ref_clk_norm:
                    messagebox.showwarning(
                        "Reference File",
                        f"The selected file:\n{os.path.basename(f)}\n\nis currently set as the Reference CLK and cannot be added as a test product."
                    )
                    return
                f_date = file_parsers.extract_file_date(f)
                if f_date != ref_date:
                    f_date_str = f_date.strftime('%Y-%m-%d') if f_date else 'Unknown'
                    messagebox.showerror(
                        "Date Mismatch",
                        f"The selected file:\n{os.path.basename(f)}\n\n"
                        f"File Date: {f_date_str}\n"
                        f"Required Reference Date: {date_str}\n\n"
                        "Only files matching the reference date can be added."
                    )
                    return
                bname = os.path.basename(f)
                clk_files_map[bname] = f
                values = sorted(list(clk_files_map.keys()))
                clk_combo.configure(values=values)
                clk_var.set(bname)

        btn_browse_clk = ctk.CTkButton(clk_row, text="Browse...", width=80, height=28, 
                                       font=ctk.CTkFont(size=11, weight="bold"), command=on_browse_clk)
        btn_browse_clk.pack(side="right")

        # Name Row
        lbl_name_sec = ctk.CTkLabel(container, text="3. Pair Name:", font=ctk.CTkFont(weight="bold"), anchor="w")
        lbl_name_sec.pack(fill="x", pady=(4, 2))

        name_var = tk.StringVar()
        name_entry = ctk.CTkEntry(container, textvariable=name_var, placeholder_text="e.g. WUM, GFZ, CNT", height=28)
        name_entry.pack(fill="x", pady=(0, 8))

        def _extract_ac_prefix(bname):
            if not bname:
                return ""
            parts = bname.split('_')
            if len(parts) > 1 and len(parts[0]) >= 3:
                return parts[0][:3].upper()
            return bname[:3].upper()

        def on_sp3_changed(choice):
            if not choice or choice.startswith("("):
                return
            ac = _extract_ac_prefix(choice)
            if ac and (not name_var.get() or name_var.get() in [_extract_ac_prefix(k) for k in sp3_files_map.keys()]):
                name_var.set(ac)
            if clk_files_map:
                target_prefix = choice[:3].lower()
                matched_clk = next((k for k in clk_files_map.keys() if k[:3].lower() == target_prefix), None)
                if not matched_clk and len(choice) >= 4:
                    matched_clk = next((k for k in clk_files_map.keys() if k[:4].lower() == choice[:4].lower()), None)
                if matched_clk:
                    clk_var.set(matched_clk)

        sp3_combo.configure(command=on_sp3_changed)

        def refresh_dropdowns():
            sp3_map, clk_map = scan_files_for_date(current_dir[0])
            sp3_files_map.clear()
            sp3_files_map.update(sp3_map)
            clk_files_map.clear()
            clk_files_map.update(clk_map)

            sp3_list = sorted(list(sp3_files_map.keys()))
            clk_list = sorted(list(clk_files_map.keys()))

            sp3_combo.configure(values=sp3_list if sp3_list else ["(No matching SP3 files in folder)"])
            clk_combo.configure(values=clk_list if clk_list else ["(No matching CLK files in folder)"])

            if sp3_list:
                sp3_var.set(sp3_list[0])
                on_sp3_changed(sp3_list[0])
            else:
                sp3_var.set("")

            if clk_list:
                if not clk_var.get() or clk_var.get() not in clk_files_map:
                    clk_var.set(clk_list[0])
            else:
                clk_var.set("")

        refresh_dropdowns()

        # Batch Add Button if multiple matching pairs exist
        def get_all_matched_pairs():
            pairs = []
            for sp3_name, sp3_pth in sp3_files_map.items():
                pref = sp3_name[:3].lower()
                clk_name = next((k for k in clk_files_map.keys() if k[:3].lower() == pref), None)
                if clk_name:
                    ac = _extract_ac_prefix(sp3_name)
                    pairs.append({'name': ac, 'sp3': sp3_pth, 'clk': clk_files_map[clk_name]})
            return pairs

        matched_pairs = get_all_matched_pairs()
        if len(matched_pairs) > 1:
            def on_add_all_matched():
                count = 0
                for p in matched_pairs:
                    if not any(existing.get('sp3') == p['sp3'] and existing.get('clk') == p['clk'] for existing in self.sisre_pairs):
                        self.sisre_pairs.append(p)
                        count += 1
                self._refresh_pairs_text()
                self.check_sisre_ready()
                self._refresh_sat_filter_for_loaded_files()
                self.status_label.configure(text=f"Added {count} test pair(s) for date {date_str}.", text_color="green")
                dlg.destroy()

            btn_add_all = ctk.CTkButton(
                container,
                text=f"Add All Matching Pairs in Folder ({len(matched_pairs)} pairs)",
                fg_color="#2980B9",
                hover_color="#3498DB",
                font=ctk.CTkFont(size=12, weight="bold"),
                height=28,
                command=on_add_all_matched
            )
            btn_add_all.pack(fill="x", pady=(0, 8))

        # Bottom Button Row
        btn_row = ctk.CTkFrame(container, fg_color="transparent")
        btn_row.pack(fill="x", pady=(6, 0))

        def on_add_single():
            chosen_sp3_name = sp3_var.get()
            chosen_clk_name = clk_var.get()
            pair_name = name_var.get().strip()

            if not chosen_sp3_name or chosen_sp3_name not in sp3_files_map:
                messagebox.showwarning("Missing SP3", f"Please select a valid SP3 file matching reference date {date_str}.")
                return

            if not chosen_clk_name or chosen_clk_name not in clk_files_map:
                messagebox.showwarning("Missing CLK", f"Please select a valid CLK file matching reference date {date_str}.")
                return

            sp3_path = sp3_files_map[chosen_sp3_name]
            clk_path = clk_files_map[chosen_clk_name]

            if not pair_name:
                pair_name = _extract_ac_prefix(chosen_sp3_name) or chosen_sp3_name.split('.')[0]

            self.sisre_pairs.append({
                'name': pair_name,
                'sp3': sp3_path,
                'clk': clk_path
            })

            self._refresh_pairs_text()
            self.check_sisre_ready()
            self._refresh_sat_filter_for_loaded_files()
            self.status_label.configure(text=f"Added pair: {pair_name} ({date_str})", text_color="green")
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        btn_ok = ctk.CTkButton(btn_row, text="Add Pair", fg_color="#1F6AA5", width=110, height=28, 
                               font=ctk.CTkFont(size=12, weight="bold"), command=on_add_single)
        btn_ok.pack(side="left", padx=(0, 6))

        btn_cancel = ctk.CTkButton(btn_row, text="Cancel", fg_color="#555", hover_color="#777", width=90, height=28, 
                                   font=ctk.CTkFont(size=12, weight="bold"), command=on_cancel)
        btn_cancel.pack(side="left")

        # Dialog Geometry and Centering
        dlg.update_idletasks()
        req_w = max(dlg.winfo_reqwidth(), 500)
        req_h = dlg.winfo_reqheight()
        x = max(parent_x + (parent_width - req_w) // 2, 0)
        y = max(parent_y + (parent_height - req_h) // 2, 0)
        dlg.geometry(f"{req_w}x{req_h}+{x}+{y}")
        dlg.minsize(460, req_h)
        dlg.grab_set()

    def remove_last_pair(self):
        if not self.sisre_pairs:
            messagebox.showinfo("Remove Last", "No test pairs have been added yet.")
            return

        removed = self.sisre_pairs.pop()
        self._refresh_pairs_text()
        self.status_label.configure(text=f"Removed last pair: {removed.get('name','Unknown')}", text_color="blue")
        self.check_sisre_ready()
        self._refresh_sat_filter_for_loaded_files()

    def _refresh_pairs_text(self):
        current_text = "\n".join([
            f"{p.get('name','')[:3]}: {', '.join([os.path.basename(f)[:3] for f in p.get('sp3')]) if isinstance(p.get('sp3'), (list, tuple)) else os.path.basename(p.get('sp3'))[:3]} + {', '.join([os.path.basename(f)[:3] for f in p.get('clk')]) if isinstance(p.get('clk'), (list, tuple)) else os.path.basename(p.get('clk'))[:3]}" + (f" + {os.path.basename(p.get('atx'))[:3]}" if p.get('atx') else "")
            for p in self.sisre_pairs
        ])
        self.pairs_textbox.configure(state="normal")
        self.pairs_textbox.delete("0.0", tk.END)
        self.pairs_textbox.insert("0.0", current_text if current_text else "No pairs added.")
        self.pairs_textbox.configure(state="disabled")

    def add_HAS_pair(self):
        # Dialog: select SSR (single), NAV (one or more), and ATX (single)
        dlg = tk.Toplevel(self)
        dlg.title("Add HAS Pair (SSR + NAV + ATX)")
        # We'll build the dialog contents first, then compute required size
        # Ensure main window layout is up-to-date to get correct dimensions/position
        self.update_idletasks()
        parent_x = self.winfo_rootx()
        parent_y = self.winfo_rooty()
        parent_width = self.winfo_width()
        parent_height = self.winfo_height()
        dlg.transient(self)

        ssr_path = tk.StringVar()
        atx_path = tk.StringVar()
        nav_list = []
        sis_corrections_var = tk.BooleanVar(value=False)

        # Selectors
        def select_ssr():
            f = filedialog.askopenfilename(title="Select TEST SSR", filetypes=[("SSR", "*.ssr")])
            if f:
                ssr_path.set(f)
                lbl_ssr.configure(text=os.path.basename(f))

        def select_atx():
            f = filedialog.askopenfilename(title="Select ATX", filetypes=[("ATX", "*.atx")])
            if f:
                atx_path.set(f)
                lbl_atx.configure(text=os.path.basename(f))

        def select_nav():
            files = filedialog.askopenfilenames(title="Select NAV files (you may choose multiple)", filetypes=[("NAV", ("*.nav", "*.rnx", "*.**n"))])
            if files:
                nav_list.clear()
                nav_list.extend(files)
                lbl_nav.configure(text=f"{len(nav_list)} file(s) selected")

        def on_ok():
            if not ssr_path.get():
                messagebox.showwarning("Missing SSR", "Please select an SSR file.")
                return
            if not nav_list:
                messagebox.showwarning("Missing NAV", "Please select one or more NAV files.")
                return
            #if not atx_path.get():
                #messagebox.showwarning("Missing ATX", "Please select an ATX file.")
                #return

            name = os.path.basename(ssr_path.get()).split('.')[0]
            # Store NAV files as a list and ATX path
            self.sisre_pairs.append({
                'name': name,
                'sp3': ssr_path.get(),
                'ssr': ssr_path.get(),
                'clk': list(nav_list),
                'atx': atx_path.get(),
                'sis_corrections': sis_corrections_var.get()
            })

            # Update UI List (show first 3 characters of each filename; handle single paths and lists)
            def _short(pth):
                if not pth:
                    return ''
                if isinstance(pth, (list, tuple)):
                    return ", ".join(os.path.basename(f)[:3] for f in pth)
                return os.path.basename(pth)[:3]
            current_text = "\n".join([
                f"{p.get('name','')[:3]}: {_short(p.get('sp3'))} + {_short(p.get('clk'))}" + (f" + {_short(p.get('atx'))}" if p.get('atx') else "")
                for p in self.sisre_pairs
            ])
            self.pairs_textbox.configure(state="normal")
            self.pairs_textbox.delete("0.0", tk.END)
            self.pairs_textbox.insert("0.0", current_text if current_text else "No pairs added.")
            self.pairs_textbox.configure(state="disabled")

            self.check_sisre_ready()
            self._refresh_sat_filter_for_loaded_files()
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        # Layout using grid
        container = ctk.CTkFrame(dlg)
        container.pack(fill="both", expand=True, padx=10, pady=10)
        #container.grid_rowconfigure(3, weight=1)  # Make row 3 expand to push buttons down

        btn1 = ctk.CTkButton(container, text="Select SSR", font=ctk.CTkFont(size=12, weight="bold"), height=28, command=select_ssr)
        btn1.grid(row=0, column=0, padx=(0,8), pady=6, sticky="w")
        lbl_ssr = ctk.CTkLabel(container, text="No file selected", anchor="w")
        lbl_ssr.grid(row=0, column=1, sticky="w")

        btn2 = ctk.CTkButton(container, text="Select NAV(s)", font=ctk.CTkFont(size=12, weight="bold"), height=28, command=select_nav)
        btn2.grid(row=1, column=0, padx=(0,8), pady=6, sticky="w")
        lbl_nav = ctk.CTkLabel(container, text="No files selected", anchor="w")
        lbl_nav.grid(row=1, column=1, sticky="w")

        btn3 = ctk.CTkButton(container, text="Select ATX", font=ctk.CTkFont(size=12, weight="bold"), height=28, command=select_atx)
        btn3.grid(row=2, column=0, padx=(0,8), pady=6, sticky="w")
        lbl_atx = ctk.CTkLabel(container, text="No file selected", anchor="w")
        lbl_atx.grid(row=2, column=1, sticky="w")

        chk_sis = ctk.CTkCheckBox(container, text="SIS corrections", variable=sis_corrections_var)
        chk_sis.grid(row=3, column=0, columnspan=2, pady=6, sticky="w")

        # Spacer row to push buttons to bottom
        spacer = ctk.CTkLabel(container, text="", fg_color="transparent")
        spacer.grid(row=4, column=0, columnspan=2, sticky="nsew")
        container.grid_rowconfigure(4, weight=1)

        ok_btn = ctk.CTkButton(container, text="OK", font=ctk.CTkFont(size=12, weight="bold"), width=90, height=28, command=on_ok)
        ok_btn.grid(row=5, column=0, pady=(12,0), sticky="w")
        cancel_btn = ctk.CTkButton(container, text="Cancel", font=ctk.CTkFont(size=12, weight="bold"), fg_color="#555", hover_color="#777", width=90, height=28, command=on_cancel)
        cancel_btn.grid(row=5, column=1, pady=(12,0), sticky="w")

        # Now that the dialog content is laid out, compute required size and center it
        dlg.update_idletasks()
        req_w = dlg.winfo_reqwidth()
        req_h = dlg.winfo_reqheight()
        x = max(parent_x + (parent_width - req_w) // 2, 0)
        y = max(parent_y + (parent_height - req_h) // 2, 0)
        dlg.geometry(f"{req_w}x{req_h}+{x}+{y}")
        # Prevent resizing and lock window size to content
        dlg.resizable(False, False)
        dlg.minsize(req_w, req_h)
        dlg.maxsize(req_w, req_h)
        dlg.grab_set()

    def add_BRDC_pair(self):
        # Dialog: select NAV (one or more) and ATX (single)
        dlg = tk.Toplevel(self)
        dlg.title("Add BRDC Pair (NAV + ATX)")
        self.update_idletasks()
        parent_x = self.winfo_rootx()
        parent_y = self.winfo_rooty()
        parent_width = self.winfo_width()
        parent_height = self.winfo_height()
        dlg.transient(self)

        atx_path = tk.StringVar()
        nav_list = []

        def select_atx():
            f = filedialog.askopenfilename(title="Select ATX", filetypes=[("ATX", "*.atx")])
            if f:
                atx_path.set(f)
                lbl_atx.configure(text=os.path.basename(f))

        def select_nav():
            files = filedialog.askopenfilenames(title="Select NAV file", filetypes=[("NAV", ("*.nav", "*.rnx", "*.**n"))])
            if files:
                nav_list.clear()
                nav_list.extend(files)
                lbl_nav.configure(text=f"{len(nav_list)} file(s) selected")

        def on_ok():
            if not nav_list:
                messagebox.showwarning("Missing NAV", "Please select one or more NAV files.")
                return

            name = "BRDC_" + os.path.basename(nav_list[0]).split('.')[0]
            self.sisre_pairs.append({
                'name': name,
                'sp3': "BRDC",
                'clk': list(nav_list),
                'atx': atx_path.get(),
                'sis_corrections': True
            })

            def _short(pth):
                if not pth: return ''
                if isinstance(pth, (list, tuple)): return ", ".join(os.path.basename(f)[:3] for f in pth)
                return os.path.basename(pth)[:3]
            
            current_text = "\n".join([
                f"{p.get('name','')[:3]}: {_short(p.get('sp3'))} + {_short(p.get('clk'))}" + (f" + {_short(p.get('atx'))}" if p.get('atx') else "")
                for p in self.sisre_pairs
            ])
            self.pairs_textbox.configure(state="normal")
            self.pairs_textbox.delete("0.0", tk.END)
            self.pairs_textbox.insert("0.0", current_text if current_text else "No pairs added.")
            self.pairs_textbox.configure(state="disabled")

            self.check_sisre_ready()
            self._refresh_sat_filter_for_loaded_files()
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        container = ctk.CTkFrame(dlg)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        btn2 = ctk.CTkButton(container, text="Select NAV", font=ctk.CTkFont(size=12, weight="bold"), height=28, command=select_nav)
        btn2.grid(row=0, column=0, padx=(0,8), pady=6, sticky="w")
        lbl_nav = ctk.CTkLabel(container, text="No files selected", anchor="w")
        lbl_nav.grid(row=0, column=1, sticky="w")

        btn3 = ctk.CTkButton(container, text="Select ATX", font=ctk.CTkFont(size=12, weight="bold"), height=28, command=select_atx)
        btn3.grid(row=1, column=0, padx=(0,8), pady=6, sticky="w")
        lbl_atx = ctk.CTkLabel(container, text="No file selected", anchor="w")
        lbl_atx.grid(row=1, column=1, sticky="w")

        spacer = ctk.CTkLabel(container, text="", fg_color="transparent")
        spacer.grid(row=3, column=0, columnspan=2, sticky="nsew")
        container.grid_rowconfigure(3, weight=1)

        ok_btn = ctk.CTkButton(container, text="OK", font=ctk.CTkFont(size=12, weight="bold"), width=90, height=28, command=on_ok)
        ok_btn.grid(row=4, column=0, pady=(12,0), sticky="w")
        cancel_btn = ctk.CTkButton(container, text="Cancel", font=ctk.CTkFont(size=12, weight="bold"), fg_color="#555", hover_color="#777", width=90, height=28, command=on_cancel)
        cancel_btn.grid(row=4, column=1, pady=(12,0), sticky="w")

        dlg.update_idletasks()
        req_w = dlg.winfo_reqwidth()
        req_h = dlg.winfo_reqheight()
        x = max(parent_x + (parent_width - req_w) // 2, 0)
        y = max(parent_y + (parent_height - req_h) // 2, 0)
        dlg.geometry(f"{req_w}x{req_h}+{x}+{y}")
        dlg.resizable(False, False)
        dlg.minsize(req_w, req_h)
        dlg.maxsize(req_w, req_h)
        dlg.grab_set()

    def check_sisre_ready(self):
        if self.sisre_ref_sp3 and self.sisre_ref_clk and len(self.sisre_pairs) > 0:
            self.run_btn.configure(state="normal")
        else:
            self.run_btn.configure(state="disabled")

    def reset_app(self, keep_mode=False):
        self.mode_states = {}
        self._current_mode = self.product_type_seg.get()
        self.filepaths = []
        self.results = {}
        self.cov_results = {}
        self.results_metadata = {}
        self.sisre_ref_sp3 = None
        self.sisre_ref_clk = None
        self.sisre_pairs = []
        self.enabled_satellites = None
        self.target_sats_filter = None
        self.excluded_sats_filter = None
        
        # Reset Widgets
        self.ref_file_dropdown.set("")
        self.ref_file_dropdown.configure(values=[], state="disabled")
        self.btn_ref_sp3.configure(text="Select Ref SP3")
        self.btn_ref_clk.configure(text="Select Ref CLK")
        self.pairs_textbox.configure(state="normal")
        self.pairs_textbox.delete("0.0", tk.END)
        self.pairs_textbox.insert("0.0", "No pairs added.")
        self.pairs_textbox.configure(state="disabled")
        self.sat_filter_status_label.configure(text="All Satellites (Default)", text_color=("#1B5E20", "#2ECC71"))
        self.run_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        self.progress_bar.set(0)
        self.progress_bar.pack_forget()
        
        # Only clear location fields when doing a full reset, not when just switching modes
        if not keep_mode:
            self.lat_entry.delete(0, tk.END)
            self.lon_entry.delete(0, tk.END)
            self.h_entry.delete(0, tk.END)
            self.el_entry.delete(0, tk.END)
        
        self.check_location_inputs()

        if hasattr(self, 'plot_tabview'):
            self.plot_tabview.destroy()
        self.plot_tabview = ctk.CTkTabview(self.plots_frame)
        self.plot_tabview.grid(row=0, column=0, sticky="nsew")

    def run_comparison(self):
        """Start comparison in a background thread to keep UI responsive."""
        # Disable buttons to prevent multiple runs
        self.run_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        self.reset_btn.configure(state="disabled")
        
        self.progress_bar.set(0)
        self.progress_bar.pack(padx=15, pady=(4, 4), fill="x", before=self.status_label)
        self.status_label.configure(text="Processing...", text_color="blue")
        self.update_idletasks()
        
        # Start worker thread
        thread = threading.Thread(target=self._run_comparison_worker, daemon=True)
        thread.start()
    
    def _run_comparison_worker(self):
        """Worker method that runs in background thread."""
        mode = self.product_type_seg.get()
        
        try:
            self.results = {}
            all_sats = get_all_known_satellites(self.get_available_satellites())
            self._update_sat_filter_structures(all_sats)
            target_sats = self.target_sats_filter
            excluded_sats = self.excluded_sats_filter

            observer_lat = None
            observer_lon = None
            observer_h = None
            min_elevation = None
            try:
                lat_text = self.lat_entry.get().strip()
                lon_text = self.lon_entry.get().strip()
                h_text = self.h_entry.get().strip()
                el_text = self.el_entry.get().strip()

                if lat_text and lon_text and h_text and el_text:
                    observer_lat = float(lat_text)
                    observer_lon = float(lon_text)
                    observer_h = float(h_text)
                    min_elevation = float(el_text)
            except ValueError:
                self.update_status_threadsafe("Warning: Invalid latitude/longitude values. Skipping elevation filter.")
                
            duration_str = self.cov_duration_entry.get().strip()
            try:
                sim_duration = float(duration_str) if duration_str else None
            except ValueError:
                sim_duration = None

            run_cov = self.cov_var.get() if mode == "SISRE" else False
            
            res, res_meta, cov_res = orchestrator.run_analysis_workflow(
                mode=mode,
                filepaths=self.filepaths,
                ref_basename=self.ref_file_dropdown.get(),
                sisre_ref_sp3=self.sisre_ref_sp3,
                sisre_ref_clk=self.sisre_ref_clk,
                sisre_pairs=self.sisre_pairs,
                target_sats_filter=target_sats,
                excluded_sats_filter=excluded_sats,
                observer_lat=observer_lat,
                observer_lon=observer_lon,
                observer_h=observer_h,
                min_elevation=min_elevation,
                run_cov_sim=run_cov,
                cov_duration_hrs=sim_duration,
                status_callback=self.update_status_threadsafe,
                progress_callback=self.update_rnx_progress
            )
            
            self.results = res
            self.results_metadata = res_meta
            self.cov_results = cov_res
            
            # Schedule completion on main thread
            self.after(0, self._on_comparison_complete)
            
        except Exception as e:
            error_msg = str(e)
            self.after(0, lambda: self._on_comparison_error(error_msg))
    
    def _on_comparison_complete(self):
        """Called on main thread when comparison finishes successfully."""
        # Save results to per-mode storage
        current_mode = self.product_type_seg.get()
        if self.results:
            self.results_by_mode[current_mode] = self.results.copy()
        
        self.status_label.configure(text="Done. Generating Plots...", text_color="green")
        self.export_btn.configure(state="normal")
        self.run_btn.configure(state="normal")
        self.reset_btn.configure(state="normal")
        self.progress_bar.set(1.0)
        self.progress_bar.pack_forget()
        self.draw_plots()
    
    def _on_comparison_error(self, error_msg):
        """Called on main thread when comparison fails."""
        self.status_label.configure(text=f"Error: {error_msg}", text_color="red")
        self.run_btn.configure(state="normal")
        self.reset_btn.configure(state="normal")
        self.progress_bar.set(0)
        self.progress_bar.pack_forget()
        print(error_msg)

    def draw_plots(self):
        if not self.results:
            return

        # 1. Setup Filter
        all_sats = self.get_available_satellites()
        self._update_sat_filter_structures(all_sats)
        target_sats = self.target_sats_filter
        excluded_sats = self.excluded_sats_filter
        
        # 2. Reset Plots
        if hasattr(self, 'plot_tabview'): self.plot_tabview.destroy()
        self.plot_tabview = ctk.CTkTabview(self.plots_frame)
        self.plot_tabview.grid(row=0, column=0, sticky="nsew")
        
        mode = self.product_type_seg.get()
        
        # --- DEFINE TABS BASED ON MODE ---
        if mode == 'SP3':
            components = {'dX_cm': 'Difference on X (cm)', 'dY_cm': 'Difference on Y (cm)', 'dZ_cm': 'Difference on Z (cm)'}
        elif mode == 'CLK':
            components = {'dClock_ns': 'Difference on clock (ns)'}
        else: # SISRE
            components = {
                'SISRE_comb_cm': 'SISRE',
                'dClock_ns': 'Clock errors',
                'dR_cm': 'Radial (cm)',
                'dA_cm': 'Along-Track (cm)',
                'dC_cm': 'Cross-Track (cm)'}
            
        # Helper for closure
        def create_on_pick(mapping, cvs):
            def on_pick(event):
                leg_line = event.artist
                if leg_line in mapping:
                    plot_line = mapping[leg_line]
                    vis = not plot_line.get_visible()
                    plot_line.set_visible(vis)
                    leg_line.set_alpha(1.0 if vis else 0.2)
                    cvs.draw()
            return on_pick

        for col, title in components.items():
            self.plot_tabview.add(title)
            
            fig = Figure(figsize=(5, 4), dpi=100)
            ax = fig.add_subplot(111)
            lines = []
            # Track min/max datetime across all plotted series to set tight x-limits
            min_dt = None
            max_dt = None

            for name, df in self.results.items():
                if col not in df.columns: continue
                
                # --- LOGIC BRANCH: Specific Filter vs Constellation Aggregation ---
                df_temp = df.copy()
                if target_sats:
                    df_temp = comparison_logic.filter_by_satellite_patterns(df_temp, target_sats, exclude=False)
                if getattr(self, 'excluded_sats_filter', None):
                    df_temp = comparison_logic.filter_by_satellite_patterns(df_temp, self.excluded_sats_filter, exclude=True)
                
                if df_temp.empty: continue

                has_prefix = bool(target_sats and target_sats.get('prefix'))
                has_exact = bool(target_sats and target_sats.get('exact'))

                if target_sats and has_exact and not has_prefix:
                    # Specific exact satellite IDs specified (e.g. G01, G02) -> plot individual satellite curves
                    for sat_id in target_sats['exact']:
                        sat_data = df_temp[df_temp.index.get_level_values('SatID') == sat_id]
                        if sat_data.empty: continue

                        rms = comparison_logic.calculate_rms(sat_data[col])
                        unit = "cm" if "cm" in col else "ns"
                        xs = sat_data.index.get_level_values('Epoch')
                        line, = ax.plot(xs, sat_data[col],
                                        label=f"{name[:3]} [{sat_id}] RMS={rms:.1f}{unit}",
                                        marker='.', markersize=4, linewidth=1)
                        lines.append(line)
                        try:
                            min_x = xs.min()
                            max_x = xs.max()
                            if min_x is not None and (min_dt is None or min_x < min_dt): min_dt = min_x
                            if max_x is not None and (max_dt is None or max_x > max_dt): max_dt = max_x
                        except Exception:
                            pass
                else:
                    # Constellation-wise Aggregation (Plot one line per System)
                    df_temp['Sys'] = df_temp.index.get_level_values('SatID').str[0]
                    unique_sys = df_temp['Sys'].unique()

                    for sys in unique_sys:
                        sys_data = df_temp[df_temp['Sys'] == sys]
                        if sys_data.empty: continue

                        epoch_rms = round(sys_data[col].groupby(level='Epoch').apply(comparison_logic.calculate_rms), 2)
                        global_rms = comparison_logic.calculate_rms(sys_data[col])
                        unit = "cm" if "cm" in col else "ns"

                        xs = epoch_rms.index
                        line, = ax.plot(xs, epoch_rms.values,
                                        label=f"{name[:3]} [{sys}] RMS={global_rms:.1f}{unit}", 
                                        marker='.', markersize=4, linewidth=1.5)
                        lines.append(line)
                        try:
                            min_x = xs.min()
                            max_x = xs.max()
                            if min_x is not None and (min_dt is None or min_x < min_dt): min_dt = min_x
                            if max_x is not None and (max_dt is None or max_x > max_dt): max_dt = max_x
                        except Exception:
                            pass

            ax.set_title(f"{title}", fontsize=16)
            ax.set_ylabel(f"Error ({'ns' if 'ns' in col else 'cm'})", fontsize=16)
            ax.tick_params(axis='both', which='major', labelsize=14)
            ax.hlines(0, xmin=ax.get_xlim()[0], xmax=ax.get_xlim()[1], colors='black', linestyles='dashed', linewidth=2)
            ax.grid(True)

            # Adjust x-limits to the actual data range and leave a small padding so the plot doesn't reach into the next day
            try:
                if min_dt is not None and max_dt is not None:
                    # Small fraction padding (0.5%) — noticeably smaller than matplotlib's default margins
                    pad_frac = 0.03
                    try:
                        delta = (max_dt - min_dt) * pad_frac
                    except Exception:
                        # If subtraction/multiplication fails (non-pandas datetimes), fall back to margins
                        delta = None
                    if delta is None or delta == 0:
                        # Fallback: use 1 second padding
                        delta = pd.Timedelta(seconds=1)
                    ax.set_xlim(min_dt - delta, max_dt + delta)
            except Exception:
                pass

            # Format x-axis to show time of day only (HH:MM:SS) - major ticks every 6 hours
            try:
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                fig.autofmt_xdate()
            except Exception:
                # If for some reason mdates can't format (non-datetime index), ignore silently
                pass
            
            # Legend visibility
            current_map = {}
            if self.legend_var.get():
                leg = ax.legend(fontsize=10, loc='upper right')
                for leg_line, plot_line in zip(leg.get_lines(), lines):
                    leg_line.set_picker(5)
                    current_map[leg_line] = plot_line

            tab_frame = self.plot_tabview.tab(title)
            canvas = FigureCanvasTkAgg(fig, master=tab_frame)
            canvas.draw()
            if current_map:
                canvas.mpl_connect('pick_event', create_on_pick(current_map, canvas))
            
            toolbar = NavigationToolbar2Tk(canvas, tab_frame)
            toolbar.update()
            canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

        # --- Plot Covariance Simulation if available (SISRE mode only) ---
        if mode == 'SISRE' and hasattr(self, 'cov_results') and self.cov_results:
            title = "Covariance (m)"
            self.plot_tabview.add(title)
            fig = Figure(figsize=(5, 4), dpi=100)
            ax = fig.add_subplot(111)
            lines = []
            
            # Extract thresholds
            h_thresh_str = self.cov_horiz_thresh_entry.get().strip()
            v_thresh_str = self.cov_vert_thresh_entry.get().strip()
            try:
                h_thresh = float(h_thresh_str) if h_thresh_str else None
            except ValueError:
                h_thresh = None
            try:
                v_thresh = float(v_thresh_str) if v_thresh_str else None
            except ValueError:
                v_thresh = None
                
            if h_thresh is not None:
                ax.axhline(y=h_thresh, color='#2980B9', linestyle=':', linewidth=1.5, alpha=0.75, label=f'H Thresh ({h_thresh}m)')
            if v_thresh is not None:
                ax.axhline(y=v_thresh, color='#C0392B', linestyle=':', linewidth=1.5, alpha=0.75, label=f'V Thresh ({v_thresh}m)')
            
            conv_events = []
            conv_summary_entries = []

            for name, cov_df in self.cov_results.items():
                if cov_df.empty: continue
                xs = cov_df['Epoch']

                # Compute convergence time
                conv_mins = None
                t_conv = None
                conv_row = None
                if h_thresh is not None and v_thresh is not None and len(cov_df) > 0:
                    mask = (cov_df['horizontal_error_m'] <= h_thresh) & (cov_df['vertical_error_m'] <= v_thresh)
                    if mask.any():
                        conv_idx = mask.idxmax()
                        conv_row = cov_df.loc[conv_idx]
                        t_conv = conv_row['Epoch']
                        t_start = cov_df['Epoch'].iloc[0]
                        try:
                            conv_mins = (t_conv - t_start).total_seconds() / 60.0
                        except AttributeError:
                            conv_mins = (t_conv - t_start) / 60.0

                label_h = f"{name[:3]} Horiz" + (f" [Conv: {conv_mins:.1f}m]" if conv_mins is not None else " [No conv]" if (h_thresh and v_thresh) else "")
                label_v = f"{name[:3]} Vert"

                line_h, = ax.plot(xs, cov_df['horizontal_error_m'], label=label_h, linewidth=1.5, marker='.', markersize=4)
                color = line_h.get_color()
                line_v, = ax.plot(xs, cov_df['vertical_error_m'], label=label_v, linewidth=1.2, linestyle='--', marker='.', markersize=3, color=color, alpha=0.8)
                lines.extend([line_h, line_v])

                if conv_mins is not None and t_conv is not None:
                    conv_events.append({
                        'name': name[:3],
                        't_conv': t_conv,
                        'conv_mins': conv_mins,
                        'color': color,
                        'h_err': conv_row['horizontal_error_m'] if conv_row is not None else h_thresh,
                        'v_err': conv_row['vertical_error_m'] if conv_row is not None else v_thresh
                    })
                    conv_summary_entries.append(f"{name[:3]}: {conv_mins:.1f} min")
                elif h_thresh is not None and v_thresh is not None:
                    conv_summary_entries.append(f"{name[:3]}: No conv")

            # Draw convergence markers and anti-collision staggered badges
            if conv_events:
                conv_events.sort(key=lambda ev: ev['t_conv'])
                
                # Determine vertical tiers to prevent label overlap when convergence times are close
                tiers = []
                last_t = None
                curr_tier = 0
                for ev in conv_events:
                    t = ev['t_conv']
                    if last_t is not None:
                        try:
                            dt_sec = abs((t - last_t).total_seconds())
                        except Exception:
                            dt_sec = abs(t - last_t)
                        # If events are within 25 minutes of each other, step to next tier
                        if dt_sec < 1500:
                            curr_tier = (curr_tier + 1) % 3
                        else:
                            curr_tier = 0
                    last_t = t
                    tiers.append(curr_tier)

                y_thresh_max = max(h_thresh or 0, v_thresh or 0, 0.5)
                y_base = y_thresh_max * 1.1

                for ev, tier in zip(conv_events, tiers):
                    t = ev['t_conv']
                    c = ev['color']
                    nm = ev['name']
                    m = ev['conv_mins']

                    # Color-matched vertical dashed line
                    ax.axvline(x=t, color=c, linestyle='--', alpha=0.65, linewidth=1.2)

                    # Convergence point marker on horizontal error curve
                    ax.plot([t], [ev['h_err']], marker='o', markersize=6, color=c, zorder=5)

                    # Staggered height calculation
                    y_span = max(ax.get_ylim()[1] - y_base, y_base * 0.8)
                    y_pos = y_base + tier * (y_span * 0.28)

                    ax.text(
                        t, y_pos, 
                        f" {nm}: {m:.1f}m ", 
                        rotation=90, 
                        verticalalignment='bottom', 
                        horizontalalignment='center',
                        color=c, 
                        fontsize=10, 
                        weight='bold',
                        bbox=dict(boxstyle='round,pad=0.25', facecolor='white', alpha=0.88, edgecolor=c, linewidth=1.2),
                        zorder=6
                    )

            # Compact Summary Box in top-left
            if conv_summary_entries and (h_thresh is not None or v_thresh is not None):
                thresh_info = f"H≤{h_thresh}m, V≤{v_thresh}m" if (h_thresh and v_thresh) else f"Thresh: {h_thresh or v_thresh}m"
                summary_text = f"Convergence ({thresh_info}):\n" + "\n".join(f"• {e}" for e in conv_summary_entries)
                ax.text(
                    0.02, 0.96, 
                    summary_text, 
                    transform=ax.transAxes, 
                    verticalalignment='top',
                    fontsize=9, 
                    weight='bold',
                    bbox=dict(boxstyle='round,pad=0.4', facecolor='white', alpha=0.88, edgecolor='#999', linewidth=0.8),
                    zorder=10
                )
                
            ax.set_title("Theoretical Convergence", fontsize=16)
            ax.set_ylabel("Formal Error (m)", fontsize=16)
            ax.tick_params(axis='both', which='major', labelsize=14)
            ax.grid(True)
            try:
                ax.xaxis.set_major_locator(mdates.AutoDateLocator())
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                fig.autofmt_xdate()
            except Exception:
                pass
                
            # Legend visibility
            current_map = {}
            if self.legend_var.get():
                leg = ax.legend(fontsize=9, loc='upper right')
                for leg_line, plot_line in zip(leg.get_lines(), lines):
                    leg_line.set_picker(5)
                    current_map[leg_line] = plot_line
                    
            tab_frame = self.plot_tabview.tab(title)
            canvas = FigureCanvasTkAgg(fig, master=tab_frame)
            canvas.draw()
            if current_map:
                canvas.mpl_connect('pick_event', create_on_pick(current_map, canvas))
            toolbar = NavigationToolbar2Tk(canvas, tab_frame)
            toolbar.update()
            canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

    def export_statistics(self):
        if not self.results: return
        save_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not save_path: return
        
        all_sats = get_all_known_satellites(self.get_available_satellites())
        self._update_sat_filter_structures(all_sats)
        target_sats = self.target_sats_filter
        excluded_sats = self.excluded_sats_filter
        
        self.update_status_threadsafe("Exporting to Excel...", color="blue")
        
        export_logic.export_results_to_excel(
            results=self.results,
            results_metadata=self.results_metadata,
            target_sats_filter=target_sats,
            excluded_sats_filter=excluded_sats,
            save_path=save_path,
            status_callback=self.update_status_threadsafe
        )

def main():
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()