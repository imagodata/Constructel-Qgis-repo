# -*- coding: utf-8 -*-
"""Géocoder rapport As-Built (.msg Outlook) par profondeur de pose.

Algorithme QGIS Processing autonome (partageable via *QGIS Resource Sharing*).
Il lit les rapports périodiques « To update Go Fiber As-Built » exportés aux
formats Outlook ``.msg`` **ou** tableur ``.xlsx`` / ``.csv`` (même tableau
WorkOrder / Intervention / Address / PostalCode / Place / profondeur), géocode
les adresses via Nominatim (OpenStreetMap) et pousse les points EPSG:31370,
catégorisés par profondeur de pose (feu tricolore + gris « manquante »), dans
la base PostgreSQL de la connexion QGIS ``be`` (points + segments d'axe de
rue) ; aucune couche temporaire n'est produite, les deux couches de la base
sont ajoutées au projet si elles n'y sont pas déjà.

Le fichier est volontairement mono-fichier (contrainte Resource Sharing : un
script Processing = un ``.py`` déposé tel quel). Toute la logique de parsing /
normalisation / dédoublonnage / construction de requête est factorisée dans des
fonctions PURES, sans dépendance PyQGIS, testables via pytest. La classe
``QgsProcessingAlgorithm`` n'est qu'un fin wrapper d'orchestration.

Dépendances runtime (auto-installées via pip au besoin) : ``extract-msg``
(lecture ``.msg``) et ``openpyxl`` (lecture ``.xlsx``). Les ``.csv`` n'utilisent
que la stdlib. Politique Nominatim : 1 req/s max + User-Agent identifiant ;
renseigner ``CONTACT_EMAIL`` est fortement recommandé.

Segments d'axe de rue : localisation via ``public.fn_asbuilt_locate_on_road``
(table ``ref.osm_roads``) puis, en repli pour les points non couverts,
extraction OSM via l'API Overpass (stdlib ``urllib``, lecture seule) et
localisation en Python pur (:func:`locate_on_ways`). Chaque point est rangé
d'un côté de la route ; les segments sont appariés par côté et dessinés
décalés selon le type de voie (:data:`HIGHWAY_OFFSET_M`).
"""

import csv
import dataclasses
import difflib
import glob
import hashlib
import io
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional

# ---------------------------------------------------------------------------
# Imports PyQGIS — encapsulés pour que les fonctions pures ci-dessous restent
# importables (et testables via pytest) dans un Python standard sans QGIS.
# ---------------------------------------------------------------------------
try:
    from qgis.core import (
        Qgis,
        QgsApplication,
        QgsCategorizedSymbolRenderer,
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsDataSourceUri,
        QgsExpression,
        QgsFeature,
        QgsFeatureRequest,
        QgsGeometry,
        QgsPointXY,
        QgsProcessingAlgorithm,
        QgsProcessingContext,
        QgsProcessingException,
        QgsProcessingLayerPostProcessorInterface,
        QgsProcessingParameterBoolean,
        QgsProcessingParameterDefinition,
        QgsProcessingParameterFile,
        QgsProcessingParameterString,
        QgsProject,
        QgsProviderRegistry,
        QgsRendererCategory,
        QgsSymbol,
        QgsVectorLayer,
        QgsWkbTypes,
    )
    from qgis.PyQt.QtCore import QCoreApplication, QDateTime
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

# Libellés lisibles de chaque catégorie (bornés par les seuils fixes ci-dessus).
# Source UNIQUE des libellés du rendu de repli (_build_depth_renderer /
# _apply_segments_style). Le .qml livré (style/depth_category.qml) porte
# directement ces mêmes libellés en dur — plus de réalignement à l'exécution.
DEPTH_CATEGORY_LABELS = {
    "manquante": "Manquante — non mesurée",
    "rouge": f"Rouge — non conforme (< {THRESHOLD_ORANGE_CM:g} cm)",
    "orange": f"Orange — limite ({THRESHOLD_ORANGE_CM:g}–{THRESHOLD_VERT_CM:g} cm)",
    "vert": f"Vert — conforme (≥ {THRESHOLD_VERT_CM:g} cm)",
}

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
    du rapport source côté appelant, cf. ``_build_attribute_values``).
    """

    lat: float
    lon: float
    postcode: str = ""
    city: str = ""
    # Métadonnées OSM du résultat (même réponse, addressdetails=1 — aucun appel
    # supplémentaire), gardées EN MÉMOIRE pour le run afin de sécuriser le
    # rattachement du point à son axe de rue (cf. assess_attachment).
    road: str = ""          # nom de rue canonique OSM (address.road, sinon pedestrian…)
    osm_type: str = ""      # node / way / relation
    osm_id: int = 0
    osm_class: str = ""     # class : highway, building, place, boundary…
    osm_kind: str = ""      # type : residential, house, village…
    addresstype: str = ""
    importance: float = 0.0
    precision: str = ""     # house / street / locality (cf. nominatim_precision)


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
# Code postal SUIVI de la localité, sans virgule : « … 175 4780 Sankt Vith »
# (run réel du 29/09 : empêchait aussi la déduplication « X/X 175 »).
_TRAILING_POSTAL_LOCALITY_RE = re.compile(r"^(.*?[^\W\d_].*?)\s+\d{4}\s+[^\d,/]+$")
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
       ne different pas par ce seul artefact), puis retrait d'un code postal
       SUIVI de la localite en fin d'adresse (« … 175 4780 Sankt Vith ») ;
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
    # « … 175 4780 Sankt Vith » : code postal + localité retirés AVANT la
    # déduplication, sinon le dernier segment « X 175 4780 Sankt Vith » ne
    # ressemble plus aux précédents.
    match = _TRAILING_POSTAL_LOCALITY_RE.match(text)
    if match:
        text = match.group(1)
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


def _record_completeness(rec: InterventionRecord) -> int:
    """Nombre de champs exploitables d'une ligne (cf. dedupe_records)."""
    return (
        sum(bool((value or "").strip()) for value in (
            rec.work_order, rec.address, rec.postal_code, rec.place,
        ))
        + (parse_depth_cm(rec.depth_raw) is not None)
    )


def dedupe_records(records: list[InterventionRecord]) -> list[InterventionRecord]:
    """Dédoublonnage du lot par identifiant d'intervention : UNE ligne par clé.

    Couvre « même intervention répétée 3× dans un message » comme « même
    intervention présente dans plusieurs fichiers du dossier ». Règle
    DÉTERMINISTE pour choisir la ligne retenue :

    1. la plus COMPLÈTE (:func:`_record_completeness` : WorkOrder, adresse,
       code postal, localité non vides + profondeur interprétable) ;
    2. à complétude égale, la DERNIÈRE occurrence dans l'ordre de lecture —
       fichiers triés par chemin (:func:`_collect_input_files`) puis ordre
       des lignes : un rapport plus récent nommé par date l'emporte.

    L'ordre de sortie suit la PREMIÈRE apparition de chaque clé (stable).
    Les lignes sans identifiant d'intervention exploitable sont écartées
    (parasites). Fonction PURE.
    """
    best: dict[str, InterventionRecord] = {}
    order: list[str] = []
    for rec in records:
        key = (rec.intervention or "").strip()
        if not key:
            continue
        if key not in best:
            order.append(key)
            best[key] = rec
        elif _record_completeness(rec) >= _record_completeness(best[key]):
            best[key] = rec
    return [best[key] for key in order]


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
    structured: Optional[dict] = None,
) -> Optional[NominatimHit]:
    """Géocode une requête -> :class:`NominatimHit` ou ``None`` si introuvable.

    ``structured`` (cf. :func:`build_structured_params`) : requête STRUCTURÉE
    (street/postalcode/city/country) à la place du texte libre ``q``.
    Lève :class:`NominatimBlockedError` sur 403/429 (rate-limit / blocage) afin
    d'arrêter proprement plutôt que de marquer silencieusement tout en échec.
    ``addressdetails=1`` ajoute le détail d'adresse structuré (postcode,
    ville) à la MÊME requête/réponse — aucun appel réseau supplémentaire.
    """
    params = {
        "format": "json", "limit": "1", "countrycodes": "be",
        "addressdetails": "1",
    }
    if structured:
        params.update(structured)
    else:
        params["q"] = query
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
    return parse_nominatim_result(first, lat, lon)


# Clés d'adresse Nominatim portant le nom de la VOIE, par ordre de préférence.
_NOMINATIM_ROAD_KEYS = (
    "road", "pedestrian", "residential", "footway", "path", "cycleway",
    "living_street", "service", "square", "place",
)


def nominatim_precision(result) -> str:
    """Précision d'un résultat Nominatim : 'house', 'street' ou 'locality'.

    * house : bâtiment / adresse (class building, type house, addresstype
      house|building, ou numéro de maison dans le détail d'adresse) ;
    * street : la voie elle-même (class highway, addresstype road) — le
      point est quelque part sur la rue, pas devant la maison ;
    * locality : commune, village, code postal, quartier… — point au centre
      d'une zone : AUCUN rattachement fiable à un axe. Fonction PURE.
    """
    if not isinstance(result, dict):
        return "locality"
    osm_class = str(result.get("class") or "")
    kind = str(result.get("type") or "")
    addresstype = str(result.get("addresstype") or "")
    address = result.get("address") if isinstance(result.get("address"), dict) else {}
    if (
        osm_class == "building" or kind == "house" or addresstype in ("house", "building")
        or address.get("house_number")
    ):
        return "house"
    if osm_class == "highway" or addresstype in ("road", "street"):
        return "street"
    return "locality"


def parse_nominatim_result(result, lat, lon) -> "NominatimHit":
    """Construit le :class:`NominatimHit` complet (lieu + métadonnées OSM). PURE."""
    postcode, city = extract_nominatim_place(result)
    address = result.get("address") if isinstance(result.get("address"), dict) else {}
    road = ""
    for key in _NOMINATIM_ROAD_KEYS:
        if address.get(key):
            road = str(address[key]).strip()
            break
    try:
        osm_id = int(result.get("osm_id") or 0)
    except (TypeError, ValueError):
        osm_id = 0
    try:
        importance = float(result.get("importance") or 0.0)
    except (TypeError, ValueError):
        importance = 0.0
    return NominatimHit(
        lat=lat, lon=lon, postcode=postcode, city=city, road=road,
        osm_type=str(result.get("osm_type") or ""), osm_id=osm_id,
        osm_class=str(result.get("class") or ""), osm_kind=str(result.get("type") or ""),
        addresstype=str(result.get("addresstype") or ""), importance=importance,
        precision=nominatim_precision(result),
    )


def reference_street_names(address_street, hit=None) -> tuple:
    """Noms de rue de RÉFÉRENCE d'un point, par ordre de confiance (dédoublonnés).

    Nom canonique OSM renvoyé par Nominatim (``hit.road``) d'abord, puis le
    nom extrait de l'adresse brute (variante) ; deux noms identiques après
    normalisation n'en font qu'un. Fonction PURE.
    """
    names = []
    for name in ((hit.road if hit is not None else ""), address_street):
        if name and normalize_street_name(name) not in {normalize_street_name(n) for n in names}:
            names.append(name)
    return tuple(names)


def postal_mismatch(record_postal, hit) -> bool:
    """Code postal de l'adresse différent de celui renvoyé par Nominatim au point ?"""
    mine = extract_postal4(record_postal)
    theirs = extract_postal4(hit.postcode if hit is not None else "")
    return bool(mine and theirs and mine != theirs)


def build_structured_params(address, postal_code, place, country="Belgium"):
    """Paramètres de requête Nominatim STRUCTURÉE, ou ``None`` si trop incomplets.

    ``street`` = adresse (numéro + rue, notation belge acceptée), ``postalcode``
    = 4 chiffres (du champ ou de l'adresse), ``city`` = localité,
    ``country``. Il faut une adresse ET au moins le code postal ou la localité,
    sinon la requête libre (``q``) est plus sûre. Fonction PURE.
    """
    street = fix_szett_artifact((address or "").strip()).strip()
    postal4 = extract_postal4(postal_code) or extract_postal4(street) or ""
    if postal4 and street.endswith(postal4):
        street = street[: -len(postal4)].rstrip(" ,")
    city = (place or "").strip()
    if not street or not (postal4 or city):
        return None
    params = {"street": street, "country": country}
    if postal4:
        params["postalcode"] = postal4
    if city:
        params["city"] = city
    return params


def describe_structured(params) -> str:
    """Trace lisible d'une requête structurée (journal, colonne geocode_query)."""
    return "; ".join(
        f"{key}={params[key]}" for key in ("street", "postalcode", "city", "country")
        if params.get(key)
    )


def in_belgium_wgs84(lat, lon) -> bool:
    """Résultat Nominatim plausible pour la Belgique (lat 49,4–51,6 ; lon 2,5–6,5) ?"""
    try:
        return 49.4 <= float(lat) <= 51.6 and 2.5 <= float(lon) <= 6.5
    except (TypeError, ValueError):
        return False


def geocode_with_dedup_fallback(
    address: str,
    postal_code: str,
    place: str,
    user_agent: str,
    geocode_fn=nominatim_geocode,
    sleep_fn=None,
    country: str = "Belgium",
) -> tuple[Optional[NominatimHit], str, bool]:
    """Géocode une adresse : requête STRUCTURÉE, puis texte libre, puis repli dédupliqué.

    0. **Requête structurée** (:func:`build_structured_params` : street,
       postalcode, city, country) quand les champs le permettent ; ``geocode_fn``
       est alors appelée avec ``structured=params``. Échec -> étapes
       suivantes (``sleep_fn`` avant l'appel suivant : 1 req/s).

    Puis, comportement historique — renvoie ``(hit, query, used_fallback)`` :

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
    structured = build_structured_params(address, postal_code, place, country=country)
    if structured is not None:
        label = describe_structured(structured)
        hit = geocode_fn(label, user_agent, structured=structured)
        if hit is not None:
            return hit, label, False
        if sleep_fn is not None:
            sleep_fn()  # cadence Nominatim : 1 req/s avant l'appel suivant
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
# rendu profondeur, appliquée par le script lui-même (couche de la base 'be'
# ajoutée au projet ET style par défaut synchronisé en base), et applicable à
# la main comme filet.
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


def build_ungeocoded_message(entries) -> str:
    """Message compact, pret a copier-coller, listant les adresses non geocodees.

    ``entries`` : iterable de (InterventionRecord, query), ``query`` etant la
    requete Nominatim en echec. Affiche dans le journal du run. Fonction pure,
    testable hors QGIS.
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

    Aucune dépendance PyQGIS — valeurs de l'upsert vers
    ``public.geofiber_asbuilt_depth_points`` (connexion ``be``).
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


# Segment de BOUT DE RUE (au-delà du premier / dernier point d'une chaîne,
# aucun point adjacent) : PETIT segment de cette longueur, mesurée le long de
# l'axe depuis le point projeté vers l'extrémité de l'axe (ou jusqu'à elle si
# elle est plus proche). Un point isolé donne deux petits segments contigus
# (ROAD_END_STUB_M de chaque côté, centrés sur lui) ; plus court que
# LONG_SEGMENT_THRESHOLD_M -> trait plein. Décision utilisateur du 29/09 :
# auparavant le bout allait jusqu'à l'extrémité de l'axe (un point isolé
# colorait ≈ 2 km de route).
ROAD_END_STUB_M = 25.0
# Paire de points consécutifs au-delà de cette distance : conservée, mais
# signalée au journal (interpolation sur une très longue distance).
VERY_LONG_PAIR_M = 500.0
LONG_SEGMENT_THRESHOLD_M = 100.0
ROAD_START_SENTINEL = "__ROAD_START__"
ROAD_END_SENTINEL = "__ROAD_END__"

# Côté de la route d'un point, relatif au SENS de l'axe fusionné (sens des
# position_m croissantes) : 'L' = à gauche, 'R' = à droite. CONVENTION : un
# point situé sur l'axe (distance au point projeté < SIDE_ON_AXIS_TOLERANCE_M)
# est rangé à droite ('R').
SIDE_LEFT = "L"
SIDE_RIGHT = "R"
SIDE_ON_AXIS_TOLERANCE_M = 0.01

# Décalage latéral (m) des segments dessinés, par type de voie OSM (tag
# ``highway``) : chaque segment est translaté perpendiculairement vers le côté
# de son point, pour séparer visuellement les deux trottoirs. Les ``*_link``
# (bretelles) prennent la valeur de leur voie mère. Constantes modifiables.
HIGHWAY_OFFSET_M = {
    "motorway": 8.0,
    "trunk": 8.0,
    "primary": 6.0,
    "secondary": 5.0,
    "tertiary": 4.0,
    "residential": 3.0,
    "unclassified": 3.0,
    "living_street": 3.0,
    "service": 2.0,
    "track": 2.0,
    "path": 2.0,
    "pedestrian": 2.0,
}
DEFAULT_HIGHWAY_OFFSET_M = 3.0

# Paramètres de la localisation PAR NOM (base et Overpass). Run réel du 29/09 :
# les points géocodés (numéro de maison) sont souvent en RETRAIT de la rue de
# 30 à 50 m, et les rues sont coupées en tronçons non raccordés à 1 m près ->
# rayon élargi, raccord élargi, ambiguïté entre homonymes seulement quand leurs
# distances sont comparables.
# * LOCATE_RADIUS_M : rayon de recherche d'une voie de MÊME NOM (base via le
#   paramètre p_search_radius de fn_asbuilt_locate_on_road, et Overpass) ;
# * LOW_CONFIDENCE_DISTANCE_M : au-delà, rattachement ASSUMÉ mais marqué « faible
#   confiance » (journal + compteur), pas rejeté ;
# * ROAD_JOIN_TOLERANCE_M : raccord des tronçons de même nom (rues coupées au
#   carrefour), composante bornée à ROAD_COMPONENT_MAX_WAYS ;
# * Deux composantes homonymes NON connectées (rue coupée par un tronçon d'un
#   autre nom, rond-point, chaussées séparées, sens uniques…) : AMBIGU
#   seulement en QUASI-ÉGALITÉ (2e à moins de COMPONENT_TIE_GAP_M de plus ET
#   rapport < COMPONENT_TIE_RATIO) ; sinon la plus proche l'emporte, marquée
#   faible confiance si la marge est < COMPONENT_LOW_CONF_GAP_M. Règle
#   historique (écart < 15 m OU rapport < 1,5) conservée seulement quand les
#   DEUX composantes sont à plus de COMPONENT_FAR_M (run réel du 29/09 : 52
#   « ambigus » dont des voies à 10–22 m).
LOCATE_RADIUS_M = 150.0
LOCATE_RADIUS_MAX_M = 200.0
LOW_CONFIDENCE_DISTANCE_M = 50.0
ROAD_JOIN_TOLERANCE_M = 12.0
# Garde d'invariant : la ligne d'axe retenue pour un point ne peut pas être
# plus loin de lui que la voie germe + AXIS_GUARD_M (m).
AXIS_GUARD_M = 10.0
COMPONENT_AMBIGUITY_GAP_M = 15.0
COMPONENT_AMBIGUITY_RATIO = 1.5
COMPONENT_TIE_GAP_M = 5.0
COMPONENT_TIE_RATIO = 1.15
COMPONENT_LOW_CONF_GAP_M = 15.0
COMPONENT_FAR_M = 40.0
# Nom APPROCHANT (voie au nom voisin : « Linden-Allee » pour « Lindenallee »)
# : ratio de similarité minimal des formes compactées, distance maximale à la
# voie, et marge nette : refusé si une voie d'un autre nom est plus proche de
# plus de FUZZY_NAME_MARGIN_M. Rattachement toujours marqué faible confiance.
FUZZY_NAME_RATIO = 0.85
FUZZY_NAME_MAX_DISTANCE_M = 40.0
FUZZY_NAME_MARGIN_M = 5.0
# Repli par coordonnées : une voie portant un nom de RÉFÉRENCE du point (nom
# canonique Nominatim ou nom nettoyé de l'adresse) est retenue jusqu'à ce
# plafond, avant la plus proche voie carrossable.
COORD_PREFERRED_NAME_RADIUS_M = 80.0
ROAD_COMPONENT_MAX_WAYS = 500

# Extraction OSM de repli via l'API Overpass (les voies obtenues peuvent
# alimenter ref.osm_roads via fn_asbuilt_store_osm_ways, cf. _store_osm_ways).
# Requêtes LÉGÈRES : filtrées par NOMS de rue (ceux des
# adresses des points à localiser) dans une emprise serrée — une requête sur
# tout le réseau d'une grande emprise a été mesurée en 504/time-out (run réel du
# 29/09). Le serveur public répond AU HASARD OK / 504 / 429 à une même requête
# (limitation de débit : 2 à 4 « slots ») : on réessaie donc généreusement sur
# le même miroir avant de passer au suivant.
# Miroirs vérifiés le 29/09 depuis l'extérieur : overpass-api.de (OK / 504 /
# SSL EOF selon les appels) et overpass.openstreetmap.fr (OK 0,2–0,4 s).
# ÉCARTÉS : overpass.osm.ch (extrait SUISSE seulement : réponse vide pour la
# Belgique, qui serait prise pour « aucune voie » et mise en cache !),
# maps.mail.ru, overpass.kumi.systems et overpass.private.coffee (délai dépassé
# à chaque essai).
OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
)
OVERPASS_QUERY_TIMEOUT_S = 25        # [timeout:..] côté serveur
OVERPASS_TIMEOUT_S = 35.0            # client, par tentative
OVERPASS_FALLBACK_TIMEOUT_S = 20.0   # client, miroirs de repli
OVERPASS_PRIMARY_ATTEMPTS = 4        # tentatives sur le miroir principal (429/502/503/504)
OVERPASS_FALLBACK_ATTEMPTS = 2       # tentatives sur chaque miroir de repli
OVERPASS_BACKOFF_S = 4.0             # attentes 4 s, 8 s, 16 s (+ gigue) entre tentatives
OVERPASS_RETRY_HTTP_CODES = (429, 502, 503, 504)
OVERPASS_MAX_WAIT_S = 60.0           # plafond de toute attente (Retry-After, slot libre)
OVERPASS_PAUSE_S = 1.0               # politesse entre deux requêtes réseau
OVERPASS_MAX_CONSECUTIVE_FAILURES = 8  # coupe-circuit (seulement si AUCUN succès du run)
OVERPASS_GIVE_UP_PAUSE_S = 30.0      # dernière pause avant de renoncer
OVERPASS_TILE_M = 2000.0             # tuiles du repli par coordonnées
OVERPASS_MAX_REQUEST_SPAN_M = 3000.0  # côté max de l'emprise d'une requête par noms
OVERPASS_BBOX_MARGIN_M = 250.0
OVERPASS_BBOX_GRID_M = 100.0         # emprise arrondie : requêtes stables (cache)
OVERPASS_MAX_NAMES_PER_QUERY = 40
OVERPASS_CACHE_DIRNAME = "asbuilt_overpass_cache"
OVERPASS_CACHE_TTL_S = 30 * 24 * 3600
# Clés de nom OSM comparées au nom de rue de l'adresse (name:de : Communauté
# germanophone, zone à l'origine du repli).
OSM_NAME_KEYS = ("name", "name:fr", "name:nl", "name:de")

# Repli par COORDONNÉES (3e étape de la chaîne de localisation) : point encore
# non localisé par nom -> voie carrossable OSM la plus proche dans ce rayon (m),
# omis si une voie d'un autre nom est à moins de OSM_COORD_AMBIGUITY_M de plus
# (carrefour). Chemins, pistes, trottoirs, pistes cyclables exclus.
OSM_COORD_FALLBACK_RADIUS_M = 30.0
OSM_COORD_AMBIGUITY_M = 3.0
# Rayon ÉLARGI du repli par coordonnées quand AUCUNE voie portant le nom de
# référence n'existe à LOCATE_RADIUS_M (hameau desservi par une route sans
# nom, ex. « Neidingen 18B » à 33 m d'une unclassified sans nom) ;
# rattachement marqué faible confiance.
COORD_FALLBACK_LONE_RADIUS_M = 60.0
OSM_COORD_BBOX_EXTRA_M = 20.0
OSM_COORD_HIGHWAYS = (
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "living_street", "service", "road",
)

# SCR UNIQUE de toutes les géométries manipulées ou écrites par le script :
# Lambert belge 72 (BD72), EPSG:31370 — PAS Lambert 2008 (EPSG:3812). Nominatim
# et Overpass (WGS84, EPSG:4326) sont systématiquement reprojetés vers lui.
BELGIAN_LAMBERT_AUTHID = "EPSG:31370"
# Écart toléré entre la reprojection QGIS et la formule Python de référence
# (wgs84_to_lambert72_pure) : les opérations de datum BD72 usuelles diffèrent
# de moins d'un mètre.
LAMBERT_CROSSCHECK_TOLERANCE_M = 5.0

# Plage de vraisemblance des coordonnées Lambert belge 72 (EPSG:31370) : une
# géométrie hors plage trahit un SCR mal appliqué (degrés WGS84 non reprojetés,
# axes inversés…). Borne basse à 10 km (la Belgique commence vers x≈20 km,
# y≈20 km) : des degrés (≈ 2–7 ; 49–52) sont ainsi rejetés.
LAMBERT72_X_RANGE = (10000.0, 300000.0)
LAMBERT72_Y_RANGE = (10000.0, 250000.0)

# Fusion des points co-localisés pour les segments (même adresse -> même point
# projeté) : tolérance sur le point projeté, et gravité des catégories (le
# nœud fusionné prend la PIRE : rouge > orange > vert).
COLOCATED_TOLERANCE_M = 0.5
DEPTH_SEVERITY = {"rouge": 0, "orange": 1, "vert": 2}


