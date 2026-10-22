class QAction:
    def __init__(self, *_args, **_kwargs):
        pass


class QDialog:
    class DialogCode:
        Accepted = 1
        Rejected = 0

    Accepted = DialogCode.Accepted
    Rejected = DialogCode.Rejected


class QInputDialog:
    pass


class QMenu:
    def __init__(self, *_args, **_kwargs):
        pass


class QMessageBox:
    @staticmethod
    def critical(*_args, **_kwargs):
        pass

    @staticmethod
    def warning(*_args, **_kwargs):
        pass


class QToolButton:
    def __init__(self, *_args, **_kwargs):
        pass
