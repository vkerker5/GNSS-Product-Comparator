import pandas as pd
from datetime import datetime, date, timedelta
import os
import re

from cssrlib.rinex import rnxdec
from cssrlib.gnss import Nav, epoch2time, id2sat, sat2id, sat2prn, uGNSS, time2epoch, rSigRnx, rCST
from cssrlib.ephemeris import eph2pos, findeph, eph2clk, geph2pos, geph2clk
from cssrlib.peph import atxdec, searchpcv, apc2com
import numpy as np

SUPPORTED_SYS = {'G', 'E', 'R', 'C', 'J'}
GEO_EXCLUSIONS = {'C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09', 'C10', 'C13', 'C16', 'C38', 'C39', 'C40'}

def extract_satellites_from_sp3(file_path):
    sats = set()
    if not os.path.exists(file_path):
        return sats
    try:
        with open(file_path, 'r', errors='ignore') as f:
            for line in f:
                if line.startswith('P') and len(line) > 3:
                    sat = line[1:4].strip()
                    if len(sat) >= 2 and sat[0].isalpha() and sat[1:].isdigit():
                        sys_code = sat[0].upper()
                        if sys_code in SUPPORTED_SYS:
                            formatted = f"{sys_code}{int(sat[1:]):02d}"
                            if formatted not in GEO_EXCLUSIONS:
                                sats.add(formatted)
    except Exception:
        pass
    return sats

def extract_satellites_from_clk(file_path):
    sats = set()
    if not os.path.exists(file_path):
        return sats
    try:
        with open(file_path, 'r', errors='ignore') as f:
            for line in f:
                if line.startswith(('AS', 'AR')):
                    parts = line.split()
                    if len(parts) >= 2:
                        sat = parts[1].strip()
                        if len(sat) >= 2 and sat[0].isalpha() and sat[1:].isdigit():
                            sys_code = sat[0].upper()
                            if sys_code in SUPPORTED_SYS:
                                formatted = f"{sys_code}{int(sat[1:]):02d}"
                                if formatted not in GEO_EXCLUSIONS:
                                    sats.add(formatted)
    except Exception:
        pass
    return sats

def extract_satellites_from_ssr(file_path):
    sats = set()
    if not os.path.exists(file_path):
        return sats
    try:
        with open(file_path, 'r', errors='ignore') as f:
            for line in f:
                if not line.startswith('>'):
                    parts = line.split()
                    if parts:
                        sat = parts[0].strip()
                        if len(sat) >= 2 and sat[0].isalpha() and sat[1:].isdigit():
                            sys_code = sat[0].upper()
                            if sys_code in SUPPORTED_SYS:
                                formatted = f"{sys_code}{int(sat[1:]):02d}"
                                if formatted not in GEO_EXCLUSIONS:
                                    sats.add(formatted)
    except Exception:
        pass
    return sats

def extract_satellites_from_nav(file_path):
    sats = set()
    if not os.path.exists(file_path):
        return sats
    try:
        dec = rnxdec()
        nav = Nav()
        dec.decode_nav(file_path, nav)
        for eph in getattr(nav, 'eph', []):
            sid = sat2id(eph.sat)
            if sid and sid != -1 and sid[0] in SUPPORTED_SYS and sid not in GEO_EXCLUSIONS:
                sats.add(sid)
        for geph in getattr(nav, 'geph', []):
            sid = sat2id(geph.sat)
            if sid and sid != -1 and sid[0] in SUPPORTED_SYS and sid not in GEO_EXCLUSIONS:
                sats.add(sid)
    except Exception:
        try:
            with open(file_path, 'r', errors='ignore') as f:
                in_header = True
                for line in f:
                    if in_header:
                        if "END OF HEADER" in line:
                            in_header = False
                        continue
                    if len(line) >= 3 and line[0] in SUPPORTED_SYS and line[1:3].isdigit():
                        sat = line[:3].strip()
                        if sat not in GEO_EXCLUSIONS:
                            sats.add(sat)
        except Exception:
            pass
    return sats

