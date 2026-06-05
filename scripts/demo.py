#!/usr/bin/env python3
"""
BGI 实机演示一键脚本

用法:
  python scripts/demo.py start     # 启动Docker + 初始化 + 灌数据 + 启动UI
  python scripts/demo.py crawl     # 快速采集演示（1-2关键词）
  python scripts/demo.py persona   # 人物钓鱼演示
  python scripts/demo.py ui        # 仅启动UI（数据已就位）
  python scripts/demo.py full      # 完整流程：采集演示 + 人物演示 + UI

演示流程:
  Step 1: 快速采集演示 — 现场爬1-2个关键词，展示采集能力
  Step 2: 人物钓鱼演示 — 跑一段AI钓鱼对话，展示主动情报收集
  Step 3: 预置数据前端展示 — 7平台10K+数据，展示完整分析链路
"""

import sys, os, time, subprocess, json, argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

DOCKER = "E:/Docker/resources/bin/docker.exe"
UI_PORT = 8600


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check_docker() -> bool:
    """确保Docker在运行"""
    try:
        result = subprocess.run([DOCKER, "ps"], capture_output=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def start_docker():
    """启动Docker Desktop"""
    if check_docker():
        print("Docker: 已在运行")
        return True
    print("正在启动 Docker Desktop...")
    os.startfile("E:/Docker/Docker Desktop.exe")
    for i in range(30):
        time.sleep(2)
        if check_docker():
            print(f"Docker: 已启动 (耗时{(i+1)*2}s)")
            return True
    print("Docker 启动超时，请手动启动后重试")
    return False


def start_containers():
    """启动BGI容器"""
    section("启动容器")
    subprocess.run(
        [DOCKER, "compose", "-f", "docker/docker-compose.yml", "up", "-d"],
        cwd=str(PROJECT_ROOT),
    )
    time.sleep(8)
    subprocess.run([DOCKER, "ps"], cwd=str(PROJECT_ROOT))
    print("所有容器已启动")


def init_database():
    """初始化数据库（跳过Milvus，避免超时）"""
    section("初始化数据库")
    from storage.mysql_store import mysql
    from storage.neo4j_store import neo4j
    mysql.init_tables()
    try:
        neo4j.init_constraints()
    except Exception:
        pass  # Neo4j可选
    print("数据库初始化完成 (MySQL)")


def load_examples():
    """导入所有example数据到MySQL"""
    section("导入示例数据")
    from storage.mysql_store import mysql
    from datetime import datetime
    import json as _json

    # 清空旧数据（带重试）
    for attempt in range(3):
        try:
            with mysql.cursor() as c:
                c.execute("DELETE FROM ods_raw_intel")
            break
        except Exception:
            if attempt < 2:
                time.sleep(5)
    print("已清空旧数据")

    platforms = {
        "weibo": 1768, "zhihu": 1607, "xiaohongshu": 2556,
        "douyin": 1167, "tieba": 1141, "xianyu": 1389,
        "qq_group": 620,
    }
    total = 0
    for p in platforms:
        f = PROJECT_ROOT / "examples" / f"{p}_sample.json"
        if not f.exists():
            print(f"  {p}: 文件不存在，跳过")
            continue
        with open(f, "r", encoding="utf-8") as fp:
            data = _json.load(fp)
        items = data.get("items", data.get("messages", []))
        count = 0
        for item in items:
            content = item.get("content_raw", "").strip()
            if not content:
                continue
            mysql.insert_raw({
                "source_platform": p,
                "source_url": item.get("source_url", ""),
                "author_id": item.get("author_uid", ""),
                "author_name": item.get("author_username", ""),
                "content_type": item.get("content_type", "text"),
                "content_raw": content,
                "raw_status": "RAW_COLLECTED",
                "collect_time": datetime.utcnow(),
                "metadata": _json.dumps(item.get("metadata", {}), ensure_ascii=False, default=str),
            })
            count += 1
        print(f"  {p:15s}: {count:>6,d} 条")
        total += count
    print(f"\n  总计: {total:,d} 条")


def run_quick_clean():
    """运行清洗管道"""
    section("清洗管道")
    subprocess.run(
        [sys.executable, "main.py", "clean", "-l", "500"],
        cwd=str(PROJECT_ROOT),
    )
    print("清洗完成")


def start_ui():
    """启动Streamlit UI"""
    section("启动前端")
    # 杀掉所有旧streamlit
    subprocess.run("taskkill /F /IM streamlit.exe 2>nul", shell=True)
    time.sleep(2)
    # 启动
    subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "ui/app.py",
         "--server.port", str(UI_PORT)],
        cwd=str(PROJECT_ROOT),
    )
    time.sleep(8)
    print(f"\n  UI 已启动: http://localhost:{UI_PORT}")
    print(f"  数据: 7平台, 10K+条目")


def demo_crawl():
    """快速采集演示"""
    section("快速采集演示")
    print("正在采集 微博「刷单」1页...")
    subprocess.run(
        [sys.executable, "main.py", "collect", "-p", "weibo",
         "-k", "刷单", "--max-pages", "1"],
        cwd=str(PROJECT_ROOT),
    )
    print("\n采集演示完成！")


def demo_persona():
    """人物钓鱼演示"""
    section("AI人物钓鱼演示")
    from persona.engine import PersonaEngine
    engine = PersonaEngine()
    result = engine.run_conversation(
        persona_name="ecommerce_buyer",
        target_platform="xianyu",
        target_uid="user123",
        target_username="涨粉专家老王",
        target_context="提供抖音/快手/小红书全平台涨粉服务，真人粉丝不掉，50元1000粉",
    )
    print(f"\n人物: {result.persona_name}")
    print(f"目标: {result.target_username}")
    print(f"对话轮次: {len(result.raw_messages)}")
    print()
    for t in result.raw_messages:
        role = "买家(小张)" if t["role"] == "persona" else "卖家(老王)"
        print(f"  {role}: {t['content'][:80]}...")
    print(f"\n安全标记: {len(result.safety_flags)} (0=全部安全)")
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="BGI 演示脚本")
    parser.add_argument("action", choices=["start", "crawl", "persona", "ui", "full"],
                        help="start=初始化+灌数据+UI | crawl=采集演示 | persona=钓鱼演示 | ui=仅UI | full=完整流程")
    args = parser.parse_args()

    if args.action == "start":
        if not start_docker():
            return
        start_containers()
        init_database()
        load_examples()
        run_quick_clean()
        start_ui()

    elif args.action == "crawl":
        demo_crawl()

    elif args.action == "persona":
        demo_persona()

    elif args.action == "ui":
        if not start_docker():
            return
        start_containers()
        start_ui()

    elif args.action == "full":
        print("\n" + "="*60)
        print("  BGI 黑灰产情报分析系统 — 实机演示")
        print("="*60)

        if not start_docker():
            return
        start_containers()
        init_database()
        load_examples()
        run_quick_clean()

        demo_crawl()
        demo_persona()
        start_ui()

        print(f"\n{'='*60}")
        print(f"  演示就绪！")
        print(f"  UI: http://localhost:{UI_PORT}")
        print(f"  数据: 7平台 / 10K+条目 / 清洗+分析完成")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
