"""Minimal stand-in for qgis.PyQt.QtNetwork (Bridge 1.8 revue D-TLS-1) :
QSslCertificate.fromData decoupe les blocs PEM comme Qt ; un certificat
est identifie par son PEM normalise (pas de verification X.509)."""
import re

_PEM_RE = re.compile(rb"-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----", re.DOTALL)


class QSslCertificate:
    def __init__(self, pem=b""):
        self._pem = bytes(pem)

    @staticmethod
    def fromData(data, *_args):
        certs = []
        for match in _PEM_RE.finditer(bytes(data)):
            body = b"".join(match.group(1).split())
            certs.append(QSslCertificate(b"-----BEGIN CERTIFICATE-----\n" + body + b"\n-----END CERTIFICATE-----\n"))
        return certs

    def isNull(self):
        return not self._pem

    def toPem(self):
        return self._pem

    def __eq__(self, other):
        return isinstance(other, QSslCertificate) and other._pem == self._pem

    def __hash__(self):
        return hash(self._pem)
