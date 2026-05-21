-- BGI Agent MySQL Schema
-- Auto-executed on first container start

CREATE TABLE IF NOT EXISTS raw_data (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_platform VARCHAR(32) NOT NULL COMMENT 'telegram/tieba/weibo/zhihu/forum',
    source_url TEXT COMMENT 'Original URL',
    author_uid VARCHAR(128) COMMENT 'Author user ID',
    author_username VARCHAR(256) COMMENT 'Author display name',
    content_type VARCHAR(16) DEFAULT 'text' COMMENT 'text/image/gif/video/audio',
    content_raw MEDIUMTEXT NOT NULL COMMENT 'Original unprocessed content',
    content MEDIUMTEXT COMMENT 'Cleaned content after pipeline',
    image_hash VARCHAR(64) COMMENT 'MD5 of image for dedup',
    simhash VARCHAR(64) COMMENT '64-bit SimHash fingerprint',
    priority VARCHAR(16) DEFAULT 'normal' COMMENT 'normal/high/critical',
    status VARCHAR(16) DEFAULT 'pending' COMMENT 'pending/cleaned/analyzed/discarded',
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    group_id VARCHAR(128) COMMENT 'Telegram group / Tieba name',
    message_id BIGINT COMMENT 'Message or post ID',
    metadata JSON COMMENT 'Extra platform-specific metadata',
    INDEX idx_platform (source_platform),
    INDEX idx_simhash (simhash),
    INDEX idx_status (status),
    INDEX idx_priority (priority),
    INDEX idx_collected_at (collected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS analysis_results (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    raw_data_id BIGINT NOT NULL,
    intent_label VARCHAR(64) COMMENT 'Primary risk category',
    sub_label VARCHAR(128) COMMENT 'Secondary risk sub-category',
    confidence DECIMAL(5,4) COMMENT 'Classification confidence 0-1',
    classification_method VARCHAR(32) COMMENT 'keyword/roberta/llm',
    is_high_risk TINYINT(1) DEFAULT 0,
    analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (raw_data_id) REFERENCES raw_data(id) ON DELETE CASCADE,
    INDEX idx_label (intent_label),
    INDEX idx_raw_id (raw_data_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS entities (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    raw_data_id BIGINT NOT NULL,
    entity_type VARCHAR(32) NOT NULL COMMENT 'phone/wechat/qq/url/domain/ip/bank_card/alipay/slang/tool/feature',
    entity_value TEXT NOT NULL COMMENT 'The actual extracted value',
    extraction_method VARCHAR(32) DEFAULT 'regex' COMMENT 'regex/dict/embedding/llm',
    context TEXT COMMENT 'Surrounding text for context',
    metadata JSON COMMENT 'Extra info (similarity score, meaning, etc.)',
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (raw_data_id) REFERENCES raw_data(id) ON DELETE CASCADE,
    INDEX idx_type (entity_type),
    INDEX idx_value (entity_value(255)),
    INDEX idx_method (extraction_method)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS slang_dict (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    slang VARCHAR(128) NOT NULL COMMENT 'The slang term',
    normalized_meaning TEXT NOT NULL COMMENT 'Normalized semantic meaning',
    category VARCHAR(64) COMMENT 'Risk category',
    source VARCHAR(64) DEFAULT 'manual' COMMENT 'threathunter/manual/llm/embedding',
    embedding_id VARCHAR(64) COMMENT 'Corresponding Milvus embedding ID',
    status VARCHAR(16) DEFAULT 'active' COMMENT 'active/candidate/deprecated',
    confirmed_by VARCHAR(64) COMMENT 'Who confirmed this entry',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_slang (slang),
    INDEX idx_status (status),
    INDEX idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS cheat_scripts (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(256) NOT NULL COMMENT 'Script title',
    risk_type VARCHAR(64) COMMENT 'Associated risk type',
    abuse_chain TEXT COMMENT 'Full abuse chain description',
    tools_used TEXT COMMENT 'JSON array of tools',
    related_entities TEXT COMMENT 'JSON array of related entities',
    defense_suggestions TEXT COMMENT 'JSON array of defense suggestions',
    related_intel_ids TEXT COMMENT 'JSON array of related intel IDs',
    generated_by VARCHAR(32) DEFAULT 'llm',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS annotation_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    raw_data_id BIGINT,
    field_name VARCHAR(64) COMMENT 'Which field was corrected',
    old_value TEXT,
    new_value TEXT,
    annotated_by VARCHAR(64) DEFAULT 'human',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (raw_data_id) REFERENCES raw_data(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
