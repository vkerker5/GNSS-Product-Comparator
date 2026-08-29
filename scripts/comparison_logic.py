import pandas as pd
import numpy as np
from cssrlib.gnss import satazel, pos2ecef
from scipy.interpolate import BarycentricInterpolator

# Constants
def calculate_average_satellites(df):
    """
    Calculates the average number of satellites per epoch.
    
    Args:
        df: DataFrame with MultiIndex (Epoch, SatID)
    
    Returns:
        int: Average number of satellites per epoch (rounded to integer)
    """
    if df.empty:
        return 0
    
    # Count unique satellites per epoch
    sats_per_epoch = df.index.get_level_values('Epoch').value_counts()
    
    # Calculate average and convert to integer
    avg_sats = int(round(sats_per_epoch.mean()))
    
    return avg_sats

def calculate_elevation_from_ref(ref_positions_df, observer_lat, observer_lon, observer_alt=0.0):
    """
    Calculates elevation angles for satellites in DataFrame using reference positions.
    Fully vectorized using NumPy for ultra-fast performance.
    
    Args:
        ref_positions_df: DataFrame with MultiIndex (Epoch, SatID) and columns [X_m, Y_m, Z_m]
        observer_lat: Observer latitude in degrees
        observer_lon: Observer longitude in degrees
        observer_alt: Observer altitude in meters (default: 0.0)
    
    Returns:
        np.ndarray: Elevation angles in degrees for each row
    """
    if ref_positions_df.empty or observer_lat is None or observer_lon is None:
        return np.array([], dtype=np.float64)
        
    if observer_alt is None:
        observer_alt = 0.0

    # Extract satellite positions as (N, 3) float64 array
    sat_ecef = ref_positions_df[['X_m', 'Y_m', 'Z_m']].to_numpy(dtype=np.float64)
    if sat_ecef.shape[0] == 0:
        return np.array([], dtype=np.float64)

    # Convert observer LLH position to ECEF (3,)
    observer_pos_rad = np.array([np.radians(observer_lat), np.radians(observer_lon), float(observer_alt)], dtype=np.float64)
    observer_ecef = pos2ecef(observer_pos_rad)

    # ENU rotation matrix for observer (3, 3)
    lat_rad, lon_rad = observer_pos_rad[0], observer_pos_rad[1]
    sin_lat, cos_lat = np.sin(lat_rad), np.cos(lat_rad)
    sin_lon, cos_lon = np.sin(lon_rad), np.cos(lon_rad)

    R_enu = np.array([
        [-sin_lon, cos_lon, 0.0],
        [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
        [cos_lat * cos_lon, cos_lat * sin_lon, sin_lat]
    ], dtype=np.float64)

    # Vector from receiver to satellite: (N, 3)
    diff = sat_ecef - observer_ecef

    # Rotate into ENU local frame: (N, 3)
    enu = diff @ R_enu.T

    # Slant range distance (N,)
    rho = np.linalg.norm(enu, axis=1)

    # Valid mask for non-zero range and non-NaN entries
    valid_mask = (rho > 0.0) & ~np.isnan(rho)

    elevations = np.full(len(rho), -90.0, dtype=np.float64)
    if np.any(valid_mask):
        sin_el = np.clip(enu[valid_mask, 2] / rho[valid_mask], -1.0, 1.0)
        elevations[valid_mask] = np.degrees(np.arcsin(sin_el))

    return elevations

def filter_results_by_elevation(result_df, ref_aligned, observer_lat, observer_lon, min_elevation=5.0, observer_alt=0.0):
    """
    Filters result DataFrame by satellite elevation angle calculated from reference positions.
    
    Args:
        result_df: DataFrame with comparison results, MultiIndex (Epoch, SatID)
        ref_aligned: Reference DataFrame with satellite positions, same MultiIndex
        observer_lat: Observer latitude in degrees
        observer_lon: Observer longitude in degrees
        min_elevation: Minimum elevation angle in degrees (default: 5.0)
        observer_alt: Observer altitude in meters (default: 0.0)
    
    Returns:
        pd.DataFrame: Filtered result DataFrame with only satellites above min_elevation
    """
    if result_df.empty or ref_aligned.empty or observer_lat is None or observer_lon is None:
        return result_df
    
    # Fast path if indices already match exactly
    if result_df.index.equals(ref_aligned.index):
        result_aligned = result_df
        ref_pos_aligned = ref_aligned[['X_m', 'Y_m', 'Z_m']]
    else:
        common_idx = result_df.index.intersection(ref_aligned.index)
        if len(common_idx) == 0:
            return result_df
        result_aligned = result_df.loc[common_idx]
        ref_pos_aligned = ref_aligned.loc[common_idx, ['X_m', 'Y_m', 'Z_m']]
    
    # Calculate elevations for filtered positions
    elevations = calculate_elevation_from_ref(ref_pos_aligned, observer_lat, observer_lon, observer_alt)
    
    # Filter by elevation angle
    if len(elevations) > 0:
        mask = elevations >= min_elevation
        return result_aligned[mask]
    else:
        return result_aligned

def calculate_velocity_from_positions(df_pos):
    """
    Calculates satellite velocity (m/s) using central differences with 
    forward/backward difference boundary handling so no boundary epochs are lost.
    """
    if df_pos.empty:
        return pd.DataFrame(columns=['Vx_ms', 'Vy_ms', 'Vz_ms'])

    sat_ids = df_pos.index.get_level_values('SatID')
    epochs = df_pos.index.get_level_values('Epoch')
    
    pos_arr = df_pos[['X_m', 'Y_m', 'Z_m']].to_numpy(dtype=np.float64)
    time_sec = epochs.astype('int64').to_numpy() / 1e9
    
    unique_sats = df_pos.index.get_level_values('SatID').unique()
    vel_arr = np.empty_like(pos_arr)
    
    for sat in unique_sats:
        mask = (sat_ids == sat)
        sat_idx = np.where(mask)[0]
        n_pts = len(sat_idx)
        
        if n_pts < 2:
            vel_arr[sat_idx] = np.nan
            continue
            
        t_sat = time_sec[sat_idx]
        pos_sat = pos_arr[sat_idx]
        v_sat = np.empty_like(pos_sat)
        
        # Central difference for interior points
        if n_pts > 2:
            dt_central = (t_sat[2:] - t_sat[:-2])[:, None]
            dt_central = np.where(dt_central == 0.0, 1.0, dt_central)
            v_sat[1:-1] = (pos_sat[2:] - pos_sat[:-2]) / dt_central
            
        # Forward difference at start
        dt_start = t_sat[1] - t_sat[0]
        v_sat[0] = (pos_sat[1] - pos_sat[0]) / dt_start if dt_start > 0 else 0.0
        
        # Backward difference at end
        dt_end = t_sat[-1] - t_sat[-2]
        v_sat[-1] = (pos_sat[-1] - pos_sat[-2]) / dt_end if dt_end > 0 else 0.0
        
        vel_arr[sat_idx] = v_sat

    return pd.DataFrame(vel_arr, index=df_pos.index, columns=['Vx_ms', 'Vy_ms', 'Vz_ms'])

def ecef_to_rac(ref_pos, ref_vel, diff_ecef):
    """
    Transforms coordinate differences from ECEF to Radial, Along-track, Cross-track.
    """
    # Align all inputs
    common_idx = ref_pos.index.intersection(ref_vel.index).intersection(diff_ecef.index)
    
    r = ref_pos.loc[common_idx].values
    v = ref_vel.loc[common_idx].values
    d = diff_ecef.loc[common_idx].values
    
    # 1. Radial Unit Vector
    r_norm = np.linalg.norm(r, axis=1, keepdims=True)
    r_norm = np.where(r_norm == 0.0, 1.0, r_norm)
    e_R = r / r_norm
    
    # 2. Cross-track Unit Vector
    cross_rv = np.cross(r, v)
    cross_norm = np.linalg.norm(cross_rv, axis=1, keepdims=True)
    cross_norm = np.where(cross_norm == 0.0, 1.0, cross_norm)
    e_C = cross_rv / cross_norm
    
    # 3. Along-track Unit Vector
    e_A = np.cross(e_C, e_R)
    
    # 4. Project
    dR = np.sum(d * e_R, axis=1)
    dA = np.sum(d * e_A, axis=1)
    dC = np.sum(d * e_C, axis=1)
    
    return pd.DataFrame({'dR_cm': dR, 'dA_cm': dA, 'dC_cm': dC}, index=common_idx)

def assign_weights(sat_id):
    """Helper to map SatID to weights for vectorization."""
    sys_id = sat_id[0]
    try:
        prn = int(sat_id[1:])
    except:
        prn = 0

    if sys_id == 'G': return 0.98, 1.0/49.0
    if sys_id == 'R': return 0.98, 1.0/45.0
    if sys_id == 'E': return 0.984, 1.0/61.0
    if sys_id == 'C':
        if prn in range(1, 6) or prn > 58: return 0.99, 1.0/126.0
        return 0.98, 1.0/54.0
    if sys_id in ['J', 'I']: return 0.99, 1.0/126.0
    
    return 0.98, 1.0/49.0

def assign_weights_vectorized(sat_series):
    """
    Returns w_R and w_AC 1D numpy arrays for a pandas Series or Index of SatIDs.
    """
    if not isinstance(sat_series, pd.Series):
        sat_series = pd.Series(sat_series)
        
    sys_ids = sat_series.str[0].values
    try:
        prns = sat_series.str[1:].astype(int).values
    except Exception:
        prns = np.zeros(len(sat_series), dtype=int)

    w_R = np.full(len(sat_series), 0.98, dtype=np.float64)
    w_AC = np.full(len(sat_series), 1.0 / 49.0, dtype=np.float64)

    # Galileo ('E')
    mask_E = (sys_ids == 'E')
    w_R[mask_E] = 0.984
    w_AC[mask_E] = 1.0 / 61.0

    # GLONASS ('R')
    mask_R = (sys_ids == 'R')
    w_R[mask_R] = 0.98
    w_AC[mask_R] = 1.0 / 45.0

    # BeiDou ('C')
    mask_C = (sys_ids == 'C')
    bds_geo = mask_C & ((prns >= 1) & (prns <= 5) | (prns > 58))
    bds_non_geo = mask_C & ~((prns >= 1) & (prns <= 5) | (prns > 58))

    w_R[bds_geo] = 0.99
    w_AC[bds_geo] = 1.0 / 126.0

    w_R[bds_non_geo] = 0.98
    w_AC[bds_non_geo] = 1.0 / 54.0

    # QZSS ('J') / IRNSS ('I')
    mask_JI = (sys_ids == 'J') | (sys_ids == 'I')
    w_R[mask_JI] = 0.99
    w_AC[mask_JI] = 1.0 / 126.0

    return w_R, w_AC

def interpolate_to_reference(target_df, ref_epochs, method='time', limit=1, order=9):
    """
    Interpolates target DataFrame to match reference epochs for each satellite.
    
    Args:
        target_df: DataFrame with MultiIndex (Epoch, SatID) to be interpolated.
        ref_epochs: List or Index of datetimes representing the reference epochs.
        method: Interpolation method: 'time' / 'linear' (linear interpolation) or 'lagrange' (windowed polynomial).
        limit: Maximum number of consecutive NaNs to fill for 'time' method.
        order: Order of Lagrange polynomial (window size = order + 1). Default 9 (IOVG standard).
        
    Returns:
        pd.DataFrame: Interpolated DataFrame containing only epochs present in ref_epochs.
    """
    if target_df.empty:
        return target_df

    # Ensure ref_epochs is sorted datetime index
    if not isinstance(ref_epochs, pd.DatetimeIndex):
        ref_epochs = pd.DatetimeIndex(ref_epochs).sort_values()
    else:
        ref_epochs = ref_epochs.sort_values()

    window_size = order + 1
    half_win = window_size // 2
    interpolated_list = []

    # Process each satellite group
    for sat_id, group in target_df.groupby(level='SatID'):
        group = group.droplevel('SatID')
        group = group[~group.index.duplicated(keep='first')].sort_index()
        if group.empty:
            continue

        min_t, max_t = group.index[0], group.index[-1]
        mask = (ref_epochs >= min_t) & (ref_epochs <= max_t)
        target_epochs = ref_epochs[mask]
        if len(target_epochs) == 0:
            continue

        numeric_cols = group.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) == 0:
            continue

        x_known = (group.index - min_t).total_seconds().values
        x_req = (target_epochs - min_t).total_seconds().values
        vals_known = group[numeric_cols].values
        n_known = len(x_known)
        n_req = len(x_req)
        n_cols = len(numeric_cols)

        if method == 'lagrange':
            if n_known < window_size:
                continue

            res_matrix = np.full((n_req, n_cols), np.nan)
            valid_mask = np.zeros(n_req, dtype=bool)

            idx_arr = np.searchsorted(x_known, x_req)
            last_start_i = -1
            inv_denom = None

            for i in range(n_req):
                xr = x_req[i]
                idx = idx_arr[i]

                # Exact match check (point already exists in known data)
                if idx < n_known and abs(x_known[idx] - xr) < 1e-4:
                    res_matrix[i] = vals_known[idx]
                    valid_mask[i] = True
                    continue

                # Clamp window bounds to keep window size fixed near boundaries
                start_i = idx - half_win
                if start_i < 0:
                    start_i = 0
                elif start_i + window_size > n_known:
                    start_i = n_known - window_size

                end_i = start_i + window_size
                x_win = x_known[start_i:end_i]

                # Gap check: skip if max gap in window is > 2.5 * median gap (missing data)
                diffs = np.diff(x_win)
                if len(diffs) > 0 and np.max(diffs) > 2.5 * np.median(diffs):
                    continue

                # Precompute and cache invariant denominator when sliding window changes
                if start_i != last_start_i:
                    diff_matrix = x_win[:, None] - x_win[None, :]
                    np.fill_diagonal(diff_matrix, 1.0)
                    denom = np.prod(diff_matrix, axis=1)
                    inv_denom = 1.0 / denom
                    last_start_i = start_i

                # Vectorized numerator & weights for target xr
                dx = xr - x_win
                num_matrix = np.tile(dx, (window_size, 1))
                np.fill_diagonal(num_matrix, 1.0)
                num = np.prod(num_matrix, axis=1)
                w = num * inv_denom

                # Evaluate all numeric columns at once via 1D @ 2D matrix multiplication
                res_matrix[i] = w @ vals_known[start_i:end_i]
                valid_mask[i] = True

            if np.any(valid_mask):
                final_res = pd.DataFrame(
                    res_matrix[valid_mask],
                    index=target_epochs[valid_mask],
                    columns=numeric_cols
                )
            else:
                final_res = pd.DataFrame()

        else: # Fast linear / time method
            res_matrix = np.empty((n_req, n_cols))
            for c in range(n_cols):
                res_matrix[:, c] = np.interp(x_req, x_known, vals_known[:, c])
            final_res = pd.DataFrame(res_matrix, index=target_epochs, columns=numeric_cols)

        if not final_res.empty:
            final_res.index.name = 'Epoch'
            final_res['SatID'] = sat_id
            interpolated_list.append(final_res)

    if not interpolated_list:
        return pd.DataFrame()

    result = pd.concat(interpolated_list)
    result.set_index('SatID', append=True, inplace=True)
    result = result.reorder_levels(['Epoch', 'SatID'])
    result.sort_index(inplace=True)
    return result

