#!/usr/bin/env python3
"""Import seed slang terms from a CSV/JSON file into MySQL + Milvus.

Slang (黑话) terms are used by the entity extractor's L2 dict matching and
L3 embedding-based variant detection. This script reads a structured file
and populates both `slang_dict` (MySQL) and `slang_embeddings` (Milvus).

Usage:
    python scripts/importers/import_seed_slang.py
    python scripts/importers/import_seed_slang.py --file data/slang.csv
    python scripts/importers/import_seed_slang.py --dry-run

Seed file format (CSV):
    slang,normalized_meaning,category
    刷单,虚假交易提升销量,作弊
    接码,接收短信验证码,账号黑产
    跑分,代收代付洗钱,诈骗

Seed file format (JSON):
    [{"slang": "刷单", "meaning": "虚假交易提升销量", "category": "作弊"}, ...]
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Built-in seed slang (used when no file is provided)
_SEED_SLANG: list[dict] = [
    {"slang": "刷单", "meaning": "虚假交易提升销量/信用", "category": "作弊"},
    {"slang": "接码", "meaning": "接收短信验证码用于批量注册", "category": "账号黑产"},
    {"slang": "跑分", "meaning": "代收代付洗钱，利用他人账户转移资金", "category": "诈骗"},
    {"slang": "出号", "meaning": "出售已注册的社交媒体/平台账号", "category": "账号黑产"},
    {"slang": "猫池", "meaning": "批量接收短信验证码的硬件设备群", "category": "账号黑产"},
    {"slang": "撞库", "meaning": "用已泄露的账号密码尝试登录其他平台", "category": "账号黑产"},
    {"slang": "四件套", "meaning": "身份证+银行卡+手机卡+U盾，用于实名认证绕过", "category": "账号黑产"},
    {"slang": "数字人", "meaning": "AI生成虚拟形象用于无人直播带货", "category": "直播违规"},
    {"slang": "无人直播", "meaning": "循环播放录制视频冒充实时直播", "category": "直播违规"},
    {"slang": "群控", "meaning": "一台电脑控制多台手机批量操作", "category": "作弊"},
    {"slang": "薅羊毛", "meaning": "利用平台漏洞/规则批量获取优惠补贴", "category": "作弊"},
    {"slang": "引流", "meaning": "将用户从公开平台引导至私域/外部站点", "category": "引流"},
    {"slang": "菠菜", "meaning": "博彩/赌博网站的隐语代称", "category": "引流"},
    {"slang": "卡商", "meaning": "批量持有银行卡/电话卡用于注册和洗钱", "category": "账号黑产"},
    {"slang": "发卡", "meaning": "自动售卡平台，出售验证码/账号/卡密", "category": "工具交易"},
]


def load_from_file(path: str) -> list[dict]:
    """Load slang entries from CSV or JSON file."""
    p = Path(path)
    if p.suffix == ".json":
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return [{"slang": d["slang"], "meaning": d.get("meaning", d.get("normalized_meaning", "")),
                 "category": d.get("category", "")} for d in data]
    elif p.suffix == ".csv":
        with open(p, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [{"slang": r["slang"], "meaning": r.get("normalized_meaning", r.get("meaning", "")),
                     "category": r.get("category", "")} for r in reader]
    else:
        print(f"Unsupported format: {p.suffix} (use .csv or .json)")
        sys.exit(1)


def import_to_mysql(entries: list[dict], dry_run: bool = False):
    """Insert slang entries into MySQL slang_dict."""
    from storage.mysql_store import mysql

    count = 0
    for entry in entries:
        if dry_run:
            print(f"  [DRY RUN] {entry['slang']} → {entry['meaning']}")
        else:
            try:
                mysql.insert_slang({
                    "slang": entry["slang"],
                    "normalized_meaning": entry["meaning"],
                    "category": entry.get("category", ""),
                    "source": "seed",
                    "status": "active",
                })
            except Exception as exc:
                print(f"  [WARN] {entry['slang']}: {exc}")
        count += 1
    return count


def embed_to_milvus(entries: list[dict], dry_run: bool = False):
    """Embed slang meanings and upsert to Milvus slang_embeddings collection."""
    try:
        from sentence_transformers import SentenceTransformer
        from storage.milvus_store import milvus
        from config.settings import settings

        model = SentenceTransformer(settings.embedding_model_name)
        for entry in entries:
            vec = model.encode(entry["meaning"]).tolist()
            if not dry_run:
                milvus.upsert_slang_embedding(entry["slang"], entry["meaning"], vec)
    except ImportError:
        print("[WARN] Cannot embed — sentence_transformers or milvus not available")
    except Exception as exc:
        print(f"[WARN] Milvus embedding failed: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Import seed slang terms into BGI databases")
    parser.add_argument("--file", "-f", type=str, default=None,
                        help="Path to CSV/JSON file of slang terms")
    parser.add_argument("--dry-run", action="store_true", help="Print without importing")
    parser.add_argument("--no-milvus", action="store_true", help="Skip Milvus embedding")
    args = parser.parse_args()

    if args.file:
        entries = load_from_file(args.file)
        print(f"Loaded {len(entries)} slang terms from {args.file}")
    else:
        entries = _SEED_SLANG
        print(f"Using built-in seed list ({len(entries)} terms)")

    print(f"\nImporting {len(entries)} slang terms...")
    count = import_to_mysql(entries, dry_run=args.dry_run)
    print(f"  MySQL: {count} entries {'(dry run)' if args.dry_run else 'inserted'}")

    if not args.no_milvus and not args.dry_run:
        print("Embedding to Milvus...")
        embed_to_milvus(entries)
        print("  Milvus: embeddings upserted")

    print("\nDone. Restart the UI to see updated slang dictionary.")


if __name__ == "__main__":
    main()
