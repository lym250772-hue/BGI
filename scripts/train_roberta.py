#!/usr/bin/env python3
"""Fine-tune RoBERTa for black/grey-market intent classification (L2).

This is a placeholder — training requires labeled data with 7 intent categories.
Once labeled data is available, this script will:
  1. Load a Chinese RoBERTa base model (hfl/chinese-roberta-wwm-ext)
  2. Fine-tune on labeled (text, intent_label) pairs
  3. Save to models/roberta-intent/ for the classifier's L2 cascade

Usage:
    python scripts/train_roberta.py --data data/labeled_intel.csv --epochs 3

Prerequisites:
    pip install transformers datasets scikit-learn
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser(
        description="Train RoBERTa classifier for BGI intent detection"
    )
    parser.add_argument("--data", type=str, default="data/labeled_intel.csv",
                        help="Path to labeled training data (CSV with text,label columns)")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--output", type=str, default="models/roberta-intent")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"[SKIP] No labeled data at {data_path}")
        print("       Provide labeled CSV with columns: text, intent_label")
        print("       Intent labels: 诈骗, 引流, 作弊, 账号黑产, 内容违规, 工具交易, 直播违规")
        return

    try:
        from transformers import (
            AutoTokenizer,
            AutoModelForSequenceClassification,
            TrainingArguments,
            Trainer,
        )
        from datasets import Dataset
    except ImportError:
        print("Install dependencies: pip install transformers datasets scikit-learn")
        return

    # TODO: Load data, tokenize, train, save
    print(f"Training RoBERTa on {data_path} for {args.epochs} epochs...")
    print("[PLACEHOLDER] Training logic not yet implemented — waiting for labeled data")


if __name__ == "__main__":
    main()
