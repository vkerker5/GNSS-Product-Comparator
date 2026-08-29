import os
import pandas as pd
import numpy as np
import scripts.comparison_logic as comparison_logic

def export_results_to_excel(
    results, 
    results_metadata, 
    target_sats_filter, 
    excluded_sats_filter, 
    save_path, 
    status_callback=None
):
    if not results:
        return
    
    def log_status(msg, color="blue"):
        if status_callback:
            status_callback(msg, color)
            
    try:
        with pd.ExcelWriter(save_path, engine='openpyxl') as writer:
            stats = []
            
            for name, df in results.items():
                if target_sats_filter:
                    df = comparison_logic.filter_by_satellite_patterns(df, target_sats_filter, exclude=False)

                if excluded_sats_filter:
                    df = comparison_logic.filter_by_satellite_patterns(df, excluded_sats_filter, exclude=True)
                
                if df.empty: 
                    continue
                
                avg_sats = results_metadata.get(name, {}).get('avg_satellites', 'N/A')
                
                if target_sats_filter:
                    for col in df.columns:
                        if "cm" in col or "ns" in col:
                            stats.append({
                                'File': name, 'Avg_Satellites': avg_sats, 'Type': 'Selected', 'Comp': col,
                                'RMS': round(np.sqrt(np.mean(df[col]**2)), 2),
                                'Mean': round(df[col].abs().mean(), 2),
                                'Min': df[col].min(), 'Max': df[col].max()
                            })
                else:
                    for col in df.columns:
                        if "cm" in col or "ns" in col:
                            const_stats = comparison_logic.aggregate_constellation_stats(df, col)
                            for sys, val in const_stats.items():
                                stats.append({
                                    'File': name, 'Avg_Satellites': avg_sats, 'Type': f'Constellation {sys}', 'Comp': col,
                                    'RMS': val['RMS'],
                                    'Mean': val['Mean'],
                                    'Min': val['Min'], 'Max': val['Max'] 
                                })

                sheet_name_raw = name[:30].replace(":", "_")
                out = df.reset_index()
                
                if 'Epoch' in out.columns:
                    times = out['Epoch'].dt
                    out['Decimal_hour_of_day'] = times.hour + (times.minute / 60.0) + (times.second / 3600.0)
                    out['Decimal_hour_of_day'] = out['Decimal_hour_of_day'].round(4)
                    
                    cols = list(out.columns)
                    cols.insert(1, cols.pop(cols.index('Decimal_hour_of_day')))
                    out = out[cols]
                    out['Epoch'] = out['Epoch'].apply(lambda x: x.replace(tzinfo=None) if hasattr(x, 'replace') else x)
                
                out.to_excel(writer, sheet_name=sheet_name_raw, index=False)

                if not target_sats_filter:
                    val_cols = [c for c in df.columns if 'cm' in c or 'ns' in c]
                    const_ts_df = comparison_logic.calculate_epoch_rms_by_system(df, val_cols)
                    
                    if not const_ts_df.empty:
                        const_ts_df.reset_index(inplace=True)
                        times = const_ts_df['Epoch'].dt
                        const_ts_df['Decimal_hour_of_day'] = times.hour + (times.minute / 60.0) + (times.second / 3600.0)
                        const_ts_df['Decimal_hour_of_day'] = const_ts_df['Decimal_hour_of_day'].round(4)

                        cols = list(const_ts_df.columns)
                        cols.insert(1, cols.pop(cols.index('Decimal_hour_of_day')))
                        const_ts_df = const_ts_df[cols]
                        const_ts_df['Epoch'] = const_ts_df['Epoch'].apply(lambda x: x.replace(tzinfo=None) if hasattr(x, 'replace') else x)
                        
                        sheet_name_agg = (name[:20] + "_Constell").replace(":", "_")
                        const_ts_df.to_excel(writer, sheet_name=sheet_name_agg, index=False)
            
            if stats:
                pd.DataFrame(stats).to_excel(writer, sheet_name="Summary_Stats", index=False)
        
        log_status(f"Saved to {os.path.basename(save_path)}", color="green")
    except Exception as e:
        log_status(f"Export Error: {e}", color="red")
        print(e)
