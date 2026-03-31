from typing import Protocol, runtime_checkable

from packages.tradeflow.types import SignalType


@runtime_checkable
class BaseStrategy(Protocol):
    """
    Protocol defining the contract for all Strategy implementations.
    Python-based strategies (loaded via PythonStrategy) must implement this interface.
    """

    def evaluate(self, indicators: dict[str, float]) -> tuple[SignalType, str, float]:
        """
        Evaluates the current market state and returns a trading signal.

        Args:
            indicators (Dict): Dictionary of indicator values from IndicatorCalculator.

        Returns:
            tuple[SignalType, str, float]:
                - SignalType: LONG, SHORT, or NEUTRAL.
                - str: Reason string (e.g., "CROSSOVER", "ML_PREDICTION").
                - float: Confidence score between 0.0 and 1.0.
        """
        ...
