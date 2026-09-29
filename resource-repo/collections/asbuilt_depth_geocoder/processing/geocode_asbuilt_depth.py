# -*- coding: utf-8 -*-
"""Géocoder rapport As-Built (.msg Outlook) par profondeur de pose.

Algorithme QGIS Processing autonome (partageable via *QGIS Resource Sharing*).
Il lit les rapports périodiques « To update Go Fiber As-Built » exportés aux
formats Outlook ``.msg`` **ou** tableur ``.xlsx`` / ``.csv`` (même tableau
WorkOrder / Intervention / Address / PostalCode / Place / profondeur), géocode
les adresses via Nominatim (OpenStreetMap) et produit une couche de points
EPSG:31370 colorée par profondeur de pose (feu tricolore + gris « manquante »).

Le fichier est volontairement mono-fichier (contrainte Resource Sharing : un
script Processing = un ``.py`` déposé tel quel). Toute la logique de parsing /
normalisation / dédoublonnage / construction de requête est factorisée dans des
fonctions PURES, sans dépendance PyQGIS, testables via pytest. La classe
``QgsProcessingAlgorithm`` n'est qu'un fin wrapper d'orchestration.

Dépendances runtime (auto-installées via pip au besoin) : ``extract-msg``
(lecture ``.msg``) et ``openpyxl`` (lecture ``.xlsx``). Les ``.csv`` n'utilisent
que la stdlib. Politique Nominatim : 1 req/s max + User-Agent identifiant ;
renseigner ``CONTACT_EMAIL`` est fortement recommandé.
"""

import csv
import glob
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional

# ---------------------------------------------------------------------------
# Imports PyQGIS — encapsulés pour que les fonctions pures ci-dessous restent
# importables (et testables via pytest) dans un Python standard sans QGIS.
# ---------------------------------------------------------------------------
try:
    from qgis.core import (
        QgsApplication,
        QgsCategorizedSymbolRenderer,
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsDataSourceUri,
        QgsExpression,
        QgsFeature,
        QgsFeatureRequest,
        QgsFeatureSink,
        QgsField,
        QgsFields,
        QgsGeometry,
        QgsPointXY,
        QgsProcessing,
        QgsProcessingAlgorithm,
        QgsProcessingContext,
        QgsProcessingException,
        QgsProcessingLayerPostProcessorInterface,
        QgsProcessingParameterBoolean,
        QgsProcessingParameterFeatureSink,
        QgsProcessingParameterFeatureSource,
        QgsProcessingParameterFile,
        QgsProcessingParameterFileDestination,
        QgsProcessingParameterString,
        QgsProcessingUtils,
        QgsProject,
        QgsProviderRegistry,
        QgsRendererCategory,
        QgsSymbol,
        QgsVectorLayer,
        QgsWkbTypes,
    )
    from qgis.PyQt.QtCore import QCoreApplication, QDateTime, QVariant
    from qgis.PyQt.QtGui import QColor

    HAS_QGIS = True
except ImportError:  # pragma: no cover - branche prise uniquement hors QGIS
    HAS_QGIS = False


# ===========================================================================
# Constantes
# ===========================================================================
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Identifiants logiques des colonnes du tableau de rapport.
COL_WORKORDER = "work_order"
COL_INTERVENTION = "intervention"
COL_ADDRESS = "address"
COL_POSTAL = "postal_code"
COL_PLACE = "place"
COL_DEPTH = "depth"

# Seuils de catégorisation de la profondeur (en cm) — FIXES, non paramétrables.
THRESHOLD_MISSING_CM = 10.0
THRESHOLD_ORANGE_CM = 50.0
THRESHOLD_VERT_CM = 55.0

# Palette « feu tricolore » + gris pour la catégorie « manquante ».
# SOURCE DE VÉRITÉ du rendu = le fichier ``style/depth_category.qml`` livré à côté
# du script (chargé via ``loadNamedStyle``, cf. _apply_depth_style). Cette palette
# ne sert plus QUE de FILET ULTIME (rendu Python construit par _build_depth_renderer)
# quand le .qml est absent/illisible — d'où une teinte pouvant légèrement différer
# du .qml sur ce chemin de repli.
DEPTH_COLORS = {
    "manquante": "#999999",
    "rouge": "#D7263D",
    "orange": "#F4A300",
    "vert": "#2A9D3D",
}

# Ordre d'affichage de la table de synthèse : du plus conforme au moins conforme,
# la catégorie « manquante » (non mesurée) en dernier.
DEPTH_SUMMARY_ORDER = ("vert", "orange", "rouge", "manquante")

# Libellés lisibles de chaque catégorie (bornés par les seuils fixes ci-dessus).
# Source UNIQUE des libellés : le rendu de repli (_build_depth_renderer) et la
# table de synthèse xlsx. Le .qml livré (style/depth_category.qml) porte
# directement ces mêmes libellés en dur — plus de réalignement à l'exécution.
DEPTH_CATEGORY_LABELS = {
    "manquante": "Manquante — non mesurée",
    "rouge": f"Rouge — non conforme (< {THRESHOLD_ORANGE_CM:g} cm)",
    "orange": f"Orange — limite ({THRESHOLD_ORANGE_CM:g}–{THRESHOLD_VERT_CM:g} cm)",
    "vert": f"Vert — conforme (≥ {THRESHOLD_VERT_CM:g} cm)",
}

# Repli défensif : clé de ventilation dans la table de synthèse par ville
# quand un point géocodé n'a pas de ville renseignée (place vide/absente en
# source, ou copiée sans valeur depuis une couche existante en mode additif).
UNKNOWN_PLACE_LABEL = "(ville inconnue)"

# Titres des feuilles de la table de synthèse xlsx. Le titre de la feuille pivot
# sert AUSSI d'identifiant de couche (``layername``) au chargement OGR côté QGIS :
# writer et loader DOIVENT référencer la même constante, sinon la couche table
# ne se charge pas.
SUMMARY_PIVOT_SHEET_TITLE = "Synthèse par ville"
SUMMARY_PCT_SHEET_TITLE = "Pourcentages"
SUMMARY_UNGEOCODED_SHEET_TITLE = "Adresses non géocodées"

# Un identifiant d'intervention est un code numérique (observé : 8 chiffres).
_INTERVENTION_RE = re.compile(r"^\d{5,}$")
# Code postal belge : 4 chiffres isolés.
_POSTAL_RE = re.compile(r"\b(\d{4})\b")


# ===========================================================================
# Modèle de données
# ===========================================================================
@dataclass
class InterventionRecord:
    """Une ligne du tableau de rapport (avant géocodage)."""

    work_order: str = ""
    intervention: str = ""
    address: str = ""
    postal_code: str = ""
    place: str = ""
    depth_raw: str = ""
    source_message: str = ""


@dataclass
class NominatimHit:
    """Résultat structuré d'un géocodage Nominatim réussi.

    ``postcode``/``city`` proviennent du détail d'adresse structuré Nominatim
    (``addressdetails=1``, cf. :func:`extract_nominatim_place`) — chaîne vide
    si Nominatim ne les a pas fournis pour ce résultat (repli sur les valeurs
    du rapport source côté appelant, cf. ``_build_feature``).
    """

    lat: float
    lon: float
    postcode: str = ""
    city: str = ""


class NominatimBlockedError(RuntimeError):
    """Levée quand Nominatim renvoie 403/429 (rate-limit / blocage)."""


# ===========================================================================
# Fonctions PURES — parsing / normalisation / dédoublonnage / requête
# (aucune dépendance PyQGIS ; couvertes par pytest)
# ===========================================================================
def _looks_like_intervention(value: str) -> bool:
    """True si ``value`` ressemble à un identifiant d'intervention numérique."""
    return bool(_INTERVENTION_RE.match((value or "").strip()))


def parse_depth_cm(raw: Optional[str]) -> Optional[float]:
    """Normalise une cellule de profondeur brute en centimètres.

    Règles (confirmées sur données réelles) :
      * cellule vide / non numérique -> ``None`` ;
      * la chaîne contient un séparateur décimal (``.`` ou ``,``)
        -> valeur exprimée en MÈTRES -> ×100 (ex ``"0.60"`` -> 60.0 cm) ;
      * sinon valeur déjà en centimètres (ex ``"70"`` -> 70.0 cm).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    is_decimal = ("." in s) or ("," in s)
    try:
        value = float(s.replace(",", "."))
    except ValueError:
        return None
    return value * 100.0 if is_decimal else value


def categorize_depth(depth_cm: Optional[float]) -> str:
    """Catégorise une profondeur (cm) en manquante/rouge/orange/vert (seuils fixes)."""
    if depth_cm is None or depth_cm < THRESHOLD_MISSING_CM:
        return "manquante"
    if depth_cm < THRESHOLD_ORANGE_CM:
        return "rouge"
    if depth_cm < THRESHOLD_VERT_CM:
        return "orange"
    return "vert"


def extract_postal4(text: Optional[str]) -> Optional[str]:
    """Extrait le premier code postal à 4 chiffres isolé, ou ``None``."""
    if not text:
        return None
    match = _POSTAL_RE.search(text)
    return match.group(1) if match else None


def normalize_place(raw: Optional[str]) -> str:
    """Normalise un nom de localité : espaces et casse homogènes.

    Rogne les bords, réduit les espaces multiples à un seul, puis applique
    une casse Title (``"BRUXELLES"`` / ``"bruxelles"`` -> ``"Bruxelles"`` ;
    gère aussi les noms composés/bilingues : ``"molenbeek-saint-jean"`` ->
    ``"Molenbeek-Saint-Jean"``, ``"IXELLES/ELSENE"`` -> ``"Ixelles/Elsene"``,
    ``str.title()`` capitalisant après tout caractère non alphabétique).
    Chaîne vide si ``raw`` est vide/``None``/uniquement des espaces. Fonction
    PURE — aucune dépendance PyQGIS, couverte par pytest.
    """
    if not raw:
        return ""
    collapsed = re.sub(r"\s+", " ", raw.strip())
    return collapsed.title()


_HOUSE_NUMBER_RE = re.compile(r"^(.*?)\s+\d+[a-zA-Z]?(?:[/\-]\S+)?\s*$")
# Code postal belge (4 chiffres) en fin d'adresse : « Rue de la Gare 12 1000 ».
_TRAILING_POSTAL_RE = re.compile(r"^(.*?)\s+\d{4}\s*$")
# Suffixe boîte en fin d'adresse : « bte 3 », « boîte 3A », « bte. B », « bus 3 »
# (nl). La valeur de boîte est restreinte (nombre+lettre optionnelle, ou lettre
# seule) pour ne jamais mordre sur un nom de rue contenant le mot « bus ».
_TRAILING_BOX_RE = re.compile(
    r"^(.*?)\s+(?:bte|bo[iî]te|bus)\.?\s*(?:\d+[a-zA-Z]?|[a-zA-Z])\s*$",
    re.IGNORECASE,
)
_SZETT_DOUBLE_S_RE = re.compile(r"ß[sS]")


def fix_szett_artifact(text: str) -> str:
    """Corrige l'artefact 'ßs'/'ßS' -> 'ß'.

    Le ß allemand (Eszett) vaut deja phonetiquement 'ss' ; un 's' immediatement
    apres est une duplication parasite observee en donnees reelles (export
    BeOn, adresses germanophones de la region), ex. « Malmedyer Straßse » au
    lieu de « Malmedyer Straße ». Ne touche PAS un 's' plus loin dans le mot
    (seulement collé au ß).
    """
    if not text:
        return text
    return _SZETT_DOUBLE_S_RE.sub("ß", text)


def extract_street_name(address_raw: Optional[str]) -> str:
    """Extrait le nom de rue d'une adresse brute belge (tronque le numero/boite final).

    Notation belge : ``"Rue de la Gare 12"`` / ``"Rue de la Gare 12/3"`` ->
    ``"Rue de la Gare"``. Pas de numero detecte en fin de chaine (deja sans
    numero, ou format non reconnu) -> la chaine est renvoyee telle quelle
    (repli permissif : le matching de nom cote SQL est normalise/insensible
    a la casse ; un residu de numero non tronque fera simplement echouer le
    matching plutot que de planter).

    Nettoyage, dans cet ordre (meme sequence que le chemin de geocodage :
    fix_szett_artifact, puis clean_duplicated_address) :

    1. fix_szett_artifact (l'artefact peut apparaitre n'importe ou dans le nom
       de rue ; applique AVANT la deduplication pour que des segments repetes
       ne different pas par ce seul artefact) ;
    2. clean_duplicated_address (bug d'export « Rue X/Rue X/Rue X 12 ») ;
    3. format a virgule (« Rue X, 12 », « Rue X 12, 1000 Bruxelles ») : seul le
       premier segment contenant une lettre est garde (« 12, Rue X » -> « Rue X ») ;
    4. en fin de chaine, dans l'ordre ou ils apparaissent a rebours : code
       postal a 4 chiffres, suffixe boite (« bte 3 », « boîte 3 », « bus 3 »),
       numero de maison ; puis ponctuation/espaces residuels.

    Chaque etape de l'etape 4 n'est tentee qu'UNE fois (pas de boucle jusqu'a
    point fixe) : un nom de rue se terminant lui-meme par un nombre n'est
    ainsi ampute que du seul numero de maison.
    """
    if not address_raw:
        return ""
    text = fix_szett_artifact(address_raw.strip())
    if not text:
        return ""
    text = clean_duplicated_address(text)
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        text = next((p for p in parts if re.search(r"[^\W\d_]", p)), "")
    for pattern in (_TRAILING_POSTAL_RE, _TRAILING_BOX_RE, _HOUSE_NUMBER_RE):
        match = pattern.match(text)
        if match and match.group(1).strip():
            text = match.group(1)
    return text.strip().rstrip(" ,;-/").strip()


def normalize_postal_code(raw: Optional[str]) -> str:
    """Normalise un code postal : les 4 chiffres isolés qu'il contient.

    Réutilise :func:`extract_postal4` (même détection que pour la
    construction de requête Nominatim). Si aucun code à 4 chiffres n'est
    trouvé (valeur atypique), replie DÉFENSIVEMENT sur la valeur brute
    rognée plutôt que de perdre l'information silencieusement. Fonction
    PURE — aucune dépendance PyQGIS, couverte par pytest.
    """
    postal4 = extract_postal4(raw)
    if postal4:
        return postal4
    return (raw or "").strip()


def format_postal_codes(codes) -> str:
    """Formate un ensemble de codes postaux normalisés pour affichage.

    Dédoublonne, trie, joint par ``", "`` (ex. une ville associée à plusieurs
    codes postaux dans le rapport source). Accepte tout itérable (``set``,
    ``list``...). Fonction PURE — aucune dépendance PyQGIS, couverte par pytest.
    """
    return ", ".join(sorted(set(codes)))


def build_geocode_query(
    address: str, postal_code: str, place: str, country: str = "Belgium"
) -> str:
    """Construit la requête Nominatim à partir des champs source.

    Les données sources sont incohérentes : le code postal apparaît souvent
    déjà dupliqué dans ``Address``. Si les 4 chiffres du code postal sont déjà
    présents dans l'adresse, on n'ajoute pas de suffixe redondant.
    """
    address = fix_szett_artifact(address)
    address = (address or "").strip()
    postal_code = (postal_code or "").strip()
    place = (place or "").strip()

    postal4 = extract_postal4(postal_code) or extract_postal4(address)
    if postal4 and postal4 in address:
        return f"{address}, {country}"

    tail = " ".join(part for part in (postal_code, place) if part).strip()
    if tail:
        return f"{address}, {tail}, {country}"
    return f"{address}, {country}"


def clean_duplicated_address(address: str) -> str:
    """Déduplique une adresse dont le nom de rue est répété via des « / ».

    Certains exports BeOn répètent le libellé de rue plusieurs fois, séparé par
    des « / » (bug de la source, PAS du script), ex :
    ``"Malmedyer Straße/Malmedyer Straße/Malmedyer Straße 203"``. Nominatim
    renvoie alors 0 résultat, alors que le seul dernier segment
    (``"Malmedyer Straße 203"``, celui qui porte le numéro) géocode correctement.

    Règle : si l'adresse contient au moins un « / », ne conserver que le DERNIER
    segment non vide (après ``strip``) — À CONDITION que ce schéma soit bien
    celui d'une RÉPÉTITION : tous les segments qui précèdent le dernier doivent
    être identiques entre eux, et le dernier doit commencer par ce même texte
    (c'est lui qui porte le numéro en plus). Sans cette vérification, le « / »
    de la notation belge numéro/boîte (ex. ``"Rue de la Gare 12/3"``, tout à
    fait légitime) serait confondu avec le bug source et réduirait l'adresse au
    seul numéro de boîte (``"3"``) — un géocodage alors FAUX mais silencieusement
    marqué réussi (repli qui « réussit » sur un point erroné). Si le schéma ne
    correspond pas à une répétition, l'adresse est renvoyée INCHANGÉE (aucun
    nettoyage tenté). Fonction PURE (couverte par pytest) : ne fait PAS d'appel
    réseau et n'altère pas le chemin nominal.
    """
    if not address or "/" not in address:
        return address
    non_empty = [seg.strip() for seg in address.split("/") if seg.strip()]
    if not non_empty:
        return address
    if len(non_empty) == 1:
        return non_empty[0]
    *prefix_segments, last = non_empty
    reference = prefix_segments[0]
    if not all(seg == reference for seg in prefix_segments):
        return address
    if not last.startswith(reference):
        return address
    return last


def dedupe_records(records: list[InterventionRecord]) -> list[InterventionRecord]:
    """Dédoublonnage intra-batch par identifiant d'intervention (clé unique).

    Couvre le cas réel « même intervention répétée 3× dans un message » ainsi
    que les doublons stricts. Les lignes sans identifiant d'intervention
    exploitable sont écartées (parasites).
    """
    seen: set[str] = set()
    out: list[InterventionRecord] = []
    for rec in records:
        key = (rec.intervention or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


# --- Parsing HTML ----------------------------------------------------------
def _classify_header_cell(norm: str) -> Optional[str]:
    """Associe un intitulé de colonne (normalisé) à un identifiant logique."""
    if "workorder" in norm:
        return COL_WORKORDER
    if "intervention" in norm:
        return COL_INTERVENTION
    if "postalcode" in norm or "postal" in norm:
        return COL_POSTAL
    if "place" in norm:
        return COL_PLACE
    if "depth" in norm or "profondeur" in norm:
        return COL_DEPTH
    if "address" in norm:
        return COL_ADDRESS
    return None


class _ReportTableParser(HTMLParser):
    """Collecte les ``<table>`` sous forme de listes de lignes de cellules.

    Gère l'imbrication de tables (Outlook enveloppe le contenu dans des tables
    de mise en page) via des piles indépendantes.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._tables: list[list[list[str]]] = []  # pile de tables en cours
        self._rows: list[list[str]] = []  # pile de lignes en cours
        self._cells: list[list[str]] = []  # pile de fragments de cellule
        self.tables: list[list[list[str]]] = []  # tables terminées

    def handle_starttag(self, tag, attrs):  # noqa: D401
        t = tag.lower()
        if t == "table":
            self._tables.append([])
        elif t == "tr":
            if self._tables:
                self._rows.append([])
        elif t in ("td", "th"):
            if self._rows:
                self._cells.append([])

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("td", "th"):
            if self._cells:
                fragments = self._cells.pop()
                text = " ".join("".join(fragments).split())
                if self._rows:
                    self._rows[-1].append(text)
        elif t == "tr":
            if self._rows:
                row = self._rows.pop()
                if self._tables:
                    self._tables[-1].append(row)
        elif t == "table":
            if self._tables:
                self.tables.append(self._tables.pop())

    def handle_data(self, data):
        if self._cells:
            self._cells[-1].append(data)


