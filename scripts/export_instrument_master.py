import os
import sys
import polars as pl
from pymongo import MongoClient

# Ensure the project root is in sys.path so 'packages' can be imported
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from packages.settings import settings
from packages.utils.mongo import MongoRepository
from packages.utils.log_utils import setup_logger

logger = setup_logger("export_instrument_master")

def export_master_to_parquet():
    """
    Reads data from instrument_master collection of MongoDB and creates a parquet file.
    Fields: exchangeInstrumentID, description, displayName, exchangeSegment, instrumentTypeNum, series
    Target: ../data/master/master.parquet (relative to script execution or project root)
    """
    
    # 1. Target Path
    # The user specifically requested ../data/master/master.parquet
    # Assuming script is run from tradebot-python root, this points to tradebot/data/master/master.parquet
    target_path = os.path.abspath(os.path.join(os.getcwd(), "..", "data", "master", "master.parquet"))
    target_dir = os.path.dirname(target_path)
    
    # Ensure directory exists
    os.makedirs(target_dir, exist_ok=True)
    
    logger.info(f"Connecting to MongoDB and fetching from {settings.INSTRUMENT_MASTER_COLLECTION}")
    
    try:
        # 2. Fetch Data
        db = MongoRepository.get_db()
        coll = db[settings.INSTRUMENT_MASTER_COLLECTION]
        
        fields = [
            "exchangeInstrumentID",
            "description",
            "displayName",
            "exchangeSegment",
            "instrumentTypeNum",
            "series"
        ]
        
        projection = {field: 1 for field in fields}
        projection["_id"] = 0
        
        cursor = coll.find({}, projection)
        data = list(cursor)
        
        if not data:
            logger.warning(f"No data found in {settings.INSTRUMENT_MASTER_COLLECTION} collection.")
            return

        # 3. Create Polars DataFrame
        df = pl.DataFrame(data)
        
        # Ensure exchangeInstrumentID is Int64 for joining with tick data
        if "exchangeInstrumentID" in df.columns:
            df = df.with_columns(pl.col("exchangeInstrumentID").cast(pl.Int64))

        # 4. Save to Parquet
        # Overwrite is default for write_parquet
        logger.info(f"Saving {len(df)} records to {target_path}")
        df.write_parquet(target_path)
        logger.info("Export completed successfully.")
        print(f"✅ Master parquet created at: {target_path} ({len(df)} records)")

    except Exception as e:
        logger.error(f"Failed to export master data: {e}")
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    export_master_to_parquet()
