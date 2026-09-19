# Cycle terminal time correction

The final terminal timestamp fallback now covers CANCELLED, REJECTED, FAILED, BLOCKED and COMPLETED when the canonical work records provide actual completion time. Missing historical timestamps remain null. This closes the remaining two independent C timestamp findings without altering source evidence.
