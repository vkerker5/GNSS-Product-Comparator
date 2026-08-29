import numpy as np
import math
import pandas as pd

# Step 2: Implement Coordinate Geometry Helpers

def llh_to_ecef(lat, lon, h):
    """
    Converts receiver geodetic coordinates to Earth-Centered, Earth-Fixed (ECEF) XYZ.
    Parameters:
        lat: Latitude in degrees
        lon: Longitude in degrees
        h: Height in meters
    Returns:
        np.array: [X, Y, Z] in meters
    """
    a = 6378137.0
    e2 = 6.69437999014e-3
    
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)
    
    N = a / math.sqrt(1 - e2 * sin_lat**2)
    
    X = (N + h) * cos_lat * cos_lon
    Y = (N + h) * cos_lat * sin_lon
    Z = (N * (1 - e2) + h) * sin_lat
    
    return np.array([X, Y, Z])

def ecef_to_enu_matrix(lat, lon):
    """
    Returns the 3x3 rotation matrix to convert ECEF coordinate differences 
    to local East, North, Up (ENU) frame.
    Parameters:
        lat: Latitude in degrees
        lon: Longitude in degrees
    Returns:
        np.ndarray: 3x3 rotation matrix
    """
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)
    
    # Rotation matrix from ECEF to ENU
    R = np.array([
        [-sin_lon, cos_lon, 0],
        [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
        [cos_lat * cos_lon, cos_lat * sin_lon, sin_lat]
    ])
    return R


# Step 1: Define the Module Interface and Dependencies

def simulate_convergence(result_df, ref_sp3, receiver_llh, sim_duration_hours=None, flg_brdc=False):
    """
    Simulates formal coordinate error convergence over time using a Kalman Filter covariance propagation.
    - Uses Ambiguity Process Noise (Q) to capture product stability without degrading carrier-phase precision.
    - Handles cycle slips and satellite tracking dropouts natively.
    """
    import sys
    import os
    import math
    import numpy as np
    import pandas as pd
    
    try:
        from scripts.comparison_logic import calculate_elevation_from_ref
    except ImportError:
        code_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'CODE'))
        if code_dir not in sys.path:
            sys.path.append(code_dir)
        from scripts.comparison_logic import calculate_elevation_from_ref

    lat, lon, h = receiver_llh
    rec_xyz = llh_to_ecef(lat, lon, h)
    enu_matrix = ecef_to_enu_matrix(lat, lon)
    
    joined_df = result_df[['SISRE_comb_cm']].join(ref_sp3[['X_m', 'Y_m', 'Z_m']], how='inner')
    
    if joined_df.empty:
        return pd.DataFrame(columns=['Epoch', 'horizontal_error_m', 'vertical_error_m'])

    elevations_deg = calculate_elevation_from_ref(joined_df[['X_m', 'Y_m', 'Z_m']], lat, lon, h)
    joined_df['el_rad'] = np.radians(elevations_deg)
    joined_df['SISRE_m'] = joined_df['SISRE_comb_cm'] / 100.0
    
    # --- PRODUCT DETECTION & STOCHASTIC MODELING CONFIGURATION ---

    dt_sim = 10.0  # Internal step size is 10 seconds
    
    if flg_brdc == True:  
        # Broadcast Ephemeris Profile
        correlation_time = 3600.0   # 1-hour code correlation window
        sigma_phase_base = 0.06     # 3 cm phase baseline (includes unmodeled atmospheric residuals)
        q_amb = (0.03) ** 2        # 5 mm drift per 10s step to simulate orbit/clock instability
    else:                   
        # Precise Product Profile (e.g., Galileo HAS)
        correlation_time = 15.0     # 45-second rapid decorrelation
        sigma_phase_base = 0.005   # 5 mm pristine phase tracking floor
        q_amb = (1e-5) ** 2         # Near-zero drift (corrections are tightly bounded)
        
    bias_inflation = math.sqrt(correlation_time / dt_sim)
    # ---------------------------------------------------------------
    
    unique_sats = sorted(joined_df.index.get_level_values('SatID').unique())
    num_sats = len(unique_sats)
    sat_to_idx = {sat_id: i for i, sat_id in enumerate(unique_sats)}
    
    num_states = 5 + num_sats
    P = np.zeros((num_states, num_states))
    
    P[0:3, 0:3] = np.eye(3) * (100.0**2)
    P[3, 3] = 100.0**2
    P[4, 4] = 0.5**2
    for i in range(num_sats):
        P[5+i, 5+i] = 1000.0**2
    
    epochs = joined_df.index.get_level_values('Epoch').unique().sort_values()
    
    if sim_duration_hours is not None and len(epochs) > 0:
        start_time = epochs[0]
        try:
            end_time = start_time + pd.Timedelta(hours=sim_duration_hours)
        except TypeError:
            end_time = start_time + sim_duration_hours * 3600.0
        epochs = epochs[epochs <= end_time]
    
    out_epochs = []
    err_H_list = []
    err_V_list = []
    
    tracked_sats_prev = set()
    
    for i in range(len(epochs)):
        t1 = epochs[i]
        try:
            epoch_data1 = joined_df.loc[t1]
        except KeyError:
            continue
            
        if i < len(epochs) - 1:
            t2 = epochs[i+1]
            try:
                epoch_data2 = joined_df.loc[t2]
            except KeyError:
                epoch_data2 = None
        else:
            epoch_data2 = None
            
        if epoch_data2 is not None:
            try:
                dt_total = float((t2 - t1).total_seconds())
            except AttributeError:
                dt_total = float(t2 - t1)
                
            if 0 < dt_total <= 900: 
                num_steps = max(1, int(dt_total // 10))
                common_sats = epoch_data1.index.intersection(epoch_data2.index)
            else:
                num_steps = 1
                common_sats = epoch_data1.index
        else:
            num_steps = 1
            common_sats = epoch_data1.index
            
        for step in range(num_steps):
            step_seconds = step * 10
            if hasattr(t1, 'timestamp'): 
                current_t = t1 + pd.Timedelta(seconds=step_seconds)
            else:
                current_t = t1 + step_seconds
                
            if step == 0:
                sats_to_use = epoch_data1.index
                current_fraction = 0.0
            else:
                sats_to_use = common_sats
                current_fraction = step_seconds / float(dt_total)
                
            # Construct Dynamic Process Noise Matrix
            Q = np.zeros((num_states, num_states))
            Q[3, 3] = 10**4                  
            Q[4, 4] = 1e-8 * 1.0             
            
            # Inject ambiguity process noise to represent satellite product drift over time
            for s_idx in range(num_sats):
                Q[5 + s_idx, 5 + s_idx] = q_amb
            
            # Time Update
            P = P + Q
            
            n = len(sats_to_use)
            if n == 0:
                tracked_sats_prev.clear()
                out_epochs.append(current_t)
                err_H_list.append(np.nan)
                err_V_list.append(np.nan)
                continue
                
            # Cycle Slip / Re-acquisition Reset Loop
            for sat_id in sats_to_use:
                if sat_id not in tracked_sats_prev:
                    sat_idx = sat_to_idx[sat_id]
                    state_idx = 5 + sat_idx
                    P[state_idx, :] = 0.0
                    P[:, state_idx] = 0.0
                    P[state_idx, state_idx] = 1000.0**2
            
            H = np.zeros((2 * n, num_states))
            R = np.zeros((2 * n, 2 * n))
            
            sigma_code = 3.0     
            
            for j, sat_id in enumerate(sats_to_use):
                if current_fraction > 0:
                    row1 = epoch_data1.loc[sat_id]
                    row2 = epoch_data2.loc[sat_id]
                    sat_xyz = (1 - current_fraction) * np.array([row1['X_m'], row1['Y_m'], row1['Z_m']]) + current_fraction * np.array([row2['X_m'], row2['Y_m'], row2['Z_m']])
                    el = (1 - current_fraction) * row1['el_rad'] + current_fraction * row2['el_rad']
                    sisre = (1 - current_fraction) * row1['SISRE_m'] + current_fraction * row2['SISRE_m']
                else:
                    row1 = epoch_data1.loc[sat_id]
                    sat_xyz = np.array([row1['X_m'], row1['Y_m'], row1['Z_m']])
                    el = row1['el_rad']
                    sisre = row1['SISRE_m']
                    
                diff = sat_xyz - rec_xyz
                rho = np.linalg.norm(diff)
                los_vector = -diff / rho
                
                sin_el = math.sin(el) if el > 0.01 else math.sin(0.01)
                map_tropo = 1.0 / sin_el
                
                # --- CODE OBSERVATION (Inflated to protect code boundaries) ---
                H[2*j, 0:3] = los_vector
                H[2*j, 3] = 1.0             
                H[2*j, 4] = map_tropo       
                R[2*j, 2*j] = (sigma_code / sin_el)**2 + (sisre * bias_inflation)**2
                
                # --- PHASE OBSERVATION (Pristine tracking noise floor) ---
                H[2*j+1, 0:3] = los_vector
                H[2*j+1, 3] = 1.0           
                H[2*j+1, 4] = map_tropo     
                sat_idx = sat_to_idx[sat_id]
                H[2*j+1, 5 + sat_idx] = 1.0 
                
                # Phase only experiences a minute fraction of raw SISRE as unmodeled high-frequency noise
                R[2*j+1, 2*j+1] = (sigma_phase_base / sin_el)**2 + (sisre * 0.01)**2
                
            # Measurement Update 
            S = H @ P @ H.T + R
            try:
                S_inv = np.linalg.inv(S)
                K = P @ H.T @ S_inv
                P = (np.eye(num_states) - K @ H) @ P
            except np.linalg.LinAlgError:
                pass
            
            tracked_sats_prev = set(sats_to_use)
                
            P_XYZ = P[0:3, 0:3]
            P_ENU = enu_matrix @ P_XYZ @ enu_matrix.T
            err_H = math.sqrt(abs(P_ENU[0, 0] + P_ENU[1, 1]))
            err_V = math.sqrt(abs(P_ENU[2, 2]))
            
            out_epochs.append(current_t)
            err_H_list.append(err_H)
            err_V_list.append(err_V)

    return pd.DataFrame({
        'Epoch': out_epochs,
        'horizontal_error_m': err_H_list,
        'vertical_error_m': err_V_list
    })