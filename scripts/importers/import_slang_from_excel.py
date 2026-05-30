#!/usr/bin/env python3
"""Import slang terms from Excel files into MySQL slang_dict + Milvus embeddings.

Usage:
    python scripts/importers/import_slang_from_excel.py "黑话对应释义表/"
    python scripts/importers/import_slang_from_excel.py --dry-run
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from loguru import logger


def load_all_slang(excel_dir: str) -> list[dict]:
    """Load all slang from Excel files in the directory."""
    excel_dir = Path(excel_dir)
    all_terms = []
    for xlsx in sorted(excel_dir.glob("*.xlsx")):
        df = pd.read_excel(xlsx)
        # Columns: 场景分类, 黑话术语, 精准定义
        cols = list(df.columns)
        cat_col = cols[0]
        term_col = cols[1]
        def_col = cols[2]
        for _, row in df.iterrows():
            all_terms.append({
                "category": str(row[cat_col]).strip(),
                "slang": str(row[term_col]).strip(),
                "normalized_meaning": str(row[def_col]).strip(),
            })
        logger.info(f"  {xlsx.name}: {len(df)} terms")
    return all_terms


def import_to_mysql(terms: list[dict]) -> int:
    """Insert slang terms into MySQL slang_dict. Returns count."""
    from storage.mysql_store import mysql
    count = 0
    for t in terms:
        try:
            mysql.insert_slang({
                "slang": t["slang"],
                "normalized_meaning": t["normalized_meaning"],
                "category": t["category"],
                "source": "公众号-黑灰产情报",
                "status": "active",
            })
            count += 1
        except Exception as exc:
            logger.warning(f"Skip duplicate? {t['slang']}: {exc}")
    return count


def embed_to_milvus(terms: list[dict]) -> int:
    """Embed slang definitions and upsert into Milvus slang_embeddings."""
    from sentence_transformers import SentenceTransformer
    from config.settings import settings
    from storage.milvus_store import milvus

    model = SentenceTransformer(settings.embedding_model_name)
    count = 0
    for t in terms:
        try:
            text = f"{t['slang']}: {t['normalized_meaning']}"
            vec = model.encode(text).tolist()
            milvus.insert_slang(
                slang=t["slang"],
                meaning=t["normalized_meaning"],
                embedding=vec,
                category=t["category"],
            )
            count += 1
        except Exception as exc:
            logger.warning(f"Milvus embed failed for {t['slang']}: {exc}")
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Import slang from Excel files into MySQL + Milvus"
    )
    parser.add_argument("excel_dir", help="Directory containing .xlsx slang files")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't import")
    parser.add_argument("--no-milvus", action="store_true", help="Skip Milvus embedding")
    args = parser.parse_args()

    terms = load_all_slang(args.excel_dir)
    print(f"\nTotal: {len(terms)} slang terms from 6 categories")

    # Category breakdown
    cats = {}
    for t in terms:
        cats[t["category"]] = cats.get(t["category"], 0) + 1
    for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {cnt}")

    if args.dry_run:
        print("\n[Dry run — sample terms]")
        for t in terms[:5]:
            print(f"  [{t['category']}] {t['slang']} — {t['normalized_meaning'][:60]}...")
        return

    print(f"\nImporting to MySQL...")
    mysql_count = import_to_mysql(terms)
    print(f"  MySQL: {mysql_count} inserted")

    if not args.no_milvus:
        print(f"Embedding to Milvus...")
        milvus_count = embed_to_milvus(terms)
        print(f"  Milvus: {milvus_count} embedded")

    print(f"\nDone. {mysql_count} terms ready for entity extraction.")


if __name__ == "__main__":
    main()
