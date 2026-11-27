"""Order conflicts: deliveries that failed or were rejected, queued for an operator.

An order lands here when the ERP rejects it or a delivery attempt fails transiently. The
operator assigns it, then resolves it: accept the ERP's version, accept the reseller's, or
dismiss it. The rows are plain CRUD, not event-sourced: this is operator workflow state.
"""
