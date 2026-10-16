class AuditRepositoryError(RuntimeError):
    pass


class InvalidIdentifierError(AuditRepositoryError):
    pass


class UndoEngineUnavailable(AuditRepositoryError):
    pass


class UndoRejected(AuditRepositoryError):
    pass
