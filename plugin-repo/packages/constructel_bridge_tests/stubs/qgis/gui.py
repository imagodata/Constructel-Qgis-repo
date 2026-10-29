class QgisInterface:
    pass


class QgsMessageBarItem:
    """Bridge 1.8 revue (I9) : bandeau persistant (duree 0). Test-double :
    garde titre, texte, niveau et duree pour les assertions."""

    def __init__(self, title="", text="", level=None, duration=0, parent=None):
        self.title = title
        self.text = text
        self.level = level
        self.duration = duration
