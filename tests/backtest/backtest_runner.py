import argparse
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from packages.services.trade_config_service import TradeConfigService
from packages.settings import settings
from packages.tradeflow.fund_manager import FundManager
from packages.utils.log_utils import setup_logger

logger = setup_logger("BacktestRunner")


def get_parser():
    parser = argparse.ArgumentParser(description="Backtest Runner")
    parser.add_argument("--mode", type=str, choices=["db", "socket"], default="db", help="Backtest mode: db or socket")
    parser.add_argument("--start", type=str, default="2026-02-02", help="Start Date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End Date (YYYY-MM-DD). Defaults to --start if omitted.")
    parser.add_argument(
        "--strategy-id", "-I", type=str, default="triple-confirmation", help="Strategy Indicator ID (from DB)."
    )
    parser.add_argument("--budget", "-b", type=str, default=settings.TRADE_BUDGET, help="Initial Capital (e.g. 200000-inr or 10-lots)")
    parser.add_argument("--sl-pct", "-l", type=float, default=settings.TRADE_STOP_LOSS_PCT, help="Stop Loss Percentage")
    parser.add_argument(
        "--target-pct", "-t", type=str, default=settings.TRADE_TARGET_PCT_STEPS, help="Comma separated target percentages"
    )
    parser.add_argument("--tsl-pct", "-L", type=float, default=settings.TRADE_TSL_PCT, help="Trailing Stop Loss Percentage (0 to disable)")
    parser.add_argument("--use-be", "-e", action="store_true", default=settings.TRADE_USE_BE, help="Enable Break-Even trailing on first target")
    parser.add_argument(
        "--instrument-type", type=str, choices=["CASH", "OPTIONS"], default=settings.TRADE_INSTRUMENT_TYPE, help="Instrument to trade"
    )
    parser.add_argument(
        "--strike-selection",
        "-S",
        type=str,
        choices=["ITM", "ATM", "OTM"],
        default=settings.TRADE_STRIKE_SELECTION,
        help="Option Strike selection",
    )
    parser.add_argument(
        "--invest-mode", "-i", type=str, choices=["compound", "fixed"], default=settings.TRADE_INVEST_MODE
    )
    # Hybrid Strategy & Pyramiding
    parser.add_argument(
        "--pyramid-steps",
        type=str,
        default=settings.TRADE_PYRAMID_STEPS,
        help="Comma-separated entry percentages (e.g., 25,50,25 or 100 for all-in)",
    )
    parser.add_argument(
        "--pyramid-confirm-pts",
        type=float,
        default=settings.TRADE_PYRAMID_CONFIRM_PTS,
        help="Points price must move in our favor before next pyramid step",
    )
    parser.add_argument(
        "--price-source",
        "-p",
        type=str,
        choices=["open", "close"],
        default=settings.TRADE_PRICE_SOURCE,
        help="Price source for backtest entry/exit (open or close)",
    )
    parser.add_argument(
        "--tsl-id",
        "-T",
        type=str,
        default=settings.TRADE_TSL_ID,
        help="Indicator ID for Trailing Stop Loss (e.g. trade-ema-5)",
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False, help="Enable verbose heartbeats, warmup notices, and low history warnings"
    )
    return parser


def setup_fund_manager(args, rule_config):
    pos_config = {
        "symbol": "NIFTY",
        "quantity": 1,  # Default placeholder, will be recalculated by FundManager
        "sl_pct": args.sl_pct,
        "target_pct": args.target_pct,
        "tsl_pct": args.tsl_pct,
        "tsl_id": args.tsl_id,
        "use_be": args.use_be,
        "instrument_type": args.instrument_type,
        "strike_selection": args.strike_selection,
        "invest_mode": args.invest_mode,
        "budget": args.budget,
        "python_strategy_path": rule_config.get("python_strategy_path"),
        # Pyramiding
        "pyramid_steps": args.pyramid_steps,
        "pyramid_confirm_pts": args.pyramid_confirm_pts,
        "price_source": args.price_source,
    }

    logger.info(f"Initializing FundManager with Strategy: {args.strategy_id} and Position Config: {pos_config}")
    fm = FundManager(strategy_config=rule_config, position_config=pos_config, is_backtest=True)
    return fm


def main():
    parser = get_parser()
    args = parser.parse_args()

    if args.end is None:
        args.end = args.start

    rule_config = TradeConfigService.fetch_strategy_config(args.strategy_id)

    strategy_path = rule_config.get("python_strategy_path") or rule_config.get("pythonStrategyPath")
    if not strategy_path:
        logger.error(f"Strategy {args.strategy_id} has no pythonStrategyPath configured in DB.")
        sys.exit(1)

    pos_config = {
        "symbol": "NIFTY",
        "quantity": 1,
        "sl_pct": args.sl_pct,
        "target_pct": args.target_pct,
        "tsl_pct": args.tsl_pct,
        "tsl_id": args.tsl_id,
        "use_be": args.use_be,
        "instrument_type": args.instrument_type,
        "strike_selection": args.strike_selection,
        "invest_mode": args.invest_mode,
        "budget": args.budget,
        "python_strategy_path": strategy_path,
        "pyramid_steps": args.pyramid_steps,
        "pyramid_confirm_pts": args.pyramid_confirm_pts,
        "price_source": args.price_source,
    }

    from packages.services.backtest_engine import BacktestEngine

    engine = BacktestEngine(
        strategy_config=rule_config,
        position_config=pos_config,
        start_date=args.start,
        end_date=args.end,
        mode=args.mode,
        reduced_log=not args.verbose,
    )

    try:
        engine.run()
    except KeyboardInterrupt:
        logger.info("Backtest Interrupted.")
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        import traceback

        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
