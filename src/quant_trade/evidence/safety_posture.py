"""The safety posture stamped onto opportunity and shadow artifacts.

This lived in ``cloud_rental/models.py``, which meant the board, the paper
allocation and the shadow portfolio all imported a constant out of the mining
package. Retiring mining would have broken the V8 paper-trading path at import
time for the sake of a five-key dictionary, so the constant moves somewhere
neutral first and the deletion becomes possible afterwards.

The keys are unchanged, in the same order, so the artifacts that embed this
dictionary are byte-identical across the move. Two of them
(``miner_execution``, ``hardware_control_enabled``) only mean anything while
mining exists; pruning them is a separate decision, because it changes artifact
bytes and therefore has to travel with a regeneration.

Every value is False and stays False. This is an assertion that nothing here
can spend money or start hardware, not a configuration switch.
"""

from __future__ import annotations

SAFETY_POSTURE: dict[str, bool] = {
    "aws_resources_created": False,
    "alibaba_resources_created": False,
    "external_spend_authorized": False,
    "miner_execution": False,
    "hardware_control_enabled": False,
}

__all__ = ["SAFETY_POSTURE"]
