import os
import sys
import argparse
from datetime import datetime
import polars as pl

def format_size(size_bytes):
    """Formats bytes into a human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"

def compact_daily_ticks(date_str: str = None):
    """
    Merges multiple small 3-minute parquet chunks into a single daily file.
    Includes any existing daily file to prevent data loss on restarts.
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # 1. Resolve paths
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    parent_dir = os.path.dirname(root_dir)
    
    base_dir = os.path.join(parent_dir, "data", "ticks", f"date={date_str}")
    
    if not os.path.exists(base_dir):
        print(f"❌ Directory not found: {base_dir}")
        return

    # 2. Identify all parquet files in the directory
    all_files = [f for f in os.listdir(base_dir) if f.endswith(".parquet")]
    
    # We want to merge the small chunks (ticks_HHMM_SS.parquet)
    chunk_files = [f for f in all_files if f.startswith("ticks_") and f != "ticks_daily.parquet"]
    
    if not chunk_files:
        print(f"ℹ️ No new chunks found in {base_dir} to compact.")
        return

    # Check if a daily file already exists from a previous run
    daily_file = "ticks_daily.parquet" if "ticks_daily.parquet" in all_files else None
    
    files_to_merge = chunk_files.copy()
    if daily_file:
        files_to_merge.append(daily_file)
        print(f"🔄 Found existing daily file. Appending {len(chunk_files)} new chunks to it...")
    else:
        print(f"🔄 Compacting {len(chunk_files)} new files for {date_str}...")

    # Calculate original total size
    original_size = sum(os.path.getsize(os.path.join(base_dir, f)) for f in files_to_merge)

    # 3. Read and Merge using Polars
    full_paths = [os.path.join(base_dir, f) for f in files_to_merge]
    
    try:
        # scan_parquet is very efficient for multiple files
        df = pl.scan_parquet(full_paths).collect()
        
        # Sort by timestamp to ensure chronological order regardless of file naming
        if "t" in df.columns:
            df = df.sort("t")
        elif "timestamp" in df.columns:
            df = df.sort("timestamp")
            
        # Drop duplicates just in case some ticks were double-saved during the restart
        df = df.unique()

        output_file = os.path.join(base_dir, "ticks_daily.parquet")
        
        # 4. Write the single large file (this will overwrite the old daily file with the new merged version)
        df.write_parquet(output_file, compression="zstd", compression_level=3)
        
        final_size = os.path.getsize(output_file)
        savings = original_size - final_size
        savings_pct = (savings / original_size) * 100 if original_size > 0 else 0

        print(f"✅ Success! Updated {output_file} ({len(df):,} total rows)")
        if not daily_file:
            print(f"📊 Stats: {format_size(original_size)} ➡️ {format_size(final_size)} (Saved {format_size(savings)} / {savings_pct:.1f}%)")

        # 5. Cleanup individual chunks (ONLY delete the ticks_HHMM_SS.parquet files, never the daily file)
        for f in chunk_files:
            os.remove(os.path.join(base_dir, f))
        print(f"🗑️ Deleted {len(chunk_files)} small chunk files.")

    except Exception as e:
        print(f"💥 Error during compaction: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compact 3-minute tick chunks into a single daily file.")
    parser.add_argument("--date", type=str, help="Date to compact (YYYY-MM-DD). Defaults to today.")
    
    args = parser.parse_args()
    compact_daily_ticks(args.date)