def calculate_sisre_combined(ref_sp3, ref_clk, comp_sp3, comp_clk, obs_lat=None, obs_lon=None, obs_h=None, min_elevation=5.0):
    """
    Calculates the 'Global SISRE' combining Orbit and Clock products.
    
    Args:
        ref_sp3, ref_clk, comp_sp3, comp_clk: Reference and comparison DataFrames
        obs_lat: Observer latitude in degrees (optional, for elevation filtering)
        obs_lon: Observer longitude in degrees (optional, for elevation filtering)
        obs_h: Observer altitude in meters (optional, for elevation filtering)
        min_elevation: Minimum elevation angle in degrees (default: 5.0)
    
    Returns:
        pd.DataFrame: DataFrame with dR_cm, dA_cm, dC_cm, dClock_ns, and SISRE_comb_cm.
    """
    ref_full = ref_sp3.join(ref_clk, how='inner')
    comp_full = comp_sp3.join(comp_clk, how='inner')
    
    ref_aligned, comp_aligned = ref_full.align(comp_full, join='inner')
    if ref_aligned.empty:
        print("Warning: No common data points (Epoch/Sat) across all files.")
        return pd.DataFrame()

    # Orbit ECEF difference
    diff_ecef = comp_aligned[['X_m', 'Y_m', 'Z_m']] - ref_aligned[['X_m', 'Y_m', 'Z_m']]
    diff_ecef_cm = diff_ecef * 100.0

    # Calculate Velocity from Reference Orbits (with boundary preservation)
    ref_vel = calculate_velocity_from_positions(ref_aligned)
    
    # Transform to RAC
    rac_df = ecef_to_rac(ref_aligned[['X_m', 'Y_m', 'Z_m']], ref_vel, diff_ecef_cm)

    # Clock difference & bias removal (computed over global constellation)
    raw_clk_diff = comp_aligned['Clock_s'] - ref_aligned['Clock_s']
    sat_ids_series = pd.Series(raw_clk_diff.index.get_level_values('SatID'), index=raw_clk_diff.index)
    sys_series = pd.Series(sat_ids_series.str[0].values, index=raw_clk_diff.index)
    epoch_level = raw_clk_diff.index.get_level_values('Epoch')

    # Remove System Time Bias (Constellation Median per Epoch)
    epoch_sys_bias = raw_clk_diff.groupby([epoch_level, sys_series]).transform('median')
    dClock_s = raw_clk_diff - epoch_sys_bias

    # Remove Satellite-specific median clock bias
    sat_bias = dClock_s.groupby(sat_ids_series).transform('median')
    dClock_s = dClock_s - sat_bias
    dClock_ns = dClock_s * 1e9

    # Combine RAC and Clock
    result_df = rac_df.copy()
    result_df['dClock_ns'] = dClock_ns.loc[result_df.index]

    # Vectorized SISRE calculation
    w_R_arr, w_AC_arr = assign_weights_vectorized(result_df.index.get_level_values('SatID'))

    dR = result_df['dR_cm'].values
    dA = result_df['dA_cm'].values
    dC = result_df['dC_cm'].values
    dT = result_df['dClock_ns'].values

    term1 = (w_R_arr * dR - dT) ** 2
    term2 = (w_AC_arr ** 2) * (dA ** 2 + dC ** 2)

    result_df['SISRE_comb_cm'] = np.sqrt(term1 + term2)
    result_df = result_df.round(2)

    # Apply elevation masking after global RAC, clock bias, and SISRE computation
    if obs_lat is not None and obs_lon is not None and min_elevation is not None:
        elevations = calculate_elevation_from_ref(ref_aligned.loc[result_df.index, ['X_m', 'Y_m', 'Z_m']], obs_lat, obs_lon, observer_alt=obs_h)
        if len(elevations) > 0:
            elev_mask = (elevations >= min_elevation)
            result_df = result_df[elev_mask]

    return result_df

