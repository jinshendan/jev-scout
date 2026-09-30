"""A bounded, read-only code investigation harness."""

from .investigator import investigate
from .models import ActionCandidate, DecisionState, InvestigationResult, Policy, RulePolicy

__all__ = [
    "ActionCandidate",
    "DecisionState",
    "InvestigationResult",
    "Policy",
    "RulePolicy",
    "investigate",
]
__version__ = "0.1.0"