@dataclass
class RoadLocation:
    """Un point de profondeur localise sur son axe de rue.

    Source : public.fn_asbuilt_locate_on_road (base 'be') ou, en repli, la
    localisation Python sur les voies extraites d'Overpass
    (:func:`locate_on_ways`). ``x``/``y`` = point PROJETE sur l'axe.
    ``side`` = cote de la route du point geocode (cf. SIDE_LEFT/SIDE_RIGHT),
    ``highway`` = type de voie OSM du troncon (decalage du dessin, cf.
    :func:`offset_for_highway` ; vide = decalage par defaut).
    """

    intervention_id: str
    depth_category: str
    road_key: str
    position_m: float
    x: float
    y: float
    side: str = SIDE_RIGHT
    highway: str = ""


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
    de la moitie elle-meme. Quand la polyligne de l'axe est connue
    (``axis_parts`` non vide), elle est mesuree LE LONG DE L'AXE (abscisses
    curvilignes position_m) ; sinon (repli) c'est la corde entre points
    projetes. ``is_long`` suit la meme mesure.

    ``start_*``/``end_*`` : extremites SUR L'AXE (non decalees), dans le sens
    de dessin. ``axis_parts`` : sous-ligne(s) de l'axe couverte(s) par la
    moitie, orientee(s) dans le sens des position_m CROISSANTES (plusieurs
    parties si l'axe est fragmente) ; vide -> corde droite (repli). La
    geometrie enregistree (MultiLineString) est cette sous-ligne decalee de
    ``offset_m`` vers ``side`` (cf. :func:`segment_half_geometry`).
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
    side: str = SIDE_RIGHT
    offset_m: float = 0.0
    axis_parts: tuple = ()


def offset_for_highway(highway) -> float:
    """Décalage latéral (m) pour un tag OSM ``highway`` (défaut si inconnu/vide)."""
    value = (highway or "").strip().lower()
    if value.endswith("_link"):
        value = value[: -len("_link")]
    return HIGHWAY_OFFSET_M.get(value, DEFAULT_HIGHWAY_OFFSET_M)


def side_of_point(dir_x, dir_y, vec_x, vec_y) -> str:
    """Côté ('L'/'R') du vecteur projeté->point par rapport à la direction de l'axe.

    Produit vectoriel ``dir × vec`` : positif -> gauche. Point sur l'axe
    (``|vec|`` < SIDE_ON_AXIS_TOLERANCE_M) ou direction nulle -> 'R'
    (convention). Fonction PURE.
    """
    if math.hypot(vec_x, vec_y) < SIDE_ON_AXIS_TOLERANCE_M:
        return SIDE_RIGHT
    cross = dir_x * vec_y - dir_y * vec_x
    return SIDE_LEFT if cross > 0.0 else SIDE_RIGHT


def side_probe_points(x, y, px, py, eps=1.0):
    """Points de sonde pour déduire le côté via fn_asbuilt_locate_on_road seule.

    La fonction SQL ne renvoie pas la direction de l'axe ; on la sonde : soit
    ``n`` = point - projeté (perpendiculaire à l'axe) et ``m`` = ``n`` tourné
    de +90° (donc parallèle à l'axe). Le point est à GAUCHE ssi avancer le
    long de ``m`` fait DÉCROÎTRE position_m (``t·m = -(t × n)``). Retourne
    ``((x+, y+), (x-, y-))`` = projeté ± ``eps``·m unitaire, ou ``None`` si le
    point est sur l'axe (-> 'R' par convention). Fonction PURE.
    """
    nx, ny = x - px, y - py
    norm = math.hypot(nx, ny)
    if norm < SIDE_ON_AXIS_TOLERANCE_M:
        return None
    mx, my = -ny / norm, nx / norm
    return (px + eps * mx, py + eps * my), (px - eps * mx, py - eps * my)


def side_from_probe_positions(pos_plus, pos_minus):
    """'L' si position_m(projeté + m) < position_m(projeté - m), 'R' si >, None si indécidable."""
    if pos_plus is None or pos_minus is None:
        return None
    if pos_plus < pos_minus - 1e-9:
        return SIDE_LEFT
    if pos_plus > pos_minus + 1e-9:
        return SIDE_RIGHT
    return None


# --- Géométrie de l'axe : abscisse curviligne, sous-ligne, décalage (PUR) ----
# Jointure des décalages aux sommets : onglet (miter) tant que sa longueur ne
# dépasse pas OFFSET_MITER_LIMIT × le décalage, biseau (bevel) au-delà (angles
# aigus) ; côté intérieur, le point d'onglet est omis quand il retomberait
# au-delà d'un des deux tronçons adjacents (évite boucles et autointersections).
OFFSET_MITER_LIMIT = 2.0


def _as_parts(line):
    """Accepte une polyligne ``[(x, y), …]`` ou une multipolyligne ``[[…], …]``."""
    if not line:
        return []
    first = line[0]
    if first and isinstance(first[0], (int, float)):
        return [list(line)]
    return [list(part) for part in line]


def multiline_length(line) -> float:
    """Longueur totale (m) d'une polyligne ou multipolyligne (parties bout à bout)."""
    return sum(polyline_length(part) for part in _as_parts(line))


def point_at_distance(line, s):
    """Point à l'abscisse curviligne ``s`` (bornée) d'une (multi)polyligne.

    Les parties d'une multipolyligne sont parcourues bout à bout, dans l'ordre
    (même convention que position_m). Fonction PURE.
    """
    parts = [p for p in _as_parts(line) if p]
    if not parts:
        return None
    s = max(0.0, float(s))
    walked = 0.0
    for part in parts:
        for (x1, y1), (x2, y2) in zip(part, part[1:]):
            seg = math.hypot(x2 - x1, y2 - y1)
            if walked + seg >= s and seg > 0.0:
                t = (s - walked) / seg
                return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
            walked += seg
    return tuple(parts[-1][-1])


def polyline_substring(coords, s0, s1):
    """Sous-ligne d'une polyligne entre les abscisses ``s0`` <= ``s1`` (bornées).

    Sommets intermédiaires conservés ; ``s0 == s1`` -> ligne dégénérée
    ``[p, p]``. Fonction PURE.
    """
    total = polyline_length(coords)
    s0 = min(max(0.0, s0), total)
    s1 = min(max(s0, s1), total)
    start = point_at_distance(coords, s0)
    if s1 - s0 <= 0.0:
        return [start, start]
    out = [start]
    walked = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        walked += math.hypot(x2 - x1, y2 - y1)
        if s0 < walked < s1:
            out.append((x2, y2))
    out.append(point_at_distance(coords, s1))
    return out


def multiline_substring(line, s0, s1) -> list:
    """Sous-ligne(s) d'une (multi)polyligne entre ``s0`` <= ``s1`` -> liste de parties.

    Une partie par tronçon de l'axe traversé (axe fragmenté -> plusieurs
    parties) ; ``s0 == s1`` -> une partie dégénérée. Fonction PURE.
    """
    parts = [p for p in _as_parts(line) if len(p) >= 2]
    if not parts:
        return []
    if s1 <= s0:
        p = point_at_distance(parts, s0)
        return [[p, p]]
    out = []
    offset = 0.0
    for part in parts:
        length = polyline_length(part)
        lo, hi = max(s0, offset), min(s1, offset + length)
        if hi > lo:
            out.append(polyline_substring(part, lo - offset, hi - offset))
        offset += length
    return out


def offset_polyline(coords, distance, side):
    """Décalage parallèle d'une polyligne de ``distance`` m vers ``side`` ('L'/'R').

    Gauche/droite relatives au SENS de ``coords``. Jointures : onglet borné
    (:data:`OFFSET_MITER_LIMIT`) puis biseau côté extérieur ; côté intérieur,
    intersection des deux décalages, omise si elle tombe au-delà d'un tronçon
    adjacent (pas de boucle). Sommets confondus retirés ; ligne dégénérée ou
    décalage nul -> copie inchangée. Fonction PURE.
    """
    pts = []
    for p in coords:
        if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-9:
            pts.append((float(p[0]), float(p[1])))
    if len(pts) < 2 or not distance:
        return [tuple(p) for p in coords]
    sign = 1.0 if side == SIDE_LEFT else -1.0
    units, lengths, normals = [], [], []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        units.append((ux, uy))
        lengths.append(length)
        normals.append((sign * -uy * distance, sign * ux * distance))
    out = [(pts[0][0] + normals[0][0], pts[0][1] + normals[0][1])]
    for j in range(1, len(pts) - 1):
        (ux0, uy0), (ux1, uy1) = units[j - 1], units[j]
        (nx0, ny0), (nx1, ny1) = normals[j - 1], normals[j]
        px, py = pts[j]
        cross = ux0 * uy1 - uy0 * ux1
        dot = ux0 * ux1 + uy0 * uy1
        if abs(cross) < 1e-12 and dot > 0:
            out.append((px + nx1, py + ny1))
            continue
        inner = sign * cross > 0
        denom = 1.0 + dot
        if inner:
            if denom <= 1e-12:
                continue
            # Recul de l'intersection le long de chaque tronçon : d·tan(θ/2).
            backoff = abs(distance) * math.sqrt(max(0.0, (1.0 - dot) / denom))
            if backoff > lengths[j - 1] or backoff > lengths[j]:
                continue  # onglet intérieur hors des tronçons : omis
            out.append((px + (nx0 + nx1) / denom, py + (ny0 + ny1) / denom))
        else:
            ratio = math.sqrt(2.0 / denom) if denom > 1e-12 else float("inf")
            if ratio <= OFFSET_MITER_LIMIT:
                out.append((px + (nx0 + nx1) / denom, py + (ny0 + ny1) / denom))
            else:  # biseau
                out.append((px + nx0, py + ny0))
                out.append((px + nx1, py + ny1))
    out.append((pts[-1][0] + normals[-1][0], pts[-1][1] + normals[-1][1]))
    return out


def build_segment_halves(locations, road_extents, road_lines=None) -> list:
    """Construit les moities de segments d'axe de rue, PAR COTE de la route.

    ``locations`` : points localises (un road_key manquant/vide est filtre
    par l'appelant, cf. Task 7). Les points gris (categorie 'manquante' ou
    vide) sont normalement filtres en amont, AVANT localisation (aucun appel
    SQL/Overpass pour eux) ; ils sont de toute facon ignores ici.
    ``road_extents`` : dict road_key -> RoadExtent (bornes de la route
    fusionnee, pour les segments de bout de route). ``road_lines`` : dict
    road_key -> polyligne (ou multipolyligne) de l'axe FUSIONNE, orientee
    comme les position_m ; route absente -> repli en cordes droites. Fonction
    PURE, aucune dependance PyQGIS.

    Appariement par ``(road_key, side)`` : les points de chaque cote forment
    leur propre chaine (points consecutifs par position_m), avec leurs propres
    segments de bout de route — deux points de cotes opposes ne sont jamais
    relies. Avec l'axe : moitie 'a' = de A au MILIEU CURVILIGNE de A–B, 'b' =
    du milieu a B, bouts de rue = du point a l'extremite de l'axe ;
    ``length_m``/``is_long`` le long de l'axe. Sans axe : cordes, longueur
    = distance entre points projetes. ``offset_m`` : decalage du dessin selon
    le type de voie du point porteur de la moitie (:func:`offset_for_highway`).
    """
    road_lines = road_lines or {}
    # Gardes défensives (en plus du filtre amont de _sync_segments) :
    # * points GRIS (profondeur 'manquante' ou vide) ignorés — ni nœud, ni
    #   voisin d'appariement, ni départ d'un segment de bout de rue ;
    # * unicité : un même intervention_id localisé deux fois produirait des
    #   clés (a, b, half, side) en double — seule la PREMIÈRE est gardée.
    by_road = defaultdict(list)
    seen_ids = set()
    for loc in locations:
        if not loc.depth_category or loc.depth_category == "manquante":
            continue
        if loc.intervention_id in seen_ids:
            continue
        seen_ids.add(loc.intervention_id)
        by_road[(loc.road_key, loc.side)].append(loc)

    def parts_of(line, s0, s1):
        return tuple(tuple(tuple(p) for p in part) for part in multiline_substring(line, s0, s1))

    halves: list[SegmentHalf] = []
    for (road_key, side), points in by_road.items():
        ordered = sorted(points, key=lambda p: p.position_m)
        line = road_lines.get(road_key)

        for a, b in zip(ordered, ordered[1:]):
            if line:
                length = max(0.0, b.position_m - a.position_m)
                mid_s = (a.position_m + b.position_m) / 2.0
                mid_x, mid_y = point_at_distance(line, mid_s)
                parts_a = parts_of(line, a.position_m, mid_s)
                parts_b = parts_of(line, mid_s, b.position_m)
            else:
                length = math.hypot(b.x - a.x, b.y - a.y)
                mid_x, mid_y = (a.x + b.x) / 2.0, (a.y + b.y) / 2.0
                parts_a = parts_b = ()
            is_long = length >= LONG_SEGMENT_THRESHOLD_M
            halves.append(SegmentHalf(
                point_a_intervention_id=a.intervention_id,
                point_b_intervention_id=b.intervention_id,
                half="a", depth_category=a.depth_category, is_long=is_long,
                length_m=length, road_key=road_key,
                start_x=a.x, start_y=a.y, end_x=mid_x, end_y=mid_y,
                side=side, offset_m=offset_for_highway(a.highway),
                axis_parts=parts_a,
            ))
            halves.append(SegmentHalf(
                point_a_intervention_id=a.intervention_id,
                point_b_intervention_id=b.intervention_id,
                half="b", depth_category=b.depth_category, is_long=is_long,
                length_m=length, road_key=road_key,
                start_x=mid_x, start_y=mid_y, end_x=b.x, end_y=b.y,
                side=side, offset_m=offset_for_highway(b.highway),
                axis_parts=parts_b,
            ))

        extent = road_extents.get(road_key)
        if extent is None and not line:
            continue
        first, last = ordered[0], ordered[-1]
        cap = ROAD_END_STUB_M
        if line:
            total = multiline_length(line)
            s_start = max(0.0, first.position_m - cap)
            s_end = min(total, last.position_m + cap)
            ends = (
                (first, ROAD_START_SENTINEL, point_at_distance(line, s_start),
                 max(0.0, first.position_m - s_start),
                 parts_of(line, s_start, first.position_m)),
                (last, ROAD_END_SENTINEL, point_at_distance(line, s_end),
                 max(0.0, s_end - last.position_m),
                 parts_of(line, last.position_m, s_end)),
            )
        else:
            ends = []
            for point, sentinel, (tx, ty) in (
                (first, ROAD_START_SENTINEL, (extent.start_x, extent.start_y)),
                (last, ROAD_END_SENTINEL, (extent.end_x, extent.end_y)),
            ):
                full = math.hypot(tx - point.x, ty - point.y)
                k = min(1.0, cap / full) if full > 0 else 1.0
                ends.append((
                    point, sentinel,
                    (point.x + k * (tx - point.x), point.y + k * (ty - point.y)),
                    min(full, cap), (),
                ))
        for point, sentinel, (end_x, end_y), length, parts in ends:
            halves.append(SegmentHalf(
                point_a_intervention_id=point.intervention_id,
                point_b_intervention_id=sentinel,
                half="a", depth_category=point.depth_category,
                is_long=length >= LONG_SEGMENT_THRESHOLD_M,
                length_m=length, road_key=road_key,
                start_x=point.x, start_y=point.y, end_x=end_x, end_y=end_y,
                side=side, offset_m=offset_for_highway(point.highway),
                axis_parts=parts,
            ))
    return halves


def segment_half_geometry(half):
    """Géométrie ENREGISTRÉE d'une moitié : tuple de parties ``((x, y), …)`` (MultiLineString).

    * Axe connu (``axis_parts``) : chaque partie de la sous-ligne de l'axe
      est décalée parallèlement de ``half.offset_m`` vers ``half.side``
      (:func:`offset_polyline`, gauche/droite relatives au SENS DE L'AXE =
      position_m croissantes), puis l'ensemble est remis dans le sens de
      dessin (un bout de route vers ROAD_START est dessiné à rebours).
    * Repli (corde) : une seule partie, translation perpendiculaire à la
      corde ; direction nulle ou décalage nul -> extrémités sur l'axe.

    Fonction PURE.
    """
    reverse = half.point_b_intervention_id == ROAD_START_SENTINEL
    if half.axis_parts:
        parts = []
        for part in half.axis_parts:
            axis = [tuple(p) for p in part]
            if not half.offset_m:
                parts.append(axis)
                continue
            shifted = offset_polyline(axis, half.offset_m, half.side)
            # Garde-fou : une partie décalée aberrante (boucle, retournement,
            # crochet…) est remplacée par l'axe NON décalé plutôt que tracée.
            if offset_part_anomalies(axis, shifted, half.offset_m):
                shifted = axis
            parts.append(shifted)
        if reverse:
            parts = [list(reversed(part)) for part in reversed(parts)]
        return tuple(tuple((float(x), float(y)) for x, y in part) for part in parts)
    sx, sy, ex, ey = half.start_x, half.start_y, half.end_x, half.end_y
    dx, dy = ex - sx, ey - sy
    if reverse:
        dx, dy = -dx, -dy
    norm = math.hypot(dx, dy)
    if norm == 0.0 or not half.offset_m:
        return (((sx, sy), (ex, ey)),)
    # Normale gauche de la direction de l'axe ; côté droit = opposé.
    sign = 1.0 if half.side == SIDE_LEFT else -1.0
    ox = sign * half.offset_m * (-dy / norm)
    oy = sign * half.offset_m * (dx / norm)
    return (((sx + ox, sy + oy), (ex + ox, ey + oy)),)


def _segments_cross(p1, p2, q1, q2) -> bool:
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return d1 * d2 < 0 and d3 * d4 < 0


def polyline_self_intersects(coords) -> bool:
    """Deux tronçons NON adjacents d'une polyligne se croisent-ils ? PURE."""
    segs = [(a, b) for a, b in zip(coords, coords[1:]) if a != b]
    for i in range(len(segs)):
        for j in range(i + 2, len(segs)):
            if _segments_cross(segs[i][0], segs[i][1], segs[j][0], segs[j][1]):
                return True
    return False


GEOMETRY_CHECK_TOLERANCE_M = 0.5
GEOMETRY_LENGTH_RATIO = (0.7, 1.5)
GEOMETRY_RATIO_MIN_AXIS_M = 5.0


def offset_part_anomalies(axis, offset_coords, distance) -> list:
    """Contrôle d'une partie DÉCALÉE par rapport à sa partie d'axe -> liste de défauts.

    (1) auto-intersection ; (2) rapport longueur décalée / longueur d'axe hors
    [0,7 ; 1,5] (parties d'axe ≥ 5 m) ; (3) retournement : un tronçon décalé
    dont la direction fait plus de 90° avec la direction locale de l'axe ;
    (4) extrémité décalée à plus de ``distance`` + 0,5 m de l'extrémité
    d'axe correspondante. Les deux listes de sommets sont dans le MÊME sens.
    Fonction PURE.
    """
    problems = []
    if len(axis) < 2 or len(offset_coords) < 2:
        return problems
    if polyline_self_intersects(offset_coords):
        problems.append("auto-intersection")
    axis_len = polyline_length(axis)
    if axis_len >= GEOMETRY_RATIO_MIN_AXIS_M:
        ratio = polyline_length(offset_coords) / axis_len
        if not GEOMETRY_LENGTH_RATIO[0] <= ratio <= GEOMETRY_LENGTH_RATIO[1]:
            problems.append(f"rapport de longueur {ratio:.2f}")
    for a, b in zip(offset_coords, offset_coords[1:]):
        vx, vy = b[0] - a[0], b[1] - a[1]
        if math.hypot(vx, vy) < 1e-6:
            continue
        mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        _d, _pos, _qx, _qy, dx, dy = project_on_polyline(mx, my, axis)
        if vx * dx + vy * dy < 0:
            problems.append("retournement")
            break
    limit = abs(distance) + GEOMETRY_CHECK_TOLERANCE_M
    for axis_end, offset_end in ((axis[0], offset_coords[0]), (axis[-1], offset_coords[-1])):
        if math.hypot(axis_end[0] - offset_end[0], axis_end[1] - offset_end[1]) > limit:
            problems.append("extrémité décalée trop loin")
            break
    return problems


def segment_geometry_anomalies(half) -> list:
    """Défauts du décalage BRUT d'une moitié (avant garde-fou) ; vide = sain.

    Une moitié qui en présente est dessinée sur l'axe non décalé
    (:func:`segment_half_geometry`) : c'est une moitié « simplifiée ». PURE.
    """
    if not half.axis_parts or not half.offset_m:
        return []
    problems = []
    for part in half.axis_parts:
        axis = [tuple(p) for p in part]
        problems.extend(offset_part_anomalies(
            axis, offset_polyline(axis, half.offset_m, half.side), half.offset_m
        ))
    return problems


def merge_colocated(locations, tol=COLOCATED_TOLERANCE_M):
    """Fusionne les points CO-LOCALISÉS en un seul nœud pour les segments.

    Deux interventions distinctes au même point projeté (typiquement la même
    adresse, géocodée au même endroit) produiraient sinon un segment de
    longueur nulle. Par (road_key, side), les points triés par (position_m,
    intervention_id) sont regroupés tant qu'ils restent à ``tol`` m au plus
    du PREMIER point du groupe (ancre). Nœud fusionné :

    * intervention_id, position et point projeté du plus PETIT id du groupe
      (représentant déterministe) ;
    * catégorie = la PIRE du groupe (rouge > orange > vert, cf.
      :data:`DEPTH_SEVERITY` ; une catégorie inconnue n'est jamais retenue
      comme pire qu'une connue).

    Les points restent tous en base ; seuls les segments utilisent le nœud.
    Retourne ``(nœuds, membres)`` : ``membres`` = dict id représentant ->
    tuple trié des ids du groupe (groupes de ≥ 2 seulement). Fonction PURE.
    """
    groups = defaultdict(list)
    for loc in locations:
        groups[(loc.road_key, loc.side)].append(loc)
    nodes = []
    members = {}
    for key in sorted(groups, key=lambda k: (str(k[0]), str(k[1]))):
        clusters = []
        for loc in sorted(groups[key], key=lambda l: (l.position_m, l.intervention_id)):
            if clusters:
                anchor = clusters[-1][0]
                if math.hypot(loc.x - anchor.x, loc.y - anchor.y) <= tol:
                    clusters[-1].append(loc)
                    continue
            clusters.append([loc])
        for cluster in clusters:
            rep = min(cluster, key=lambda l: l.intervention_id)
            worst = min(
                cluster, key=lambda l: DEPTH_SEVERITY.get(l.depth_category, len(DEPTH_SEVERITY))
            ).depth_category
            nodes.append(RoadLocation(
                intervention_id=rep.intervention_id, depth_category=worst,
                road_key=rep.road_key, position_m=rep.position_m, x=rep.x, y=rep.y,
                side=rep.side, highway=rep.highway,
            ))
            if len(cluster) > 1:
                members[rep.intervention_id] = tuple(sorted(l.intervention_id for l in cluster))
    return nodes, members


def colocated_raw_groups(points, tol=COLOCATED_TOLERANCE_M) -> dict:
    """Groupes de points probablement fusionnés, estimés SANS relocalisation.

    ``points`` : ``(intervention_id, nom_de_rue, x, y)`` (point GÉOCODÉ, avant
    projection). Même rue (nom normalisé) et même position à ``tol`` près
    -> même point projeté, donc même nœud fusionné (:func:`merge_colocated`).
    Sert au mode incrémental : un membre non représentant n'apparaît dans
    aucun segment, il ne doit pas être pris pour « jamais localisé », et un
    membre sale rend tout son groupe sale. Retourne dict id -> frozenset du
    groupe (groupes de ≥ 2 seulement). Fonction PURE.
    """
    by_street = defaultdict(list)
    for intervention_id, street, x, y in points:
        by_street[normalize_street_name(street)].append((x, y, intervention_id))
    result = {}
    for street, pts in by_street.items():
        if not street:
            continue
        clusters = []
        for x, y, intervention_id in sorted(pts):
            if clusters and math.hypot(x - clusters[-1][0][0], y - clusters[-1][0][1]) <= tol:
                clusters[-1].append((x, y, intervention_id))
            else:
                clusters.append([(x, y, intervention_id)])
        for cluster in clusters:
            if len(cluster) > 1:
                group = frozenset(p[2] for p in cluster)
                for intervention_id in group:
                    result[intervention_id] = group
    return result


def with_companions(ids, companions) -> set:
    """``ids`` complété par tous les membres de leurs groupes co-localisés."""
    out = set(ids)
    for intervention_id in list(out):
        out |= companions.get(intervention_id, frozenset())
    return out


def filter_protected_deletions(to_delete, existing, protected_roads):
    """Retire de la purge les segments des routes protégées -> ``(gardés, n_bloqués)``.

    Routes protégées : celles où figurait un point non localisé faute de
    réponse Overpass (échec isolé) — leurs segments ne sont pas purgés ce run.
    Fonction PURE.
    """
    kept = [key for key in to_delete if existing[key].get("road_key") not in protected_roads]
    return kept, len(to_delete) - len(kept)


def crs_needs_fix(authid) -> bool:
    """Le SCR d'une couche des tables 'be' doit-il être forcé en EPSG:31370 ?

    Tout autre authid — vide (SCR invalide/inconnu), EPSG:3857 hérité du fond
    de carte, EPSG:4326… — trahit une couche mal géoréférencée (coordonnées
    Lambert 72 affichées ailleurs). Fonction PURE.
    """
    return (authid or "").strip().upper() != BELGIAN_LAMBERT_AUTHID


def split_ungeocoded(entries, existing_point_ids):
    """Règle « si géocodé, garder que géocodé » -> ``(à_pousser, conservés)``.

    ``entries`` : (InterventionRecord, requête) en échec de géocodage à CE run.
    Une intervention qui a déjà un point géocodé en base
    (``existing_point_ids``) n'est PAS poussée dans les non géocodées : le
    point existant est conservé, l'échec de re-géocodage ignoré. Fonction PURE.
    """
    existing = {str(i) for i in existing_point_ids}
    to_push = [e for e in entries if str(e[0].intervention) not in existing]
    kept = [e for e in entries if str(e[0].intervention) in existing]
    return to_push, kept


@dataclass
class Connector:
    """Ligne du point GÉOCODÉ vers l'extrémité de son segment (axe décalé).

    Un connecteur par point réel : les membres d'un nœud fusionné (points
    co-localisés) ont chacun le leur, vers l'extrémité du nœud. ``length_m``
    = longueur du connecteur ; géométrie LineString EPSG:31370 à 2 sommets.
    """

    intervention_id: str
    depth_category: str
    side: str
    road_key: str
    length_m: float
    start_x: float
    start_y: float
    end_x: float
    end_y: float


def segment_endpoints(halves) -> dict:
    """Extrémité DESSINÉE (axe décalé) de chaque nœud, d'après ses moitiés de segment.

    Premier sommet de la moitié 'a' qui part du nœud (paires et bouts de
    rue : un bout vers ROAD_START est dessiné depuis le point), à défaut
    dernier sommet de la moitié 'b' qui y arrive. Fonction PURE.
    """
    ends = {}
    for half in halves:
        if half.half == "a":
            geometry = segment_half_geometry(half)
            if geometry and geometry[0]:
                ends.setdefault(half.point_a_intervention_id, tuple(geometry[0][0]))
    for half in halves:
        if half.half == "b" and half.point_b_intervention_id not in ends:
            geometry = segment_half_geometry(half)
            if geometry and geometry[-1]:
                ends[half.point_b_intervention_id] = tuple(geometry[-1][-1])
    return ends


def build_connectors(points, locations, halves, merged_members=None) -> list:
    """Connecteurs point géocodé -> extrémité du segment tel que dessiné.

    ``points`` : dict id -> (x, y, catégorie) des points RÉELS (EPSG:31370,
    géocodés) ; ``locations`` : nœuds localisés (après fusion des
    co-localisés) ; ``halves`` : moitiés construites à partir de ces nœuds —
    l'extrémité est lue sur leur géométrie DÉCALÉE (:func:`segment_endpoints`),
    donc au point projeté orthogonalement sur l'axe décalé du côté et de la
    distance du type de voie ; ``merged_members`` : dict id représentant ->
    ids du groupe (:func:`merge_colocated`). Nœud sans moitié (route sans
    bornes connues) : extrémité = point projeté décalé vers le point géocodé.
    Points gris ou inconnus de ``points`` : aucun connecteur. PURE.
    """
    merged_members = merged_members or {}
    ends = segment_endpoints(halves)
    connectors = []
    seen = set()
    for loc in locations:
        end = ends.get(loc.intervention_id)
        if end is None:
            px, py = points.get(loc.intervention_id, (loc.x, loc.y, ""))[:2]
            dx, dy = px - loc.x, py - loc.y
            norm = math.hypot(dx, dy)
            offset = offset_for_highway(loc.highway)
            end = (loc.x + offset * dx / norm, loc.y + offset * dy / norm) if norm > 0 else (loc.x, loc.y)
        for member in merged_members.get(loc.intervention_id, (loc.intervention_id,)):
            if member in seen or member not in points:
                continue
            x, y, category = points[member]
            if not category or category == "manquante":
                continue
            seen.add(member)
            connectors.append(Connector(
                intervention_id=member, depth_category=category, side=loc.side,
                road_key=loc.road_key, length_m=math.hypot(end[0] - x, end[1] - y),
                start_x=x, start_y=y, end_x=end[0], end_y=end[1],
            ))
    return sorted(connectors, key=lambda c: c.intervention_id)


def connector_changed(connector, existing, tol=None) -> bool:
    """Connecteur recalculé différent de la ligne en base ? (attributs + 2 sommets à tol)."""
    tol = SEGMENT_COMPARE_TOLERANCE if tol is None else tol
    if existing.get("depth_category") != connector.depth_category:
        return True
    if existing.get("side") != connector.side or existing.get("road_key") != connector.road_key:
        return True
    length = existing.get("length_m")
    if not isinstance(length, (int, float)) or abs(length - connector.length_m) > tol:
        return True
    coords = existing.get("coords")
    wanted = ((connector.start_x, connector.start_y), (connector.end_x, connector.end_y))
    if not coords or len(coords) != 2:
        return True
    return any(
        abs(a[0] - b[0]) > tol or abs(a[1] - b[1]) > tol for a, b in zip(coords, wanted)
    )


@dataclass
class ConnectorSyncPlan:
    to_insert: list
    to_update: list
    to_delete: list
    unchanged: int


def plan_connector_sync(fresh, existing, scope_ids=None, eligible_ids=None) -> ConnectorSyncPlan:
    """Répartit les connecteurs recalculés en insert / update / delete / inchangés.

    ``existing`` : dict intervention_id -> état en base. ``scope_ids`` : points
    RELOCALISÉS à ce run (incrémental) ou None (complet). Suppression d'un
    connecteur en base absent de ``fresh`` SEULEMENT s'il est dans le
    périmètre, ou si son point n'est plus éligible (``eligible_ids`` : points
    de couleur présents dans la table — devenu gris ou supprimé). Un
    connecteur identique n'est jamais réécrit. Fonction PURE.
    """
    fresh_by_id = {c.intervention_id: c for c in fresh}
    to_insert, to_update, unchanged = [], [], 0
    for intervention_id, connector in sorted(fresh_by_id.items()):
        current = existing.get(intervention_id)
        if current is None:
            to_insert.append(connector)
        elif connector_changed(connector, current):
            to_update.append(connector)
        else:
            unchanged += 1
    to_delete = sorted(
        i for i in existing
        if i not in fresh_by_id and (
            scope_ids is None or i in scope_ids
            or (eligible_ids is not None and i not in eligible_ids)
        )
    )
    return ConnectorSyncPlan(to_insert, to_update, to_delete, unchanged)


_DEPTH_CONNECTORS_STYLE_QML_NAME = "depth_connectors.qml"


def _collection_style_qml_path(file_name, profile_dir: Optional[str] = None) -> Optional[str]:
    """Chemin d'un ``.qml`` de la collection (sibling ``../style/`` puis cache Resource Sharing)."""
    candidates: list[str] = []
    try:
        module_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.normpath(os.path.join(module_dir, "..", "style", file_name)))
    except NameError:  # pragma: no cover - __file__ absent (exec sans fichier)
        pass
    candidates.extend(
        os.path.join(style_dir, file_name) for style_dir in _resource_sharing_style_dirs(profile_dir)
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def count_zero_length_pairs(halves) -> int:
    """Nombre de PAIRES de points distincts au même point projeté (longueur nulle).

    Cas typique : deux interventions à la même adresse, géocodées au même
    point. Comptées une fois par paire (moitié 'a' seulement), segments de
    bout de route exclus. Fonction PURE (journalisation).
    """
    return sum(
        1 for h in halves
        if h.half == "a" and h.length_m == 0.0
        and h.point_b_intervention_id not in (ROAD_START_SENTINEL, ROAD_END_SENTINEL)
    )


def segment_key(half):
    """Clé métier d'une moitié : (point_a, point_b, half, side) — cf. PK en base."""
    return (
        half.point_a_intervention_id, half.point_b_intervention_id,
        half.half, half.side,
    )


SEGMENT_COMPARE_TOLERANCE = 1e-6


@dataclass
class SegmentSyncPlan:
    """Plan d'écriture des segments (cf. :func:`plan_segment_sync`)."""

    to_insert: list   # SegmentHalf absents de la base
    to_update: list   # SegmentHalf présents mais différents
    to_delete: list   # clés (a, b, half, side) obsolètes DANS le périmètre
    unchanged: int    # présents et identiques : ni recalcul écrit, ni réécriture


def parse_wkt_lines(text):
    """WKT (E)WKT ``LINESTRING`` / ``MULTILINESTRING`` (2D, Z/M ignorés) -> liste de parties.

    ``None`` si vide, illisible ou d'un autre type. Fonction PURE.
    """
    if not text:
        return None
    body = str(text).strip()
    if body.upper().startswith("SRID="):
        body = body.split(";", 1)[-1].strip()
    match = re.match(r"^(MULTILINESTRING|LINESTRING)\s*(ZM|Z|M)?\s*\((.*)\)\s*$", body, re.I | re.S)
    if not match:
        return None
    kind, inner = match.group(1).upper(), match.group(3)
    raw_parts = re.findall(r"\(([^()]*)\)", inner) if kind == "MULTILINESTRING" else [inner]
    parts = []
    for raw in raw_parts:
        coords = []
        for pair in raw.split(","):
            values = pair.split()
            if len(values) < 2:
                return None
            try:
                coords.append((float(values[0]), float(values[1])))
            except ValueError:
                return None
        if len(coords) >= 2:
            parts.append(coords)
    return parts or None


def is_multilinestring_type(geometry_type) -> bool:
    """Type ``geometry_columns.type`` d'une colonne MultiLineString ? Fonction PURE."""
    return (geometry_type or "").strip().upper().startswith("MULTILINESTRING")


def road_line_matches(parts, road_length_m, tol_m=1.0) -> bool:
    """La géométrie d'axe renvoyée par la base est-elle celle des position_m ?

    Garde de cohérence avant de faire suivre l'axe aux segments : longueur
    totale égale (à ``tol_m`` près) à road_length_m de fn_asbuilt_locate_on_road
    — sinon (autre fusion, autre composante) repli sur les cordes. PURE.
    """
    try:
        return bool(parts) and abs(multiline_length(parts) - float(road_length_m)) <= tol_m
    except (TypeError, ValueError):
        return False


def looks_like_chord_segments(existing) -> bool:
    """Segments en base TOUS en cordes (une partie, 2 sommets) — version antérieure ?"""
    coords = [c.get("coords") for c in existing.values()]
    return bool(coords) and all(
        c and len(c) == 1 and len(c[0]) == 2 for c in coords
    )


def geometry_for_column(parts, multi_column=True):
    """Parties effectivement écrites selon le type de la colonne ``geom``.

    Colonne MultiLineString : toutes les parties. Colonne encore LineString
    (migration non appliquée) : la PREMIÈRE partie seulement. Retourne
    ``(parties, nb_parties_abandonnées)``. Fonction PURE.
    """
    parts = tuple(parts)
    if multi_column or len(parts) <= 1:
        return parts, 0
    return parts[:1], len(parts) - 1


def segment_half_changed(half, existing, tol=SEGMENT_COMPARE_TOLERANCE,
                         multi_column=True, geometry=None) -> bool:
    """Le segment recalculé ``half`` diffère-t-il de la ligne ``existing`` en base ?

    ``existing`` : dict ``road_key``/``depth_category``/``is_long``/``length_m``
    et ``coords`` (tuple de parties ``((x, y), …)`` lu en base, ou ``None``
    si illisible -> différent). ``side`` fait partie de la clé, donc pas
    comparé ici. Longueur et géométrie à ``tol`` près ; géométrie = celle
    qui SERAIT écrite (:func:`segment_half_geometry` puis
    :func:`geometry_for_column`) : même nombre de parties, mêmes nombres de
    sommets, sommets à ``tol`` près. Fonction PURE.
    """
    if existing.get("road_key") != half.road_key:
        return True
    if existing.get("depth_category") != half.depth_category:
        return True
    if bool(existing.get("is_long")) != bool(half.is_long) or existing.get("is_long") is None:
        return True
    length = existing.get("length_m")
    if not isinstance(length, (int, float)) or abs(length - half.length_m) > tol:
        return True
    coords = existing.get("coords")
    if geometry is None:
        geometry = segment_half_geometry(half)
    fresh, _dropped = geometry_for_column(geometry, multi_column)
    if not coords or len(coords) != len(fresh):
        return True
    for old_part, new_part in zip(coords, fresh):
        if len(old_part) != len(new_part):
            return True
        for (ex, ey), (fx, fy) in zip(old_part, new_part):
            if abs(ex - fx) > tol or abs(ey - fy) > tol:
                return True
    return False


def plan_segment_sync(fresh, existing, scope_roads=None, multi_column=True,
                      geometries=None) -> SegmentSyncPlan:
    """Répartit les moitiés recalculées en insert / update / delete / inchangées.

    ``fresh`` : SegmentHalf de build_segment_halves (cet appel) — clés uniques.
    ``existing`` : dict clé (a, b, half, side) -> état en base (cf.
    :func:`segment_half_changed`). ``scope_roads`` : road_keys RECALCULÉES
    (mode incrémental) ou ``None`` (reconstruction complète : tout est dans
    le périmètre).

    * insert : clé fraîche absente de la base ;
    * update : clé présente mais contenu différent — un segment IDENTIQUE
      n'est jamais réécrit (compté dans ``unchanged``) ;
    * delete : clé en base, absente de ``fresh``, ET dans le périmètre (son
      road_key est recalculé) : une purge ne touche JAMAIS une route propre,
      dont les segments ne figurent pas dans ``fresh`` puisqu'elle n'a pas
      été recalculée. Fonction PURE.
    """
    fresh_by_key = {}
    for half in fresh:
        fresh_by_key.setdefault(segment_key(half), half)
    to_insert, to_update, unchanged = [], [], 0
    for key, half in fresh_by_key.items():
        current = existing.get(key)
        if current is None:
            to_insert.append(half)
        elif segment_half_changed(
            half, current, multi_column=multi_column,
            geometry=(geometries or {}).get(key),
        ):
            to_update.append(half)
        else:
            unchanged += 1
    to_delete = sorted(
        key for key, current in existing.items()
        if key not in fresh_by_key
        and (scope_roads is None or current.get("road_key") in scope_roads)
    )
    return SegmentSyncPlan(to_insert, to_update, to_delete, unchanged)


def point_changed(old, new, tol=SEGMENT_COMPARE_TOLERANCE) -> bool:
    """Un point upserté a-t-il changé d'une façon qui impacte les segments ?

    ``old`` : état lu en base AVANT l'upsert (dict ``depth_category``/
    ``address_raw``/``x``/``y``, ``x``/``y`` à ``None`` si géométrie
    illisible) ou ``None`` (point nouveau). ``new`` : valeurs écrites. Seuls
    comptent la catégorie (couleur, gris), l'adresse (nom de rue) et la
    position. Fonction PURE.
    """
    if old is None:
        return True
    if (old.get("depth_category") or "") != (new.get("depth_category") or ""):
        return True
    if (old.get("address_raw") or "") != (new.get("address_raw") or ""):
        return True
    if old.get("x") is None or old.get("y") is None:
        return True
    return math.hypot(old["x"] - new["x"], old["y"] - new["y"]) > tol


def index_existing_segments(existing):
    """Index des segments en base -> (ids par road_key, road_keys par id, ids couverts).

    Les sentinelles de bout de route ne sont pas des interventions. Fonction PURE.
    """
    road_ids = defaultdict(set)
    id_roads = defaultdict(set)
    for (point_a, point_b, _half, _side), current in existing.items():
        road_key = current.get("road_key")
        for intervention_id in (point_a, point_b):
            if intervention_id in (ROAD_START_SENTINEL, ROAD_END_SENTINEL):
                continue
            road_ids[road_key].add(intervention_id)
            id_roads[intervention_id].add(road_key)
    return dict(road_ids), dict(id_roads), set(id_roads)


def inconsistent_roads(existing) -> set:
    """road_keys dont les segments en base ne forment pas une chaîne valide.

    Une reconstruction saine donne, par (road_key, side) : au plus un segment
    de début et un de fin de route, et pour chaque point au plus UNE moitié
    'a' hors début de route (vers son successeur ou vers la fin de route) ;
    et chaque point n'appartient qu'à UN SEUL (road_key, side). Une violation signale des segments PÉRIMÉS laissés en place par un run
    dont la purge a été suspendue (garde-fous) : la route doit être refaite
    au prochain run, même si aucun de ses points n'a changé. Fonction PURE.
    """
    starts = Counter()
    ends = Counter()
    outgoing = Counter()
    groups_of_point = defaultdict(set)
    for (point_a, point_b, half, side), current in existing.items():
        group = (current.get("road_key"), side)
        for intervention_id in (point_a, point_b):
            if intervention_id not in (ROAD_START_SENTINEL, ROAD_END_SENTINEL):
                groups_of_point[intervention_id].add(group)
        if point_b == ROAD_START_SENTINEL:
            starts[group] += 1
        elif half == "a":
            outgoing[(group, point_a)] += 1
            if point_b == ROAD_END_SENTINEL:
                ends[group] += 1
    bad = {group[0] for group, n in starts.items() if n > 1}
    bad |= {group[0] for group, n in ends.items() if n > 1}
    bad |= {group[0] for (group, _point), n in outgoing.items() if n > 1}
    for groups in groups_of_point.values():
        if len(groups) > 1:  # point passé de côté ou de route
            bad |= {group[0] for group in groups}
    return bad


def initial_dirty_ids(changed_ids, eligible_ids, locatable_ids, covered_ids,
                      recompute_existing=True) -> set:
    """Points « sales » de départ du mode incrémental. Fonction PURE.

    * ``changed_ids`` — nouveaux/modifiés par l'upsert de CE run (catégorie,
      adresse ou position, cf. :func:`point_changed`) ;
    * ``locatable_ids - covered_ids`` — points de couleur (``eligible_ids``)
      AVEC nom de rue extractible (``locatable_ids``) absents de tout segment :
      jamais localisés, ou segments perdus (retentés à chaque run) ;
    * ``covered_ids - eligible_ids`` — points cités par des segments mais
      désormais gris ou supprimés de la table : leurs routes sont à refaire.

    ``recompute_existing=False`` (point déjà géocodé = rien à refaire) : seuls
    les ``changed_ids`` de CE run sont sales, aucune relocalisation (donc ni
    ``ref.osm_roads`` ni Overpass) n'est relancée pour les points existants.
    """
    if not recompute_existing:
        return set(changed_ids)
    return (
        set(changed_ids)
        | (set(locatable_ids) - set(covered_ids))
        | (set(covered_ids) - set(eligible_ids))
    )


def expand_dirty_roads(dirty_ids, eligible_ids, road_ids, id_roads, locate, companions=None):
    """Propage les points sales aux routes à recalculer, jusqu'au point fixe.

    Pour chaque lot : les routes des segments EXISTANTS qui citent ses points,
    plus les routes où ses points éligibles sont (re)localisés via ``locate``
    (callable ``list[id] -> dict id -> road_key``, appelé seulement pour les
    points jamais tentés) deviennent sales ; les AUTRES points de chaque
    nouvelle route sale (connus par ses segments existants) sont ajoutés au
    lot suivant, pour reconstruire la route en entier. Terminaison : les
    ensembles ne font que croître. ``companions`` (cf.
    :func:`colocated_raw_groups`) : tout point ajouté entraîne les membres de
    son groupe co-localisé (le nœud fusionné doit être recalculé en entier).
    Retourne ``(routes_sales, localisés)``,
    ``localisés`` = dict id -> road_key. Fonction PURE (``locate`` injecté).
    """
    dirty_roads: set = set()
    located: dict = {}
    seen: set = set()
    companions = companions or {}
    pending = with_companions(dirty_ids, companions)
    while pending:
        batch = sorted(pending - seen)
        seen.update(batch)
        new_roads = set()
        for intervention_id in batch:
            new_roads.update(id_roads.get(intervention_id, ()))
        to_locate = [i for i in batch if i in eligible_ids]
        if to_locate:
            result = locate(to_locate)
            located.update(result)
            new_roads.update(result.values())
        pending = set()
        for road_key in sorted(new_roads - dirty_roads):
            dirty_roads.add(road_key)
            pending.update(road_ids.get(road_key, ()))
        pending = with_companions(pending, companions) - seen
    return dirty_roads, located


# --- Repli Overpass : extraction OSM + localisation Python (PUR) -------------
@dataclass
class OsmWay:
    """Une voie OSM nommée (tag ``highway``) extraite d'Overpass.

    ``names`` : noms normalisés (:func:`normalize_street_name`) des clés
    :data:`OSM_NAME_KEYS` présentes. ``coords`` : sommets ``(x, y)`` — en
    WGS84 ``(lon, lat)`` à la sortie de :func:`parse_overpass_ways`, en
    EPSG:31370 une fois reprojetés par l'appelant (seul repère dans lequel
    les fonctions de localisation, en mètres, ont un sens).
    """

    way_id: int
    names: tuple
    highway: str
    coords: list
    # Tags OSM bruts (name, name:de, name:fr, name:nl, ref, maxspeed…) et
    # géométrie WGS84 d'origine : nécessaires à l'alimentation de ref.osm_roads
    # (fn_asbuilt_store_osm_ways reprojette elle-même depuis le WGS84).
    tags: dict = field(default_factory=dict)
    coords_wgs84: tuple = ()


class OverpassError(RuntimeError):
    """Levée quand aucun miroir Overpass n'a fourni de réponse exploitable."""


def normalize_street_name(name) -> str:
    """Nom de rue normalisé pour comparaison : minuscules, sans accents, ß -> ss.

    Équivalent Python de ``lower(unaccent(...))`` côté SQL, espaces réduits.
    Fonction PURE.
    """
    text = (name or "").lower().replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


# Paramètres Lambert belge 72 (EPSG:31370) et transformation de datum WGS84 ->
# BD72 (EPSG « BD72 to WGS 84 (3) », 7 paramètres, convention coordinate frame,
# appliquée en INVERSE) — identiques au pipeline PROJ retenu par QGIS pour
# EPSG:4326 -> EPSG:31370 (précision annoncée : 1 m).
_WGS84_A, _WGS84_F = 6378137.0, 1.0 / 298.257223563
_INTL_A, _INTL_F = 6378388.0, 1.0 / 297.0
_BD72_TO_WGS84 = {  # translations (m), rotations (secondes d'arc), échelle (ppm)
    "tx": -106.8686, "ty": 52.2978, "tz": -103.7239,
    "rx": -0.3366, "ry": 0.457, "rz": -1.8422, "ds": -1.2747,
}
_L72_LON0 = math.radians(4.36748666666667)
_L72_LAT1 = math.radians(51.1666672333333)
_L72_LAT2 = math.radians(49.8333339)
_L72_X0, _L72_Y0 = 150000.013, 5400088.438


def _geodetic_to_ecef(lon, lat, a, f):
    e2 = f * (2 - f)
    n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return (
        n * math.cos(lat) * math.cos(lon),
        n * math.cos(lat) * math.sin(lon),
        n * (1 - e2) * math.sin(lat),
    )


def _ecef_to_geodetic(x, y, z, a, f):
    e2 = f * (2 - f)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(10):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(z + e2 * n * math.sin(lat), p)
    return lon, lat


def wgs84_to_lambert72_pure(lon, lat):
    """WGS84 (lon, lat en degrés) -> Lambert belge 72 (x, y en m), en Python PUR.

    Repli sans PyQGIS (tests, contrôles d'ordre de grandeur) : cartésiennes
    WGS84 -> Helmert 7 paramètres inverse vers BD72 (ellipsoïde Hayford 1924)
    -> conique conforme de Lambert 2SP (paramètres EPSG:31370). Même chaîne
    que PROJ ; écart constaté < 1 cm sur la Belgique. Dans QGIS, le script
    utilise :func:`wgs84_to_lambert` (QgsCoordinateTransform).
    """
    p = _BD72_TO_WGS84
    sec = math.pi / (180.0 * 3600.0)
    rx, ry, rz = p["rx"] * sec, p["ry"] * sec, p["rz"] * sec
    scale = 1.0 + p["ds"] * 1e-6
    xw, yw, zw = _geodetic_to_ecef(math.radians(lon), math.radians(lat), _WGS84_A, _WGS84_F)
    # Inverse de X_w = T + scale * R X_bd (coordinate frame, petites rotations) :
    # X_bd = R^T (X_w - T) / scale.
    dx, dy, dz = (xw - p["tx"]) / scale, (yw - p["ty"]) / scale, (zw - p["tz"]) / scale
    xb = dx - rz * dy + ry * dz
    yb = rz * dx + dy - rx * dz
    zb = -ry * dx + rx * dy + dz
    lam, phi = _ecef_to_geodetic(xb, yb, zb, _INTL_A, _INTL_F)
    e = math.sqrt(_INTL_F * (2 - _INTL_F))

    def m(ph):
        return math.cos(ph) / math.sqrt(1 - (e * math.sin(ph)) ** 2)

    def t(ph):
        es = e * math.sin(ph)
        return math.tan(math.pi / 4 - ph / 2) / ((1 - es) / (1 + es)) ** (e / 2)

    n = (math.log(m(_L72_LAT1)) - math.log(m(_L72_LAT2))) / (
        math.log(t(_L72_LAT1)) - math.log(t(_L72_LAT2))
    )
    big_f = m(_L72_LAT1) / (n * t(_L72_LAT1) ** n)
    r = _INTL_A * big_f * t(phi) ** n   # r0 = 0 (lat_0 = 90°)
    theta = n * (lam - _L72_LON0)
    return _L72_X0 + r * math.sin(theta), _L72_Y0 - r * math.cos(theta)


def lambert72_to_wgs84_pure(x, y):
    """Lambert belge 72 (x, y) -> WGS84 ``(lon, lat)`` en degrés, Python PUR.

    Inverse exact de :func:`wgs84_to_lambert72_pure` (conique inverse, puis
    Helmert BD72 -> WGS84 direct) ; sert aux tests de non-régression des
    emprises de requête (ordre lat/lon). Fonction PURE.
    """
    e = math.sqrt(_INTL_F * (2 - _INTL_F))

    def m(ph):
        return math.cos(ph) / math.sqrt(1 - (e * math.sin(ph)) ** 2)

    def t(ph):
        es = e * math.sin(ph)
        return math.tan(math.pi / 4 - ph / 2) / ((1 - es) / (1 + es)) ** (e / 2)

    n = (math.log(m(_L72_LAT1)) - math.log(m(_L72_LAT2))) / (
        math.log(t(_L72_LAT1)) - math.log(t(_L72_LAT2))
    )
    big_f = m(_L72_LAT1) / (n * t(_L72_LAT1) ** n)
    dx, dy = x - _L72_X0, _L72_Y0 - y
    r = math.copysign(math.hypot(dx, dy), n)
    theta = math.atan2(dx, dy)
    tt = (r / (_INTL_A * big_f)) ** (1.0 / n)
    phi = math.pi / 2 - 2 * math.atan(tt)
    for _ in range(15):
        es = e * math.sin(phi)
        phi = math.pi / 2 - 2 * math.atan(tt * ((1 - es) / (1 + es)) ** (e / 2))
    lam = theta / n + _L72_LON0
    p = _BD72_TO_WGS84
    sec = math.pi / (180.0 * 3600.0)
    rx, ry, rz = p["rx"] * sec, p["ry"] * sec, p["rz"] * sec
    scale = 1.0 + p["ds"] * 1e-6
    xb, yb, zb = _geodetic_to_ecef(lam, phi, _INTL_A, _INTL_F)
    xw = p["tx"] + scale * (xb + rz * yb - ry * zb)
    yw = p["ty"] + scale * (-rz * xb + yb + rx * zb)
    zw = p["tz"] + scale * (ry * xb - rx * yb + zb)
    lon, lat = _ecef_to_geodetic(xw, yw, zw, _WGS84_A, _WGS84_F)
    return math.degrees(lon), math.degrees(lat)


def lambert_bbox_to_wgs84(bbox, to_wgs84):
    """Emprise Lambert 72 ``(xmin, ymin, xmax, ymax)`` -> ``(south, west, north, east)``.

    ``to_wgs84(x, y) -> (lon, lat)`` (QGIS en production, formule pure en
    test). Les 4 coins sont reprojetés (la reprojection tourne légèrement
    l'emprise) ; ordre de sortie = celui d'Overpass : LATITUDES puis
    longitudes. Fonction PURE.
    """
    xmin, ymin, xmax, ymax = bbox
    corners = [to_wgs84(x, y) for x in (xmin, xmax) for y in (ymin, ymax)]
    lons = [lon for lon, _lat in corners]
    lats = [lat for _lon, lat in corners]
    return min(lats), min(lons), max(lats), max(lons)


def lambert72_plausible(x, y) -> bool:
    """Coordonnées vraisemblables en EPSG:31370 (Belgique) ? Fonction PURE."""
    try:
        return (
            LAMBERT72_X_RANGE[0] <= float(x) <= LAMBERT72_X_RANGE[1]
            and LAMBERT72_Y_RANGE[0] <= float(y) <= LAMBERT72_Y_RANGE[1]
        )
    except (TypeError, ValueError):
        return False


@dataclass
class OverpassRequest:
    """Une requête Overpass : noms de rue d'une tuile, emprise serrée (EPSG:31370)."""

    bbox: tuple        # (xmin, ymin, xmax, ymax) en EPSG:31370
    names: tuple       # noms de rue tels qu'extraits des adresses (triés)
    ids: tuple         # intervention_id des points concernés (triés)


def plan_overpass_requests(items, margin_m=OVERPASS_BBOX_MARGIN_M,
                           max_names=OVERPASS_MAX_NAMES_PER_QUERY,
                           max_span_m=OVERPASS_MAX_REQUEST_SPAN_M,
                           grid_m=OVERPASS_BBOX_GRID_M) -> list:
    """Regroupe les points à localiser en requêtes Overpass par NOMS, peu nombreuses.

    ``items`` : ``(intervention_id, nom_de_rue, x, y[, localité])`` en
    EPSG:31370 ; localité = place normalisée, à défaut code postal.

    1. LOTS par couple (rue normalisée, localité normalisée) : deux rues
       homonymes de localités différentes ne partagent jamais un lot ; emprise
       d'un lot = SES points ± ``margin_m``.
    2. REQUÊTES : lots empaquetés dans l'ordre (localité, rue) tant que la
       requête reste sous ``max_names`` rues, sous ``max_span_m`` de côté
       (emprise réunie) et SANS deux lots de même nom de rue (une homonyme
       ne partage jamais l'emprise d'une autre) — tuiles adaptatives : une
       localité entière tient souvent en une requête.

    Emprise arrondie vers l'extérieur à ``grid_m`` m (une même zone redonne
    la même requête : cache efficace). Ordre déterministe. Fonction PURE.
    """
    lots = defaultdict(list)
    for item in items:
        intervention_id, street, x, y = item[:4]
        locality = item[4] if len(item) > 4 else ""
        key = normalize_street_name(street)
        if not key:
            continue
        lots[(normalize_street_name(locality), key)].append((intervention_id, street, x, y))

    def bbox_of(members):
        xs = [m[2] for m in members]
        ys = [m[3] for m in members]
        return (min(xs) - margin_m, min(ys) - margin_m, max(xs) + margin_m, max(ys) + margin_m)

    def union(a, b):
        return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))

    def rounded(box):
        return (
            math.floor(box[0] / grid_m) * grid_m, math.floor(box[1] / grid_m) * grid_m,
            math.ceil(box[2] / grid_m) * grid_m, math.ceil(box[3] / grid_m) * grid_m,
        )

    requests = []
    current = None  # [bbox, noms normalisés, noms bruts, ids]
    for (locality, key) in sorted(lots):
        members = lots[(locality, key)]
        box = bbox_of(members)
        if current is not None:
            merged = union(current[0], box)
            fits = (
                len(current[1]) < max_names
                and key not in current[1]
                and merged[2] - merged[0] <= max_span_m
                and merged[3] - merged[1] <= max_span_m
            )
            if fits:
                current[0] = merged
                current[1].add(key)
                current[2].update(m[1] for m in members)
                current[3].update(m[0] for m in members)
                continue
            requests.append(current)
        current = [box, {key}, {m[1] for m in members}, {m[0] for m in members}]
    if current is not None:
        requests.append(current)
    return [
        OverpassRequest(bbox=rounded(box), names=tuple(sorted(raw)), ids=tuple(sorted(ids)))
        for box, _keys, raw, ids in requests
    ]


