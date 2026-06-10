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
import re
import threading
from contextlib import contextmanager
from datetime import datetime
from loguru import logger
from config.settings import settings


RAW_STATUSES = {
    "RAW_COLLECTED",
    "CLEANED",
    "ANALYZING",
    "SCREENED",
    "ANALYZED",
    "FAILED",
    "DISCARDED",
}

RAW_PENDING_STATUSES = ("RAW_COLLECTED", "CLEANED")


class MySQLStore:
    """Manages all MySQL CRUD operations."""

    def __init__(self):
        self._local = threading.local()

    @property
    def conn(self):
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
            conn = pymysql.connect(
                host=settings.mysql_host,
                port=settings.mysql_port,
                user=settings.mysql_user,
                password=settings.mysql_password,
                database=settings.mysql_database,
                charset="utf8mb4",
                connect_timeout=15,
                read_timeout=120,
                write_timeout=60,
                autocommit=False,
                cursorclass=pymysql.cursors.DictCursor)
            self._local.conn = conn
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
            raise
        finally:
            c.close()

    def reconnect(self):
        """强制断开并重新连接 MySQL（大量写入后使用）。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        self._local.conn = None

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
            similar_intel_ids JSON,
            analysis_status VARCHAR(32) DEFAULT 'CLASSIFIED',
            version INT DEFAULT 1,
            is_latest TINYINT DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_raw(raw_id),
            INDEX idx_risk(risk_label, risk_sub_label),
            INDEX idx_level(risk_level),
            INDEX idx_latest(raw_id, is_latest)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        -- Add columns if table already exists (idempotent migration)
        """

        ddl2 = """
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
            id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
            term VARCHAR(128) NOT NULL UNIQUE COMMENT '黑话原词或候选词',
            normalized_meaning TEXT NOT NULL COMMENT '标准释义；候选状态下为模型建议释义',
            risk_category VARCHAR(64) COMMENT '关联风险分类',
            examples JSON COMMENT '示例用法JSON数组',
            source VARCHAR(64) COMMENT '来源：manual人工、seed种子、llm_candidate大模型发现、embedding_candidate向量发现',
            confidence DECIMAL(5,4) DEFAULT 1.0 COMMENT '模型或人工确认置信度',
            status VARCHAR(32) DEFAULT 'active' COMMENT '状态：active正式词典、candidate待审核、rejected已忽略',
            embedding_id VARCHAR(128) COMMENT '关联Milvus向量主键',
            candidate_raw_id BIGINT COMMENT '首次发现该候选黑话的原始情报ID',
            candidate_evidence TEXT COMMENT '触发候选判断的原文证据片段',
            candidate_reason TEXT COMMENT '模型判断为疑似黑话的原因',
            created_by VARCHAR(64) COMMENT '创建人或系统来源',
            reviewed_by VARCHAR(64) COMMENT '审核人',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
            INDEX idx_term(term),
            INDEX idx_category(risk_category),
            INDEX idx_status(status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='黑灰产黑话词典与候选黑话池';

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

        -- LOG layer: async analysis job queue
        CREATE TABLE IF NOT EXISTS analysis_job (
            job_id VARCHAR(64) PRIMARY KEY,
            raw_id BIGINT,
            input_text MEDIUMTEXT NOT NULL,
            platform VARCHAR(32) DEFAULT 'unknown',
            status VARCHAR(16) DEFAULT 'pending',
            progress INT DEFAULT 0,
            current_step VARCHAR(64),
            result_analysis_id BIGINT,
            error_message TEXT,
            options JSON,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            started_at DATETIME,
            finished_at DATETIME,
            INDEX idx_raw(raw_id),
            INDEX idx_status(status),
            INDEX idx_created(created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """

        # Execute DDL block 1: ods_raw_intel, dwd_clean_intel, dwd_intel_analysis
        with self.cursor() as c:
            for stmt in ddl.split(";"):
                lines = [l for l in stmt.split("\n")
                        if not l.strip().startswith("--")]
                stmt_clean = "\n".join(lines).strip()
                if stmt_clean:
                    c.execute(stmt_clean)

        # Idempotent migration: add version/is_latest if missing (table may pre-exist)
        try:
            with self.cursor() as c:
                c.execute(
                    "ALTER TABLE dwd_intel_analysis "
                    "ADD COLUMN version INT DEFAULT 1, "
                    "ADD COLUMN is_latest TINYINT DEFAULT 1"
                )
        except Exception:
            pass

        # Execute DDL block 2: dwd_entity, dim_slang_dict, ads, logs, jobs
        with self.cursor() as c:
            for stmt in ddl2.split(";"):
                lines = [l for l in stmt.split("\n")
                        if not l.strip().startswith("--")]
                stmt_clean = "\n".join(lines).strip()
                if stmt_clean:
                    c.execute(stmt_clean)
        self._ensure_schema_columns()
        logger.info("MySQL tables initialized (10-table ODS/DWD/DIM/ADS schema)")

    def _ensure_schema_columns(self):
        """Add columns that may be missing in older local databases."""
        migrations = [
            ("annotation_log", "target_type", "ALTER TABLE annotation_log ADD COLUMN target_type VARCHAR(32) NOT NULL DEFAULT 'other' COMMENT '标注对象类型：slang、classification、entity'"),
            ("annotation_log", "target_id", "ALTER TABLE annotation_log ADD COLUMN target_id BIGINT NOT NULL DEFAULT 0 COMMENT '标注对象ID'"),
            ("annotation_log", "synced", "ALTER TABLE annotation_log ADD COLUMN synced TINYINT DEFAULT 0"),
            ("agent_report", "training_sample", "ALTER TABLE agent_report ADD COLUMN training_sample JSON"),
            ("dwd_intel_analysis", "version", "ALTER TABLE dwd_intel_analysis ADD COLUMN version INT DEFAULT 1"),
            ("dwd_intel_analysis", "is_latest", "ALTER TABLE dwd_intel_analysis ADD COLUMN is_latest TINYINT DEFAULT 1"),
            ("dwd_intel_analysis", "similar_intel_ids", "ALTER TABLE dwd_intel_analysis ADD COLUMN similar_intel_ids JSON COMMENT '历史相似情报ID与相似度JSON'"),
            ("dim_slang_dict", "candidate_raw_id", "ALTER TABLE dim_slang_dict ADD COLUMN candidate_raw_id BIGINT COMMENT '首次发现该候选黑话的原始情报ID'"),
            ("dim_slang_dict", "candidate_evidence", "ALTER TABLE dim_slang_dict ADD COLUMN candidate_evidence TEXT COMMENT '触发候选判断的原文证据片段'"),
            ("dim_slang_dict", "candidate_reason", "ALTER TABLE dim_slang_dict ADD COLUMN candidate_reason TEXT COMMENT '模型判断为疑似黑话的原因'")]
        with self.cursor() as c:
            for table, column, sql in migrations:
                c.execute(
                    """SELECT COUNT(*) AS cnt
                       FROM INFORMATION_SCHEMA.COLUMNS
                       WHERE TABLE_SCHEMA=DATABASE()
                         AND TABLE_NAME=%s
                         AND COLUMN_NAME=%s""",
                    (table, column))
                if not c.fetchone()["cnt"]:
                    c.execute(sql)
            try:
                c.execute(
                    """UPDATE annotation_log
                       SET target_id=COALESCE(NULLIF(target_id, 0), raw_data_id),
                           target_type=COALESCE(NULLIF(target_type, ''), 'other')
                       WHERE raw_data_id IS NOT NULL"""
                )
            except Exception as exc:
                logger.debug(f"Annotation legacy backfill skipped: {exc}")
            c.execute("ALTER TABLE dim_slang_dict COMMENT='黑灰产黑话词典与候选黑话池'")
            comment_migrations = [
                "ALTER TABLE dim_slang_dict MODIFY COLUMN id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN term VARCHAR(128) NOT NULL COMMENT '黑话原词或候选词'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN normalized_meaning TEXT NOT NULL COMMENT '标准释义；候选状态下为模型建议释义'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN risk_category VARCHAR(64) COMMENT '关联风险分类'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN examples JSON COMMENT '示例用法JSON数组'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN source VARCHAR(64) COMMENT '来源：manual人工、seed种子、llm_candidate大模型发现、embedding_candidate向量发现'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN confidence DECIMAL(5,4) DEFAULT 1.0 COMMENT '模型或人工确认置信度'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN status VARCHAR(32) DEFAULT 'active' COMMENT '状态：active正式词典、candidate待审核、rejected已忽略'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN embedding_id VARCHAR(128) COMMENT '关联Milvus向量主键'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN created_by VARCHAR(64) COMMENT '创建人或系统来源'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN reviewed_by VARCHAR(64) COMMENT '审核人'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'",
                "ALTER TABLE dim_slang_dict MODIFY COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'"]
            for sql in comment_migrations:
                try:
                    c.execute(sql)
                except Exception as exc:
                    logger.debug(f"Column comment migration skipped: {exc}")
        self._ensure_schema_comments()

    def _ensure_schema_comments(self):
        """Keep local MySQL schema readable in Chinese for demos and handoff."""
        table_comments = [
            ("ods_raw_intel", "原始情报表：保存采集或人工导入的原始文本与来源信息"),
            ("dwd_clean_intel", "清洗情报表：保存去噪、OCR/ASR融合、去重后的文本"),
            ("dwd_intel_analysis", "情报研判结果表：保存风险分类、证据片段和版本状态"),
            ("dwd_entity", "结构化线索表：保存账号、联系方式、链接、黑话、工具等实体"),
            ("dwd_entity_relation", "线索关系表：保存实体之间的共现和推断关系"),
            ("dim_slang_dict", "黑灰产黑话词典与候选黑话池"),
            ("ads_risk_case", "风险案件聚合表：保存团伙或案件级研判结果"),
            ("agent_report", "Agent研判摘要表：保存摘要、证据、建议和图谱结果"),
            ("annotation_log", "人工反馈日志表：保存人工修正和回流状态"),
            ("analysis_job", "异步研判任务表：保存后台任务进度和结果索引")]
        column_comments = [
            "ALTER TABLE ods_raw_intel MODIFY COLUMN id BIGINT NOT NULL AUTO_INCREMENT COMMENT '原始情报ID'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN source_platform VARCHAR(32) NOT NULL COMMENT '来源平台，如weibo、tieba、zhihu'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN source_channel VARCHAR(128) COMMENT '来源频道、群组、贴吧或社区名称'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN source_url VARCHAR(1024) COMMENT '原始情报链接'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN source_keyword VARCHAR(128) COMMENT '采集命中的关键词'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN author_id VARCHAR(128) COMMENT '发布者账号ID'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN author_name VARCHAR(256) COMMENT '发布者昵称'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN publish_time DATETIME COMMENT '原始发布时间'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN collect_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '采集或导入时间'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN content_type VARCHAR(32) DEFAULT 'text' COMMENT '内容类型：text、image、video、audio'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN content_raw MEDIUMTEXT NOT NULL COMMENT '原始文本内容'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN media_urls JSON COMMENT '图片、音频、视频等媒体地址JSON'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN raw_status VARCHAR(32) DEFAULT 'RAW_COLLECTED' COMMENT '原始情报处理状态'",
            "ALTER TABLE ods_raw_intel MODIFY COLUMN metadata JSON COMMENT '采集侧附加元数据JSON'",

            "ALTER TABLE dwd_clean_intel MODIFY COLUMN id BIGINT NOT NULL AUTO_INCREMENT COMMENT '清洗记录ID'",
            "ALTER TABLE dwd_clean_intel MODIFY COLUMN raw_id BIGINT NOT NULL COMMENT '关联原始情报ID'",
            "ALTER TABLE dwd_clean_intel MODIFY COLUMN clean_text MEDIUMTEXT COMMENT '清洗后的正文'",
            "ALTER TABLE dwd_clean_intel MODIFY COLUMN ocr_text MEDIUMTEXT COMMENT '图片OCR识别文本'",
            "ALTER TABLE dwd_clean_intel MODIFY COLUMN asr_text MEDIUMTEXT COMMENT '音频ASR转写文本'",
            "ALTER TABLE dwd_clean_intel MODIFY COLUMN merged_text MEDIUMTEXT COMMENT '融合后的最终研判文本'",
            "ALTER TABLE dwd_clean_intel MODIFY COLUMN simhash VARCHAR(64) COMMENT 'SimHash指纹，用于近重复识别'",
            "ALTER TABLE dwd_clean_intel MODIFY COLUMN noise_score DECIMAL(5,4) DEFAULT 0 COMMENT '噪声分数，越高越像无效内容'",
            "ALTER TABLE dwd_clean_intel MODIFY COLUMN priority VARCHAR(16) DEFAULT 'normal' COMMENT '处理优先级'",
            "ALTER TABLE dwd_clean_intel MODIFY COLUMN clean_status VARCHAR(32) DEFAULT 'CLEANED' COMMENT '清洗状态'",

            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN id BIGINT NOT NULL AUTO_INCREMENT COMMENT '研判结果ID'",
            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN raw_id BIGINT NOT NULL COMMENT '关联原始情报ID'",
            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN risk_label VARCHAR(64) COMMENT '风险大类'",
            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN risk_sub_label VARCHAR(128) COMMENT '风险细分类型'",
            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN risk_score DECIMAL(5,4) COMMENT '综合风险分，范围0到1'",
            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN risk_level VARCHAR(16) COMMENT '风险等级：low、normal、high、critical'",
            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN classification_method VARCHAR(64) COMMENT '分类来源：keyword、roberta、llm、degraded'",
            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN evidence_spans JSON COMMENT '风险证据片段JSON'",
            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN similar_intel_ids JSON COMMENT '历史相似情报ID与相似度JSON'",
            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN analysis_status VARCHAR(32) DEFAULT 'CLASSIFIED' COMMENT '研判状态'",
            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN version INT DEFAULT 1 COMMENT '同一情报的研判版本号'",
            "ALTER TABLE dwd_intel_analysis MODIFY COLUMN is_latest TINYINT DEFAULT 1 COMMENT '是否为最新研判结果'",

            "ALTER TABLE dwd_entity MODIFY COLUMN id BIGINT NOT NULL AUTO_INCREMENT COMMENT '线索ID'",
            "ALTER TABLE dwd_entity MODIFY COLUMN raw_id BIGINT NOT NULL COMMENT '关联原始情报ID'",
            "ALTER TABLE dwd_entity MODIFY COLUMN entity_type VARCHAR(64) NOT NULL COMMENT '线索类型，如wechat、phone、url、slang、tool'",
            "ALTER TABLE dwd_entity MODIFY COLUMN entity_value TEXT NOT NULL COMMENT '线索原始值'",
            "ALTER TABLE dwd_entity MODIFY COLUMN normalized_value TEXT COMMENT '归一化后的线索值'",
            "ALTER TABLE dwd_entity MODIFY COLUMN extract_method VARCHAR(32) COMMENT '抽取方式：regex、dict、embedding、llm'",
            "ALTER TABLE dwd_entity MODIFY COLUMN confidence DECIMAL(5,4) COMMENT '抽取置信度'",
            "ALTER TABLE dwd_entity MODIFY COLUMN context TEXT COMMENT '命中线索附近上下文'",
            "ALTER TABLE dwd_entity MODIFY COLUMN first_seen DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '首次发现时间'",

            "ALTER TABLE annotation_log MODIFY COLUMN id BIGINT NOT NULL AUTO_INCREMENT COMMENT '标注记录ID'",
            "ALTER TABLE annotation_log MODIFY COLUMN target_type VARCHAR(32) NOT NULL COMMENT '标注对象类型：slang、classification、entity'",
            "ALTER TABLE annotation_log MODIFY COLUMN target_id BIGINT NOT NULL COMMENT '标注对象ID'",
            "ALTER TABLE annotation_log MODIFY COLUMN field_name VARCHAR(64) NOT NULL COMMENT '被修正字段或黑话词条'",
            "ALTER TABLE annotation_log MODIFY COLUMN old_value TEXT COMMENT '修正前内容'",
            "ALTER TABLE annotation_log MODIFY COLUMN new_value TEXT COMMENT '修正后内容'",
            "ALTER TABLE annotation_log MODIFY COLUMN annotator VARCHAR(64) COMMENT '标注人'",
            "ALTER TABLE annotation_log MODIFY COLUMN reason VARCHAR(256) COMMENT '修正原因'",
            "ALTER TABLE annotation_log MODIFY COLUMN synced TINYINT DEFAULT 0 COMMENT '是否已回流到词典或研判结果'",

            "ALTER TABLE analysis_job MODIFY COLUMN job_id VARCHAR(64) NOT NULL COMMENT '异步任务ID'",
            "ALTER TABLE analysis_job MODIFY COLUMN raw_id BIGINT COMMENT '关联原始情报ID'",
            "ALTER TABLE analysis_job MODIFY COLUMN input_text MEDIUMTEXT NOT NULL COMMENT '任务输入文本'",
            "ALTER TABLE analysis_job MODIFY COLUMN platform VARCHAR(32) DEFAULT 'unknown' COMMENT '来源平台'",
            "ALTER TABLE analysis_job MODIFY COLUMN status VARCHAR(16) DEFAULT 'pending' COMMENT '任务状态：pending、running、success、failed'",
            "ALTER TABLE analysis_job MODIFY COLUMN progress INT DEFAULT 0 COMMENT '任务进度百分比'",
            "ALTER TABLE analysis_job MODIFY COLUMN current_step VARCHAR(64) COMMENT '当前执行步骤'",
            "ALTER TABLE analysis_job MODIFY COLUMN result_analysis_id BIGINT COMMENT '成功后关联的研判结果ID'",
            "ALTER TABLE analysis_job MODIFY COLUMN error_message TEXT COMMENT '失败原因'",
            "ALTER TABLE analysis_job MODIFY COLUMN options JSON COMMENT '任务执行选项JSON'"]
        column_comments.append(
            "ALTER TABLE ods_raw_intel MODIFY COLUMN raw_status VARCHAR(32) "
            "DEFAULT 'RAW_COLLECTED' COMMENT "
            "'处理状态：RAW_COLLECTED待研判、CLEANED已清洗、"
            "ANALYZING研判中、SCREENED已初筛、ANALYZED已研判、FAILED研判失败、DISCARDED已丢弃'"
        )
        with self.cursor() as c:
            for table, comment in table_comments:
                try:
                    c.execute(f"ALTER TABLE {table} COMMENT=%s", (comment))
                except Exception as exc:
                    logger.debug(f"Table comment migration skipped [{table}]: {exc}")
            for sql in column_comments:
                try:
                    c.execute(sql)
                except Exception as exc:
                    logger.debug(f"Column comment migration skipped: {exc}")

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
        item.setdefault("source_platform", item.get("platform", "unknown"))
        item.setdefault("source_channel", item.get("source_channel"))
        item.setdefault("source_url", item.get("source_url"))
        item.setdefault("source_keyword", item.get("source_keyword"))
        item.setdefault("author_id", item.get("author_uid"))
        item.setdefault("author_name", item.get("author_username"))
        item.setdefault("publish_time", item.get("publish_time") or item.get("collected_at"))
        item.setdefault("collect_time", item.get("collected_at"))
        item.setdefault("content_type", "text")
        item.setdefault("content_raw", item.get("content") or "")
        media_urls = item.get("media_urls", [])
        item["media_urls"] = media_urls if isinstance(media_urls, str) else _json.dumps(media_urls, ensure_ascii=False)
        item.setdefault("media_hash", item.get("image_hash"))
        item.setdefault("crawl_batch_id", item.get("crawl_batch_id"))
        item.setdefault("raw_status", item.get("status", "RAW_COLLECTED"))
        item["raw_status"] = self._normalize_raw_status(item["raw_status"])
        metadata = item.get("metadata", {})
        item["metadata"] = metadata if isinstance(metadata, str) else _json.dumps(metadata, ensure_ascii=False)
        with self.cursor() as c:
            c.execute(sql, item)
            return c.lastrowid

    @staticmethod
    def _normalize_raw_status(status: str | None) -> str:
        """Normalize legacy/lowercase statuses into the raw intelligence lifecycle."""
        if not status:
            return "RAW_COLLECTED"
        value = str(status).strip()
        legacy_map = {
            "pending": "RAW_COLLECTED",
            "raw": "RAW_COLLECTED",
            "cleaned": "CLEANED",
            "running": "ANALYZING",
            "analyzing": "ANALYZING",
            "screened": "SCREENED",
            "initial_screened": "SCREENED",
            "success": "ANALYZED",
            "analyzed": "ANALYZED",
            "failed": "FAILED",
            "discarded": "DISCARDED",
        }
        normalized = legacy_map.get(value.lower(), value.upper())
        return normalized if normalized in RAW_STATUSES else "RAW_COLLECTED"

    def update_raw_status(self, raw_id: int, status: str,
                          clean_text: str = None, simhash: str = None,
                          noise_score: float = None, clean_reason: str = None):
        """Update ods_raw_intel status. If clean_text/simhash provided,
        also upsert into dwd_clean_intel."""
        if not raw_id:
            return
        status = self._normalize_raw_status(status)
        with self.cursor() as c:
            c.execute("UPDATE ods_raw_intel SET raw_status=%s WHERE id=%s",
                      (status, raw_id))
        if clean_text or simhash:
            self.insert_clean_intel(
                raw_id,
                clean_text,
                simhash,
                noise_score=noise_score,
                clean_status=status,
                clean_reason=clean_reason,
            )

    def update_raw_metadata(self, raw_id: int, updates: dict):
        """Merge small decision fields into ods_raw_intel.metadata."""
        if not raw_id or not updates:
            return
        pairs = []
        params = []
        for key, value in updates.items():
            if not re.fullmatch(r"[A-Za-z0-9_]+", str(key)):
                continue
            pairs.append(f"'$.{key}', %s")
            params.append(value)
        if not pairs:
            return
        params.append(raw_id)
        with self.cursor() as c:
            c.execute(
                f"""UPDATE ods_raw_intel
                    SET metadata=JSON_SET(COALESCE(metadata, JSON_OBJECT()), {', '.join(pairs)})
                    WHERE id=%s""",
                params,
            )

    def mark_screen_decision(self, raw_id: int, decision: str, reason: str,
                             risk_score: float = None):
        """Persist the first-pass screening decision without deleting raw data."""
        updates = {
            "screen_decision": decision,
            "screen_reason": (reason or "")[:500],
            "screened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if risk_score is not None:
            updates["screen_risk_score"] = float(risk_score)
        self.update_raw_metadata(raw_id, updates)

    def mark_raw_analyzing(self, raw_id: int):
        """Mark a raw intelligence row as being actively analyzed."""
        if not raw_id:
            return
        self.update_raw_status(raw_id, "ANALYZING")

    def mark_raw_failed(self, raw_id: int, error_message: str = ""):
        """Mark analysis failure and keep a small audit note in metadata."""
        if not raw_id:
            return
        failed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_text = (error_message or "")[:1000]
        with self.cursor() as c:
            c.execute(
                """UPDATE ods_raw_intel
                   SET raw_status='FAILED',
                       metadata=JSON_SET(
                           COALESCE(metadata, JSON_OBJECT()),
                           '$.last_error', %s,
                           '$.failed_at', %s
                       )
                   WHERE id=%s""",
                (error_text, failed_at, raw_id))

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
                f"SELECT * FROM ods_raw_intel {clause} ORDER BY collect_time DESC LIMIT %s OFFSET %s",
                params)
            rows = c.fetchall()
            # Map field names for backward compat
            for r in rows:
                self._normalize_raw_row(r)
            return rows

    @staticmethod
    def _normalize_raw_row(row: dict) -> dict:
        row.setdefault("content", row.get("content_raw"))
        row.setdefault("author_uid", row.get("author_id"))
        row.setdefault("author_username", row.get("author_name"))
        row.setdefault("platform", row.get("source_platform"))
        row.setdefault("collected_at", row.get("collect_time"))
        row.setdefault("status", row.get("raw_status"))
        row.setdefault("image_hash", row.get("media_hash"))
        return row

    def get_raw_by_id(self, raw_id: int) -> dict | None:
        """Return one raw intelligence row by primary key."""
        with self.cursor() as c:
            c.execute("SELECT * FROM ods_raw_intel WHERE id=%s", (raw_id,))
            row = c.fetchone()
            return self._normalize_raw_row(row) if row else None

    def get_preferred_analysis_text(self, raw_id: int, fallback: str = "") -> str:
        """Return the text that should be sent to the Agent.

        Priority: merged_text > clean_text > content_raw/fallback.
        """
        with self.cursor() as c:
            c.execute(
                "SELECT merged_text, clean_text FROM dwd_clean_intel WHERE raw_id=%s",
                (raw_id))
            clean = c.fetchone()
            if clean:
                text = clean.get("merged_text") or clean.get("clean_text")
                if text:
                    return text
            c.execute("SELECT content_raw FROM ods_raw_intel WHERE id=%s", (raw_id))
            raw = c.fetchone()
            if raw and raw.get("content_raw"):
                return raw["content_raw"]
            return fallback or ""

    def list_existing_simhashes(self, limit: int = 5000) -> list[str]:
        """返回已清洗条目的 simhash 列表，用于去重比对。"""
        try:
            with self.cursor() as c:
                c.execute(
                    "SELECT simhash FROM dwd_clean_intel "
                    "WHERE simhash IS NOT NULL AND simhash != '' "
                    "ORDER BY id DESC LIMIT %s",
                    (limit,))
                return [r["simhash"] for r in c.fetchall()]
        except Exception:
            return []

    def find_by_simhash(self, simhash: str, limit: int = 5) -> list[dict]:
        with self.cursor() as c:
            c.execute(
                "SELECT ci.*, r.source_platform, r.content_raw "
                "FROM dwd_clean_intel ci "
                "LEFT JOIN ods_raw_intel r ON ci.raw_id = r.id "
                "WHERE ci.simhash=%s LIMIT %s",
                (simhash, limit))
            return c.fetchall()

    # ==================================================================
    # DWD: Clean Intel
    # ==================================================================

    def insert_clean_intel(self, raw_id: int, clean_text: str = None,
                           simhash: str = None, **kwargs):
        """Upsert into dwd_clean_intel."""
        clean_status = kwargs.get("clean_status") or "CLEANED"
        noise_score = kwargs.get("noise_score")
        clean_reason = kwargs.get("clean_reason")
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
                if clean_status:
                    sets.append("clean_status=%s"); params.append(clean_status)
                if noise_score is not None:
                    sets.append("noise_score=%s"); params.append(float(noise_score))
                if clean_reason is not None:
                    sets.append("clean_reason=%s"); params.append(str(clean_reason)[:256])
                if sets:
                    params.append(raw_id)
                    c.execute(f"UPDATE dwd_clean_intel SET {', '.join(sets)} WHERE raw_id=%s", params)
                return existing["id"]
            else:
                c.execute(
                    """INSERT INTO dwd_clean_intel
                       (raw_id, clean_text, simhash, noise_score, clean_status, clean_reason)
                    VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        raw_id,
                        clean_text,
                        simhash,
                        float(noise_score) if noise_score is not None else 0,
                        clean_status,
                        str(clean_reason)[:256] if clean_reason is not None else None,
                    ))
                return c.lastrowid

    # ==================================================================
    # DWD: Analysis
    # ==================================================================

    def insert_analysis(self, result: dict):
        """Insert into dwd_intel_analysis with version tracking.

        If a previous analysis exists for this raw_id, marks it is_latest=0
        and creates a new record with version=N+1, is_latest=1.
        """
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
        if "similar_intel_ids" in result:
            val = result["similar_intel_ids"]
            if not isinstance(val, str):
                result["similar_intel_ids"] = _json.dumps(val, ensure_ascii=False)
        else:
            result["similar_intel_ids"] = "[]"

        raw_id = result["raw_id"]

        with self.cursor() as c:
            # Find latest version for this raw_id
            c.execute(
                "SELECT MAX(version) as max_ver FROM dwd_intel_analysis WHERE raw_id=%s",
                (raw_id))
            row = c.fetchone()
            max_ver = row["max_ver"] if row and row["max_ver"] else 0
            next_ver = max_ver + 1

            # Mark old versions as not latest
            if max_ver > 0:
                c.execute(
                    "UPDATE dwd_intel_analysis SET is_latest=0 WHERE raw_id=%s",
                    (raw_id))

            # Insert new version
            sql = """INSERT INTO dwd_intel_analysis
                (raw_id, clean_id, risk_label, risk_sub_label, risk_score, risk_level,
                 classification_method, evidence_spans, similar_intel_ids, analysis_status,
                 version, is_latest)
            VALUES (%(raw_id)s, %(clean_id)s, %(risk_label)s, %(risk_sub_label)s,
                    %(risk_score)s, %(risk_level)s, %(classification_method)s,
                    %(evidence_spans)s, %(similar_intel_ids)s, %(analysis_status)s,
                    %(version)s, 1)"""
            result["version"] = next_ver
            try:
                c.execute(sql, result)
            except pymysql.err.OperationalError as exc:
                if exc.args and exc.args[0] == 1054 and "similar_intel_ids" in str(exc):
                    c.execute(
                        "ALTER TABLE dwd_intel_analysis "
                        "ADD COLUMN similar_intel_ids JSON COMMENT '历史相似情报ID与相似度JSON'"
                    )
                    c.execute(sql, result)
                else:
                    raise
            analysis_id = c.lastrowid
            logger.info(f"Analysis saved: raw_id={raw_id} version={next_ver}")
            return analysis_id

    def get_analysis_history(self, raw_id: int) -> list[dict]:
        """Return all analysis versions for a raw_id, newest first."""
        with self.cursor() as c:
            c.execute(
                "SELECT * FROM dwd_intel_analysis WHERE raw_id=%s ORDER BY version DESC",
                (raw_id))
            return c.fetchall()

    @staticmethod
    def _similar_raw_id(entry) -> int | None:
        """Extract raw_id from a similar-intel entry.

        Accepts both the new shape:
            {"raw_id": 123, "similarity": 0.91, "distance": 0.09}
        and the old shape:
            123
        """
        if isinstance(entry, dict):
            value = entry.get("raw_id") or entry.get("raw_data_id")
        else:
            value = entry
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def list_similar_intel_details(self, similar_entries: list) -> list[dict]:
        """Load UI-friendly summaries for similar historical intel IDs."""
        ids: list[int] = []
        meta_by_id: dict[int, dict] = {}
        for entry in similar_entries or []:
            raw_id = self._similar_raw_id(entry)
            if raw_id is None or raw_id in meta_by_id:
                continue
            ids.append(raw_id)
            meta_by_id[raw_id] = entry if isinstance(entry, dict) else {"raw_id": raw_id}

        if not ids:
            return []

        placeholders = ", ".join(["%s"] * len(ids))
        with self.cursor() as c:
            c.execute(
                f"""SELECT r.id, r.source_platform, r.source_channel, r.content_raw,
                           r.collect_time, r.raw_status,
                           a.risk_label, a.risk_sub_label, a.risk_score,
                           a.risk_level, a.classification_method, a.created_at AS analyzed_at
                    FROM ods_raw_intel r
                    LEFT JOIN dwd_intel_analysis a
                      ON r.id = a.raw_id AND a.is_latest=1
                    WHERE r.id IN ({placeholders})""",
                ids,
            )
            rows = c.fetchall()

        by_id = {int(row["id"]): row for row in rows}
        ordered = []
        for raw_id in ids:
            row = by_id.get(raw_id)
            if not row:
                continue
            meta = meta_by_id.get(raw_id, {})
            content = row.get("content_raw") or ""
            row = dict(row)
            row["content_preview"] = content[:140]
            row["similarity"] = meta.get("similarity")
            row["distance"] = meta.get("distance")
            ordered.append(row)
        return ordered

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
            return c.lastrowid

    def delete_entities_for_raw(self, raw_id: int):
        """Remove previous extracted entities for a raw item before re-analysis."""
        with self.cursor() as c:
            c.execute("DELETE FROM dwd_entity WHERE raw_id=%s", (raw_id))

    def find_entity(self, entity_type: str, value: str) -> list[dict]:
        with self.cursor() as c:
            c.execute(
                "SELECT * FROM dwd_entity WHERE entity_type=%s AND entity_value=%s",
                (entity_type, value))
            return c.fetchall()

    def find_entities_by_raw(self, raw_id: int) -> list[dict]:
        with self.cursor() as c:
            c.execute("SELECT * FROM dwd_entity WHERE raw_id=%s", (raw_id))
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
                kwargs.get("confidence", 1.0)))

    def get_entity_relations(self, entity_id: int) -> list[dict]:
        with self.cursor() as c:
            c.execute(
                """SELECT * FROM dwd_entity_relation
                   WHERE src_entity_id=%s OR dst_entity_id=%s""",
                (entity_id, entity_id))
            return c.fetchall()

    # ==================================================================
    # DIM: Slang Dictionary
    # ==================================================================

    def insert_slang(self, slang: dict):
        """Insert or update dim_slang_dict."""
        sql = """INSERT INTO dim_slang_dict
            (term, normalized_meaning, risk_category, examples, source,
             confidence, status, embedding_id, candidate_raw_id,
             candidate_evidence, candidate_reason, created_by, reviewed_by)
        VALUES (%(term)s, %(normalized_meaning)s, %(risk_category)s, %(examples)s,
                %(source)s, %(confidence)s, %(status)s, %(embedding_id)s,
                %(candidate_raw_id)s, %(candidate_evidence)s, %(candidate_reason)s,
                %(created_by)s, %(reviewed_by)s)
        ON DUPLICATE KEY UPDATE
            normalized_meaning=VALUES(normalized_meaning),
            risk_category=VALUES(risk_category),
            examples=VALUES(examples),
            source=VALUES(source),
            confidence=VALUES(confidence),
            status=VALUES(status),
            embedding_id=VALUES(embedding_id),
            candidate_raw_id=VALUES(candidate_raw_id),
            candidate_evidence=VALUES(candidate_evidence),
            candidate_reason=VALUES(candidate_reason),
            reviewed_by=VALUES(reviewed_by)"""
        slang.setdefault("term", slang.get("slang"))
        slang.setdefault("normalized_meaning", slang.get("normalized_meaning") or "待人工确认")
        slang.setdefault("risk_category", slang.get("category"))
        slang.setdefault("examples", slang.get("examples",
            _json.dumps([], ensure_ascii=False)))
        slang.setdefault("source", slang.get("source", "manual"))
        slang.setdefault("confidence", slang.get("confidence", 1.0))
        slang.setdefault("status", slang.get("status", "active"))
        slang.setdefault("embedding_id", slang.get("embedding_id"))
        slang.setdefault("candidate_raw_id", slang.get("raw_id"))
        slang.setdefault("candidate_evidence", slang.get("evidence"))
        slang.setdefault("candidate_reason", slang.get("reason"))
        slang.setdefault("created_by", slang.get("created_by"))
        slang.setdefault("reviewed_by", slang.get("reviewed_by") or slang.get("confirmed_by"))
        with self.cursor() as c:
            c.execute(sql, slang)

    def list_slang(self, status: str | None = "active") -> list[dict]:
        with self.cursor() as c:
            if status is None:
                c.execute("SELECT * FROM dim_slang_dict ORDER BY updated_at DESC")
            else:
                c.execute(
                    "SELECT * FROM dim_slang_dict WHERE status=%s ORDER BY updated_at DESC",
                    (status))
            rows = c.fetchall()
            for r in rows:
                r.setdefault("slang", r.get("term"))
                r.setdefault("category", r.get("risk_category"))
                r.setdefault("normalized_meaning", r.get("normalized_meaning"))
            return rows

    def upsert_slang_candidate(self, candidate: dict):
        """Persist a model-discovered slang candidate for human review."""
        term = (candidate.get("term") or candidate.get("slang") or "").strip()
        if not term:
            return None
        with self.cursor() as c:
            c.execute(
                "SELECT status FROM dim_slang_dict WHERE term=%s LIMIT 1",
                (term))
            existing = c.fetchone()
        if existing and existing.get("status") == "active":
            return None

        self.insert_slang({
            "term": term,
            "normalized_meaning": candidate.get("suggested_meaning")
                                  or candidate.get("normalized_meaning")
                                  or "待人工确认",
            "risk_category": candidate.get("risk_category"),
            "examples": _json.dumps([candidate.get("evidence", "")], ensure_ascii=False),
            "source": candidate.get("source", "llm_candidate"),
            "confidence": candidate.get("confidence", 0.5),
            "status": "candidate",
            "candidate_raw_id": candidate.get("raw_id"),
            "candidate_evidence": candidate.get("evidence"),
            "candidate_reason": candidate.get("reason"),
            "created_by": "agent",
        })
        return term

    def list_slang_candidates(self, raw_id: int = None, limit: int = 100) -> list[dict]:
        """List pending slang candidates. Optionally filter by raw intel ID."""
        with self.cursor() as c:
            if raw_id is None:
                c.execute(
                    """SELECT * FROM dim_slang_dict
                       WHERE status='candidate'
                       ORDER BY updated_at DESC LIMIT %s""",
                    (limit))
            else:
                c.execute(
                    """SELECT * FROM dim_slang_dict
                       WHERE status='candidate' AND candidate_raw_id=%s
                       ORDER BY updated_at DESC LIMIT %s""",
                    (raw_id, limit))
            rows = c.fetchall()
        for row in rows:
            row.setdefault("term", row.get("slang"))
            row.setdefault("suggested_meaning", row.get("normalized_meaning"))
            row.setdefault("evidence", row.get("candidate_evidence"))
            row.setdefault("reason", row.get("candidate_reason"))
        return rows

    def approve_slang_candidate(self, term: str, meaning: str = None,
                                category: str = None, reviewer: str = "analyst") -> bool:
        """Promote a candidate slang term into the active dictionary."""
        with self.cursor() as c:
            c.execute(
                """UPDATE dim_slang_dict
                   SET status='active',
                       normalized_meaning=COALESCE(NULLIF(%s, ''), normalized_meaning),
                       risk_category=COALESCE(NULLIF(%s, ''), risk_category),
                       reviewed_by=%s,
                       updated_at=NOW()
                   WHERE term=%s""",
                (meaning or "", category or "", reviewer, term))
            return c.rowcount > 0

    def reject_slang_candidate(self, term: str, reviewer: str = "analyst",
                               reason: str = None) -> bool:
        """Mark a candidate slang term as rejected without deleting audit evidence."""
        with self.cursor() as c:
            c.execute(
                """UPDATE dim_slang_dict
                   SET status='rejected',
                       reviewed_by=%s,
                       candidate_reason=COALESCE(NULLIF(%s, ''), candidate_reason),
                       updated_at=NOW()
                   WHERE term=%s AND status='candidate'""",
                (reviewer, reason or "", term))
            return c.rowcount > 0

    # ==================================================================
    # ADS: Risk Case
    # ==================================================================

    def upsert_risk_case(self, case_id: str, **kwargs):
        """Insert or update an ads_risk_case."""
        with self.cursor() as c:
            c.execute("SELECT case_id FROM ads_risk_case WHERE case_id=%s", (case_id))
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
                    values)

    def list_risk_cases(self, status: str = "open") -> list[dict]:
        with self.cursor() as c:
            c.execute("SELECT * FROM ads_risk_case WHERE status=%s ORDER BY created_at DESC", (status))
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
            c.execute("SELECT * FROM agent_report WHERE raw_id=%s ORDER BY created_at DESC", (raw_id))
            return c.fetchall()

    # ==================================================================
    # Annotation Log (HITL)
    # ==================================================================

    def log_annotation(self, target_type: str, target_id: int, field_name: str,
                       old_value: str, new_value: str, annotator: str = None,
                       reason: str = None) -> dict:
        """Record a human correction and auto-trigger the feedback loop.

        Returns dict with annotation_id and sync status.
        - slang corrections → updates dim_slang_dict + marks synced
        - classification corrections → updates dwd_intel_analysis + generates training sample
        - entity corrections → updates dwd_entity
        """
        sql = """INSERT INTO annotation_log
            (target_type, target_id, field_name, old_value, new_value, annotator, reason)
        VALUES (%s, %s, %s, %s, %s, %s, %s)"""
        with self.cursor() as c:
            c.execute(sql, (target_type, target_id, field_name, old_value, new_value,
                          annotator, reason))
            annotation_id = c.lastrowid

        result = {"annotation_id": annotation_id, "target_type": target_type, "synced": False}

        try:
            if target_type == "slang":
                result["synced"] = self.sync_slang_correction(
                    slang=field_name,  # field_name carries the slang term
                    normalized_meaning=new_value,
                    corrected_by=annotator)
            elif target_type == "classification":
                result["synced"] = self.sync_classification_correction(
                    raw_data_id=target_id,
                    intent_label=field_name,  # field_name carries the intent_label
                    sub_label=new_value or "",
                    corrected_by=annotator)
                self._generate_training_sample(target_id, field_name, new_value)
            elif target_type == "entity":
                result["synced"] = self.sync_entity_correction(
                    entity_id=target_id,
                    field_name=field_name,
                    new_value=new_value,
                    corrected_by=annotator)
        except Exception as exc:
            logger.warning(f"HITL auto-sync failed for {target_type}: {exc}")
            result["sync_error"] = str(exc)

        return result

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
                   WHERE target_type='slang' AND synced=0
                   AND field_name=%s""",
                (slang))
        logger.info(f"HITL slang correction synced: '{slang}' -> '{normalized_meaning}'")
        return True

    def sync_classification_correction(self, raw_data_id: int, intent_label: str,
                                       sub_label: str = "", corrected_by: str = None) -> bool:
        """Update dwd_intel_analysis and mark annotations as synced."""
        with self.cursor() as c:
            c.execute(
                """UPDATE dwd_intel_analysis
                   SET risk_label=%s, risk_sub_label=%s, classification_method='manual'
                   WHERE raw_id=%s AND is_latest=1""",
                (intent_label, sub_label, raw_data_id))
            c.execute(
                """UPDATE annotation_log SET synced=1
                   WHERE target_type='classification' AND target_id=%s AND synced=0""",
                (raw_data_id))
        logger.info(f"HITL classification correction synced for raw_id={raw_data_id}")
        return True

    def sync_entity_correction(self, entity_id: int, field_name: str,
                               new_value: str, corrected_by: str = None) -> bool:
        """Update dwd_entity and mark annotation as synced."""
        with self.cursor() as c:
            if field_name == "entity_type":
                c.execute(
                    "UPDATE dwd_entity SET entity_type=%s WHERE id=%s",
                    (new_value, entity_id))
            elif field_name == "entity_value":
                c.execute(
                    "UPDATE dwd_entity SET entity_value=%s, normalized_value=%s WHERE id=%s",
                    (new_value, new_value, entity_id))
            elif field_name == "confidence":
                c.execute(
                    "UPDATE dwd_entity SET confidence=%s WHERE id=%s",
                    (float(new_value), entity_id))
            else:
                logger.warning(f"Unknown entity field: {field_name}")
                return False
            c.execute(
                """UPDATE annotation_log SET synced=1
                   WHERE target_type='entity' AND target_id=%s AND field_name=%s AND synced=0""",
                (entity_id, field_name))
        logger.info(f"HITL entity correction synced: entity_id={entity_id} {field_name}={new_value}")
        return True

    def _generate_training_sample(self, raw_id: int, intent_label: str, sub_label: str):
        """Generate a training sample from a human-corrected classification.

        Stores the sample in agent_report.training_sample (not dwd_intel_analysis,
        which has no training_sample column).
        """
        try:
            with self.cursor() as c:
                c.execute(
                    "SELECT clean_text, merged_text FROM dwd_clean_intel WHERE raw_id=%s",
                    (raw_id))
                clean = c.fetchone()
                text = (clean.get("merged_text") or clean.get("clean_text") or "") if clean else ""

            if not text:
                return

            sample = _json.dumps({
                "text": text[:2000],
                "intent_label": intent_label,
                "sub_label": sub_label,
                "source": "manual",
            }, ensure_ascii=False)

            with self.cursor() as c:
                c.execute(
                    """UPDATE agent_report
                       SET training_sample=%s,
                           summary='人工标注修正',
                           generated_by='hitl',
                           created_at=NOW()
                       WHERE raw_id=%s AND report_type='training_sample'""",
                    (sample, raw_id),
                )
                if c.rowcount == 0:
                    c.execute(
                        """INSERT INTO agent_report
                            (raw_id, report_type, title, summary, training_sample, generated_by)
                        VALUES (%s, 'training_sample', 'HITL训练样本', '人工标注修正',
                                %s, 'hitl')""",
                        (raw_id, sample),
                    )
            logger.info(f"Training sample generated for raw_id={raw_id}")
        except Exception as exc:
            logger.warning(f"Training sample generation failed for raw_id={raw_id}: {exc}")

    # ==================================================================
    # Analysis Job Queue (async task system)
    # ==================================================================

    def create_job(self, raw_id: int, input_text: str, platform: str = "unknown",
                   options: dict = None) -> str:
        """Create a new analysis job. Returns job_id (UUID)."""
        import uuid
        job_id = str(uuid.uuid4())[:12]
        with self.cursor() as c:
            c.execute(
                """INSERT INTO analysis_job
                    (job_id, raw_id, input_text, platform, status, progress, options)
                VALUES (%s, %s, %s, %s, 'pending', 0, %s)""",
                (job_id, raw_id, input_text, platform,
                 _json.dumps(options) if options else None))
        logger.debug(f"Job created: {job_id} for raw_id={raw_id}")
        return job_id

    def update_job_status(self, job_id: str, **kwargs):
        """Update job fields: status, progress, current_step, result_analysis_id, error_message."""
        allowed = {"status", "progress", "current_step", "result_analysis_id", "error_message"}
        sets = []
        params = []
        for k, v in kwargs.items():
            if k in allowed:
                sets.append(f"{k}=%s")
                params.append(v)
        if not sets:
            return
        if kwargs.get("status") == "running" and "started_at" not in kwargs:
            sets.append("started_at=NOW()")
        if kwargs.get("status") in ("success", "failed"):
            sets.append("finished_at=NOW()")
        params.append(job_id)
        with self.cursor() as c:
            c.execute(f"UPDATE analysis_job SET {', '.join(sets)} WHERE job_id=%s", params)

    def get_job(self, job_id: str) -> dict | None:
        """Get a single job by ID."""
        with self.cursor() as c:
            c.execute("SELECT * FROM analysis_job WHERE job_id=%s", (job_id))
            return c.fetchone()

    def get_analysis_bundle(self, raw_id: int) -> dict:
        """Load the latest persisted analysis result in UI/API-friendly shape."""
        with self.cursor() as c:
            c.execute(
                """SELECT * FROM dwd_intel_analysis
                   WHERE raw_id=%s AND is_latest=1
                   ORDER BY created_at DESC LIMIT 1""",
                (raw_id))
            analysis = c.fetchone() or {}
            c.execute(
                "SELECT * FROM dwd_entity WHERE raw_id=%s ORDER BY id DESC",
                (raw_id))
            entities = c.fetchall()
            c.execute(
                "SELECT * FROM agent_report WHERE raw_id=%s ORDER BY created_at DESC LIMIT 1",
                (raw_id))
            report = c.fetchone() or {}

        if not analysis:
            return {}

        def _json_load(value, default):
            if value is None:
                return default
            if isinstance(value, (dict, list)):
                return value
            try:
                return _json.loads(value)
            except Exception:
                return default

        return {
            "raw_id": raw_id,
            "clean_text": self.get_preferred_analysis_text(raw_id),
            "risk_label": analysis.get("risk_label", ""),
            "risk_sub_label": analysis.get("risk_sub_label", ""),
            "risk_score": float(analysis.get("risk_score") or 0),
            "risk_level": analysis.get("risk_level", "normal"),
            "classification_method": analysis.get("classification_method", ""),
            "evidence_spans": _json_load(analysis.get("evidence_spans"), []),
            "similar_intel_ids": _json_load(analysis.get("similar_intel_ids"), []),
            "similar_intel": self.list_similar_intel_details(
                _json_load(analysis.get("similar_intel_ids"), [])
            ),
            "entities": [
                {
                    "entity_type": e.get("entity_type"),
                    "entity_value": e.get("entity_value"),
                    "extraction_method": e.get("extract_method"),
                    "confidence": float(e.get("confidence") or 0),
                    "context": e.get("context") or "",
                }
                for e in entities
            ],
            "slang_terms": [
                {
                    "term": e.get("entity_value"),
                    "meaning": e.get("context") or "",
                    "source": e.get("extract_method") or "",
                }
                for e in entities
                if e.get("entity_type") == "slang"
            ],
            "new_slang_candidates": self.list_slang_candidates(raw_id=raw_id),
            "graph_result": _json_load(report.get("graph_json"), {}),
            "agent_summary": report.get("summary", ""),
            "disposal_advice": _json_load(report.get("disposal_advice"), []),
        }

    def list_jobs(self, status: str = None, limit: int = 50) -> list[dict]:
        """List recent jobs, optionally filtered by status."""
        with self.cursor() as c:
            if status:
                c.execute(
                    "SELECT * FROM analysis_job WHERE status=%s ORDER BY created_at DESC LIMIT %s",
                    (status, limit))
            else:
                c.execute(
                    "SELECT * FROM analysis_job ORDER BY created_at DESC LIMIT %s",
                    (limit))
            return c.fetchall()

    def list_unfinished_jobs(self, limit: int = 50) -> list[dict]:
        """List jobs that still need an in-process worker."""
        with self.cursor() as c:
            c.execute(
                """SELECT * FROM analysis_job
                   WHERE status IN ('pending','running')
                   ORDER BY created_at ASC
                   LIMIT %s""",
                (limit,),
            )
            return c.fetchall()

    # ==================================================================
    # Stats for Dashboard
    # ==================================================================

    def daily_stats(self) -> dict:
        with self.cursor() as c:
            c.execute("SELECT COUNT(*) as cnt FROM ods_raw_intel WHERE DATE(collect_time) = CURDATE()")
            today_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM ods_raw_intel WHERE raw_status IN ('RAW_COLLECTED','CLEANED')")
            pending_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM ods_raw_intel WHERE raw_status='ANALYZING'")
            running_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM ods_raw_intel WHERE raw_status='SCREENED'")
            screened_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM ods_raw_intel WHERE raw_status='FAILED'")
            failed_count = c.fetchone()["cnt"]
            c.execute(
                """SELECT COUNT(*) as cnt FROM dwd_intel_analysis
                   WHERE is_latest=1 AND risk_level IN ('high','critical')"""
            )
            high_risk_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM dwd_entity")
            entity_count = c.fetchone()["cnt"]
            c.execute(
                """SELECT risk_label, COUNT(*) as cnt
                   FROM dwd_intel_analysis
                   WHERE is_latest=1
                   GROUP BY risk_label"""
            )
            label_distribution = {r["risk_label"]: r["cnt"] for r in c.fetchall()}
            c.execute("""
                SELECT r.id, r.content_raw, r.source_platform, r.collect_time,
                       a.risk_label, a.risk_level, a.risk_score
                FROM ods_raw_intel r
                LEFT JOIN dwd_intel_analysis a ON r.id = a.raw_id AND a.is_latest=1
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
            "running_count": running_count,
            "screened_count": screened_count,
            "failed_count": failed_count,
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
