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


class _SuffixMap(dict):
    """Dict whose lookups also match when the key and a stored key share a
    suffix. The remittance file uses full unit numbers (e.g. ``249690``) while
    the Settings → Locations table stores short codes (e.g. ``9690``)."""

    def _resolve(self, key):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        key = str(key)
        for stored in self:
            s = str(stored)
            if s and (key.endswith(s) or s.endswith(key)):
                return dict.__getitem__(self, stored)
        return None

    def get(self, key, default=None):
        value = self._resolve(key)
        return default if value is None else value

    def __contains__(self, key):
        return self._resolve(key) is not None


def _remittance_mapping_from_settings(mod: ModuleType):
    """Build (locations, banks, coa_rules) from the Settings tables, falling
    back to the legacy script defaults for any category left unconfigured."""
    from webapp.database import SessionLocal
    from webapp.models import ChartOfAccountRule, Location

    locations = _SuffixMap()
    banks = _SuffixMap()
    coa_rules: list[tuple] = []

    db = SessionLocal()
    try:
        for loc in db.query(Location).filter_by(is_active=True).all():
            code = (loc.code or "").strip()
            if not code:
                continue
            locations[code] = (loc.name or code).strip()
            bank = (loc.bank_account or "").strip()
            if bank:
                banks[code] = bank
        coa_rules = [
            (
                rule.source_contains,
                rule.account,
                rule.output_description or rule.source_contains,
                rule.entry_type,
            )
            for rule in db.query(ChartOfAccountRule)
            .filter_by(tool_scope="remittance")
            .all()
        ]
    finally:
        db.close()

    if not locations:
        locations = _SuffixMap(mod.LOCATIONS)
    if not banks:
        banks = _SuffixMap(mod.BANK_ACCOUNTS)
    if not coa_rules:
        coa_rules = list(mod.DEFAULT_COA_RULES)
    return locations, banks, coa_rules


def run_daily_remittance(
    input_path: Path,
    output_path: Optional[Path] = None,
    mapping_path: Optional[Path] = None,
) -> ConversionResult:
    mod = _load_module("daily_remittance", "Daily Remittance/Daily_Remittance_Converter_CSV_FIXED.py")
    out = output_path or (OUTPUT_DIR / f"{input_path.stem}_QuickBooks_Journal.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        # An uploaded mapping workbook still takes precedence; otherwise the
        # mapping is driven by the editable Settings → Locations / COA tables.
        if mapping_path:
            locations, banks, coa_rules = mod.load_mapping(str(mapping_path))
        else:
            locations, banks, coa_rules = _remittance_mapping_from_settings(mod)

        groups = mod.read_remittance(str(input_path))
        rows, warnings = mod.build_journal(groups, locations, banks, coa_rules)
        mod.write_csv(rows, str(out))

        debits = sum(float(row[3] or 0) for row in rows)
        credits = sum(float(row[4] or 0) for row in rows)
        if abs(debits - credits) > 0.01:
            warnings.append(
                f"Journal is not balanced: debits {debits:.2f}, credits {credits:.2f}."
            )
        units, row_count = len(groups), len(rows)

        disc = abs(float(debits) - float(credits))
        msg = f"Units={units} rows={row_count} debits={debits:.2f} credits={credits:.2f}"
        if warnings:
            msg += " | " + "; ".join(warnings[:5])
        return ConversionResult(True, str(out), msg, units, row_count, disc)
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
