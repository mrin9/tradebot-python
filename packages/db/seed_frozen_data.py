import os
import sys
from datetime import datetime, timedelta

sys.path.append(os.getcwd())
from packages.settings import settings
from packages.utils.mongo import MongoRepository

DB_NAME = "tradebot_frozen"
# In seed mode, we must ensure DB_NAME is set so properties produce the correct suffixes
settings.DB_NAME = DB_NAME

NIFTY_COL = settings.NIFTY_CANDLE_COLLECTION
OPT_COL = settings.OPTIONS_CANDLE_COLLECTION
RULE_COL = settings.STRATEGY_INDICATORS_COLLECTION
INST_COL = settings.INSTRUMENT_MASTER_COLLECTION


def clear_db(db):
    print("Clearing collections...")
    db[NIFTY_COL].delete_many({})
    db[OPT_COL].delete_many({})
    db[RULE_COL].delete_many({})
    db[INST_COL].delete_many({})


def generate_instruments(db):
    print("Seeding instrument_master...")
    instruments = []
    # Spot
    instruments.append(
        {
            "exchangeSegment": "NSECM",
            "exchangeInstrumentID": 26000,
            "name": "NIFTY 50",
            "description": "NIFTY 50",
            "instrumentTypeNum": 1,
        }
    )

    # Options (Strikes from 20000 to 28000, 50 intervals)
    expiry = "2026-02-12T00:00:00"
    base_id = 50000
    for strike in range(20000, 28000, 50):
        # CE
        instruments.append(
            {
                "exchangeSegment": "NSEFO",
                "exchangeInstrumentID": base_id,
                "name": "NIFTY",
                "series": "OPTIDX",
                "contractExpiration": expiry,
                "strikePrice": strike,
                "optionType": 3,  # CE
                "description": f"NIFTY {strike} CE",
                "lotSize": 50,
            }
        )
        base_id += 1
        # PE
        instruments.append(
            {
                "exchangeSegment": "NSEFO",
                "exchangeInstrumentID": base_id,
                "name": "NIFTY",
                "series": "OPTIDX",
                "contractExpiration": expiry,
                "strikePrice": strike,
                "optionType": 4,  # PE
                "description": f"NIFTY {strike} PE",
                "lotSize": 50,
            }
        )
        base_id += 1

    db[INST_COL].insert_many(instruments)
    print(f"Inserted {len(instruments)} instruments to {INST_COL}")

    # Return mapping for data generation
    # CE mapping: strike -> id, PE mapping: strike -> id
    ce_map = {inst["strikePrice"]: inst["exchangeInstrumentID"] for inst in instruments if inst.get("optionType") == 3}
    pe_map = {inst["strikePrice"]: inst["exchangeInstrumentID"] for inst in instruments if inst.get("optionType") == 4}
    return ce_map, pe_map


def make_candle(inst_id, t_epoch, open_, high, low, close, volume=1000):
    return {"i": inst_id, "t": t_epoch, "o": open_, "h": high, "l": low, "c": close, "v": volume}




