import os
import sys
import argparse
from datetime import datetime
import polars as pl

def compact_daily_ticks(date_str: str = None):
    \"\"\"
    Merges multiple small 3-minute parquet chunks into a single daily file.
    \"\"\"
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # 1. Resolve paths (relative to this script's location)
    # scripts/compact_ticks.py -> root -> data
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    parent_dir = os.path.dirname(root_dir)
    
    base_dir = os.path.join(parent_dir, "data", "ticks", f"date={date_str}")
    
    if not os.path.exists(base_dir):
        print(f"❌ Directory not found: {base_dir}")
        return

    # 2. Identify all chunk files
    all_files = [f for f in os.listdir(base_dir) if f.startswith("ticks_") and f.endswith(".parquet")]
    # Exclude any already compacted files
    chunk_files = [f for f in all_files if f != "ticks_daily.parquet"]
    
    if not chunk_files:
        print(f"ℹ️ No individual chunks found in {base_dir} to compact.")
        return

    print(f"🔄 Compacting {len(chunk_files)} files for {date_str}...")

    # 3. Read and Merge using Polars (extremely memory efficient)
    full_paths = [os.path.join(base_dir, f) for f in chunk_files]
    
    try:
        # scan_parquet allows lazy evaluation and optimized merging
        df = pl.scan_parquet(full_paths).collect()
        
        # Sort by timestamp to ensure clean data
        if "t" in df.columns:
            df = df.sort("t")
        elif "timestamp" in df.columns:
            df = df.sort("timestamp")

        output_file = os.path.join(base_dir, "ticks_daily.parquet")
        
        # 4. Write the single large file
        df.write_parquet(output_file, compression="zstd", compression_level=3)
        print(f"✅ Success! Created {output_file} ({len(df):,} rows)")

        # 5. Cleanup individual chunks
        for f in full_paths:
            os.remove(f)
        print(f"🗑️ Deleted {len(chunk_files)} small chunk files.")

    except Exception as e:
        print(f"💥 Error during compaction: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compact 3-minute tick chunks into a single daily file.")
    parser.add_argument("--date", type=str, help="Date to compact (YYYY-MM-DD). Defaults to today.")
    
    args = parser.parse_args()
    compact_daily_ticks(args.date)
