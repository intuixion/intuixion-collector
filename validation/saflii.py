"""
SAFLII NoteUp link-out (tech direction Phase 1).

When an answer cites a statute, include a link to that section's SAFLII page
alongside the citation so users can see which cases have cited that provision.

This is a signal, not a solution — the link goes to SAFLII's own NoteUp tooling
which maintains currency. We assert nothing about which cases matter.

URL pattern: https://www.saflii.org/za/legis/consol_act/{act_id}/index.html
NoteUp:      https://www.saflii.org/cgi-bin/noter-up.pl?path=/za/legis/consol_act/{act_id}

Slug → SAFLII act_id mapping. Extend as corpus grows.
Unknown slugs get None — don't link rather than link to a wrong page.
"""

# SAFLII consolidated legislation act IDs, verified per slug
_SLUG_TO_SAFLII: dict[str, str] = {
    "constitution_1996":                    "const1996",
    "popia_act_2013":                       "popia2013",
    "companies_act_71_2008":                "ca2008",
    "bcea_basic_conditions_employment":     "bcea1997",
    "lra_labour_relations_act_1995":        "lra1995",
    "cpa_consumer_protection_act_2008":     "cpa2008",
    "nca_national_credit_act_2005":         "nca2005",
    "fica_financial_intelligence_centre_act": "fica2001",
    "medical_schemes_act_131_1998":         "msa1998",
    "national_health_act_61_2003":          "nha2003",
    "employment_equity_act":                "eea1998",
    "fsra_financial_sector_regulation_act": "fsra2017",
    "pension_funds_act":                    "pfa1956",
}

SAFLII_LEGIS_BASE = "https://www.saflii.org/za/legis/consol_act"
SAFLII_NOTEUP_BASE = "https://www.saflii.org/cgi-bin/noter-up.pl?path=/za/legis/consol_act"


def saflii_url(slug: str) -> str | None:
    """
    Return the SAFLII consolidated-legislation URL for a given corpus slug, or None.

    The returned URL points to the Act's index page. Append '#secN' for section
    deep-links once section-level mapping is available.
    """
    act_id = _SLUG_TO_SAFLII.get(slug)
    if not act_id:
        return None
    return f"{SAFLII_LEGIS_BASE}/{act_id}"


def noteup_url(slug: str) -> str | None:
    """Return the SAFLII NoteUp URL (case-law citing this Act), or None."""
    act_id = _SLUG_TO_SAFLII.get(slug)
    if not act_id:
        return None
    return f"{SAFLII_NOTEUP_BASE}/{act_id}"