def _row_to_record(row: list[str], colmap: dict[str, int]) -> Optional[InterventionRecord]:
    def get(col: str) -> str:
        idx = colmap.get(col)
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    intervention = get(COL_INTERVENTION)
    if not _looks_like_intervention(intervention):
        return None
    return InterventionRecord(
        work_order=get(COL_WORKORDER),
        intervention=intervention,
        address=get(COL_ADDRESS),
        postal_code=get(COL_POSTAL),
        place=get(COL_PLACE),
        depth_raw=get(COL_DEPTH),
    )


def _extract_records_from_tables(
    tables: list[list[list[str]]],
) -> list[InterventionRecord]:
    for table in tables:
        colmap: Optional[dict[str, int]] = None
        header_idx = None
        for i, row in enumerate(table):
            mapping: dict[str, int] = {}
            for j, cell in enumerate(row):
                norm = re.sub(r"\s+", "", cell).lower()
                logical = _classify_header_cell(norm)
                if logical and logical not in mapping:
                    mapping[logical] = j
            if all(k in mapping for k in (COL_WORKORDER, COL_INTERVENTION, COL_ADDRESS, COL_DEPTH)):
                header_idx = i
                colmap = mapping
                break
        if header_idx is None or colmap is None:
            continue
        records: list[InterventionRecord] = []
        for row in table[header_idx + 1:]:
            rec = _row_to_record(row, colmap)
            if rec is not None:
                records.append(rec)
        if records:
            return records
    return []


def parse_html_report(html: Optional[str]) -> list[InterventionRecord]:
    """Extrait les interventions du corps HTML du rapport (``msg.htmlBody``)."""
    if not html:
        return []
    parser = _ReportTableParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # HTML pathologique -> on bascule sur le repli texte
        return []
    return _extract_records_from_tables(parser.tables)


# --- Parsing texte brut (repli) --------------------------------------------
def _split_blocks(lines: list[str], min_blank_sep: int = 2) -> list[list[str]]:
    """Découpe des lignes en blocs séparés par >= ``min_blank_sep`` lignes vides."""
    blocks: list[list[str]] = []
    current: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip() == "":
            blank_run += 1
            if blank_run >= min_blank_sep and current:
                blocks.append(current)
                current = []
            continue
        blank_run = 0
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _parse_text_format_a(lines: list[str], header_idx: int) -> list[InterventionRecord]:
    """Format A : une intervention par ligne, champs séparés par des tabulations."""
    records: list[InterventionRecord] = []
    for line in lines[header_idx + 1:]:
        if "\t" not in line:
            if line.strip() == "":
                continue
            break  # fin du bloc tableau (signature, etc.)
        cells = [c.strip() for c in line.split("\t")]
        while cells and cells[-1] == "":
            cells.pop()
        if len(cells) < 6:
            continue
        wo, interv, addr, postal, place, depth = cells[:6]
        if not _looks_like_intervention(interv):
            continue
        records.append(InterventionRecord(wo, interv, addr, postal, place, depth))
    return records


def _parse_text_format_b(lines: list[str]) -> list[InterventionRecord]:
    """Format B (message transféré) : un champ par ligne, blocs séparés."""
    blocks = _split_blocks(lines, min_blank_sep=2)
    header_i = None
    for bi, block in enumerate(blocks):
        joined = re.sub(r"\s+", "", " ".join(block)).lower()
        if (
            "workorder" in joined
            and "intervention" in joined
            and "address" in joined
            and "depth" in joined
        ):
            header_i = bi
            break
    if header_i is None:
        return []
    records: list[InterventionRecord] = []
    for block in blocks[header_i + 1:]:
        fields = [ln.strip() for ln in block if ln.strip() != ""]
        if len(fields) < 6:
            continue
        wo, interv, addr, postal, place, depth = fields[:6]
        if not _looks_like_intervention(interv):
            break  # bloc post-tableau (signature, footer) -> fin
        records.append(InterventionRecord(wo, interv, addr, postal, place, depth))
    return records


def parse_text_report(body: Optional[str]) -> list[InterventionRecord]:
    """Extrait les interventions du corps texte brut (``msg.body``).

    Gère les deux formats observés : A (tabulé, message direct) et B (un champ
    par ligne, message transféré « FW: »). La détection repose sur la présence
    d'une ligne d'en-tête tabulée.
    """
    if not body:
        return []
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, line in enumerate(lines):
        if "\t" not in line:
            continue
        norm = re.sub(r"\s+", "", line).lower()
        if (
            "workorder" in norm
            and "intervention" in norm
            and "address" in norm
            and "depth" in norm
        ):
            return _parse_text_format_a(lines, i)
    return _parse_text_format_b(lines)


def parse_report_content(
    html: Optional[str], body: Optional[str]
) -> list[InterventionRecord]:
    """Parse un rapport : priorité au HTML, repli sur le texte brut."""
    records = parse_html_report(html)
    if not records:
        records = parse_text_report(body)
    return records


# --- Lecteurs tabulaires (xlsx / xls / csv) --------------------------------
# Les rapports Go Fiber As-Built sont parfois fournis en export direct (Excel /
# CSV) plutôt qu'en pièce jointe ``.msg``. On ramène chaque format à la même
# « matrice de cellules » (``list[list[str]]``) puis on réutilise TELLE QUELLE
# la détection d'en-tête + extraction déjà écrite pour le HTML
# (``_extract_records_from_tables``) : aucune logique aval n'est dupliquée.
_SUPPORTED_EXTENSIONS = (".msg", ".xlsx", ".xls", ".csv")


def _collect_input_files(folder: str) -> list[str]:
    """Liste triée des fichiers d'entrée supportés d'un dossier (non récursif).

    Filtrage par extension INSENSIBLE À LA CASSE : ``.msg`` ``.xlsx`` ``.xls``
    ``.csv``. Non récursif (même dossier uniquement), pour rester prévisible.
    """
    paths: list[str] = []
    for entry in glob.glob(os.path.join(folder, "*")):
        if not os.path.isfile(entry):
            continue
        if os.path.splitext(entry)[1].lower() in _SUPPORTED_EXTENSIONS:
            paths.append(entry)
    return sorted(paths)


def _cell_to_str(value) -> str:
    """Convertit une cellule de tableur (openpyxl) en chaîne « comme saisie ».

    Enjeu : ``parse_depth_cm`` distingue cm (entier ``"70"``) et mètres
    (décimal ``"0.60"``) sur la présence d'un séparateur décimal. openpyxl rend
    des valeurs *typées* (``int`` / ``float``), pas le texte source :
      * un entier ``70`` -> ``"70"`` (reste des centimètres) ;
      * un flottant fractionnaire ``0.6`` -> ``"0.6"`` (reste des mètres) ;
      * un flottant entier ``70.0`` -> ``"70"`` (et NON ``"70.0"``, qui serait
        relu comme 70 m = 7000 cm) — une profondeur de tranchée exprimée en
        mètres n'a jamais de partie entière > 3.
    """
    if value is None:
        return ""
    if isinstance(value, bool):  # avant int : bool est une sous-classe de int
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value).strip()


def sniff_csv_delimiter(sample: str, default: str = ",") -> str:
    """Détecte le séparateur CSV (``,`` ``;`` ou tabulation) sur un échantillon.

    Excel exporte selon la locale : ``,`` (US/UK) ou ``;`` (FR/BE/DE). On tente
    ``csv.Sniffer`` puis, en repli, on compte les candidats sur la 1re ligne
    non vide (l'en-tête), avec ``default`` si aucun ne se détache.
    """
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        if dialect.delimiter in (";", ",", "\t"):
            return dialect.delimiter
    except csv.Error:
        pass
    first_line = next((ln for ln in sample.splitlines() if ln.strip()), "")
    counts = {sep: first_line.count(sep) for sep in (";", ",", "\t")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else default


def parse_csv_text(text: str) -> list[list[str]]:
    """Transforme le texte d'un CSV en matrice de cellules (BOM + séparateur).

    Gère le BOM UTF-8 (Excel) et détecte le séparateur via
    :func:`sniff_csv_delimiter`. Les cellules sont rognées (``strip``).
    """
    if not text:
        return []
    if text[0] == "\ufeff":  # BOM UTF-8 résiduel
        text = text[1:]
    delimiter = sniff_csv_delimiter(text[:4096])
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[(cell or "").strip() for cell in row] for row in reader]


def read_csv_rows(path: str) -> list[list[str]]:
    """Lit un fichier ``.csv`` -> matrice de cellules (stdlib, sans dépendance).

    Essaie plusieurs encodages (UTF-8 avec/sans BOM puis cp1252 / latin-1,
    fréquents sur les exports Excel FR/BE) avant un dernier repli tolérant.
    """
    with open(path, "rb") as handle:
        raw = handle.read()
    text: Optional[str] = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", "replace")
    return parse_csv_text(text)


def read_xlsx_rows(path: str, openpyxl_module=None) -> list[list[str]]:
    """Lit un classeur ``.xlsx`` (feuille active) -> matrice de cellules.

    Requiert ``openpyxl`` (injecté ou importé paresseusement). Ouvert en lecture
    seule + ``data_only`` (valeurs mises en cache plutôt que formules). Ne lit
    PAS les ``.xls`` binaires legacy : openpyxl lève alors une erreur, que
    l'appelant convertit en message « ré-exportez en .xlsx/.csv ».
    """
    if openpyxl_module is None:
        import openpyxl

        openpyxl_module = openpyxl
    workbook = openpyxl_module.load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        if worksheet is None:
            return []
        return [
            [_cell_to_str(value) for value in row]
            for row in worksheet.iter_rows(values_only=True)
        ]
    finally:
        workbook.close()


def parse_tabular_rows(rows: list[list[str]]) -> list[InterventionRecord]:
    """Extrait les interventions d'une matrice de cellules (csv / xlsx / xls).

    Réutilise :func:`_extract_records_from_tables` — donc EXACTEMENT la même
    détection d'en-tête souple (insensible à la casse, par intitulé et non par
    position) et la même validation de ligne que le chemin HTML.
    """
    if not rows:
        return []
    return _extract_records_from_tables([rows])


# --- Géocodage Nominatim (pur, stdlib urllib) ------------------------------
def build_user_agent(contact_email: Optional[str]) -> str:
    """User-Agent conforme à la politique d'usage Nominatim."""
    contact = (contact_email or "").strip() or "non-fourni"
    return f"QGIS-ASBuilt-Depth-Geocoder/1.0 (contact: {contact})"


# Priorité des champs d'adresse structurée Nominatim pour la « ville » : OSM
# tague différemment les communes rurales (``town``/``village``) et les
# grandes villes/quartiers urbains (``city``/``suburb`` — utile pour les
# communes de Bruxelles). Premier champ non vide qui gagne.
_NOMINATIM_CITY_KEYS = ("city", "town", "village", "municipality", "suburb")


def extract_nominatim_place(result) -> tuple[str, str]:
    """Extrait ``(postcode, ville)`` du détail d'adresse d'un résultat Nominatim.

    Nécessite une requête faite avec ``addressdetails=1`` (sous-objet
    ``"address"``). Ville = premier champ non vide parmi
    :data:`_NOMINATIM_CITY_KEYS`. Renvoie ``("", "")`` si absent/mal formé —
    ne lève jamais. Fonction PURE (aucun appel réseau, aucune dépendance
    PyQGIS) — couverte par pytest.
    """
    address = result.get("address") if isinstance(result, dict) else None
    if not isinstance(address, dict):
        return "", ""
    postcode = str(address.get("postcode") or "").strip()
    city = ""
    for key in _NOMINATIM_CITY_KEYS:
        value = address.get(key)
        if value:
            city = str(value).strip()
            break
    return postcode, city