def extract_satellites_from_file(file_path):
    """
    Extracts all satellite IDs present in a given file (SP3, CLK, SSR, NAV).
    """
    if isinstance(file_path, (list, tuple)):
        combined = set()
        for f in file_path:
            combined |= extract_satellites_from_file(f)
        return combined

    if not file_path or not isinstance(file_path, str) or not os.path.exists(file_path):
        return set()

    lower = file_path.lower()
    if lower.endswith('.sp3'):
        return extract_satellites_from_sp3(file_path)
    elif lower.endswith('.clk'):
        return extract_satellites_from_clk(file_path)
    elif lower.endswith('.ssr'):
        return extract_satellites_from_ssr(file_path)
    elif lower.endswith(('.nav', '.rnx')) or (len(lower) > 4 and lower[-1] in ('n', 'p') and lower[-4] == '.'):
        return extract_satellites_from_nav(file_path)
    else:
        try:
            with open(file_path, 'r', errors='ignore') as f:
                first_lines = "".join(f.readline() for _ in range(5))
                if "#P" in first_lines or "*  " in first_lines or "P " in first_lines:
                    return extract_satellites_from_sp3(file_path)
                elif "RINEX VERSION" in first_lines:
                    if "NAVIGATION" in first_lines:
                        return extract_satellites_from_nav(file_path)
                    elif "CLOCK" in first_lines:
                        return extract_satellites_from_clk(file_path)
        except Exception:
            pass
        return set()

def extract_file_date(file_path):
    """
    Extracts the observation/product start date (datetime.date) from a GNSS file (SP3, CLK, NAV, SSR)
    by inspecting header/records, falling back to standard filename patterns.
    """
    if not file_path or not isinstance(file_path, str):
        return None

    # 1. Try reading from file content first if file exists on disk
    if os.path.exists(file_path) and os.path.isfile(file_path):
        try:
            with open(file_path, 'r', errors='ignore') as f:
                for _ in range(150):
                    line = f.readline()
                    if not line:
                        break
                    # SP3 header line 1 or epoch line
                    if line.startswith(('#c', '#a', '#d', '#v', '#P')) and len(line) >= 14:
                        parts = line[3:].split()
                        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
                            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                            if 1980 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                                return date(y, m, d)
                    if line.startswith('*') and len(line) >= 14:
                        parts = line.split()
                        if len(parts) >= 4 and parts[1].isdigit() and parts[2].isdigit() and parts[3].isdigit():
                            y, m, d = int(parts[1]), int(parts[2]), int(parts[3])
                            if 1980 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                                return date(y, m, d)
                    # CLK AS / AR record
                    if line.startswith(('AS', 'AR')) and len(line) >= 20:
                        parts = line.split()
                        if len(parts) >= 5 and parts[2].isdigit() and parts[3].isdigit() and parts[4].isdigit():
                            y, m, d = int(parts[2]), int(parts[3]), int(parts[4])
                            if 1980 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                                return date(y, m, d)
                    # CLK TIME OF FIRST OBS
                    if 'TIME OF FIRST OBS' in line:
                        parts = line.split()
                        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
                            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                            if 1980 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                                return date(y, m, d)
                    # SSR > EPOCH or > CLOCK or > ORBIT
                    if line.startswith('>') and len(line) >= 12:
                        parts = line.replace('>', '').replace('-', ' ').split()
                        for i in range(len(parts) - 2):
                            if parts[i].isdigit() and parts[i+1].isdigit() and parts[i+2].isdigit():
                                y, m, d = int(parts[i]), int(parts[i+1]), int(parts[i+2])
                                if 1980 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                                    return date(y, m, d)
        except Exception:
            pass

    # 2. Fallback to filename parsing
    basename = os.path.basename(file_path)
    
    # IGS Long name: e.g. WUM0MGXFIN_20232400000_01D_15M_ORB.SP3
    m = re.search(r'_(\d{4})(\d{3})\d{4}_', basename)
    if m:
        y, doy = int(m.group(1)), int(m.group(2))
        if 1980 <= y <= 2100 and 1 <= doy <= 366:
            return date(y, 1, 1) + timedelta(days=doy - 1)
            
    # IGS Long name with YYYYMMDD
    m = re.search(r'_(\d{4})(\d{2})(\d{2})\d{4}_', basename)
    if m:
        y, mth, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1980 <= y <= 2100 and 1 <= mth <= 12 and 1 <= d <= 31:
            return date(y, mth, d)

    # Legacy 8.3 name: e.g. wum22763.sp3, igs22763.clk
    m = re.search(r'[a-zA-Z]{3,4}(\d{4})([0-6])\.', basename)
    if m:
        week, dow = int(m.group(1)), int(m.group(2))
        gps_start = date(1980, 1, 6)
        return gps_start + timedelta(weeks=week, days=dow)

    # Generic YYYY-MM-DD or YYYYMMDD in filename
    m = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', basename)
    if m:
        y, mth, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1980 <= y <= 2100 and 1 <= mth <= 12 and 1 <= d <= 31:
            return date(y, mth, d)

    return None