def aggregate_constellation_stats(df, col_name):
    """
    Aggregates statistics by Constellation (First letter of SatID).
    Returns a dictionary: {'G': {'RMS': rms_val, 'Mean': mean_val, 'Min': min_val, 'Max': max_val}, ...}
    """
    if df.empty or col_name not in df.columns:
        return {}

    # Create a temporary column for System ID
    sys_ids = df.index.get_level_values('SatID').str[0]
    
    stats = {}
    unique_sys = sys_ids.unique()
    
    for sys in unique_sys:
        # Filter data for this system
        mask = (sys_ids == sys)
        sys_data = df.loc[mask, col_name]
        
        # Calculate all statistics
        rms = np.sqrt(np.mean(sys_data**2))
        stats[sys] = {
            'RMS': round(rms, 2),
            'Mean': round(sys_data.abs().mean(), 2),
            'Min': sys_data.min(),
            'Max': sys_data.max()
        }
        
    return stats

def calculate_differences(ref_df, comp_df, product_type, obs_lat=None, obs_lon=None, obs_h=None, min_elevation=None):
    """
    Legacy wrapper for single-type comparison.
    """
    ref_aligned, comp_aligned = ref_df.align(comp_df, join='inner')

    if ref_aligned.empty:
        return pd.DataFrame()

    if product_type == 'SP3':
        diff_df = comp_aligned - ref_aligned
        diff_df = diff_df * 100
        diff_df = diff_df.round(2)
        diff_df.columns = ['dX_cm', 'dY_cm', 'dZ_cm']

        if obs_lat is not None and obs_lon is not None and min_elevation is not None:
            elevations = calculate_elevation_from_ref(ref_aligned[['X_m', 'Y_m', 'Z_m']], obs_lat, obs_lon, observer_alt=obs_h)
            if len(elevations) > 0:
                elev_mask = elevations >= min_elevation
                diff_df = diff_df[elev_mask]

        return diff_df

    elif product_type == 'CLK':
        raw_diff_series = comp_aligned['Clock_s'] - ref_aligned['Clock_s'] if 'Clock_s' in comp_aligned.columns else comp_aligned - ref_aligned
        if isinstance(raw_diff_series, pd.DataFrame):
            raw_diff_series = raw_diff_series.iloc[:, 0]
        
        sat_ids_series = pd.Series(raw_diff_series.index.get_level_values('SatID'), index=raw_diff_series.index)
        sys_series = pd.Series(sat_ids_series.str[0].values, index=raw_diff_series.index)
        epoch_level = raw_diff_series.index.get_level_values('Epoch')

        epoch_bias = raw_diff_series.groupby([epoch_level, sys_series]).transform('median')
        diff_s = raw_diff_series - epoch_bias

        satellite_bias = diff_s.groupby(sat_ids_series).transform('median')
        diff_s = diff_s - satellite_bias

        diff_ns = diff_s * 1e9
        diff_df = pd.DataFrame({'dClock_ns': diff_ns.round(2)}, index=raw_diff_series.index)
        return diff_df

    else:
        raise ValueError("Invalid product type")

