"""Country-code fixes applied only to generated Excel files."""

EXCEL_CODE_MAP = {"SIN": "SGP", "LIB": "LBN"}


def excel_code(code):
    """SIN -> SGP, LIB -> LBN (case-insensitive); anything else unchanged."""
    if not code:
        return code
    return EXCEL_CODE_MAP.get(str(code).strip().upper(), code)
