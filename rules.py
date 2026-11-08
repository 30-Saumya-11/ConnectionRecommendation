"""Medical RULES are rule-based on purpose.  ML only RANKS people who already pass these rules.
!! The numbers below are common defaults.  VERIFY them with official (NBTC/NACO or hospital) guidelines
!! before showing them as facts.  This is a prototype, not a medical device.
"""
from datetime import date

GROUPS = ("O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+")
MIN_GAP_DAYS = 90            # minimum days between two whole-blood donations
MIN_AGE, MAX_AGE = 18, 65
RBC_SHELF_LIFE_DAYS = 35     # red-cell units expire after about 35 days
PRIORITY_NAMES = {0: "EMERGENCY", 1: "URGENT", 2: "ROUTINE"}


def _split(group):
    return group[:-1], group[-1]          # 'AB+' -> ('AB', '+')


def can_donate_to(donor_group, recipient_group):
    """Red-cell compatibility (ABO + Rh)."""
    d_abo, d_rh = _split(donor_group)
    r_abo, r_rh = _split(recipient_group)
    abo_ok = d_abo == "O" or d_abo == r_abo or r_abo == "AB"
    rh_ok = d_rh == "-" or r_rh == "+"
    return abo_ok and rh_ok


def compatible_donor_groups(recipient_group):
    return [g for g in GROUPS if can_donate_to(g, recipient_group)]


def is_eligible(birth_year, last_donation, available, today, gap_days=MIN_GAP_DAYS):
    """Returns (True, '') or (False, reason).  last_donation = 'YYYY-MM-DD' or None."""
    if not available:
        return False, "not available"
    age = today.year - birth_year
    if age < MIN_AGE or age > MAX_AGE:
        return False, "age outside 18-65"
    if last_donation:
        y, m, d = map(int, last_donation.split("-"))
        if (today - date(y, m, d)).days < gap_days:
            return False, "donated too recently"
    return True, ""
