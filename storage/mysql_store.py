"""MySQL storage layer for BGI agent — aligned to PROJECT_PLAN.md Section 5.1.

Table layering:
    ODS: ods_raw_intel     — original intelligence
    DWD: dwd_clean_intel   — cleaned / deduped
         dwd_intel_analysis — classification + evidence
         dwd_entity         — extracted entities
         dwd_entity_relation— entity pairs
    DIM: dim_slang_dict    — slang dictionary
    ADS: ads_risk_case     — gang / case aggregation
         agent_report      — generated reports
    LOG: annotation_log    — HITL feedback
"""

import json as _json
import pymysql
from contextlib import contextmanager
from loguru import logger
from config.settings import settings


class MySQLStore:
    """Manages all MySQL CRUD operations."""

    def __init__(self):
        self._conn = None

    @property
    def conn(self):
        if self._conn is None or not self._conn.open:
            self._conn = pymysql.connect(
                host=settings.mysql_host,
                port=settings.mysql_port,
                user=settings.mysql_user,
                password=settings.mysql_password,
                database=settings.mysql_database,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
            )
        return self._conn

    @contextmanager
    def cursor(self):
        c = self.conn.cursor()
        try:
            yield c
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            c.close()

    # ------------------------------------------------------------------
    # Init — all 9 tables per PROJECT_PLAN.md 5.1
    # ------------------------------------------------------------------

    def init_tables(self):
        ddl = """
        -- ODS layer: raw intelligence
        CREATE TABLE IF NOT EXISTS ods_raw_intel (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            source_platform VARCHAR(32) NOT NULL,
            source_channel VARCHAR(128),
            source_url VARCHAR(1024),
            source_keyword VARCHAR(128),
            author_id VARCHAR(128),
            author_name VARCHAR(256),
            publish_time DATETIME,
            collect_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            content_type VARCHAR(32) DEFAULT 'text',
            content_raw MEDIUMTEXT NOT NULL,
            media_urls JSON,
            media_hash VARCHAR(64),
            crawl_batch_id VARCHAR(64),
            raw_status VARCHAR(32) DEFAULT 'RAW_COLLECTED',
            metadata JSON,
            INDEX idx_platform_time(source_platform, publish_time),
            INDEX idx_batch(crawl_batch_id),
            INDEX idx_status(raw_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        -- DWD layer: cleaned / deduped
        CREATE TABLE IF NOT EXISTS dwd_clean_intel (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            raw_id BIGINT NOT NULL,
            clean_text MEDIUMTEXT,
            ocr_text MEDIUMTEXT,
            asr_text MEDIUMTEXT,
            merged_text MEDIUMTEXT,
            simhash VARCHAR(64),
            content_md5 VARCHAR(64),
            dedup_group_id BIGINT,
            is_duplicate TINYINT DEFAULT 0,
            noise_score DECIMAL(5,4) DEFAULT 0,
            priority VARCHAR(16) DEFAULT 'normal',
            clean_status VARCHAR(32) DEFAULT 'CLEANED',
            clean_reason VARCHAR(256),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_raw(raw_id),
            INDEX idx_simhash(simhash),
            INDEX idx_priority(priority)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        -- DWD layer: classification + evidence
        CREATE TABLE IF NOT EXISTS dwd_intel_analysis (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            raw_id BIGINT NOT NULL,
            clean_id BIGINT,
            risk_label VARCHAR(64),
            risk_sub_label VARCHAR(128),
            risk_score DECIMAL(5,4),
            risk_level VARCHAR(16),
            classification_method VARCHAR(64),
            evidence_spans JSON,
            analysis_status VARCHAR(32) DEFAULT 'CLASSIFIED',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_raw(raw_id),
            INDEX idx_risk(risk_label, risk_sub_label),
            INDEX idx_level(risk_level)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        -- DWD layer: extracted entities
        CREATE TABLE IF NOT EXISTS dwd_entity (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            raw_id BIGINT NOT NULL,
            clean_id BIGINT,
            entity_type VARCHAR(64) NOT NULL,
            entity_value TEXT NOT NULL,
            normalized_value TEXT,
            extract_method VARCHAR(32),
            confidence DECIMAL(5,4),
            context TEXT,
            start_offset INT,
            end_offset INT,
            first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_raw(raw_id),
            INDEX idx_type(entity_type),
            INDEX idx_value(entity_value(255))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        -- DWD layer: entity relationship pairs
        CREATE TABLE IF NOT EXISTS dwd_entity_relation (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            src_entity_id BIGINT NOT NULL,
            dst_entity_id BIGINT NOT NULL,
            relation_type VARCHAR(64) NOT NULL,
            relation_source VARCHAR(64),
            evidence_raw_id BIGINT,
            confidence DECIMAL(5,4),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_src(src_entity_id),
            INDEX idx_dst(dst_entity_id),
            INDEX idx_relation(relation_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        -- DIM layer: slang dictionary
        CREATE TABLE IF NOT EXISTS dim_slang_dict (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            term VARCHAR(128) NOT NULL UNIQUE,
            normalized_meaning TEXT NOT NULL,
            risk_category VARCHAR(64),
            examples JSON,
            source VARCHAR(64),
            confidence DECIMAL(5,4) DEFAULT 1.0,
            status VARCHAR(32) DEFAULT 'active',
            embedding_id VARCHAR(128),
            created_by VARCHAR(64),
            reviewed_by VARCHAR(64),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_term(term),
            INDEX idx_category(risk_category),
            INDEX idx_status(status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        -- ADS layer: gang / risk case
        CREATE TABLE IF NOT EXISTS ads_risk_case (
            case_id VARCHAR(128) PRIMARY KEY,
            case_name VARCHAR(256),
            main_risk_type VARCHAR(64),
            risk_level VARCHAR(16),
            summary TEXT,
            key_entities JSON,
            related_intel_count INT DEFAULT 0,
            first_seen DATETIME,
            last_seen DATETIME,
            status VARCHAR(32) DEFAULT 'open',
            agent_report_id BIGINT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        -- ADS layer: generated reports
        CREATE TABLE IF NOT EXISTS agent_report (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            raw_id BIGINT,
            case_id VARCHAR(128),
            report_type VARCHAR(32),
            title VARCHAR(256),
            summary TEXT,
            evidence_json JSON,
            entities_json JSON,
            graph_json JSON,
            disposal_advice JSON,
            training_sample JSON,
            generated_by VARCHAR(64) DEFAULT 'report_agent',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_raw(raw_id),
            INDEX idx_case(case_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        -- LOG layer: HITL annotation
        CREATE TABLE IF NOT EXISTS annotation_log (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            target_type VARCHAR(32) NOT NULL,
            target_id BIGINT NOT NULL,
            field_name VARCHAR(64) NOT NULL,
            old_value TEXT,
            new_value TEXT,
            annotator VARCHAR(64),
            reason VARCHAR(256),
            synced TINYINT DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_target(target_type, target_id),
            INDEX idx_synced(synced)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        with self.cursor() as c:
            for stmt in ddl.split(";"):
                # Strip comment lines and whitespace
                lines = [l for l in stmt.split("\n")
                        if not l.strip().startswith("--")]
                stmt = "\n".join(lines).strip()
                if stmt:
                    c.execute(stmt)
        logger.info("MySQL tables initialized (9-table ODS/DWD/DIM/ADS schema)")

    # ==================================================================
    # ODS: Raw Intelligence
    # ==================================================================

    def insert_raw(self, item: dict) -> int:
        """Insert into ods_raw_intel. Backward-compat: maps old field names."""
        sql = """INSERT INTO ods_raw_intel
            (source_platform, source_channel, source_url, source_keyword,
             author_id, author_name, publish_time, collect_time,
             content_type, content_raw, media_urls, media_hash,
             crawl_batch_id, raw_status, metadata)
        VALUES (%(source_platform)s, %(source_channel)s, %(source_url)s, %(source_keyword)s,
                %(author_id)s, %(author_name)s, %(publish_time)s, %(collect_time)s,
                %(content_type)s, %(content_raw)s, %(media_urls)s, %(media_hash)s,
                %(crawl_batch_id)s, %(raw_status)s, %(metadata)s)"""
        # Map old field names for backward compatibility
        item.setdefault("source_url", item.get("source_url"))
        item.setdefault("source_channel", item.get("source_channel"))
        item.setdefault("source_keyword", item.get("source_keyword"))
        item.setdefault("author_id", item.get("author_uid"))
        item.setdefault("author_name", item.get("author_username"))
        item.setdefault("publish_time", item.get("publish_time") or item.get("collected_at"))
        item.setdefault("collect_time", item.get("collected_at"))
        item.setdefault("media_urls", _json.dumps(item.get("media_urls", [])) if not isinstance(item.get("media_urls"), str) else item.get("media_urls"))
        item.setdefault("media_hash", item.get("image_hash"))
        item.setdefault("crawl_batch_id", item.get("crawl_batch_id"))
        item.setdefault("raw_status", item.get("status", "RAW_COLLECTED"))
        item.setdefault("metadata", _json.dumps(item.get("metadata", {})) if not isinstance(item.get("metadata"), str) else item.get("metadata"))
        with self.cursor() as c:
            c.execute(sql, item)
            return c.lastrowid

    def update_raw_status(self, raw_id: int, status: str,
                          clean_text: str = None, simhash: str = None,
                          priority: str = None, noise_score: float = None,
                          clean_reason: str = None):
        """Update ods_raw_intel status. If clean_text/simhash provided,
        also upsert into dwd_clean_intel."""
        with self.cursor() as c:
            c.execute("UPDATE ods_raw_intel SET raw_status=%s WHERE id=%s",
                      (status, raw_id))
        if clean_text or simhash:
            self.insert_clean_intel(raw_id, clean_text, simhash,
                                    priority=priority, noise_score=noise_score,
                                    clean_reason=clean_reason)

    def list_raw(self, status: str = None, priority: str = None,
                 platform: str = None, limit: int = 100, offset: int = 0) -> list[dict]:
        where = []
        params = []
        if status:
            where.append("raw_status=%s"); params.append(status)
        if priority:
            where.append("JSON_EXTRACT(metadata, '$.priority')=%s"); params.append(priority)
        if platform:
            where.append("source_platform=%s"); params.append(platform)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.extend([limit, offset])
        with self.cursor() as c:
            c.execute(
                f"""SELECT o.*, d.clean_text, d.simhash as clean_simhash,
                           d.priority as clean_priority, d.noise_score
                    FROM ods_raw_intel o
                    LEFT JOIN dwd_clean_intel d ON d.raw_id = o.id
                    {clause}
                    ORDER BY o.collect_time DESC LIMIT %s OFFSET %s""",
                params,
            )
            rows = c.fetchall()
            # Map field names for backward compat
            for r in rows:
                r.setdefault("content", r.get("content_raw"))
                r.setdefault("author_uid", r.get("author_id"))
                r.setdefault("author_username", r.get("author_name"))
                r.setdefault("platform", r.get("source_platform"))
                r.setdefault("collected_at", r.get("collect_time"))
                r.setdefault("status", r.get("raw_status"))
                r.setdefault("image_hash", r.get("media_hash"))
            return rows

    def find_by_simhash(self, simhash: str, limit: int = 5) -> list[dict]:
        with self.cursor() as c:
            c.execute(
                "SELECT ci.*, r.source_platform, r.content_raw "
                "FROM dwd_clean_intel ci "
                "LEFT JOIN ods_raw_intel r ON ci.raw_id = r.id "
                "WHERE ci.simhash=%s LIMIT %s",
                (simhash, limit),
            )
            return c.fetchall()

    # ==================================================================
    # DWD: Clean Intel
    # ==================================================================

    def insert_clean_intel(self, raw_id: int, clean_text: str = None,
                           simhash: str = None, priority: str = None,
                           noise_score: float = None, clean_reason: str = None,
                           **kwargs):
        """Upsert into dwd_clean_intel."""
        with self.cursor() as c:
            c.execute("SELECT id FROM dwd_clean_intel WHERE raw_id=%s", (raw_id,))
            existing = c.fetchone()
            if existing:
                sets = []
                params = []
                if clean_text:
                    sets.append("clean_text=%s"); params.append(clean_text)
                if simhash:
                    sets.append("simhash=%s"); params.append(simhash)
                if priority:
                    sets.append("priority=%s"); params.append(priority)
                if noise_score is not None:
                    sets.append("noise_score=%s"); params.append(noise_score)
                if clean_reason:
                    sets.append("clean_reason=%s"); params.append(clean_reason)
                if sets:
                    params.append(raw_id)
                    c.execute(f"UPDATE dwd_clean_intel SET {', '.join(sets)} WHERE raw_id=%s", params)
                return existing["id"]
            else:
                c.execute(
                    """INSERT INTO dwd_clean_intel
                       (raw_id, clean_text, simhash, priority, noise_score, clean_reason, clean_status)
                       VALUES (%s, %s, %s, %s, %s, %s, 'CLEANED')""",
                    (raw_id, clean_text, simhash, priority or "normal",
                     noise_score or 0.0, clean_reason or ""),
                )
                return c.lastrowid
                return c.lastrowid

    # ==================================================================
    # DWD: Analysis
    # ==================================================================

    def insert_analysis(self, result: dict):
        """Insert into dwd_intel_analysis."""
        sql = """INSERT INTO dwd_intel_analysis
            (raw_id, clean_id, risk_label, risk_sub_label, risk_score, risk_level,
             classification_method, evidence_spans, analysis_status)
        VALUES (%(raw_id)s, %(clean_id)s, %(risk_label)s, %(risk_sub_label)s,
                %(risk_score)s, %(risk_level)s, %(classification_method)s,
                %(evidence_spans)s, %(analysis_status)s)"""
        result.setdefault("risk_label", result.get("intent_label"))
        result.setdefault("risk_sub_label", result.get("sub_label"))
        result.setdefault("risk_score", result.get("confidence", 0))
        result.setdefault("risk_level", result.get("risk_level", "normal"))
        result.setdefault("classification_method", result.get("classification_method", ""))
        result.setdefault("clean_id", result.get("clean_id"))
        result.setdefault("analysis_status", result.get("analysis_status", "CLASSIFIED"))
        result.setdefault("raw_id", result.get("raw_data_id"))
        # Ensure evidence_spans is serialized to JSON
        if "evidence_spans" in result:
            val = result["evidence_spans"]
            if not isinstance(val, str):
                result["evidence_spans"] = _json.dumps(val, ensure_ascii=False)
        else:
            result["evidence_spans"] = "[]"
        with self.cursor() as c:
            c.execute(sql, result)

    def update_analysis(self, raw_id: int, **kwargs):
        """Update specific fields in dwd_intel_analysis."""
        allowed = {"risk_label", "risk_sub_label", "risk_score", "risk_level",
                   "classification_method", "evidence_spans", "analysis_status"}
        sets = []
        params = []
        for k, v in kwargs.items():
            if k in allowed:
                sets.append(f"{k}=%s"); params.append(v)
        if not sets:
            return
        params.append(raw_id)
        with self.cursor() as c:
            c.execute(f"UPDATE dwd_intel_analysis SET {', '.join(sets)} WHERE raw_id=%s", params)

    # ==================================================================
    # DWD: Entity
    # ==================================================================

    def insert_entity(self, entity: dict):
        """Insert into dwd_entity."""
        sql = """INSERT INTO dwd_entity
            (raw_id, clean_id, entity_type, entity_value, normalized_value,
             extract_method, confidence, context, start_offset, end_offset)
        VALUES (%(raw_id)s, %(clean_id)s, %(entity_type)s, %(entity_value)s,
                %(normalized_value)s, %(extract_method)s, %(confidence)s,
                %(context)s, %(start_offset)s, %(end_offset)s)"""
        entity.setdefault("raw_id", entity.get("raw_data_id"))
        entity.setdefault("clean_id", entity.get("clean_id"))
        entity.setdefault("normalized_value", entity.get("entity_value"))
        entity.setdefault("extract_method", entity.get("extraction_method", "regex"))
        entity.setdefault("confidence", entity.get("confidence", 0.9))
        entity.setdefault("start_offset", entity.get("start", -1))
        entity.setdefault("end_offset", entity.get("end", -1))
        with self.cursor() as c:
            c.execute(sql, entity)

    def find_entity(self, entity_type: str, value: str) -> list[dict]:
        with self.cursor() as c:
            c.execute(
                "SELECT * FROM dwd_entity WHERE entity_type=%s AND entity_value=%s",
                (entity_type, value),
            )
            return c.fetchall()

    def find_entities_by_raw(self, raw_id: int) -> list[dict]:
        with self.cursor() as c:
            c.execute("SELECT * FROM dwd_entity WHERE raw_id=%s", (raw_id,))
            return c.fetchall()

    # ==================================================================
    # DWD: Entity Relation
    # ==================================================================

    def insert_entity_relation(self, src_entity_id: int, dst_entity_id: int,
                               relation_type: str, **kwargs):
        """Insert a relationship between two entities."""
        sql = """INSERT INTO dwd_entity_relation
            (src_entity_id, dst_entity_id, relation_type, relation_source,
             evidence_raw_id, confidence)
        VALUES (%s, %s, %s, %s, %s, %s)"""
        with self.cursor() as c:
            c.execute(sql, (
                src_entity_id, dst_entity_id, relation_type,
                kwargs.get("relation_source", "neo4j_sync"),
                kwargs.get("evidence_raw_id"),
                kwargs.get("confidence", 1.0),
            ))

    def get_entity_relations(self, entity_id: int) -> list[dict]:
        with self.cursor() as c:
            c.execute(
                """SELECT * FROM dwd_entity_relation
                   WHERE src_entity_id=%s OR dst_entity_id=%s""",
                (entity_id, entity_id),
            )
            return c.fetchall()

    # ==================================================================
    # DIM: Slang Dictionary
    # ==================================================================

    def insert_slang(self, slang: dict):
        """Insert or update dim_slang_dict."""
        sql = """INSERT INTO dim_slang_dict
            (term, normalized_meaning, risk_category, examples, source,
             confidence, status, embedding_id, created_by, reviewed_by)
        VALUES (%(term)s, %(normalized_meaning)s, %(risk_category)s, %(examples)s,
                %(source)s, %(confidence)s, %(status)s, %(embedding_id)s,
                %(created_by)s, %(reviewed_by)s)
        ON DUPLICATE KEY UPDATE
            normalized_meaning=VALUES(normalized_meaning),
            risk_category=VALUES(risk_category),
            examples=VALUES(examples),
            source=VALUES(source),
            confidence=VALUES(confidence),
            status=VALUES(status),
            embedding_id=VALUES(embedding_id),
            reviewed_by=VALUES(reviewed_by)"""
        slang.setdefault("term", slang.get("slang"))
        slang.setdefault("normalized_meaning", slang.get("normalized_meaning"))
        slang.setdefault("risk_category", slang.get("category"))
        slang.setdefault("examples", slang.get("examples",
            _json.dumps([], ensure_ascii=False)))
        slang.setdefault("source", slang.get("source", "manual"))
        slang.setdefault("confidence", slang.get("confidence", 1.0))
        slang.setdefault("status", slang.get("status", "active"))
        slang.setdefault("embedding_id", slang.get("embedding_id"))
        slang.setdefault("created_by", slang.get("created_by"))
        slang.setdefault("reviewed_by", slang.get("reviewed_by") or slang.get("confirmed_by"))
        with self.cursor() as c:
            c.execute(sql, slang)

    def list_slang(self, status: str = "active") -> list[dict]:
        with self.cursor() as c:
            c.execute("SELECT * FROM dim_slang_dict WHERE status=%s", (status,))
            rows = c.fetchall()
            for r in rows:
                r.setdefault("slang", r.get("term"))
                r.setdefault("category", r.get("risk_category"))
                r.setdefault("normalized_meaning", r.get("normalized_meaning"))
            return rows

    # ==================================================================
    # ADS: Risk Case
    # ==================================================================

    def upsert_risk_case(self, case_id: str, **kwargs):
        """Insert or update an ads_risk_case."""
        with self.cursor() as c:
            c.execute("SELECT case_id FROM ads_risk_case WHERE case_id=%s", (case_id,))
            if c.fetchone():
                sets = []
                params = []
                for k, v in kwargs.items():
                    if v is not None:
                        sets.append(f"{k}=%s"); params.append(v)
                if sets:
                    params.append(case_id)
                    c.execute(f"UPDATE ads_risk_case SET {', '.join(sets)} WHERE case_id=%s", params)
            else:
                fields = ["case_id"] + list(kwargs.keys())
                placeholders = ["%s"] * len(fields)
                values = [case_id] + list(kwargs.values())
                c.execute(
                    f"INSERT INTO ads_risk_case ({', '.join(fields)}) VALUES ({', '.join(placeholders)})",
                    values,
                )

    def list_risk_cases(self, status: str = "open") -> list[dict]:
        with self.cursor() as c:
            c.execute("SELECT * FROM ads_risk_case WHERE status=%s ORDER BY created_at DESC", (status,))
            return c.fetchall()

    # ==================================================================
    # ADS: Agent Report
    # ==================================================================

    def insert_report(self, report: dict) -> int:
        """Insert a generated report."""
        sql = """INSERT INTO agent_report
            (raw_id, case_id, report_type, title, summary, evidence_json,
             entities_json, graph_json, disposal_advice, training_sample, generated_by)
        VALUES (%(raw_id)s, %(case_id)s, %(report_type)s, %(title)s, %(summary)s,
                %(evidence_json)s, %(entities_json)s, %(graph_json)s,
                %(disposal_advice)s, %(training_sample)s, %(generated_by)s)"""
        for json_field in ["evidence_json", "entities_json", "graph_json",
                          "disposal_advice", "training_sample"]:
            if json_field in report:
                val = report[json_field]
                if not isinstance(val, str):
                    report[json_field] = _json.dumps(val, ensure_ascii=False)
            else:
                report[json_field] = "{}"
        report.setdefault("raw_id", report.get("raw_id"))
        report.setdefault("case_id", report.get("case_id", ""))
        report.setdefault("report_type", report.get("report_type", "intel_analysis"))
        report.setdefault("title", report.get("title", ""))
        report.setdefault("summary", report.get("conclusion", report.get("summary", "")))
        report.setdefault("generated_by", report.get("generated_by", "report_agent"))
        with self.cursor() as c:
            c.execute(sql, report)
            return c.lastrowid

    def get_reports_by_raw(self, raw_id: int) -> list[dict]:
        with self.cursor() as c:
            c.execute("SELECT * FROM agent_report WHERE raw_id=%s ORDER BY created_at DESC", (raw_id,))
            return c.fetchall()

    # ==================================================================
    # Annotation Log (HITL)
    # ==================================================================

    def log_annotation(self, target_type: str, target_id: int, field_name: str,
                       old_value: str, new_value: str, annotator: str = None,
                       reason: str = None):
        """Record a human correction."""
        sql = """INSERT INTO annotation_log
            (target_type, target_id, field_name, old_value, new_value, annotator, reason)
        VALUES (%s, %s, %s, %s, %s, %s, %s)"""
        with self.cursor() as c:
            c.execute(sql, (target_type, target_id, field_name, old_value, new_value,
                          annotator, reason))

    def get_pending_annotations(self) -> list[dict]:
        with self.cursor() as c:
            c.execute("SELECT * FROM annotation_log WHERE synced=0 ORDER BY created_at")
            return c.fetchall()

    # ==================================================================
    # HITL Closed-Loop Sync
    # ==================================================================

    def sync_slang_correction(self, slang: str, normalized_meaning: str,
                              category: str = None, corrected_by: str = None) -> bool:
        """Update dim_slang_dict and mark annotations as synced."""
        self.insert_slang({
            "term": slang,
            "normalized_meaning": normalized_meaning,
            "risk_category": category,
            "source": "manual",
            "status": "active",
            "reviewed_by": corrected_by,
        })
        with self.cursor() as c:
            c.execute(
                """UPDATE annotation_log SET synced=1
                   WHERE target_type='slang' AND field_name='normalized_meaning'
                   AND new_value=%s AND synced=0""",
                (normalized_meaning,),
            )
        logger.info(f"HITL slang correction synced: '{slang}' -> '{normalized_meaning}'")
        return True

    def sync_classification_correction(self, raw_data_id: int, intent_label: str,
                                       sub_label: str = "", corrected_by: str = None) -> bool:
        """Update dwd_intel_analysis and mark annotations as synced."""
        with self.cursor() as c:
            c.execute(
                """UPDATE dwd_intel_analysis
                   SET risk_label=%s, risk_sub_label=%s, classification_method='manual'
                   WHERE raw_id=%s""",
                (intent_label, sub_label, raw_data_id),
            )
            c.execute(
                """UPDATE annotation_log SET synced=1
                   WHERE target_type='classification' AND target_id=%s AND synced=0""",
                (raw_data_id,),
            )
        logger.info(f"HITL classification correction synced for raw_id={raw_data_id}")
        return True

    # ==================================================================
    # Stats for Dashboard
    # ==================================================================

    def daily_stats(self) -> dict:
        with self.cursor() as c:
            c.execute("SELECT COUNT(*) as cnt FROM ods_raw_intel WHERE DATE(collect_time) = CURDATE()")
            today_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM ods_raw_intel WHERE raw_status IN ('RAW_COLLECTED','CLEANED')")
            pending_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM dwd_intel_analysis WHERE risk_level IN ('high','critical')")
            high_risk_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM dwd_entity")
            entity_count = c.fetchone()["cnt"]
            c.execute("SELECT risk_label, COUNT(*) as cnt FROM dwd_intel_analysis GROUP BY risk_label")
            label_distribution = {r["risk_label"]: r["cnt"] for r in c.fetchall()}
            c.execute("""
                SELECT r.id, r.content_raw, r.source_platform, r.collect_time,
                       a.risk_label, a.risk_level, a.risk_score
                FROM ods_raw_intel r
                LEFT JOIN dwd_intel_analysis a ON r.id = a.raw_id
                WHERE r.raw_status != 'DISCARDED'
                ORDER BY r.id DESC
                LIMIT 10
            """)
            recent_items = [dict(row) for row in c.fetchall()]
            for ri in recent_items:
                ri.setdefault("content", ri.get("content_raw"))
                ri.setdefault("platform", ri.get("source_platform"))
                ri.setdefault("collected_at", ri.get("collect_time"))
        return {
            "today_count": today_count,
            "pending_count": pending_count,
            "high_risk_count": high_risk_count,
            "entity_count": entity_count,
            "label_distribution": label_distribution,
            "recent_items": recent_items,
        }

    # ==================================================================
    # Data Migration: old tables → new tables
    # ==================================================================

    def migrate_old_data(self) -> dict:
        """Migrate data from old table names to new PROJECT_PLAN.md schema.
        Runs idempotently — skips already-migrated records.
        """
        stats = {}

        with self.cursor() as c:
            # 1. raw_data → ods_raw_intel
            try:
                c.execute("SELECT COUNT(*) as cnt FROM raw_data")
                old_count = c.fetchone()["cnt"]
                if old_count > 0:
                    c.execute("""
                        INSERT IGNORE INTO ods_raw_intel
                            (id, source_platform, source_url, author_id, author_name,
                             content_type, content_raw, media_hash,
                             collect_time, raw_status, metadata)
                        SELECT id, source_platform, source_url, author_uid, author_username,
                               content_type, content_raw, image_hash,
                               collected_at, status, metadata
                        FROM raw_data
                    """)
                    stats["ods_raw_intel"] = f"migrated {old_count} rows from raw_data"
            except Exception as e:
                stats["ods_raw_intel"] = f"skipped: {e}"

            # 2. analysis_results → dwd_intel_analysis
            try:
                c.execute("SELECT COUNT(*) as cnt FROM analysis_results")
                old_count = c.fetchone()["cnt"]
                if old_count > 0:
                    c.execute("""
                        INSERT IGNORE INTO dwd_intel_analysis
                            (id, raw_id, risk_label, risk_sub_label, risk_score,
                             risk_level, classification_method, analysis_status, created_at)
                        SELECT id, raw_data_id, intent_label, sub_label, confidence,
                               CASE WHEN is_high_risk=1 THEN 'high' ELSE 'normal' END,
                               classification_method, 'CLASSIFIED', analyzed_at
                        FROM analysis_results
                    """)
                    stats["dwd_intel_analysis"] = f"migrated {old_count} rows from analysis_results"
            except Exception as e:
                stats["dwd_intel_analysis"] = f"skipped: {e}"

            # 3. entities → dwd_entity
            try:
                c.execute("SELECT COUNT(*) as cnt FROM entities")
                old_count = c.fetchone()["cnt"]
                if old_count > 0:
                    c.execute("""
                        INSERT IGNORE INTO dwd_entity
                            (id, raw_id, entity_type, entity_value,
                             extract_method, context, first_seen)
                        SELECT id, raw_data_id, entity_type, entity_value,
                               extraction_method, context, first_seen
                        FROM entities
                    """)
                    stats["dwd_entity"] = f"migrated {old_count} rows from entities"
            except Exception as e:
                stats["dwd_entity"] = f"skipped: {e}"

            # 4. slang_dict → dim_slang_dict
            try:
                c.execute("SELECT COUNT(*) as cnt FROM slang_dict")
                old_count = c.fetchone()["cnt"]
                if old_count > 0:
                    c.execute("""
                        INSERT IGNORE INTO dim_slang_dict
                            (term, normalized_meaning, risk_category, source,
                             status, embedding_id, created_by, created_at)
                        SELECT slang, normalized_meaning, category, source,
                               status, embedding_id, confirmed_by, created_at
                        FROM slang_dict
                    """)
                    stats["dim_slang_dict"] = f"migrated {old_count} rows from slang_dict"
            except Exception as e:
                stats["dim_slang_dict"] = f"skipped: {e}"

            # 5. annotation_log (old → new, mapping corrected_by → annotator)
            try:
                c.execute("""
                    SELECT COUNT(*) as cnt FROM annotation_log
                    WHERE annotator IS NULL AND synced IS NOT NULL
                """)
                # Just ensure columns exist; old annotations stay as-is
                stats["annotation_log"] = "columns already aligned"
            except Exception as e:
                stats["annotation_log"] = f"skipped: {e}"

        logger.info(f"Data migration complete: {stats}")
        return stats


mysql = MySQLStore()