# Variantes tolérées dans le filtre de nom Overpass : accents (l'adresse les
# omet souvent), ß/ss, apostrophe droite/typographique, tiret/espace. Groupes
# d'ALTERNATION (pas de classes [..]) : sûrs même si le moteur regex du
# serveur travaille octet par octet sur l'UTF-8.
_ACCENT_VARIANTS = {
    "a": "aàáâäãå", "c": "cç", "e": "eéèêë", "i": "iìíîï", "n": "nñ",
    "o": "oòóôöõ", "u": "uùúûü", "y": "yýÿ",
}
_ERE_METACHARS = set("\\.^$|?*+()[]{}")


def street_name_regex(name) -> str:
    """Regex ERE (sans ancres) reconnaissant ``name`` et ses graphies usuelles.

    Accents ignorés (chaque voyelle -> groupe de ses variantes accentuées,
    minuscules ET majuscules, la casse ASCII étant gérée par le drapeau
    ``,i`` de la requête), ``ß``/``ss`` équivalents, ``'``/``’`` et ``-``/
    espace équivalents, métacaractères regex échappés. Fonction PURE.
    """
    base = unicodedata.normalize("NFKD", " ".join((name or "").split()))
    base = "".join(ch for ch in base if not unicodedata.combining(ch))
    out = []
    i = 0
    while i < len(base):
        ch = base[i]
        low = ch.lower()
        if low == "ß" or (low == "s" and base[i:i + 2].lower() == "ss"):
            out.append("(ss|ß|SS|ẞ)")
            i += 1 if low == "ß" else 2
            continue
        if low in _ACCENT_VARIANTS:
            variants = _ACCENT_VARIANTS[low]
            out.append("(" + "|".join(variants + variants[1:].upper()) + ")")
        elif ch in ("'", "’"):
            out.append("('|’)")
        elif ch in ("-", " "):
            out.append("(-| )")
        elif ch in _ERE_METACHARS:
            out.append("\\" + ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _ql_string(text) -> str:
    """Littéral chaîne Overpass QL entre guillemets (échappe ``\\`` et ``"``)."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_overpass_query(names, south, west, north, east,
                         timeout_s=OVERPASS_QUERY_TIMEOUT_S) -> str:
    """Requête Overpass QL : voies ``highway`` portant l'un des ``names`` dans l'emprise.

    Une clause par clé de :data:`OSM_NAME_KEYS`, TOUTES filtrées par la même
    regex ``^(n1|n2|…)$`` insensible à la casse (:func:`street_name_regex`) :
    seules les rues concernées sont renvoyées, pas le réseau entier.
    Fonction PURE.
    """
    pattern = "^(" + "|".join(street_name_regex(n) for n in names) + ")$"
    bbox = f"({south:.7f},{west:.7f},{north:.7f},{east:.7f})"
    literal = _ql_string(pattern)
    clauses = "".join(
        f'way["highway"]["{key}"~{literal},i]{bbox};' for key in OSM_NAME_KEYS
    )
    return f"[out:json][timeout:{int(timeout_s)}];({clauses});out geom;"


def parse_overpass_ways(data, keep_unnamed=False) -> list:
    """Réponse JSON Overpass -> list[OsmWay] (coords en ``(lon, lat)``).

    Ignore sans lever les éléments non ``way``, sans géométrie exploitable
    (moins de 2 sommets valides) ou mal formés, et — sauf ``keep_unnamed``
    (repli par coordonnées) — les voies sans nom. Fonction PURE.
    """
    elements = data.get("elements") if isinstance(data, dict) else None
    ways = []
    for element in elements or ():
        if not isinstance(element, dict) or element.get("type") != "way":
            continue
        tags = element.get("tags") or {}
        names = []
        for key in OSM_NAME_KEYS:
            normalized = normalize_street_name(tags.get(key))
            if normalized and normalized not in names:
                names.append(normalized)
        if not names and not keep_unnamed:
            continue
        coords = []
        for vertex in element.get("geometry") or ():
            try:
                coords.append((float(vertex["lon"]), float(vertex["lat"])))
            except (KeyError, TypeError, ValueError):
                continue
        if len(coords) < 2:
            continue
        try:
            way_id = int(element["id"])
        except (KeyError, TypeError, ValueError):
            continue
        ways.append(OsmWay(
            way_id=way_id, names=tuple(names),
            highway=str(tags.get("highway") or ""), coords=coords,
            tags=dict(tags), coords_wgs84=tuple(coords),
        ))
    return ways


OVERPASS_MERGE_GAP_M = 300.0
OVERPASS_MERGE_MAX_AREA_M2 = 9_000_000.0


def merge_overpass_requests(requests, max_names=OVERPASS_MAX_NAMES_PER_QUERY,
                            max_side_m=OVERPASS_MAX_REQUEST_SPAN_M,
                            max_gap_m=OVERPASS_MERGE_GAP_M,
                            max_area_m2=OVERPASS_MERGE_MAX_AREA_M2) -> list:
    """Fusionne les requêtes Overpass VOISINES pour en réduire le nombre.

    Deux requêtes fusionnent si leurs emprises se touchent ou sont à moins de
    ``max_gap_m``, que l'union reste sous ``max_side_m`` de côté ET sous
    ``max_area_m2``, sous ``max_names`` noms, et qu'elles ne partagent AUCUN
    nom normalisé (deux rues homonymes de localités différentes ne partagent
    jamais une emprise). Requêtes restent filtrées par noms (ou par types de
    voie pour le repli par coordonnées) ; emprise réunie = union exacte des
    emprises déjà arrondies. Déterministe. Fonction PURE.
    """
    pending = list(requests)

    def gap(a, b):
        dx = max(a[0] - b[2], b[0] - a[2], 0.0)
        dy = max(a[1] - b[3], b[1] - a[3], 0.0)
        return math.hypot(dx, dy)

    merged_any = True
    while merged_any:
        merged_any = False
        for i in range(len(pending)):
            for j in range(i + 1, len(pending)):
                a, b = pending[i], pending[j]
                box = (min(a.bbox[0], b.bbox[0]), min(a.bbox[1], b.bbox[1]),
                       max(a.bbox[2], b.bbox[2]), max(a.bbox[3], b.bbox[3]))
                keys_a = {normalize_street_name(n) for n in a.names}
                keys_b = {normalize_street_name(n) for n in b.names}
                if (
                    gap(a.bbox, b.bbox) > max_gap_m
                    or box[2] - box[0] > max_side_m or box[3] - box[1] > max_side_m
                    or (box[2] - box[0]) * (box[3] - box[1]) > max_area_m2
                    or len(keys_a | keys_b) > max_names
                    or keys_a & keys_b
                ):
                    continue
                pending[i] = OverpassRequest(
                    bbox=box, names=tuple(sorted(set(a.names) | set(b.names))),
                    ids=tuple(sorted(set(a.ids) | set(b.ids))),
                )
                del pending[j]
                merged_any = True
                break
            if merged_any:
                break
    return pending


def parse_overpass_status(text):
    """Attente (s) avant un slot libre d'après ``/api/status`` ; 0 si libre, None si inconnu.

    Formats du serveur : « 2 slots available now. » ou « Slot available
    after: 2026-09-29T12:00:05Z, in 7 seconds. » (une ligne par slot occupé :
    on retient la plus courte). Fonction PURE.
    """
    if not text:
        return None
    now = re.search(r"(\d+)\s+slots?\s+available\s+now", text)
    if now and int(now.group(1)) > 0:
        return 0.0
    waits = [float(v) for v in re.findall(r"in\s+(-?\d+)\s+seconds?", text)]
    if waits:
        return max(0.0, min(waits))
    return None


def retry_after_seconds(headers):
    """Valeur numérique de l'en-tête ``Retry-After`` (secondes), sinon None. PURE."""
    try:
        value = headers.get("Retry-After") if headers is not None else None
        return max(0.0, float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def overpass_wait_s(attempt, backoff_s=OVERPASS_BACKOFF_S, jitter=0.0,
                    retry_after=None, slot_wait=None, max_wait=OVERPASS_MAX_WAIT_S):
    """Attente avant la tentative suivante (exponentielle + gigue, Retry-After, slot).

    ``backoff_s × 2^attempt`` (4 s, 8 s, 16 s…) + ``jitter`` ; au moins
    ``Retry-After`` et l'attente de slot annoncée par /api/status ; plafonnée
    à ``max_wait``. Fonction PURE.
    """
    wait = backoff_s * (2 ** attempt) + jitter
    for extra in (retry_after, slot_wait):
        if extra is not None:
            wait = max(wait, extra)
    return min(wait, max_wait)


def _overpass_status_url(url) -> str:
    return url.rsplit("/", 1)[0] + "/status"


def overpass_fetch(query, user_agent, mirrors=OVERPASS_MIRRORS,
                   timeout=OVERPASS_TIMEOUT_S,
                   fallback_timeout=OVERPASS_FALLBACK_TIMEOUT_S,
                   attempts=OVERPASS_PRIMARY_ATTEMPTS,
                   fallback_attempts=OVERPASS_FALLBACK_ATTEMPTS,
                   backoff_s=OVERPASS_BACKOFF_S,
                   urlopen=None, sleep=None, rng=None, check_status=True):
    """POST ``query`` sur les miroirs Overpass -> dict JSON du premier succès.

    Par miroir (principal : ``attempts`` tentatives, délai ``timeout`` ;
    repli : ``fallback_attempts``, ``fallback_timeout``) : sur HTTP
    429/502/503/504 (surcharge, limitation de débit), nouvelle tentative sur
    le MÊME miroir après :func:`overpass_wait_s` — 4 s, 8 s, 16 s + gigue,
    au moins ``Retry-After`` et l'attente de slot lue sur ``/api/status``
    (plafond 60 s). Avant la 1re tentative sur le principal, ``/api/status``
    est aussi consulté (attente d'un slot libre). Autres erreurs (réseau,
    délai dépassé, JSON invalide, ``remark`` d'erreur : éléments PARTIELS
    inexploitables) : miroir suivant. :class:`OverpassError` si tous
    échouent. ``urlopen``/``sleep``/``rng`` injectables (tests : aucune
    attente réelle).
    """
    urlopen = urlopen or urllib.request.urlopen
    sleep = sleep or time.sleep
    rng = rng or random.random
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    headers = {
        "User-Agent": user_agent,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    def slot_wait(url):
        if not check_status:
            return None
        try:
            request = urllib.request.Request(
                _overpass_status_url(url), headers={"User-Agent": user_agent}
            )
            with urlopen(request, timeout=10) as response:
                return parse_overpass_status(response.read().decode("utf-8", "replace"))
        except Exception:
            return None

    errors = []
    for index, url in enumerate(mirrors):
        primary = index == 0
        tries = max(1, attempts if primary else fallback_attempts)
        if primary:
            wait = slot_wait(url)
            if wait:
                sleep(min(wait, OVERPASS_MAX_WAIT_S))
        for attempt in range(tries):
            request = urllib.request.Request(url, data=body, headers=headers)
            try:
                with urlopen(request, timeout=timeout if primary else fallback_timeout) as response:
                    data = json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                errors.append(f"{url} : HTTP {exc.code}")
                if exc.code in OVERPASS_RETRY_HTTP_CODES and attempt + 1 < tries:
                    sleep(overpass_wait_s(
                        attempt, backoff_s, jitter=rng() * backoff_s / 2,
                        retry_after=retry_after_seconds(getattr(exc, "headers", None)),
                        slot_wait=slot_wait(url) if exc.code in (429, 504) else None,
                    ))
                    continue
                break
            except (urllib.error.URLError, OSError, ValueError) as exc:
                errors.append(f"{url} : {exc}")
                break
            if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
                errors.append(f"{url} : réponse inattendue")
                break
            remark = str(data.get("remark") or "")
            if "error" in remark.lower():
                errors.append(f"{url} : {remark}")
                break
            return data
    raise OverpassError(" ; ".join(errors) or "aucun miroir Overpass configuré")


def overpass_cache_path(cache_dir, query) -> str:
    """Fichier de cache d'une requête : ``<cache_dir>/<sha256(requête)>.json``."""
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, f"{digest}.json")


def overpass_cache_read(path, ttl_s=OVERPASS_CACHE_TTL_S, now=None):
    """Réponse en cache si présente, lisible et de moins de ``ttl_s`` ; sinon ``None``.

    Tolérant : fichier absent, périmé, corrompu ou mal formé -> ``None`` (la
    requête sera simplement refaite), jamais d'exception. Fonction PURE (E/S
    fichier locales seulement).
    """
    now = time.time() if now is None else now
    try:
        if now - os.path.getmtime(path) > ttl_s:
            return None
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        return None
    return data


def overpass_cache_write(path, data) -> bool:
    """Écrit la réponse en cache (écriture atomique) ; échec silencieux -> False."""
    tmp = f"{path}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def fetch_overpass_cached(query, user_agent, cache_dir=None, fetch=None, now=None):
    """Réponse Overpass via le cache disque si possible -> ``(data, depuis_cache)``.

    ``cache_dir`` None -> pas de cache. Seules les réponses RÉUSSIES sont mises
    en cache ; une erreur de ``fetch`` (:class:`OverpassError`) remonte.
    """
    fetch = fetch or overpass_fetch
    path = overpass_cache_path(cache_dir, query) if cache_dir else None
    if path:
        cached = overpass_cache_read(path, now=now)
        if cached is not None:
            return cached, True
    data = fetch(query, user_agent)
    if path:
        overpass_cache_write(path, data)
    return data, False


@dataclass
class OverpassOutcome:
    """Résultat d'une requête planifiée (données, ou erreur isolée)."""

    request: OverpassRequest
    data: Optional[dict]
    error: str
    elapsed_s: float
    from_cache: bool


def run_overpass_requests(requests, fetch, is_canceled=None, pause=None, report=None,
                          max_consecutive_failures=OVERPASS_MAX_CONSECUTIVE_FAILURES,
                          give_up_pause=None, state=None, clock=None) -> list:
    """Exécute les requêtes UNE PAR UNE, chaque échec restant ISOLÉ.

    ``fetch(request) -> (data, depuis_cache)``, lève :class:`OverpassError`.
    L'échec d'une requête n'interrompt pas les suivantes. Coupe-circuit
    (service manifestement indisponible) : seulement après
    ``max_consecutive_failures`` échecs CONSÉCUTIFS **et** si AUCUNE requête
    du run n'a réussi ; on fait alors une dernière pause (``give_up_pause``,
    30 s) et un dernier essai avant de marquer les restantes « non tentées ».
    ``state`` (dict partagé entre les appels d'un même run : requêtes par
    noms puis par coordonnées) porte succès / échecs consécutifs. Annulation :
    requêtes restantes « annulé ». ``pause()`` après chaque requête RÉSEAU,
    ``report(i, n, outcome)`` après chacune. Fonction PURE (effets injectés).
    """
    clock = clock or time.monotonic
    state = state if state is not None else {}
    state.setdefault("successes", 0)
    state.setdefault("consecutive", 0)
    state.setdefault("gave_last_chance", False)
    outcomes = []
    total = len(requests)
    for index, request in enumerate(requests, start=1):
        circuit = (
            state["consecutive"] >= max_consecutive_failures and state["successes"] == 0
        )
        if circuit and not state["gave_last_chance"]:
            state["gave_last_chance"] = True
            if give_up_pause is not None:
                give_up_pause()
            circuit = False  # un dernier essai après la pause
        if is_canceled is not None and is_canceled():
            outcome = OverpassOutcome(request, None, "annulé", 0.0, False)
        elif circuit:
            outcome = OverpassOutcome(
                request, None,
                f"non tentée ({state['consecutive']} échecs consécutifs sans aucun "
                "succès : Overpass indisponible)",
                0.0, False,
            )
        else:
            started = clock()
            try:
                data, from_cache = fetch(request)
                outcome = OverpassOutcome(request, data, "", clock() - started, from_cache)
                state["successes"] += 1
                state["consecutive"] = 0
            except OverpassError as exc:
                outcome = OverpassOutcome(request, None, str(exc), clock() - started, False)
                state["consecutive"] += 1
            if pause is not None and not outcome.from_cache and index < total:
                pause()
        outcomes.append(outcome)
        if report is not None:
            report(index, total, outcome)
    return outcomes


def index_ways_by_name(ways) -> dict:
    """nom normalisé -> voies portant ce nom (triées par way_id, déterministe)."""
    index = defaultdict(list)
    for way in sorted(ways, key=lambda w: w.way_id):
        for name in way.names:
            index[name].append(way)
    return dict(index)


# --- Index spatial par bbox (PUR) ---------------------------------------------
SPATIAL_INDEX_CELL_M = 200.0


def polyline_bbox(coords):
    """Emprise ``(xmin, ymin, xmax, ymax)`` d'une polyligne."""
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_distance(px, py, bbox) -> float:
    """Distance d'un point à une emprise (0 dedans) : minorant de la distance à la voie."""
    dx = max(bbox[0] - px, 0.0, px - bbox[2])
    dy = max(bbox[1] - py, 0.0, py - bbox[3])
    return math.hypot(dx, dy)


class WaySpatialIndex:
    """Grille uniforme (cellules de ``cell`` m) des voies, par emprise.

    ``candidates(x, y, r)`` renvoie les voies dont l'EMPRISE est à au plus
    ``r`` du point — sur-ensemble exact des voies à au plus ``r`` (la
    distance à l'emprise minore la distance à la polyligne) — dans l'ORDRE
    de la liste d'origine : les fonctions qui l'utilisent donnent donc
    STRICTEMENT le même résultat qu'un balayage de toutes les voies (test
    d'équivalence). Pure, sans dépendance.
    """

    def __init__(self, ways, cell=SPATIAL_INDEX_CELL_M):
        self.ways = list(ways)
        self.cell = float(cell)
        self.bboxes = [polyline_bbox(w.coords) for w in self.ways]
        self.grid = defaultdict(list)
        self.by_name = defaultdict(list)
        for way in self.ways:
            for name in way.names:
                self.by_name[name].append(way)
        for index, (xmin, ymin, xmax, ymax) in enumerate(self.bboxes):
            for cx in range(math.floor(xmin / self.cell), math.floor(xmax / self.cell) + 1):
                for cy in range(math.floor(ymin / self.cell), math.floor(ymax / self.cell) + 1):
                    self.grid[(cx, cy)].append(index)
        if self.bboxes:
            self.extent = (
                min(b[0] for b in self.bboxes), min(b[1] for b in self.bboxes),
                max(b[2] for b in self.bboxes), max(b[3] for b in self.bboxes),
            )
        else:
            self.extent = None

    def candidates(self, px, py, radius):
        found = set()
        c = self.cell
        for cx in range(math.floor((px - radius) / c), math.floor((px + radius) / c) + 1):
            for cy in range(math.floor((py - radius) / c), math.floor((py + radius) / c) + 1):
                for index in self.grid.get((cx, cy), ()):
                    if index not in found and bbox_distance(px, py, self.bboxes[index]) <= radius:
                        found.add(index)
        return [self.ways[i] for i in sorted(found)]

    def covers_all(self, px, py, radius) -> bool:
        """Le disque de rayon ``radius`` contient-il l'emprise de TOUTES les voies ?"""
        if self.extent is None:
            return True
        xmin, ymin, xmax, ymax = self.extent
        far_x = max(abs(px - xmin), abs(px - xmax))
        far_y = max(abs(py - ymin), abs(py - ymax))
        return math.hypot(far_x, far_y) <= radius


# Appels SQL par LOTS (localisation en base) : points par lot, cellule de
# regroupement spatial des points d'un même lot.
SQL_BATCH_SIZE = 100
SQL_BATCH_CELL_M = 1000.0


def batch_cell_key(x, y, cell=SQL_BATCH_CELL_M):
    """Clé de tri spatial (cellule de ``cell`` m) : lots de points voisins. PURE."""
    return (math.floor(x / cell), math.floor(y / cell), x, y)


def batch_locate_sql(items, radius) -> str:
    """UNE requête appelant fn_asbuilt_locate_on_road pour tout un lot (LATERAL).

    ``items`` : ``(tag entier, x, y, littéral SQL du nom)`` ; mêmes arguments
    que l'appel point par point (:meth:`_locate_sql`), rayon compris.
    ``WITH ORDINALITY`` conserve l'ordre des lignes de la fonction : la
    PREMIÈRE ligne par tag est celle qu'aurait prise l'appel unitaire
    (``result[0]``, cf. :func:`first_rows_by_tag`). Fonction PURE.
    """
    values = ", ".join(
        f"({int(tag)}, {float(x)!r}::double precision, {float(y)!r}::double precision, "
        f"{literal}::text)"
        for tag, x, y, literal in items
    )
    return (
        "SELECT v.tag, l.road_key, l.position_m, "
        "ST_X(l.projected_point), ST_Y(l.projected_point), l.road_length_m, "
        "ST_X(l.road_start), ST_Y(l.road_start), ST_X(l.road_end), ST_Y(l.road_end) "
        f"FROM (VALUES {values}) AS v(tag, x, y, street) "
        "CROSS JOIN LATERAL public.fn_asbuilt_locate_on_road("
        "ST_SetSRID(ST_MakePoint(v.x, v.y), 31370), v.street, "
        f"{float(radius)!r}) WITH ORDINALITY AS l(road_key, position_m, projected_point, "
        "road_length_m, road_start, road_end, ord) "
        "ORDER BY v.tag, l.ord"
    )


def batch_road_geometry_sql(items, radius) -> str:
    """UNE requête fn_asbuilt_road_geometry (axe + type de voie) pour un lot de routes.

    ``items`` : ``(tag, x, y, littéral du nom)`` — un point représentant par
    road_key, avec le nom qui l'a localisé. Retour : tag, road_key, géométrie
    en WKT, road_highway ; première ligne par tag (WITH ORDINALITY). PURE.
    """
    values = ", ".join(
        f"({int(tag)}, {float(x)!r}::double precision, {float(y)!r}::double precision, "
        f"{literal}::text)"
        for tag, x, y, literal in items
    )
    return (
        "SELECT v.tag, g.road_key, ST_AsText(g.road_geom), g.road_highway "
        f"FROM (VALUES {values}) AS v(tag, x, y, street) "
        "CROSS JOIN LATERAL public.fn_asbuilt_road_geometry("
        "ST_SetSRID(ST_MakePoint(v.x, v.y), 31370), v.street, "
        f"{float(radius)!r}) WITH ORDINALITY AS g(road_key, road_geom, road_highway, ord) "
        "ORDER BY v.tag, g.ord"
    )


def pick_db_road_geometry(row, expected_road_key, road_length_m):
    """Ligne de fn_asbuilt_road_geometry -> ``(parties, highway)`` si RETENUE, sinon None.

    Retenue seulement si road_key IDENTIQUE à celui de la localisation et
    longueur de la géométrie = road_length_m (:func:`road_line_matches`) —
    sinon (fail-closed, autre fusion) l'appelant repasse par Overpass. PURE.
    """
    if not row:
        return None
    found_key, wkt, highway = (tuple(row) + (None, None, None))[:3]
    if str(found_key) != str(expected_road_key):
        return None
    parts = parse_wkt_lines(wkt)
    if not parts or not road_line_matches(parts, road_length_m):
        return None
    return parts, str(highway or "")


def first_rows_by_tag(rows) -> dict:
    """Résultat d'un lot -> dict tag -> 1re ligne (sans le tag). PURE."""
    out = {}
    for row in rows:
        tag = int(row[0])
        if tag not in out:
            out[tag] = tuple(row[1:])
    return out


def highway_allowed_for_coords(highway) -> bool:
    """Type de voie éligible au repli par coordonnées (``*_link`` compris)."""
    value = (highway or "").strip().lower()
    if value.endswith("_link"):
        value = value[: -len("_link")]
    return value in OSM_COORD_HIGHWAYS


def build_overpass_coord_query(south, west, north, east,
                               timeout_s=OVERPASS_QUERY_TIMEOUT_S) -> str:
    """Requête Overpass QL du repli par coordonnées : voies carrossables de l'emprise.

    Filtre ``highway`` par regex (types de :data:`OSM_COORD_HIGHWAYS` et leurs
    ``_link`` ; chemins, pistes, trottoirs exclus), sur une EMPRISE serrée —
    PAS ``around`` : mesuré le 29/09 sur overpass-api.de, ``around:30`` + regex
    renvoie 504 en ~9 s (y compris sur un seul point) quand la même recherche
    par emprise répond en 0,4 s (5 points) à 2 s (tuile de 2 km, 174 voies).
    La distance au rayon est appliquée ensuite en Python. Fonction PURE.
    """
    kinds = "|".join(OSM_COORD_HIGHWAYS)
    bbox = f"({south:.7f},{west:.7f},{north:.7f},{east:.7f})"
    return (
        f"[out:json][timeout:{int(timeout_s)}];"
        f'way["highway"~"^({kinds})(_link)?$"]{bbox};out geom;'
    )


def plan_coord_requests(items, tile_m=OVERPASS_TILE_M,
                        margin_m=OSM_COORD_FALLBACK_RADIUS_M + OSM_COORD_BBOX_EXTRA_M,
                        grid_m=OVERPASS_BBOX_GRID_M) -> list:
    """Regroupe les points du repli par coordonnées en requêtes par tuile.

    ``items`` : ``(intervention_id, x, y)`` en EPSG:31370. Une requête par tuile
    de ``tile_m`` m, emprise = points de la tuile ± ``margin_m`` (rayon + marge),
    arrondie vers l'extérieur à ``grid_m`` m (cache). Fonction PURE.
    """
    tiles = defaultdict(list)
    for intervention_id, x, y in items:
        tiles[(math.floor(x / tile_m), math.floor(y / tile_m))].append((intervention_id, x, y))
    requests = []
    for tile in sorted(tiles):
        members = tiles[tile]
        xs = [m[1] for m in members]
        ys = [m[2] for m in members]
        requests.append(OverpassRequest(
            bbox=(
                math.floor((min(xs) - margin_m) / grid_m) * grid_m,
                math.floor((min(ys) - margin_m) / grid_m) * grid_m,
                math.ceil((max(xs) + margin_m) / grid_m) * grid_m,
                math.ceil((max(ys) + margin_m) / grid_m) * grid_m,
            ),
            names=(),
            ids=tuple(sorted({m[0] for m in members})),
        ))
    return requests


def _way_identity(way):
    """Identité d'une voie pour l'ambiguïté : son nom principal, ou elle-même si sans nom."""
    return ("name", way.names[0]) if way.names else ("way", way.way_id)


def nearest_way(px, py, ways, radius=OSM_COORD_FALLBACK_RADIUS_M,
                ambiguity_m=OSM_COORD_AMBIGUITY_M, preferred_names=(),
                preferred_radius=COORD_PREFERRED_NAME_RADIUS_M, spatial=None):
    """Voie carrossable la plus proche du point, dans le rayon -> ``(voie, raison)``.

    Seules les voies :func:`highway_allowed_for_coords` comptent. Aucune dans
    ``radius`` -> ``(None, 'no_match')``. AMBIGU (carrefour) si une voie
    d'IDENTITÉ différente (autre nom ; une voie sans nom n'est identique qu'à
    elle-même) est à moins de ``ambiguity_m`` m de plus que la plus proche ->
    ``(None, 'ambiguous')``. Les tronçons d'une même rue ne s'excluent pas.
    ``preferred_names`` (noms de référence normalisés : canonique Nominatim,
    nom nettoyé de l'adresse) : une voie portant l'un d'eux est retenue en
    PRIORITÉ jusqu'à ``preferred_radius``, même si une voie d'un autre nom est
    plus proche. Départage déterministe : distance puis way_id. ``spatial``
    (:class:`WaySpatialIndex` des MÊMES voies) : seules les voies dont
    l'emprise est dans le rayon sont examinées — résultat identique. PURE.
    """
    wanted = set(preferred_names)
    if wanted:
        pool = ways if spatial is None else spatial.candidates(px, py, preferred_radius)
        named = sorted(
            (project_on_polyline(px, py, way.coords)[0], way.way_id, way)
            for way in pool
            if highway_allowed_for_coords(way.highway) and wanted & set(way.names)
        )
        if named and named[0][0] <= preferred_radius:
            return named[0][2], None
    candidates = []
    for way in (ways if spatial is None else spatial.candidates(px, py, radius)):
        if not highway_allowed_for_coords(way.highway):
            continue
        dist = project_on_polyline(px, py, way.coords)[0]
        if dist <= radius:
            candidates.append((dist, way.way_id, way))
    if not candidates:
        return None, "no_match"
    candidates.sort(key=lambda c: (c[0], c[1]))
    best_dist, _best_id, best = candidates[0]
    identity = _way_identity(best)
    for dist, _way_id, way in candidates[1:]:
        if dist - best_dist > ambiguity_m:
            break
        if _way_identity(way) != identity:
            return None, "ambiguous"
    return best, None


def locate_on_single_way(px, py, way):
    """Localisation sur une voie SANS NOM : un tronçon isolé, sans fusion.

    road_key ``overpass-noname:<way_id>`` (stable d'un run à l'autre) ;
    position, point projeté et côté comme :func:`locate_on_ways`, bornes =
    celles de la voie. Fonction PURE.
    """
    _dist, position_m, qx, qy, dir_x, dir_y = project_on_polyline(px, py, way.coords)
    coords = way.coords
    return {
        "road_key": f"overpass-noname:{way.way_id}",
        "position_m": position_m,
        "x": qx,
        "y": qy,
        "side": side_of_point(dir_x, dir_y, px - qx, py - qy),
        "highway": way.highway,
        "extent": RoadExtent(
            length_m=polyline_length(coords),
            start_x=coords[0][0], start_y=coords[0][1],
            end_x=coords[-1][0], end_y=coords[-1][1],
        ),
    }


def locate_rows_on_osm(name_items, coord_items, ways,
                       radius=OSM_COORD_FALLBACK_RADIUS_M,
                       ambiguity_m=OSM_COORD_AMBIGUITY_M,
                       preferred_ways=None):
    """Localisation Overpass complète d'un lot : OSM_ID, puis NOM, puis COORDONNÉES.

    ``name_items`` : ``(id, nom(s)_de_rue, x, y)`` — un nom, ou un tuple de noms
    de RÉFÉRENCE essayés dans l'ordre (nom canonique Nominatim puis nom de
    l'adresse, cf. :func:`reference_street_names`) ; ``coord_items`` : ``(id,
    x, y)`` (points sans nom exploitable). ``ways`` : TOUTES les voies
    extraites (EPSG:31370) — un seul index, un seul cache : une rue a le MÊME
    road_key quel que soit le chemin qui y mène. ``preferred_ways`` : dict id
    -> way_id OSM renvoyé par Nominatim pour ce point (objet highway) : l'axe
    le plus sûr.

    0. voie désignée par Nominatim (si extraite et à moins de LOCATE_RADIUS_M) ;
    1. par nom (:func:`locate_on_ways`), noms de référence dans l'ordre ;
    2. sinon — ou sans nom — par coordonnées : voie carrossable la plus proche
       dans ``radius`` (:func:`nearest_way`, ambiguïté au carrefour) ; voie
       nommée -> :func:`locate_on_ways` avec le NOM OSM de cette voie (même
       composante fusionnée, position, côté que par nom) ; voie sans nom ->
       :func:`locate_on_single_way`. Le match note alors si une voie portant
       un nom de référence du point existe à moins de LOCATE_RADIUS_MAX_M
       (``same_name_nearby``, cf. :func:`assess_attachment`).

    1b. sinon, NOM APPROCHANT (:func:`_locate_by_fuzzy_name`, faible confiance) ;
    au repli par coordonnées, une voie portant un nom de référence est
    préférée jusqu'à COORD_PREFERRED_NAME_RADIUS_M.

    Chaque match porte ``method`` ('osm_id'|'name'|'fuzzy'|'coords'), ``way_names``,
    ``distance``. Retourne ``(résultats, raisons, axes)`` : ``résultats`` =
    dict id -> (match, method) ; ``raisons`` = dict id -> 'ambiguous'|
    'no_match' des points non localisés ; ``axes`` = dict road_key ->
    polyligne FUSIONNÉE de l'axe (orientée comme les position_m). PURE.
    """
    preferred_ways = preferred_ways or {}
    ways = list(ways)
    spatial = WaySpatialIndex(ways)  # recherche indexée par bbox (résultat identique)
    by_id = {w.way_id: w for w in ways}
    named_ways = [w for w in ways if w.names]
    index = index_ways_by_name(named_ways)
    cache = {}
    noname_lines = {}
    results = {}
    reasons = {}
    fallback = []
    point_names = {}

    def finish(intervention_id, match, method):
        match["method"] = method
        results[intervention_id] = (match, method)
        reasons.pop(intervention_id, None)

    for intervention_id, streets, x, y in name_items:
        names = (streets,) if isinstance(streets, str) else tuple(n for n in streets if n)
        point_names[intervention_id] = {normalize_street_name(n) for n in names}
        way = by_id.get(preferred_ways.get(intervention_id))
        if way is not None and project_on_polyline(x, y, way.coords)[0] <= LOCATE_RADIUS_M:
            if way.names:
                match, _reason = locate_on_ways(x, y, way.names[0], index, cache=cache)
            else:
                match = locate_on_single_way(x, y, way)
                noname_lines[match["road_key"]] = list(way.coords)
            if match is not None and not _axis_close_enough(match, x, y, way):
                match = None  # axe retenu loin de la voie désignée : refusé
            if match is not None:
                match.setdefault("way_names", way.names)
                match.setdefault("distance", project_on_polyline(x, y, way.coords)[0])
                finish(intervention_id, match, "osm_id")
                continue
        match = None
        for name in names:
            match, reason = locate_on_ways(x, y, name, index, cache=cache)
            if match is not None:
                break
            if reasons.get(intervention_id) != "ambiguous":
                reasons[intervention_id] = reason
        if match is not None:
            finish(intervention_id, match, "name")
            continue
        if reasons.get(intervention_id) != "ambiguous":
            match = _locate_by_fuzzy_name(x, y, names, ways, index, cache, spatial)
            if match is not None:
                finish(intervention_id, match, "fuzzy")
                continue
        reasons.setdefault(intervention_id, "no_match")
        fallback.append((intervention_id, x, y))
    fallback.extend(coord_items)
    for intervention_id, x, y in fallback:
        way, reason = nearest_way(
            x, y, ways, radius, ambiguity_m,
            preferred_names=point_names.get(intervention_id, ()), spatial=spatial,
        )
        lone = False
        if way is None and reason == "no_match":
            # Aucune voie du nom de référence à LOCATE_RADIUS_M : rayon élargi
            # pour la voie carrossable la plus proche (hameau, route sans nom).
            wanted_names = point_names.get(intervention_id, set())
            if not any(
                project_on_polyline(x, y, other.coords)[0] <= LOCATE_RADIUS_M
                for name in wanted_names for other in index.get(name, ())
            ):
                way, reason = nearest_way(
                    x, y, ways, COORD_FALLBACK_LONE_RADIUS_M, ambiguity_m, spatial=spatial,
                )
                lone = way is not None
        if way is None:
            # Un échec par nom « ambigu » reste l'information la plus utile.
            if reasons.get(intervention_id) != "ambiguous":
                reasons[intervention_id] = reason
            continue
        distance = project_on_polyline(x, y, way.coords)[0]
        if way.names:
            match, reason = locate_on_ways(x, y, way.names[0], index, cache=cache)
        else:
            match, reason = locate_on_single_way(x, y, way), None
            noname_lines[match["road_key"]] = list(way.coords)
        if match is not None and not _axis_close_enough(match, x, y, way):
            match, reason = None, "far_axis"
        if match is None:
            reasons[intervention_id] = reason
            continue
        wanted = point_names.get(intervention_id, set())
        match["way_names"] = way.names
        match["distance"] = distance
        if lone:
            match["lone"] = True
            match["low_confidence"] = (
                f"voie sans nom / nom différent, {radius:g}–"
                f"{COORD_FALLBACK_LONE_RADIUS_M:g} m"
            )
        match["same_name_nearby"] = bool(wanted) and not (wanted & set(way.names)) and any(
            project_on_polyline(x, y, other.coords)[0] <= LOCATE_RADIUS_MAX_M
            for name in wanted for other in index.get(name, ())
        )
        finish(intervention_id, match, "coords")
    lines = dict(cache.get("lines", {}))
    lines.update(noname_lines)
    used = {match["road_key"] for match, _method in results.values()}
    return results, reasons, {key: line for key, line in lines.items() if key in used}


def _axis_close_enough(match, px, py, way) -> bool:
    """Invariant : l'axe retenu n'est pas plus loin que la voie visée + AXIS_GUARD_M."""
    target = project_on_polyline(px, py, way.coords)[0]
    return float(match.get("distance") or 0.0) <= target + AXIS_GUARD_M


def _locate_by_fuzzy_name(px, py, names, ways, index, cache, spatial=None):
    """Rattachement par NOM APPROCHANT (« Linden-Allee » pour « Lindenallee »).

    Voie carrossable dont un nom est :func:`fuzzy_name_match` avec un nom de
    référence, à au plus FUZZY_NAME_MAX_DISTANCE_M ; refusé si une voie d'un
    AUTRE nom (non approchant) est plus proche de plus de FUZZY_NAME_MARGIN_M.
    Localisation ensuite par le NOM OSM de cette voie (même composante que
    par nom). Match marqué faible confiance, ou None. Fonction PURE.
    """
    if not names:
        return None
    scored = []
    reach = FUZZY_NAME_MAX_DISTANCE_M + FUZZY_NAME_MARGIN_M
    for way in (ways if spatial is None else spatial.candidates(px, py, reach)):
        if not highway_allowed_for_coords(way.highway) or not way.names:
            continue
        dist = project_on_polyline(px, py, way.coords)[0]
        if dist > FUZZY_NAME_MAX_DISTANCE_M + FUZZY_NAME_MARGIN_M:
            continue
        fuzzy = any(fuzzy_name_match(n, w) for n in names for w in way.names)
        scored.append((dist, way.way_id, way, fuzzy))
    fuzzy_ways = sorted((d, i, w) for d, i, w, f in scored if f and d <= FUZZY_NAME_MAX_DISTANCE_M)
    if not fuzzy_ways:
        return None
    best_dist, _id, best = fuzzy_ways[0]
    if any(not f and d < best_dist - FUZZY_NAME_MARGIN_M for d, _i, _w, f in scored):
        return None
    match, _reason = locate_on_ways(px, py, best.names[0], index, cache=cache)
    if match is None or not _axis_close_enough(match, px, py, best):
        return None
    match["low_confidence"] = (
        f"nom approchant « {best.tags.get('name') or best.names[0]} »"
    )
    return match


_FREEWAY_CLASSES = ("motorway", "trunk")


def assess_attachment(match, point_names=(), hit=None):
    """Score de CONFIANCE d'un rattachement point -> axe, et cause de rejet éventuelle.

    ``match`` : résultat de localisation (``method``, ``distance``,
    ``way_names``, ``highway``, ``same_name_nearby``) ; ``point_names`` : noms
    de référence du point ; ``hit`` : :class:`NominatimHit` du point si géocodé
    À CE RUN (métadonnées en mémoire), sinon None. Rejet (retourne une cause)
    si :

    * le géocodage n'a trouvé qu'une LOCALITÉ (point au centre d'une zone) ;
    * rattachement par coordonnées à plus de OSM_COORD_FALLBACK_RADIUS_M ;
    * nom de la voie différent des noms de référence ET une voie portant l'un
      d'eux existe à proximité (le point appartient sans doute à celle-ci) ;
    * autoroute / voie rapide pour une adresse de bâtiment, sans nom commun.

    Score (0–100, informatif) : 100 − 2/m de distance − 30 si nom différent −
    20 si Nominatim n'a trouvé que la rue − 40 si classe implausible − 60 si
    localité seulement. Retourne ``(score, cause_ou_None)``. Fonction PURE.
    """
    method = match.get("method", "")
    distance = float(match.get("distance") or 0.0)
    wanted = {normalize_street_name(n) for n in point_names if n}
    way_names = set(match.get("way_names") or ())
    name_ok = method in ("db", "name", "fuzzy") or bool(wanted & way_names)
    highway = str(match.get("highway") or "").lower()
    if highway.endswith("_link"):
        highway = highway[: -len("_link")]
    precision = hit.precision if hit is not None else ""
    freeway_odd = highway in _FREEWAY_CLASSES and precision == "house" and not name_ok
    score = 100.0 - 2.0 * distance
    score -= 0 if name_ok else 30
    score -= 20 if precision == "street" else 0
    score -= 40 if freeway_odd else 0
    score -= 60 if precision == "locality" else 0
    score = max(0.0, min(100.0, score))
    if precision == "locality":
        return score, "géocodage imprécis (localité seulement)"
    limit = COORD_FALLBACK_LONE_RADIUS_M if match.get("lone") else OSM_COORD_FALLBACK_RADIUS_M
    if method == "coords" and distance > limit:
        return score, f"voie la plus proche à {distance:.0f} m (> {limit:g} m)"
    if method == "coords" and not name_ok and match.get("same_name_nearby"):
        return score, "nom de voie différent et voie du même nom que l'adresse à proximité"
    if freeway_odd:
        return score, f"classe de voie implausible pour une adresse ({highway})"
    return score, None


# Types de voie acceptés dans ref.osm_roads (ceux importés par Farois :
# classes MAJOR/ARTERIAL/LOCAL) — la fonction SQL filtre aussi.
FAROIS_HIGHWAY_TYPES = (
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential",
)
OSM_STORE_BATCH_SIZE = 500


def osm_oneway(value) -> bool:
    """Tag OSM ``oneway`` -> booléen (yes/true/1/-1 = sens unique). PURE.

    ``-1`` (sens unique inversé) et ``reversible`` seraient REJETÉS par un
    cast ``::boolean`` côté SQL : on envoie toujours un vrai booléen JSON.
    """
    return str(value or "").strip().lower() in ("yes", "true", "1", "-1")


def build_store_payload(ways, already_sent=()):
    """Voies Overpass à envoyer à fn_asbuilt_store_osm_ways -> (objets JSON, ids).

    Filtre : types :data:`FAROIS_HIGHWAY_TYPES`, géométrie WGS84 d'origine
    (≥ 2 sommets), identifiant positif, pas déjà envoyée pendant le run
    (``already_sent``), dédoublonnage par osm_id. ``wkt`` en WGS84
    (``LINESTRING(lon lat, …)``) : la fonction SQL reprojette elle-même.
    Fonction PURE.
    """
    sent = set(already_sent)
    payload = []
    for way in ways:
        if way.way_id <= 0 or way.way_id in sent:
            continue
        if way.highway not in FAROIS_HIGHWAY_TYPES or len(way.coords_wgs84) < 2:
            continue
        sent.add(way.way_id)
        tags = way.tags or {}
        payload.append({
            "osm_id": way.way_id,
            "highway": way.highway,
            "name": str(tags.get("name") or ""),
            "name_de": str(tags.get("name:de") or ""),
            "name_fr": str(tags.get("name:fr") or ""),
            "name_nl": str(tags.get("name:nl") or ""),
            "ref": str(tags.get("ref") or ""),
            "maxspeed": str(tags.get("maxspeed") or ""),
            "surface": str(tags.get("surface") or ""),
            "lanes": str(tags.get("lanes") or ""),
            "oneway": osm_oneway(tags.get("oneway")),
            "wkt": "LINESTRING(" + ", ".join(
                f"{lon:.7f} {lat:.7f}" for lon, lat in way.coords_wgs84
            ) + ")",
        })
    return payload, [item["osm_id"] for item in payload]


def store_osm_ways_sql(payload) -> str:
    """Appel SQL de fn_asbuilt_store_osm_ways avec le lot en JSON, sans injection.

    Le JSON (échappements JSON standard : guillemets, antislashs, contrôles)
    est passé en chaîne « dollar-quoted » dont la balise est choisie ABSENTE du
    texte — apostrophes et antislashs n'y ont aucun sens particulier. PURE.
    """
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    tag, n = "osmw", 0
    while f"${tag}$" in text:
        n += 1
        tag = f"osmw{n}"
    return f"SELECT public.fn_asbuilt_store_osm_ways(${tag}${text}${tag}$::jsonb)"


def build_overpass_ids_query(way_ids, timeout_s=OVERPASS_QUERY_TIMEOUT_S) -> str:
    """Requête Overpass des voies désignées par Nominatim : ``way(id:…);out geom;``."""
    ids = ",".join(str(int(i)) for i in sorted(set(way_ids)))
    return f"[out:json][timeout:{int(timeout_s)}];way(id:{ids});out geom;"


def project_on_polyline(px, py, coords):
    """Projection orthogonale de ``(px, py)`` sur une polyligne.

    Retourne ``(distance, position_m, qx, qy, dir_x, dir_y)`` : distance au
    point projeté ``(qx, qy)``, abscisse curviligne de celui-ci depuis le
    premier sommet, direction du tronçon porteur (sens de la polyligne). À
    distance égale, le premier tronçon gagne (déterministe). Fonction PURE.
    """
    if len(coords) == 1:
        x, y = coords[0]
        return math.hypot(px - x, py - y), 0.0, x, y, 0.0, 0.0
    best = None
    walked = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        vx, vy = x2 - x1, y2 - y1
        seg_sq = vx * vx + vy * vy
        seg_len = math.sqrt(seg_sq)
        t = 0.0
        if seg_sq > 0.0:
            t = min(1.0, max(0.0, ((px - x1) * vx + (py - y1) * vy) / seg_sq))
        qx, qy = x1 + t * vx, y1 + t * vy
        dist = math.hypot(px - qx, py - qy)
        if best is None or dist < best[0]:
            best = (dist, walked + t * seg_len, qx, qy, vx, vy)
        walked += seg_len
    return best


def polyline_length(coords) -> float:
    return sum(
        math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(coords, coords[1:])
    )


def _ways_touch(a, b, tol):
    """Deux voies se raccordent si une extrémité de l'une est à ``tol`` de l'autre."""
    for end in (a.coords[0], a.coords[-1]):
        if project_on_polyline(end[0], end[1], b.coords)[0] <= tol:
            return True
    for end in (b.coords[0], b.coords[-1]):
        if project_on_polyline(end[0], end[1], a.coords)[0] <= tol:
            return True
    return False


def connected_component(seed, candidates, tol=ROAD_JOIN_TOLERANCE_M,
                        max_ways=ROAD_COMPONENT_MAX_WAYS) -> list:
    """Composante connexe de ``seed`` parmi ``candidates`` (même nom), bornée.

    Parcours en largeur, voisins explorés par way_id croissant : même
    composante quel que soit le germe (hors troncature à ``max_ways``).
    Fonction PURE.
    """
    pool = sorted(candidates, key=lambda w: w.way_id)
    # Préfiltre par EMPRISE : deux voies dont les emprises sont à plus de
    # ``tol`` ne peuvent pas se raccorder (résultat identique, sans O(n²)
    # calculs de projection sur les grandes rues).
    boxes = {w.way_id: polyline_bbox(w.coords) for w in pool}
    boxes.setdefault(seed.way_id, polyline_bbox(seed.coords))

    def boxes_close(a, b):
        return not (a[0] - tol > b[2] or b[0] - tol > a[2]
                    or a[1] - tol > b[3] or b[1] - tol > a[3])

    component = [seed]
    seen = {seed.way_id}
    queue = [seed]
    while queue and len(component) < max_ways:
        current = queue.pop(0)
        current_box = boxes.get(current.way_id) or polyline_bbox(current.coords)
        for way in pool:
            if way.way_id in seen or not boxes_close(current_box, boxes[way.way_id]):
                continue
            if not _ways_touch(current, way, tol):
                continue
            seen.add(way.way_id)
            component.append(way)
            queue.append(way)
            if len(component) >= max_ways:
                break
    return sorted(component, key=lambda w: w.way_id)


def split_component_chains(ways, tol=ROAD_JOIN_TOLERANCE_M) -> list:
    """Découpe une composante de voies homonymes en CHAÎNES sans fourche.

    Graphe : nœuds = extrémités de voies regroupées à ``tol`` près, arêtes =
    voies (parcourues par way_id croissant). Une chaîne = portion maximale
    entre deux nœuds qui ne sont pas de degré 2 (bout de rue, carrefour en Y,
    rond-point…) ; les boucles pures forment une chaîne à elles seules.
    Aucune voie n'est abandonnée : chaque voie appartient à exactement une
    chaîne. Orientation DÉTERMINISTE : une chaîne ouverte part de son
    extrémité de plus petites coordonnées ``(x, y)`` ; une boucle part de son
    plus petit nœud, par l'arête de plus petit way_id. Rue simple (aucune
    fourche) -> une seule chaîne, identique à l'ancienne fusion.

    Retourne une liste de ``(way_ids triés, coords)`` triée par plus petit
    way_id. Fonction PURE.
    """
    nodes = []

    def node_of(pt):
        for idx, node in enumerate(nodes):
            if math.hypot(pt[0] - node[0], pt[1] - node[1]) <= tol:
                return idx
        nodes.append(pt)
        return len(nodes) - 1

    edges = []
    for way in sorted(ways, key=lambda w: w.way_id):
        edges.append((node_of(way.coords[0]), node_of(way.coords[-1]), way))
    degree = Counter()
    incident = defaultdict(list)
    for idx, (u, v, way) in enumerate(edges):
        degree[u] += 1
        degree[v] += 1
        incident[u].append(idx)
        if v != u:
            incident[v].append(idx)
    visited = set()

    def walk(start, first_edge):
        path, used = [], []
        current, idx = start, first_edge
        while True:
            visited.add(idx)
            used.append(edges[idx][2].way_id)
            u, v, way = edges[idx]
            coords = list(way.coords) if u == current else list(reversed(way.coords))
            path.extend(coords if not path else coords[1:])
            current = v if u == current else u
            if degree[current] != 2 or current == start:
                break
            nxt = [i for i in sorted(incident[current], key=lambda i: edges[i][2].way_id)
                   if i not in visited]
            if not nxt:
                break
            idx = nxt[0]
        return path, used

    chains = []
    # Chaînes ouvertes : départ de chaque nœud qui n'est pas de degré 2.
    for node in sorted((n for n in range(len(nodes)) if degree[n] != 2),
                       key=lambda n: nodes[n]):
        for idx in sorted(incident[node], key=lambda i: edges[i][2].way_id):
            if idx in visited:
                continue
            path, used = walk(node, idx)
            if tuple(path[-1]) < tuple(path[0]):
                path = list(reversed(path))
            chains.append((sorted(used), path))
    # Boucles pures (tous nœuds de degré 2).
    while len(visited) < len(edges):
        rest = [i for i in range(len(edges)) if i not in visited]
        start = min({edges[i][0] for i in rest} | {edges[i][1] for i in rest},
                    key=lambda n: nodes[n])
        first = min((i for i in rest if start in edges[i][:2]),
                    key=lambda i: edges[i][2].way_id)
        path, used = walk(start, first)
        chains.append((sorted(used), path))
    return sorted(chains, key=lambda c: c[0][0])


def merge_component(ways, tol=ROAD_JOIN_TOLERANCE_M, seed_way_id=None) -> list:
    """Polyligne orientée de la composante — sans JAMAIS abandonner le germe.

    Rue simple : toutes les voies fusionnées (une chaîne). Composante
    ramifiée : la CHAÎNE (cf. :func:`split_component_chains`) qui contient la
    voie ``seed_way_id`` (à défaut, la première chaîne). Fonction PURE.
    """
    chains = split_component_chains(ways, tol)
    for way_ids, coords in chains:
        if seed_way_id is None or seed_way_id in way_ids:
            return coords
    return chains[0][1] if chains else []


def homonym_decision(d_best, d_other) -> str:
    """Deux composantes homonymes non connectées -> 'ambiguous' | 'low' | 'ok'.

    * 'ambiguous' en QUASI-ÉGALITÉ : 2e à moins de COMPONENT_TIE_GAP_M de plus
      ET rapport < COMPONENT_TIE_RATIO ; ou, quand les DEUX sont à plus de
      COMPONENT_FAR_M, selon la règle historique (écart < 15 m OU rapport <
      1,5) ;
    * 'low' : la plus proche l'emporte mais la marge est < COMPONENT_LOW_CONF_GAP_M
      (rattachement marqué faible confiance) ;
    * 'ok' : la plus proche l'emporte nettement. Fonction PURE.
    """
    gap = d_other - d_best
    ratio = d_other / d_best if d_best > 0 else float("inf")
    if gap < COMPONENT_TIE_GAP_M and ratio < COMPONENT_TIE_RATIO:
        return "ambiguous"
    if d_best > COMPONENT_FAR_M and d_other > COMPONENT_FAR_M and (
        gap < COMPONENT_AMBIGUITY_GAP_M or ratio < COMPONENT_AMBIGUITY_RATIO
    ):
        return "ambiguous"
    return "low" if gap < COMPONENT_LOW_CONF_GAP_M else "ok"


def homonym_components_ambiguous(d_best, d_other) -> bool:
    """Compatibilité : vrai si :func:`homonym_decision` rend 'ambiguous'."""
    return homonym_decision(d_best, d_other) == "ambiguous"


_STREET_TYPE_ALIASES = (
    (r"strasse\b", "str"), (r"str\.?(?=\s|$)", "str"), (r"straat\b", "str"),
    (r"allee\b", "alle"), (r"alee\b", "alle"),
)


def compact_street_name(name) -> str:
    """Forme compacte pour la comparaison APPROCHANTE de noms de rue. PURE.

    :func:`normalize_street_name` puis : suffixes de type unifiés
    (strasse/str./straat -> « str », allee/alee -> « alle »), espaces,
    tirets, apostrophes et points retirés.
    """
    text = normalize_street_name(name)
    for pattern, repl in _STREET_TYPE_ALIASES:
        text = re.sub(pattern, repl, text)
    return re.sub(r"[\s\-'’.]", "", text)


def fuzzy_name_match(a, b, min_ratio=FUZZY_NAME_RATIO) -> bool:
    """Deux noms de rue APPROCHANTS (formes compactes égales ou ratio difflib ≥ seuil) ?"""
    ca, cb = compact_street_name(a), compact_street_name(b)
    if not ca or not cb:
        return False
    return ca == cb or difflib.SequenceMatcher(None, ca, cb).ratio() >= min_ratio


def diagnose_unlocated(px, py, names, ways, radius=OSM_COORD_FALLBACK_RADIUS_M,
                       spatial=None):
    """Cause lisible d'un point non localisé + distance à la voie nommée la plus proche.

    ``names`` : noms de référence du point ; ``ways`` : voies extraites
    (EPSG:31370). Retourne ``(cause, distance_m_ou_None)`` :

    * « voie du même nom trop loin » — une voie portant l'un des noms existe
      (distance = la plus proche de ce nom) ;
    * « nom introuvable » — aucune voie de ce nom, mais des voies carrossables
      dans ``radius`` (distance = voie nommée la plus proche) ;
    * « aucune voie à proximité » — rien de carrossable dans ``radius``.

    L'ambiguïté est diagnostiquée en amont (raison 'ambiguous'). PURE.
    """
    wanted = {normalize_street_name(n) for n in names if n}
    if spatial is not None:
        # Recherche par anneaux croissants : la voie nommée la plus proche
        # trouvée à r est la plus proche de toutes (les autres sont à > r).
        # Même nom : toutes les voies de ce nom (index par nom, peu nombreuses).
        same = min(
            (project_on_polyline(px, py, w.coords)[0]
             for name in wanted for w in spatial.by_name.get(name, ())),
            default=None,
        )
        reach = max(radius, spatial.cell)
        while True:
            pool = spatial.candidates(px, py, reach)
            dists = [(project_on_polyline(px, py, w.coords)[0], w) for w in pool]
            named = min((d for d, w in dists if w.names), default=None)
            if spatial.covers_all(px, py, reach) or (named is not None and named <= reach):
                break
            reach *= 4
        carrossable_near = any(
            highway_allowed_for_coords(w.highway) and d <= radius for d, w in dists
        )
        if same is not None:
            return "voie du même nom trop loin", same
        if carrossable_near:
            return "nom introuvable", named
        return "aucune voie à proximité", named
    same, named = None, None
    carrossable_near = False
    for way in ways:
        dist = project_on_polyline(px, py, way.coords)[0]
        if wanted & set(way.names):
            same = dist if same is None else min(same, dist)
        if way.names:
            named = dist if named is None else min(named, dist)
        if highway_allowed_for_coords(way.highway) and dist <= radius:
            carrossable_near = True
    if same is not None:
        return "voie du même nom trop loin", same
    if carrossable_near:
        return "nom introuvable", named
    return "aucune voie à proximité", named


# Classes de voie admises pour un rattachement PAR NOM (plus petit = prioritaire).
_NAME_TIER_1 = (
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "road",
)
_NAME_TIER_2 = ("living_street", "service")
_NAME_TIER_3 = ("pedestrian",)


def name_match_tier(highway):
    """Priorité d'une voie pour le rattachement par nom (1, 2, 3) ou None (exclue).

    1 : voies carrossables (classes Farois et leurs ``_link``) ; 2 : zone de
    rencontre, desserte — seulement sans voie de rang 1 homonyme dans le
    rayon ; 3 : voie piétonne, en dernier recours ; None : chemins agricoles,
    sentiers, trottoirs, pistes cyclables, escaliers… jamais cible d'un
    rattachement d'adresse. Fonction PURE.
    """
    value = (highway or "").strip().lower()
    if value.endswith("_link"):
        value = value[: -len("_link")]
    if value in _NAME_TIER_1:
        return 1
    if value in _NAME_TIER_2:
        return 2
    if value in _NAME_TIER_3:
        return 3
    return None


def locate_on_ways(px, py, street_name, ways_by_name, radius=LOCATE_RADIUS_M,
                   tol=ROAD_JOIN_TOLERANCE_M, max_ways=ROAD_COMPONENT_MAX_WAYS,
                   cache=None):
    """Équivalent Python de fn_asbuilt_locate_on_road sur des voies OSM (EPSG:31370).

    1. voies dont un nom normalisé égale celui de la rue, à ``radius`` m au
       plus (défaut 40, borné à LOCATE_RADIUS_MAX_M) ; aucune -> ``no_match`` ;
    2. germe = la plus proche (puis plus petit way_id) ; composante connexe
       des voies du même nom (raccord ``tol``, bornée à ``max_ways``) ;
    3. rues homonymes NON connectées dans le rayon -> ``ambiguous`` (omis) ;
    4. la composante est découpée en CHAÎNES sans fourche
       (:func:`split_component_chains` : carrefour en Y, rond-point, chaussées
       séparées) ; le point se rattache à la chaîne qui CONTIENT le germe —
       road_key = nom + plus petit way_id de la chaîne, ligne mise en cache :
       tous les points d'une même chaîne ont des position_m comparables et
       seuls eux s'apparient ; garde d'invariant : ligne retenue à au plus
       distance du germe + AXIS_GUARD_M, sinon ``far_axis`` ;
    5. projection orthogonale -> position_m, point projeté, côté (produit
       vectoriel direction locale × projeté->point), highway du germe.

    Retourne ``(match, reason)`` : ``match`` = dict road_key/position_m/x/y/
    side/highway/extent (RoadExtent), ``reason`` None ; ou ``(None,
    'no_match'|'ambiguous'|'far_axis')``. ``cache`` : dict partagé entre appels d'un
    même lot. Fonction PURE.
    """
    radius = min(max(float(radius), 0.0), LOCATE_RADIUS_MAX_M)
    cache = {} if cache is None else cache
    lines = cache.setdefault("lines", {})
    key_of_way = cache.setdefault("key_of_way", {})

    name = normalize_street_name(street_name)
    candidates = ways_by_name.get(name, []) if name else []
    near = []
    for way in candidates:
        tier = name_match_tier(way.highway)
        if tier is None:
            continue  # chemin agricole, sentier, trottoir… : jamais cible par nom
        dist = project_on_polyline(px, py, way.coords)[0]
        if dist <= radius:
            near.append((dist, way.way_id, way, tier))
    if not near:
        return None, "no_match"
    # Classe de voie : carrossable « Farois » d'abord ; desserte / zone de
    # rencontre seulement sans carrossable homonyme dans le rayon ; voie
    # piétonne en tout dernier recours (run réel : un chemin agricole portant
    # le nom de la rue, à 0 m, captait les points de la secondary à 35 m).
    tier = min(item[3] for item in near)
    candidates = [
        w for w in candidates
        if name_match_tier(w.highway) is not None and name_match_tier(w.highway) <= tier
    ]
    near = sorted(
        ((d, i, w) for d, i, w, t in near if t <= tier), key=lambda item: (item[0], item[1])
    )
    seed = near[0][2]

    # key_of_way : voie -> identifiant de sa COMPOSANTE (ambiguïté entre
    # homonymes non raccordés) ; chains : composante -> ses CHAÎNES sans
    # fourche (:func:`split_component_chains`), chacune entité routière propre.
    chains_of = cache.setdefault("chains", {})

    def register(component):
        comp_key = f"overpass:{name}:{component[0].way_id}"
        for member in component:
            key_of_way.setdefault((name, tier, member.way_id), comp_key)
        if (tier, comp_key) not in chains_of:
            chains_of[(tier, comp_key)] = split_component_chains(component, tol)
        return comp_key

    road_key = key_of_way.get((name, tier, seed.way_id))
    if road_key is None:
        road_key = register(connected_component(seed, candidates, tol, max_ways))
    if any(key_of_way.get((name, tier, way.way_id)) != road_key for _, _, way in near):
        # Voisins pas encore rattachés : les classer avant de conclure.
        for _, _, way in near:
            if (name, tier, way.way_id) not in key_of_way:
                register(connected_component(way, candidates, tol, max_ways))
        # Distance la plus courte de chaque AUTRE composante homonyme du rayon.
        others = {}
        for dist, _way_id, way in near:
            key = key_of_way.get((name, tier, way.way_id))
            if key != road_key:
                others[key] = min(dist, others.get(key, dist))
        best = near[0][0]
        decision = homonym_decision(best, min(others.values())) if others else "ok"
        if decision == "ambiguous":
            return None, "ambiguous"
        low_confidence = (
            "homonyme non raccordé proche (marge < "
            f"{COMPONENT_LOW_CONF_GAP_M:g} m)" if decision == "low" else ""
        )
    else:
        low_confidence = ""

    # CHAÎNE retenue : celle qui contient le germe (jamais une portion
    # lointaine d'un axe fusionné ramifié — bug du 29/09, Hauptstraße de Sankt
    # Vith rattachée à 125 m) ; garde d'invariant : la distance à la ligne
    # retenue ne dépasse pas celle du germe de plus de AXIS_GUARD_M.
    seed_dist = near[0][0]
    chains = chains_of[(tier, road_key)]
    ordered = sorted(
        chains, key=lambda c: (seed.way_id not in c[0], c[0][0])
    )
    chosen = None
    for way_ids, coords in ordered:
        projection = project_on_polyline(px, py, coords)
        if projection[0] <= seed_dist + AXIS_GUARD_M:
            chosen = (way_ids, coords, projection)
            break
    if chosen is None:
        return None, "far_axis"
    way_ids, line, (dist, position_m, qx, qy, dir_x, dir_y) = chosen
    road_key = f"overpass:{name}:{way_ids[0]}"
    lines.setdefault(road_key, line)
    if dist > radius:
        return None, "no_match"
    return {
        "road_key": road_key,
        "position_m": position_m,
        "x": qx,
        "y": qy,
        "side": side_of_point(dir_x, dir_y, px - qx, py - qy),
        "highway": seed.highway,
        "way_id": seed.way_id,
        "way_names": seed.names,
        "distance": dist,
        "low_confidence": low_confidence,
        "extent": RoadExtent(
            length_m=polyline_length(line),
            start_x=line[0][0], start_y=line[0][1],
            end_x=line[-1][0], end_y=line[-1][1],
        ),
    }, None


def build_locate_failure_warning(n_rows, n_located, n_no_street, n_no_match,
                                 overpass_status=None):
    """Avertissement actionnable quand AUCUN point n'a pu être localisé sur un axe.

    Retourne ``None`` s'il n'y a rien à signaler (aucun point à localiser, ou
    au moins un point localisé). Sinon, un message expliquant pourquoi aucun
    segment ne sera créé, ventilé selon la cause dominante :

    * ``n_no_match`` > 0 — aucun tronçon nommé correspondant près des points,
      ni dans ``ref.osm_roads`` (constaté : table limitée à Bruxelles alors que
      les points sont dans l'est du pays), ni via le repli Overpass selon
      ``overpass_status`` (``None`` = non tenté, ``'ok'`` = tenté sans
      résultat, ``'failed'`` = injoignable) ;
    * ``n_no_street`` seul — aucun nom de rue extractible des adresses
      (format d'adresse inattendu), la couverture OSM n'est pas en cause.

    Les échecs de connexion/fonction sont signalés séparément par l'appelant
    (``reportError``) : ce message ne les couvre pas. Fonction PURE.
    """
    if n_rows <= 0 or n_located > 0:
        return None
    message = (
        f"Segments : aucun des {n_rows} point(s) à localiser n'a pu être "
        f"rattaché à un axe de rue ({n_no_street} sans nom de rue extractible "
        f"de l'adresse, {n_no_match} sans tronçon nommé correspondant à "
        "proximité) — aucun segment ne peut être créé."
    )
    if n_no_match > 0:
        if overpass_status == "failed":
            message += (
                " La table ref.osm_roads ne couvre pas ces points et "
                "l'extraction OSM de repli (API Overpass) a échoué : vérifiez "
                "l'accès Internet/proxy puis relancez, ou importez les routes "
                "OSM de la zone dans ref.osm_roads."
            )
        elif overpass_status == "ok":
            message += (
                " Ni ref.osm_roads ni l'extraction OSM de repli (API Overpass) "
                "ne contiennent de voie portant ces noms à proximité : "
                "vérifiez l'orthographe des rues dans les rapports (ou les "
                "noms OSM de la zone)."
            )
        else:
            message += (
                " Cause la plus probable : la table ref.osm_roads ne contient "
                "pas de routes à proximité de ces points (couverture OSM "
                "partielle). Importez les routes OSM de la zone concernée "
                "dans ref.osm_roads, puis relancez l'algorithme."
            )
    else:
        message += (
            " Aucun nom de rue n'a pu être extrait des adresses : vérifiez le "
            "format de la colonne Address des rapports."
        )
    return message


def _normalize_pg_identity(ident):
    """Normalise un dict d'identité de table PostgreSQL (cf. same_postgres_table).

    Schéma vide -> ``public`` (table non qualifiée), port vide -> ``5432``,
    hôte en minuscules (insensible à la casse, contrairement aux noms de
    schéma/table/base, sensibles à la casse côté PostgreSQL).
    """
    return {
        "schema": (ident.get("schema") or "").strip() or "public",
        "table": (ident.get("table") or "").strip(),
        "database": (ident.get("database") or "").strip(),
        "host": (ident.get("host") or "").strip().lower(),
        "port": (ident.get("port") or "").strip() or "5432",
        "service": (ident.get("service") or "").strip(),
    }


def same_postgres_table(a, b) -> bool:
    """Indique si deux sources PostgreSQL désignent la MÊME table.

    ``a``/``b`` : dicts ``schema``/``table``/``database``/``host``/``port``/
    ``service`` (extraits d'un ``QgsDataSourceUri`` par l'appelant). La
    comparaison porte sur la source de données, jamais sur le nom de couche
    (renommable librement dans le projet) :

    * schéma et table identiques — obligatoire ;
    * puis identité du serveur : même ``service`` si les deux en ont un, sinon
      même hôte + port + base si aucun n'en a ;
    * cas MIXTE (l'une via ``service``, l'autre via hôte) : non décidable sans
      résoudre le fichier de services -> repli sur la seule base (non vide et
      identique), pour privilégier l'absence de DOUBLON dans le projet.

    Une colonne géométrique ou un filtre (``sql``) différent n'y changent rien :
    la table est considérée comme déjà présente. Fonction PURE.
    """
    na, nb = _normalize_pg_identity(a), _normalize_pg_identity(b)
    if not na["table"] or na["schema"] != nb["schema"] or na["table"] != nb["table"]:
        return False
    if na["service"] and nb["service"]:
        return na["service"] == nb["service"] and na["database"] == nb["database"]
    if not na["service"] and not nb["service"]:
        return (
            na["host"] == nb["host"]
            and na["port"] == nb["port"]
            and na["database"] == nb["database"]
        )
    return bool(na["database"]) and na["database"] == nb["database"]


def address_key(address: Optional[str], postal_code: Optional[str] = None) -> str:
    """Clé de comparaison d'une adresse : casse et espaces neutralisés.

    ``"Rue de la Gare  12"`` et ``"rue de la gare 12"`` donnent la même clé ;
    le code postal normalisé (4 chiffres) est ajouté s'il est connu. Fonction
    PURE. Chaîne vide si l'adresse est vide.
    """
    text = re.sub(r"\s+", " ", (address or "").strip()).casefold()
    if not text:
        return ""
    postal4 = extract_postal4(postal_code) or ""
    return f"{text}|{postal4}"


def build_known_keys(rows) -> tuple:
    """Index des points déjà présents en base 'be'.

    ``rows`` : itérable de ``(intervention_id, work_order, address_raw,
    postal_code)`` (lignes de ``geofiber_asbuilt_depth_points`` ayant une
    géométrie). Retourne ``(interventions, work_order_addresses)`` : l'ensemble
    des ``intervention_id`` et l'ensemble des couples ``(work_order,
    address_key)``. Fonction PURE.
    """
    interventions: set = set()
    work_order_addresses: set = set()
    for intervention_id, work_order, address_raw, postal_code in rows:
        if intervention_id not in (None, ""):
            interventions.add(str(intervention_id))
        key = address_key(address_raw, postal_code)
        if work_order and key:
            work_order_addresses.add((str(work_order).strip(), key))
    return interventions, work_order_addresses


def is_already_present(rec, interventions, work_order_addresses) -> bool:
    """Vrai si ``rec`` est déjà géocodé en base : même intervention, OU même
    work order avec la même adresse (on ne géocode ni ne recrée de segment).

    Un même work order peut couvrir plusieurs adresses : une adresse nouvelle
    sous un work order connu reste à traiter. Fonction PURE.
    """
    if rec.intervention in interventions:
        return True
    key = address_key(rec.address, rec.postal_code)
    return bool(
        rec.work_order and key
        and (rec.work_order.strip(), key) in work_order_addresses
    )


# ===========================================================================
# Wrapper QGIS Processing — fin, orchestration uniquement
# ===========================================================================
if HAS_QGIS:

    # Drapeau « paramètre avancé » : enum Qgis.ProcessingParameterFlag depuis
    # QGIS 3.36, QgsProcessingParameterDefinition.FlagAdvanced avant.
    try:
        _ADVANCED_PARAMETER_FLAG = Qgis.ProcessingParameterFlag.Advanced
    except AttributeError:  # QGIS < 3.36
        _ADVANCED_PARAMETER_FLAG = QgsProcessingParameterDefinition.FlagAdvanced

    BE_CONNECTION_NAME = "be"
    BE_TABLE_SCHEMA = "public"
    BE_TABLE_NAME = "geofiber_asbuilt_depth_points"
    BE_GEOM_COLUMN = "geom"

    UNGEOCODED_TABLE_SCHEMA = "public"
    UNGEOCODED_TABLE_NAME = "geofiber_asbuilt_ungeocoded"

    SEGMENTS_TABLE_SCHEMA = "public"
    SEGMENTS_TABLE_NAME = "geofiber_asbuilt_depth_segments"

    CONNECTORS_TABLE_SCHEMA = "public"
    CONNECTORS_TABLE_NAME = "geofiber_asbuilt_depth_connectors"

    # Noms lisibles des deux couches de la base 'be' ajoutées au projet en fin
    # d'exécution (cf. _load_be_layers_in_project) — seulement si absentes.
    BE_POINTS_LAYER_NAME = "Profondeur As-Built — points"
    BE_SEGMENTS_LAYER_NAME = "Profondeur As-Built — segments d'axe de rue"
    BE_CONNECTORS_LAYER_NAME = "Profondeur As-Built — connecteurs"

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

    def _str_or_empty(value) -> str:
        """Valeur d'attribut texte, NULL (QVariant) ou autre -> chaîne vide."""
        return value if isinstance(value, str) else ""

    def _point_state(feat) -> dict:
        """État d'un point en base utile aux segments (cf. point_changed)."""
        x = y = None
        geom = feat.geometry()
        if geom is not None and not geom.isEmpty():
            try:
                pt = geom.asPoint()
                x, y = pt.x(), pt.y()
            except (TypeError, ValueError):
                pass
        return {
            "depth_category": _str_or_empty(feat["depth_category"]),
            "address_raw": _str_or_empty(feat["address_raw"]),
            "x": x, "y": y,
        }

    def _pg_identity(ds_uri) -> dict:
        """Identité de table d'un ``QgsDataSourceUri`` postgres (cf. same_postgres_table)."""
        return {
            "schema": ds_uri.schema(),
            "table": ds_uri.table(),
            "database": ds_uri.database(),
            "host": ds_uri.host(),
            "port": ds_uri.port(),
            "service": ds_uri.service(),
        }

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

        Utilisée aux DEUX points de style (couche de la base 'be' ajoutée au
        projet ET style par défaut synchronisé dans ``layer_styles``, cf.
        :func:`_sync_style_to_db`) : ils partagent donc exactement la même source.
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
        # Pas de catégorie « manquante » : les points gris ne produisent aucun
        # segment (comme dans style/depth_segments.qml).
        categories = []
        for value in ("vert", "orange", "rouge"):
            color = DEPTH_COLORS[value]
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
        _upsert_geocoded_records / _sync_segments). Appel + interpretation du
        retour : cf. _save_style_to_db.
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

    def lambert_transforms(transform_context=None):
        """Transformations (WGS84 -> Lambert 72, Lambert 72 -> WGS84), créées une fois par run.

        Contexte de transformation du projet (choix de l'opération de datum,
        ici « BD72 to WGS 84 » comme PROJ), SANS lien avec le SCR du projet ni
        de ses couches.
        """
        context = transform_context or QgsProject.instance().transformContext()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        lambert = QgsCoordinateReferenceSystem(BELGIAN_LAMBERT_AUTHID)
        return (
            QgsCoordinateTransform(wgs84, lambert, context),
            QgsCoordinateTransform(lambert, wgs84, context),
        )

    def wgs84_to_lambert(lon, lat, transform=None):
        """WGS84 -> Lambert belge 72 (x, y en m). SEUL point d'entrée des reprojections.

        ORDRE DES AXES : QgsPointXY(x = lon, y = lat) — QGIS travaille toujours
        en (longitude, latitude) pour EPSG:4326, quel que soit l'ordre « officiel »
        de l'EPSG. ``transform`` : premier élément de :func:`lambert_transforms`.
        Lève QgsCsException sur échec.
        """
        transform = transform or lambert_transforms()[0]
        point = transform.transform(QgsPointXY(lon, lat))
        return point.x(), point.y()

    def lambert_to_wgs84(x, y, transform=None):
        """Lambert belge 72 -> WGS84 ``(lon, lat)`` (emprises des requêtes Overpass)."""
        transform = transform or lambert_transforms()[1]
        point = transform.transform(QgsPointXY(x, y))
        return point.x(), point.y()

    def _force_target_crs(layer, feedback=None, label="", always_log=False):
        """Force le SCR EPSG:31370 sur une couche des tables 'be' ; retourne l'authid constaté.

        Les tables 'be' sont TOUTES en SRID 31370 (points, segments,
        ref.osm_roads), mais le SCR que QGIS attribue à la couche peut dériver :
        introspection peu fiable de la connexion (estimatedmetadata), URI sans
        srid, SCR invalide remplacé au chargement par celui du projet ou du fond
        de carte (constaté : points affichés en EPSG:3857, dans le golfe de
        Guinée). On ne lit donc jamais ``layer.crs()`` comme une vérité : on
        FORCE 31370 (:func:`crs_needs_fix`) et on avertit si l'authid différait.
        Le SCR du PROJET n'est jamais modifié.
        """
        crs = layer.crs()
        authid = crs.authid() if crs is not None and crs.isValid() else ""
        if crs_needs_fix(authid):
            layer.setCrs(QgsCoordinateReferenceSystem(BELGIAN_LAMBERT_AUTHID))
            if crs_needs_fix(layer.crs().authid()):
                # Repli : réassigner la source puis forcer à nouveau.
                try:
                    layer.setDataSource(layer.source(), layer.name(), "postgres")
                except Exception:  # pragma: no cover - défensif
                    pass
                layer.setCrs(QgsCoordinateReferenceSystem(BELGIAN_LAMBERT_AUTHID))
            if feedback is not None:
                feedback.pushWarning(
                    f"Couche {label} : SCR {authid or 'invalide/inconnu'} constaté, "
                    f"corrigé en {BELGIAN_LAMBERT_AUTHID} (coordonnées Lambert 72 en base)."
                )
        elif feedback is not None and always_log:
            feedback.pushInfo(f"Couche {label} : SCR {BELGIAN_LAMBERT_AUTHID} (forcé).")
        return authid

    def _apply_connectors_style(layer, feedback=None) -> bool:
        """Style connecteurs (``style/depth_connectors.qml`` ; repli : fin pointillé catégorisé)."""
        try:
            profile_dir = QgsApplication.qgisSettingsDirPath()
        except Exception:  # pragma: no cover - défensif
            profile_dir = None
        qml_path = _collection_style_qml_path(_DEPTH_CONNECTORS_STYLE_QML_NAME, profile_dir)
        if qml_path is not None:
            try:
                if _named_style_loaded_ok(layer.loadNamedStyle(qml_path)):
                    return True
            except Exception:  # pragma: no cover - défensif
                pass
        if feedback is not None:
            feedback.pushInfo("Style connecteurs non appliqué — repli sur un rendu minimal.")
        categories = []
        for value in ("vert", "orange", "rouge"):
            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.LineGeometry)
            symbol.setColor(QColor(DEPTH_COLORS[value]))
            symbol.setWidth(0.35)
            categories.append(QgsRendererCategory(value, symbol, DEPTH_CATEGORY_LABELS[value]))
        layer.setRenderer(QgsCategorizedSymbolRenderer("depth_category", categories))
        return False

    class _ConnectorsLayerStyler(QgsProcessingLayerPostProcessorInterface):
        """Post-traitement de la couche connecteurs chargée : SCR 31370 forcé puis style."""

        def __init__(self):
            super().__init__()

        def postProcessLayer(self, layer, context, feedback):  # noqa: N802
            try:
                _force_target_crs(layer, feedback, layer.name(), always_log=True)
                _apply_connectors_style(layer, feedback)
                layer.triggerRepaint()
            except Exception:  # pragma: no cover - défensif (rendu non bloquant)
                pass

    class _SegmentsLayerStyler(QgsProcessingLayerPostProcessorInterface):
        """Applique le style segments (source : ``style/depth_segments.qml``).

        Pendant de :class:`_DepthLayerStyler` pour la couche
        ``public.geofiber_asbuilt_depth_segments`` : post-traitement de la couche
        ajoutée au projet en fin d'exécution (cf. _load_be_layers_in_project),
        délégué à :func:`_apply_segments_style` (même source de vérité que le
        style synchronisé en base).
        """

        def __init__(self):
            super().__init__()

        def postProcessLayer(self, layer, context, feedback):  # noqa: N802
            # SCR re-vérifié APRÈS l'ajout au projet (Processing peut réassigner
            # un SCR au chargement), puis style.
            try:
                _force_target_crs(layer, feedback, layer.name(), always_log=True)
            except Exception:  # pragma: no cover - défensif
                pass
            try:
                _apply_segments_style(layer, feedback)
                layer.triggerRepaint()
            except Exception:  # pragma: no cover - défensif (rendu non bloquant)
                pass

    class _DepthLayerStyler(QgsProcessingLayerPostProcessorInterface):
        """Applique le style profondeur (source : ``style/depth_category.qml``).

        Post-traitement de la couche ``public.geofiber_asbuilt_depth_points``
        ajoutée au projet en fin d'exécution (cf. _load_be_layers_in_project).
        Délègue à :func:`_apply_depth_style` — donc la MÊME source de vérité (le
        ``.qml``) que le style par défaut synchronisé en base, garantissant un
        rendu identique entre l'affichage immédiat et les ouvertures ultérieures.
        Ré-appliqué APRÈS l'ajout au projet par l'interface Processing, pour
        avoir le dernier mot sur tout style par défaut qu'elle appliquerait.
        """

        def __init__(self):
            super().__init__()

        def postProcessLayer(self, layer, context, feedback):  # noqa: N802
            # SCR re-vérifié APRÈS l'ajout au projet (Processing peut réassigner
            # un SCR au chargement), puis style.
            try:
                _force_target_crs(layer, feedback, layer.name(), always_log=True)
            except Exception:  # pragma: no cover - défensif
                pass
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
        PAS une exception Python catchable), observé à l'écriture
        (``openpyxl.Workbook()``) et pouvant toucher la lecture ``.xlsx`` en
        entrée (même mécanisme interne) — seul usage restant d'openpyxl ici.

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
        """Géocode un lot de rapports As-Built et pousse les points par profondeur en base 'be'.

        Aucune couche de sortie temporaire : les points (et segments d'axe de
        rue) vivent dans la base 'be', dont les deux couches sont ajoutées au
        projet en fin d'exécution si elles n'y sont pas déjà.
        """

        INPUT_FOLDER = "INPUT_FOLDER"
        CONTACT_EMAIL = "CONTACT_EMAIL"
        FULL_REBUILD = "FULL_REBUILD"
        RECOMPUTE_EXISTING = "RECOMPUTE_EXISTING"

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
                "et enregistre les points, catégorisés par profondeur de pose, "
                "dans la base 'be'. Aucun fichier ni couche temporaire n'est "
                "produit : le résultat est en base (et dans le journal).\n\n"
                "ENTRÉES — dossier balayé (non récursif) : .msg (Outlook, corps "
                "HTML ou texte, message direct ou « FW: »), .xlsx et .csv ; les "
                ".xls binaires legacy sont à ré-exporter en .xlsx ou .csv. "
                "Tableau attendu : WorkOrder, Intervention, Address, PostalCode, "
                "Place et une colonne de profondeur (intitulé contenant « depth » "
                "ou « profondeur »), repérés par intitulé, casse ignorée. Une "
                "même Intervention présente plusieurs fois (lignes ou fichiers) "
                "n'est traitée qu'UNE fois : la ligne la plus complète, à "
                "égalité la dernière (fichiers triés par nom).\n\n"
                "PROFONDEUR — valeur avec séparateur décimal = mètres (0.60 → "
                "60 cm), sinon centimètres. Catégories (seuils fixes) : vert "
                f"≥ {THRESHOLD_VERT_CM:g} cm, orange {THRESHOLD_ORANGE_CM:g}–"
                f"{THRESHOLD_VERT_CM:g} cm, rouge < {THRESHOLD_ORANGE_CM:g} cm, "
                f"manquante (absente ou < {THRESHOLD_MISSING_CM:g} cm).\n\n"
                "BASE 'be' (connexion QGIS du plugin Constructel Bridge, "
                "OBLIGATOIRE : absente ou inutilisable -> échec immédiat, avant "
                "tout géocodage). Ordre garanti : 1) chaque intervention géocodée "
                "est upsertée dans public.geofiber_asbuilt_depth_points (écrasement "
                "complet sur même intervention : un rapport rejoué avec une "
                "adresse dégradée écrase une géométrie correcte) ; les non "
                "géocodées vont dans public.geofiber_asbuilt_ungeocoded, une "
                "ligne par intervention. Règle « si géocodé, garder que "
                "géocodé » : une intervention présente dans les points n'est "
                "JAMAIS dans les non géocodées (nettoyage en début d'étape ; un "
                "échec de re-géocodage d'un point existant est ignoré, le point "
                "est conservé). Leur liste et un email prêt à envoyer sont aussi "
                "affichés dans le journal ; 2) les segments des routes "
                "impactées sont régénérés à partir des points de la table (cf. "
                "SEGMENTS) ; 3) les styles sont "
                "réécrits en base ; 4) les couches points et segments de la base "
                "sont ajoutées au projet, stylées, UNIQUEMENT si elles n'y sont "
                "pas déjà (comparaison sur la source de données, pas sur le nom : "
                "un projet qui les contient déjà n'est pas modifié). Un échec "
                "partiel en cours de route (une étape, Overpass, un style) est "
                "signalé en avertissement sans interrompre les étapes suivantes.\n\n"
                "ADRESSES DÉJÀ EN BASE — par défaut (case avancée « Recalculer » décochée), "
                "une intervention déjà présente avec un point géocodé dans "
                "public.geofiber_asbuilt_depth_points (même intervention, ou même "
                "WorkOrder avec la même adresse) n'est NI géocodée (Nominatim), NI "
                "réécrite, NI relocalisée (ref.osm_roads, Overpass) : seules les "
                "nouvelles adresses déclenchent des requêtes et des segments. "
                "Cochez la case pour tout recalculer (géocodage, routes OSM, "
                "segments) comme avant.\n\n"
                "SEGMENTS D'AXE DE RUE — recalcul INCRÉMENTAL : seules les routes "
                "impactées (points nouveaux ou modifiés par ce run, points jamais "
                "localisés, points devenus gris ou supprimés, et les autres points "
                "de ces routes) sont relocalisées et recalculées, et seuls les "
                "segments réellement différents sont réécrits ; le premier run "
                "(table vide) est complet. Case AVANCÉE « Reconstruire tous les "
                "segments » : à cocher après un changement de règle (seuils, "
                "décalages, côtés) ou de ref.osm_roads, que l'incrémental ne "
                "détecte pas. Rues RAMIFIÉES (carrefour en Y, rond-point, "
                "chaussées séparées) découpées en CHAÎNES sans fourche : un point "
                "se rattache à la chaîne qui contient la voie la plus proche (jamais "
                "à une portion lointaine de l'axe), seuls les points d'une même "
                "chaîne sont reliés ; par nom, seules les voies carrossables sont "
                "retenues (desserte / zone de rencontre à défaut, jamais un chemin "
                "agricole ou un sentier). Bouts de rue : PETIT segment de "
                f"{ROAD_END_STUB_M:g} m le long de l'axe depuis le premier / dernier "
                "point, de chaque côté d'un point isolé). Un décalage aberrant (boucle, "
                "retournement) est tracé sur l'axe non décalé. Les points gris (profondeur manquante) "
                "sont ignorés pour les segments ; chaque point de profondeur connue est projeté "
                "orthogonalement sur l'axe de sa rue (nom extrait de l'adresse) "
                "et rangé du côté gauche ou droit de la route (point sur l'axe : "
                "droite). Par rue ET par côté, les points consécutifs sont reliés "
                "par un segment coupé en deux moitiés colorées chacune selon son "
                "point, et les bouts de rue sont prolongés ; deux points de côtés "
                "opposés ne sont jamais reliés. Plusieurs interventions au MÊME "
                f"point projeté (à {COLOCATED_TOLERANCE_M:g} m, même rue et même "
                "côté — typiquement la même adresse) sont fusionnées en un seul "
                "nœud (plus petit identifiant, catégorie la PIRE du groupe : rouge "
                "> orange > vert) : pas de segment de longueur nulle ; les points "
                "restent tous en base. Chaque segment SUIT L'AXE DE RUE (sous-ligne "
                "de l'axe entre les deux points ; moitié = jusqu'au milieu "
                "mesuré le long de l'axe), en MultiLineString EPSG:31370, décalé "
                "parallèlement vers son côté selon le type de voie OSM "
                "(autoroute/voie rapide "
                f"{HIGHWAY_OFFSET_M['motorway']:g} m, primaire "
                f"{HIGHWAY_OFFSET_M['primary']:g} m, secondaire "
                f"{HIGHWAY_OFFSET_M['secondary']:g} m, tertiaire "
                f"{HIGHWAY_OFFSET_M['tertiary']:g} m, résidentielle "
                f"{HIGHWAY_OFFSET_M['residential']:g} m, desserte/chemin "
                f"{HIGHWAY_OFFSET_M['service']:g} m, autre "
                f"{DEFAULT_HIGHWAY_OFFSET_M:g} m). Segments ≥ "
                f"{LONG_SEGMENT_THRESHOLD_M:g} m (mesurés sur l'axe) en pointillé "
                "(interpolation peu fiable) ; longueur mesurée le long de l'axe. "
                "Routes de ref.osm_roads : axe ET type de voie via la fonction "
                "public.fn_asbuilt_road_geometry (migration road_geom, requêtes par "
                "lots) ; absente -> localisation de TOUTES les routes via Overpass "
                "(axe suivi) pour le run ; axe non retenu pour une route -> repli "
                "Overpass, sinon cordes droites (compteur). Colonne geom encore "
                "LineString -> première partie seulement (migration MultiLineString "
                "recommandée). Après ces migrations, cochez une fois « Reconstruire "
                "tous les segments ». Écriture dans "
                "public.geofiber_asbuilt_depth_segments : insertion / mise à jour "
                "des segments changés, purge des segments obsolètes des seules "
                "routes recalculées (suspendue si la localisation ou la lecture "
                "est incomplète).\n"
                "LOCALISATION en 3 étapes : 1) ref.osm_roads (base 'be') par nom "
                "de rue — nom de RÉFÉRENCE = nom canonique OSM renvoyé par "
                "Nominatim pour le point, puis nom lu dans l'adresse (les deux sont "
                f"essayés s'ils diffèrent), voie du même nom cherchée jusqu'à "
                f"{LOCATE_RADIUS_M:g} m (points géocodés souvent en retrait de la "
                f"rue ; au-delà de {LOW_CONFIDENCE_DISTANCE_M:g} m le rattachement est "
                "conservé mais signalé « faible confiance ») ; tronçons de même nom "
                f"raccordés à {ROAD_JOIN_TOLERANCE_M:g} m près ; deux tronçons "
                "homonymes non raccordés (rue coupée, rond-point, chaussées "
                "séparées) ne rendent le point ambigu qu'en quasi-égalité (moins "
                f"de {COMPONENT_TIE_GAP_M:g} m d'écart et rapport < "
                f"{COMPONENT_TIE_RATIO:g}) — sinon le plus proche l'emporte, en "
                f"faible confiance si la marge est < {COMPONENT_LOW_CONF_GAP_M:g} m ; "
                "NOM APPROCHANT accepté en faible confiance (« Linden-Allee » pour "
                "« Lindenallee », Str./Straße/Strasse, espaces et tirets) jusqu'à "
                f"{FUZZY_NAME_MAX_DISTANCE_M:g} m si aucune voie d'un autre nom n'est "
                "nettement plus proche ; adresses « Rue X/Rue X 12 1000 Localité » "
                "nettoyées avant recherche ; 2) API Overpass : d'abord la voie "
                "désignée par Nominatim (identifiant OSM, l'axe le plus sûr), puis "
                "par NOM (lots par rue ET localité : deux "
                "rues homonymes de villages différents ne se confondent pas ; "
                "accents, ß/ss, apostrophes et tirets tolérés) ; 3) Overpass par "
                f"COORDONNÉES : voie portant le nom de référence jusqu'à "
                f"{COORD_PREFERRED_NAME_RADIUS_M:g} m, sinon voie carrossable la plus "
                f"proche à {OSM_COORD_FALLBACK_RADIUS_M:g} m (chemins, pistes et "
                "trottoirs exclus ; omis si une voie d'un autre nom est à moins de "
                f"{OSM_COORD_AMBIGUITY_M:g} m de plus — carrefour), y compris sans nom de rue dans l'adresse ; une rue a le "
                "même identifiant quel que soit le chemin. LIMITE : un point mal "
                "géocodé par Nominatim se rattache à la mauvaise route. CONFIANCE : "
                "chaque rattachement est noté (distance à l'axe, nom de la voie "
                "comparé aux noms de référence, classe de voie plausible, précision "
                "du géocodage) grâce aux métadonnées déjà renvoyées par Nominatim "
                "(aucun appel supplémentaire) ; un rattachement à faible confiance "
                "est écarté (géocodage à la localité seulement, voie trouvée par "
                "coordonnées à plus de 30 m ou d'un autre nom alors qu'une voie du "
                "nom attendu est proche, autoroute pour une adresse) et le journal en "
                "donne le nombre et 5 exemples ; un code postal d'adresse différent "
                "de celui du point géocodé est signalé. Voies Overpass : envoyées "
                "au fil de l'eau vers ref.osm_roads (types de voie Farois, jamais "
                "d'écrasement) si la fonction public.fn_asbuilt_store_osm_ways "
                "existe — sinon simple information ; après la première "
                "alimentation, cochez « Reconstruire tous les segments ». Overpass : "
                f"accès Internet requis ; au plus {OVERPASS_MAX_NAMES_PER_QUERY} rues par "
                "requête ; serveur public instable (réponses OK / 504 / 429 au "
                "hasard) : plusieurs tentatives avec attente croissante, attente "
                "d'un slot libre, miroir de repli. Réponses en CACHE dans le "
                f"profil QGIS ({OVERPASS_CACHE_DIRNAME}, "
                f"{OVERPASS_CACHE_TTL_S // 86400} jours) : relancer le script après "
                "un échec partiel ne refait que les requêtes manquantes. Un échec "
                "de requête est ISOLÉ (les autres continuent, purge suspendue pour "
                "les seules routes concernées). Journal et progression par "
                "requête, bilan final ; si aucun point n'est localisé, un "
                "avertissement en donne la cause ; recherche des voies indexée par "
                "bbox et appels SQL par lots ; en fin d'étape, les points non "
                "localisés sont listés par cause (aucune voie à proximité, nom "
                "introuvable, voie du même nom trop loin, ambigu) avec 10 exemples.\n"
                "CONNECTEURS — pour chaque point localisé, une ligne fine en "
                "pointillé relie le point géocodé à l'extrémité de son segment "
                "(point projeté sur l'axe décalé) ; table "
                "public.geofiber_asbuilt_depth_connectors (migration_connectors : "
                "absente -> simple information), même logique incrémentale que les "
                "segments, couche « Profondeur As-Built — connecteurs » ajoutée au "
                "projet si absente (sous les segments et les points).\n"
                "PRÉREQUIS : colonne « side » sur "
                "public.geofiber_asbuilt_depth_segments (clé primaire point_a, "
                "point_b, half, side). Absente -> avertissement « migration "
                "requise », segments ni recalculés ni modifiés.\n\n"
                "SCR — toutes les coordonnées sont reprojetées en Lambert belge 72 "
                "(EPSG:31370 ; pas Lambert 2008) : les couches de "
                "la base reçoivent explicitement ce SCR (URI srid=31370 ET SCR de "
                "couche forcé, re-vérifié après chargement ; un autre SCR constaté "
                "est corrigé et signalé), les points Nominatim et les voies "
                "Overpass (WGS84, x = longitude, y = latitude) sont reprojetés "
                "vers 31370 (contrôle croisé avec une formule de référence), et "
                "toute coordonnée hors de la plage belge est signalée. Le SCR du projet "
                "n'est jamais modifié.\n\n"
                "STYLES — source de vérité : les .qml livrés "
                "(style/depth_category.qml, style/depth_segments.qml). Ils sont "
                "réécrits à chaque run comme style par défaut des deux tables (layer_styles de la base 'be') : une "
                "retouche enregistrée comme style par défaut dans QGIS sera "
                "perdue — modifiez plutôt les .qml.\n\n"
                "NOMINATIM — requête STRUCTURÉE (rue, code postal, localité, "
                "Belgique) puis texte libre ; résultat hors Belgique = échec. "
                "1 requête/s ; renseignez CONTACT_EMAIL. Chaque run "
                "géocode TOUTES les interventions du dossier : ne laissez dans le dossier que "
                "les rapports à traiter. Adresse à "
                "segments « / » répétés (bug d'export, ex. « Malmedyer "
                "Straße/Malmedyer Straße 203 ») : second essai avec le dernier "
                "segment seul ; la notation numéro/boîte (« Rue de la Gare "
                "12/3 ») n'est pas concernée.\n\n"
                "DÉPENDANCES — 'extract-msg' (.msg) et 'openpyxl' (lecture des "
                ".xlsx), installés via pip au besoin, seulement si le dossier "
                "contient ces formats."
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
                QgsProcessingParameterString(
                    self.CONTACT_EMAIL,
                    self.tr("Email de contact (User-Agent Nominatim, recommandé)"),
                    defaultValue="sig@constructel.fr",
                    optional=True,
                )
            )
            # Parametre AVANCE. Par defaut (decoche) : une adresse deja geocodee en base 'be' n'est
            # NI re-geocodee, NI re-localisee (ref.osm_roads / Overpass), NI
            # reecrite. Coche : tout est recalcule comme avant.
            recompute = QgsProcessingParameterBoolean(
                self.RECOMPUTE_EXISTING,
                self.tr(
                    "Recalculer aussi les adresses déjà géocodées en base "
                    "(géocodage, routes OSM/Overpass, segments)"
                ),
                defaultValue=False,
            )
            recompute.setFlags(recompute.flags() | _ADVANCED_PARAMETER_FLAG)
            self.addParameter(recompute)
            # Parametre AVANCE : force la reconstruction de TOUS les segments
            # (ancien comportement) — a cocher apres un changement de regle
            # (seuils, decalages, cotes, ref.osm_roads) que le mode incremental,
            # qui ne recalcule que les routes des points modifies, ne detecte pas.
            full_rebuild = QgsProcessingParameterBoolean(
                self.FULL_REBUILD,
                self.tr("Reconstruire tous les segments (après un changement de règle)"),
                defaultValue=False,
            )
            full_rebuild.setFlags(full_rebuild.flags() | _ADVANCED_PARAMETER_FLAG)
            self.addParameter(full_rebuild)

        # -- traitement ---------------------------------------------------
        def processAlgorithm(self, parameters, context, feedback):
            folder = self.parameterAsFile(parameters, self.INPUT_FOLDER, context)
            contact_email = self.parameterAsString(parameters, self.CONTACT_EMAIL, context)
            user_agent = build_user_agent(contact_email)
            full_rebuild = self.parameterAsBoolean(parameters, self.FULL_REBUILD, context)
            recompute_existing = self.parameterAsBoolean(
                parameters, self.RECOMPUTE_EXISTING, context
            )
            self._segments_multi = None  # sonde du type de colonne, une fois par run
            self._connectors_available = None  # sonde de la table connecteurs
            # Metadonnees Nominatim/OSM des points geocodes A CE RUN (en memoire
            # seulement) : nom de rue canonique, objet OSM, precision.
            self._nominatim_hits = {}
            postal_mismatches: list = []
            # La base 'be' est l'UNIQUE destination : sans elle, rien a faire.
            # Verifiee AVANT la lecture et le geocodage (couteux, 1 req/s).
            self._require_be(feedback)

            # Interventions geocodees avec succes par ce run, pour l'upsert vers
            # la connexion 'be' (cf. self._upsert_geocoded_records) : (dict de
            # valeurs d'attributs, QgsPointXY reprojete en BELGIAN_LAMBERT_AUTHID). Seule
            # trace EN MEMOIRE des points de ce run : aucune couche de sortie
            # temporaire n'est produite, la base 'be' est l'unique destination.
            geocoded_for_db: list[tuple[dict, "QgsPointXY"]] = []

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
            # WGS84 (Nominatim) -> Lambert belge 72, contexte de transformation
            # du projet (datums), quel que soit le SCR du projet.
            to_lambert, _ = lambert_transforms(context.transformContext())
            n_ok = n_nf = n_skip_be = 0
            # Points déjà en base 'be' (même intervention, ou même work order +
            # même adresse) : ni géocodage Nominatim, ni upsert, donc aucun
            # point « modifié » et aucun segment recalculé pour eux.
            if deduped and not recompute_existing:
                be_known_ids, be_known_wo_addr = self._load_known_from_be(feedback)
                feedback.pushInfo(
                    f"{len(be_known_ids)} interventions déjà géocodées en base 'be' "
                    "(ignorées : option « Recalculer » décochée)."
                )
            else:
                be_known_ids, be_known_wo_addr = set(), set()
                if recompute_existing:
                    feedback.pushInfo(
                        "Option « Recalculer » cochée : tout est géocodé et recalculé."
                    )
            out_of_range: list[str] = []  # contrôle de vraisemblance Lambert 72
            divergent: list[str] = []     # contrôle croisé QGIS / Python pur
            total = max(len(deduped), 1)
            # Adresses non géocodées de ce run : (InterventionRecord, requête en
            # échec) — message/email copiables du journal et upsert dans
            # public.geofiber_asbuilt_ungeocoded.
            ungeocoded: list[tuple[InterventionRecord, str]] = []

            # Cadence Nominatim (1 req/s) en respectant l'annulation utilisateur.
            # Injecté dans le repli pour espacer ses deux appels, et réutilisé en
            # fin de boucle pour espacer les interventions successives.
            def _rate_limit_pause():
                _sleep_with_cancel(feedback, 1.0)

            for i, rec in enumerate(deduped):
                if feedback.isCanceled():
                    break
                if is_already_present(rec, be_known_ids, be_known_wo_addr):
                    n_skip_be += 1
                    feedback.pushInfo(
                        f"Déjà en base 'be' (work order {rec.work_order}, "
                        f"intervention {rec.intervention}) : ni géocodage ni segment."
                    )
                    feedback.setProgress(int(100 * (i + 1) / total))
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
                reject = None
                if hit is not None:
                    # Résultat HORS BELGIQUE (Nominatim a pu trouver une rue
                    # homonyme ailleurs) = échec, pas un point poussé.
                    if not in_belgium_wgs84(hit.lat, hit.lon):
                        reject = f"résultat hors Belgique (lat {hit.lat:.5f}, lon {hit.lon:.5f})"
                    else:
                        # UNIQUE reprojection WGS84 (x = lon, y = lat) -> Lambert 72.
                        x, y = wgs84_to_lambert(hit.lon, hit.lat, to_lambert)
                        if not lambert72_plausible(x, y):
                            out_of_range.append(rec.intervention)
                            reject = (
                                f"coordonnées Lambert 72 hors plage ({x:.0f}, {y:.0f})"
                                " — SCR suspect"
                            )
                if hit is None or reject:
                    n_nf += 1
                    ungeocoded.append((rec, query))
                    feedback.pushWarning(
                        f"Non géocodé (intervention {rec.intervention}) : {query}"
                        + (f" — {reject}" if reject else "")
                    )
                else:
                    point = QgsPointXY(x, y)
                    self._nominatim_hits[rec.intervention] = hit
                    if postal_mismatch(rec.postal_code, hit):
                        postal_mismatches.append(
                            f"{rec.intervention} ({rec.postal_code} ≠ {hit.postcode})"
                        )
                    # Contrôle croisé avec la projection Python pure (même
                    # chaîne BD72/Lambert 72 que PROJ) : un écart trahit une
                    # reprojection mal configurée.
                    px, py = wgs84_to_lambert72_pure(hit.lon, hit.lat)
                    if math.hypot(px - x, py - y) > LAMBERT_CROSSCHECK_TOLERANCE_M:
                        divergent.append(rec.intervention)
                    values = _build_attribute_values(rec, query, "ok", hit)
                    geocoded_for_db.append((values, point))
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
                f"{n_skip_be} déjà en base 'be' ignorées."
            )
            if postal_mismatches:
                feedback.pushWarning(
                    f"{len(postal_mismatches)} point(s) dont le code postal de l'adresse "
                    "diffère de celui renvoyé par Nominatim au point (géocodage "
                    f"possiblement dans une autre commune) : {', '.join(postal_mismatches[:5])}"
                )
            if divergent:
                feedback.pushWarning(
                    f"{len(divergent)} point(s) dont la reprojection QGIS vers "
                    f"{BELGIAN_LAMBERT_AUTHID} s'écarte de plus de "
                    f"{LAMBERT_CROSSCHECK_TOLERANCE_M:g} m de la formule de référence "
                    f"(transformation de datum inattendue ?) : {', '.join(divergent[:10])}"
                )
            if out_of_range:
                feedback.pushWarning(
                    f"{len(out_of_range)} point(s) rejeté(s) : hors de la plage Lambert 72 "
                    f"après reprojection vers {BELGIAN_LAMBERT_AUTHID} (SCR suspect) : "
                    f"{', '.join(out_of_range[:10])}"
                    + ("…" if len(out_of_range) > 10 else "")
                )
            feedback.pushInfo(build_ungeocoded_message(ungeocoded))

            # --- base 'be' : ORDRE GARANTI --------------------------------
            # 1) points (+ non geocodees), 2) PUIS regeneration COMPLETE des
            # segments depuis TOUS les points de la table (pas seulement ce
            # run : les points de CE run n'y sont qu'apres l'etape 1), 3) styles
            # en base, 4) couches du projet. Chaque etape a son propre garde :
            # un echec (avertissement) n'empeche pas les suivantes -- en
            # particulier, un upsert en echec n'empeche pas de regenerer les
            # segments a partir des points deja en base. Annulation : rien
            # n'est ecrit.
            if not feedback.isCanceled():
                feedback.pushInfo(
                    f"Étape 1/4 — points : upsert de {len(geocoded_for_db)} "
                    f"intervention(s) géocodée(s) dans {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} "
                    f"et de {len(ungeocoded)} non géocodée(s) dans "
                    f"{UNGEOCODED_TABLE_SCHEMA}.{UNGEOCODED_TABLE_NAME}."
                )
                # Regle « si geocode, garder que geocode » : aucune intervention
                # presente dans les points ne reste dans les non geocodees
                # (nettoie aussi l'historique, sans script separe).
                self._purge_ungeocoded_already_geocoded(feedback)
                written_ids: set = set()
                # None = points modifies INCONNUS (upsert interrompu) : les
                # segments sont alors entierement reconstruits par prudence.
                changed_ids = None
                try:
                    written_ids, changed_ids = self._upsert_geocoded_records(
                        geocoded_for_db, feedback
                    )
                except Exception as exc:
                    feedback.pushWarning(
                        f"Points : erreur inattendue lors de l'upsert ({exc}) — "
                        "segments reconstruits entièrement par prudence."
                    )
                try:
                    self._remove_resolved_ungeocoded(written_ids, feedback)
                except Exception as exc:
                    feedback.pushWarning(
                        f"Non géocodées : erreur inattendue lors du retrait des "
                        f"interventions désormais géocodées ({exc})."
                    )
                # Echec de geocodage alors qu'un point geocode existe deja pour
                # cette intervention : point conserve, PAS de ligne en non geocodees.
                existing_ids = self._existing_point_ids(
                    [rec.intervention for rec, _query in ungeocoded], feedback
                )
                if existing_ids is not None:
                    ungeocoded, kept = split_ungeocoded(ungeocoded, existing_ids)
                    for rec, _query in kept:
                        feedback.pushInfo(
                            f"Intervention {rec.intervention} : point géocodé existant "
                            "conservé, échec de re-géocodage ignoré."
                        )
                try:
                    self._upsert_ungeocoded_records(ungeocoded, feedback)
                except Exception as exc:
                    feedback.pushWarning(
                        f"Non géocodées : erreur inattendue lors de l'upsert ({exc})."
                    )
                if existing_ids is None:
                    # Verification impossible avant ecriture : on retablit la
                    # regle apres coup.
                    self._purge_ungeocoded_already_geocoded(feedback)

                feedback.pushInfo(
                    f"Étape 2/4 — segments : régénération de "
                    f"{SEGMENTS_TABLE_SCHEMA}.{SEGMENTS_TABLE_NAME} ("
                    + ("reconstruction complète demandée" if full_rebuild
                       else "incrémentale : routes impactées seulement")
                    + ")."
                )
                try:
                    self._sync_segments(
                        feedback, user_agent, changed_ids, full_rebuild,
                        recompute_existing,
                    )
                    self._log_locate_extras(feedback)
                except Exception as exc:
                    feedback.pushWarning(
                        f"Segments : erreur inattendue lors de la régénération ({exc})."
                    )

                feedback.pushInfo("Étape 3/4 — styles par défaut en base (layer_styles).")
                try:
                    self._sync_styles_to_db(feedback)
                except Exception as exc:
                    feedback.pushWarning(
                        f"Styles : erreur inattendue lors de la synchronisation ({exc})."
                    )

                feedback.pushInfo("Étape 4/4 — couches de la base dans le projet.")
                try:
                    self._load_be_layers_in_project(context, feedback)
                except Exception as exc:
                    feedback.pushWarning(
                        "Couches de la base 'be' non ajoutées au projet (erreur "
                        f"inattendue : {exc})."
                    )

            # --- message copiable des adresses non géocodées ------------
            feedback.pushInfo(build_ungeocoded_message(ungeocoded))
            if ungeocoded:
                feedback.pushInfo(
                    build_ungeocoded_email(ungeocoded, contact_email, n_ok)
                )
            # Aucune sortie déclarée : tout est écrit en base 'be' (et les deux
            # couches de la base ajoutées au projet si absentes).
            return {}

        # -- helpers d'instance ------------------------------------------
        def _require_be(self, feedback):
            """Verifie au DEMARRAGE que la base 'be' est utilisable, sinon echec net.

            La base 'be' est l'unique destination de l'algorithme (aucune autre
            sortie) : connexion QGIS 'be' introuvable, ou table
            public.geofiber_asbuilt_depth_points non ouvrable (invalide, non
            spatiale, sans cle primaire) -> QgsProcessingException, AVANT toute
            lecture de fichier ou requete Nominatim. Les echecs partiels
            ulterieurs (segments, Overpass, styles) restent des avertissements.
            """
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            if md is None or md.findConnection(BE_CONNECTION_NAME) is None:
                raise QgsProcessingException(
                    "Connexion QGIS 'be' introuvable — installez/activez le plugin "
                    "Constructel Bridge (connexion PostgreSQL « be »). La base "
                    "'be' est l'unique destination de cet algorithme : arrêt."
                )
            layer = self._open_be_points_layer(feedback)
            if layer is None or not layer.primaryKeyAttributes():
                raise QgsProcessingException(
                    f"Table {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} inutilisable via la "
                    "connexion 'be' (injoignable, invalide, non spatiale ou sans clé "
                    "primaire — cf. journal). Rien n'a été géocodé ni écrit : arrêt."
                )

        def _sync_styles_to_db(self, feedback):
            """Reecrit les styles par defaut des tables points et segments (etape 3).

            Source : les .qml livres (_apply_depth_style / _apply_segments_style),
            enregistres dans layer_styles (useAsDefault=True) via
            _sync_style_to_db. Best-effort : table non ouvrable -> avertissement
            deja emis par _open_be_layer, style suivant tente quand meme.
            """
            points_layer = self._open_be_points_layer(feedback)
            if points_layer is not None:
                _apply_depth_style(points_layer, feedback)
                _sync_style_to_db(
                    points_layer, "depth_category",
                    "Style profondeur As-Built (points) — géré par geocode_asbuilt_depth, ne pas éditer manuellement.",
                    feedback,
                )
            segments_layer = self._open_be_layer(
                SEGMENTS_TABLE_SCHEMA, SEGMENTS_TABLE_NAME,
                BE_GEOM_COLUMN,
                QgsWkbTypes.MultiLineString if self._segments_is_multi(feedback)
                else QgsWkbTypes.LineString,
                feedback,
            )
            if segments_layer is not None:
                _apply_segments_style(segments_layer, feedback)
                _sync_style_to_db(
                    segments_layer, "depth_segments",
                    "Style segments d'axe de rue As-Built — géré par geocode_asbuilt_depth, ne pas éditer manuellement.",
                    feedback,
                )
            connectors = self._read_connectors(feedback)
            if connectors is not None:
                _apply_connectors_style(connectors[0], feedback)
                _sync_style_to_db(
                    connectors[0], "depth_connectors",
                    "Style connecteurs As-Built — géré par geocode_asbuilt_depth, ne pas éditer manuellement.",
                    feedback,
                )

        def _open_be_layer(self, schema: str, table: str, geom_column: str, wkb_type, feedback):
            """Ouvre schema.table via la connexion 'be', geometrie forcee.

            Ne fait PAS confiance a l'auto-detection de tableUri() sur cette
            connexion : cf. le commentaire ci-dessous sur l'incident constate
            en prod le 03/08 (geometrie silencieusement omise). Factorise
            depuis _upsert_geocoded_records ; reutilise par _sync_segments et
            _load_be_layers_in_project.
            """
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            be_connection = md.findConnection(BE_CONNECTION_NAME) if md else None
            if be_connection is None:
                feedback.pushWarning(
                    "Connexion QGIS 'be' introuvable — installez/activez "
                    "Constructel Bridge pour pousser les interventions en base. "
                    f"Rien n'a ete ecrit dans {schema}.{table}."
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
                ds_uri.setSrid(BELGIAN_LAMBERT_AUTHID.split(":")[-1])
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
            _force_target_crs(layer, feedback, f"{schema}.{table}")
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
            echouer le run — le reste du traitement (geocodage couteux, autres
            tables) ne doit pas etre perdu pour un probleme d'ecriture d'une
            ligne. Cf. spec
            docs/superpowers/specs/2026-08-03-geofiber-depth-upsert-design.md.

            Pas de doublon : chaque ligne est cherchee par intervention_id AVANT
            ecriture (mise a jour si presente, insertion sinon) et committee
            aussitot — un meme intervention_id present deux fois dans le lot
            (impossible apres dedupe_records, mais sans consequence) serait donc
            mis a jour, jamais insere deux fois.

            Retourne ``(written_ids, changed_ids)`` : intervention_id ecrits avec
            succes (cf. _remove_resolved_ungeocoded), et parmi eux ceux qui sont
            nouveaux ou dont la categorie, l'adresse ou la position ont change
            par rapport a l'etat lu AVANT l'ecriture (cf. point_changed) — les
            points « sales » du recalcul incremental des segments.
            """
            written_ids: set = set()
            changed_ids: set = set()
            if not records:
                feedback.pushInfo("Points : aucune intervention geocodee a pousser.")
                return written_ids, changed_ids
            layer = self._open_be_layer(
                BE_TABLE_SCHEMA, BE_TABLE_NAME, BE_GEOM_COLUMN, QgsWkbTypes.Point, feedback
            )
            if layer is None:
                return written_ids, changed_ids
            if not layer.primaryKeyAttributes():
                feedback.pushWarning(
                    f"Couche {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} sans cle primaire "
                    "exploitable — ecriture impossible, rien n'a ete ecrit en base."
                )
                return written_ids, changed_ids

            fields = layer.fields()
            id_field = QgsExpression.quotedColumnRef("intervention_id")
            inserted = updated = failed = 0
            for values, point in records:
                intervention_id = values["intervention_id"]
                id_value = QgsExpression.quotedValue(intervention_id)
                request = QgsFeatureRequest()
                request.setFilterExpression(f"{id_field} = {id_value}")
                existing = list(layer.getFeatures(request))
                old_state = _point_state(existing[0]) if existing else None

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
                    written_ids.add(intervention_id)
                    new_state = {
                        "depth_category": values.get("depth_category"),
                        "address_raw": values.get("address_raw"),
                        "x": point.x(), "y": point.y(),
                    }
                    if point_changed(old_state, new_state):
                        changed_ids.add(intervention_id)
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
                f"Points : {inserted + updated} upsertee(s) ({inserted} creee(s), "
                f"{updated} mise(s) a jour), {failed} echec(s) sur {len(records)} "
                "intervention(s) geocodee(s)."
            )
            return written_ids, changed_ids

        def _be_connection(self):
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            return md.findConnection(BE_CONNECTION_NAME) if md else None

        def _purge_ungeocoded_already_geocoded(self, feedback):
            """Supprime des non geocodees toute intervention presente dans les points.

            Une seule requete ``DELETE … USING … RETURNING`` (atomique : une
            transaction) ciblee sur les intervention_id communs aux deux tables —
            jamais une purge de masse. Compteur au journal ; echec ->
            avertissement, jamais d'exception.
            """
            be_connection = self._be_connection()
            if be_connection is None:
                return
            sql = (
                f"DELETE FROM {UNGEOCODED_TABLE_SCHEMA}.{UNGEOCODED_TABLE_NAME} u "
                f"USING {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} p "
                "WHERE u.intervention_id = p.intervention_id "
                "RETURNING u.intervention_id"
            )
            try:
                deleted = be_connection.executeSql(sql) or []
            except Exception as exc:
                feedback.pushWarning(
                    f"Non géocodées : nettoyage des interventions déjà géocodées "
                    f"impossible ({exc})."
                )
                return
            if deleted:
                feedback.pushInfo(
                    f"Non géocodées : {len(deleted)} intervention(s) déjà présente(s) "
                    f"dans {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} retirée(s) de "
                    f"{UNGEOCODED_TABLE_SCHEMA}.{UNGEOCODED_TABLE_NAME}."
                )

        def _load_known_from_be(self, feedback):
            """Lit en base 'be' les points déjà géocodés (intervention + work order/adresse).

            Retourne ``(interventions, work_order_addresses)`` (cf.
            build_known_keys). Best-effort : lecture impossible -> ensembles
            vides (avertissement), tout est alors géocodé comme avant.
            """
            be_connection = self._be_connection()
            if be_connection is None:
                return set(), set()
            try:
                rows = be_connection.executeSql(
                    "SELECT intervention_id, work_order, address_raw, postal_code "
                    f"FROM {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} WHERE geom IS NOT NULL"
                ) or []
            except Exception as exc:
                feedback.pushWarning(
                    f"Lecture des points déjà présents en base 'be' impossible "
                    f"({exc}) — tout sera géocodé."
                )
                return set(), set()
            return build_known_keys(rows)

        def _existing_point_ids(self, intervention_ids, feedback):
            """intervention_id parmi ``intervention_ids`` ayant deja un point en base.

            Retourne un ``set`` de chaines, ou ``None`` si la verification est
            impossible (l'appelant retablit alors la regle apres ecriture).
            """
            ids = sorted({str(i) for i in intervention_ids if i})
            if not ids:
                return set()
            be_connection = self._be_connection()
            if be_connection is None:
                return None
            found = set()
            try:
                for start in range(0, len(ids), 500):
                    chunk = ", ".join(
                        QgsExpression.quotedValue(v) for v in ids[start:start + 500]
                    )
                    rows = be_connection.executeSql(
                        f"SELECT intervention_id FROM {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} "
                        f"WHERE intervention_id IN ({chunk})"
                    ) or []
                    found.update(str(row[0]) for row in rows)
            except Exception as exc:
                feedback.pushWarning(
                    f"Non géocodées : vérification des points existants impossible ({exc})."
                )
                return None
            return found

        def _remove_resolved_ungeocoded(self, intervention_ids, feedback):
            """Retire de public.geofiber_asbuilt_ungeocoded les interventions desormais geocodees.

            CIBLE : uniquement les ``intervention_ids`` ecrits AVEC SUCCES dans
            les points par CE run (retour de _upsert_geocoded_records) — jamais
            de purge de masse. Evite qu'une intervention figure a la fois dans
            les points et dans les non geocodees. Une transaction unique ;
            best-effort (avertissement, jamais d'exception).
            """
            if not intervention_ids:
                return
            layer = self._open_be_nonspatial_layer(
                UNGEOCODED_TABLE_SCHEMA, UNGEOCODED_TABLE_NAME, feedback
            )
            if layer is None or not layer.primaryKeyAttributes():
                return
            id_field = QgsExpression.quotedColumnRef("intervention_id")
            ids = sorted(intervention_ids)
            fids = []
            for start in range(0, len(ids), 500):  # expressions IN bornees
                chunk = ", ".join(QgsExpression.quotedValue(v) for v in ids[start:start + 500])
                request = QgsFeatureRequest()
                request.setFilterExpression(f"{id_field} IN ({chunk})")
                request.setNoAttributes()
                request.setFlags(QgsFeatureRequest.NoGeometry)
                fids.extend(feat.id() for feat in layer.getFeatures(request))
            if not fids:
                return
            layer.startEditing()
            if layer.deleteFeatures(fids) and layer.commitChanges():
                feedback.pushInfo(
                    f"Non geocodees : {len(fids)} intervention(s) desormais geocodee(s) "
                    f"retiree(s) de {UNGEOCODED_TABLE_SCHEMA}.{UNGEOCODED_TABLE_NAME}."
                )
            else:
                for err in layer.commitErrors():
                    feedback.reportError(f"Non geocodees : {err}", fatalError=False)
                layer.rollBack()
                feedback.pushWarning(
                    "Non geocodees : retrait des interventions desormais geocodees "
                    "en echec (lignes laissees en place)."
                )

        def _upsert_ungeocoded_records(self, entries, feedback):
            """Upsert les adresses non geocodees dans public.geofiber_asbuilt_ungeocoded.

            ``entries`` : (InterventionRecord, query) — meme forme que
            build_ungeocoded_message. Best-effort, meme politique que
            _upsert_geocoded_records : ne fait jamais echouer le run.
            """
            if not entries:
                feedback.pushInfo("Non geocodees : aucune adresse a pousser.")
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
                f"Non geocodees : {inserted} creee(s), {updated} mise(s) a jour, "
                f"{failed} echec(s) sur {len(entries)}."
            )

        @staticmethod
        def _locate_sql(x, y, street_literal):
            """Appel SQL de public.fn_asbuilt_locate_on_road pour un point EPSG:31370."""
            return (
                "SELECT road_key, position_m, "
                "ST_X(projected_point), ST_Y(projected_point), "
                "road_length_m, ST_X(road_start), ST_Y(road_start), "
                "ST_X(road_end), ST_Y(road_end) "
                "FROM public.fn_asbuilt_locate_on_road("
                f"ST_SetSRID(ST_MakePoint({x!r}, {y!r}), 31370), "
                f"{street_literal}, {LOCATE_RADIUS_M!r})"
            )

        def _probe_side_in_db(self, be_connection, row, px, py, road_key, street_literal):
            """Côté de la route d'un point localisé EN BASE ('L'/'R', ou None si indécidable).

            fn_asbuilt_locate_on_road ne renvoie pas la direction de l'axe : on la
            sonde avec deux appels supplémentaires, de part et d'autre du point
            projeté le long de l'axe (cf. :func:`side_probe_points` /
            :func:`side_from_probe_positions`), ce qui donne un côté relatif au
            MÊME sens que position_m. Point sur l'axe -> 'R' (convention). Une
            sonde qui retombe sur un autre road_key (ou sur rien) rend le côté
            indécidable (None). Les exceptions SQL remontent à l'appelant.
            """
            probes = side_probe_points(row["x"], row["y"], px, py)
            if probes is None:
                return SIDE_RIGHT
            positions = []
            for qx, qy in probes:
                result = be_connection.executeSql(
                    self._locate_sql(qx, qy, street_literal)
                )
                if not result or result[0][0] != road_key:
                    return None
                positions.append(float(result[0][1]))
            return side_from_probe_positions(positions[0], positions[1])

        def _locate_via_overpass(self, unmatched, no_street_rows, feedback, user_agent):
            """Repli Overpass : par NOMS de rue, puis par COORDONNÉES (étapes 2 et 3).

            ``unmatched`` : ``(row, street_name)`` sans tronçon nommé dans
            ref.osm_roads ; ``no_street_rows`` : points sans nom de rue
            extractible de l'adresse (coordonnées seulement).

            1. Requêtes par NOMS (:func:`plan_overpass_requests` : tuiles de 2 km,
               ≤ 30 rues, emprise serrée) ;
            2. pour les points encore non localisés par nom (et ceux sans nom),
               requêtes par COORDONNÉES (:func:`plan_coord_requests` : voies
               carrossables des emprises, rayon appliqué en Python) ;
            3. localisation FINALE de tous les points sur l'ensemble des voies
               extraites pendant le run (:func:`locate_rows_on_osm`) — un seul
               index : une rue a le même road_key quel que soit le chemin.

            Mêmes garde-fous pour toutes les requêtes : cache disque du profil
            QGIS (:func:`fetch_overpass_cached`, TTL 30 jours), miroirs et
            backoff (:func:`overpass_fetch`), échecs ISOLÉS et coupe-circuit
            (:func:`run_overpass_requests`), journal et progression par requête,
            annulation. Géométries reprojetées WGS84 -> Lambert 72
            (:func:`wgs84_to_lambert`). Les voies nouvelles du run sont envoyées
            à ref.osm_roads via fn_asbuilt_store_osm_ways si elle existe
            (:meth:`_store_osm_ways`, best-effort, jamais d'écrasement). Voie
            désignée par Nominatim (``osm_type`` way + ``class`` highway) :
            interrogée d'abord par identifiant, prioritaire à la localisation.
            Chaque rattachement passe par :func:`assess_attachment` (écarté si
            faible confiance).

            Les voies extraites et les entrées de chaque point sont CUMULÉES sur
            le run (``self._osm_ways`` / ``self._osm_inputs``) : les lots
            successifs du mode incrémental localisent sur un ensemble croissant,
            et :meth:`_sync_segments` refait une passe finale commune.

            Retourne ``(locations, road_extents, stats, unavailable_ids,
            road_lines)`` (``road_lines`` : axes fusionnés par road_key) :
            ``stats`` = dict ``name``/``coords``/``ambiguous`` ;
            ``unavailable_ids`` = points non localisés dont une requête a échoué.
            Jamais d'exception.
            """
            stats = {"name": 0, "fuzzy": 0, "coords": 0, "ambiguous": 0}
            name_items = [
                (row["intervention_id"], street, row["x"], row["y"])
                for row, street in unmatched
            ]
            coord_only = [
                (row["intervention_id"], row["x"], row["y"]) for row in no_street_rows
            ]
            rows_by_id = {row["intervention_id"]: row for row, _street in unmatched}
            rows_by_id.update({row["intervention_id"]: row for row in no_street_rows})
            all_ids = set(rows_by_id)
            feedback.pushInfo(
                f"Segments : {len(name_items)} point(s) sans tronçon nommé dans "
                f"ref.osm_roads et {len(coord_only)} sans nom de rue — repli via "
                "l'API Overpass : voie désignée par Nominatim, puis par nom, puis par "
                "coordonnées."
            )
            try:
                from_wgs, to_wgs = lambert_transforms()
            except Exception as exc:  # pragma: no cover - défensif
                feedback.pushWarning(f"Overpass : reprojection impossible ({exc}).")
                return [], {}, stats, all_ids, {}
            try:
                cache_dir = os.path.join(
                    QgsApplication.qgisSettingsDirPath(), OVERPASS_CACHE_DIRNAME
                )
            except Exception:  # pragma: no cover - défensif
                cache_dir = None
            if not hasattr(self, "_osm_ways"):
                self._osm_ways, self._osm_inputs = {}, {}

            def wgs_bbox(request):
                try:
                    return lambert_bbox_to_wgs84(
                        request.bbox, lambda x, y: lambert_to_wgs84(x, y, to_wgs)
                    )
                except Exception as exc:  # QgsCsException
                    raise OverpassError(f"reprojection de l'emprise impossible ({exc})")

            def fetch_by_name(request):
                south, west, north, east = wgs_bbox(request)
                query = build_overpass_query(request.names, south, west, north, east)
                return fetch_overpass_cached(query, user_agent, cache_dir)

            def fetch_by_coords(request):
                query = build_overpass_coord_query(*wgs_bbox(request))
                return fetch_overpass_cached(query, user_agent, cache_dir)

            def reporter(label):
                def report(index, total, outcome):
                    feedback.setProgress(int(100 * index / max(total, 1)))
                    what = (
                        f"{len(outcome.request.names)} rue(s)" if outcome.request.names
                        else f"{len(outcome.request.ids)} point(s)"
                    )
                    if outcome.data is not None:
                        n_ways = sum(
                            1 for el in outcome.data.get("elements", ())
                            if isinstance(el, dict) and el.get("type") == "way"
                        )
                        source = " (cache)" if outcome.from_cache else ""
                        feedback.pushInfo(
                            f"Overpass {label} {index}/{total} : {what}, {n_ways} "
                            f"voie(s), {outcome.elapsed_s:.1f} s{source}."
                        )
                    else:
                        feedback.pushWarning(
                            f"Overpass {label} {index}/{total} : {what}, "
                            f"{len(outcome.request.ids)} point(s) — échec : {outcome.error}"
                        )
                return report

            n_out_of_range = [0]

            def absorb(outcomes, keep_unnamed):
                failed = set()
                for outcome in outcomes:
                    if outcome.data is None:
                        failed.update(outcome.request.ids)
                        continue
                    for way in parse_overpass_ways(outcome.data, keep_unnamed=keep_unnamed):
                        if way.way_id in self._osm_ways:
                            continue  # voie déjà extraite (autre requête / lot)
                        try:
                            way.coords = [
                                wgs84_to_lambert(lon, lat, from_wgs)
                                for lon, lat in way.coords
                            ]
                        except Exception:  # QgsCsException : voie ignorée
                            continue
                        n_out_of_range[0] += sum(
                            1 for x, y in way.coords if not lambert72_plausible(x, y)
                        )
                        self._osm_ways[way.way_id] = way
                        fresh_ways.append(way)
                    # Alimentation de ref.osm_roads au fil de l'eau (best-effort).
                    self._store_osm_ways(fresh_ways, feedback)
                    fresh_ways.clear()
                return failed

            fresh_ways: list = []

            pause = lambda: _sleep_with_cancel(feedback, OVERPASS_PAUSE_S)  # noqa: E731

            def give_up_pause():
                feedback.pushWarning(
                    f"Overpass : aucune réponse depuis {OVERPASS_MAX_CONSECUTIVE_FAILURES} "
                    f"requêtes — dernière pause de {OVERPASS_GIVE_UP_PAUSE_S:g} s avant "
                    "de renoncer pour ce run."
                )
                _sleep_with_cancel(feedback, OVERPASS_GIVE_UP_PAUSE_S)

            # Etat du coupe-circuit PARTAGE par les vagues de requetes.
            circuit = {}
            all_outcomes = []
            # 0) voies DESIGNEES par Nominatim (objet highway du resultat) :
            #    l'axe le plus sur, interroge directement par identifiant.
            preferred = {}
            for intervention_id in rows_by_id:
                hit = getattr(self, "_nominatim_hits", {}).get(intervention_id)
                if hit is not None and hit.osm_type == "way" and hit.osm_class == "highway" \
                        and hit.osm_id > 0:
                    preferred[intervention_id] = hit.osm_id
            wanted_ids = sorted({w for w in preferred.values() if w not in self._osm_ways})
            id_requests = [
                OverpassRequest(
                    bbox=(0.0, 0.0, 0.0, 0.0), names=(),
                    ids=tuple(sorted(i for i, w in preferred.items() if w in chunk)),
                )
                for chunk in (
                    set(wanted_ids[k:k + 200]) for k in range(0, len(wanted_ids), 200)
                )
            ]
            id_chunks = {
                req.ids: sorted({preferred[i] for i in req.ids}) for req in id_requests
            }
            if id_requests and not feedback.isCanceled():
                outcomes = run_overpass_requests(
                    id_requests,
                    lambda req: fetch_overpass_cached(
                        build_overpass_ids_query(id_chunks[req.ids]), user_agent, cache_dir
                    ),
                    is_canceled=feedback.isCanceled, pause=pause,
                    report=reporter("osm_id"), give_up_pause=give_up_pause, state=circuit,
                )
                all_outcomes.extend(outcomes)
                absorb(outcomes, keep_unnamed=True)
            # 1) par noms (noms de reference : canonique Nominatim + adresse),
            #    lots par (rue, localite)
            name_requests = plan_overpass_requests([
                (row["intervention_id"], name, row["x"], row["y"],
                 row.get("place") or row.get("postal_code") or "")
                for row, names in unmatched for name in names
            ])
            name_requests = merge_overpass_requests(name_requests)
            outcomes = run_overpass_requests(
                name_requests, fetch_by_name, is_canceled=feedback.isCanceled,
                pause=pause, report=reporter("noms"), give_up_pause=give_up_pause,
                state=circuit,
            )
            all_outcomes.extend(outcomes)
            failed_ids = absorb(outcomes, keep_unnamed=False)
            # 2) par coordonnées, pour ce qui reste
            first, _reasons, _lines = locate_rows_on_osm(
                name_items, [], list(self._osm_ways.values()), preferred_ways=preferred
            )
            by_name = {i for i, (_m, method) in first.items() if method != "coords"}
            coord_items = [
                (i, x, y) for i, _street, x, y in name_items if i not in by_name
            ] + coord_only
            coord_requests = merge_overpass_requests(plan_coord_requests(coord_items))
            if coord_requests and not feedback.isCanceled():
                outcomes = run_overpass_requests(
                    coord_requests, fetch_by_coords, is_canceled=feedback.isCanceled,
                    pause=pause, report=reporter("coordonnées"),
                    give_up_pause=give_up_pause, state=circuit,
                )
                all_outcomes.extend(outcomes)
                failed_ids |= absorb(outcomes, keep_unnamed=True)
            if n_out_of_range[0]:
                feedback.pushWarning(
                    f"Overpass : {n_out_of_range[0]} sommet(s) hors de la plage Lambert 72 "
                    "après reprojection vers EPSG:31370 — SCR suspect."
                )
            # 3) localisation finale sur toutes les voies du run
            results, reasons, road_lines = locate_rows_on_osm(
                name_items, coord_only, list(self._osm_ways.values()),
                preferred_ways=preferred,
            )
            for i, names, x, y in name_items:
                self._osm_inputs[i] = (names, x, y, preferred.get(i))
            for i, x, y in coord_only:
                self._osm_inputs[i] = ((), x, y, preferred.get(i))

            locations: list[RoadLocation] = []
            road_extents: dict[str, RoadExtent] = {}
            for intervention_id in sorted(results):
                match, method = results[intervention_id]
                ctx = self.__dict__.get("_point_ctx", {}).get(intervention_id, {})
                _score, cause = assess_attachment(
                    match, ctx.get("names", ()), ctx.get("hit")
                )
                if cause:
                    self._reject_attachment(intervention_id, cause)
                    continue
                distance = float(match.get("distance") or 0.0)
                low = match.get("low_confidence") or ""
                if method in ("name", "osm_id") and distance > LOW_CONFIDENCE_DISTANCE_M:
                    # Voie du même nom à 50–150 m : rattachement assumé, marqué.
                    low = low or f"voie du même nom à {distance:.0f} m"
                if low:
                    self.__dict__.setdefault("_low_conf_attached", {})[intervention_id] = low
                stats[{"osm_id": "name"}.get(method, method)] += 1
                row = rows_by_id[intervention_id]
                locations.append(RoadLocation(
                    intervention_id=intervention_id,
                    depth_category=row["depth_category"],
                    road_key=match["road_key"], position_m=match["position_m"],
                    x=match["x"], y=match["y"],
                    side=match["side"], highway=match["highway"],
                ))
                road_extents.setdefault(match["road_key"], match["extent"])
            stats["ambiguous"] = sum(1 for r in reasons.values() if r == "ambiguous")
            unavailable_ids = failed_ids - set(results)
            # Diagnostic des points restés non localisés (journal de fin).
            unlocated = self.__dict__.setdefault("_unlocated", {})
            all_ways = list(self._osm_ways.values())
            spatial = WaySpatialIndex(all_ways) if all_ids - set(results) else None
            for intervention_id in sorted(all_ids - set(results)):
                row = rows_by_id[intervention_id]
                names = self.__dict__.get("_point_ctx", {}).get(intervention_id, {}).get("names", ())
                cause, distance = diagnose_unlocated(
                    row["x"], row["y"], names, all_ways, spatial=spatial
                )
                if intervention_id in unavailable_ids:
                    cause = "Overpass indisponible"
                elif reasons.get(intervention_id) == "ambiguous":
                    cause = "ambigu"
                elif reasons.get(intervention_id) == "far_axis":
                    cause = "axe fusionné éloigné"
                unlocated[intervention_id] = (cause, distance)
            n_total = len(all_outcomes)
            if preferred:
                feedback.pushInfo(
                    f"Overpass : {sum(1 for m, h in results.values() if h == 'osm_id')}/"
                    f"{len(preferred)} point(s) rattaché(s) à la voie désignée par "
                    "Nominatim (identifiant OSM)."
                )
            n_ok = sum(1 for o in all_outcomes if o.data is not None)
            n_cached = sum(1 for o in all_outcomes if o.from_cache)
            summary = (
                f"Overpass : {n_ok}/{n_total} requête(s) réussie(s), {n_cached} servie(s) "
                f"par le cache, {n_total - n_ok} en échec"
            )
            if n_total - n_ok:
                feedback.pushWarning(
                    summary + " — relancez le script pour reprendre les requêtes "
                    "manquantes (le cache conserve les réussies)."
                )
            else:
                feedback.pushInfo(summary + ".")
            feedback.pushInfo(
                f"Overpass : {len(name_requests)} requête(s) par nom, "
                f"{len(coord_requests)} par coordonnées ; {stats['name']} point(s) "
                f"localisé(s) par nom, {stats['fuzzy']} par nom approchant, "
                f"{stats['coords']} par coordonnées (rayon "
                f"{OSM_COORD_FALLBACK_RADIUS_M:g} m), {len(all_ids) - len(results)} non "
                f"localisé(s) dont {stats['ambiguous']} ambigu(s) et "
                f"{len(unavailable_ids)} faute de réponse Overpass."
            )
            return locations, road_extents, stats, unavailable_ids, road_lines

        def _locate_points_on_road(self, rows, feedback, user_agent):
            """Localise chaque ligne (dict avec intervention_id/depth_category/address_raw/x/y)
            sur son axe de rue, côté de la route compris.

            Source 1 : public.fn_asbuilt_locate_on_road (connexion 'be', table
            ref.osm_roads) ; côté par sondes (:meth:`_probe_side_in_db`) ; axe ET
            type de voie via fn_asbuilt_road_geometry, par lots
            (:meth:`_db_road_geometries`) — fonction absente : localisation en
            base désactivée pour le run (tout passe par Overpass) ; axe non
            retenu pour une route : repli Overpass, sinon cordes (compteur).
            Source 2, en REPLI pour les points
            sans tronçon nommé en base : extraction OSM via Overpass et
            localisation Python (:meth:`_locate_via_overpass`). La répartition par
            source est indiquée au journal.

            Retourne (locations, road_extents, had_connection_error, unavailable_ids,
            road_lines) — ``road_lines`` : polyligne de l'axe par road_key quand
            elle est connue (Overpass ; base via fn_asbuilt_road_geometry si la
            migration est appliquee, cf. :meth:`_db_road_geometries`). Un point sans nom de
            rue extractible, ou sans troncon matchant, est omis (pas une erreur — cf.
            spec), compte dans le journal. Si AUCUN point n'a pu etre localise alors
            qu'il y en avait a localiser, un avertissement explicite et actionnable est
            emis (cf. build_locate_failure_warning), sans lever. had_connection_error=True
            sur un echec de connexion/permission (feedback.reportError) ou des sondes
            de cote : recalcul incomplet, l'appelant desactive TOUTE purge. Les echecs
            Overpass restent ISOLES : ``unavailable_ids`` = points non localises faute
            de reponse Overpass ; l'appelant ne suspend la purge que pour les routes
            ou ils figuraient. Jamais sur une simple absence de match.
            """
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            be_connection = md.findConnection(BE_CONNECTION_NAME) if md else None
            if be_connection is None:
                feedback.pushWarning(
                    "Connexion QGIS 'be' introuvable — segments d'axe de rue non calcules."
                )
                return [], {}, True, set(), {}

            locations: list[RoadLocation] = []
            road_extents: dict[str, RoadExtent] = {}
            had_connection_error = False
            n_side_default = 0
            # Points sans troncon nomme en base -> repli Overpass : (row, nom de rue).
            unmatched: list = []
            # Points sans nom de rue extractible -> repli Overpass par coordonnees.
            no_street_rows: list = []
            # Axes fusionnes connus, par road_key (segments qui suivent l'axe).
            road_lines: dict = {}
            probe_enabled = True
            db_located: list = []  # points localisés en base (avant contrôle d'axe)
            # --- Phase A : localisation EN BASE par lots (LATERAL sur VALUES) ---
            # Un aller-retour SQL par lot de SQL_BATCH_SIZE points (au lieu d'un
            # par point et par nom) ; points regroupés par cellule pour des lots
            # compacts. Lot en échec -> repli point par point, avec EXACTEMENT
            # la sémantique d'erreur historique (fatal -> arrêt de la
            # localisation en base pour les points restants).
            candidates = []  # (row, names, hit) dans l'ordre d'origine
            for row in rows:
                if feedback.isCanceled():
                    break
                # Noms de REFERENCE : nom canonique OSM renvoye par Nominatim a
                # ce run (s'il y en a un) puis nom extrait de l'adresse ; les
                # deux sont essayes quand ils different.
                hit = getattr(self, "_nominatim_hits", {}).get(row["intervention_id"])
                names = reference_street_names(extract_street_name(row["address_raw"]), hit)
                self.__dict__.setdefault("_point_ctx", {})[row["intervention_id"]] = {
                    "names": names, "hit": hit, "address": row["address_raw"] or "",
                }
                if not names:
                    # Pas de nom exploitable : ni la base ni Overpass par nom —
                    # repli direct par coordonnees.
                    no_street_rows.append(row)
                    continue
                candidates.append((row, names, hit))

            batch_enabled = True
            # Sans fn_asbuilt_road_geometry, les routes de la base n'ont NI axe
            # NI type de voie (cordes droites, décalage par défaut) : la
            # localisation en base est alors DÉSACTIVÉE pour ce run et tous les
            # points passent par Overpass (axe suivi, cache disque).
            if candidates and not self._road_geometry_available(be_connection, feedback):
                unmatched.extend((row, names) for row, names, _hit in candidates)
                candidates = []
            found = {}      # index candidat -> (ligne resultat, litteral du nom)
            failed = set()  # candidats en erreur (non localisables en base ce run)
            fatal = False
            depth = max((len(c[1]) for c in candidates), default=0)
            for level in range(depth):
                if fatal or feedback.isCanceled():
                    break
                todo = [
                    k for k, (row, names, _hit) in enumerate(candidates)
                    if k not in found and k not in failed and len(names) > level
                ]
                todo.sort(key=lambda k: batch_cell_key(
                    candidates[k][0]["x"], candidates[k][0]["y"]))
                for start in range(0, len(todo), SQL_BATCH_SIZE):
                    if fatal or feedback.isCanceled():
                        break
                    chunk = todo[start:start + SQL_BATCH_SIZE]
                    items = [
                        (k, candidates[k][0]["x"], candidates[k][0]["y"],
                         QgsExpression.quotedValue(candidates[k][1][level]))
                        for k in chunk
                    ]
                    if batch_enabled:
                        try:
                            rows_by_tag = first_rows_by_tag(
                                be_connection.executeSql(
                                    batch_locate_sql(items, LOCATE_RADIUS_M)
                                ) or []
                            )
                            for k, _x, _y, literal in items:
                                if k in rows_by_tag:
                                    found[k] = (rows_by_tag[k], literal)
                            continue
                        except Exception:
                            # Lots indisponibles (ex. LATERAL refusé) : repli point
                            # par point pour ce lot et les suivants.
                            batch_enabled = False
                    for k, x, y, literal in items:
                        row = candidates[k][0]
                        try:
                            result = be_connection.executeSql(
                                self._locate_sql(x, y, literal)
                            )
                        except Exception as exc:
                            feedback.reportError(
                                f"fn_asbuilt_locate_on_road indisponible pour "
                                f"{row['intervention_id']} : {exc}",
                                fatalError=False,
                            )
                            had_connection_error = True
                            failed.add(k)
                            # Fonction absente / droit refuse / connexion perdue :
                            # l'appel echouera a l'identique pour tous les points
                            # restants — inutile de journaliser une erreur par
                            # point. Une autre exception (propre a CE point)
                            # laisse la boucle continuer.
                            message = str(exc).lower()
                            if any(marker in message for marker in _LOCATE_FATAL_ERROR_MARKERS):
                                feedback.pushWarning(
                                    "fn_asbuilt_locate_on_road inutilisable (fonction "
                                    "absente, droit refuse ou connexion perdue) — "
                                    "localisation interrompue pour les points restants."
                                )
                                fatal = True
                                break
                            continue
                        if result:
                            found[k] = (tuple(result[0]), literal)

            # --- Sondes de côté par lots (2 par point localisé) -----------------
            probe_positions = {}  # (k, 0|1) -> (road_key, position_m)
            probe_batch_ok = False
            probe_items = []
            for k, (result, literal) in found.items():
                row = candidates[k][0]
                probes = side_probe_points(row["x"], row["y"], float(result[2]), float(result[3]))
                if probes is not None:
                    for j, (qx, qy) in enumerate(probes):
                        probe_items.append((2 * k + j, qx, qy, literal))
            if probe_items and not fatal and batch_enabled:
                try:
                    for start in range(0, len(probe_items), SQL_BATCH_SIZE):
                        chunk = probe_items[start:start + SQL_BATCH_SIZE]
                        rows_by_tag = first_rows_by_tag(
                            be_connection.executeSql(batch_locate_sql(chunk, LOCATE_RADIUS_M))
                            or []
                        )
                        for tag, *_rest in chunk:
                            if tag in rows_by_tag:
                                probe_positions[tag] = (
                                    rows_by_tag[tag][0], float(rows_by_tag[tag][1]),
                                )
                    probe_batch_ok = True
                except Exception:
                    probe_positions = {}  # repli : sondes point par point

            # --- Phase B : points localisés en base, dans l'ordre d'origine -----
            for k, (row, names, hit) in enumerate(candidates):
                if k in failed:
                    continue
                if k not in found:
                    if fatal:
                        continue  # jamais interrogé : ni base ni repli ce run
                    unmatched.append((row, names))
                    continue  # aucun troncon nomme dans le rayon : repli Overpass
                result, street_literal = found[k]
                (road_key, position_m, px, py,
                 road_length_m, sx, sy, ex, ey) = result
                px, py = float(px), float(py)
                db_distance = math.hypot(row["x"] - px, row["y"] - py)
                _score, cause = assess_attachment(
                    {"method": "db", "distance": db_distance}, names, hit,
                )
                if cause:
                    self._reject_attachment(row["intervention_id"], cause)
                    continue
                if db_distance > LOW_CONFIDENCE_DISTANCE_M:
                    self.__dict__.setdefault("_low_conf_attached", {})[
                        row["intervention_id"]] = f"voie du même nom à {db_distance:.0f} m"
                side = None
                if probe_batch_ok:
                    if side_probe_points(row["x"], row["y"], px, py) is None:
                        side = SIDE_RIGHT
                    else:
                        plus = probe_positions.get(2 * k)
                        minus = probe_positions.get(2 * k + 1)
                        if plus and minus and plus[0] == road_key and minus[0] == road_key:
                            side = side_from_probe_positions(plus[1], minus[1])
                elif probe_enabled:
                    try:
                        side = self._probe_side_in_db(
                            be_connection, row, px, py, road_key, street_literal
                        )
                    except Exception as exc:
                        # Cotes faux -> cles (.., side) fausses : purge desactivee.
                        probe_enabled = False
                        had_connection_error = True
                        feedback.reportError(
                            f"Sonde de cote (fn_asbuilt_locate_on_road) en echec : "
                            f"{exc} — cote 'R' par defaut pour les points restants, "
                            "purge desactivee.",
                            fatalError=False,
                        )
                if side is None:
                    side = SIDE_RIGHT
                    n_side_default += 1
                db_located.append({
                    "row": row, "names": names, "literal": street_literal,
                    "road_length_m": road_length_m,
                    "location": RoadLocation(
                        intervention_id=row["intervention_id"],
                        depth_category=row["depth_category"],
                        road_key=road_key, position_m=float(position_m),
                        x=px, y=py, side=side, highway="",
                    ),
                    "extent": RoadExtent(
                        length_m=float(road_length_m),
                        start_x=float(sx), start_y=float(sy),
                        end_x=float(ex), end_y=float(ey),
                    ),
                })

            # --- Phase C : axe + type de voie des routes de la base, par lots ---
            # Une requête LATERAL sur fn_asbuilt_road_geometry par lot de routes
            # (un point représentant par road_key). Géométrie retenue seulement
            # si road_key identique et longueur = road_length_m ; sinon la route
            # repasse par Overpass (axe suivi), et en dernier recours reste en
            # cordes droites (compteur).
            db_fallback = {}  # intervention_id -> entrée db_located (cordes si Overpass échoue)
            geometries = self._db_road_geometries(be_connection, db_located, feedback)
            for entry in db_located:
                loc = entry["location"]
                found_geometry = geometries.get(loc.road_key) if geometries is not None else None
                if found_geometry is None:
                    db_fallback[loc.intervention_id] = entry
                    unmatched.append((entry["row"], entry["names"]))
                    continue
                parts, highway = found_geometry
                road_lines[loc.road_key] = parts
                road_extents.setdefault(loc.road_key, entry["extent"])
                locations.append(dataclasses.replace(loc, highway=highway))

            n_db = sum(1 for loc in locations if not loc.road_key.startswith("overpass"))
            stats = {"name": 0, "fuzzy": 0, "coords": 0, "ambiguous": 0}
            overpass_status = None
            unavailable_ids: set = set()
            ov_ids: set = set()
            if (unmatched or no_street_rows) and not feedback.isCanceled():
                ov_locations, ov_extents, stats, unavailable_ids, ov_lines = (
                    self._locate_via_overpass(
                        unmatched, no_street_rows, feedback, user_agent
                    )
                )
                road_lines.update(ov_lines)
                # 'failed' : aucune reponse Overpass exploitable pour ces points.
                overpass_status = (
                    "failed" if unavailable_ids and not ov_locations else "ok"
                )
                locations.extend(ov_locations)
                # road_key prefixes "overpass" : aucune collision avec ceux de la base.
                road_extents.update(ov_extents)
                ov_ids = {loc.intervention_id for loc in ov_locations}
            chords = [entry for i, entry in db_fallback.items() if i not in ov_ids]
            for entry in chords:
                locations.append(entry["location"])
                road_extents.setdefault(entry["location"].road_key, entry["extent"])
            if db_fallback:
                feedback.pushInfo(
                    f"Segments : {len(db_fallback)} point(s) localisé(s) en base sans axe "
                    f"retenu -> repli Overpass ; {len(chords)} resté(s) en cordes droites "
                    "(axe introuvable)."
                )
            ov_ids |= {entry["location"].intervention_id for entry in chords}
            n_no_street = sum(1 for row in no_street_rows if row["intervention_id"] not in ov_ids)
            n_no_match = sum(1 for row, _s in unmatched if row["intervention_id"] not in ov_ids)
            n_unlocated = n_no_street + n_no_match

            summary = (
                f"Segments : {len(locations)} point(s) localise(s) sur {len(rows)} — "
                f"{n_db} via ref.osm_roads (nom), {stats['name']} via Overpass (nom), "
                f"{stats['fuzzy']} rattaché(s) par nom approchant, "
                f"{stats['coords']} via Overpass (coordonnées, rayon "
                f"{OSM_COORD_FALLBACK_RADIUS_M:g} m), {n_unlocated} non localisé(s) "
                f"(dont {stats['ambiguous']} ambigu(s), {len(unavailable_ids)} faute de "
                f"réponse Overpass ; {n_no_street} sans nom de rue dans l'adresse)."
            )
            if n_side_default:
                summary += (
                    f" Cote de la route indetermine pour {n_side_default} point(s) "
                    "localise(s) en base -> 'R' par defaut."
                )
            feedback.pushInfo(summary)
            # Echec TOTAL de localisation (hors erreur de connexion en base, deja
            # signalee via reportError, mais y compris l'echec du repli Overpass)
            # et hors annulation (compteurs partiels) : sans ce message, le run se
            # terminerait sans aucun segment et sans explication (constate :
            # ref.osm_roads limitee a Bruxelles, points en Communaute
            # germanophone).
            if (
                (not had_connection_error or overpass_status == "failed")
                and not feedback.isCanceled()
            ):
                warning = build_locate_failure_warning(
                    len(rows), len(locations), n_no_street, n_no_match,
                    overpass_status,
                )
                if warning:
                    feedback.pushWarning(warning)
            return locations, road_extents, had_connection_error, unavailable_ids, road_lines

        def _segments_is_multi(self, feedback):
            """La colonne geom des segments est-elle MultiLineString ? (sonde memorisee par run).

            geometry_columns via la connexion 'be'. Colonne encore LineString
            (migration non appliquee) ou sonde en echec -> False : on ecrit des
            LineString (premiere partie), avec avertissement.
            """
            cached = getattr(self, "_segments_multi", None)
            if cached is not None:
                return cached
            be_connection = self._be_connection()
            geometry_type = None
            if be_connection is not None:
                try:
                    rows = be_connection.executeSql(
                        "SELECT type FROM geometry_columns WHERE "
                        f"f_table_schema = '{SEGMENTS_TABLE_SCHEMA}' AND "
                        f"f_table_name = '{SEGMENTS_TABLE_NAME}' AND "
                        f"f_geometry_column = '{BE_GEOM_COLUMN}'"
                    ) or []
                    geometry_type = str(rows[0][0]) if rows else None
                except Exception:
                    geometry_type = None
            multi = is_multilinestring_type(geometry_type)
            if not multi:
                feedback.pushWarning(
                    f"Segments : colonne geom encore {geometry_type or 'de type inconnu'} "
                    "— migration MultiLineString recommandée (les segments sont écrits "
                    "en LineString, première partie seulement)."
                )
            self._segments_multi = multi
            return multi

        def _road_geometry_available(self, be_connection, feedback):
            """fn_asbuilt_road_geometry existe-t-elle ? (sonde pg_proc memorisee par run).

            Absente -> message unique : localisation des routes uniquement via
            Overpass pour ce run (l'appelant desactive la localisation en base).
            """
            state = self.__dict__.setdefault("_road_geom_state", {"available": None, "fallback": 0})
            if state["available"] is None:
                try:
                    probe = be_connection.executeSql(
                        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
                        "ON n.oid = p.pronamespace WHERE n.nspname = 'public' "
                        "AND p.proname = 'fn_asbuilt_road_geometry'"
                    )
                    state["available"] = bool(probe and int(probe[0][0]) > 0)
                except Exception:
                    state["available"] = False
                if not state["available"]:
                    feedback.pushWarning(
                        "Segments : fonction fn_asbuilt_road_geometry absente : "
                        "localisation des routes uniquement via Overpass (axe suivi) — "
                        "appliquez migration_road_geom.sql pour utiliser aussi "
                        "ref.osm_roads."
                    )
            return state["available"]

        def _db_road_geometries(self, be_connection, db_located, feedback):
            """Axe + type de voie des routes de la base, PAR LOTS -> dict road_key -> (parties, highway).

            Un point représentant par road_key ; requête LATERAL sur
            fn_asbuilt_road_geometry (:func:`batch_road_geometry_sql`). Une route
            n'est présente dans le résultat que si sa géométrie est retenue
            (:func:`pick_db_road_geometry` : road_key identique, longueur =
            road_length_m). Lot en échec -> None (toutes les routes de la base
            repassent par Overpass) avec avertissement.
            """
            representatives = {}
            for entry in db_located:
                representatives.setdefault(entry["location"].road_key, entry)
            if not representatives:
                return {}
            keys = sorted(representatives)
            retained = {}
            try:
                for start in range(0, len(keys), SQL_BATCH_SIZE):
                    chunk = keys[start:start + SQL_BATCH_SIZE]
                    items = [
                        (n, representatives[key]["row"]["x"], representatives[key]["row"]["y"],
                         representatives[key]["literal"])
                        for n, key in enumerate(chunk)
                    ]
                    rows_by_tag = first_rows_by_tag(
                        be_connection.executeSql(batch_road_geometry_sql(items, LOCATE_RADIUS_M))
                        or []
                    )
                    for n, key in enumerate(chunk):
                        picked = pick_db_road_geometry(
                            rows_by_tag.get(n), key, representatives[key]["road_length_m"]
                        )
                        if picked is not None:
                            retained[key] = picked
            except Exception as exc:
                self._road_geom_state["available"] = False
                feedback.pushWarning(
                    f"Segments : fn_asbuilt_road_geometry en échec ({exc}) — routes de la "
                    "base relocalisées via Overpass."
                )
                return None
            return retained

        def _log_locate_extras(self, feedback):
            """Journal de fin d'etape 2 : rattachements ecartes, alimentation de ref.osm_roads."""
            attached = self.__dict__.get("_low_conf_attached", {})
            ctx = self.__dict__.get("_point_ctx", {})
            if attached:
                examples = "; ".join(
                    f"{i} ({ctx.get(i, {}).get('address', '')}) : {why}"
                    for i, why in sorted(attached.items())[:5]
                )
                n_fuzzy = sum(1 for why in attached.values() if why.startswith("nom approchant"))
                n_lone = sum(1 for why in attached.values() if why.startswith("voie sans nom"))
                feedback.pushWarning(
                    f"Segments : {len(attached)} rattachement(s) à FAIBLE CONFIANCE "
                    f"conservé(s), dont {n_fuzzy} rattaché(s) par nom approchant et "
                    f"{n_lone} rattaché(s) à une voie sans nom "
                    f"{OSM_COORD_FALLBACK_RADIUS_M:g}–{COORD_FALLBACK_LONE_RADIUS_M:g} m — "
                    f"{examples}"
                )
            unlocated = self.__dict__.get("_unlocated", {})
            if unlocated:
                by_cause = Counter(cause for cause, _d in unlocated.values())
                examples = "; ".join(
                    f"{i} ({ctx.get(i, {}).get('address', '')}) : {cause}"
                    + (f", voie nommée la plus proche à {d:.0f} m" if d is not None else "")
                    for i, (cause, d) in sorted(unlocated.items())[:10]
                )
                feedback.pushWarning(
                    f"Segments : {len(unlocated)} point(s) non localisé(s) — "
                    + ", ".join(f"{n} {cause}" for cause, n in by_cause.most_common())
                    + f". Exemples : {examples}"
                )
            rejected = self.__dict__.get("_low_confidence", {})
            if rejected:
                ctx = self.__dict__.get("_point_ctx", {})
                examples = "; ".join(
                    f"{i} ({ctx.get(i, {}).get('address', '')}) : {cause}"
                    for i, cause in sorted(rejected.items())[:5]
                )
                feedback.pushWarning(
                    f"Segments : {len(rejected)} rattachement(s) à faible confiance "
                    f"écarté(s) — {examples}"
                )
            state = self.__dict__.get("_store_state") or {}
            if state.get("offered"):
                inserted = state["inserted"]
                feedback.pushInfo(
                    f"ref.osm_roads : {inserted} voie(s) ajoutée(s) "
                    f"({state['offered'] - inserted} déjà présente(s))."
                )
                if inserted:
                    feedback.pushWarning(
                        "ref.osm_roads vient d'être alimentée : les road_key de la base "
                        "et d'Overpass diffèrent — cochez « Reconstruire tous les "
                        "segments » après la première alimentation."
                    )

        def _read_connectors(self, feedback):
            """Couche + etat des connecteurs en base, ou None si la table est absente.

            Presence sondee UNE fois par run (information_schema) ; absente ->
            une ligne d'info « couche connecteurs indisponible (migration_connectors
            requise) », aucune erreur. Retourne ``(couche, etats, fids)`` :
            ``etats`` = dict intervention_id -> depth_category/side/road_key/
            length_m/coords (cf. connector_changed).
            """
            available = self.__dict__.get("_connectors_available")
            be_connection = self._be_connection()
            if available is None:
                available = False
                if be_connection is not None:
                    try:
                        rows = be_connection.executeSql(
                            "SELECT count(*) FROM information_schema.tables WHERE "
                            f"table_schema = '{CONNECTORS_TABLE_SCHEMA}' AND "
                            f"table_name = '{CONNECTORS_TABLE_NAME}'"
                        )
                        available = bool(rows and int(rows[0][0]) > 0)
                    except Exception:
                        available = False
                self._connectors_available = available
                if not available:
                    feedback.pushInfo(
                        "Connecteurs : couche connecteurs indisponible "
                        "(migration_connectors requise)."
                    )
            if not available:
                return None
            layer = self._open_be_layer(
                CONNECTORS_TABLE_SCHEMA, CONNECTORS_TABLE_NAME, BE_GEOM_COLUMN,
                QgsWkbTypes.LineString, feedback,
            )
            if layer is None or not layer.primaryKeyAttributes():
                return None
            states, fids = {}, {}
            for feat in layer.getFeatures():
                intervention_id = feat["intervention_id"]
                if not isinstance(intervention_id, str) or intervention_id in fids:
                    continue
                fids[intervention_id] = feat.id()
                coords = None
                geom = feat.geometry()
                if geom is not None and not geom.isEmpty():
                    try:
                        coords = tuple((p.x(), p.y()) for p in geom.asPolyline())
                    except (TypeError, ValueError):
                        coords = None
                length_m = feat["length_m"]
                states[intervention_id] = {
                    "depth_category": _str_or_empty(feat["depth_category"]),
                    "side": _str_or_empty(feat["side"]),
                    "road_key": _str_or_empty(feat["road_key"]),
                    "length_m": float(length_m) if isinstance(length_m, (int, float)) else None,
                    "coords": coords,
                }
            return layer, states, fids

        def _sync_connectors(self, feedback, connectors, points, locations, halves,
                             merged_groups, scope_ids, deletions_allowed, protected_ids):
            """Etape 2b : connecteurs point geocode -> extremite de son segment (axe decale).

            Memes localisations et memes moities que les segments
            (:func:`build_connectors`), meme logique incrementale
            (:func:`plan_connector_sync` : seuls les points relocalises a ce run
            sont recalcules ; un connecteur identique n'est pas reecrit ; ceux
            des points devenus gris ou supprimes sont retires) et memes gardes
            de purge (``deletions_allowed`` ; points Overpass indisponibles
            proteges). Best-effort : un echec d'ecriture est journalise.
            """
            layer, existing, fids = connectors
            fresh = build_connectors(points, locations, halves, merged_groups)
            plan = plan_connector_sync(fresh, existing, scope_ids, set(points))
            to_delete = [i for i in plan.to_delete if i not in protected_ids]
            if not deletions_allowed:
                to_delete = [i for i in to_delete if i not in points]  # gris/supprimés seulement
            fields = layer.fields()
            inserted = updated = deleted = failed = 0
            for connector in plan.to_insert + plan.to_update:
                if feedback.isCanceled():
                    break
                fid = fids.get(connector.intervention_id)
                geom = QgsGeometry.fromPolylineXY([
                    QgsPointXY(connector.start_x, connector.start_y),
                    QgsPointXY(connector.end_x, connector.end_y),
                ])
                values = {
                    "intervention_id": connector.intervention_id,
                    "depth_category": connector.depth_category,
                    "side": connector.side,
                    "road_key": connector.road_key,
                    "length_m": connector.length_m,
                }
                layer.startEditing()
                try:
                    if fid is not None:
                        ok = layer.changeAttributeValues(fid, {
                            fields.indexOf(k): v for k, v in values.items()
                            if k != "intervention_id"
                        })
                        ok = layer.changeGeometry(fid, geom) and ok
                    else:
                        feat = QgsFeature(fields)
                        for k, v in values.items():
                            feat.setAttribute(k, v)
                        now = QDateTime.currentDateTimeUtc()
                        for ts_col in ("created_at", "updated_at"):
                            idx = fields.indexOf(ts_col)
                            if idx >= 0:
                                feat.setAttribute(idx, now)
                        feat.setGeometry(geom)
                        ok = layer.addFeature(feat)
                    ok = ok and layer.commitChanges()
                except Exception as exc:
                    feedback.reportError(
                        f"Connecteur {connector.intervention_id} : {exc}", fatalError=False
                    )
                    ok = False
                if ok:
                    updated += 1 if fid is not None else 0
                    inserted += 0 if fid is not None else 1
                else:
                    failed += 1
                    layer.rollBack()
            if to_delete and not feedback.isCanceled():
                layer.startEditing()
                if layer.deleteFeatures([fids[i] for i in to_delete]) and layer.commitChanges():
                    deleted = len(to_delete)
                else:
                    failed += len(to_delete)
                    layer.rollBack()
            feedback.pushInfo(
                f"Connecteurs : {inserted} inséré(s) / {updated} mis à jour / {deleted} "
                f"supprimé(s) / {plan.unchanged} inchangé(s) ; {failed} échec(s)."
            )

        def _reject_attachment(self, intervention_id, cause):
            """Memorise un rattachement a faible confiance ecarte (journal de fin de run)."""
            rejected = self.__dict__.setdefault("_low_confidence", {})
            rejected[intervention_id] = cause

        def _store_osm_ways(self, ways, feedback):
            """Envoie les voies Overpass NOUVELLES du run a ref.osm_roads (best-effort).

            Via ``public.fn_asbuilt_store_osm_ways(jsonb)`` (SECURITY DEFINER,
            ON CONFLICT DO NOTHING, types Farois seulement) — le compte 'be' n'a
            aucun droit direct sur ref. Sa presence est sondee UNE fois par run
            (pg_proc) ; absente -> une ligne d'info, rien d'autre. Lots de
            :data:`OSM_STORE_BATCH_SIZE`, dedoublonnes par osm_id sur le run
            (:func:`build_store_payload`), JSON en chaine dollar-quoted
            (:func:`store_osm_ways_sql`). Un echec = avertissement : jamais
            d'interruption, jamais d'effet sur la purge des segments.
            """
            state = self.__dict__.setdefault(
                "_store_state",
                {"available": None, "sent": set(), "inserted": 0, "offered": 0, "failed": 0},
            )
            be_connection = self._be_connection()
            if be_connection is None or not ways:
                return
            if state["available"] is None:
                try:
                    probe = be_connection.executeSql(
                        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
                        "ON n.oid = p.pronamespace WHERE n.nspname = 'public' "
                        "AND p.proname = 'fn_asbuilt_store_osm_ways'"
                    )
                    state["available"] = bool(probe and int(probe[0][0]) > 0)
                except Exception:
                    state["available"] = False
                if not state["available"]:
                    feedback.pushInfo(
                        "ref.osm_roads : stockage OSM en base indisponible (fonction "
                        "fn_asbuilt_store_osm_ways absente)."
                    )
            if not state["available"]:
                return
            payload, ids = build_store_payload(ways, state["sent"])
            state["sent"].update(ids)
            for start in range(0, len(payload), OSM_STORE_BATCH_SIZE):
                batch = payload[start:start + OSM_STORE_BATCH_SIZE]
                try:
                    rows = be_connection.executeSql(store_osm_ways_sql(batch)) or []
                    inserted = int(rows[0][0]) if rows and rows[0][0] is not None else 0
                except Exception as exc:
                    state["failed"] += len(batch)
                    feedback.pushWarning(
                        f"ref.osm_roads : envoi de {len(batch)} voie(s) en échec ({exc}) — "
                        "sans effet sur les segments."
                    )
                    continue
                state["inserted"] += inserted
                state["offered"] += len(batch)

        def _final_overpass_pass(self, locations, road_extents, road_lines):
            """Relocalise les points Overpass du run sur TOUTES les voies extraites.

            Pure recombinaison (:func:`locate_rows_on_osm`), sans requete : les
            points localises en base (ref.osm_roads) sont inchanges ; un point
            Overpass que la passe finale ne localise plus (cas limite) garde sa
            localisation initiale. Retourne ``(locations, road_extents,
            road_lines)``.
            """
            inputs = getattr(self, "_osm_inputs", {}) or {}
            if not inputs:
                return locations, road_extents, road_lines
            name_items = [(i, names, x, y) for i, (names, x, y, _p) in inputs.items() if names]
            coord_items = [(i, x, y) for i, (names, x, y, _p) in inputs.items() if not names]
            preferred = {i: p for i, (_n, _x, _y, p) in inputs.items() if p}
            results, _reasons, osm_lines = locate_rows_on_osm(
                name_items, coord_items, list(self._osm_ways.values()),
                preferred_ways=preferred,
            )
            new_lines = {
                key: line for key, line in road_lines.items()
                if not key.startswith("overpass")
            }
            new_lines.update(osm_lines)
            new_locations = []
            new_extents = {
                key: ext for key, ext in road_extents.items()
                if not key.startswith("overpass")
            }
            for loc in locations:
                result = results.get(loc.intervention_id)
                if result is not None and loc.road_key.startswith("overpass"):
                    match = result[0]
                    ctx = self.__dict__.get("_point_ctx", {}).get(loc.intervention_id, {})
                    _score, cause = assess_attachment(match, ctx.get("names", ()), ctx.get("hit"))
                    if cause:
                        self._reject_attachment(loc.intervention_id, cause)
                        continue
                    loc = RoadLocation(
                        intervention_id=loc.intervention_id,
                        depth_category=loc.depth_category,
                        road_key=match["road_key"], position_m=match["position_m"],
                        x=match["x"], y=match["y"],
                        side=match["side"], highway=match["highway"],
                    )
                    new_extents.setdefault(match["road_key"], match["extent"])
                elif loc.road_key.startswith("overpass"):
                    new_extents.setdefault(loc.road_key, road_extents.get(loc.road_key))
                new_locations.append(loc)
            for loc in new_locations:  # localisations initiales conservées
                if loc.road_key.startswith("overpass") and loc.road_key not in new_lines:
                    if loc.road_key in road_lines:
                        new_lines[loc.road_key] = road_lines[loc.road_key]
            return (
                new_locations,
                {k: v for k, v in new_extents.items() if v is not None},
                new_lines,
            )

        def _sync_segments(self, feedback, user_agent, changed_ids=None, full_rebuild=False,
                           recompute_existing=True):
            """Regenere les segments d'axe de rue — INCREMENTAL par defaut.

            Relit TOUT public.geofiber_asbuilt_depth_points et TOUTE la table des
            segments, puis :

            * mode INCREMENTAL (defaut) : ne relocalise et ne recalcule que les
              routes impactees — points « sales » (``changed_ids`` : nouveaux ou
              modifies par l'upsert de CE run ; points de couleur absents de tout
              segment ; points cites par des segments mais devenus gris ou
              supprimes, cf. initial_dirty_ids), propages a leurs routes et aux
              autres points de ces routes jusqu'au point fixe
              (expand_dirty_roads). Les routes propres ne sont ni relocalisees,
              ni recalculees, ni reecrites, ni purgees ;
            * mode COMPLET : ``full_rebuild`` (parametre avance FULL_REBUILD, a
              utiliser apres un changement de regle : seuils, decalages, cotes,
              ref.osm_roads), ``changed_ids`` None (points modifies inconnus) ou
              table segments vide (premier run) : tous les points sont localises.

            Dans les deux cas, plan_segment_sync ne fait ecrire que les segments
            nouveaux ou DIFFERENTS de l'existant ; la purge ne vise que le
            perimetre recalcule. Localisation : axe de rue ET cote (base puis
            repli Overpass, cf. _locate_points_on_road), moities par (road_key,
            side) via build_segment_halves. Cle d'un segment : (point_a, point_b,
            half, side). Geometrie enregistree = moitie decalee vers son cote
            selon le type de voie (segment_half_geometry) ; length_m/is_long
            restent mesures sur l'axe.

            Prerequis de schema : colonne ``side`` sur la table segments (cf.
            brouillon de migration). Absente -> avertissement « migration requise »
            et RIEN n'est fait (ni localisation, ni ecriture, ni purge).

            Best-effort : si _locate_points_on_road signale une erreur de connexion
            (base, sondes de cote ou repli Overpass), ou si la lecture des points ne
            peut etre verifiee complete (count(*) exact divergent ou en echec),
            AUCUNE suppression n'est jouee (cf. Review Focus - ne pas purger sur un
            recalcul non fiable), seul l'upsert du lot obtenu est tente. Idem si
            aucun point n'a ete localise alors qu'il y en avait. Annulation
            utilisateur : les boucles d'upsert et de purge s'arretent (le drapeau
            d'annulation etant persistant, une annulation pendant la localisation
            n'entraine aucune purge).

            Ordre des points DETERMINISTE (tri par intervention_id des rows ET des
            localisations avant build_segment_halves, quel que soit l'ordre des
            lots de localisation incrementaux) : l'ordre d'iteration QGIS sur une couche
            postgres n'est PAS garanti stable d'un run a l'autre, et
            build_segment_halves depart les ex-aequo de position_m par ordre
            d'entree -- sans ce tri, deux runs sans changement de donnees pourraient
            reordonner les paires et casser l'idempotence (cle a/b differente d'un
            run a l'autre pour les memes points).

            Un SegmentHalf de longueur nulle (deux points geocodes au meme endroit,
            ou un point situe exactement sur un bout de route) N'EST PAS filtre :
            c'est une geometrie LineString valide (PostGIS l'accepte), un cas de
            donnees legitime bien que rare -- pas une erreur (dessine sur l'axe,
            sans decalage : direction indefinie).
            """
            # Voies Overpass et entrees des points cumulees sur CE run (cf.
            # _locate_via_overpass) : repartent de zero a chaque synchronisation.
            self._osm_ways, self._osm_inputs = {}, {}
            # Contexte des points (noms de reference, metadonnees Nominatim du
            # run), rattachements ecartes, alimentation de ref.osm_roads : par run.
            self._point_ctx, self._low_confidence = {}, {}
            self._low_conf_attached, self._unlocated = {}, {}
            self._connectors_available = None  # sonde de la table, une fois par run
            self._store_state = {
                "available": None, "sent": set(), "inserted": 0, "offered": 0, "failed": 0,
            }
            # Sonde « axe des routes de la base » (fn_asbuilt_road_geometry) :
            # une seule par run, memorisee (cf. _road_geometry_available).
            self._road_geom_state = {"available": None, "fallback": 0}
            points_layer = self._open_be_points_layer(feedback)
            if points_layer is None:
                return

            # Table segments ouverte et verifiee AVANT la localisation (sondes
            # SQL, appels Overpass) : inutile de payer ce cout si l'ecriture est
            # de toute facon impossible. Type de geometrie selon la colonne
            # reelle (MultiLineString, ou LineString avant migration).
            multi_column = self._segments_is_multi(feedback)
            segments_layer = self._open_be_layer(
                SEGMENTS_TABLE_SCHEMA, SEGMENTS_TABLE_NAME, BE_GEOM_COLUMN,
                QgsWkbTypes.MultiLineString if multi_column else QgsWkbTypes.LineString,
                feedback,
            )
            if segments_layer is None:
                return
            if not segments_layer.primaryKeyAttributes():
                feedback.pushWarning(
                    f"Couche {SEGMENTS_TABLE_SCHEMA}.{SEGMENTS_TABLE_NAME} sans cle "
                    "primaire exploitable — ecriture impossible, rien n'a ete ecrit "
                    "en base."
                )
                return
            fields = segments_layer.fields()
            if fields.indexOf("side") < 0:
                feedback.pushWarning(
                    f"Colonne 'side' absente de {SEGMENTS_TABLE_SCHEMA}."
                    f"{SEGMENTS_TABLE_NAME} — MIGRATION REQUISE (ajout de la colonne "
                    "side 'L'/'R' et cle primaire (point_a_intervention_id, "
                    "point_b_intervention_id, half, side)). Segments non recalcules : "
                    "rien n'a ete ecrit ni supprime pour ce run."
                )
                return

            features = sorted(
                points_layer.getFeatures(), key=lambda f: f["intervention_id"] or ""
            )
            total_features_seen = 0
            rows = []
            for feat in features:
                total_features_seen += 1
                category = feat["depth_category"]
                # Points GRIS exclus AVANT la localisation : ni sondes SQL, ni
                # Overpass pour eux (build_segment_halves les ignore aussi).
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
                    "place": _str_or_empty(feat["place"]),
                    "postal_code": _str_or_empty(feat["postal_code"]),
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

            # Un seul parcours de la table segments : cle -> fid (ecritures) et
            # cle -> etat (comparaison : un segment identique n'est pas reecrit ;
            # index route <-> points pour le mode incremental).
            existing_fids = {}
            existing = {}
            for feat in segments_layer.getFeatures():
                key = (
                    feat["point_a_intervention_id"],
                    feat["point_b_intervention_id"],
                    feat["half"],
                    feat["side"],
                )
                if key in existing_fids:
                    continue
                existing_fids[key] = feat.id()
                coords = None
                geom = feat.geometry()
                if geom is not None and not geom.isEmpty():
                    try:
                        lines = (
                            geom.asMultiPolyline() if geom.isMultipart()
                            else [geom.asPolyline()]
                        )
                        coords = tuple(
                            tuple((p.x(), p.y()) for p in part) for part in lines
                        )
                    except (TypeError, ValueError):
                        coords = None
                length_m = feat["length_m"]
                is_long = feat["is_long"]
                existing[key] = {
                    "road_key": _str_or_empty(feat["road_key"]),
                    "depth_category": _str_or_empty(feat["depth_category"]),
                    "is_long": is_long if isinstance(is_long, bool) else None,
                    "length_m": float(length_m) if isinstance(length_m, (int, float)) else None,
                    "coords": coords,
                }

            # Connecteurs (etape 2b) : table optionnelle (migration_connectors),
            # lue ici pour que les points SANS connecteur soient relocalises.
            connectors = self._read_connectors(feedback)

            # --- mode : complet ou incremental ------------------------------
            # Complet si demande (FULL_REBUILD), si les points modifies par CE run
            # sont inconnus (upsert interrompu : changed_ids None), ou si la
            # table segments est vide (premier run : tout est a construire).
            full = full_rebuild or changed_ids is None or not existing
            had_connection_error = False
            unavailable_ids: set = set()
            road_ids, id_roads, covered_ids = index_existing_segments(existing)
            if full:
                reason = (
                    "demandée" if full_rebuild
                    else "table des segments vide" if not existing
                    else "points modifiés inconnus (upsert interrompu)"
                )
                feedback.pushInfo(
                    f"Segments : reconstruction complète ({reason}) sur "
                    f"{total_features_seen} point(s) de {BE_TABLE_SCHEMA}."
                    f"{BE_TABLE_NAME} ({len(rows)} de profondeur connue)…"
                )
                (locations, road_extents, had_connection_error,
                 unavailable_ids, road_lines) = self._locate_points_on_road(
                    rows, feedback, user_agent
                )
                n_attempted = len(rows)
                scope_roads = None
            else:
                rows_by_id = {row["intervention_id"]: row for row in rows}
                # Tout point de couleur est localisable : par nom, ou a defaut par
                # coordonnees (repli Overpass, meme sans nom de rue dans l'adresse).
                locatable_ids = set(rows_by_id)
                # Points co-localises (fusionnes en un seul noeud, cf.
                # merge_colocated) : un membre non representant n'apparait dans
                # aucun segment -> couvert si son groupe l'est ; un membre sale
                # rend tout le groupe sale (expand_dirty_roads).
                companions = colocated_raw_groups([
                    (i, extract_street_name(row["address_raw"]), row["x"], row["y"])
                    for i, row in rows_by_id.items()
                ])
                covered_with_groups = with_companions(covered_ids, companions)
                dirty_ids = initial_dirty_ids(
                    changed_ids, set(rows_by_id), locatable_ids, covered_with_groups,
                    recompute_existing,
                )
                if connectors is not None and recompute_existing:
                    # Points couverts par des segments mais sans connecteur (table
                    # creee apres coup, ecriture en echec) : a relocaliser.
                    dirty_ids |= (covered_with_groups & set(rows_by_id)) - set(connectors[1])
                # Routes laissees incoherentes par un run precedent dont la
                # purge a ete suspendue (garde-fous) : a refaire elles aussi.
                stale_roads = inconsistent_roads(existing) if recompute_existing else set()
                for road_key in stale_roads:
                    dirty_ids |= road_ids.get(road_key, set())
                if stale_roads:
                    feedback.pushInfo(
                        f"Segments : {len(stale_roads)} route(s) aux segments "
                        "périmés (purge suspendue lors d'un run précédent) "
                        "recalculée(s)."
                    )
                acc = {
                    "locations": [], "extents": {}, "error": False, "attempted": 0,
                    "unavailable": set(), "lines": {}, "ids": set(),
                }

                def locate(ids):
                    batch_rows = [rows_by_id[i] for i in ids]
                    locs, exts, err, unavailable, lines = self._locate_points_on_road(
                        batch_rows, feedback, user_agent
                    )
                    acc["locations"].extend(locs)
                    for road_key, line in lines.items():
                        acc["lines"].setdefault(road_key, line)
                    for road_key, extent in exts.items():
                        acc["extents"].setdefault(road_key, extent)
                    acc["error"] = acc["error"] or err
                    acc["unavailable"] |= unavailable
                    acc["attempted"] += len(batch_rows)
                    acc["ids"].update(ids)
                    return {loc.intervention_id: loc.road_key for loc in locs}

                scope_roads, _located = expand_dirty_roads(
                    dirty_ids, set(rows_by_id), road_ids, id_roads, locate,
                    companions=companions,
                )
                locations = acc["locations"]
                road_extents = acc["extents"]
                road_lines = acc["lines"]
                had_connection_error = acc["error"]
                unavailable_ids = acc["unavailable"]
                n_attempted = acc["attempted"]
                n_roads_total = len(set(road_ids) | scope_roads)
                feedback.pushInfo(
                    f"Segments : incrémental — {len(dirty_ids)} point(s) modifié(s) "
                    f"ou non couvert(s), {len(scope_roads)} route(s) impactée(s) sur "
                    f"{n_roads_total}, {n_attempted} point(s) relocalisé(s)."
                )
                if not scope_roads:
                    feedback.pushInfo(
                        "Segments : aucune route impactée — rien à recalculer ni à écrire."
                    )
                    return

            # Ordre DETERMINISTE des points (ex-aequo de position_m) quel que soit
            # l'ordre des lots de localisation : meme resultat en complet et en
            # incremental.
            # Passe FINALE Overpass : tous les points localises via Overpass
            # pendant le run sont relocalises sur l'ensemble CUMULE des voies
            # extraites — sinon deux lots incrementaux ayant extrait des voies
            # differentes pourraient donner deux road_key a une meme rue.
            locations, road_extents, road_lines = self._final_overpass_pass(
                locations, road_extents, road_lines
            )
            if scope_roads is not None:
                scope_roads = scope_roads | {loc.road_key for loc in locations}
            locations = sorted(locations, key=lambda loc: loc.intervention_id or "")
            # Interventions distinctes au MEME point projete : un seul noeud
            # (plus petit id, pire categorie) -> pas de segment de longueur nulle.
            locations, merged_groups = merge_colocated(locations)
            if merged_groups:
                n_merged = sum(len(ids) for ids in merged_groups.values())
                feedback.pushInfo(
                    f"Segments : {n_merged} point(s) co-localisé(s) (même point projeté "
                    f"à {COLOCATED_TOLERANCE_M:g} m) fusionné(s) en "
                    f"{len(merged_groups)} nœud(s) — catégorie retenue = la pire du "
                    "groupe ; les points restent tous en base."
                )
            fresh = build_segment_halves(locations, road_extents, road_lines)
            ends = [h for h in fresh if h.point_b_intervention_id in (
                ROAD_START_SENTINEL, ROAD_END_SENTINEL)]
            n_stub = sum(1 for h in ends if h.length_m >= ROAD_END_STUB_M - 1e-6)
            if n_stub:
                feedback.pushInfo(
                    f"Segments : {n_stub} bout(s) de rue limité(s) à "
                    f"{ROAD_END_STUB_M:g} m (aucun point adjacent au-delà)."
                )
            if any(
                c.get("length_m") and c["length_m"] > ROAD_END_STUB_M + 0.01
                for k, c in existing.items()
                if k[1] in (ROAD_START_SENTINEL, ROAD_END_SENTINEL)
            ):
                feedback.pushWarning(
                    "Segments : des bouts de rue en base dépassent "
                    f"{ROAD_END_STUB_M:g} m (règle modifiée) — cochez « Reconstruire "
                    "tous les segments » une fois."
                )
            very_long = sorted(
                (h.length_m, h.point_a_intervention_id, h.point_b_intervention_id)
                for h in fresh if h.half == "a" and h.length_m > VERY_LONG_PAIR_M
                and h.point_b_intervention_id not in (ROAD_START_SENTINEL, ROAD_END_SENTINEL)
            )
            if very_long:
                feedback.pushWarning(
                    f"Segments : {len(very_long)} paire(s) de points consécutifs à plus de "
                    f"{VERY_LONG_PAIR_M:g} m (conservées) — "
                    + "; ".join(f"{a}–{b} : {d:.0f} m" for d, a, b in very_long[:20])
                )
            n_simplified = sum(1 for h in fresh if segment_geometry_anomalies(h))
            if n_simplified:
                feedback.pushInfo(
                    f"Segments : {n_simplified} demi-segment(s) simplifié(s) (décalage "
                    "aberrant : tracé sur l'axe non décalé)."
                )
            n_chord_roads = len({h.road_key for h in fresh if not h.axis_parts})
            if n_chord_roads:
                feedback.pushInfo(
                    f"Segments : {n_chord_roads} route(s) sans géométrie d'axe connue — "
                    "segments en cordes droites décalées (repli)."
                )
            n_zero = count_zero_length_pairs(fresh)
            if n_zero:
                feedback.pushInfo(
                    f"Segments : {n_zero} paire(s) d'interventions distinctes au MÊME "
                    "point projeté (même adresse géocodée) — segment de longueur "
                    "nulle conservé, dessiné sur l'axe sans décalage."
                )

            # Géométries décalées calculées UNE fois (comparaison, contrôle, écriture).
            geometries = {segment_key(h): segment_half_geometry(h) for h in fresh}
            plan = plan_segment_sync(
                fresh, existing, scope_roads, multi_column=multi_column,
                geometries=geometries,
            )
            to_delete = plan.to_delete
            if had_connection_error or partial_read:
                to_delete = []
                feedback.pushWarning(
                    "Localisation et/ou lecture des points partiellement en "
                    "echec — purge des segments obsoletes desactivee par "
                    "prudence pour ce run."
                )
            elif n_attempted and not locations and to_delete:
                # Aucun point localise alors qu'il y en avait : recalcul non
                # fiable (ex. ref.osm_roads videe/en cours de reimport, ou zone
                # non couverte). Sans ce garde, `fresh` vide ferait purger TOUS
                # les segments du perimetre -- meme politique que ci-dessus : ne
                # jamais purger sur un recalcul non fiable. Les segments
                # obsoletes seront purges au prochain run sain.
                to_delete = []
                feedback.pushWarning(
                    "Aucun point localise sur un axe de rue — purge des segments "
                    "existants desactivee par prudence pour ce run."
                )
            if to_delete and unavailable_ids:
                # Echec Overpass ISOLE : pas de purge sur les routes ou figuraient
                # les points non localises faute de reponse (les autres routes
                # sont purgees normalement).
                protected_roads = set()
                for intervention_id in unavailable_ids:
                    protected_roads |= id_roads.get(intervention_id, set())
                to_delete, n_blocked = filter_protected_deletions(
                    to_delete, existing, protected_roads
                )
                if n_blocked:
                    feedback.pushWarning(
                        f"Segments : purge suspendue pour {n_blocked} segment(s) de "
                        f"{len(protected_roads)} route(s) dont des points n'ont pu "
                        "être localisés (Overpass indisponible)."
                    )

            # Seuls les segments NOUVEAUX ou DIFFERENTS sont ecrits.
            writes = [(half, None) for half in plan.to_insert] + [
                (half, existing_fids[segment_key(half)]) for half in plan.to_update
            ]
            n_implausible = sum(
                1 for half, _fid in writes
                if not all(
                    lambert72_plausible(x, y)
                    for part in geometries[segment_key(half)] for x, y in part
                )
            )
            n_dropped_parts = 0
            if n_implausible:
                feedback.pushWarning(
                    f"Segments : {n_implausible} géométrie(s) à écrire hors de la plage "
                    f"Lambert 72 ({BELGIAN_LAMBERT_AUTHID}) — SCR suspect."
                )
            inserted = updated = failed = 0
            n_writes = max(len(writes), 1)
            for i, (half, existing_fid) in enumerate(writes):
                if feedback.isCanceled():
                    break
                feedback.setProgress(int(100 * i / n_writes))
                key = segment_key(half)
                key_label = f"({key[0]}, {key[1]}, {key[2]}, {key[3]})"
                is_update = existing_fid is not None
                parts, dropped = geometry_for_column(geometries[key], multi_column)
                n_dropped_parts += dropped
                if multi_column:
                    geom = QgsGeometry.fromMultiPolylineXY([
                        [QgsPointXY(x, y) for x, y in part] for part in parts
                    ])
                else:
                    geom = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in parts[0]])
                values = {
                    "point_a_intervention_id": half.point_a_intervention_id,
                    "point_b_intervention_id": half.point_b_intervention_id,
                    "half": half.half,
                    "side": half.side,
                    "depth_category": half.depth_category,
                    "is_long": half.is_long,
                    "length_m": half.length_m,
                    "road_key": half.road_key,
                }
                segments_layer.startEditing()
                ok = False
                try:
                    if is_update:
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
                    updated += 1 if is_update else 0
                    inserted += 0 if is_update else 1
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
                key_label = f"({key[0]}, {key[1]}, {key[2]}, {key[3]})"
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

            if n_dropped_parts:
                feedback.pushWarning(
                    f"Segments : colonne geom encore LineString — {n_dropped_parts} "
                    "partie(s) de géométrie non écrite(s) (seule la première partie "
                    "l'est) ; migration MultiLineString recommandée."
                )
            if not full and existing and looks_like_chord_segments(existing) and any(
                len(part) > 2 for h in fresh for part in h.axis_parts
            ):
                feedback.pushWarning(
                    "Segments : les segments existants sont des cordes droites (version "
                    "antérieure) — cochez « Reconstruire tous les segments » une fois "
                    "pour qu'ils suivent tous l'axe de rue."
                )
            feedback.pushInfo(
                f"Segments : {'reconstruction complète' if full else 'incrémental'} — "
                f"{inserted} inséré(s) / {updated} mis à jour / {deleted} supprimé(s) / "
                f"{plan.unchanged} inchangé(s) (non réécrits) ; {failed} échec(s) "
                f"d'écriture, {failed_delete} échec(s) de suppression."
            )

            # --- etape 2b : connecteurs point -> extremite du segment ---------
            if connectors is not None and not feedback.isCanceled():
                self._sync_connectors(
                    feedback, connectors,
                    points={r["intervention_id"]: (r["x"], r["y"], r["depth_category"])
                            for r in rows},
                    locations=locations, halves=fresh, merged_groups=merged_groups,
                    scope_ids=None if full else acc["ids"],
                    deletions_allowed=not (
                        had_connection_error or partial_read
                        or (n_attempted and not locations)
                    ),
                    protected_ids=unavailable_ids,
                )

        def _load_be_layers_in_project(self, context, feedback):
            """Ajoute au projet les couches points et segments de la base 'be', si absentes.

            Cible : ``context.project()``, repli sur ``QgsProject.instance()`` ;
            aucun projet -> journalisé, rien n'est chargé. Connexion 'be'
            introuvable -> rien (déjà signalé par l'upsert / la resynchro).

            Pour chacune des deux tables, la présence dans le projet est testée sur
            la SOURCE DE DONNÉES (schéma + table + serveur/base, cf.
            :func:`same_postgres_table`), jamais sur le nom de couche : une table
            déjà présente — même renommée, filtrée ou restylée par l'utilisateur —
            laisse le projet STRICTEMENT inchangé (ni doublon, ni restyle).

            URI construite explicitement : l'introspection de la connexion 'be'
            n'est pas fiable (cf. :meth:`_open_be_layer` : colonne géométrique,
            SRID et type forcés). La clé primaire détectée par le provider est de
            plus figée dans l'URI (``key=``), pour que la couche enregistrée dans
            le projet ne dépende plus de cette détection à la réouverture ; pas
            de clé primaire -> couche non ajoutée (édition/identification
            incohérentes).

            Chargement via le mécanisme Processing de fin d'exécution
            (``addLayerToLoadOnCompletion``) : le style ``.qml`` est appliqué avant
            remise au projet, puis ré-appliqué par post-traitement
            (:class:`_DepthLayerStyler` / :class:`_SegmentsLayerStyler`) une fois
            la couche ajoutée. Best-effort et NON bloquant.
            """
            project = context.project()
            if project is None:
                project = QgsProject.instance()
            if project is None:
                feedback.pushInfo(
                    "Couches de la base 'be' non ajoutées : aucun projet cible."
                )
                return
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            if md is None or md.findConnection(BE_CONNECTION_NAME) is None:
                return

            present = [
                _pg_identity(QgsDataSourceUri(layer.source()))
                for layer in project.mapLayers().values()
                if layer.providerType() == "postgres"
            ]
            # Ordre d'empilement : connecteurs SOUS les segments, SOUS les points
            # (cle de tri : plus grande = au-dessus).
            specs = [
                (BE_TABLE_SCHEMA, BE_TABLE_NAME, QgsWkbTypes.Point,
                 BE_POINTS_LAYER_NAME, _apply_depth_style, _DepthLayerStyler, 3),
                (SEGMENTS_TABLE_SCHEMA, SEGMENTS_TABLE_NAME,
                 QgsWkbTypes.MultiLineString if self._segments_is_multi(feedback)
                 else QgsWkbTypes.LineString,
                 BE_SEGMENTS_LAYER_NAME, _apply_segments_style, _SegmentsLayerStyler, 2),
            ]
            if self._read_connectors(feedback) is not None:
                specs.append(
                    (CONNECTORS_TABLE_SCHEMA, CONNECTORS_TABLE_NAME, QgsWkbTypes.LineString,
                     BE_CONNECTORS_LAYER_NAME, _apply_connectors_style,
                     _ConnectorsLayerStyler, 1)
                )
            # Références conservées sur l'instance : setPostProcessor ne prend
            # pas la propriété, le styler doit survivre jusqu'au chargement.
            self._be_layer_stylers = []
            for schema, table, wkb_type, layer_name, apply_style, styler_cls, sort_key in specs:
                layer = self._open_be_layer(
                    schema, table, BE_GEOM_COLUMN, wkb_type, feedback
                )
                if layer is None:
                    continue
                ds_uri = QgsDataSourceUri(layer.source())
                if any(same_postgres_table(_pg_identity(ds_uri), other) for other in present):
                    feedback.pushInfo(
                        f"Couche {schema}.{table} déjà présente dans le projet — "
                        "non ajoutée (projet inchangé)."
                    )
                    continue
                pk_names = [
                    layer.fields().at(idx).name() for idx in layer.primaryKeyAttributes()
                ]
                if not pk_names:
                    feedback.pushWarning(
                        f"Couche {schema}.{table} sans clé primaire détectable via "
                        "'be' — non ajoutée au projet."
                    )
                    continue
                if not ds_uri.keyColumn():
                    # Format attendu par le provider postgres (parseUriKey) :
                    # identifiants entre guillemets, séparés par des virgules.
                    ds_uri.setKeyColumn(",".join(
                        '"{}"'.format(name.replace('"', '""')) for name in pk_names
                    ))
                # URI explicite : colonne geometrique, type ET srid 31370 re-forces
                # (jamais deduits de l'introspection de la connexion 'be').
                ds_uri.setGeometryColumn(BE_GEOM_COLUMN)
                ds_uri.setSrid(BELGIAN_LAMBERT_AUTHID.split(":")[-1])
                ds_uri.setWkbType(wkb_type)
                layer = QgsVectorLayer(ds_uri.uri(False), layer_name, "postgres")
                if not layer.isValid() or not layer.isSpatial():
                    feedback.pushWarning(
                        f"Couche {schema}.{table} invalide une fois la clé "
                        "primaire figée — non ajoutée au projet."
                    )
                    continue
                # SCR force explicitement AVANT la remise au projet (puis
                # re-verifie par le post-traitement une fois la couche chargee).
                _force_target_crs(layer, feedback, layer_name)
                layer.setCrs(QgsCoordinateReferenceSystem(BELGIAN_LAMBERT_AUTHID))
                feedback.pushInfo(
                    f"Couche « {layer_name} » : SCR {layer.crs().authid() or BELGIAN_LAMBERT_AUTHID} "
                    "(forcé)."
                )
                apply_style(layer, feedback)
                context.temporaryLayerStore().addMapLayer(layer)
                details = QgsProcessingContext.LayerDetails(layer_name, project, "")
                if hasattr(details, "layerSortKey"):  # QGIS >= 3.32
                    details.layerSortKey = sort_key
                styler = styler_cls()
                self._be_layer_stylers.append(styler)
                details.setPostProcessor(styler)
                context.addLayerToLoadOnCompletion(layer.id(), details)
                feedback.pushInfo(
                    f"Couche {schema}.{table} ajoutée au projet en fin "
                    f"d'exécution : « {layer_name} »."
                )
