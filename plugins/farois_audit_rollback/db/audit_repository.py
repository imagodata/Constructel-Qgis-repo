"""Safe, parameterized access to the Farois audit/undo PostgreSQL contract."""

import re
from uuid import UUID
from .errors import InvalidIdentifierError, UndoEngineUnavailable, UndoRejected

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_SCHEMAS = frozenset({"wyre", "orange", "proximus", "audit"})


class IdentifierPolicy:
    def __init__(
        self, allowed_schemas=DEFAULT_SCHEMAS, allowed_tables=None, allowed_columns=None
    ):
        self.allowed_schemas = {str(x).lower() for x in allowed_schemas}
        self.allowed_tables = {str(x).lower() for x in (allowed_tables or ())}
        self.allowed_columns = {str(x).lower() for x in (allowed_columns or ())}

    def validate(self, schema_name, table_name, column_name=None):
        values = (
            (schema_name, table_name)
            if column_name is None
            else (schema_name, table_name, column_name)
        )
        if any(not isinstance(v, str) or not IDENTIFIER.fullmatch(v) for v in values):
            raise InvalidIdentifierError("Identifiant SQL invalide")
        if schema_name.lower() not in self.allowed_schemas:
            raise InvalidIdentifierError("Schéma hors périmètre autorisé")
        if self.allowed_tables and table_name.lower() not in self.allowed_tables:
            raise InvalidIdentifierError("Table hors allowlist")
        if (
            column_name
            and self.allowed_columns
            and column_name.lower() not in self.allowed_columns
        ):
            raise InvalidIdentifierError("Colonne hors allowlist")


HISTORY_SQL = (
    "SELECT * FROM audit.v_undo_candidates "
    "WHERE schema_name = %s AND table_name = %s AND record_id = %s"
)


