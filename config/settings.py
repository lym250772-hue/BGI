"""Global settings for BGI Intelligence Analysis Agent."""
from pathlib import Path
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    # --- MySQL ---
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "bagi"
    mysql_password: str = "bagi2026pass"
    mysql_database: str = "bagi_intel"

    # --- Neo4j ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "bagi2026neo4j"

    # --- Milvus ---
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_dim: int = 384

    # --- LLM API ---
    llm_provider: str = "deepseek"  # or "doubao"
    llm_api_key: str = ""
    llm_api_base: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"

    # --- Collection ---
    collection_interval_minutes: int = 30
    max_requests_per_minute: int = 20

    # --- Cookies (JSON strings for platform login, stored in .env) ---
    weibo_cookies: str = ""
    tieba_cookies: str = ""
    zhihu_cookies: str = ""
    xiaohongshu_cookies: str = ""
    douyin_cookies: str = ""

    # --- Cleaning ---
    simhash_threshold: int = 3  # hamming distance <= 3 = duplicate
    dedup_similarity: float = 0.95

    # --- Classification ---
    roberta_model_path: str = str(DATA_DIR / "models" / "roberta_classifier")
    classification_confidence_threshold: float = 0.7
    embedding_model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"
    slang_similarity_threshold: float = 0.75

    # --- Paths ---
    raw_data_dir: Path = DATA_DIR / "raw"
    cleaned_data_dir: Path = DATA_DIR / "cleaned"
    models_dir: Path = DATA_DIR / "models"
    slang_dict_path: Path = DATA_DIR / "slang_dict"

    class Config:
        env_file = PROJECT_ROOT / ".env"
        env_prefix = "BGI_"


settings = Settings()
