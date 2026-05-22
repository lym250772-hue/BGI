"""MySQL storage layer for BGI agent."""
import pymysql
from contextlib import contextmanager
from typing import Optional
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
    # Init
    # ------------------------------------------------------------------

    def init_tables(self):
        ddl = """
        CREATE TABLE IF NOT EXISTS raw_data (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            source_platform VARCHAR(32) NOT NULL,
            source_url TEXT,
            author_uid VARCHAR(128),
            author_username VARCHAR(256),
            content_type VARCHAR(16) DEFAULT 'text',
            content_raw MEDIUMTEXT NOT NULL,
            content MEDIUMTEXT,
            image_hash VARCHAR(64),
            simhash VARCHAR(64),
            priority VARCHAR(16) DEFAULT 'normal',
            status VARCHAR(16) DEFAULT 'pending',
            collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            group_id VARCHAR(128),
            message_id BIGINT,
            metadata JSON,
            INDEX idx_platform (source_platform),
            INDEX idx_simhash (simhash),
            INDEX idx_status (status),
            INDEX idx_priority (priority),
            INDEX idx_collected_at (collected_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS analysis_results (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            raw_data_id BIGINT NOT NULL,
            intent_label VARCHAR(64),
            sub_label VARCHAR(128),
            confidence DECIMAL(5,4),
            classification_method VARCHAR(32),
            is_high_risk TINYINT(1) DEFAULT 0,
            analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (raw_data_id) REFERENCES raw_data(id) ON DELETE CASCADE,
            INDEX idx_label (intent_label),
            INDEX idx_raw_id (raw_data_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS entities (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            raw_data_id BIGINT NOT NULL,
            entity_type VARCHAR(32) NOT NULL,
            entity_value TEXT NOT NULL,
            extraction_method VARCHAR(32) DEFAULT 'regex',
            context TEXT,
            metadata JSON,
            first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (raw_data_id) REFERENCES raw_data(id) ON DELETE CASCADE,
            INDEX idx_type (entity_type),
            INDEX idx_value (entity_value(255))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS slang_dict (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            slang VARCHAR(128) NOT NULL,
            normalized_meaning TEXT NOT NULL,
            category VARCHAR(64),
            source VARCHAR(64) DEFAULT 'manual',
            embedding_id VARCHAR(64),
            status VARCHAR(16) DEFAULT 'active',
            confirmed_by VARCHAR(64),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_slang (slang),
            INDEX idx_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS cheat_scripts (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            title VARCHAR(256) NOT NULL,
            risk_type VARCHAR(64),
            abuse_chain TEXT,
            tools_used TEXT,
            related_entities TEXT,
            defense_suggestions TEXT,
            related_intel_ids TEXT,
            generated_by VARCHAR(32) DEFAULT 'llm',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS annotation_log (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            target_type VARCHAR(32) NOT NULL,
            target_id BIGINT,
            field_name VARCHAR(64),
            old_value TEXT,
            new_value TEXT NOT NULL,
            corrected_by VARCHAR(64),
            synced TINYINT(1) DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_target (target_type, target_id),
            INDEX idx_synced (synced)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        with self.cursor() as c:
            for stmt in ddl.split(";"):
                stmt = stmt.strip()
                if stmt and not stmt.startswith("--"):
                    c.execute(stmt)
        logger.info("MySQL tables initialized")

    # ------------------------------------------------------------------
    # Raw Data
    # ------------------------------------------------------------------

    def insert_raw(self, item: dict) -> int:
        sql = """INSERT INTO raw_data
            (source_platform, source_url, author_uid, author_username,
             content_type, content_raw, content, image_hash, simhash,
             priority, status, collected_at, group_id, message_id, metadata)
        VALUES (%(source_platform)s, %(source_url)s, %(author_uid)s, %(author_username)s,
                %(content_type)s, %(content_raw)s, %(content)s, %(image_hash)s, %(simhash)s,
                %(priority)s, %(status)s, %(collected_at)s, %(group_id)s, %(message_id)s, %(metadata)s)"""
        with self.cursor() as c:
            c.execute(sql, item)
            return c.lastrowid

    def update_raw_status(self, raw_id: int, status: str, content: str = None, simhash: str = None):
        sets = ["status=%s"]
        params = [status]
        if content is not None:
            sets.append("content=%s")
            params.append(content)
        if simhash is not None:
            sets.append("simhash=%s")
            params.append(simhash)
        params.append(raw_id)
        with self.cursor() as c:
            c.execute(f"UPDATE raw_data SET {', '.join(sets)} WHERE id=%s", params)

    def find_by_simhash(self, simhash: str, limit: int = 5) -> list[dict]:
        with self.cursor() as c:
            c.execute("SELECT * FROM raw_data WHERE simhash=%s LIMIT %s", (simhash, limit))
            return c.fetchall()

    def list_raw(self, status: str = None, priority: str = None, platform: str = None,
                 limit: int = 100, offset: int = 0) -> list[dict]:
        where = []
        params = []
        if status:
            where.append("status=%s"); params.append(status)
        if priority:
            where.append("priority=%s"); params.append(priority)
        if platform:
            where.append("source_platform=%s"); params.append(platform)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.extend([limit, offset])
        with self.cursor() as c:
            c.execute(f"SELECT * FROM raw_data {clause} ORDER BY collected_at DESC LIMIT %s OFFSET %s", params)
            return c.fetchall()

    # ------------------------------------------------------------------
    # Analysis Results
    # ------------------------------------------------------------------

    def insert_analysis(self, result: dict):
        sql = """INSERT INTO analysis_results
            (raw_data_id, intent_label, sub_label, confidence, classification_method, is_high_risk)
        VALUES (%(raw_data_id)s, %(intent_label)s, %(sub_label)s, %(confidence)s,
                %(classification_method)s, %(is_high_risk)s)"""
        with self.cursor() as c:
            c.execute(sql, result)

    # ------------------------------------------------------------------
    # Entities
    # ------------------------------------------------------------------

    def insert_entity(self, entity: dict):
        sql = """INSERT INTO entities
            (raw_data_id, entity_type, entity_value, extraction_method, context, metadata)
        VALUES (%(raw_data_id)s, %(entity_type)s, %(entity_value)s, %(extraction_method)s,
                %(context)s, %(metadata)s)"""
        with self.cursor() as c:
            c.execute(sql, entity)

    def find_entity(self, entity_type: str, value: str) -> list[dict]:
        with self.cursor() as c:
            c.execute("SELECT * FROM entities WHERE entity_type=%s AND entity_value=%s",
                      (entity_type, value))
            return c.fetchall()

    # ------------------------------------------------------------------
    # Slang Dictionary
    # ------------------------------------------------------------------

    def insert_slang(self, slang: dict):
        sql = """INSERT INTO slang_dict (slang, normalized_meaning, category, source, embedding_id, status)
        VALUES (%(slang)s, %(normalized_meaning)s, %(category)s, %(source)s,
                %(embedding_id)s, %(status)s)
        ON DUPLICATE KEY UPDATE normalized_meaning=VALUES(normalized_meaning),
                                category=VALUES(category),
                                source=VALUES(source),
                                status=VALUES(status)"""
        slang.setdefault("embedding_id", None)
        slang.setdefault("status", "active")
        with self.cursor() as c:
            c.execute(sql, slang)

    def list_slang(self, status: str = "active") -> list[dict]:
        with self.cursor() as c:
            c.execute("SELECT * FROM slang_dict WHERE status=%s", (status,))
            return c.fetchall()

    # ------------------------------------------------------------------
    # HITL Feedback — annotation_log + auto-sync
    # ------------------------------------------------------------------

    def log_annotation(self, target_type: str, target_id: int, field_name: str,
                       old_value: str, new_value: str, corrected_by: str = None):
        """Record a human correction in the annotation log."""
        sql = """INSERT INTO annotation_log
            (target_type, target_id, field_name, old_value, new_value, corrected_by)
        VALUES (%s, %s, %s, %s, %s, %s)"""
        with self.cursor() as c:
            c.execute(sql, (target_type, target_id, field_name, old_value, new_value, corrected_by))

    def sync_slang_correction(self, slang: str, normalized_meaning: str,
                              category: str = None, corrected_by: str = None) -> bool:
        """HITL closed-loop: when user corrects slang, update slang_dict and
        mark annotation_log as synced. Caller should re-embed to Milvus.

        Returns True if the slang_dict row was inserted/updated.
        """
        self.insert_slang({
            "slang": slang,
            "normalized_meaning": normalized_meaning,
            "category": category,
            "source": "manual",
            "status": "active",
        })
        # Mark pending annotations as synced
        with self.cursor() as c:
            c.execute(
                """UPDATE annotation_log SET synced=1
                   WHERE target_type='slang' AND field_name='normalized_meaning'
                   AND new_value=%s AND synced=0""",
                (normalized_meaning,),
            )
        logger.info(f"HITL slang correction synced: '{slang}' → '{normalized_meaning}'")
        return True

    def sync_classification_correction(self, raw_data_id: int, intent_label: str,
                                       sub_label: str = "", corrected_by: str = None) -> bool:
        """HITL closed-loop: when user corrects classification, update
        analysis_results and mark annotation_log as synced.
        """
        with self.cursor() as c:
            c.execute(
                """UPDATE analysis_results
                   SET intent_label=%s, sub_label=%s, classification_method='manual'
                   WHERE raw_data_id=%s""",
                (intent_label, sub_label, raw_data_id),
            )
            c.execute(
                """UPDATE annotation_log SET synced=1
                   WHERE target_type='classification' AND target_id=%s AND synced=0""",
                (raw_data_id,),
            )
        logger.info(f"HITL classification correction synced for raw_id={raw_data_id}")
        return True

    def get_pending_annotations(self) -> list[dict]:
        """Get unsynced annotations for batch processing."""
        with self.cursor() as c:
            c.execute("SELECT * FROM annotation_log WHERE synced=0 ORDER BY created_at")
            return c.fetchall()

    # ------------------------------------------------------------------
    # Stats for dashboard
    # ------------------------------------------------------------------

    def daily_stats(self) -> dict:
        with self.cursor() as c:
            c.execute("SELECT COUNT(*) as cnt FROM raw_data WHERE DATE(collected_at) = CURDATE()")
            today_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM raw_data WHERE status IN ('pending','cleaned')")
            pending_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM raw_data WHERE priority IN ('high','critical') AND status != 'discarded'")
            high_risk_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM entities")
            entity_count = c.fetchone()["cnt"]
            c.execute("SELECT intent_label, COUNT(*) as cnt FROM analysis_results GROUP BY intent_label")
            label_distribution = {r["intent_label"]: r["cnt"] for r in c.fetchall()}
            c.execute("""
                SELECT r.content_raw, r.content, r.source_platform, r.priority,
                       r.collected_at, a.intent_label
                FROM raw_data r
                LEFT JOIN analysis_results a ON r.id = a.raw_data_id
                WHERE r.status != 'discarded'
                ORDER BY r.id DESC
                LIMIT 10
            """)
            recent_items = [dict(row) for row in c.fetchall()]
        return {
            "today_count": today_count,
            "pending_count": pending_count,
            "high_risk_count": high_risk_count,
            "entity_count": entity_count,
            "label_distribution": label_distribution,
            "recent_items": recent_items,
        }


mysql = MySQLStore()