class AuditRepository:
    def __init__(self, connection, policy=None):
        self.connection, self.policy = connection, policy or IdentifierPolicy()
        self.engine_available = None
        self.engine_contract = None

    def close(self):
        self.connection.close()

    def refresh_capabilities(self):
        cur = self._cursor()
        try:
            cur.execute(
                """
                SELECT to_regclass('audit.v_undo_candidates') IS NOT NULL
                   AND to_regclass('audit.undo_log') IS NOT NULL
                   AND has_schema_privilege(current_user, 'audit', 'USAGE')
                   AND has_table_privilege(current_user, to_regclass('audit.v_undo_candidates'), 'SELECT')
                   AND to_regprocedure('audit.revert_transaction(uuid,text)') IS NOT NULL
                   AND has_function_privilege(current_user,
                         to_regprocedure('audit.revert_change(uuid,text)'), 'EXECUTE')
                   AND has_function_privilege(current_user,
                         to_regprocedure('audit.revert_transaction(uuid,text)'), 'EXECUTE'),
                   CASE
                     WHEN p.prorettype = 'jsonb'::regtype AND p.proargnames[2] = 'p_mode'
                      AND t.prorettype = 'jsonb'::regtype AND t.proargnames[2] = 'p_mode'
                      AND to_regprocedure('audit.fn_undo_caller()') IS NOT NULL
                      AND to_regprocedure('audit.undo_window()') IS NOT NULL
                      AND has_function_privilege(current_user, to_regprocedure('audit.fn_undo_caller()'), 'EXECUTE')
                      AND has_function_privilege(current_user, to_regprocedure('audit.undo_window()'), 'EXECUTE')
                      THEN 'legacy_field'
                     WHEN p.prorettype = 'uuid'::regtype AND t.prorettype = 'uuid'::regtype
                      AND to_regprocedure('audit.undo_candidates(name,name,uuid,integer)') IS NOT NULL
                      AND has_function_privilege(current_user,
                            to_regprocedure('audit.undo_candidates(name,name,uuid,integer)'), 'EXECUTE')
                      THEN 'reason'
                     ELSE 'unsupported'
                   END
                  FROM (SELECT 1) probe
                  LEFT JOIN pg_catalog.pg_proc p
                    ON p.oid = to_regprocedure('audit.revert_change(uuid,text)')
                  LEFT JOIN pg_catalog.pg_proc t
                    ON t.oid = to_regprocedure('audit.revert_transaction(uuid,text)')
                """,
                (),
            )
            row = cur.fetchone()
            self.engine_contract = row[1] if row and len(row) > 1 else "unsupported"
            self.engine_available = bool(
                row and row[0] and self.engine_contract != "unsupported"
            )
            return self.engine_available
        finally:
            cur.close()

    def _cursor(self):
        return self.connection.cursor()

    def _history_view(self):
        if self.engine_available is None:
            self.refresh_capabilities()
        if not self.engine_available:
            return "audit.v_operator_changes_scoped"
        if self.engine_contract != "legacy_field":
            return "audit.v_undo_candidates"
        # All business data comes from the existing scoped view, including rows
        # not eligible for undo. Eligibility is evaluated with the real server
        # identity; neither a QGIS username nor an actor label grants authority.
        return """(
            SELECT s.*, u.transaction_id, COALESCE(u.already_undone, FALSE) AS already_undone,
                   u.change_id IS NOT NULL AS in_engine,
                   GREATEST((SELECT count(*) FROM audit.v_undo_candidates sibling
                              WHERE sibling.transaction_id = u.transaction_id
                                AND NOT sibling.already_undone), 1) - 1 AS cascade_count,
                   eligibility.reason = '' AS can_undo,
                   eligibility.reason AS refusal_reason
              FROM audit.v_operator_changes_scoped s
              LEFT JOIN audit.v_undo_candidates u ON u.change_id = s.change_id
              CROSS JOIN audit.fn_undo_caller() caller
              CROSS JOIN LATERAL (
                SELECT CASE
                  WHEN u.change_id IS NULL THEN 'Changement hors périmètre du moteur'
                  WHEN u.already_undone THEN 'Modification déjà annulée'
                  WHEN NOT caller.is_admin AND caller.caller_id IS NULL
                    THEN 'Identité PostgreSQL non reconnue pour annuler'
                  WHEN NOT caller.is_admin AND u.author_id IS NULL THEN 'Auteur non identifié'
                  WHEN NOT caller.is_admin AND caller.caller_id IS DISTINCT FROM u.author_id
                    THEN 'Modification effectuée par un autre utilisateur'
                  WHEN NOT caller.is_admin AND u.changed_at < clock_timestamp() - audit.undo_window()
                    THEN 'Modification hors délai'
                  WHEN u.operation <> 'UPDATE' THEN 'Cette version annule uniquement les modifications UPDATE'
                  ELSE '' END AS reason
              ) eligibility
        ) history"""

    def _read_history(self, sql, params):
        cur = self._cursor()
        try:
            cur.execute(sql, params)
            rows = cur.fetchall()
            names = [item[0] for item in cur.description] if cur.description else []
            return [
                dict(zip(names, row)) if not isinstance(row, dict) else row
                for row in rows
            ]
        finally:
            cur.close()

    @staticmethod
    def _limit(limit):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("La limite doit être un entier entre 1 et 1000.")
        return limit

    def layer_history(self, schema_name, table_name, limit=200):
        self.policy.validate(schema_name, table_name)
        if self.engine_available is None:
            self.refresh_capabilities()
        if self.engine_available and self.engine_contract == "reason":
            return self._read_history(
                "SELECT * FROM audit.undo_candidates(%s::name, %s::name, NULL::uuid, %s) "
                "ORDER BY changed_at DESC, change_id DESC",
                (schema_name, table_name, self._limit(limit)),
            )
        return self._read_history(
            "SELECT * FROM "
            + self._history_view()
            + " WHERE schema_name = %s AND table_name = %s ORDER BY changed_at DESC LIMIT %s",
            (schema_name, table_name, self._limit(limit)),
        )

    def visible_history(self, limit=200):
        # This is still the database-scoped endpoint. Never read audit.changes.
        if self.engine_available is None:
            self.refresh_capabilities()
        if self.engine_available and self.engine_contract == "reason":
            return self._read_history(
                "SELECT * FROM audit.undo_candidates(NULL::name, NULL::name, NULL::uuid, %s) "
                "ORDER BY changed_at DESC, change_id DESC",
                (self._limit(limit),),
            )
        return self._read_history(
            "SELECT * FROM "
            + self._history_view()
            + " ORDER BY changed_at DESC LIMIT %s",
            (self._limit(limit),),
        )

    def history(
        self,
        schema_name,
        table_name,
        record_id,
        *,
        user="",
        provenance="",
        column="",
        cancelable_only=False,
    ):
        self.policy.validate(schema_name, table_name)
        if self.engine_available is None:
            self.refresh_capabilities()
        if self.engine_available and self.engine_contract == "reason":
            return self._read_history(
                "SELECT * FROM audit.undo_candidates(%s::name, %s::name, %s::uuid, %s) "
                "ORDER BY changed_at DESC, change_id DESC",
                (schema_name, table_name, record_id, 1000),
            )
        sql = (
            "SELECT * FROM "
            + self._history_view()
            + " WHERE schema_name = %s AND table_name = %s AND record_id = %s"
        )
        params = (schema_name, table_name, record_id)
        cur = self._cursor()
        try:
            cur.execute(sql + " ORDER BY changed_at DESC", params)
            rows = cur.fetchall()
            names = [item[0] for item in cur.description] if cur.description else []
            return [
                dict(zip(names, row)) if not isinstance(row, dict) else row
                for row in rows
            ]
        except Exception as exc:
            if getattr(exc, "pgcode", None) == "42P01" and self.engine_available:
                raise UndoEngineUnavailable(
                    "Le moteur d’annulation Farois est indisponible pour cette connexion (installation, contrat ou droits PostgreSQL)."
                ) from exc
            raise
        finally:
            cur.close()

    def _call(self, function, change_id, reason):
        if not reason or not str(reason).strip():
            raise UndoRejected("Un motif est obligatoire.")
        if self.engine_available is None:
            self.refresh_capabilities()
        if not self.engine_available:
            raise UndoEngineUnavailable(
                "Le moteur d’annulation Farois est indisponible pour cette connexion (installation, contrat ou droits PostgreSQL)."
            )
        # Reads use autocommit. A legacy FIELD revert may write some fields
        # before reporting conflicts, so its result must be checked in a real
        # transaction BEFORE committing any change.
        previous_autocommit = getattr(self.connection, "autocommit", None)
        if previous_autocommit is not None:
            self.connection.autocommit = False
        cur = None
        try:
            cur = self._cursor()
            if self.engine_contract == "legacy_field":
                cur.execute(
                    "SELECT set_config('app.undo_reason', %s, true)", (reason.strip(),)
                )
            argument = (
                "FIELD" if self.engine_contract == "legacy_field" else reason.strip()
            )
            cur.execute("SELECT " + function + "(%s, %s)", (change_id, argument))
            row = cur.fetchone()
            result = row[0] if row else None
            if result is None:
                raise UndoRejected("La base n'a pas confirmé l'annulation.")
            if self.engine_contract == "legacy_field" and not isinstance(result, dict):
                raise UndoRejected(
                    "Le moteur n'a pas retourné de rapport d'annulation valide."
                )
            if self.engine_contract == "reason":
                try:
                    UUID(str(result))
                except (ValueError, TypeError, AttributeError):
                    raise UndoRejected(
                        "La base n'a pas retourné d'identifiant d'annulation valide."
                    ) from None
            self._validate_result(result)
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise
        finally:
            if cur is not None:
                cur.close()
            if previous_autocommit is not None:
                self.connection.autocommit = previous_autocommit

    @classmethod
    def _validate_result(cls, result):
        if not isinstance(result, dict):
            return
        if result.get("success") is False or result.get("conflicts"):
            raise UndoRejected("Conflit détecté : aucune modification n'a été annulée.")
        changes = result.get("changes")
        if changes is not None:
            if not isinstance(changes, list) or not changes:
                raise UndoRejected(
                    "Cette transaction ne contient plus de modification annulable."
                )
            for change in changes:
                if not isinstance(change, dict):
                    raise UndoRejected(
                        "Le moteur n'a pas retourné de rapport d'annulation valide."
                    )
                cls._validate_result(change)
        elif not (
            result.get("reverted") or result.get("restored") or result.get("deleted")
        ):
            raise UndoRejected("La base n'a effectué aucune annulation.")

    def revert_change(self, change_id, reason):
        return self._call("audit.revert_change", change_id, reason)

    def revert_transaction(self, transaction_id, reason):
        return self._call("audit.revert_transaction", transaction_id, reason)
