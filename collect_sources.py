"""
intuixion.ai — SA RAG Data Source Collector
Downloads all public SA regulatory documents listed in the RAG Data Sources Guide.
Usage:
    pip install requests beautifulsoup4 lxml tqdm python-dotenv playwright
    playwright install chromium
    python collect_sources.py [--sector all|healthcare|financial|retail|cross] [--output ./data]

scrape_mode per source entry:
    static       — BeautifulSoup on static HTML (default)
    headless     — Playwright Chromium for JS-rendered pages
    content_type — Follow all links; HEAD-check Content-Type for hidden PDFs
    manual       — Cannot be automated (auth wall / Excel-only); skipped with instructions
"""

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from tqdm import tqdm

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

load_dotenv()

# ---------------------------------------------------------------------------
# Source catalogue
# Each entry:
#   slug        — safe filename prefix (matches naming convention in the guide)
#   name        — human label
#   sector      — healthcare | financial | retail | cross
#   index_url   — landing page to scrape for PDF links (used when pdf_url is None)
#   pdf_url     — direct PDF link if known; None = scrape index_url
#   notes       — ingestion hints from the guide
# ---------------------------------------------------------------------------
SOURCES = [
    # ── CROSS-SECTOR (Tier 1 — always ingest first) ──────────────────────
    {
        "slug": "popia_act_2013",
        "name": "Protection of Personal Information Act (POPIA) — Act 4 of 2013",
        "sector": "cross",
        "index_url": "https://www.gov.za/documents/protection-personal-information-act",
        "pdf_url": None,
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Best opening demo question for any audience",
    },
    {
        "slug": "companies_act_71_2008",
        "name": "Companies Act 71 of 2008 + Regulations",
        "sector": "cross",
        "index_url": "https://www.gov.za/documents/companies-act",
        "pdf_url": None,
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Company secretaries, legal teams, CFOs",
    },
    {
        "slug": "bcea_basic_conditions_employment",
        "name": "Basic Conditions of Employment Act (BCEA) + Sectoral Determinations",
        "sector": "cross",
        "index_url": "https://www.gov.za/documents/basic-conditions-employment-act",
        "pdf_url": None,
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Every HR team in SA searches this",
    },
    {
        "slug": "lra_labour_relations_act_1995",
        "name": "Labour Relations Act 66 of 1995",
        "sector": "cross",
        "index_url": "https://www.gov.za/documents/labour-relations-act",
        "pdf_url": None,
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Dismissal procedures, disciplinary processes",
    },
    {
        "slug": "cpa_consumer_protection_act_2008",
        "name": "Consumer Protection Act 68 of 2008",
        "sector": "cross",
        "index_url": "https://www.gov.za/documents/consumer-protection-act",
        "pdf_url": None,
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Every B2C company deals with refunds, liability, product issues",
    },
    # SARS tax guides — multiple PDFs; collector grabs all from the index
    {
        "slug": "sars_tax_guides",
        "name": "SARS Tax Guides — Income Tax / VAT / Employees Tax",
        "sector": "cross",
        "index_url": "https://www.sars.gov.za/legal-counsel/legal-counsel-publications/find-a-guide/",
        "pdf_url": None,
        "pdf_urls": [
            "https://www.sars.gov.za/wp-content/uploads/Ops/Guides/Legal-Pub-Guide-IT01-Guide-on-Income-Tax-and-the-Individual.pdf",
            "https://www.sars.gov.za/wp-content/uploads/Ops/Guides/Legal-Pub-Guide-VAT404-VAT-404-Guide-for-Vendors.pdf",
            "https://www.sars.gov.za/wp-content/uploads/Ops/Guides/PAYE-GEN-01-G18-Guide-for-Employers-iro-Employees-Tax-for-2024-External-Guide.pdf",
            "https://www.sars.gov.za/wp-content/uploads/Ops/Guides/Legal-Pub-Guide-Gen01-Taxation-in-South-Africa.pdf",
            "https://www.sars.gov.za/wp-content/uploads/Ops/Guides/Legal-Pub-Guide-Gen09-Tax-Guide-for-Small-Businesses.pdf",
        ],
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Re-ingest when SARS updates — check Last Updated date",
    },

    # ── HEALTHCARE & MEDICAL AID ──────────────────────────────────────────
    {
        "slug": "medical_schemes_act_131_1998",
        "name": "Medical Schemes Act 131 of 1998 + Amendments",
        "sector": "healthcare",
        "index_url": "https://www.gov.za/documents/medical-schemes-act",
        "pdf_url": None,
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Foundational legislation for medical aids",
    },
    {
        "slug": "cms_pmb_schedule",
        "name": "Prescribed Minimum Benefits (PMB) Schedule — Full List",
        "sector": "healthcare",
        "index_url": "https://www.medicalschemes.co.za/prescribed-minimum-benefits/",
        "pdf_url": None,
        "scrape_mode": "manual",
        "manual_instructions": "Download Excel file from https://www.medicalschemes.co.za/prescribed-minimum-benefits/ — convert to CSV, one row per chunk",
        "chunk_size": None,   # one PMB entry per chunk
        "chunk_overlap": None,
        "unstructured_mode": "table",
        "notes": "Use Excel when available; convert to CSV; one row = one chunk",
    },
    {
        "slug": "cms_circulars",
        "name": "Council for Medical Schemes (CMS) Circulars & Rulings",
        "sector": "healthcare",
        "index_url": "https://www.medicalschemes.co.za/publications/",
        "pdf_url": None,
        "pdf_urls": [
            "https://www.medicalschemes.co.za/download/3819/2026-circulars-current/31043/circular-13-of-2026.pdf",
            "https://www.medicalschemes.co.za/download/3819/2026-circulars-current/30971/circular-9-of-2026-financial-annual-statutory-returns-for-2025.pdf",
            "https://www.medicalschemes.co.za/download/3770/2025-circulars-current/30291/circular-32-of-2025.pdf",
            "https://www.medicalschemes.co.za/download/3728/2024-circulars-current/29432/circular-49-of-2024",
            "https://www.medicalschemes.co.za/download/3728/2024-circulars-current/29003/circular-35-of-2024_guidance-on-contribution-increases-and-benefits-changes-for-2025",
            "https://www.medicalschemes.co.za/download/3728/2024-circulars-current/28764/circular20of2024",
            "https://www.medicalschemes.co.za/download/3728/2024-circulars-current/28537/circular13-of-2024",
        ],
        "max_files": 10,
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "Download latest 10; rename cms_circular_{number}_{year}.pdf",
    },
    {
        "slug": "national_health_act_61_2003",
        "name": "National Health Act 61 of 2003",
        "sector": "healthcare",
        "index_url": "https://www.gov.za/documents/national-health-act",
        "pdf_url": None,
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Patient rights, consent, inspection protocols",
    },
    {
        "slug": "hpcsa_guidelines",
        "name": "HPCSA Health Professions Council SA Guidelines",
        "sector": "healthcare",
        "index_url": "https://www.hpcsa.co.za/Uploads/Professional_Practice/",
        "pdf_url": None,
        "scrape_mode": "manual",
        "manual_instructions": "Requires authenticated access — download booklets manually from https://www.hpcsa.co.za/Uploads/Professional_Practice/",
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "Multiple booklets; tag metadata: professional_type",
    },
    {
        "slug": "sanc_regulations",
        "name": "South African Nursing Council (SANC) Regulations",
        "sector": "healthcare",
        "index_url": "https://www.sanc.co.za/regulations-index/",
        "pdf_url": None,
        "scrape_mode": "manual",
        "manual_instructions": (
            "SANC blocks all automated access (Cloudflare). "
            "Download manually from these confirmed URLs and place in data/healthcare/: "
            "https://www.sanc.co.za/wp-content/uploads/2023/03/Regulations-Scope-of-Practice-Nurse-and-Midwife.pdf | "
            "https://www.sanc.co.za/wp-content/uploads/2020/06/Nursing-Act-2005.pdf | "
            "https://www.sanc.co.za/wp-content/uploads/2020/08/revised-r425.pdf | "
            "https://www.sanc.co.za/wp-content/uploads/2020/08/Nursing-Education-and-Training-Standards.pdf"
        ),
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "Scope of practice, registration, disciplinary procedures",
    },
    {
        "slug": "eml_essential_medicines_list",
        "name": "Essential Medicines List (EML) — National DoH",
        "sector": "healthcare",
        "index_url": "https://www.health.gov.za/nhi-edp-stgs-eml/",
        "pdf_url": None,
        "scrape_mode": "content_type",
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "Also available as Excel; highly structured",
    },
    {
        "slug": "stg_standard_treatment_guidelines",
        "name": "Standard Treatment Guidelines (STGs) — National DoH",
        "sector": "healthcare",
        "index_url": "https://www.health.gov.za/nhi-edp-stgs-eml/",
        "pdf_url": None,
        "scrape_mode": "content_type",
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "Add condition and level_of_care as metadata per chunk",
    },
    {
        "slug": "sama_ethical_guidelines",
        "name": "SAMA SA Medical Association Ethical Guidelines",
        "sector": "healthcare",
        "index_url": "https://samedical.org/samarec/",
        "pdf_url": None,
        "scrape_mode": "content_type",
        "chunk_size": 256,
        "chunk_overlap": 50,
        "unstructured_mode": "by_title",
        "notes": "Tight chunking — very precise ethical questions",
    },
    {
        "slug": "icd10_coding_guidelines_sa",
        "name": "ICD-10 Coding Guidelines — SA Edition (DoH)",
        "sector": "healthcare",
        "index_url": "https://www.health.gov.za/icd-10-master-industry-table/",
        "pdf_url": None,
        "scrape_mode": "content_type",
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "Also available as Excel; medical coders and billing teams",
    },
    {
        "slug": "discovery_annual_report",
        "name": "Discovery Health Medical Scheme Annual Report (Public)",
        "sector": "healthcare",
        "index_url": "https://www.discovery.co.za/medical-aid/annual-reports-and-financials",
        "pdf_url": "https://www.discovery.co.za/assets/discoverycoza/corporate/investor-relations/2025/dhms-ir-2024.pdf",
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Tier 3 prospect-specific; ingest executive summary sections only",
    },

    # ── FINANCIAL SERVICES ────────────────────────────────────────────────
    {
        "slug": "nca_national_credit_act_2005",
        "name": "National Credit Act 34 of 2005 (NCA) + Regulations",
        "sector": "financial",
        "index_url": "https://www.gov.za/documents/national-credit-act",
        "pdf_url": None,
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Affordability, reckless lending, credit agreement requirements",
    },
    {
        "slug": "fica_financial_intelligence_centre_act",
        "name": "Financial Intelligence Centre Act (FICA) — Full Text + Guidance",
        "sector": "financial",
        "index_url": "https://www.gov.za/documents/financial-intelligence-centre-act",
        "pdf_url": None,
        "scrape_mode": "static",
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "AML compliance; download Act + guidance notes",
    },
    {
        "slug": "sarb_prudential_standards",
        "name": "SARB SA Reserve Bank Prudential Standards",
        "sector": "financial",
        "index_url": "https://www.resbank.co.za/en/home/publications/prudential-authority",
        "pdf_url": None,
        "pdf_urls": [
            "https://www.resbank.co.za/content/dam/sarb/publications/prudential-authority/pa-deposit-takers/banks-directives/2025/d1-of-2025/D1%20-%202025%20-%20Directive%20returns%20to%20be%20submitted%20to%20the%20PA.pdf",
            "https://www.resbank.co.za/content/dam/sarb/publications/prudential-authority/pa-deposit-takers/banks-directives/2025/d2-of-2025/D2-2025%20Matters%20related%20to%20the%20Capital%20treatment%20of%20significant%20investments%20in%20Insurance%20entities.pdf",
            "https://www.resbank.co.za/content/dam/sarb/publications/prudential-authority/pa-deposit-takers/banks-directives/2025/D3-2025%20-%20Matters%20relating%20to%20Leverage%20Buffer%20requirements.pdf",
            "https://www.resbank.co.za/content/dam/sarb/publications/prudential-authority/pa-deposit-takers/banks-directives/2025/D5-2025%20-Directive%20replacing%20D1%20of%202025%20returns%20to%20be%20submitted%20to%20the%20PA.pdf",
            "https://www.resbank.co.za/content/dam/sarb/publications/prudential-authority/pa-deposit-takers/banks-directives/2025/d10-2025/D10-2025%20-%20Directive%20on%20Pillar%203%20disclosure%20requirements.pdf",
            "https://www.resbank.co.za/content/dam/sarb/publications/prudential-authority/pa-deposit-takers/banks-directives/2025/d11/D11-2025%20-%20Prudential%20treatment%20of%20distressed%20restructured%20credit%20exposures.pdf",
            "https://www.resbank.co.za/content/dam/sarb/publications/prudential-authority/pa-deposit-takers/banks-directives/2024/d2-of-2024/D2%20-%202024%20-%20Directive_Reporting%20requirements%20in%20terms%20of%20regulation%2046.pdf",
            "https://www.resbank.co.za/content/dam/sarb/what-we-do/prudential-regulation/pa-regulatory-strategy/PA%20Regulatory%20Strategy%202025-2030.pdf",
        ],
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "BA returns, directives; formal regulatory language",
    },
    {
        "slug": "fsca_regulations",
        "name": "Financial Sector Conduct Authority (FSCA) Regulations",
        "sector": "financial",
        "index_url": "https://www.fsca.co.za/Regulated-Entities/Pages/Legislation.aspx",
        "pdf_url": None,
        "scrape_mode": "headless",
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "TCF, FAIS, insurance regulations",
    },
    {
        "slug": "jse_listings_requirements",
        "name": "JSE Listings Requirements",
        "sector": "financial",
        "index_url": "https://www.jse.co.za/regulation/companies-issuer-regulation",
        "pdf_url": None,
        "pdf_urls": [
            "https://www.jse.co.za/sites/default/files/media/documents/jse-listings-requirements-service-issue-1-third-edition-march-2026/JSE%20Listings%20Requirements%20Service%20Issue%201%20%28Third%20Edition%29%20March%202026_2.pdf",
            "https://www.jse.co.za/sites/default/files/media/documents/jse-listings-requirements-simplified/JSE_Listings_Requirements_Simplified_Final_%40_12_December_2025_Final.pdf",
        ],
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Company secretaries at JSE-listed companies",
    },
    {
        "slug": "king_iv_corporate_governance",
        "name": "King IV Report on Corporate Governance",
        "sector": "financial",
        "index_url": "https://www.iodsa.co.za/page/KingIV",
        "pdf_url": None,
        "scrape_mode": "manual",
        "manual_instructions": "Requires free registration at IoDSA (iodsa.co.za) — download after login and place in data/financial/",
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Free on registration at IoDSA; attribution required",
    },
    {
        "slug": "fsra_financial_sector_regulation_act",
        "name": "Twin Peaks Legislation — FSRA (Financial Sector Regulation Act)",
        "sector": "financial",
        "index_url": "https://www.gov.za/documents/financial-sector-regulation-act-9-2017-english-sepedi-22-aug-2017-0000",
        "pdf_url": None,
        "scrape_mode": "static",
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Restructured SA financial regulation; frequently searched",
    },
    {
        "slug": "pension_funds_act",
        "name": "Pension Funds Act + PFA Circulars",
        "sector": "financial",
        "index_url": "https://www.gov.za/documents/pension-funds-act-22-may-2015-1349",
        "pdf_url": None,
        "scrape_mode": "static",
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "Pension fund administrators and trustees",
    },
    {
        "slug": "saia_guidelines",
        "name": "South African Insurance Association (SAIA) Guidelines",
        "sector": "financial",
        "index_url": "https://saia.co.za/about-us/code-of-conduct/",
        "pdf_url": None,
        "scrape_mode": "content_type",
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "Short-term insurance compliance and underwriting",
    },

    # ── RETAIL & GENERAL ENTERPRISE ───────────────────────────────────────
    {
        "slug": "employment_equity_act",
        "name": "Employment Equity Act + Employment Equity Reports",
        "sector": "retail",
        "index_url": "https://www.gov.za/documents/employment-equity-act",
        "pdf_url": None,
        "chunk_size": 1024,
        "chunk_overlap": 200,
        "unstructured_mode": "by_title",
        "notes": "Mandatory for designated employers (50+ employees)",
    },
    {
        "slug": "bbbee_codes_good_practice",
        "name": "B-BBEE Codes of Good Practice + Sector Charters",
        "sector": "retail",
        "index_url": "https://www.thedtic.gov.za/economic-empowerment/b-bbee/codes-of-good-practice/",
        "pdf_url": None,
        "scrape_mode": "headless",
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "Structured scoring tables; transformation teams and procurement",
    },
    {
        "slug": "ncr_guidelines",
        "name": "National Credit Regulator (NCR) Guidelines",
        "sector": "retail",
        "index_url": "https://www.ncr.org.za/index.php/publications/guidelines",
        "pdf_url": None,
        "scrape_mode": "content_type",
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "Retailers offering credit — affordability, disclosures",
    },
    {
        "slug": "retail_wage_determinations",
        "name": "Sector-Specific Retail Wage Determinations",
        "sector": "retail",
        "index_url": "https://www.labour.gov.za/DocumentCenter/Pages/Sectoral.aspx",
        "pdf_url": None,
        "pdf_urls": [
            "https://www.labour.gov.za/DocumentCenter/Publications/Basic%20Conditions%20of%20Employment/What%20wholesale%20and%20retail%20empoyees%20and%20their%20employers%20should%20know%20about%20minimum%20wage%20and%20conditions%20of%20employment.pdf",
            "https://www.labour.gov.za/DocumentCenter/Acts/Basic%20Conditions%20of%20Employment/-%20ES-%20What%20Hospitality%20Workers%20and%20their%20Employers%20should%20know%20about%20minimum%20wages%20and%20basic%20conditions%20of%20employment.pdf",
            "https://www.labour.gov.za/DocumentCenter/Publications/Basic%20Conditions%20of%20Employment/The%20National%20Minimum%20Wage%20in%20the%20Agriculture%20and%20Domestic%20Work%20Sectors.pdf",
            "https://www.labour.gov.za/DocumentCenter/Sectoral%20determinations/National%20Minimum%20Wage/National%20Minimum%20Wage%20Act.pdf",
            "https://www.labour.gov.za/DocumentCenter/Regulations%20and%20Notices/Regulations/Basic%20Conditions%20of%20Employment/National%20Minimum%20Wages%20Wage%20increase%201%20March%202024.pdf",
        ],
        "chunk_size": 512,
        "chunk_overlap": 100,
        "unstructured_mode": "by_title",
        "notes": "Minimum wages by sector; HR / payroll teams",
    },
]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": os.getenv(
        "COLLECTOR_USER_AGENT",
        "Mozilla/5.0 (compatible; intuixion-collector/1.0; +https://intuixion.ai)",
    )
}
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
RATE_LIMIT_SECONDS = float(os.getenv("RATE_LIMIT_SECONDS", "1.5"))  # polite delay between requests
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BACKOFF = float(os.getenv("RETRY_BACKOFF", "2.0"))
MIN_FILE_BYTES = 1024  # files smaller than this are treated as error pages


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _get_with_retry(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """GET with exponential backoff on transient errors (429, 5xx, connection errors)."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                print(f"  [RETRY] HTTP {resp.status_code} on attempt {attempt}/{MAX_RETRIES} — waiting {wait:.1f}s")
                time.sleep(wait)
                continue
            return resp
        except requests.ConnectionError as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                print(f"  [RETRY] Connection error on attempt {attempt}/{MAX_RETRIES} — waiting {wait:.1f}s")
                time.sleep(wait)
    if last_exc:
        raise last_exc
    return resp  # unreachable; satisfies type checkers


def scrape_pdf_links_headless(url: str) -> list[str]:
    """Use Playwright Chromium to scrape PDF links from JS-rendered pages."""
    if not PLAYWRIGHT_AVAILABLE:
        print("  [WARN] playwright not installed — run: pip install playwright && playwright install chromium")
        return []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000, wait_until="networkidle")
            links: list[str] = page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]'))
                       .map(a => a.href)
                       .filter(h => /\\.pdf($|\\?)/i.test(h))"""
            )
            browser.close()
        return list(dict.fromkeys(links))
    except Exception as exc:
        print(f"  [WARN] Headless scrape failed for {url}: {exc}")
        return []


def scrape_pdf_links_content_type(session: requests.Session, url: str) -> list[str]:
    """Follow every link on a page; HEAD-check Content-Type to find unlabelled PDFs."""
    try:
        resp = _get_with_retry(session, url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  [WARN] Could not fetch {url}: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    candidates = [
        urljoin(url, tag["href"])
        for tag in soup.find_all("a", href=True)
        if not tag["href"].startswith(("mailto:", "tel:", "#"))
    ]

    pdf_links = []
    for href in dict.fromkeys(candidates):
        if re.search(r"\.pdf($|\?)", href.lower()):
            pdf_links.append(href)
            continue
        try:
            head = session.head(href, timeout=10, allow_redirects=True)
            if "pdf" in head.headers.get("content-type", "").lower():
                pdf_links.append(href)
        except requests.RequestException:
            pass
        time.sleep(0.5)

    return list(dict.fromkeys(pdf_links))


def scrape_pdf_links(session: requests.Session, url: str) -> list[str]:
    """Return all absolute PDF hrefs found on a page."""
    try:
        resp = _get_with_retry(session, url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  [WARN] Could not fetch {url}: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    links = []
    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        if re.search(r"\.pdf($|\?)", href.lower()):
            links.append(urljoin(url, href))
    return list(dict.fromkeys(links))   # deduplicate, preserve order


def download_file(
    session: requests.Session,
    url: str,
    dest_path: Path,
    show_progress: bool = True,
) -> str | None:
    """Stream-download a file to dest_path.

    Returns the SHA-256 hex digest on success, or None on failure.
    Uses a .tmp staging file so a failed download never leaves a corrupt dest_path.
    """
    try:
        resp = _get_with_retry(session, url, stream=True, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  [ERROR] Download failed {url}: {exc}")
        return None

    content_type = resp.headers.get("content-type", "")
    if "pdf" not in content_type.lower() and not re.search(r"\.pdf($|\?)", url.lower()):
        print(f"  [WARN] Unexpected Content-Type '{content_type}' for {url} — skipping")
        return None

    total = int(resp.headers.get("content-length", 0))
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(".tmp")
    hasher = hashlib.sha256()

    try:
        with open(tmp_path, "wb") as fh:
            if show_progress and total:
                with tqdm(
                    total=total,
                    unit="B",
                    unit_scale=True,
                    desc=dest_path.name,
                    leave=False,
                ) as bar:
                    for chunk in resp.iter_content(chunk_size=8192):
                        fh.write(chunk)
                        hasher.update(chunk)
                        bar.update(len(chunk))
            else:
                for chunk in resp.iter_content(chunk_size=8192):
                    fh.write(chunk)
                    hasher.update(chunk)

        if tmp_path.stat().st_size < MIN_FILE_BYTES:
            print(f"  [WARN] File too small ({tmp_path.stat().st_size} B) — likely an error page, discarding")
            tmp_path.unlink()
            return None

        tmp_path.rename(dest_path)
        return hasher.hexdigest()

    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        print(f"  [ERROR] Write failed for {dest_path.name}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Core collector
# ---------------------------------------------------------------------------
def collect_source(
    session: requests.Session,
    source: dict,
    output_dir: Path,
    dry_run: bool = False,
) -> dict:
    """
    Download documents for one source entry.
    Returns a result dict with status and downloaded file paths.
    """
    sector_dir = output_dir / source["sector"]
    sector_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "slug": source["slug"],
        "name": source["name"],
        "sector": source["sector"],
        "files": [],
        "sha256": {},
        "errors": [],
    }

    # Build list of PDF URLs to download
    scrape_mode = source.get("scrape_mode", "static")

    if scrape_mode == "manual":
        msg = (
            f"Manual download required — {source.get('manual_instructions', 'visit ' + source['index_url'])}"
        )
        print(f"  [MANUAL] {msg}")
        result["errors"].append(msg)
        return result

    if source.get("pdf_urls"):
        pdf_urls = source["pdf_urls"]
        time.sleep(RATE_LIMIT_SECONDS)
    elif source["pdf_url"]:
        pdf_urls = [source["pdf_url"]]
        time.sleep(RATE_LIMIT_SECONDS)
    else:
        index = source["index_url"]
        print(f"  Scraping index ({scrape_mode}): {index}")

        if scrape_mode == "headless":
            pdf_urls = scrape_pdf_links_headless(index)
        elif scrape_mode == "content_type":
            pdf_urls = scrape_pdf_links_content_type(session, index)
        else:
            pdf_urls = scrape_pdf_links(session, index)

        time.sleep(RATE_LIMIT_SECONDS)

        if not pdf_urls:
            msg = f"No PDFs found at {index} — manual download required"
            print(f"  [SKIP] {msg}")
            result["errors"].append(msg)
            return result

        print(f"  Found {len(pdf_urls)} PDF link(s)")

    # For sources that may have many PDFs (e.g. SARS guides, CMS circulars)
    # cap at a sensible default to avoid grabbing entire archives
    max_files = source.get("max_files", 20)
    pdf_urls = pdf_urls[:max_files]

    for i, url in enumerate(pdf_urls, 1):
        # Build a clean filename
        url_path = urlparse(url).path
        raw_name = Path(url_path).name or f"doc_{i}.pdf"
        # Sanitise
        safe_name = re.sub(r"[^\w\-.]", "_", raw_name)
        if not safe_name.lower().endswith(".pdf"):
            safe_name += ".pdf"

        # Prefix with slug for uniqueness
        dest_name = f"{source['slug']}__{safe_name}"
        dest_path = sector_dir / dest_name

        if dest_path.exists() and dest_path.stat().st_size >= MIN_FILE_BYTES:
            print(f"  [SKIP] Already exists: {dest_name}")
            result["files"].append(str(dest_path))
            continue

        if dry_run:
            print(f"  [DRY-RUN] Would download: {url} -> {dest_name}")
            result["files"].append(str(dest_path))
            continue

        print(f"  Downloading ({i}/{len(pdf_urls)}): {dest_name}")
        sha = download_file(session, url, dest_path)
        if sha is not None:
            result["files"].append(str(dest_path))
            result["sha256"][dest_name] = sha
        else:
            result["errors"].append(url)

        time.sleep(RATE_LIMIT_SECONDS)

    return result


# ---------------------------------------------------------------------------
# Manifest writer
# ---------------------------------------------------------------------------
def write_manifest(results: list[dict], output_dir: Path) -> None:
    """
    Write a JSON manifest of all collected files + ingestion metadata.
    When run with --sector, merges into the existing manifest rather than
    overwriting it — preserving entries from other sectors.
    """
    manifest_path = output_dir / "manifest.json"

    # Load existing manifest (keyed by slug) to preserve other-sector entries
    existing: dict[str, dict] = {}
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as fh:
            for entry in json.load(fh):
                existing[entry["slug"]] = entry

    # Merge ingestion hints from SOURCES into results
    slug_map = {s["slug"]: s for s in SOURCES}
    for r in results:
        meta = slug_map.get(r["slug"], {})
        existing[r["slug"]] = {
            **r,
            "chunk_size": meta.get("chunk_size"),
            "chunk_overlap": meta.get("chunk_overlap"),
            "unstructured_mode": meta.get("unstructured_mode"),
            "ingestion_notes": meta.get("notes"),
            "index_url": meta.get("index_url"),
            "sha256": r.get("sha256", {}),
        }

    # Write back in SOURCES order so manifest order is stable
    source_order = [s["slug"] for s in SOURCES]
    ordered = [existing[slug] for slug in source_order if slug in existing]
    # Append any slugs not in SOURCES (shouldn't happen, but be safe)
    ordered += [v for k, v in existing.items() if k not in source_order]

    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(ordered, fh, indent=2, ensure_ascii=False)

    print(f"\nManifest written to {manifest_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Collect SA regulatory PDFs for intuixion.ai RAG corpus"
    )
    p.add_argument(
        "--sector",
        choices=["all", "healthcare", "financial", "retail", "cross"],
        default=os.getenv("COLLECTOR_SECTOR", "all"),
        help="Which sector(s) to download (default: all)",
    )
    p.add_argument(
        "--output",
        default=os.getenv("COLLECTOR_OUTPUT_DIR", "./data"),
        help="Root output directory (default: ./data)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be downloaded without writing files",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List all sources and exit",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output)

    if args.list:
        print(f"\n{'Slug':<45} {'Sector':<12} Name")
        print("-" * 100)
        for s in SOURCES:
            print(f"{s['slug']:<45} {s['sector']:<12} {s['name']}")
        return

    # Filter by sector
    sources = (
        SOURCES
        if args.sector == "all"
        else [s for s in SOURCES if s["sector"] == args.sector]
    )

    print(
        f"\nintuixion.ai Source Collector"
        f"\n  Sector filter : {args.sector}"
        f"\n  Sources       : {len(sources)}"
        f"\n  Output dir    : {output_dir}"
        f"\n  Dry run       : {args.dry_run}"
        f"\n"
    )

    session = _session()
    results = []

    try:
        for source in sources:
            print(f"\n[{source['sector'].upper()}] {source['name']}")
            result = collect_source(session, source, output_dir, dry_run=args.dry_run)
            results.append(result)

            ok = len(result["files"])
            err = len(result["errors"])
            print(f"  -> {ok} file(s) downloaded, {err} error(s)")
    finally:
        session.close()

    if not args.dry_run:
        write_manifest(results, output_dir)

    # Summary
    total_files = sum(len(r["files"]) for r in results)
    total_errors = sum(len(r["errors"]) for r in results)
    print(
        f"\n{'='*60}"
        f"\nDone. {total_files} file(s) collected, {total_errors} error(s)."
        f"\nNext step: run your ingestion pipeline against {output_dir}"
        f"\n{'='*60}\n"
    )


if __name__ == "__main__":
    main()