def generate_day_data(db, start_dt, day_type, ce_map, pe_map, start_nifty_price=22000.0):
    print(f"Generating data for {start_dt.date()} (Type: {day_type})...")
    nifty_candles = []
    opt_candles = []

    timestamp = int(start_dt.timestamp())
    nifty_price = start_nifty_price

    # Derive initial ATM strike
    atm_strike = round(nifty_price / 50) * 50
    ce_map[atm_strike]
    pe_map[atm_strike]

    ce_price = 100.0
    pe_price = 100.0

    for minutes in range(375):  # 09:15 to 15:30
        current_ts = timestamp + (minutes * 60)

        # Determine price movement based on day_type
        if day_type == "UP_TREND_PERFECT":
            # Spot goes up smoothly
            n_open, n_close = nifty_price, nifty_price + 2.0
            nifty_price = n_close
            # CE goes up (confirms)
            ce_open, ce_close = ce_price, ce_price + 1.0
            ce_price = ce_close
            # PE goes down (confirms)
            pe_open, pe_close = pe_price, pe_price - 0.5
            pe_price = max(1.0, pe_close)


        elif day_type == "DOWN_TREND_PERFECT":
            n_open, n_close = nifty_price, nifty_price - 2.0
            nifty_price = n_close
            ce_open, ce_close = ce_price, ce_price - 0.5
            ce_price = max(1.0, ce_close)
            pe_open, pe_close = pe_price, pe_price + 1.0
            pe_price = pe_close


        elif day_type == "PARTIAL_ALIGNMENT":
            # Active (CE) looks great, Spot flat/down, PE flat
            n_open, n_close = nifty_price, nifty_price - 0.1
            nifty_price = n_close
            ce_open, ce_close = ce_price, ce_price + 1.5  # Fake breakout on option
            ce_price = ce_close
            pe_open, pe_close = pe_price, pe_price - 0.1
            pe_price = max(1.0, pe_close)


        elif day_type == "STRIKE_ROLLING":
            # Huge jump in price (100 points over 2 hours)
            if minutes < 120:
                n_open, n_close = nifty_price, nifty_price + 1.0
                ce_open, ce_close = ce_price, ce_price + 0.2
                pe_open, pe_close = pe_price, pe_price - 0.1
            else:
                n_open, n_close = nifty_price, nifty_price + 3.0  # acceleration
                ce_open, ce_close = ce_price, ce_price + 1.5
                pe_open, pe_close = pe_price, pe_price - 0.5
            nifty_price = n_close
            ce_price = ce_close
            pe_price = max(1.0, pe_close)


        elif day_type == "CHOPPY":
            # Up and down
            change = 2.0 if (minutes // 10) % 2 == 0 else -2.0
            n_open, n_close = nifty_price, nifty_price + change
            nifty_price = n_close
            ce_open, ce_close = ce_price, ce_price + (change * 0.5)
            ce_price = max(1.0, ce_close)
            pe_open, pe_close = pe_price, pe_price - (change * 0.5)
            pe_price = max(1.0, pe_close)


        else:
            n_open, n_close = nifty_price, nifty_price
            ce_open, ce_close = ce_price, ce_price
            pe_open, pe_close = pe_price, pe_price


        # Update ATM tracking logic for generating data on the active strike
        new_atm_strike = round(nifty_price / 50) * 50
        ce_map[new_atm_strike]
        pe_map[new_atm_strike]

        # Nifty Candle
        nifty_candles.append(make_candle(26000, current_ts, n_open, max(n_open, n_close) + 1, min(n_open, n_close) - 1, n_close))


        # CE Candle (generate for the currently active ATM strike specifically to ensure data exists for that strike)
        # We also generate data for the previous strike if it diverged, but for simplicity, we provide valid options data for all generated strikes close to ATM
        # Seed strikes within +/- 15 of initial ATM
        for offset in range(-15, 16):
            strike = int(atm_strike + (offset * 50))
            if strike in ce_map:
                offset_factor = (strike - new_atm_strike) / 50.0  # Just arbitrary pricing difference
                strike_ce_open = max(1.0, ce_open - offset_factor * 10)
                strike_ce_close = max(1.0, ce_close - offset_factor * 10)
                opt_candles.append(
                    make_candle(
                        ce_map[strike],
                        current_ts,
                        strike_ce_open,
                        max(strike_ce_open, strike_ce_close) + 0.5,
                        min(strike_ce_open, strike_ce_close) - 0.5,
                        strike_ce_close,
                    )
                )


            if strike in pe_map:
                offset_factor = (new_atm_strike - strike) / 50.0
                strike_pe_open = max(1.0, pe_open - offset_factor * 10)
                strike_pe_close = max(1.0, pe_close - offset_factor * 10)
                opt_candles.append(
                    make_candle(
                        pe_map[strike],
                        current_ts,
                        strike_pe_open,
                        max(strike_pe_open, strike_pe_close) + 0.5,
                        min(strike_pe_open, strike_pe_close) - 0.5,
                        strike_pe_close,
                    )
                )


    if nifty_candles:
        db[NIFTY_COL].insert_many(nifty_candles)
    if opt_candles:
        db[OPT_COL].insert_many(opt_candles)

    return nifty_price  # return ending price for next day


def generate_rules(db):
    print("Seeding strategy indicators for tests...")
    rules = [
        # 1. Triple Confirmation (180s)
        {
            "strategyId": "ema-5x21+rsi-180s-triple",
            "name": "EMA 5x21 + RSI Triple Lock",
            "enabled": True,
            "timeframe_seconds": 180,
            "pythonStrategyPath": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
            "indicators": [
                {"indicator": "ema-5", "InstrumentType": "SPOT"},
                {"indicator": "ema-21", "InstrumentType": "SPOT"},
                {"indicator": "rsi-14", "InstrumentType": "SPOT"},
                {"indicator": "ema-5", "InstrumentType": "OPTIONS_BOTH"},
                {"indicator": "ema-21", "InstrumentType": "OPTIONS_BOTH"},
                {"indicator": "rsi-14", "InstrumentType": "OPTIONS_BOTH"},
            ],
        },
        # 2. Supertrend + Price (300s)
        {
            "strategyId": "st-price-300s-active",
            "name": "Supertrend Price Active",
            "enabled": True,
            "timeframe_seconds": 300,
            "pythonStrategyPath": "packages/tradeflow/python_strategies.py:SuperTrendAndPriceCrossStrategy",
            "indicators": [{"indicator": "supertrend-10-3", "InstrumentType": "OPTIONS_BOTH"}],
        },
        # 3. EMA Cross + RSI (180s)
        {
            "strategyId": "ema-cross-rsi-180s",
            "name": "EMA Cross RSI Confirm",
            "enabled": True,
            "timeframe_seconds": 180,
            "pythonStrategyPath": "packages/tradeflow/python_strategies.py:EmaCrossWithRsiStrategy",
            "indicators": [
                {"indicator": "ema-5", "InstrumentType": "OPTIONS_BOTH"},
                {"indicator": "ema-21", "InstrumentType": "OPTIONS_BOTH"},
                {"indicator": "rsi-14", "InstrumentType": "OPTIONS_BOTH"},
            ],
        },
        # 4. Simple MACD (180s)
        {
            "strategyId": "macd-180s-dual",
            "name": "Simple MACD Dual",
            "enabled": True,
            "timeframe_seconds": 180,
            "pythonStrategyPath": "packages/tradeflow/python_strategies.py:SimpleMACDStrategy",
            "indicators": [{"indicatorId": "macd", "indicator": "macd-12-26-9", "InstrumentType": "OPTIONS_BOTH"}],
        },
    ]
    db[RULE_COL].insert_many(rules)


def generate_all():
    # Force settings into frozen mode
    settings.DB_NAME = DB_NAME
    db = MongoRepository.get_db()

    clear_db(db)
    generate_rules(db)
    ce_map, pe_map = generate_instruments(db)

    start_dt = datetime(2026, 2, 2, 9, 15)  # Monday

    # Day 1: Perfect Up Trend
    price = generate_day_data(db, start_dt, "UP_TREND_PERFECT", ce_map, pe_map, start_nifty_price=22000.0)

    # Day 2: Partial Alignment (False breakout option, Spot flat)
    start_dt += timedelta(days=1)
    price = generate_day_data(db, start_dt, "PARTIAL_ALIGNMENT", ce_map, pe_map, start_nifty_price=price)

    # Day 3: Strike Rolling (Huge trend up)
    start_dt += timedelta(days=1)
    price = generate_day_data(db, start_dt, "STRIKE_ROLLING", ce_map, pe_map, start_nifty_price=price)

    # Day 4: Perfect Down Trend
    start_dt += timedelta(days=1)
    price = generate_day_data(db, start_dt, "DOWN_TREND_PERFECT", ce_map, pe_map, start_nifty_price=price)

    # Day 5: Choppy
    start_dt += timedelta(days=1)
    price = generate_day_data(db, start_dt, "CHOPPY", ce_map, pe_map, start_nifty_price=price)

    print("Data Generation Complete!")


if __name__ == "__main__":
    generate_all()