def get_pco(nav, sat, t, rs, use_sis_corrections=True):
    """
    Calculates PCO correction vector (APC -> COM) in ECEF.
    r_com = r_apc - pco_ecef
    
    Args:
        use_sis_corrections (bool): If True, use full dual-signal selection; if False, use single primary signal.

    Returns:
        np.array: PCO vector in ECEF (dr)
    """
    # 1. Find PCV
    if not hasattr(nav, 'sat_ant') or not nav.sat_ant:
        return np.zeros(3)
    
    pcv = searchpcv(nav.sat_ant, sat, t)
    if pcv is None:
        print("No PCV found for satellite:", sat)
        return np.zeros(3)
    sys, prn = sat2prn(sat)
    k = nav.glo_ch.get(sat, 0) if hasattr(nav, 'glo_ch') else 0
    if sys == uGNSS.GPS:
        sigs = [rSigRnx("GC1C"), rSigRnx("GC2P")] if use_sis_corrections else [rSigRnx("GC1C")]
    elif sys == uGNSS.GAL:
        sigs = [rSigRnx("EC1C"), rSigRnx("EC7Q")] if use_sis_corrections else [rSigRnx("EC1C")]
    elif sys == uGNSS.GLO:
        sigs = [rSigRnx("RC1C"), rSigRnx("RC2P")] if use_sis_corrections else [rSigRnx("RC1C")]
    elif sys == uGNSS.BDS:
        sigs = [rSigRnx("CC2I"), rSigRnx("CC6I")] if use_sis_corrections else [rSigRnx("CC2I")]
    else:
        sigs = []

    try:
        pco_ecef = apc2com(nav, sat, t, rs, sigs, k=k)
        if pco_ecef is None:
            return np.zeros(3)
        return pco_ecef
    except Exception:
        return np.zeros(3)

def datetime2time(dt):
    return(epoch2time([dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second]))