def nominatim_geocode(
    query: str,
    user_agent: str,
    timeout: float = 15.0,
    base_url: str = NOMINATIM_URL,
) -> Optional[NominatimHit]:
    """Géocode une requête -> :class:`NominatimHit` ou ``None`` si introuvable.

    Lève :class:`NominatimBlockedError` sur 403/429 (rate-limit / blocage) afin
    d'arrêter proprement plutôt que de marquer silencieusement tout en échec.
    ``addressdetails=1`` ajoute le détail d'adresse structuré (postcode,
    ville) à la MÊME requête/réponse — aucun appel réseau supplémentaire.
    """
    params = {
        "format": "json", "limit": "1", "countrycodes": "be",
        "addressdetails": "1", "q": query,
    }
    url = base_url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise NominatimBlockedError(
                f"Nominatim a répondu HTTP {exc.code} (rate-limit / blocage). "
                "Réduisez la cadence et renseignez CONTACT_EMAIL."
            ) from exc
        return None
    except urllib.error.URLError:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not data:
        return None
    first = data[0]
    try:
        lat, lon = float(first["lat"]), float(first["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    postcode, city = extract_nominatim_place(first)
    return NominatimHit(lat=lat, lon=lon, postcode=postcode, city=city)


def geocode_with_dedup_fallback(
    address: str,
    postal_code: str,
    place: str,
    user_agent: str,
    geocode_fn=nominatim_geocode,
    sleep_fn=None,
    country: str = "Belgium",
) -> tuple[Optional[NominatimHit], str, bool]:
    """Géocode une adresse avec un repli « adresse dédupliquée » sur échec.

    Renvoie ``(hit, query, used_fallback)`` :

    * **1er essai** — requête construite sur l'adresse BRUTE
      (:func:`build_geocode_query`). Chemin nominal INCHANGÉ : si ce premier
      essai réussit, aucun repli n'est tenté (``used_fallback=False``).
    * **Repli (uniquement si)** — le 1er essai renvoie ``not_found`` (``None``)
      ET l'adresse brute contient un « / » ET son nettoyage
      (:func:`clean_duplicated_address`) change effectivement la chaîne. Un
      SECOND et unique essai est alors tenté avec l'adresse nettoyée. ``sleep_fn``
      (s'il est fourni) est appelé AVANT ce second appel pour respecter la
      cadence Nominatim (1 req/s) entre les deux tentatives.
    * Sur repli réussi -> ``(hit, retry_query, True)`` (la requête retournée
      est celle qui a produit le point, pour traçabilité). Sur échec (avec ou
      sans repli) -> ``(None, query_brute, False)`` : comportement inchangé.

    Injection de ``geocode_fn`` / ``sleep_fn`` -> fonction PURE testable via
    pytest (mock HTTP) sans dépendance PyQGIS. :class:`NominatimBlockedError`
    remonte telle quelle (l'appelant l'arrête proprement). ``geocode_fn`` doit
    renvoyer un :class:`NominatimHit` (ou ``None``) — cette fonction ne fait
    que le faire transiter, elle n'inspecte pas sa forme.
    """
    query = build_geocode_query(address, postal_code, place, country=country)
    hit = geocode_fn(query, user_agent)
    if hit is not None:
        return hit, query, False
    if "/" in (address or ""):
        cleaned = clean_duplicated_address(address)
        if cleaned != address:
            if sleep_fn is not None:
                sleep_fn()  # cadence Nominatim : 1 req/s avant le 2e appel
            retry_query = build_geocode_query(
                cleaned, postal_code, place, country=country
            )
            retry_hit = geocode_fn(retry_query, user_agent)
            if retry_hit is not None:
                return retry_hit, retry_query, True
    return None, query, False


def _style_save_error_message(result) -> str:
    """Interprète le retour de ``saveStyleToDatabase[V2]`` -> message d'erreur.

    Deux variantes de l'API QGIS coexistent selon la version :

    * ``QgsVectorLayer.saveStyleToDatabase`` (dépréciée depuis QGIS ~3.44) —
      binding Python : renvoie la chaîne ``msgError`` (vide = succès) ;
    * ``QgsVectorLayer.saveStyleToDatabaseV2`` (QGIS ~3.44+) — renvoie un tuple
      ``(QgsMapLayer.SaveStyleResults, msgError)``.

    On considère l'enregistrement réussi si le message d'erreur (la DERNIÈRE
    chaîne du retour, quelle que soit la forme) est vide. ``None`` (méthode
    ``void`` mappée sans sortie par SIP) est traité comme un succès. Fonction
    PURE — aucune dépendance PyQGIS, couverte par pytest.
    """
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, tuple):
        for item in reversed(result):
            if isinstance(item, str):
                return item.strip()
    return ""


# Nom du fichier de style livré dans la collection Resource Sharing. Le script
# (``processing/geocode_asbuilt_depth.py``) et le style (``style/<ce nom>``) sont
# frères sous ``collections/<id>/`` : ce ``.qml`` est la SOURCE DE VÉRITÉ UNIQUE du
# rendu profondeur, appliquée par le script lui-même (post-traitement live ET
# style embarqué dans le GeoPackage), et applicable à la main comme filet.
_DEPTH_STYLE_QML_NAME = "depth_category.qml"


def _resource_sharing_style_dirs(profile_dir: Optional[str]) -> list[str]:
    """Sous-dossiers ``style/`` sous ``resource_sharing/collections/*/style/``.

    QGIS Resource Sharing copie les scripts Processing À PLAT dans
    ``processing/scripts/`` (sans le dossier ``style/`` frère), tandis que le
    ``.qml`` reste dans son propre cache de collection sous
    ``<profil QGIS>/resource_sharing/collections/<nom>/style/``. ``<nom>`` est
    le nom donné au DÉPÔT par l'utilisateur dans le plugin (pas une constante
    reconstructible) — on scanne donc par glob plutôt que de le deviner.
    Fonction PURE (os.path/glob) : ``profile_dir`` est injecté (au lieu d'un
    appel à ``QgsApplication.qgisSettingsDirPath()`` ici) pour rester testable
    via pytest sans dépendance PyQGIS.
    """
    if not profile_dir:
        return []
    pattern = os.path.join(profile_dir, "resource_sharing", "collections", "*", "style")
    return sorted(p for p in glob.glob(pattern) if os.path.isdir(p))


def _depth_style_qml_path(profile_dir: Optional[str] = None) -> Optional[str]:
    """Chemin absolu du ``.qml`` de profondeur, ou ``None`` si introuvable.

    Deux emplacements possibles, dans cet ordre :

    1. Sibling de CE module sous ``../style/`` — valable quand le script est
       exécuté depuis une structure de collection intacte (``processing/`` +
       ``style/`` frères, ex. dépôt source, tests).
    2. Cache Resource Sharing du profil QGIS actif (:func:`_resource_sharing_style_dirs`)
       — c'est l'emplacement réel en usage normal, le script étant copié à plat
       dans ``processing/scripts/`` par le plugin (cf. ce module docstring).

    Renvoie ``None`` si ``__file__`` est indisponible pour (1) et qu'aucun
    candidat de (2) n'existe — l'appelant replie alors sur le rendu Python.
    Fonction PURE (os.path/glob) — couverte par pytest.
    """
    candidates: list[str] = []
    try:
        module_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(
            os.path.normpath(os.path.join(module_dir, "..", "style", _DEPTH_STYLE_QML_NAME))
        )
    except NameError:  # pragma: no cover - __file__ absent (exec sans fichier)
        pass
    candidates.extend(
        os.path.join(style_dir, _DEPTH_STYLE_QML_NAME)
        for style_dir in _resource_sharing_style_dirs(profile_dir)
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


# Nom du fichier de style des segments d'axe de rue, frère de _DEPTH_STYLE_QML_NAME
# sous ``style/`` — même statut de SOURCE DE VÉRITÉ UNIQUE, cf. _apply_segments_style.
_DEPTH_SEGMENTS_STYLE_QML_NAME = "depth_segments.qml"


def _depth_segments_style_qml_path(profile_dir: Optional[str] = None) -> Optional[str]:
    """Chemin absolu du ``.qml`` de segments, ou ``None`` si introuvable.

    Même mécanisme de résolution que :func:`_depth_style_qml_path` (sibling
    ``../style/`` du module, puis cache Resource Sharing du profil QGIS actif
    via :func:`_resource_sharing_style_dirs`), appliqué au fichier voisin
    ``depth_segments.qml``. Fonction PURE (os.path/glob) — couverte par pytest.
    """
    candidates: list[str] = []
    try:
        module_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(
            os.path.normpath(
                os.path.join(module_dir, "..", "style", _DEPTH_SEGMENTS_STYLE_QML_NAME)
            )
        )
    except NameError:  # pragma: no cover - __file__ absent (exec sans fichier)
        pass
    candidates.extend(
        os.path.join(style_dir, _DEPTH_SEGMENTS_STYLE_QML_NAME)
        for style_dir in _resource_sharing_style_dirs(profile_dir)
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _named_style_loaded_ok(result) -> bool:
    """Interprète le retour de ``QgsVectorLayer.loadNamedStyle`` -> succès booléen.

    Le binding Python renvoie usuellement un tuple ``(message, result_flag)`` où
    ``result_flag`` (booléen) indique si le style a été chargé ; certaines versions
    renvoient un booléen simple. On considère le chargement réussi si un booléen
    ``True`` figure dans le retour. Fonction PURE — aucune dépendance PyQGIS,
    couverte par pytest.
    """
    if isinstance(result, bool):
        return result
    if isinstance(result, tuple):
        return any(item is True for item in result)
    return False


def build_summary_matrix(
    by_group: dict,
    order: tuple = DEPTH_SUMMARY_ORDER,
    last_row_label: Optional[str] = None,
) -> dict:
    """Agrège un comptage ``{groupe: Counter(catégorie)}`` en matrice pivot.

    Groupe générique (ville, fichier source...) : une ligne par clé de
    ``by_group``, une colonne par catégorie de profondeur, plus les totaux de
    ligne et de colonne. C'est l'UNIQUE source de vérité du total général
    (somme de tous les Counters) : aucun compteur global parallèle.

    Retour (``dict``) — tout est déjà ordonné, prêt à écrire :

    * ``categories`` : colonnes catégorie ordonnées = ``order`` puis toute
      catégorie inattendue rencontrée, triée ;
    * ``rows`` : ``list`` de ``{"group", "counts", "total"}`` — trié
      alphabétiquement, sauf ``last_row_label`` (si fourni et présent) toujours
      relégué en DERNIÈRE ligne (ex. une clé de repli « inconnue ») ;
    * ``totals`` : ``{catégorie: total}`` colonne par colonne (ligne « Total ») ;
    * ``grand_total`` : total général (somme de toutes les cellules).

    Fonction PURE (aucune dépendance PyQGIS / openpyxl) : couverte par pytest.
    Accepte indifféremment des valeurs ``Counter`` ou ``dict`` (via ``.get``).
    """
    # Colonnes : ordre canonique + extras inattendus (triés) pour ne rien perdre.
    seen_categories: set = set()
    for counter in by_group.values():
        seen_categories.update(counter)
    extras = sorted(str(c) for c in seen_categories - set(order))
    categories = list(order) + extras

    # Lignes : tri alpha, last_row_label (s'il est présent) relégué en dernier.
    real_groups = sorted(g for g in by_group if g != last_row_label)
    ordered_groups = real_groups + (
        [last_row_label] if last_row_label is not None and last_row_label in by_group else []
    )

    totals = {cat: 0 for cat in categories}
    rows = []
    for group in ordered_groups:
        counter = by_group[group]
        counts = {cat: int(counter.get(cat, 0)) for cat in categories}
        row_total = sum(counts.values())
        for cat in categories:
            totals[cat] += counts[cat]
        rows.append({"group": group, "counts": counts, "total": row_total})

    grand_total = sum(totals.values())
    return {
        "categories": categories,
        "rows": rows,
        "totals": totals,
        "grand_total": grand_total,
    }


# Intitulés IDENTIQUES a ceux attendus en ENTREE (WorkOrder/Intervention/
# Address/PostalCode/Place/profondeur, cf. shortHelpString) : ce CSV est
# concu pour etre corrige a la main PUIS RE-IMPORTE tel quel comme dossier
# d'entree. La colonne Depth est INDISPENSABLE a ce round-trip : sans elle,
# _extract_records_from_tables rejette toute ligne d'en-tete faute de
# colonne profondeur (les 4 colonnes WorkOrder/Intervention/Address/Depth
# sont TOUTES requises) -- bug reel observe en prod (0 interventions lues
# sur un CSV corrige a la main, 03/08). GeocodeQuery/SourceMessage restent
# en fin de ligne : ignorees par le classifieur d'en-tete (traçabilite
# seulement, sans risque de collision avec les colonnes reconnues).
UNGEOCODED_CSV_HEADER = (
    "Intervention", "WorkOrder", "Address", "PostalCode", "Place", "Depth",
    "GeocodeQuery", "SourceMessage",
)


def build_ungeocoded_rows(entries) -> list[list[str]]:
    """Construit les lignes CSV (en-tête inclus) des adresses non géocodées.

    ``entries`` : itérable de ``(InterventionRecord, query)`` où ``query`` est
    la requête Nominatim qui a échoué (traçabilité — reflète déjà le repli
    « adresse dédupliquée » si celui-ci a été tenté). Fonction PURE — aucune
    dépendance PyQGIS, couverte par pytest.
    """
    rows: list[list[str]] = [list(UNGEOCODED_CSV_HEADER)]
    for rec, query in entries:
        rows.append(
            [rec.intervention, rec.work_order, rec.address, rec.postal_code,
             rec.place, rec.depth_raw, query, rec.source_message]
        )
    return rows


def build_ungeocoded_message(entries) -> str:
    """Message compact, pret a copier-coller, listant les adresses non geocodees.

    ``entries`` : meme forme que build_ungeocoded_rows -- iterable de
    (InterventionRecord, query). Fonction pure, testable hors QGIS.
    """
    if not entries:
        return "Aucune adresse non géocodée."
    lines = [f"{len(entries)} adresse(s) non géocodée(s) à vérifier :"]
    for rec, _query in entries:
        location = " ".join(
            part for part in (rec.postal_code, rec.place) if part.strip()
        )
        addr_parts = [part for part in (rec.address, location) if part.strip()]
        addr = ", ".join(addr_parts)
        lines.append(f"- {rec.work_order} (Intervention {rec.intervention}) : {addr}")
    return "\n".join(lines)


def build_ungeocoded_email(entries, contact_email, n_ok) -> str:
    """Email complet (objet + corps + signature), pret a copier-coller.

    ``entries`` : memes adresses non geocodees que build_ungeocoded_message.
    ``n_ok`` : nombre d'adresses geocodees avec succes (pour le total dans
    le corps du mail). ``contact_email`` sert de signature -- reprend le
    parametre CONTACT_EMAIL de l'algorithme, pas de nom en dur (valable
    pour n'importe quel utilisateur du script, pas seulement Simon).
    Fonction pure, testable hors QGIS. N'a de sens que si ``entries`` est
    non vide (voir le garde au site d'appel : pas d'email a envoyer s'il
    n'y a rien a signaler).
    """
    count = len(entries)
    total = n_ok + count
    signature = (contact_email or "").strip() or "(email de contact non renseigné)"
    return (
        "Objet : Adresses à vérifier – géocodage As-Built Go Fiber\n\n"
        "Bonjour,\n\n"
        f"Lors du traitement des rapports As-Built Go Fiber, {n_ok} "
        f"adresse(s) sur {total} ont été géolocalisée(s) avec succès. Les "
        f"{count} adresse(s) suivante(s) n'ont pas pu être géolocalisée(s) "
        "automatiquement. Merci de bien vouloir les vérifier et les "
        "corriger si nécessaire :\n\n"
        f"{build_ungeocoded_message(entries)}\n\n"
        "Merci d'avance,\n\n"
        f"{signature}"
    )


def _build_attribute_values(rec, query, status, hit):
    """Valeurs d'attributs pures dérivées d'une intervention géocodée.

    Aucune dépendance PyQGIS — réutilisée à la fois pour la ``QgsFeature``
    OUTPUT et pour l'upsert vers ``public.geofiber_asbuilt_depth_points``
    (connexion ``be``).
    """
    depth_cm = parse_depth_cm(rec.depth_raw)
    return {
        "intervention_id": rec.intervention,
        "work_order": rec.work_order,
        "address_raw": rec.address,
        # PRIORITÉ au détail d'adresse structuré Nominatim (fiable,
        # indépendant d'un désalignement de colonnes dans le rapport
        # source — cf. incident colonnes PostalCode/Place garbled) ;
        # repli sur la normalisation du champ brut sinon.
        "postal_code": hit.postcode or normalize_postal_code(rec.postal_code),
        "place": hit.city or normalize_place(rec.place),
        "depth_cm": depth_cm,
        "depth_category": categorize_depth(depth_cm),
        "geocode_query": query,
        "geocode_status": status,
        "source_message": rec.source_message,
    }


LONG_SEGMENT_THRESHOLD_M = 100.0
ROAD_START_SENTINEL = "__ROAD_START__"
ROAD_END_SENTINEL = "__ROAD_END__"


@dataclass
class RoadLocation:
    """Un point de profondeur localise sur son axe de rue (fn_asbuilt_locate_on_road)."""

    intervention_id: str
    depth_category: str
    road_key: str
    position_m: float
    x: float
    y: float


@dataclass
class RoadExtent:
    """Bornes de la ligne de route fusionnee pour un road_key donne."""

    length_m: float
    start_x: float
    start_y: float
    end_x: float
    end_y: float


@dataclass
class SegmentHalf:
    """Une moitie de segment d'axe de rue (ou un segment de bout de route, half='a' seul).

    ``length_m`` est la longueur TOTALE du segment (A-B ou point-bout de
    route), identique sur les 2 moities d'une meme paire — pas la longueur
    de la moitie elle-meme.
    """

    point_a_intervention_id: str
    point_b_intervention_id: str  # intervention_id reel, ou ROAD_START_SENTINEL/ROAD_END_SENTINEL
    half: str  # 'a' ou 'b'
    depth_category: str
    is_long: bool
    length_m: float
    road_key: str
    start_x: float
    start_y: float
    end_x: float
    end_y: float


def build_segment_halves(locations, road_extents) -> list:
    """Construit les moities de segments d'axe de rue.

    ``locations`` : points DEJA filtres (categorie != 'manquante') et
    localises via fn_asbuilt_locate_on_road (un road_key manquant/vide est
    filtre par l'appelant, cf. Task 7). ``road_extents`` : dict road_key ->
    RoadExtent (bornes de la route fusionnee, pour les segments de bout de
    route). Fonction PURE, aucune dependance PyQGIS.
    """
    by_road = defaultdict(list)
    for loc in locations:
        by_road[loc.road_key].append(loc)

    halves: list[SegmentHalf] = []
    for road_key, points in by_road.items():
        ordered = sorted(points, key=lambda p: p.position_m)

        for a, b in zip(ordered, ordered[1:]):
            length = math.hypot(b.x - a.x, b.y - a.y)
            is_long = length >= LONG_SEGMENT_THRESHOLD_M
            mid_x, mid_y = (a.x + b.x) / 2.0, (a.y + b.y) / 2.0
            halves.append(SegmentHalf(
                point_a_intervention_id=a.intervention_id,
                point_b_intervention_id=b.intervention_id,
                half="a", depth_category=a.depth_category, is_long=is_long,
                length_m=length, road_key=road_key,
                start_x=a.x, start_y=a.y, end_x=mid_x, end_y=mid_y,
            ))
            halves.append(SegmentHalf(
                point_a_intervention_id=a.intervention_id,
                point_b_intervention_id=b.intervention_id,
                half="b", depth_category=b.depth_category, is_long=is_long,
                length_m=length, road_key=road_key,
                start_x=mid_x, start_y=mid_y, end_x=b.x, end_y=b.y,
            ))

        extent = road_extents.get(road_key)
        if extent is None:
            continue
        first, last = ordered[0], ordered[-1]
        for point, sentinel, (end_x, end_y) in (
            (first, ROAD_START_SENTINEL, (extent.start_x, extent.start_y)),
            (last, ROAD_END_SENTINEL, (extent.end_x, extent.end_y)),
        ):
            length = math.hypot(end_x - point.x, end_y - point.y)
            halves.append(SegmentHalf(
                point_a_intervention_id=point.intervention_id,
                point_b_intervention_id=sentinel,
                half="a", depth_category=point.depth_category,
                is_long=length >= LONG_SEGMENT_THRESHOLD_M,
                length_m=length, road_key=road_key,
                start_x=point.x, start_y=point.y, end_x=end_x, end_y=end_y,
            ))
    return halves


def plan_segment_sync(fresh, existing_keys):
    """Separe les moities fraichement calculees en (a upsert, a supprimer).

    ``fresh`` : liste de SegmentHalf issue de build_segment_halves (cet appel).
    ``existing_keys`` : cles (point_a_intervention_id, point_b_intervention_id,
    half) actuellement en base. Fonction PURE. L'upsert est TOUJOURS rejoue pour
    toute cle de ``fresh`` (idempotent cote SQL via ON CONFLICT DO UPDATE) ; la
    suppression ne vise QUE les cles presentes en base mais absentes de
    ``fresh`` (segments devenus obsoletes — point re-geocode ailleurs, etc.).
    """
    fresh_keys = {
        (h.point_a_intervention_id, h.point_b_intervention_id, h.half) for h in fresh
    }
    to_delete = sorted(existing_keys - fresh_keys)
    return list(fresh), to_delete


# ===========================================================================
# Wrapper QGIS Processing — fin, orchestration uniquement
# ===========================================================================
if HAS_QGIS:

    OUTPUT_CRS = "EPSG:31370"
    BE_CONNECTION_NAME = "be"
    BE_TABLE_SCHEMA = "public"
    BE_TABLE_NAME = "geofiber_asbuilt_depth_points"
    BE_GEOM_COLUMN = "geom"

    UNGEOCODED_TABLE_SCHEMA = "public"
    UNGEOCODED_TABLE_NAME = "geofiber_asbuilt_ungeocoded"

    SEGMENTS_TABLE_SCHEMA = "public"
    SEGMENTS_TABLE_NAME = "geofiber_asbuilt_depth_segments"

    # Fragments (minuscules) de messages d'erreur PostgreSQL/libpq, en anglais et
    # en francais (lc_messages du serveur), signalant que fn_asbuilt_locate_on_road
    # est structurellement injoignable — cf. _locate_points_on_road : un tel echec
    # interrompt la localisation au lieu d'etre re-tente point par point.
    _LOCATE_FATAL_ERROR_MARKERS = (
        "does not exist",
        "n'existe pas",
        "permission denied",
        "droit refusé",
        "droit refuse",
        "server closed the connection",
        "le serveur a fermé la connexion",
        "no connection to the server",
        "pas de connexion au serveur",
        "could not connect",
        "connection to server",
    )

    _SEGMENT_FIELD_SPECS = [
        ("point_a_intervention_id", QVariant.String),
        ("point_b_intervention_id", QVariant.String),
        ("half", QVariant.String),
        ("depth_category", QVariant.String),
        ("is_long", QVariant.Bool),
        ("length_m", QVariant.Double),
        ("road_key", QVariant.String),
    ]

    _UNGEOCODED_FIELD_SPECS = [
        ("intervention_id", QVariant.String),
        ("work_order", QVariant.String),
        ("address_raw", QVariant.String),
        ("postal_code", QVariant.String),
        ("place", QVariant.String),
        ("depth_raw", QVariant.String),
        ("geocode_query", QVariant.String),
        ("source_message", QVariant.String),
    ]

    _FIELD_SPECS = [
        ("intervention_id", QVariant.String),
        ("work_order", QVariant.String),
        ("address_raw", QVariant.String),
        ("postal_code", QVariant.String),
        ("place", QVariant.String),
        ("depth_cm", QVariant.Double),
        ("depth_category", QVariant.String),
        ("geocode_query", QVariant.String),
        ("geocode_status", QVariant.String),
        ("source_message", QVariant.String),
    ]

    def _build_output_fields() -> "QgsFields":
        fields = QgsFields()
        for name, qtype in _FIELD_SPECS:
            fields.append(QgsField(name, qtype))
        return fields

    def _build_segment_output_fields() -> "QgsFields":
        fields = QgsFields()
        for name, qtype in _SEGMENT_FIELD_SPECS:
            fields.append(QgsField(name, qtype))
        return fields

    def _build_feature(fields, values, point):
        feat = QgsFeature(fields)
        feat.setGeometry(QgsGeometry.fromPointXY(point))
        for name, value in values.items():
            feat.setAttribute(name, value)
        return feat

    def _build_depth_renderer() -> "QgsCategorizedSymbolRenderer":
        """Rendu catégorisé de REPLI, construit en Python depuis ``DEPTH_COLORS``.

        La source de vérité du rendu est le ``.qml`` livré (cf.
        :func:`_apply_depth_style`) ; cette fonction n'est utilisée que comme filet
        ultime quand le ``.qml`` est absent/illisible, pour ne jamais laisser la
        couche sans symbologie.
        """
        categories = []
        for value in ("manquante", "rouge", "orange", "vert"):
            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.PointGeometry)
            symbol.setColor(QColor(DEPTH_COLORS[value]))
            categories.append(
                QgsRendererCategory(value, symbol, DEPTH_CATEGORY_LABELS[value])
            )
        return QgsCategorizedSymbolRenderer("depth_category", categories)

    def _apply_depth_style(layer, feedback=None) -> bool:
        """Applique le style profondeur à ``layer``. SOURCE DE VÉRITÉ = le ``.qml``.

        Charge ``style/depth_category.qml`` (livré à côté du script) via
        ``loadNamedStyle``. Si le ``.qml`` est absent/illisible, replie sur le
        rendu Python :func:`_build_depth_renderer` (filet ultime) plutôt que de
        laisser la couche sans style. Best-effort et NON bloquant : journalise
        via ``feedback`` (si fourni) sans jamais lever. Retourne ``True`` si le
        ``.qml`` a été appliqué, ``False`` sur repli Python.

        Utilisée aux DEUX points de style (post-traitement live ET style embarqué
        dans le GeoPackage) : ils partagent donc exactement la même source.
        """
        try:
            profile_dir = QgsApplication.qgisSettingsDirPath()
        except Exception:  # pragma: no cover - défensif (résolution best-effort)
            profile_dir = None
        qml_path = _depth_style_qml_path(profile_dir)
        if qml_path is not None:
            loaded = False
            try:
                result = layer.loadNamedStyle(qml_path)
                loaded = _named_style_loaded_ok(result)
            except Exception as exc:  # pragma: no cover - défensif
                if feedback is not None:
                    feedback.pushInfo(
                        f"Style .qml non chargé ({exc}) — repli sur le rendu Python."
                    )
            if loaded:
                return True
            if feedback is not None:
                feedback.pushInfo(
                    f"Style .qml non appliqué ({qml_path}) — repli sur le rendu Python."
                )
        elif feedback is not None:
            feedback.pushInfo(
                "Style .qml introuvable à côté du script — repli sur le rendu Python."
            )
        layer.setRenderer(_build_depth_renderer())
        return False

    def _apply_segments_style(layer, feedback=None) -> bool:
        """Applique le style segments à ``layer``. SOURCE DE VÉRITÉ = le ``.qml``.

        Même patron que :func:`_apply_depth_style`, appliqué à
        ``style/depth_segments.qml`` (livré à côté du script). Best-effort et
        NON bloquant. Retourne ``True`` si le ``.qml`` a été appliqué,
        ``False`` sur repli Python (renderer catégorisé minimal, sans la
        distinction plein/pointillé par ``is_long`` — c'est le ``.qml`` qui
        porte cette distinction, cf. RuleRenderer).
        """
        try:
            profile_dir = QgsApplication.qgisSettingsDirPath()
        except Exception:  # pragma: no cover - défensif (résolution best-effort)
            profile_dir = None
        qml_path = _depth_segments_style_qml_path(profile_dir)
        if qml_path is not None:
            loaded = False
            try:
                result = layer.loadNamedStyle(qml_path)
                loaded = _named_style_loaded_ok(result)
            except Exception as exc:  # pragma: no cover - défensif
                if feedback is not None:
                    feedback.pushInfo(
                        f"Style segments non chargé ({exc}) — repli sur un "
                        "renderer categorise minimal."
                    )
            if loaded:
                return True
            if feedback is not None:
                feedback.pushInfo(
                    f"Style segments non appliqué ({qml_path}) — repli sur un "
                    "renderer categorise minimal."
                )
        elif feedback is not None:
            feedback.pushInfo(
                "Style segments introuvable à côté du script — repli sur un "
                "renderer categorise minimal."
            )
        categories = []
        for value, color in DEPTH_COLORS.items():
            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.LineGeometry)
            symbol.setColor(QColor(color))
            categories.append(
                QgsRendererCategory(value, symbol, DEPTH_CATEGORY_LABELS.get(value, value))
            )
        layer.setRenderer(QgsCategorizedSymbolRenderer("depth_category", categories))
        return False

    def _save_style_to_db(layer, name: str, description: str) -> str:
        """Enregistre le style courant de ``layer`` en base (useAsDefault=True).

        Retourne le message d'erreur (chaîne vide = succès), interprété par
        :func:`_style_save_error_message` quelle que soit la variante de l'API.
        saveStyleToDatabaseV2 (QGIS ~3.44+) est préféré quand présent ; repli
        sur saveStyleToDatabase (dépréciée mais disponible sur les QGIS plus
        anciens, dont le binding renvoie une chaîne seule — PAS un tuple).
        uiFileContent="" : pas d'interface Qt embarquée. Les exceptions (provider
        sans stockage de style, verrou…) remontent : à l'appelant de décider.
        """
        if hasattr(layer, "saveStyleToDatabaseV2"):
            result = layer.saveStyleToDatabaseV2(name, description, True, "")
        else:
            result = layer.saveStyleToDatabase(name, description, True, "")
        return _style_save_error_message(result)

    def _sync_style_to_db(layer, name: str, description: str, feedback) -> bool:
        """Ecrit le style courant de ``layer`` dans layer_styles (useAsDefault=True).

        Best-effort, non bloquant (meme politique que _apply_depth_style et
        _upsert_geocoded_records) : un echec loggue une info sans jamais faire
        echouer le run. Ne fonctionne que si layer est connectee en direct sur
        postgres (c'est le cas pour les couches upsertees via 'be', cf.
        _upsert_geocoded_records / _sync_segments). Meme appel + interpretation
        que _embed_style_in_output (cf. _save_style_to_db).
        """
        try:
            error = _save_style_to_db(layer, name, description)
        except Exception as exc:  # provider sans stockage de style en base…
            feedback.pushInfo(f"Style non synchronise en base pour « {name} » ({exc}).")
            return False
        if error:
            feedback.pushInfo(f"Style non synchronise en base pour « {name} » ({error}).")
            return False
        feedback.pushInfo(
            f"Style « {name} » synchronise en base (layer_styles, style par defaut)."
        )
        return True

    class _SegmentsLayerStyler(QgsProcessingLayerPostProcessorInterface):
        """Applique le style segments (source : ``style/depth_segments.qml``).

        Pendant de :class:`_DepthLayerStyler` pour la sortie OUTPUT_SEGMENTS :
        post-traitement de la couche chargée automatiquement par QGIS en fin
        d'exécution, délégué à :func:`_apply_segments_style` (même source de
        vérité que le style synchronisé en base).
        """

        def __init__(self):
            super().__init__()

        def postProcessLayer(self, layer, context, feedback):  # noqa: N802
            try:
                _apply_segments_style(layer, feedback)
                layer.triggerRepaint()
            except Exception:  # pragma: no cover - défensif (rendu non bloquant)
                pass

    class _DepthLayerStyler(QgsProcessingLayerPostProcessorInterface):
        """Applique le style profondeur (source : ``style/depth_category.qml``).

        Post-traitement de la couche chargée automatiquement par QGIS en fin
        d'exécution. Délègue à :func:`_apply_depth_style` — donc la MÊME source de
        vérité (le ``.qml``) que le style embarqué dans le GeoPackage, garantissant
        un rendu identique entre l'affichage immédiat et les ouvertures ultérieures.
        """

        def __init__(self):
            super().__init__()

        def postProcessLayer(self, layer, context, feedback):  # noqa: N802
            try:
                _apply_depth_style(layer, feedback)
                layer.triggerRepaint()
            except Exception:  # pragma: no cover - défensif (rendu non bloquant)
                pass

    def _import_extract_msg(feedback=None):
        try:
            import extract_msg  # noqa: F401

            return extract_msg
        except ImportError:
            pass
        if feedback is not None:
            feedback.pushInfo(
                "Module 'extract-msg' absent — tentative d'installation via pip…"
            )
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "extract-msg"],
                check=True,
                capture_output=True,
            )
        except Exception as exc:  # installation impossible
            raise QgsProcessingException(
                "Le module Python 'extract-msg' est requis pour lire les fichiers "
                ".msg et son installation automatique a échoué.\n"
                f"Installez-le manuellement :\n    {sys.executable} -m pip install extract-msg\n"
                f"(détail : {exc})"
            )
        try:
            import extract_msg  # noqa: F401

            return extract_msg
        except ImportError:
            raise QgsProcessingException(
                "Le module 'extract-msg' reste introuvable après installation.\n"
                f"Installez-le manuellement : {sys.executable} -m pip install extract-msg"
            )

    def _disable_openpyxl_lxml() -> None:
        """Empêche openpyxl d'utiliser lxml (repli forcé sur ``xml.etree`` stdlib).

        openpyxl bascule automatiquement sur lxml s'il est importable dans
        l'environnement (plus rapide). Observé en pratique sur QGIS Windows :
        ce lxml (roue pip, libxml2 embarqué) coexiste dans le MÊME processus
        que le libxml2 déjà chargé par GDAL/OGR (bundle QGIS) — conflit binaire
        qui se manifeste comme un CRASH NATIF (« access violation » Windows,
        PAS une exception Python catchable) dès le premier
        ``openpyxl.Workbook()`` (cf. ``_write_summary_xlsx``), pouvant aussi
        toucher la lecture ``.xlsx`` en entrée (même mécanisme interne).

        On bloque donc l'import de ``lxml`` — AVANT le tout premier
        ``import openpyxl`` du process, seul moment où le choix lxml/stdlib se
        fige dans les sous-modules d'openpyxl — en insérant une entrée ``None``
        dans ``sys.modules`` (sémantique standard : force ``ImportError`` sur
        tout ``import lxml`` suivant, cf. doc du système d'import). ``setdefault``
        : n'écrase JAMAIS un lxml déjà chargé par un autre composant QGIS/plugin
        (on ne casserait pas un usage existant), et ne fait rien si openpyxl est
        déjà importé dans ce process (trop tard — figé au premier import ;
        nécessite alors un redémarrage de QGIS pour repartir sur un process
        neuf). Fonction PURE côté effets : ne fait qu'annoter ``sys.modules``.
        """
        if "openpyxl" in sys.modules:
            return
        sys.modules.setdefault("lxml", None)
        sys.modules.setdefault("lxml.etree", None)

    def _import_openpyxl(feedback=None):
        _disable_openpyxl_lxml()
        try:
            import openpyxl  # noqa: F401

            return openpyxl
        except ImportError:
            pass
        if feedback is not None:
            feedback.pushInfo(
                "Module 'openpyxl' absent — tentative d'installation via pip…"
            )
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "openpyxl"],
                check=True,
                capture_output=True,
            )
        except Exception as exc:  # installation impossible
            raise QgsProcessingException(
                "Le module Python 'openpyxl' est requis pour lire les fichiers "
                ".xlsx et son installation automatique a échoué.\n"
                f"Installez-le manuellement :\n    {sys.executable} -m pip install openpyxl\n"
                f"(détail : {exc})"
            )
        try:
            import openpyxl  # noqa: F401

            return openpyxl
        except ImportError:
            raise QgsProcessingException(
                "Le module 'openpyxl' reste introuvable après installation.\n"
                f"Installez-le manuellement : {sys.executable} -m pip install openpyxl"
            )

    def _read_msg_bodies(path: str, extract_msg_module):
        message = extract_msg_module.Message(path)
        try:
            html = message.htmlBody
            body = message.body
        finally:
            try:
                message.close()
            except Exception:
                pass
        if isinstance(html, bytes):
            html = html.decode("utf-8", "replace")
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        return html or "", body or ""

    def _read_records_from_file(path, extract_msg_module, openpyxl_module):
        """Aiguille un fichier vers le bon lecteur -> list[InterventionRecord].

        Chaque lecteur ne fait que produire la représentation intermédiaire
        commune (``InterventionRecord``) ; toute la normalisation /
        dédoublonnage / géocodage en aval reste partagée et inchangée.
        """
        ext = os.path.splitext(path)[1].lower()
        if ext == ".msg":
            html, body = _read_msg_bodies(path, extract_msg_module)
            return parse_report_content(html, body)
        if ext == ".csv":
            return parse_tabular_rows(read_csv_rows(path))
        if ext in (".xlsx", ".xls"):
            return parse_tabular_rows(read_xlsx_rows(path, openpyxl_module))
        return []

    def _read_error_message(path: str, exc: Exception) -> str:
        """Message d'avertissement contextualisé (cas .xls legacy explicité)."""
        base = os.path.basename(path)
        if os.path.splitext(path)[1].lower() == ".xls":
            return (
                f"{base} : lecture impossible. Les fichiers .xls binaires legacy "
                "(Excel pré-2007) ne sont pas pris en charge — ré-exportez-les "
                f"en .xlsx ou .csv depuis Excel. (détail : {exc})"
            )
        return f"Lecture impossible de {base} : {exc}"

    def _sleep_with_cancel(feedback, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or feedback.isCanceled():
                return
            time.sleep(min(0.1, remaining))

    class GeocodeAsBuiltDepthAlgorithm(QgsProcessingAlgorithm):
        """Géocode un lot de rapports As-Built ``.msg`` et colore par profondeur."""

        INPUT_FOLDER = "INPUT_FOLDER"
        EXISTING_LAYER = "EXISTING_LAYER"
        CONTACT_EMAIL = "CONTACT_EMAIL"
        PUSH_TO_BE = "PUSH_TO_BE"
        OUTPUT = "OUTPUT"
        SUMMARY = "SUMMARY"
        UNGEOCODED = "UNGEOCODED"
        OUTPUT_SEGMENTS = "OUTPUT_SEGMENTS"

        # -- métadonnées --------------------------------------------------
        def name(self):
            return "geocode_asbuilt_depth"

        def displayName(self):
            return self.tr(
                "Géocoder rapport As-Built (.msg / .xlsx / .csv) par profondeur"
            )

        def group(self):
            return self.tr("Constructel")

        def groupId(self):
            return "constructel"

        def tr(self, string):
            return QCoreApplication.translate("GeocodeAsBuiltDepthAlgorithm", string)

        def createInstance(self):
            return GeocodeAsBuiltDepthAlgorithm()

        def shortHelpString(self):
            return self.tr(
                "Géocode les rapports périodiques « To update Go Fiber As-Built » "
                "et produit une couche de points EPSG:31370 colorée par "
                "profondeur de pose.\n\n"
                "FORMATS D'ENTRÉE — le dossier est balayé (non récursif) pour les "
                "fichiers .msg (Outlook), .xlsx / .xls (Excel) et .csv. Le .msg "
                "gère les corps HTML et texte brut (message direct ou transféré "
                "« FW: »). Les .xls binaires legacy (Excel pré-2007) ne sont pas "
                "lus directement — ré-exportez-les en .xlsx ou .csv.\n\n"
                "FORMAT ATTENDU — un tableau avec les colonnes : WorkOrder, "
                "Intervention, Address, PostalCode, Place, et une colonne de "
                "profondeur (intitulé contenant « depth » ou « profondeur », "
                "ex : « Tube depth in the T-branch (cm) »). Les en-têtes sont "
                "détectés par intitulé (insensible à la casse), pas par "
                "position.\n\n"
                "PROFONDEUR — une valeur avec séparateur décimal est interprétée "
                "en mètres (0.60 -> 60 cm) ; sinon en centimètres (70 -> 70 cm). "
                "Catégories (seuils fixes) : manquante (< 10 cm), rouge (< 50 cm), "
                "orange (< 55 cm), vert (≥ 55 cm).\n\n"
                "MODE ADDITIF — fournir une couche déjà géocodée dans "
                "EXISTING_LAYER : les interventions déjà présentes (clé "
                "= Intervention) ne sont pas re-géocodées.\n\n"
                "BASE 'be' (PUSH_TO_BE, optionnel, activé par défaut) — chaque "
                "intervention géocodée avec succès (nouveau géocodage OU déjà "
                "présente en mode additif) est aussi poussée dans "
                "public.geofiber_asbuilt_depth_points via la connexion QGIS "
                "'be' (plugin Constructel Bridge). Écrasement complet de la "
                "ligne en cas de conflit sur l'identifiant d'intervention : "
                "rejouer un rapport avec une adresse dégradée écrase une "
                "géométrie précédemment correcte. Désactivez PUSH_TO_BE pour "
                "un run de test sans risque d'altérer la base de production. "
                "Connexion absente/injoignable -> avertissement, section "
                "ignorée, OUTPUT reste produit normalement.\n\n"
                "NON GÉOCODÉES EN BASE (avec PUSH_TO_BE) — chaque intervention "
                "non géocodée de ce run est aussi poussée dans "
                "public.geofiber_asbuilt_ungeocoded (identifiants source, "
                "adresse brute, requête Nominatim en échec), écrasée en cas de "
                "conflit sur l'identifiant d'intervention. Une ligne n'est pas "
                "retirée de cette table si l'intervention est géocodée plus "
                "tard.\n\n"
                "SEGMENTS D'AXE DE RUE (avec PUSH_TO_BE) — après l'upsert, TOUTE "
                "la table public.geofiber_asbuilt_depth_points (pas seulement ce "
                "run) est relue : chaque point de profondeur connue est projeté "
                "sur l'axe de sa rue (nom extrait de l'adresse, numéro/boîte/code "
                "postal retirés), puis les points consécutifs d'une même rue sont "
                "reliés par un segment coupé en deux moitiés, chacune colorée "
                "selon la profondeur de son point ; les bouts de rue sont "
                "prolongés depuis le premier/dernier point. Segments ≥ "
                f"{LONG_SEGMENT_THRESHOLD_M:g} m affichés en pointillé "
                "(interpolation peu fiable). Résultat synchronisé intégralement "
                "dans public.geofiber_asbuilt_depth_segments : upsert des segments "
                "recalculés, suppression des segments devenus obsolètes — "
                "suppression désactivée pour le run si la localisation ou la "
                "lecture des points est incomplète. Un point sans nom de rue "
                "exploitable ou sans tronçon correspondant est simplement omis "
                "(compté dans le journal). OUTPUT_SEGMENTS (optionnel) : couche "
                "des segments recalculés de ce run, stylée comme en base ; vide "
                "si PUSH_TO_BE est désactivé.\n\n"
                "STYLES EN BASE (avec PUSH_TO_BE) — ATTENTION : à chaque run, les "
                "styles « depth_category » (points) et « depth_segments » "
                "(segments) sont réécrits dans la table layer_styles de la base "
                "'be' (saveStyleToDatabase, useAsDefault=True) : ils ÉCRASENT le "
                "style par défaut de ces deux tables. Une retouche manuelle "
                "enregistrée comme style par défaut dans QGIS sera perdue au run "
                "suivant — modifiez plutôt les .qml livrés dans la collection.\n\n"
                "TABLE DE SYNTHÈSE (SUMMARY, optionnel) — si un chemin .xlsx est "
                "fourni, un classeur de synthèse est écrit et chargé "
                "automatiquement comme couche (table) dans le projet. Feuille 1 "
                "« Synthèse par fichier » : matrice pivot — une ligne par fichier "
                "de rapport traité (plus une ligne « (couche existante) » pour les "
                "points recopiés en mode additif), une colonne par catégorie de "
                "profondeur, une colonne Total (par fichier) et une ligne Total "
                "(somme de chaque catégorie sur toutes les sources = total "
                "général). Feuille 2 « Pourcentages » : nombre et pourcentage par "
                "catégorie sur le total général. Laissé vide -> aucun fichier "
                "écrit.\n\n"
                "ADRESSES NON GÉOCODÉES (optionnel) — si un chemin .csv est "
                "fourni, une ligne par intervention non géocodée y est écrite "
                "(identifiants source + requête Nominatim en échec), pour "
                "corriger l'adresse à la main puis relancer. Laissé vide -> "
                "aucun fichier écrit.\n\n"
                "DÉPENDANCES — modules Python 'extract-msg' (.msg) et 'openpyxl' "
                "(.xlsx en lecture, ET écriture de la table de synthèse), "
                "installés automatiquement via pip au besoin. Les .csv "
                "n'utilisent que la stdlib.\n\n"
                "NOMINATIM — géocodage via OpenStreetMap, 1 requête/seconde. "
                "Renseignez CONTACT_EMAIL (recommandé par la politique d'usage "
                "d'OSM/Nominatim).\n\n"
                "REPLI « ADRESSE DÉDUPLIQUÉE » — si le géocodage d'une adresse "
                "échoue ET que celle-ci contient des segments « / » répétés (bug "
                "d'export : nom de rue dupliqué, ex « Malmedyer Straße/Malmedyer "
                "Straße 203 »), un second essai est tenté avec le dernier segment "
                "seul (« Malmedyer Straße 203 ») ; le repli est tracé dans le "
                "journal. La notation belge numéro/boîte (ex « Rue de la Gare "
                "12/3 ») N'EST PAS concernée : le repli ne s'applique QUE si les "
                "segments qui précèdent le dernier sont identiques entre eux "
                "(véritable répétition), pour ne jamais réduire une adresse "
                "légitime au seul numéro de boîte."
            )

        # -- paramètres ---------------------------------------------------
        def initAlgorithm(self, config=None):
            self.addParameter(
                QgsProcessingParameterFile(
                    self.INPUT_FOLDER,
                    self.tr("Dossier des rapports (.msg / .xlsx / .xls / .csv)"),
                    behavior=QgsProcessingParameterFile.Folder,
                )
            )
            self.addParameter(
                QgsProcessingParameterFeatureSource(
                    self.EXISTING_LAYER,
                    self.tr("Couche déjà géocodée (mode additif, optionnel)"),
                    optional=True,
                )
            )
            self.addParameter(
                QgsProcessingParameterString(
                    self.CONTACT_EMAIL,
                    self.tr("Email de contact (User-Agent Nominatim, recommandé)"),
                    defaultValue="sig@constructel.fr",
                    optional=True,
                )
            )
            self.addParameter(
                QgsProcessingParameterBoolean(
                    self.PUSH_TO_BE,
                    self.tr(
                        "Pousser les interventions géocodées vers la base "
                        "'be' (Constructel Bridge)"
                    ),
                    defaultValue=True,
                )
            )
            self.addParameter(
                QgsProcessingParameterFeatureSink(
                    self.OUTPUT,
                    self.tr("Interventions géocodées"),
                )
            )
            # Sortie facultative : table de synthèse ventilée par fichier source
            # (matrice pivot fichier × catégorie + totaux) ; chargée en couche
            # (table) dans le projet. Laissée vide -> aucun fichier écrit.
            self.addParameter(
                QgsProcessingParameterFileDestination(
                    self.SUMMARY,
                    self.tr(
                        "Table de synthèse par fichier source (.xlsx, optionnel)"
                    ),
                    fileFilter="Classeur Excel (*.xlsx)",
                    optional=True,
                    createByDefault=True,
                )
            )
            # Sortie facultative : une ligne par intervention non géocodée
            # (identifiants source + requête Nominatim qui a échoué), pour
            # permettre une retouche manuelle de l'adresse avant un nouveau
            # passage. Laissée vide -> aucun fichier écrit.
            self.addParameter(
                QgsProcessingParameterFileDestination(
                    self.UNGEOCODED,
                    self.tr("Adresses non géocodées (.csv, optionnel)"),
                    fileFilter="CSV (*.csv)",
                    optional=True,
                    createByDefault=True,
                )
            )
            self.addParameter(
                QgsProcessingParameterFeatureSink(
                    self.OUTPUT_SEGMENTS,
                    self.tr("Segments d'axe de rue (optionnel)"),
                    type=QgsProcessing.TypeVectorLine,
                    optional=True,
                )
            )

        # -- traitement ---------------------------------------------------
        def processAlgorithm(self, parameters, context, feedback):
            folder = self.parameterAsFile(parameters, self.INPUT_FOLDER, context)
            contact_email = self.parameterAsString(parameters, self.CONTACT_EMAIL, context)
            user_agent = build_user_agent(contact_email)
            push_to_be = self.parameterAsBoolean(parameters, self.PUSH_TO_BE, context)
            # Chemin de la table de synthèse (paramètre optionnel) : chaîne vide
            # si l'utilisateur ne l'a pas renseigné -> aucune sortie xlsx.
            summary_path = self.parameterAsFileOutput(
                parameters, self.SUMMARY, context
            )
            # Chemin du CSV des adresses non géocodées (paramètre optionnel) :
            # chaîne vide si l'utilisateur ne l'a pas renseigné -> aucune sortie.
            ungeocoded_path = self.parameterAsFileOutput(
                parameters, self.UNGEOCODED, context
            )

            out_crs = QgsCoordinateReferenceSystem(OUTPUT_CRS)
            fields = _build_output_fields()
            (sink, dest_id) = self.parameterAsSink(
                parameters,
                self.OUTPUT,
                context,
                fields,
                QgsWkbTypes.Point,
                out_crs,
            )
            if sink is None:
                raise QgsProcessingException(
                    self.invalidSinkError(parameters, self.OUTPUT)
                )

            # --- couche existante : recopie + set des ids déjà présents ---
            existing_source = self.parameterAsSource(
                parameters, self.EXISTING_LAYER, context
            )
            known_ids: set[str] = set()
            # Interventions geocodees avec succes -- nouveau geocodage (boucle
            # plus bas) OU deja presentes en mode additif (_copy_existing) --
            # pour l'upsert vers la connexion 'be' (cf.
            # self._upsert_geocoded_records) : (dict de valeurs d'attributs,
            # QgsPointXY reprojete en OUTPUT_CRS).
            geocoded_for_db: list[tuple[dict, "QgsPointXY"]] = []
            # Distribution des catégories de profondeur PAR VILLE (place
            # normalisée) pour la table de synthèse. Clé = valeur normalisée de
            # la ville (ou UNKNOWN_PLACE_LABEL si absente). Alimentée aux deux
            # points de comptage ci-dessous ; le total général se dérive en
            # sommant tous les Counters (source de vérité unique, cf.
            # build_summary_matrix).
            by_place: dict[str, Counter] = defaultdict(Counter)
            # Code(s) postal(aux) normalisé(s) rencontré(s) pour chaque ville
            # (affichés à côté du nom de ville dans la table de synthèse).
            postal_by_place: dict[str, set] = defaultdict(set)
            if existing_source is not None:
                known_ids, existing_for_db = self._copy_existing(
                    existing_source, sink, fields, out_crs, feedback,
                    by_place, postal_by_place,
                )
                geocoded_for_db.extend(existing_for_db)
                feedback.pushInfo(
                    f"{len(known_ids)} interventions déjà présentes dans la couche existante."
                )

            # --- collecte des entrées (.msg / .xlsx / .xls / .csv) -------
            input_paths = _collect_input_files(folder)
            if not input_paths:
                feedback.pushWarning(
                    f"Aucun fichier .msg/.xlsx/.xls/.csv trouvé dans {folder}."
                )

            # Imports paresseux : n'installer une dépendance que si le format
            # concerné est effectivement présent dans le dossier.
            has_msg = any(p.lower().endswith(".msg") for p in input_paths)
            has_spreadsheet = any(
                os.path.splitext(p)[1].lower() in (".xlsx", ".xls")
                for p in input_paths
            )
            extract_msg_module = _import_extract_msg(feedback) if has_msg else None
            openpyxl_module = _import_openpyxl(feedback) if has_spreadsheet else None

            all_records: list[InterventionRecord] = []
            for path in input_paths:
                if feedback.isCanceled():
                    break
                base = os.path.basename(path)
                try:
                    records = _read_records_from_file(
                        path, extract_msg_module, openpyxl_module
                    )
                except Exception as exc:
                    feedback.pushWarning(_read_error_message(path, exc))
                    continue
                for rec in records:
                    rec.source_message = base
                feedback.pushInfo(f"{base} : {len(records)} interventions lues.")
                all_records.extend(records)

            deduped = dedupe_records(all_records)
            feedback.pushInfo(
                f"{len(deduped)} interventions uniques après dédoublonnage "
                f"(sur {len(all_records)} lignes lues)."
            )

            # --- géocodage ----------------------------------------------
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            transform = QgsCoordinateTransform(wgs84, out_crs, QgsProject.instance())
            n_ok = n_nf = n_skip = 0
            total = max(len(deduped), 1)
            # Adresses non géocodées accumulées pour l'export CSV optionnel
            # (cf. self.UNGEOCODED) : (InterventionRecord, requête en échec).
            ungeocoded: list[tuple[InterventionRecord, str]] = []

            # Cadence Nominatim (1 req/s) en respectant l'annulation utilisateur.
            # Injecté dans le repli pour espacer ses deux appels, et réutilisé en
            # fin de boucle pour espacer les interventions successives.
            def _rate_limit_pause():
                _sleep_with_cancel(feedback, 1.0)

            for i, rec in enumerate(deduped):
                if feedback.isCanceled():
                    break
                if rec.intervention in known_ids:
                    n_skip += 1
                    continue
                try:
                    hit, query, used_fallback = geocode_with_dedup_fallback(
                        rec.address,
                        rec.postal_code,
                        rec.place,
                        user_agent,
                        sleep_fn=_rate_limit_pause,
                    )
                except NominatimBlockedError as exc:
                    raise QgsProcessingException(str(exc))
                if hit is None:
                    n_nf += 1
                    ungeocoded.append((rec, query))
                    feedback.pushWarning(
                        f"Non géocodé (intervention {rec.intervention}) : {query}"
                    )
                else:
                    point = transform.transform(QgsPointXY(hit.lon, hit.lat))
                    values = _build_attribute_values(rec, query, "ok", hit)
                    feature = _build_feature(fields, values, point)
                    sink.addFeature(feature, QgsFeatureSink.FastInsert)
                    geocoded_for_db.append((values, point))
                    known_ids.add(rec.intervention)
                    place_key = feature["place"] or UNKNOWN_PLACE_LABEL
                    by_place[place_key][str(feature["depth_category"])] += 1
                    if feature["postal_code"]:
                        postal_by_place[place_key].add(feature["postal_code"])
                    n_ok += 1
                    if used_fallback:
                        feedback.pushInfo(
                            f"Intervention {rec.intervention} géocodée via le repli "
                            "« adresse dédupliquée » (segments « / » répétés dans "
                            f"l'adresse source) : {query}"
                        )
                feedback.setProgress(int(100 * (i + 1) / total))
                _rate_limit_pause()  # politique Nominatim : 1 req/s

            feedback.pushInfo(
                f"{n_ok} interventions géocodées, {n_nf} échecs, "
                f"{n_skip} déjà présentes ignorées."
            )
            feedback.pushInfo(build_ungeocoded_message(ungeocoded))

            # Segments d'axe de rue recalcules — synchro complete (relit TOUTE la
            # table public.geofiber_asbuilt_depth_points, pas seulement le lot de
            # ce run), rempli le sink OUTPUT_SEGMENTS optionnel plus bas une fois
            # `outputs` initialise. N'a de sens QUE si push_to_be (les points
            # fraichement geocodes de CE run ne sont en base 'be' qu'apres
            # _upsert_geocoded_records, et la resynchro relit depuis la base).
            fresh_segments: list = []
            if push_to_be and not feedback.isCanceled():
                try:
                    self._upsert_geocoded_records(geocoded_for_db, feedback)
                except Exception as exc:
                    feedback.pushWarning(
                        f"Base 'be' : erreur inattendue lors de l'upsert ({exc}) — "
                        "OUTPUT reste disponible."
                    )
                try:
                    self._upsert_ungeocoded_records(ungeocoded, feedback)
                except Exception as exc:
                    feedback.pushWarning(
                        f"Base 'be' (non-geocodes) : erreur inattendue lors de "
                        f"l'upsert ({exc}) — OUTPUT reste disponible."
                    )
                try:
                    fresh_segments = self._sync_segments(feedback)
                except Exception as exc:
                    feedback.pushWarning(
                        f"Base 'be' (segments) : erreur inattendue lors de la "
                        f"resynchronisation ({exc}) — OUTPUT reste disponible."
                    )
                if geocoded_for_db:
                    be_points_layer = self._open_be_points_layer(feedback)
                    if be_points_layer is not None:
                        _apply_depth_style(be_points_layer, feedback)
                        _sync_style_to_db(
                            be_points_layer,
                            "depth_category",
                            "Style profondeur As-Built (points) — géré par geocode_asbuilt_depth, ne pas éditer manuellement.",
                            feedback,
                        )
            elif not push_to_be:
                feedback.pushInfo(
                    "Push vers la base 'be' désactivé (paramètre) — OUTPUT "
                    "uniquement."
                )

            # --- symbologie : deux mécanismes COMPLÉMENTAIRES ------------
            # Même source de vérité aux deux points : le .qml livré
            # (style/depth_category.qml), chargé via _apply_depth_style.
            # 1) Post-traitement — applique le style à la couche SI (et
            #    seulement si) QGIS la charge automatiquement juste après
            #    l'exécution. Fragile par nature : ne joue que dans ce cas.
            #    Conservé comme filet pour l'application immédiate.
            if context.willLoadLayerOnCompletion(dest_id):
                self._styler = _DepthLayerStyler()
                context.layersToLoadOnCompletion()[dest_id].setPostProcessor(
                    self._styler
                )

            # 2) Style EMBARQUÉ dans le GeoPackage (table layer_styles) —
            #    permanent, appliqué à TOUTE ouverture ultérieure du .gpkg
            #    (chargement immédiat, ajout manuel plus tard, autre poste…).
            #    On libère d'abord le sink pour forcer le flush du writer OGR
            #    (fichier complet sur disque) avant de le rouvrir en lecture.
            del sink
            self._embed_style_in_output(dest_id, context, feedback)

            outputs = {self.OUTPUT: dest_id}

            # --- segments d'axe de rue (sink optionnel) ------------------
            # QgsProcessingParameterFeatureSink(optional=True) est absent de
            # `parameters` (ou vaut None) si l'utilisateur ne l'a pas renseigne —
            # meme idiome que SUMMARY/UNGEOCODED (QgsProcessingParameterFileDestination
            # optional=True) deja dans ce fichier, adapte au sink.
            if parameters.get(self.OUTPUT_SEGMENTS):
                if not push_to_be:
                    feedback.pushInfo(
                        "OUTPUT_SEGMENTS : PUSH_TO_BE desactive — les segments ne "
                        "sont calcules qu'a partir de la base 'be', la couche "
                        "segments sera donc vide pour ce run."
                    )
                seg_sink, seg_dest = self.parameterAsSink(
                    parameters, self.OUTPUT_SEGMENTS, context,
                    _build_segment_output_fields(), QgsWkbTypes.LineString,
                    QgsCoordinateReferenceSystem(OUTPUT_CRS),
                )
                if seg_sink is None:
                    # Sortie optionnelle et best-effort (contrairement a OUTPUT) :
                    # un sink invalide ne doit jamais faire echouer tout le run —
                    # la resynchro en base 'be' a deja eu lieu independamment.
                    feedback.pushWarning(
                        self.invalidSinkError(parameters, self.OUTPUT_SEGMENTS)
                    )
                else:
                    try:
                        for half in fresh_segments:
                            geom = QgsGeometry.fromPolylineXY([
                                QgsPointXY(half.start_x, half.start_y),
                                QgsPointXY(half.end_x, half.end_y),
                            ])
                            feat = QgsFeature(_build_segment_output_fields())
                            feat.setGeometry(geom)
                            for name in ("point_a_intervention_id", "point_b_intervention_id",
                                         "half", "depth_category", "is_long", "length_m", "road_key"):
                                feat.setAttribute(name, getattr(half, name))
                            seg_sink.addFeature(feat, QgsFeatureSink.FastInsert)
                        outputs[self.OUTPUT_SEGMENTS] = seg_dest
                        # Post-traitement : même mécanisme que OUTPUT
                        # (_DepthLayerStyler), sur le style segments.
                        if context.willLoadLayerOnCompletion(seg_dest):
                            self._segments_styler = _SegmentsLayerStyler()
                            context.layersToLoadOnCompletion()[
                                seg_dest
                            ].setPostProcessor(self._segments_styler)
                    except Exception as exc:
                        feedback.pushWarning(
                            f"OUTPUT_SEGMENTS : erreur inattendue lors de "
                            f"l'ecriture ({exc}) — la resynchro en base 'be' reste "
                            "effective."
                        )

            # --- table de synthèse xlsx (optionnelle) -------------------
            if summary_path:
                written = self._write_summary_xlsx(
                    summary_path, by_place, postal_by_place,
                    openpyxl_module, ungeocoded, feedback,
                )
                if written:
                    outputs[self.SUMMARY] = summary_path
                    # Charge la table de synthèse comme couche (table) dans le
                    # projet, par défaut, comme la couche de points OUTPUT.
                    self._load_summary_layer(summary_path, context, feedback)

            # --- CSV des adresses non géocodées (optionnel) --------------
            if ungeocoded_path:
                written = self._write_ungeocoded_csv(
                    ungeocoded_path, ungeocoded, feedback
                )
                if written:
                    outputs[self.UNGEOCODED] = ungeocoded_path

            # --- message copiable des adresses non géocodées ------------
            feedback.pushInfo(build_ungeocoded_message(ungeocoded))
            if ungeocoded:
                feedback.pushInfo(
                    build_ungeocoded_email(ungeocoded, contact_email, n_ok)
                )
            return outputs

        # -- helpers d'instance ------------------------------------------
        def _embed_style_in_output(self, dest_id, context, feedback):
            """Enregistre le style profondeur DANS la base du GeoPackage de sortie.

            Rouvre la couche fraîchement écrite via
            :func:`QgsProcessingUtils.mapLayerFromString`, lui applique le style de
            référence (le ``.qml`` livré, via :func:`_apply_depth_style` — même
            source que le post-traitement live) puis appelle
            ``saveStyleToDatabase[V2]`` avec ``useAsDefault=True`` : le style est
            écrit dans la table native ``layer_styles`` du GeoPackage et QGIS
            l'applique automatiquement à toute ouverture future du fichier.

            Best-effort et NON bloquant : tout échec (sortie qui n'est pas un
            GeoPackage, provider sans stockage de style en base, couche non
            réouvrable ici…) est journalisé via ``feedback`` sans jamais faire
            échouer l'algorithme — le post-traitement reste le filet de secours.
            """
            try:
                layer = QgsProcessingUtils.mapLayerFromString(dest_id, context, True)
            except Exception as exc:  # pragma: no cover - défensif (hors QGIS réel)
                feedback.pushInfo(
                    f"Style non embarqué : couche de sortie introuvable ({exc})."
                )
                return
            if layer is None or not layer.isValid():
                feedback.pushInfo(
                    "Style non embarqué : couche de sortie non réouvrable ici "
                    "(le post-traitement reste le filet de secours)."
                )
                return
            try:
                _apply_depth_style(layer, feedback)
            except Exception as exc:  # pragma: no cover - défensif
                feedback.pushInfo(f"Style non embarqué : rendu non applicable ({exc}).")
                return

            name = "depth_category"
            description = "Style profondeur (vert/orange/rouge/gris)"
            # Appel V2/legacy + interprétation du retour : cf. _save_style_to_db
            # (partagé avec _sync_style_to_db).
            try:
                error = _save_style_to_db(layer, name, description)
            except Exception as exc:  # provider non-DB, verrou fichier… — non bloquant
                feedback.pushInfo(
                    "Style non embarqué : nécessite un GeoPackage en sortie "
                    f"(le stockage de style en base a échoué — {exc})."
                )
                return

            if error:
                feedback.pushInfo(
                    "Style non embarqué : nécessite un GeoPackage en sortie "
                    f"(détail : {error})."
                )
                return
            feedback.pushInfo(
                "Style « depth_category » embarqué dans le GeoPackage de sortie "
                "(table layer_styles, marqué par défaut) : il sera ré-appliqué à "
                "toute ouverture ultérieure du fichier."
            )

        def _copy_existing(
            self, existing_source, sink, fields, out_crs, feedback,
            by_place, postal_by_place,
        ):
            src_crs = existing_source.sourceCrs()
            xform = None
            if src_crs.isValid() and src_crs != out_crs:
                xform = QgsCoordinateTransform(src_crs, out_crs, QgsProject.instance())
            field_names = [fields.at(i).name() for i in range(fields.count())]
            ids: set[str] = set()
            geocoded_for_db: list[tuple[dict, "QgsPointXY"]] = []
            for feat in existing_source.getFeatures():
                new_feat = QgsFeature(fields)
                geom = feat.geometry()
                if xform is not None and geom is not None and not geom.isEmpty():
                    reprojected = QgsGeometry(geom)
                    reprojected.transform(xform)
                    new_feat.setGeometry(reprojected)
                else:
                    new_feat.setGeometry(geom)
                for name in field_names:
                    idx = feat.fields().indexOf(name)
                    if idx >= 0:
                        new_feat.setAttribute(name, feat.attribute(idx))
                sink.addFeature(new_feat, QgsFeatureSink.FastInsert)
                cat = new_feat["depth_category"]
                if cat:
                    # Points recopiés d'une couche déjà géocodée : ventilés
                    # sous leur VRAIE ville (déjà normalisée par un run
                    # précédent), comme les points fraîchement géocodés.
                    place_key = new_feat["place"] or UNKNOWN_PLACE_LABEL
                    by_place[place_key][str(cat)] += 1
                    if new_feat["postal_code"]:
                        postal_by_place[place_key].add(new_feat["postal_code"])
                idx = feat.fields().indexOf("intervention_id")
                if idx >= 0:
                    value = feat.attribute(idx)
                    if value not in (None, ""):
                        ids.add(str(value))
                        new_geom = new_feat.geometry()
                        has_all_fields = all(
                            feat.fields().indexOf(name) >= 0 for name in field_names
                        )
                        if has_all_fields and new_geom is not None and not new_geom.isEmpty():
                            # geometry.type() ne distingue pas Point de
                            # MultiPoint (les deux sont PointGeometry) ; seul
                            # asPoint() sait vraiment rejeter une geometrie non
                            # ponctuelle (ValueError). On capture plutot que
                            # de tester le type, pour ne jamais faire echouer
                            # tout le run sur une EXISTING_LAYER inattendue.
                            try:
                                point = new_geom.asPoint()
                            except ValueError:
                                feedback.pushWarning(
                                    f"Intervention {value} : geometrie non "
                                    "ponctuelle dans la couche existante, non "
                                    "poussee vers 'be' (copiee dans OUTPUT "
                                    "normalement)."
                                )
                            else:
                                # Ces interventions ne repassent jamais par la
                                # boucle de geocodage (cf. known_ids plus bas) :
                                # sans cet ajout elles ne rejoindraient jamais
                                # public.geofiber_asbuilt_depth_points,
                                # divergence permanente avec OUTPUT des qu'une
                                # couche existante est fournie (mode additif).
                                # Ne pousse que si la source a reellement les
                                # 10 champs attendus (pas seulement des
                                # valeurs non-nulles) : sinon un schema
                                # incomplet ecraserait de bonnes valeurs prod
                                # avec des NULL sur conflit.
                                values = {name: new_feat[name] for name in field_names}
                                geocoded_for_db.append((values, point))
            return ids, geocoded_for_db

        def _write_summary_xlsx(
            self, path, by_place, postal_by_place, openpyxl_module,
            ungeocoded, feedback
        ):
            """Écrit la table de synthèse ``.xlsx`` ventilée PAR VILLE.

            Trois feuilles :

            * **« Synthèse par ville »** (:data:`SUMMARY_PIVOT_SHEET_TITLE`) —
              matrice pivot : une ligne par ville (place normalisée, plus une
              ligne :data:`UNKNOWN_PLACE_LABEL` pour les points sans ville
              renseignée, si applicable), une colonne ``Code(s) postal(aux)``
              (codes postaux normalisés rencontrés pour cette ville, triés et
              joints par ``", "`` — cf. :func:`format_postal_codes`), une
              colonne par catégorie de profondeur (ordre
              :data:`DEPTH_SUMMARY_ORDER`), une colonne ``Total`` (somme de la
              ligne = total par ville) et une ligne ``Total`` en bas (somme de
              chaque colonne sur toutes les villes = total général).
            * **« Pourcentages »** (:data:`SUMMARY_PCT_SHEET_TITLE`) — rappel
              agrégé : nombre et pourcentage par catégorie sur le total général,
              toutes villes confondues.
            * **« Adresses non géocodées »** (:data:`SUMMARY_UNGEOCODED_SHEET_TITLE`) —
              le même texte que le message affiché dans le journal
              (:func:`build_ungeocoded_message`), une ligne de la feuille par
              ligne du message (pas un tableau à colonnes) : sélectionner la
              plage et la copier donne directement le texte prêt à envoyer.

            L'agrégation pivot est déléguée à la fonction pure
            :func:`build_summary_matrix` (testée hors QGIS) : source de vérité
            unique du total général. Best-effort et NON bloquant : un échec
            d'écriture est signalé via ``feedback`` sans faire échouer le
            géocodage (déjà réalisé, coûteux). Retourne ``True`` si le fichier a
            été écrit.
            """
            # openpyxl n'est chargé plus haut QUE si l'entrée contient des .xlsx ;
            # la synthèse est en .xlsx quel que soit le format d'entrée -> on
            # s'assure ici que le module est disponible (import paresseux réutilisé).
            if openpyxl_module is None:
                try:
                    openpyxl_module = _import_openpyxl(feedback)
                except QgsProcessingException as exc:
                    feedback.pushWarning(
                        f"Table de synthèse non écrite : openpyxl indisponible ({exc})."
                    )
                    return False

            matrix = build_summary_matrix(by_place, last_row_label=UNKNOWN_PLACE_LABEL)
            categories = matrix["categories"]
            totals = matrix["totals"]
            grand_total = matrix["grand_total"]
            labels = DEPTH_CATEGORY_LABELS

            def _pct(count):
                return round(100.0 * count / grand_total, 1) if grand_total else 0.0

            try:
                wb = openpyxl_module.Workbook()
                # -- Feuille 1 : matrice pivot ville × catégorie -------------
                ws = wb.active
                ws.title = SUMMARY_PIVOT_SHEET_TITLE
                ws.append(["Ville", "Code(s) postal(aux)", *categories, "Total"])
                for row in matrix["rows"]:
                    ws.append(
                        [row["group"], format_postal_codes(postal_by_place.get(row["group"], ()))]
                        + [row["counts"][cat] for cat in categories]
                        + [row["total"]]
                    )
                ws.append(
                    ["Total", ""] + [totals[cat] for cat in categories] + [grand_total]
                )
                # -- Feuille 2 : rappel agrégé nombre + % par catégorie ------
                ws_pct = wb.create_sheet(SUMMARY_PCT_SHEET_TITLE)
                ws_pct.append(["Catégorie", "Libellé", "Nombre", "Pourcentage (%)"])
                for cat in categories:
                    count = totals[cat]
                    ws_pct.append([cat, labels.get(cat, cat), count, _pct(count)])
                ws_pct.append(
                    ["Total", "", grand_total, 100.0 if grand_total else 0.0]
                )
                # -- Feuille 3 : texte du message (identique au journal) -----
                #    Une ligne de feuille par ligne de texte -- PAS un tableau
                #    a colonnes -- pour un copier-coller direct vers un mail
                #    (cf. build_ungeocoded_message, meme source que le journal).
                ws_ungeocoded = wb.create_sheet(SUMMARY_UNGEOCODED_SHEET_TITLE)
                for line in build_ungeocoded_message(ungeocoded).splitlines():
                    ws_ungeocoded.append([line])
                wb.save(path)
            except Exception as exc:  # chemin invalide, verrou fichier… — non bloquant
                feedback.pushWarning(
                    f"Table de synthèse non écrite ({path}) : {exc}."
                )
                return False

            n_places = len(matrix["rows"])
            feedback.pushInfo(
                f"Table de synthèse écrite ({grand_total} interventions, "
                f"{n_places} ville(s)) : {path}"
            )
            return True

        def _write_ungeocoded_csv(self, path, entries, feedback):
            """Écrit le CSV des adresses non géocodées (stdlib, sans dépendance).

            Une ligne par intervention non géocodée (:func:`build_ungeocoded_rows`) :
            identifiants source + requête Nominatim qui a échoué, pour permettre
            une retouche manuelle de l'adresse source (typo, ville tronquée,
            notation numéro/boîte…) avant un nouveau passage. Séparateur ``;`` +
            BOM UTF-8 (``utf-8-sig``) pour une ouverture directe correcte dans
            Excel FR/BE (accents, ß…), cohérent avec :func:`read_csv_rows` en
            lecture. Best-effort et NON bloquant : un échec d'écriture est
            journalisé via ``feedback`` sans faire échouer le géocodage (déjà
            réalisé, coûteux). Retourne ``True`` si le fichier a été écrit.
            """
            if not entries:
                feedback.pushInfo(
                    "Aucune adresse non géocodée : fichier CSV non écrit."
                )
                return False
            try:
                with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.writer(handle, delimiter=";")
                    writer.writerows(build_ungeocoded_rows(entries))
            except OSError as exc:
                feedback.pushWarning(
                    f"Adresses non géocodées non écrites ({path}) : {exc}."
                )
                return False
            feedback.pushInfo(
                f"{len(entries)} adresse(s) non géocodée(s) écrite(s) : {path}"
            )
            return True

        def _open_be_layer(self, schema: str, table: str, geom_column: str, wkb_type, feedback):
            """Ouvre schema.table via la connexion 'be', geometrie forcee.

            Ne fait PAS confiance a l'auto-detection de tableUri() sur cette
            connexion : cf. le commentaire ci-dessous sur l'incident constate
            en prod le 03/08 (geometrie silencieusement omise). Factorise
            depuis _upsert_geocoded_records ; reutilise par _sync_segments.
            """
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            be_connection = md.findConnection(BE_CONNECTION_NAME) if md else None
            if be_connection is None:
                feedback.pushWarning(
                    "Connexion QGIS 'be' introuvable — installez/activez "
                    "Constructel Bridge pour pousser les interventions en base. "
                    f"OUTPUT reste disponible, rien n'a ete ecrit dans "
                    f"{schema}.{table}."
                )
                return None
            try:
                base_uri = be_connection.tableUri(schema, table)
                # tableUri() seul ne suffit pas : observe en prod (03/08) qu'il
                # omet la colonne geometrique sur cette connexion, donnant une
                # couche NoGeometry (isValid()=True mais isSpatial()=False) qui
                # rejette toute ecriture avec "geometry type is not compatible
                # with the current layer" -- sur 501/501 interventions d'un
                # run reel. On force colonne/type/SRID via QgsDataSourceUri
                # plutot que de faire confiance a l'auto-detection.
                ds_uri = QgsDataSourceUri(base_uri)
                ds_uri.setGeometryColumn(geom_column)
                ds_uri.setSrid(OUTPUT_CRS.split(":")[-1])
                ds_uri.setWkbType(wkb_type)
                layer = QgsVectorLayer(ds_uri.uri(False), table, "postgres")
            except Exception as exc:
                feedback.pushWarning(
                    f"Connexion a {schema}.{table} via 'be' "
                    f"impossible ({exc}) — rien n'a ete ecrit en base."
                )
                return None
            if not layer.isValid() or not layer.isSpatial():
                feedback.pushWarning(
                    f"Couche {schema}.{table} invalide ou non "
                    "spatiale via la connexion 'be' — rien n'a ete ecrit en base."
                )
                return None
            return layer

        def _open_be_points_layer(self, feedback):
            return self._open_be_layer(
                BE_TABLE_SCHEMA, BE_TABLE_NAME, BE_GEOM_COLUMN, QgsWkbTypes.Point, feedback
            )

        def _open_be_nonspatial_layer(self, schema: str, table: str, feedback):
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            be_connection = md.findConnection(BE_CONNECTION_NAME) if md else None
            if be_connection is None:
                feedback.pushWarning(
                    f"Connexion QGIS 'be' introuvable — {schema}.{table} non accessible."
                )
                return None
            try:
                layer = QgsVectorLayer(be_connection.tableUri(schema, table), table, "postgres")
            except Exception as exc:
                feedback.pushWarning(f"Connexion a {schema}.{table} via 'be' impossible ({exc}).")
                return None
            if not layer.isValid():
                feedback.pushWarning(f"Couche {schema}.{table} invalide via 'be'.")
                return None
            return layer

        def _upsert_geocoded_records(self, records, feedback):
            """Upsert les interventions geocodees dans public.geofiber_asbuilt_depth_points via be.

            Best-effort ligne par ligne : la connexion be indisponible ou l'echec
            d'une ligne individuelle degradent (avertissement) sans jamais faire
            echouer le run — le geocodage/OUTPUT ont deja eu lieu et ne doivent
            pas etre perdus pour un probleme d'ecriture en base. Cf. spec
            docs/superpowers/specs/2026-08-03-geofiber-depth-upsert-design.md.
            """
            if not records:
                feedback.pushInfo("Base 'be' : aucune intervention geocodee a pousser.")
                return
            layer = self._open_be_layer(
                BE_TABLE_SCHEMA, BE_TABLE_NAME, BE_GEOM_COLUMN, QgsWkbTypes.Point, feedback
            )
            if layer is None:
                return
            if not layer.primaryKeyAttributes():
                feedback.pushWarning(
                    f"Couche {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} sans cle primaire "
                    "exploitable — ecriture impossible, rien n'a ete ecrit en base."
                )
                return

            fields = layer.fields()
            id_field = QgsExpression.quotedColumnRef("intervention_id")
            inserted = updated = failed = 0
            for values, point in records:
                intervention_id = values["intervention_id"]
                id_value = QgsExpression.quotedValue(intervention_id)
                request = QgsFeatureRequest()
                request.setFilterExpression(f"{id_field} = {id_value}")
                existing = list(layer.getFeatures(request))

                layer.startEditing()
                ok = False
                try:
                    if existing:
                        fid = existing[0].id()
                        attr_map = {
                            fields.indexOf(name): value
                            for name, value in values.items()
                            if name != "intervention_id"
                        }
                        staged = layer.changeAttributeValues(fid, attr_map)
                        staged = (
                            layer.changeGeometry(fid, QgsGeometry.fromPointXY(point))
                            and staged
                        )
                    else:
                        feat = QgsFeature(fields)
                        for name, value in values.items():
                            feat.setAttribute(name, value)
                        now = QDateTime.currentDateTimeUtc()
                        for ts_col in ("created_at", "updated_at"):
                            idx = fields.indexOf(ts_col)
                            if idx >= 0:
                                feat.setAttribute(idx, now)
                        feat.setGeometry(QgsGeometry.fromPointXY(point))
                        staged = layer.addFeature(feat)
                    ok = staged and layer.commitChanges()
                except Exception as exc:
                    feedback.reportError(
                        f"Echec upsert intervention {intervention_id} : {exc}",
                        fatalError=False,
                    )
                    ok = False

                if ok:
                    if existing:
                        updated += 1
                    else:
                        inserted += 1
                else:
                    failed += 1
                    for err in layer.commitErrors():
                        feedback.reportError(
                            f"Intervention {intervention_id} : {err}",
                            fatalError=False,
                        )
                    layer.rollBack()

            feedback.pushInfo(
                f"Base 'be' : {inserted} creee(s), {updated} mise(s) a jour, "
                f"{failed} echec(s) sur {len(records)} intervention(s) geocodee(s)."
            )

        def _upsert_ungeocoded_records(self, entries, feedback):
            """Upsert les adresses non geocodees dans public.geofiber_asbuilt_ungeocoded.

            ``entries`` : (InterventionRecord, query) — meme forme que
            build_ungeocoded_rows. Best-effort, meme politique que
            _upsert_geocoded_records : ne fait jamais echouer le run.
            """
            if not entries:
                feedback.pushInfo("Base 'be' : aucune adresse non geocodee a pousser.")
                return
            layer = self._open_be_nonspatial_layer(
                UNGEOCODED_TABLE_SCHEMA, UNGEOCODED_TABLE_NAME, feedback
            )
            if layer is None:
                return
            if not layer.primaryKeyAttributes():
                feedback.pushWarning(
                    f"Couche {UNGEOCODED_TABLE_SCHEMA}.{UNGEOCODED_TABLE_NAME} sans cle primaire "
                    "exploitable — ecriture impossible, rien n'a ete ecrit en base."
                )
                return

            fields = layer.fields()
            id_field = QgsExpression.quotedColumnRef("intervention_id")
            inserted = updated = failed = 0
            for rec, query in entries:
                values = {
                    "intervention_id": rec.intervention,
                    "work_order": rec.work_order,
                    "address_raw": rec.address,
                    "postal_code": rec.postal_code,
                    "place": rec.place,
                    "depth_raw": rec.depth_raw,
                    "geocode_query": query,
                    "source_message": rec.source_message,
                }
                id_value = QgsExpression.quotedValue(values["intervention_id"])
                request = QgsFeatureRequest()
                request.setFilterExpression(f"{id_field} = {id_value}")
                existing = list(layer.getFeatures(request))

                layer.startEditing()
                ok = False
                try:
                    if existing:
                        fid = existing[0].id()
                        attr_map = {
                            fields.indexOf(name): value
                            for name, value in values.items()
                            if name != "intervention_id"
                        }
                        ok = layer.changeAttributeValues(fid, attr_map)
                    else:
                        feat = QgsFeature(fields)
                        for name, value in values.items():
                            feat.setAttribute(name, value)
                        now = QDateTime.currentDateTimeUtc()
                        for ts_col in ("created_at", "updated_at"):
                            idx = fields.indexOf(ts_col)
                            if idx >= 0:
                                feat.setAttribute(idx, now)
                        ok = layer.addFeature(feat)
                    ok = ok and layer.commitChanges()
                except Exception as exc:
                    feedback.reportError(
                        f"Echec upsert non-geocode {values['intervention_id']} : {exc}",
                        fatalError=False,
                    )
                    ok = False

                if ok:
                    updated += 1 if existing else 0
                    inserted += 0 if existing else 1
                else:
                    failed += 1
                    for err in layer.commitErrors():
                        feedback.reportError(
                            f"Non-geocode {values['intervention_id']} : {err}",
                            fatalError=False,
                        )
                    layer.rollBack()

            feedback.pushInfo(
                f"Base 'be' (non-geocodes) : {inserted} creee(s), {updated} mise(s) a jour, "
                f"{failed} echec(s) sur {len(entries)}."
            )

        def _locate_points_on_road(self, rows, feedback):
            """Localise chaque ligne (dict avec intervention_id/depth_category/address_raw/x/y)
            sur son axe de rue via public.fn_asbuilt_locate_on_road (connexion 'be').

            Retourne (locations, road_extents, had_connection_error). Un point sans nom de
            rue extractible, ou sans troncon matchant, est silencieusement omis (pas une
            erreur — cf. spec). had_connection_error=True seulement sur un echec de
            connexion/permission (feedback.reportError), jamais sur une absence de match.
            """
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            be_connection = md.findConnection(BE_CONNECTION_NAME) if md else None
            if be_connection is None:
                feedback.pushWarning(
                    "Connexion QGIS 'be' introuvable — segments d'axe de rue non calcules."
                )
                return [], {}, True

            locations: list[RoadLocation] = []
            road_extents: dict[str, RoadExtent] = {}
            had_connection_error = False
            n_no_street = n_no_match = 0

            for row in rows:
                if feedback.isCanceled():
                    break
                street_name = extract_street_name(row["address_raw"])
                if not street_name:
                    n_no_street += 1
                    continue
                street_literal = QgsExpression.quotedValue(street_name)
                sql = (
                    "SELECT road_key, position_m, "
                    "ST_X(projected_point), ST_Y(projected_point), "
                    "road_length_m, ST_X(road_start), ST_Y(road_start), "
                    "ST_X(road_end), ST_Y(road_end) "
                    "FROM public.fn_asbuilt_locate_on_road("
                    f"ST_SetSRID(ST_MakePoint({row['x']!r}, {row['y']!r}), 31370), "
                    f"{street_literal})"
                )
                try:
                    result = be_connection.executeSql(sql)
                except Exception as exc:
                    feedback.reportError(
                        f"fn_asbuilt_locate_on_road indisponible pour "
                        f"{row['intervention_id']} : {exc}",
                        fatalError=False,
                    )
                    had_connection_error = True
                    # Fonction absente / droit refuse / connexion perdue : l'appel
                    # echouera a l'identique pour tous les points restants — inutile
                    # de journaliser une erreur par point. Une autre exception
                    # (propre a CE point) laisse la boucle continuer.
                    message = str(exc).lower()
                    if any(marker in message for marker in _LOCATE_FATAL_ERROR_MARKERS):
                        feedback.pushWarning(
                            "fn_asbuilt_locate_on_road inutilisable (fonction absente, "
                            "droit refuse ou connexion perdue) — localisation "
                            "interrompue pour les points restants."
                        )
                        break
                    continue
                if not result:
                    n_no_match += 1
                    continue  # aucun troncon nomme dans le rayon : omission normale
                (road_key, position_m, px, py,
                 road_length_m, sx, sy, ex, ey) = result[0]
                locations.append(RoadLocation(
                    intervention_id=row["intervention_id"],
                    depth_category=row["depth_category"],
                    road_key=road_key, position_m=float(position_m),
                    x=float(px), y=float(py),
                ))
                road_extents.setdefault(road_key, RoadExtent(
                    length_m=float(road_length_m),
                    start_x=float(sx), start_y=float(sy),
                    end_x=float(ex), end_y=float(ey),
                ))

            feedback.pushInfo(
                f"Segments : {len(locations)} point(s) localise(s) sur un axe de rue "
                f"sur {len(rows)} fourni(s) ({n_no_street} sans nom de rue "
                f"extractible de l'adresse, {n_no_match} sans troncon nomme "
                "correspondant a proximite)."
            )
            return locations, road_extents, had_connection_error

        def _sync_segments(self, feedback):
            """Recalcule et resynchronise integralement les segments d'axe de rue.

            Relit TOUT public.geofiber_asbuilt_depth_points (pas seulement le lot de
            ce run — cf. spec §4 "synchro complete"), localise chaque point valide sur
            son axe de rue, reconstruit les moities via build_segment_halves, puis
            upsert + supprime les orphelins dans public.geofiber_asbuilt_depth_segments.
            Best-effort : si _locate_points_on_road signale une erreur de connexion,
            ou si la lecture des points ne peut etre verifiee complete (count(*)
            exact divergent ou en echec), AUCUNE suppression n'est jouee (cf. Review
            Focus - ne pas purger sur un recalcul non fiable), seul l'upsert du lot
            obtenu est tente. Annulation utilisateur : les boucles d'upsert et de
            purge s'arretent (le drapeau d'annulation etant persistant, une
            annulation pendant la localisation n'entraine aucune purge).

            Ordre de lecture des points DETERMINISTE (tri par intervention_id avant
            construction de ``rows``) : l'ordre d'iteration QGIS sur une couche
            postgres n'est PAS garanti stable d'un run a l'autre, et
            build_segment_halves depart les ex-aequo de position_m par ordre
            d'entree -- sans ce tri, deux runs sans changement de donnees pourraient
            reordonner les paires et casser l'idempotence (cle a/b differente d'un
            run a l'autre pour les memes points).

            Un SegmentHalf de longueur nulle (deux points geocodes au meme endroit,
            ou un point situe exactement sur un bout de route) N'EST PAS filtre :
            c'est une geometrie LineString valide (PostGIS l'accepte), un cas de
            donnees legitime bien que rare -- pas une erreur.
            """
            points_layer = self._open_be_points_layer(feedback)
            if points_layer is None:
                return []

            features = sorted(
                points_layer.getFeatures(), key=lambda f: f["intervention_id"] or ""
            )
            total_features_seen = 0
            rows = []
            for feat in features:
                total_features_seen += 1
                category = feat["depth_category"]
                if category == "manquante" or not category:
                    continue
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                pt = geom.asPoint()
                rows.append({
                    "intervention_id": feat["intervention_id"],
                    "depth_category": category,
                    "address_raw": feat["address_raw"],
                    "x": pt.x(), "y": pt.y(),
                })

            # Detection d'une lecture PARTIELLE silencieuse : une QgsVectorLayer
            # postgres ne leve PAS d'exception sur une erreur de lecture en cours
            # de route (permission, connexion coupee...) -- getFeatures() se
            # contente de rendre moins d'entites que prevu. On compare donc au
            # nombre EXACT de lignes, obtenu par un count(*) SQL direct : PAS
            # points_layer.featureCount(), car la connexion 'be' est declaree
            # avec estimatedmetadata=true -> featureCount() renvoie l'estimation
            # du planificateur (pg_class.reltuples), perimee juste apres les
            # upserts de CE run, ce qui ferait passer quasiment chaque run
            # ecrivant des points pour une lecture partielle. S'il diverge du
            # nombre reellement itere, la lecture est suspecte et ne doit PAS
            # etre traitee comme un filtrage legitime (sans quoi `rows`/`fresh`
            # se retrouveraient tronques et to_delete marquerait a tort tous les
            # segments manquants comme orphelins -- purge de masse silencieuse).
            # Un count(*) en echec (expected_count None) desactive AUSSI la purge :
            # sans reference fiable, on ne peut pas exclure une lecture partielle.
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            be_connection = md.findConnection(BE_CONNECTION_NAME) if md else None
            try:
                count_result = be_connection.executeSql(
                    f"SELECT count(*) FROM {BE_TABLE_SCHEMA}.{BE_TABLE_NAME}"
                )
                expected_count = int(count_result[0][0]) if count_result else None
            except Exception:
                expected_count = None
            partial_read = (
                expected_count is None or total_features_seen != expected_count
            )
            if expected_count is None:
                feedback.pushWarning(
                    f"Comptage exact de {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} impossible "
                    "— lecture des points non verifiable."
                )
            elif partial_read:
                feedback.pushWarning(
                    f"Lecture de {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} suspectee "
                    f"incomplete ({total_features_seen}/{expected_count} entite(s) "
                    "lue(s) — echec silencieux de getFeatures() possible)."
                )

            locations, road_extents, had_connection_error = self._locate_points_on_road(
                rows, feedback
            )
            fresh = build_segment_halves(locations, road_extents)

            segments_layer = self._open_be_layer(
                SEGMENTS_TABLE_SCHEMA, SEGMENTS_TABLE_NAME,
                BE_GEOM_COLUMN, QgsWkbTypes.LineString, feedback,
            )
            if segments_layer is None:
                return fresh
            if not segments_layer.primaryKeyAttributes():
                feedback.pushWarning(
                    f"Couche {SEGMENTS_TABLE_SCHEMA}.{SEGMENTS_TABLE_NAME} sans cle "
                    "primaire exploitable — ecriture impossible, rien n'a ete ecrit "
                    "en base."
                )
                return fresh

            # Un seul parcours de la table segments : cle -> fid, reutilise tel quel
            # par les boucles d'upsert et de purge (pas de re-requete par cle).
            existing_fids = {}
            for feat in segments_layer.getFeatures():
                existing_fids.setdefault((
                    feat["point_a_intervention_id"],
                    feat["point_b_intervention_id"],
                    feat["half"],
                ), feat.id())
            to_upsert, to_delete = plan_segment_sync(fresh, set(existing_fids))
            if had_connection_error or partial_read:
                to_delete = []
                feedback.pushWarning(
                    "Localisation et/ou lecture des points partiellement en "
                    "echec — purge des segments obsoletes desactivee par "
                    "prudence pour ce run."
                )

            fields = segments_layer.fields()
            inserted = updated = failed = 0
            n_upsert = max(len(to_upsert), 1)
            for i, half in enumerate(to_upsert):
                if feedback.isCanceled():
                    break
                feedback.setProgress(int(100 * i / n_upsert))
                key_label = (
                    f"({half.point_a_intervention_id}, "
                    f"{half.point_b_intervention_id}, {half.half})"
                )
                existing_fid = existing_fids.get((
                    half.point_a_intervention_id,
                    half.point_b_intervention_id,
                    half.half,
                ))
                existing = existing_fid is not None
                geom = QgsGeometry.fromPolylineXY([
                    QgsPointXY(half.start_x, half.start_y),
                    QgsPointXY(half.end_x, half.end_y),
                ])
                values = {
                    "point_a_intervention_id": half.point_a_intervention_id,
                    "point_b_intervention_id": half.point_b_intervention_id,
                    "half": half.half,
                    "depth_category": half.depth_category,
                    "is_long": half.is_long,
                    "length_m": half.length_m,
                    "road_key": half.road_key,
                }
                segments_layer.startEditing()
                ok = False
                try:
                    if existing:
                        attr_map = {
                            fields.indexOf(name): val for name, val in values.items()
                        }
                        ok = segments_layer.changeAttributeValues(existing_fid, attr_map)
                        ok = segments_layer.changeGeometry(existing_fid, geom) and ok
                    else:
                        feat = QgsFeature(fields)
                        for name, val in values.items():
                            feat.setAttribute(name, val)
                        now = QDateTime.currentDateTimeUtc()
                        for ts_col in ("created_at", "updated_at"):
                            idx = fields.indexOf(ts_col)
                            if idx >= 0:
                                feat.setAttribute(idx, now)
                        feat.setGeometry(geom)
                        ok = segments_layer.addFeature(feat)
                    ok = ok and segments_layer.commitChanges()
                except Exception as exc:
                    feedback.reportError(
                        f"Echec upsert segment {key_label} : {exc}", fatalError=False
                    )
                    ok = False
                if ok:
                    updated += 1 if existing else 0
                    inserted += 0 if existing else 1
                else:
                    failed += 1
                    for err in segments_layer.commitErrors():
                        feedback.reportError(
                            f"Segment {key_label} : {err}", fatalError=False
                        )
                    segments_layer.rollBack()

            deleted = failed_delete = 0
            for key in to_delete:
                if feedback.isCanceled():
                    break
                key_label = f"({key[0]}, {key[1]}, {key[2]})"
                segments_layer.startEditing()
                if (
                    segments_layer.deleteFeatures([existing_fids[key]])
                    and segments_layer.commitChanges()
                ):
                    deleted += 1
                else:
                    failed_delete += 1
                    for err in segments_layer.commitErrors():
                        feedback.reportError(
                            f"Suppression segment {key_label} : {err}", fatalError=False
                        )
                    segments_layer.rollBack()

            feedback.pushInfo(
                f"Segments : {inserted} creee(s), {updated} mise(s) a jour, "
                f"{deleted} supprimee(s) (orphelins), {failed} echec(s) upsert, "
                f"{failed_delete} echec(s) suppression."
            )
            _apply_segments_style(segments_layer, feedback)
            _sync_style_to_db(
                segments_layer, "depth_segments",
                "Style segments d'axe de rue As-Built — géré par geocode_asbuilt_depth, ne pas éditer manuellement.",
                feedback,
            )
            return fresh

        def _load_summary_layer(self, summary_path, context, feedback):
            """Charge la table de synthèse xlsx comme couche (table) dans le projet.

            La feuille pivot :data:`SUMMARY_PIVOT_SHEET_TITLE` est ouverte via le
            provider OGR (couche NON spatiale : visible dans le panneau des
            couches, table attributaire ouvrable) et enregistrée pour chargement
            automatique en fin d'exécution, comme la couche de points OUTPUT.

            Best-effort et NON bloquant : si le pilote OGR XLSX est absent, la
            feuille illisible ou aucun projet cible disponible (exécution
            headless), on journalise via ``feedback`` sans faire échouer
            l'algorithme — le fichier xlsx reste écrit sur disque.
            """
            project = context.project()
            if project is None:  # exécution sans projet cible -> rien à charger
                feedback.pushInfo(
                    "Table de synthèse non chargée en couche : aucun projet cible "
                    "(le fichier xlsx reste disponible sur disque)."
                )
                return
            uri = f"{summary_path}|layername={SUMMARY_PIVOT_SHEET_TITLE}"
            layer_name = "Synthèse profondeur (table)"
            try:
                layer = QgsVectorLayer(uri, layer_name, "ogr")
            except Exception as exc:  # pragma: no cover - défensif (hors QGIS réel)
                feedback.pushInfo(
                    f"Table de synthèse non chargée en couche ({exc})."
                )
                return
            if layer is None or not layer.isValid():
                feedback.pushInfo(
                    "Table de synthèse non chargée en couche : feuille xlsx non "
                    "lisible par le pilote OGR (le fichier reste sur disque)."
                )
                return
            # Le layer store temporaire prend la propriété ; addLayerToLoadOnCompletion
            # transfère la couche vers le projet en fin d'exécution (même mécanisme
            # que la couche de points OUTPUT). outputName vide -> couche additive
            # non liée à la sortie fichier SUMMARY déjà déclarée.
            context.temporaryLayerStore().addMapLayer(layer)
            context.addLayerToLoadOnCompletion(
                layer.id(),
                QgsProcessingContext.LayerDetails(layer_name, project, ""),
            )
            feedback.pushInfo(
                f"Table de synthèse chargée comme couche (table) : « {layer_name} »."
            )
