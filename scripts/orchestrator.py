import os
import pandas as pd
import scripts.file_parsers as file_parsers
import scripts.comparison_logic as comparison_logic

def run_analysis_workflow(
    mode, 
    filepaths=None, 
    ref_basename=None, 
    sisre_ref_sp3=None, 
    sisre_ref_clk=None, 
    sisre_pairs=None, 
    target_sats_filter=None, 
    excluded_sats_filter=None, 
    observer_lat=None, 
    observer_lon=None, 
    observer_h=None, 
    min_elevation=None, 
    run_cov_sim=False, 
    cov_duration_hrs=None,
    status_callback=None, 
    progress_callback=None
):
    results = {}
    results_metadata = {}
    cov_results = {}

    def log_status(msg, color="blue"):
        if status_callback:
            status_callback(msg, color)
            
    if mode == "SISRE":
        log_status("Parsing Reference Files...")
        ref_sp3_df = file_parsers.parse_sp3(sisre_ref_sp3)
        ref_clk_df = file_parsers.parse_clk(sisre_ref_clk)

        if target_sats_filter:
            if not ref_sp3_df.empty:
                ref_sp3_df = comparison_logic.filter_by_satellite_patterns(ref_sp3_df, target_sats_filter, exclude=False)
            if not ref_clk_df.empty:
                ref_clk_df = comparison_logic.filter_by_satellite_patterns(ref_clk_df, target_sats_filter, exclude=False)

        if excluded_sats_filter:
            if not ref_sp3_df.empty:
                ref_sp3_df = comparison_logic.filter_by_satellite_patterns(ref_sp3_df, excluded_sats_filter, exclude=True)
            if not ref_clk_df.empty:
                ref_clk_df = comparison_logic.filter_by_satellite_patterns(ref_clk_df, excluded_sats_filter, exclude=True)
        
        total_pairs = len(sisre_pairs) if sisre_pairs else 0
        for pair_idx, pair in enumerate(sisre_pairs):
            log_status(f"Processing {pair['name']}...")
            if pair['sp3'] != "BRDC" and pair['sp3'].split('.')[-1].lower() != "ssr":
                if progress_callback and total_pairs > 0:
                    progress_callback(pair_idx, total_pairs, pair['name'])
            if pair['sp3'] == "BRDC" or pair['sp3'].split('.')[-1].lower() == "ssr":
                ssr_df = None
                if pair['sp3'] != "BRDC":
                    ssr_df = file_parsers.parse_ssr(pair['sp3'])
                    if target_sats_filter and not ssr_df.empty:
                        ssr_df = comparison_logic.filter_by_satellite_patterns(ssr_df, target_sats_filter, exclude=False)
                    if excluded_sats_filter and not ssr_df.empty:
                        ssr_df = comparison_logic.filter_by_satellite_patterns(ssr_df, excluded_sats_filter, exclude=True)
                
                atx_file = pair.get('atx')
                
                rnx_df = file_parsers.parse_rnx(
                    pair['clk'], ref_sp3_df, ssr_df=ssr_df,
                    atx_path=atx_file,
                    use_sis_corrections=pair.get('sis_corrections', True),
                    progress_callback=progress_callback,
                )
                
                if rnx_df.empty:
                    log_status(f"Warning: No valid data found in RINEX {pair['clk']}", color="red")
                    continue
                
                comp_sp3_df = rnx_df[['X_m', 'Y_m', 'Z_m']]
                if 'Clock_s' in rnx_df.columns:
                    comp_clk_df = rnx_df[['Clock_s']]
                else:
                    comp_clk_df = pd.DataFrame(index=rnx_df.index, columns=['Clock_s']).fillna(0)
            else:
                comp_sp3_df = file_parsers.parse_sp3(pair['sp3'])
                comp_clk_df = file_parsers.parse_clk(pair['clk'])

                if target_sats_filter:
                    if not comp_sp3_df.empty:
                        comp_sp3_df = comparison_logic.filter_by_satellite_patterns(comp_sp3_df, target_sats_filter, exclude=False)
                    if not comp_clk_df.empty:
                        comp_clk_df = comparison_logic.filter_by_satellite_patterns(comp_clk_df, target_sats_filter, exclude=False)

                if excluded_sats_filter:
                    if not comp_sp3_df.empty:
                        comp_sp3_df = comparison_logic.filter_by_satellite_patterns(comp_sp3_df, excluded_sats_filter, exclude=True)
                    if not comp_clk_df.empty:
                        comp_clk_df = comparison_logic.filter_by_satellite_patterns(comp_clk_df, excluded_sats_filter, exclude=True)
                
                if not ref_sp3_df.empty:
                    ref_epochs = ref_sp3_df.index.get_level_values('Epoch').unique().sort_values()
                    
                    if not comp_sp3_df.empty:
                        log_status(f"Interpolating SP3 for {pair['name']}...")
                        comp_sp3_df = comparison_logic.interpolate_to_reference(comp_sp3_df, ref_epochs, method='lagrange', order=9)

                    if not comp_clk_df.empty:
                        log_status(f"Interpolating CLK for {pair['name']}...")
                        comp_clk_df = comparison_logic.interpolate_to_reference(comp_clk_df, ref_epochs, method='time')
            
            if observer_lat is not None and observer_lon is not None:
                res_df = comparison_logic.calculate_sisre_combined(
                    ref_sp3_df, ref_clk_df, comp_sp3_df, comp_clk_df,
                    obs_lat=observer_lat, obs_lon=observer_lon, obs_h=observer_h, min_elevation=min_elevation
                )
                
                if run_cov_sim:
                    log_status(f"Simulating Covariance for {pair['name']}...")
                    try:
                        from scripts.covariance_sim import simulate_convergence
                        cov_res = simulate_convergence(
                           result_df=res_df, 
                           ref_sp3=ref_sp3_df, 
                           receiver_llh=(observer_lat, observer_lon, observer_h),
                           sim_duration_hours=cov_duration_hrs,
                           flg_brdc=True if pair['sp3'] == "BRDC" else False
                        )
                        cov_results[pair['name']] = cov_res
                    except Exception as e:
                        log_status(f"Covariance sim error: {e}", color="red")
            else:
                res_df = comparison_logic.calculate_sisre_combined(
                    ref_sp3_df, ref_clk_df, comp_sp3_df, comp_clk_df
                )

            if not res_df.empty:
                if target_sats_filter:
                    res_df = comparison_logic.filter_by_satellite_patterns(res_df, target_sats_filter, exclude=False)
                if excluded_sats_filter:
                    res_df = comparison_logic.filter_by_satellite_patterns(res_df, excluded_sats_filter, exclude=True)

            if not res_df.empty:
                results[pair['name']] = res_df
                avg_sats = comparison_logic.calculate_average_satellites(res_df)
                results_metadata[pair['name']] = {'avg_satellites': avg_sats}

    else:
        ref_path = next((f for f in filepaths if os.path.basename(f) == ref_basename), None)
        if mode == 'SP3': 
            ref_df = file_parsers.parse_sp3(ref_path)
        else: 
            ref_df = file_parsers.parse_clk(ref_path)

        if target_sats_filter and not ref_df.empty:
            ref_df = comparison_logic.filter_by_satellite_patterns(ref_df, target_sats_filter, exclude=False)
        if excluded_sats_filter and not ref_df.empty:
            ref_df = comparison_logic.filter_by_satellite_patterns(ref_df, excluded_sats_filter, exclude=True)
        
        comp_files = [f for f in filepaths if f != ref_path] if filepaths else []
        total_files = len(comp_files)
        for file_idx, file_path in enumerate(comp_files):
            comp_basename = os.path.basename(file_path)
            
            log_status(f"Comparing {comp_basename}...")
            if progress_callback and total_files > 0:
                progress_callback(file_idx, total_files, comp_basename)
            
            if mode == 'SP3': 
                comp_df = file_parsers.parse_sp3(file_path)
            else: 
                comp_df = file_parsers.parse_clk(file_path)

            if target_sats_filter and not comp_df.empty:
                comp_df = comparison_logic.filter_by_satellite_patterns(comp_df, target_sats_filter, exclude=False)
            if excluded_sats_filter and not comp_df.empty:
                comp_df = comparison_logic.filter_by_satellite_patterns(comp_df, excluded_sats_filter, exclude=True)
                
            if observer_lat is not None and observer_lon is not None:
                res_df = comparison_logic.calculate_differences(
                    ref_df, comp_df, mode,
                    obs_lat = observer_lat,
                    obs_lon = observer_lon,
                    obs_h = observer_h,
                    min_elevation=min_elevation
                )
            else:
                res_df = comparison_logic.calculate_differences(ref_df, comp_df, mode)

            if not res_df.empty:
                if target_sats_filter:
                    res_df = comparison_logic.filter_by_satellite_patterns(res_df, target_sats_filter, exclude=False)
                if excluded_sats_filter:
                    res_df = comparison_logic.filter_by_satellite_patterns(res_df, excluded_sats_filter, exclude=True)

            if not res_df.empty:
                results[comp_basename] = res_df
                avg_sats = comparison_logic.calculate_average_satellites(res_df)
                results_metadata[comp_basename] = {'avg_satellites': avg_sats}
                
    return results, results_metadata, cov_results