def parse_sp3(file_path):
    """
    Parses an SP3c format file to extract satellite positions.

    Args:
        file_path (str): Path to the .sp3 file.

    Returns:
        pd.DataFrame: DataFrame containing X, Y, Z coordinates (km).
                      Index: MultiIndex ('Epoch', 'SatID').
    """
    data = []
    current_epoch = None
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"The file '{file_path}' does not exist.")

    try:
        with open(file_path, 'r') as f:
            for line in f:
                # Parse Epoch Line
                if line.startswith('*'):
                    try:
                        parts = line.split()
                        # Format: * YYYY MM DD HH MM SS.SSSSSSSS
                        year = int(parts[1])
                        month = int(parts[2])
                        day = int(parts[3])
                        hour = int(parts[4])
                        minute = int(parts[5])
                        sec_float = float(parts[6])
                        
                        # Handle seconds and microseconds for datetime
                        second = int(sec_float)
                        microsecond = int((sec_float - second) * 1e6)
                        
                        current_epoch = datetime(year, month, day, hour, minute, second, microsecond)
                    except (ValueError, IndexError):
                        print(f"Warning: Skipping malformed epoch line: {line.strip()}")
                        current_epoch = None
                        continue

                # Parse Position Line
                elif line.startswith('P'):
                    if current_epoch is None:
                        continue
                    
                    try:
                        # SP3c Fixed width is standard, but split is often safer for slight variations
                        # Standard: P<SatID> <X> <Y> <Z> <Clock>
                        # SatID is usually indices 1-4 (e.g., "PG01")
                        sat_id = line[1:4].strip()
                        if sat_id in ['C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09', 'C10', 'C13', 'C16', 'C38', 'C39', 'C40']:
                            continue
                        
                        # Parse coordinates (km)
                        # Using standard SP3 fixed widths: X(5-18), Y(19-32), Z(33-46)
                        # Using split() handles variable whitespace better if file is loose
                        parts = line.split()
                        
                        # parts[0] is usually 'PG01' or 'P' and 'G01' depending on spacing
                        # We trust standard SP3c where line starts with P followed immediately by ID
                        x_km = float(line[4:18])
                        y_km = float(line[18:32])
                        z_km = float(line[32:46])
                        
                        data.append({
                            'Epoch': current_epoch,
                            'SatID': sat_id,
                            'X_m': x_km * 1000.0,
                            'Y_m': y_km * 1000.0,
                            'Z_m': z_km * 1000.0
                        })
                    except (ValueError, IndexError):
                        continue

    except Exception as e:
        raise ValueError(f"Error parsing SP3 file: {e}")

    # Create DataFrame
    if not data:
        return pd.DataFrame(columns=['X_m', 'Y_m', 'Z_m'], index=pd.MultiIndex.from_arrays([[],[]], names=['Epoch', 'SatID']))

    df = pd.DataFrame(data)
    df.set_index(['Epoch', 'SatID'], inplace=True)
    df.sort_index(inplace=True)
    
    return df

def parse_clk(file_path):
    """
    Parses a RINEX 3 CLK format file to extract satellite clock biases.

    Args:
        file_path (str): Path to the .clk file.

    Returns:
        pd.DataFrame: DataFrame containing Clock biases (seconds).
                      Index: MultiIndex ('Epoch', 'SatID').
    """
    data = []

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"The file '{file_path}' does not exist.")

    try:
        with open(file_path, 'r') as f:
            for line in f:
                # Look for 'AS' (Satellite Clock) records
                if line.startswith('AS'):
                    try:
                        parts = line.split()
                        # Format: AS <SatID> <YYYY> <MM> <DD> <HH> <MM> <SS.SS> <BIAS> <SIGMA>
                        if len(parts) < 9:
                            continue
                            
                        sat_id = parts[1]
                        if sat_id in ['C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09', 'C10', 'C13', 'C16', 'C38', 'C39', 'C40']:
                            continue
                        
                        year = int(parts[2])
                        month = int(parts[3])
                        day = int(parts[4])
                        hour = int(parts[5])
                        minute = int(parts[6])
                        sec_float = float(parts[7])
                        
                        second = int(sec_float)
                        microsecond = int((sec_float - second) * 1e6)
                        
                        epoch = datetime(year, month, day, hour, minute, second, microsecond)
                        
                        clock_bias = float(parts[9])
                        
                        data.append({
                            'Epoch': epoch,
                            'SatID': sat_id,
                            'Clock_s': clock_bias
                        })
                    except (ValueError, IndexError):
                        continue

    except Exception as e:
        raise ValueError(f"Error parsing CLK file: {e}")

    # Create DataFrame
    if not data:
         return pd.DataFrame(columns=['Clock_s'], index=pd.MultiIndex.from_arrays([[],[]], names=['Epoch', 'SatID']))

    df = pd.DataFrame(data)
    df.set_index(['Epoch', 'SatID'], inplace=True)
    df.sort_index(inplace=True)

    return df

