"""Bridge that loads legacy converter scripts via importlib (no edits to them)."""
from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

from webapp.config import LEGACY_ROOT, OUTPUT_DIR

_module_cache: dict[str, ModuleType] = {}


@dataclass
class ConversionResult:
    success: bool
    output_path: str = ""
    message: str = ""
    journals: int = 0
    lines: int = 0
    discrepancy: float = 0.0


def _load_module(key: str, relative_path: str) -> ModuleType:
    if key in _module_cache:
        return _module_cache[key]
    path = LEGACY_ROOT / relative_path
    if not path.exists():
        raise FileNotFoundError(f"Legacy script not found: {path}")
    spec = importlib.util.spec_from_file_location(f"legacy_{key}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Avoid tkinter mainloop side effects for modules that only define classes
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _module_cache[key] = module
    return module


def run_daily_sales(input_path: Path, output_path: Optional[Path] = None) -> ConversionResult:
    mod = _load_module("daily_sales", "Daily Sales/Dennys_Daily_Sales.py")
    out = output_path or (OUTPUT_DIR / f"{input_path.stem}_Journal_Output.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        journals, lines = mod.convert(str(input_path), str(out))
        return ConversionResult(True, str(out), f"Created {journals} journals / {lines} lines", journals, lines)
    except Exception as exc:
        return ConversionResult(False, message=str(exc))


def run_daily_remittance(
    input_path: Path,
    output_path: Optional[Path] = None,
    mapping_path: Optional[Path] = None,
) -> ConversionResult:
    mod = _load_module("daily_remittance", "Daily Remittance/Daily_Remittance_Converter_CSV_FIXED.py")
    out = output_path or (OUTPUT_DIR / f"{input_path.stem}_QuickBooks_Journal.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        units, rows, debits, credits, warnings = mod.convert_file(
            str(input_path),
            str(out),
            str(mapping_path) if mapping_path else None,
        )
        disc = abs(float(debits) - float(credits))
        msg = f"Units={units} rows={rows} debits={debits:.2f} credits={credits:.2f}"
        if warnings:
            msg += " | " + "; ".join(warnings[:5])
        return ConversionResult(True, str(out), msg, units, rows, disc)
    except Exception as exc:
        return ConversionResult(False, message=str(exc))


def run_payroll(input_path: Path, output_path: Optional[Path] = None) -> ConversionResult:
    mod = _load_module("payroll", "Payroll/Dennys_payroll_xformity.py")
    try:
        result = mod.convert(Path(input_path))
        # Legacy writes next to input; optionally copy/move
        out = Path(result)
        if output_path and out != output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(out.read_bytes())
            out = output_path
        return ConversionResult(True, str(out), f"Payroll journal created: {out.name}")
    except Exception as exc:
        return ConversionResult(False, message=str(exc))


def run_hotel_revenue(input_path: Path, output_path: Optional[Path] = None, location: str = "Marietta Hotel") -> ConversionResult:
    mod = _load_module("hotel_revenue", "Hotel Revenue/Marietta_hotel_revenue_daily.py")
    out = output_path or (OUTPUT_DIR / f"{input_path.stem}_QuickBooks.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        actual = mod.convert_with_locked_file_fallback(Path(input_path), Path(out), location)
        return ConversionResult(True, str(actual), f"Hotel revenue CSV: {Path(actual).name}")
    except Exception as exc:
        return ConversionResult(False, message=str(exc))


def run_sales_tax(input_path: Path, output_path: Optional[Path] = None) -> ConversionResult:
    mod = _load_module("sales_tax", "Sales Tax/daily_report_sales_tax_to_pdf.py")
    out = output_path or (OUTPUT_DIR / f"{input_path.stem}_Sales_Tax.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        vals = mod.make_pdf(Path(input_path), Path(out))
        msg = "Sales tax PDF created: " + ", ".join(f"${v:,.2f}" for v in vals)
        return ConversionResult(True, str(out), msg)
    except Exception as exc:
        return ConversionResult(False, message=str(exc))


def parse_invoice_pdf(pdf_path: Path) -> tuple[list[Any], dict[str, str]]:
    mod = _load_module("invoice", "Dennys Invoice/Dennys_weekly_invoice_DFO.py")
    return mod.parse_pdf(str(pdf_path))


def invoice_module() -> ModuleType:
    return _load_module("invoice", "Dennys Invoice/Dennys_weekly_invoice_DFO.py")


TOOLS = {
    "daily_sales": {
        "name": "Daily Sales",
        "work_type": "Daily Sales",
        "accept": ".csv,.xlsx,.xlsm",
        "runner": run_daily_sales,
    },
    "daily_remittance": {
        "name": "Daily Remittance",
        "work_type": "Daily Remittance",
        "accept": ".csv",
        "runner": run_daily_remittance,
    },
    "payroll": {
        "name": "Weekly Payroll",
        "work_type": "Weekly Payroll",
        "accept": ".csv",
        "runner": run_payroll,
    },
    "hotel_revenue": {
        "name": "Marietta Hotel Daily Revenue",
        "work_type": "Marietta Hotel Daily Revenue",
        "accept": ".pdf",
        "runner": run_hotel_revenue,
    },
    "sales_tax": {
        "name": "Sales Tax",
        "work_type": "Sales Tax",
        "accept": ".csv",
        "runner": run_sales_tax,
    },
    "invoice": {
        "name": "Weekly Denny's Invoice",
        "work_type": "Weekly Denny's Invoice",
        "accept": ".pdf",
        "runner": None,
    },
}


def safe_traceback(exc: BaseException) -> str:
    return "".join(traceback.format_exception_only(type(exc), exc)).strip()
