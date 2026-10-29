class Qt:
    class AlignmentFlag:
        AlignCenter = 0x84
        AlignLeft = 0x1

    AlignCenter = AlignmentFlag.AlignCenter


class QLocale:
    pass


class QTimer:
    """singleShot enregistre le rappel ; les tests l'executent (run_pending)."""
    _pending = []

    @staticmethod
    def singleShot(_msec, callback):
        QTimer._pending.append(callback)

    @staticmethod
    def run_pending():
        pending, QTimer._pending = QTimer._pending, []
        for callback in pending:
            callback()