def parse_ssr(file_path):
    """
    Parses an SSR ASCII format file to extract orbit and clock corrections.

    Args:
        file_path (str): Path to the .ssr file.

    Returns:
        pd.DataFrame: DataFrame containing corrections.
                      Index: MultiIndex ('Epoch', 'SatID').
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"The file '{file_path}' does not exist.")

    orbit_data = []
    clock_data = []
    
    current_epoch = None
    mode = None  # 'ORBIT' or 'CLOCK'
    
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
            
        for line in lines:
            if line.startswith('> ORBIT'):
                mode = 'ORBIT'
                parts = line.split()
                try:
                    current_epoch = datetime(int(parts[2]), int(parts[3]), int(parts[4]), 
                                           int(parts[5]), int(parts[6]), int(float(parts[7])),
                                           int((float(parts[7]) - int(float(parts[7]))) * 1e6))
                except (ValueError, IndexError):
                    current_epoch = None
                    
            elif line.startswith('> CLOCK'):
                mode = 'CLOCK'
                parts = line.split()
                try:
                    current_epoch = datetime(int(parts[2]), int(parts[3]), int(parts[4]), 
                                           int(parts[5]), int(parts[6]), int(float(parts[7])),
                                           int((float(parts[7]) - int(float(parts[7]))) * 1e6))
                except (ValueError, IndexError):
                    current_epoch = None
                    
            elif line.startswith('>'):
                mode = None
                current_epoch = None
                
            else:
                if current_epoch is not None and mode in ['ORBIT', 'CLOCK']:
                    parts = line.split()
                    if not parts:
                        continue
                    
                    sat_id = parts[0]
                    # Format: SatID IODE Radial Along Cross DotRadial DotAlong DotCross
                    # Format: SatID IODE C0 C1 C2
                    
                    try:
                        if mode == 'ORBIT':
                             orbit_data.append({
                                 'Epoch': current_epoch,
                                 'SatID': sat_id,
                                 'IODE_Orb': int(float(parts[1])),
                                 'Radial': -(np.float32(parts[2])),
                                 'Along': -(np.float32(parts[3])),
                                 'Cross': -(np.float32(parts[4])),
                                 # Skip Dots for now to save space/time if not used
                             })
                                
                        elif mode == 'CLOCK':
                            clock_data.append({
                                'Epoch': current_epoch,
                                'SatID': sat_id,
                                'IODE_Clk': int(float(parts[1])),
                                'C0': float(parts[2])
                            })
                            
                    except (ValueError, IndexError):
                        continue

    except Exception as e:
         raise ValueError(f"Error parsing SSR file: {e}")

    # Create DataFrames
    df_orb = pd.DataFrame(orbit_data)
    df_clk = pd.DataFrame(clock_data)
    
    if df_orb.empty and df_clk.empty:
        return pd.DataFrame(index=pd.MultiIndex.from_arrays([[],[]], names=['Epoch', 'SatID']))
    
    # Set Indices if not empty
    if not df_orb.empty:
        df_orb.set_index(['Epoch', 'SatID'], inplace=True)
        # Handle duplicates if any (though SSR usually valid)
        if not df_orb.index.is_unique:
             df_orb = df_orb.groupby(level=[0,1]).first()
             
    if not df_clk.empty:
        df_clk.set_index(['Epoch', 'SatID'], inplace=True)
        if not df_clk.index.is_unique:
             df_clk = df_clk.groupby(level=[0,1]).first()

    # Merge
    if df_orb.empty:
        df = df_clk
    elif df_clk.empty:
        df = df_orb
    else:
        df = df_orb.join(df_clk, how='outer')
        
    df.sort_index(inplace=True)
    return df

def parse_rnx(file_path, ref_df, ssr_df=None, atx_path=None, use_sis_corrections=True, progress_callback=None):
    """
    Parses a RINEX Navigation file to calculate satellite positions.

    Args:
        file_path (str): Path to the .rnx file.
        ref_df (pd.DataFrame): Reference DataFrame (e.g., from parse_sp3) providing target epochs.
        ssr_df (pd.DataFrame, optional): DataFrame from parse_ssr containing 'IODE_Orb'. 
                                         Used to match specific ephemeris blocks.
        atx_path (str, optional): Path to .atx file for APC->COM correction.
        use_sis_corrections (bool, optional): If False, use single primary signals "GC1C" for GPS and "EC1C" for Galileo.
        progress_callback (callable, optional): Callback function(current, total, sat_id) for progress updates.

    Returns:
        pd.DataFrame: DataFrame containing X, Y, Z coordinates (km).
                      Index: MultiIndex ('Epoch', 'SatID').
    """
    # Accept either a single path or a list/tuple of paths
    rinex_files = file_path if isinstance(file_path, (list, tuple)) else [file_path]
    missing = [f for f in rinex_files if not os.path.exists(f)]
    if missing:
        raise FileNotFoundError(f"The RINEX files do not exist: {missing}")

    # Decode RINEX
    try:
        rnx = rnxdec()
        nav = Nav()
        for file in rinex_files:
            rnx.decode_nav(file, nav, append=True)
        
        # Load ATX if provided (After nav init)
        if atx_path and os.path.exists(atx_path):
            try:
                atx = atxdec()
                atx.readpcv(atx_path)
                nav.sat_ant = atx.pcvs 
            except Exception as e:
                print(f"Warning: Failed to load ATX file: {e}")
             
    except Exception as e:
        raise ValueError(f"Error decoding RINEX file: {e}")

    # Determine Target Satellites
    if ssr_df is not None and not ssr_df.empty:
        target_sats = ssr_df.index.get_level_values('SatID').unique().tolist()
    else:
        target_sats = ref_df.index.get_level_values('SatID').unique().tolist()
        
    results = []
    
    # Map satellites to target epochs from ref_df
    # Group ref_df by SatID to get list of epochs per satellite efficiently
    # ref_df index is (Epoch, SatID). Swap level for easy grouping.
    try:
        ref_grouped = ref_df.index.to_frame(index=False).groupby('SatID')['Epoch'].agg(list)
    except Exception:
        # Fallback if index to frame fails (unlikely)
        ref_grouped = {}

    # Iterate by Satellite (Outer Loop optimization)
    total_sats = len(target_sats)
    for sat_idx, sat_id_str in enumerate(target_sats):
        # Report progress via callback if provided
        if progress_callback is not None:
            progress_callback(sat_idx, total_sats, sat_id_str)
        # 1. Get Target Epochs for this Sat
        if sat_id_str in ref_grouped:
            sat_epochs = sorted(ref_grouped[sat_id_str])
        else:
            continue
            
        if not sat_epochs:
            continue
            
        # 2. Convert SatID -> Int
        try:
            sat = id2sat(sat_id_str)
        except Exception as e:
            print(f"Error during SatID conversion for {sat_id_str}: {e}")
            continue
            
        # 3. IODE Lookup Preparation (Vectorized)
        df_targets = pd.DataFrame({'Epoch': sat_epochs})
        df_targets['Epoch_Lookup'] = df_targets['Epoch'] # Duplicate for asof key
        # Precompute time objects to avoid repeated epoch2time conversions in the inner loop
        df_targets['t'] = [datetime2time(e) for e in df_targets['Epoch']]
        
        ssr_available = False
        if ssr_df is not None:
             # Extract SSR data for this satellite
             if sat_id_str in ssr_df.index.get_level_values('SatID'):
                 # xs is faster if we sorted index once, but main loop overhead dominates usually
                 # ssr_df is indexed by [Epoch, SatID]
                 # We need index to be just Epoch for asof
                 try:
                     sat_ssr = ssr_df.xs(sat_id_str, level='SatID')
                     if not sat_ssr.index.is_monotonic_increasing:
                         sat_ssr = sat_ssr.sort_index()
                     ssr_available = True
                 except Exception as e:
                     ssr_available = False

        if ssr_available and not sat_ssr.empty:
            # Perform Merge AsOf
            # direction='backward' -> finds closer earlier (or equal) match
            # Select only the SSR columns that actually exist to avoid KeyErrors
            ssr_cols = [c for c in ['IODE_Orb', 'Radial', 'Along', 'Cross', 'C0'] if c in sat_ssr.columns]
            merged = pd.merge_asof(
                df_targets, 
                sat_ssr[ssr_cols], 
                left_on='Epoch_Lookup', 
                right_index=True, 
                direction='backward',
                tolerance=pd.Timedelta(seconds=12) # Safety: use closest earlier within 4h
            )
            # merged now may contain IODE_Orb, Radial, Along, Cross, C0 (nullable) if present in SSR data
        else:
            merged = df_targets
            merged['IODE_Orb'] = np.nan
        
        merged.drop(columns=['Epoch_Lookup'], inplace=True)
        if ssr_available:
            merged.dropna(inplace=True)
        
        # Pre-compute column presence flags (optimization: check once, not per row)
        has_radial = 'Radial' in merged.columns
        has_along = 'Along' in merged.columns
        has_cross = 'Cross' in merged.columns
        has_c0 = 'C0' in merged.columns
            
        sys, _ = sat2prn(sat)
        is_glo = (sys == uGNSS.GLO)
        eph_source = nav.geph if is_glo else nav.eph

        # 4. Process Epochs
        for row in merged.itertuples(index=False):
            epoch = row.Epoch
            t = row.t  # Use pre-computed time object
            if pd.isna(row.IODE_Orb):
                iode_val = None
                try:
                    eph = findeph(eph_source, t, sat)
                except Exception:
                    eph = None
            else:
                iode_val = int(row.IODE_Orb)
                try:
                    eph = findeph(eph_source, t, sat, iode=iode_val)
                except Exception:
                    eph = None

            if eph is None:
                continue
                
            if is_glo and hasattr(eph, 'frq') and sat not in nav.glo_ch:
                nav.glo_ch[sat] = eph.frq

            try:
                # Calculate Position
                if is_glo:
                    rs, vs, _ = geph2pos(t, eph, flg_v=True)
                    dts = geph2clk(t, eph)
                else:
                    rs, vs, _ = eph2pos(t, eph, flg_v=True)
                    dts = eph2clk(t, eph)
                rs_ = rs.copy()

                if ssr_available:
                    # Extract values using pre-computed flags (faster than checking per row)
                    rad = row.Radial if has_radial else np.nan
                    along = row.Along if has_along else np.nan
                    cross = row.Cross if has_cross else np.nan
                    c0 = row.C0 if has_c0 else np.nan

                    try:
                        # Apply SSR Orbit Correction
                        et = vs / np.linalg.norm(vs)
                        ew_= np.cross(rs, vs)
                        ew = ew_ / np.linalg.norm(ew_)
                        en = np.cross(et, ew)
                        A = np.column_stack((en, et, ew))  # ECEF to RAC
                        dorb_ = np.array([rad, along, cross])

                        dorb = A @ dorb_  # Rotate to ECEF

                        rs_ = rs + dorb
                        dclk = float(c0) / rCST.CLIGHT
                        dts += dclk
                    except Exception as e:
                        # If anything fails, skip SSR orbit correction for this epoch
                        print(f"Warning: SSR orbit correction failed for {sat_id_str} at {epoch}: {e}")
                        pass

                # Apply PCO Correction (APC -> COM) if ATX loaded
                #flg_brdc = False
                #if ssr_available == False:
                #    flg_brdc = True
                if nav.sat_ant is not None:
                    pco_ecef = get_pco(nav, sat, t, rs_, use_sis_corrections=use_sis_corrections)
                    rs_+= pco_ecef

                # Store
                results.append({
                    'Epoch': epoch,
                    'SatID': sat_id_str,
                    'X_m': rs_[0],
                    'Y_m': rs_[1],
                    'Z_m': rs_[2],
                    'Clock_s': dts # Scalar
                })
            except Exception as e:
                print(f"Error processing epoch {epoch} for {sat_id_str}: {e}")
                continue

    if not results:
        return pd.DataFrame(columns=['X_m', 'Y_m', 'Z_m', 'Clock_s'], 
                            index=pd.MultiIndex.from_arrays([[],[]], names=['Epoch', 'SatID']))

    df = pd.DataFrame(results)
    df.set_index(['Epoch', 'SatID'], inplace=True)
    df.sort_index(inplace=True)
    
    return df

