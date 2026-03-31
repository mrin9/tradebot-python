from datetime import datetime, timedelta

from packages.data.sync_history import HistoricalDataCollector
from packages.settings import settings
from packages.utils.date_utils import FMT_ISO_DATE, DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger(__name__)


def _generate_diagnostic_report(s_dt: datetime, e_dt: datetime, strike_count: int | None = None):
    """
    Internal helper to generate a completeness report.
    """
    if strike_count is None:
        strike_count = settings.OPTIONS_STRIKE_COUNT

    db = MongoRepository.get_db()
    nifty_col = db[settings.NIFTY_CANDLE_COLLECTION]
    options_col = db[settings.OPTIONS_CANDLE_COLLECTION]
    db[settings.INSTRUMENT_MASTER_COLLECTION]

    # Normalize to loop by days
    current_dt = s_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_loop_dt = e_dt.replace(hour=23, minute=59, second=59)

    days_to_check = []
    while current_dt <= end_loop_dt:
        days_to_check.append(current_dt)
        current_dt += timedelta(days=1)

    report = []

    for dt in days_to_check:
        day_str = dt.strftime(FMT_ISO_DATE)
        weekday = dt.strftime("%A")
        start_ts = DateUtils.to_timestamp(dt)
        end_ts = DateUtils.to_timestamp(dt, end_of_day=True)

        # 1. Check Spot Data
        nifty_count = nifty_col.count_documents(
            {"i": settings.NIFTY_INSTRUMENT_ID, "t": {"$gte": start_ts, "$lte": end_ts}}
        )

        row = {
            "date": day_str,
            "weekday": weekday,
            "nifty_count": nifty_count,
            "opt_status": "N/A",
            "curr_week_opt_status": "N/A",
            "status": "NO DATA",
            "curr_week_status": "N/A",
            "color": "\033[90m",  # Gray
            "missing_contracts": [],
        }

        if nifty_count == 0:
            report.append(row)
            continue

        # 2. Identify Target Contracts via ContractDiscoveryService
        from packages.services.contract_discovery import ContractDiscoveryService

        expected_contracts = ContractDiscoveryService(db).derive_target_contracts(dt, strike_count=strike_count)

        if expected_contracts:
            active_ids = [c["exchangeInstrumentID"] for c in expected_contracts]
            total_expected = len(active_ids)

            # Separate Current Weekly (first expiry in sorted list of expected contract expiries)
            expiries = sorted({c["contractExpiration"] for c in expected_contracts})
            curr_expiry = expiries[0] if expiries else None
            curr_wk_ids = [c["exchangeInstrumentID"] for c in expected_contracts if c["contractExpiration"] == curr_expiry]
            total_curr_wk = len(curr_wk_ids)

            # Check count for each contract
            counts = list(
                options_col.aggregate(
                    [
                        {"$match": {"i": {"$in": active_ids}, "t": {"$gte": start_ts, "$lte": end_ts}}},
                        {"$group": {"_id": "$i", "count": {"$sum": 1}}},
                    ]
                )
            )

            counts_dict = {c["_id"]: c["count"] for c in counts}
            complete_ids = {c_id for c_id, count in counts_dict.items() if count >= 375}

            complete_count = len(complete_ids)
            curr_wk_complete_count = sum(1 for c_id in curr_wk_ids if c_id in complete_ids)

            row["opt_status"] = f"{complete_count}/{total_expected} instr"
            row["curr_week_opt_status"] = f"{curr_wk_complete_count}/{total_curr_wk} instr"
            row["missing_contracts"] = list(set(active_ids) - complete_ids)

            # Determine statuses
            if nifty_count >= 375 and complete_count == total_expected:
                row["status"] = "FULL DATA"
                row["color"] = "\033[92m"  # Green
            else:
                row["status"] = "PARTIAL"
                row["color"] = "\033[93m"  # Yellow

            if curr_wk_complete_count == total_curr_wk:
                row["curr_week_status"] = "FULL"
                row["curr_week_color"] = "\033[92m"  # Green
            elif curr_wk_complete_count == 0:
                row["curr_week_status"] = "NO DATA"
                row["curr_week_color"] = "\033[90m"  # Gray
            else:
                row["curr_week_status"] = "PARTIAL"
                row["curr_week_color"] = "\033[93m"  # Yellow

        elif nifty_count > 0:
            row["opt_status"] = "NO MASTER"
            row["curr_week_opt_status"] = "NO MASTER"
            row["status"] = "MISSING"
            row["curr_week_status"] = "MISSING"
            row["color"] = "\033[91m"
            row["curr_week_color"] = "\033[91m"  # Red
        else:
            row["status"] = "SPOT MISSING"
            row["color"] = "\033[91m"  # Red
            row["curr_week_color"] = "\033[91m"

        report.append(row)

    return report


