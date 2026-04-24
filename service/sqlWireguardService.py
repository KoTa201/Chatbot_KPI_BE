"""
SQLWireguard Service - layer keamanan stateless & deterministic.
Memvalidasi setiap SQL yang digenerate LLM sebelum dieksekusi ke database.
Mengimplementasikan Rules W-01 s/d W-08 dari PRD Section 8.2.
"""

import re

from config import get_settings
from schema.wireguardSchema import ValidationResult

settings = get_settings()


class SQLWireguardService:
    """
    Memvalidasi dan meng-sanitize SQL yang digenerate oleh LLM.
    Stateless - tidak bergantung pada LLM, tidak bisa di-bypass via prompt injection.
    """

    def __init__(self):

        # Whitelist and blacklist rules
        self.allowed_tables = frozenset(
            {
                "kpi_master_records",
                "kpi_tracker_records",
                "kpi_groups",
                "users",
                # Backward compatibility
                "kpi_master",
                "kpi_tracker",
                "v_kpi_lengkap",
            }
        )
        self.forbidden_keywords = frozenset(
            {
                "INSERT",
                "UPDATE",
                "DELETE",
                "DROP",
                "ALTER",
                "CREATE",
                "TRUNCATE",
                "EXEC",
                "EXECUTE",
                "CALL",
                "MERGE",
                "REPLACE",
                "GRANT",
                "REVOKE",
                "COMMIT",
                "ROLLBACK",
                "SAVEPOINT",
            }
        )
        self.forbidden_keyword_phrases = (
            r"INTO\s+OUTFILE",
            r"LOAD\s+DATA",
            r"COPY\s+TO",
            r"COPY\s+FROM",
        )
        self.forbidden_columns = frozenset(
            {
                "password",
                "password_hash",
                "token",
                "refresh_token",
                "secret",
                "api_key",
                "otp_code",
                "reset_token",
            }
        )
        self.injection_patterns = (
            (re.compile(r"--"), "Comment injection (--)"),
            (re.compile(r"/\*"), "Block comment (/*)"),
            (re.compile(r";\s*\w"), "Stacked queries (;)"),
            (re.compile(r"UNION\s+(ALL\s+)?SELECT",
             re.IGNORECASE), "UNION-based injection"),
            (re.compile(r"\bOR\b\s+['\"0-9]\s*=\s*['\"0-9]",
             re.IGNORECASE), "OR 1=1 pattern"),
            (re.compile(r"xp_", re.IGNORECASE), "Extended procedure (xp_)"),
            (re.compile(r"INFORMATION_SCHEMA", re.IGNORECASE), "Schema enumeration"),
            (re.compile(r"PG_SLEEP", re.IGNORECASE),
             "Time-based injection (pg_sleep)"),
            (re.compile(r"WAITFOR\s+DELAY", re.IGNORECASE),
             "Time-based injection (waitfor)"),
        )

        # Compiled regex reused across methods
        self.table_pattern = re.compile(
            r"(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE
        )
        self.limit_pattern = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)
        self.where_pattern = re.compile(r"\bWHERE\b", re.IGNORECASE)
        self.owner_filter_pattern = re.compile(
            r"karyawan_id\s*=\s*['\"]?[0-9a-f\-]+['\"]?", re.IGNORECASE
        )
        self.insertion_pattern = re.compile(
            r"\b(GROUP\s+BY|ORDER\s+BY|LIMIT|;|$)", re.IGNORECASE
        )

    def validate(self, sql: str, user_id: str, user_role: str) -> "ValidationResult":
        """
        Jalankan semua validasi secara berurutan.
        Mengembalikan ValidationResult dengan sanitized_sql jika lolos.
        """
        normalized_sql = sql.strip()

        checks = (
            self._check_select_only,
            self._check_forbidden_keywords,
            self._check_table_whitelist,
            self._check_column_blacklist,
            self._check_injection_patterns,
            self._check_subquery_depth,
            self._check_structural_integrity,
        )
        for check in checks:
            result = check(normalized_sql)
            if not result.is_valid:
                return result

        sanitized_sql = self._sanitize_sql(normalized_sql, user_id, user_role)
        return ValidationResult(is_valid=True, reason=None, sanitized_sql=sanitized_sql)

    def _sanitize_sql(self, sql: str, user_id: str, user_role: str) -> str:
        sanitized = self._enforce_limit(sql)
        return self._enforce_rls(sanitized, user_id, user_role)

    # -- Rule W-01 -------------------------------------------------------------

    @staticmethod
    def _check_select_only(sql: str) -> "ValidationResult":
        if not sql.upper().lstrip().startswith("SELECT"):
            return ValidationResult(
                is_valid=False,
                reason="W-01: Hanya query SELECT yang diizinkan.",
                sanitized_sql=None,
            )
        return ValidationResult(is_valid=True, reason=None, sanitized_sql=sql)

    # -- Rule W-02 -------------------------------------------------------------

    def _check_forbidden_keywords(self, sql: str) -> "ValidationResult":
        tokens = re.findall(r"\b\w+\b", sql.upper())
        for token in tokens:
            if token in self.forbidden_keywords:
                return ValidationResult(
                    is_valid=False,
                    reason=f"W-02: Keyword terlarang ditemukan: '{token}'.",
                    sanitized_sql=None,
                )

        for pattern in self.forbidden_keyword_phrases:
            if re.search(pattern, sql, re.IGNORECASE):
                return ValidationResult(
                    is_valid=False,
                    reason=f"W-02: Phrase terlarang ditemukan: '{pattern}'.",
                    sanitized_sql=None,
                )

        return ValidationResult(is_valid=True, reason=None, sanitized_sql=sql)

    # -- Rule W-03 -------------------------------------------------------------

    def _check_table_whitelist(self, sql: str) -> "ValidationResult":
        tables_in_query = set(self.table_pattern.findall(sql))

        for table in tables_in_query:
            if table.lower() not in self.allowed_tables:
                return ValidationResult(
                    is_valid=False,
                    reason=f"W-03: Tabel '{table}' tidak diizinkan untuk diakses.",
                    sanitized_sql=None,
                )

        return ValidationResult(is_valid=True, reason=None, sanitized_sql=sql)

    # -- Rule W-04 -------------------------------------------------------------

    def _check_column_blacklist(self, sql: str) -> "ValidationResult":
        sql_lower = sql.lower()
        for col in self.forbidden_columns:
            if re.search(rf"\b{re.escape(col)}\b", sql_lower):
                return ValidationResult(
                    is_valid=False,
                    reason=f"W-04: Kolom sensitif '{col}' tidak dapat diakses.",
                    sanitized_sql=None,
                )
        return ValidationResult(is_valid=True, reason=None, sanitized_sql=sql)

    # -- Rule W-05 -------------------------------------------------------------

    def _check_injection_patterns(self, sql: str) -> "ValidationResult":
        for pattern, description in self.injection_patterns:
            if pattern.search(sql):
                return ValidationResult(
                    is_valid=False,
                    reason=f"W-05: Pola SQL injection terdeteksi: {description}.",
                    sanitized_sql=None,
                )
        return ValidationResult(is_valid=True, reason=None, sanitized_sql=sql)

    # -- Rule W-06 -------------------------------------------------------------

    def _enforce_rls(self, sql: str, user_id: str, user_role: str) -> str:
        if str(user_role).strip().lower() != "karyawan":
            return sql

        if self._has_owner_filter(sql):
            return sql

        if self.where_pattern.search(sql):
            return self._inject_owner_filter_existing_where(sql, user_id)

        return self._inject_owner_filter_no_where(sql, user_id)

    def _has_owner_filter(self, sql: str) -> bool:
        return bool(self.owner_filter_pattern.search(sql))

    def _inject_owner_filter_existing_where(self, sql: str, user_id: str) -> str:
        return self.where_pattern.sub(
            f"WHERE karyawan_id = '{user_id}' AND", sql, count=1
        )

    def _inject_owner_filter_no_where(self, sql: str, user_id: str) -> str:
        match = self.insertion_pattern.search(sql)
        if not match:
            return sql.rstrip("; \n") + f" WHERE karyawan_id = '{user_id}'"

        insert_pos = match.start()
        return (
            sql[:insert_pos].rstrip()
            + f" WHERE karyawan_id = '{user_id}' "
            + sql[insert_pos:]
        )

    # -- Rule W-07 -------------------------------------------------------------

    def _enforce_limit(self, sql: str) -> str:
        max_limit = settings.SQL_MAX_LIMIT
        match = self.limit_pattern.search(sql)

        if not match:
            return sql.rstrip("; \n") + f" LIMIT {max_limit}"

        current_limit = int(match.group(1))
        if current_limit > max_limit:
            return self.limit_pattern.sub(f"LIMIT {max_limit}", sql)

        return sql

    # -- Rule W-08 -------------------------------------------------------------

    def _check_subquery_depth(self, sql: str) -> "ValidationResult":
        depth = self._count_subquery_depth(sql)
        max_depth = settings.SQL_MAX_SUBQUERY_DEPTH

        if depth > max_depth:
            return ValidationResult(
                is_valid=False,
                reason=f"W-08: Kedalaman subquery ({depth}) melebihi batas maksimum ({max_depth}).",
                sanitized_sql=None,
            )
        return ValidationResult(is_valid=True, reason=None, sanitized_sql=sql)

    # -- Rule W-09 -------------------------------------------------------------

    def _check_structural_integrity(self, sql: str) -> "ValidationResult":
        balanced, reason = self._has_balanced_brackets_and_quotes(sql)
        if not balanced:
            return ValidationResult(
                is_valid=False,
                reason=f"W-09: Struktur SQL tidak lengkap ({reason}).",
                sanitized_sql=None,
            )
        return ValidationResult(is_valid=True, reason=None, sanitized_sql=sql)

    @staticmethod
    def _count_subquery_depth(sql: str) -> int:
        max_depth = 0
        current_depth = 0
        for char in sql:
            if char == "(":
                current_depth += 1
                max_depth = max(max_depth, current_depth)
            elif char == ")":
                current_depth -= 1
        return max_depth

    @staticmethod
    def _has_balanced_brackets_and_quotes(sql: str) -> tuple[bool, str | None]:
        in_single_quote = False
        in_double_quote = False
        depth = 0
        i = 0
        length = len(sql)

        while i < length:
            ch = sql[i]

            if in_single_quote:
                if ch == "'":
                    # Escaped single quote in SQL literal: ''
                    if i + 1 < length and sql[i + 1] == "'":
                        i += 2
                        continue
                    in_single_quote = False
                i += 1
                continue

            if in_double_quote:
                if ch == '"':
                    in_double_quote = False
                i += 1
                continue

            if ch == "'":
                in_single_quote = True
            elif ch == '"':
                in_double_quote = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    return False, "jumlah tanda kurung tidak seimbang"

            i += 1

        if in_single_quote:
            return False, "string literal belum ditutup"
        if in_double_quote:
            return False, "identifier quote belum ditutup"
        if depth != 0:
            return False, "jumlah tanda kurung tidak seimbang"

        return True, None