def parse_satellite_patterns(text, ignore_values=None):
    """Parse comma-separated satellite tokens with optional prefix wildcards."""
    if ignore_values is None:
        ignore_values = {"ALL", "NONE"}

    if not text:
        return None

    text = text.strip().upper()
    if text in ignore_values:
        return None

    tokens = [token.strip() for token in text.split(',') if token.strip()]
    if not tokens:
        return None

    patterns = {'exact': [], 'prefix': []}
    for token in tokens:
        if token.endswith('*'):
            patterns['prefix'].append(token[:-1])
        else:
            patterns['exact'].append(token)

    return patterns if patterns['exact'] or patterns['prefix'] else None

def satellite_pattern_mask(sat_ids, patterns):
    if not patterns:
        return None

    sat_ids = pd.Index(sat_ids).astype(str)
    mask = np.zeros(len(sat_ids), dtype=bool)

    exact = patterns.get('exact') or []
    prefix = patterns.get('prefix') or []

    if exact:
        mask |= sat_ids.isin(exact)

    for prefix_token in prefix:
        if prefix_token == "":
            mask[:] = True
            break
        mask |= sat_ids.str.startswith(prefix_token)

    return mask

def filter_by_satellite_patterns(df, patterns, exclude=False):
    if patterns is None or df.empty:
        return df

    mask = satellite_pattern_mask(df.index.get_level_values('SatID'), patterns)
    return df[~mask] if exclude else df[mask]

def calculate_rms(data_series):
    """Calculate RMS of a series."""
    return np.sqrt(np.mean(data_series**2))

def calculate_epoch_rms_by_system(df, val_cols):
    """
    Calculates the RMS per epoch for each constellation system.
    Returns a DataFrame with columns: <sys>_<col>_RMS
    """
    if df.empty:
        return pd.DataFrame()
        
    df_agg = df.copy()
    df_agg['Sys'] = df_agg.index.get_level_values('SatID').str[0]
    unique_sys = df_agg['Sys'].unique()
    
    agg_frames = []
    for sys in unique_sys:
        sys_data = df_agg[df_agg['Sys'] == sys]
        for col in val_cols:
            if col not in sys_data.columns:
                continue
            epoch_rms = round(sys_data[col].groupby(level='Epoch').apply(lambda x: np.sqrt(np.mean(x**2))), 2)
            temp_df = epoch_rms.to_frame(name=f"{sys}_{col}_RMS")
            agg_frames.append(temp_df)
    
    if agg_frames:
        return pd.concat(agg_frames, axis=1)
    return pd.DataFrame()