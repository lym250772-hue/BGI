"""Apache Doris OLAP store for analytical queries.

Doris serves as the analytical engine for dashboard aggregations,
time-series trends, and multi-dimensional risk analysis.
It connects via MySQL protocol (FE port 9030).

Table: bagi_olap.intel_analysis_wide — one row per analyzed intel,
denormalized for fast aggregation queries without joins.
"""

import pymysql
import time
import threading
from contextlib import contextmanager
from loguru import logger
from config.settings import settings


class DorisStore:
    """OLAP analytical store backed by Apache Doris."""

    def __init__(self):
        self._local = threading.local()
        self._disabled_until = 0.0

    @property
    def conn(self):
        if not settings.doris_enabled:
            raise RuntimeError("Doris disabled; set BGI_DORIS_ENABLED=true to enable OLAP")
        if time.time() < self._disabled_until:
            raise RuntimeError("Doris temporarily unavailable")
        conn = getattr(self._local, "conn", None)
        if conn is not None and conn.open:
            try:
                conn.ping()
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None
                self._local.conn = None
        if conn is None or not conn.open:
            try:
                conn = pymysql.connect(
                    host=settings.doris_host,
                    port=settings.doris_port,
                    user=settings.doris_user,
                    password=settings.doris_password,
                    charset="utf8mb4",
                    connect_timeout=1,
                    read_timeout=1,
                    write_timeout=2,
                    autocommit=False,
                    cursorclass=pymysql.cursors.DictCursor,
                )
                self._local.conn = conn
            except Exception:
                self._local.conn = None
                self._disabled_until = time.time() + 30
                raise
        return conn

    @contextmanager
    def cursor(self):
        c = self.conn.cursor()
        try:
            yield c
            self.conn.commit()
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                self._local.conn = None
                self._disabled_until = time.time() + 30
            raise
        finally:
            c.close()

    # ── Init ───────────────────────────────────────────────────────────

    def init_tables(self):
        """Register BE node, create database and tables. Idempotent."""
        import time

        # Register BE (idempotent — Doris ignores duplicates)
        try:
            with self.cursor() as c:
                c.execute("ALTER SYSTEM ADD BACKEND 'bagi-doris-be:9050'")
            logger.info("Doris BE registered")
        except Exception as exc:
            logger.warning(f"Doris BE registration (may already exist): {exc}")

        # Wait for BE to become alive before creating tables
        for _ in range(30):
            with self.cursor() as c:
                c.execute("SHOW BACKENDS")
                backends = c.fetchall()
                alive = any(
                    b.get("Alive", "").lower() == "true" for b in backends
                )
                if alive:
                    break
            time.sleep(1)
        else:
            logger.warning("BE did not become alive within 30s, proceeding anyway")

        with self.cursor() as c:
            c.execute(
                f"CREATE DATABASE IF NOT EXISTS {settings.doris_database}"
            )
            logger.info(f"Doris database '{settings.doris_database}' ready")

        ddl = f"""
        CREATE TABLE IF NOT EXISTS {settings.doris_database}.intel_analysis_wide (
            raw_id BIGINT,
            platform VARCHAR(32),
            collect_time DATETIME,
            risk_label VARCHAR(64),
            risk_sub_label VARCHAR(128),
            risk_score DECIMAL(5,4),
            risk_level VARCHAR(16),
            classification_method VARCHAR(64),
            entity_count INT,
            evidence_count INT,
            slang_count INT,
            contact_count INT,
            url_count INT,
            tool_count INT,
            is_gang_related TINYINT,
            disposal_advice_count INT,
            content_snippet VARCHAR(200),
            source_url VARCHAR(1024),
            author_id VARCHAR(128),
            source_channel VARCHAR(128),
            clean_text VARCHAR(500),
            entities_json VARCHAR(2000),
            slang_terms_json VARCHAR(1000),
            evidence_spans_json VARCHAR(2000),
            agent_summary VARCHAR(500),
            disposal_advice VARCHAR(500),
            graph_summary_json VARCHAR(1000)
        )
        DUPLICATE KEY(raw_id)
        DISTRIBUTED BY HASH(raw_id) BUCKETS 4
        PROPERTIES (
            "replication_num" = "1"
        )
        """
        with self.cursor() as c:
            c.execute(ddl)
            logger.info("Doris table intel_analysis_wide ready")
        self._ensure_wide_columns()

    def _ensure_wide_columns(self):
        """Best-effort migration for existing local Doris wide tables."""
        db = settings.doris_database
        migrations = [
            "ALTER TABLE {db}.intel_analysis_wide ADD COLUMN source_url VARCHAR(1024)",
            "ALTER TABLE {db}.intel_analysis_wide ADD COLUMN author_id VARCHAR(128)",
            "ALTER TABLE {db}.intel_analysis_wide ADD COLUMN source_channel VARCHAR(128)",
            "ALTER TABLE {db}.intel_analysis_wide ADD COLUMN clean_text VARCHAR(500)",
            "ALTER TABLE {db}.intel_analysis_wide ADD COLUMN entities_json VARCHAR(2000)",
            "ALTER TABLE {db}.intel_analysis_wide ADD COLUMN slang_terms_json VARCHAR(1000)",
            "ALTER TABLE {db}.intel_analysis_wide ADD COLUMN evidence_spans_json VARCHAR(2000)",
            "ALTER TABLE {db}.intel_analysis_wide ADD COLUMN agent_summary VARCHAR(500)",
            "ALTER TABLE {db}.intel_analysis_wide ADD COLUMN disposal_advice VARCHAR(500)",
            "ALTER TABLE {db}.intel_analysis_wide ADD COLUMN graph_summary_json VARCHAR(1000)",
        ]
        with self.cursor() as c:
            for sql in migrations:
                try:
                    c.execute(sql.format(db=db))
                except Exception:
                    pass

    # ── Insert ─────────────────────────────────────────────────────────

    def insert_analysis(self, record: dict):
        """Insert (or replace) one analysis result into the OLAP wide table.

        Uses DELETE + INSERT to simulate UNIQUE KEY behavior on raw_id,
        preventing data inflation on re-analysis.
        """
        raw_id = record.get("raw_id", 0)
        entities = record.get("entities", [])
        entity_types = {}
        for e in entities:
            et = e.get("entity_type", "")
            et_s = et.value if hasattr(et, "value") else str(et)
            entity_types[et_s] = entity_types.get(et_s, 0) + 1

        # Delete existing record if present (re-analysis dedup)
        with self.cursor() as c:
            c.execute(
                f"DELETE FROM {settings.doris_database}.intel_analysis_wide WHERE raw_id=%s",
                (raw_id,),
            )

        import json as _json

        evidence_spans = record.get("evidence_spans", [])
        slang_terms = record.get("slang_terms", [])
        disposal_advice = record.get("disposal_advice", [])
        graph_result = record.get("graph_result", {})

        sql = f"""
        INSERT INTO {settings.doris_database}.intel_analysis_wide
            (raw_id, platform, collect_time, risk_label, risk_sub_label,
             risk_score, risk_level, classification_method,
             entity_count, evidence_count, slang_count,
             contact_count, url_count, tool_count,
             is_gang_related, disposal_advice_count, content_snippet,
             source_url, author_id, source_channel, clean_text,
             entities_json, slang_terms_json, evidence_spans_json,
             agent_summary, disposal_advice, graph_summary_json)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
             %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        with self.cursor() as c:
            c.execute(sql, (
                record.get("raw_id", 0),
                record.get("platform", ""),
                record.get("collect_time"),
                record.get("risk_label", ""),
                record.get("risk_sub_label", ""),
                float(record.get("risk_score", 0)),
                record.get("risk_level", "normal"),
                record.get("classification_method", ""),
                len(entities),
                len(evidence_spans),
                entity_types.get("slang", 0),
                entity_types.get("phone", 0) + entity_types.get("wechat", 0) + entity_types.get("qq", 0),
                entity_types.get("url", 0) + entity_types.get("domain", 0),
                entity_types.get("tool", 0),
                1 if record.get("is_gang_related") else 0,
                len(disposal_advice),
                (record.get("clean_text", "") or "")[:200],
                (record.get("source_url", "") or "")[:1024],
                (record.get("author_id", "") or "")[:128],
                (record.get("source_channel", "") or "")[:128],
                (record.get("clean_text", "") or "")[:500],
                _json.dumps([{"type": e.get("entity_type", ""), "value": e.get("entity_value", "")}
                             for e in entities[:20]], ensure_ascii=False)[:2000],
                _json.dumps([{"term": s.get("term", ""), "meaning": s.get("meaning", "")}
                             for s in (slang_terms if isinstance(slang_terms, list) else [])[:10]],
                            ensure_ascii=False)[:1000],
                _json.dumps(evidence_spans[:10], ensure_ascii=False)[:2000],
                (record.get("agent_summary", "") or "")[:500],
                _json.dumps(disposal_advice[:5], ensure_ascii=False)[:500],
                _json.dumps(graph_result, ensure_ascii=False)[:1000],
            ))
        logger.debug(f"Doris insert raw_id={record.get('raw_id')}")

    # ── Dashboard Queries ──────────────────────────────────────────────

    def dashboard_stats(self) -> dict:
        """Aggregated stats for the main dashboard."""
        db = settings.doris_database
        with self.cursor() as c:
            c.execute(f"SELECT COUNT(*) as cnt FROM {db}.intel_analysis_wide")
            total = c.fetchone()["cnt"]

            c.execute(f"""
                SELECT COUNT(*) as cnt FROM {db}.intel_analysis_wide
                WHERE DATE(collect_time) = CURDATE()
            """)
            today = c.fetchone()["cnt"]

            c.execute(f"""
                SELECT COUNT(*) as cnt FROM {db}.intel_analysis_wide
                WHERE risk_level IN ('high', 'critical')
            """)
            high_risk = c.fetchone()["cnt"]

            c.execute(f"""
                SELECT risk_label, COUNT(*) as cnt
                FROM {db}.intel_analysis_wide
                GROUP BY risk_label
            """)
            label_dist = {r["risk_label"]: r["cnt"] for r in c.fetchall()}

            c.execute(f"""
                SELECT SUM(entity_count) as cnt FROM {db}.intel_analysis_wide
            """)
            entity_total = c.fetchone()["cnt"] or 0

            c.execute(f"""
                SELECT raw_id, risk_label, risk_level, risk_score, platform, collect_time,
                       entity_count, evidence_count
                FROM {db}.intel_analysis_wide
                ORDER BY raw_id DESC
                LIMIT 10
            """)
            recent = [dict(r) for r in c.fetchall()]

        return {
            "total_analyzed": total,
            "today_count": today,
            "high_risk_count": high_risk,
            "entity_count": entity_total,
            "label_distribution": label_dist,
            "recent_items": recent,
        }

    def daily_trend(self, days: int = 7) -> list[dict]:
        """Daily analysis count for the last N days."""
        db = settings.doris_database
        with self.cursor() as c:
            c.execute(f"""
                SELECT DATE(collect_time) as dt, COUNT(*) as cnt,
                       SUM(CASE WHEN risk_level IN ('high','critical') THEN 1 ELSE 0 END) as high_cnt
                FROM {db}.intel_analysis_wide
                WHERE collect_time >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                GROUP BY dt
                ORDER BY dt
            """, (days,))
            return c.fetchall()

    def risk_level_breakdown(self) -> dict:
        """Count by risk level."""
        db = settings.doris_database
        with self.cursor() as c:
            c.execute(f"""
                SELECT risk_level, COUNT(*) as cnt
                FROM {db}.intel_analysis_wide
                GROUP BY risk_level
            """)
            return {r["risk_level"]: r["cnt"] for r in c.fetchall()}

    def platform_stats(self) -> dict:
        """Count by source platform."""
        db = settings.doris_database
        with self.cursor() as c:
            c.execute(f"""
                SELECT platform, COUNT(*) as cnt,
                       AVG(risk_score) as avg_score
                FROM {db}.intel_analysis_wide
                GROUP BY platform
            """)
            return {r["platform"]: {"count": r["cnt"], "avg_score": float(r["avg_score"] or 0)}
                    for r in c.fetchall()}


doris = DorisStore()
