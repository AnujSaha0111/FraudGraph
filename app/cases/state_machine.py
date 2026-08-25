# Centralized case state machine
# Single source of truth for legal status transitions. Routers only translate violations into 409 Conflict — no transition logic may live elsewhere.

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "NEW": {"INVESTIGATING", "ESCALATED"},
    "INVESTIGATING": {"ESCALATED", "CONFIRMED_FRAUD", "FALSE_POSITIVE"},
    "ESCALATED": {"INVESTIGATING", "CONFIRMED_FRAUD", "FALSE_POSITIVE"},
    "CONFIRMED_FRAUD": {"CLOSED"},
    "FALSE_POSITIVE": {"CLOSED"},
    "CLOSED": set(),
}

TERMINAL_STATES = {"CONFIRMED_FRAUD", "FALSE_POSITIVE", "CLOSED"}
DECISION_STATES = {"CONFIRMED_FRAUD", "FALSE_POSITIVE"}
VALID_STATUSES = set(ALLOWED_TRANSITIONS)


def can_transition(current: str, nxt: str) -> bool:
    return nxt in ALLOWED_TRANSITIONS.get(current, set())


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATES
