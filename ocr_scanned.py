"""
intuixion.ai — OCR Pipeline for Scanned PDFs

Processes image-only PDFs (confirmed zero-text) using Tesseract OCR via pytesseract.
Outputs plain-text files alongside the originals, ready for re-ingestion.

Install Tesseract on Windows:
    1. Download installer: https://github.com/UB-Mannheim/tesseract/wiki
    2. Install to default path: C:\\Program Files\\Tesseract-OCR\\tesseract.exe
    3. pip install pytesseract pillow pymupdf

Usage:
    python ocr_scanned.py                   # process all blocklisted scanned files
    python ocr_scanned.py --file data/healthcare/icd10_coding_guidelines_sa__icd-10circularno04of2014.pdf
    python ocr_scanned.py --dpi 300         # higher DPI = better quality, slower
    python ocr_scanned.py --lang eng+afr    # include Afrikaans (if language pack installed)
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Files confirmed as image-only scans (from quality analysis)
SCANNED_FILES = [
    "data/healthcare/icd10_coding_guidelines_sa__Notice_-additional-emergency-ICD10-codes_COVID-19.pdf",
    "data/healthcare/icd10_coding_guidelines_sa__icd-10dictionaryicircularno03of2014.pdf",
    "data/healthcare/icd10_coding_guidelines_sa__icd-10codescircularno06of2014.pdf",
    "data/healthcare/icd10_coding_guidelines_sa__icd-10circularno04of2014.pdf",
    "data/healthcare/icd10_coding_guidelines_sa__icd-10circularno05of2014.pdf",
    "data/healthcare/icd10_coding_guidelines_sa__NoticetoallStakeholdersErrataICD-10.pdf",
    "data/healthcare/icd10_coding_guidelines_sa__ICD-10-Circular-2-of-2014-Submission-of-Aggregated-ICD-10-Compliance-Data-2014.pdf",
    "data/healthcare/icd10_coding_guidelines_sa__ICD-10-Phase3and41.pdf",
    "data/financial/fsca_regulations__UB_20Manual.pdf",
]

PROJECT_ROOT = Path(__file__).parent
TESSERACT_PATH = os.getenv(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
)


def check_deps() -> bool:
    try:
        import pytesseract
        import fitz  # pymupdf
        from PIL import Image
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
        pytesseract.get_tesseract_version()
        return True
    except Exception as exc:
        print(f"[ERROR] Dependency check failed: {exc}")
        print()
        print("To install:")
        print("  1. Download Tesseract: https://github.com/UB-Mannheim/tesseract/wiki")
        print("  2. pip install pytesseract pillow pymupdf")
        print(f"  3. Set TESSERACT_CMD in .env if installed to a non-default path")
        return False


def ocr_pdf(pdf_path: Path, dpi: int = 200, lang: str = "eng") -> str:
    """
    Render each page of a PDF to an image and run Tesseract OCR on it.
    Returns the extracted text for all pages joined with page breaks.
    """
    import fitz
    import pytesseract
    from PIL import Image
    import io

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    doc = fitz.open(str(pdf_path))
    pages_text = []
    mat = fitz.Matrix(dpi / 72, dpi / 72)  # scale factor for target DPI

    for i, page in enumerate(doc, 1):
        pixmap = page.get_pixmap(matrix=mat)
        img_bytes = pixmap.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))
        text = pytesseract.image_to_string(img, lang=lang)
        if text.strip():
            pages_text.append(f"--- Page {i} ---\n{text.strip()}")

    doc.close()
    return "\n\n".join(pages_text)


def process_file(pdf_path: Path, dpi: int, lang: str, overwrite: bool) -> dict:
    txt_path = pdf_path.with_suffix(".ocr.txt")

    if txt_path.exists() and not overwrite:
        print(f"  [SKIP] OCR text already exists: {txt_path.name}")
        return {"status": "skip", "output": str(txt_path)}

    print(f"  [OCR]  {pdf_path.name} (dpi={dpi}, lang={lang})")
    try:
        text = ocr_pdf(pdf_path, dpi=dpi, lang=lang)
    except Exception as exc:
        print(f"    [ERROR] {exc}")
        return {"status": "error", "error": str(exc)}

    if not text.strip():
        print("    [WARN] OCR produced no text — file may require higher DPI or different language pack")
        return {"status": "empty"}

    txt_path.write_text(text, encoding="utf-8")
    words = len(text.split())
    print(f"    -> {words:,} words extracted to {txt_path.name}")
    return {"status": "ok", "output": str(txt_path), "words": words}


def main() -> None:
    p = argparse.ArgumentParser(description="OCR pipeline for scanned SA regulatory PDFs")
    p.add_argument("--file", help="Process a single PDF file (overrides default list)")
    p.add_argument("--dpi", type=int, default=200,
                   help="Render DPI (higher = better quality, slower). Default: 200")
    p.add_argument("--lang", default="eng",
                   help="Tesseract language(s), e.g. 'eng+afr'. Default: eng")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-OCR even if .ocr.txt already exists")
    args = p.parse_args()

    if not check_deps():
        sys.exit(1)

    if args.file:
        targets = [Path(args.file)]
    else:
        targets = [PROJECT_ROOT / f for f in SCANNED_FILES]

    targets = [t for t in targets if t.exists()]
    if not targets:
        print("No target files found.")
        sys.exit(0)

    print(f"\nintuixion.ai OCR Pipeline")
    print(f"  Files : {len(targets)}")
    print(f"  DPI   : {args.dpi}")
    print(f"  Lang  : {args.lang}\n")

    results = {"ok": 0, "skip": 0, "empty": 0, "error": 0}
    for path in targets:
        r = process_file(path, dpi=args.dpi, lang=args.lang, overwrite=args.overwrite)
        results[r["status"]] = results.get(r["status"], 0) + 1

    print(f"\nDone. ok={results['ok']}  skip={results['skip']}  "
          f"empty={results['empty']}  error={results['error']}")
    print()
    print("Next step: re-run ingest.py to pick up the .ocr.txt files, or manually")
    print("review them and add to the data/ directory as .pdf-companion text files.")


if __name__ == "__main__":
    main()
