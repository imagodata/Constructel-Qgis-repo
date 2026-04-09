-- ============================================================================
-- constructel_bridge - Grants specifiques pour le plugin QGIS Constructel Bridge
-- ============================================================================
-- A executer avec un role admin (ftth_admin ou postgres) si les grants
-- du schema ref ne sont pas suffisants.
-- En principe, 080_security_hardening.sql donne deja INSERT/UPDATE sur ref.*
-- a ftth_editor. Ce fichier sert de reference et de secours.
-- ============================================================================

-- ftth_editor doit pouvoir s'enregistrer dans ref.users
GRANT SELECT, INSERT, UPDATE ON ref.users TO ftth_editor;

-- Sequences pour les colonnes serial (ref.users utilise UUID, pas de sequence)
-- Rien a ajouter.

-- Lecture audit.status_history pour consultation (deja OK via 080)
-- GRANT SELECT ON audit.status_history TO ftth_editor;

\echo '  constructel_bridge grants OK'
