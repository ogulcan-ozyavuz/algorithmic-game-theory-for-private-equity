"""Open Cap Format (OCF) v1.2.0 adapter: read a package into a CapTable, write one back.

OCF standardises cap-table data and defines no computation over it. This adapter maps the
payout-relevant subset and refuses what it cannot represent; ``docs/ocf.md`` is the
field-by-field account of what is honoured, refused and ignored, and why.
"""

from ovf.ocf.notes import OcfNoteTerms, note_terms_from
from ovf.ocf.reader import (
    APPLIED_TRANSACTIONS,
    IGNORED_TRANSACTIONS,
    REFUSED_TRANSACTIONS,
    OcfImport,
    from_ocf,
    import_ocf,
    load_ocf_package,
)
from ovf.ocf.schema import (
    OCF_SCHEMA_COMMIT,
    OCF_VERSION,
    Issuer,
    OcfError,
    OcfIntegrityError,
    OcfPackage,
    OcfSchemaError,
    OcfUnsupportedError,
    ParticipationCapBasis,
    Stakeholder,
)
from ovf.ocf.writer import to_ocf, write_ocf_package

__all__ = [
    "APPLIED_TRANSACTIONS",
    "IGNORED_TRANSACTIONS",
    "OCF_SCHEMA_COMMIT",
    "OCF_VERSION",
    "REFUSED_TRANSACTIONS",
    "Issuer",
    "OcfError",
    "OcfImport",
    "OcfIntegrityError",
    "OcfNoteTerms",
    "OcfPackage",
    "OcfSchemaError",
    "OcfUnsupportedError",
    "ParticipationCapBasis",
    "Stakeholder",
    "from_ocf",
    "import_ocf",
    "load_ocf_package",
    "note_terms_from",
    "to_ocf",
    "write_ocf_package",
]
