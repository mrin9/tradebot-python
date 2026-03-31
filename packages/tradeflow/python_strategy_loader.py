import importlib.util
import logging
import os

from packages.tradeflow.types import SignalType

logger = logging.getLogger(__name__)


class PythonStrategy:
    """
    A wrapper Strategy class that delegates execution to a dynamically loaded Python script.
    Delegates to a Python script for strategy logic.
    """

    def __init__(self, script_path: str):
        self.script_path = script_path
        self.custom_strategy = self._load_strategy(script_path)

    def _load_strategy(self, path_arg: str):
        """
        Dynamically loads the python file and returns an instance of the target class.
        Supports 'filepath:ClassName' syntax. Defaults to 'Strategy' if no colon is provided.
        """
        if ":" in path_arg:
            filepath, class_name = path_arg.split(":", 1)
        else:
            filepath = path_arg
            class_name = "Strategy"

        if not os.path.exists(filepath):
            logger.error(f"❌ Python Strategy File not found: {filepath}")
            raise FileNotFoundError(f"Python Strategy File not found: {filepath}")

        try:
            # Create a unique module name
            module_name = f"dynamic_strategy_{os.path.basename(filepath).split('.')[0]}"
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Extract the class and instantiate it
            target_class = getattr(module, class_name, None)
            if not target_class:
                logger.error(f"❌ Class '{class_name}' not found in {filepath}")
                raise AttributeError(f"Class '{class_name}' not found in {filepath}")

            strategy_instance = target_class()
            logger.info(f"🐍 Successfully loaded Python Strategy: {class_name} from {filepath}")
            return strategy_instance

        except Exception as e:
            logger.error(f"❌ Failed to load Python Strategy from {filepath}: {e}")
            raise

    def on_resampled_candle_closed(self, candle, indicators, current_position_intent=None):
        """
        Delegates the standard strategy interface call to the loaded custom python class.
        """
        if not self.custom_strategy:
            return SignalType.NEUTRAL, "PYTHON WRAPPER ERROR: Strategy not loaded", 0.0

        try:
            return self.custom_strategy.on_resampled_candle_closed(candle, indicators, current_position_intent)
        except Exception as e:
            logger.error(f"❌ Error during Python Strategy evaluation: {e}")
            return SignalType.NEUTRAL, f"PYTHON STRATEGY EXCEPTION: {e}", 0.0