def check_data_gaps(start_str: str, end_str: str, strike_count: int | None = None):
    """
    Analyzes data completeness for NIFTY vs derived Options.
    Reports count of 1-min candles for Spot and average count for Options.
    """
    if strike_count is None:
        strike_count = settings.OPTIONS_STRIKE_COUNT

    # Parse Range
    s_dt, e_dt = DateUtils.parse_date_range(f"{start_str}|{end_str}")

    print(f"\n{'=' * 30} DATA GAP ANALYSIS {'=' * 30}")
    print(f"{'Date':<12} | {'Day':<10} | {'Nifty (375)':<12} | {'Curr Wk (ATM+/-10)':<18} | {'Wk Status':<10} | {'Total (3 Wks)':<15} | {'Status'}")
    print("-" * 125)

    report = _generate_diagnostic_report(s_dt, e_dt, strike_count=strike_count)

    for row in report:
        day_str = row["date"]
        weekday = row["weekday"]
        nifty_count = row["nifty_count"]
        opt_status = row["opt_status"]
        curr_wk_opt_status = row["curr_week_opt_status"]
        curr_wk_status = row["curr_week_status"]
        status = row["status"]
        color = row["color"]
        curr_wk_color = row.get("curr_week_color", "\033[0m")
        reset = "\033[0m"

        print(f"{day_str:<12} | {weekday:<10} | {nifty_count:<12} | {curr_wk_opt_status:<18} | {curr_wk_color}{curr_wk_status:<10}{reset} | {opt_status:<15} | {color}{status}{reset}")

    print("-" * 125)


def fill_data_gaps(date_range_keyword: str):
    """
    Identifies missing data and attempts to fetch it from XTS.
    Shows before and after state.
    """
    s_dt, e_dt = DateUtils.parse_date_range(date_range_keyword)

    print("\n[1/3] ANALYZING GAPS BEFORE UPDATE...")
    check_data_gaps(
        s_dt.strftime(FMT_ISO_DATE), e_dt.strftime(FMT_ISO_DATE), strike_count=settings.OPTIONS_STRIKE_COUNT
    )

    report = _generate_diagnostic_report(s_dt, e_dt, strike_count=settings.OPTIONS_STRIKE_COUNT)
    collector = HistoricalDataCollector()

    total_fetched = 0
    days_to_process = [r for r in report if r["status"] != "FULL DATA"]

    if not days_to_process:
        logger.info("No gaps identified. System is up to date.")
        return

    print(f"\n[2/3] FILLING GAPS FOR {len(days_to_process)} DAYS...")

    for row in days_to_process:
        if row["nifty_count"] == 0:
            logger.info(f"Skipping {row['date']} ({row['weekday']}) as NIFTY has zero ticks (Market Closed).")
            continue

        dt_start = DateUtils.parse_iso(row["date"])
        dt_end = dt_start.replace(hour=23, minute=59, second=59)

        # 1. Fill NIFTY Spot if missing or partial
        if row["nifty_count"] < 375:
            logger.info(f"Targeting NIFTY Spot for {row['date']}...")
            added = collector.sync_for_instrument(
                settings.NIFTY_INSTRUMENT_ID, dt_start, dt_end, is_index=True
            )
            total_fetched += added

        # 2. Fill Options
        if row["missing_contracts"]:
            logger.info(f"Targeting {len(row['missing_contracts'])} missing options for {row['date']}...")
            for inst_id in row["missing_contracts"]:
                added = collector.sync_for_instrument(inst_id, dt_start, dt_end, is_index=False)
                total_fetched += added

    print(f"\n[3/3] ANALYZING GAPS AFTER UPDATE... (Total New Candles: {total_fetched})")
    check_data_gaps(
        s_dt.strftime(FMT_ISO_DATE), e_dt.strftime(FMT_ISO_DATE), strike_count=settings.OPTIONS_STRIKE_COUNT
    )
if __name__ == "__main__":
    import sys
    import os

    # Standard Path Resolution for local imports
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  Check: python3 packages/data/data_gaps.py check [start_date] [end_date]")
        print("  Fill:  python3 packages/data/data_gaps.py fill [date_range_keyword]")
        print("\nExamples:")
        print("  python3 packages/data/data_gaps.py check (Defaults to 2dago|now)")
        print("  python3 packages/data/data_gaps.py check 2026-03-10 2026-03-15")
        print("  python3 packages/data/data_gaps.py fill yesterday")
        print("  python3 packages/data/data_gaps.py fill 2026-03-10|2026-03-15")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    
    if cmd == "check":
        arg1 = sys.argv[2] if len(sys.argv) > 2 else "2dago"
        arg2 = sys.argv[3] if len(sys.argv) > 3 else "now"
        check_data_gaps(arg1, arg2)
    elif cmd == "fill":
        arg1 = sys.argv[2] if len(sys.argv) > 2 else "2dago|now"
        fill_data_gaps(arg1)
    else:
        print(f"Unknown command: {cmd}")
