"""Knowledge graph — Neo4j + pyvis visualization."""

import streamlit as st
import tempfile
from pathlib import Path

import ui.theme as T


def _fetch_graph(search: str = ""):
    try:
        from storage.neo4j_store import neo4j
        nodes, edges = [], []
        seen = set()

        with neo4j.driver.session() as sess:
            if search:
                result = sess.run("""
                    MATCH (e:Entity)-[:EXTRACTED_FROM]-(i:Intel)
                    WHERE e.value CONTAINS $q
                    RETURN e, i
                    LIMIT 40
                """, q=search)
            else:
                result = sess.run("""
                    MATCH (i:Intel)-[:EXTRACTED_FROM]-(e:Entity)
                    RETURN i.raw_id as intel_id, i.text as text,
                           e.type as etype, e.value as evalue,
                           e.uuid as eid
                    LIMIT 50
                """)

            for r in result:
                if search:
                    eid = r["e"]["uuid"]
                    iid = str(r["i"]["raw_id"])
                    if eid not in seen:
                        nodes.append({"id": eid, "label": f"{r['e']['type']}:{r['e']['value']}", "group": r["e"]["type"]})
                        seen.add(eid)
                    if iid not in seen:
                        nodes.append({"id": iid, "label": (r["i"]["text"] or "")[:25], "group": "intel"})
                        seen.add(iid)
                    edges.append({"from": iid, "to": eid})
                else:
                    iid = str(r["intel_id"])
                    eid = r["eid"]
                    if iid not in seen:
                        nodes.append({"id": iid, "label": (r["text"] or "")[:25], "group": "intel"})
                        seen.add(iid)
                    if eid not in seen:
                        nodes.append({"id": eid, "label": f"{r['etype']}:{r['evalue']}", "group": r["etype"]})
                        seen.add(eid)
                    edges.append({"from": iid, "to": eid})

        return nodes, edges
    except Exception:
        return None, None


def _check_neo4j():
    try:
        from storage.neo4j_store import neo4j
        with neo4j.driver.session() as s:
            s.run("RETURN 1")
        return True
    except Exception:
        return False


def show():
    st.markdown("## 知识图谱")
    st.caption("基于 Neo4j 的实体关系可视分析")

    neo4j_up = _check_neo4j()

    if not neo4j_up:
        st.markdown(
            f"""<div style="background:{T.BG_CARD};border:1px solid {T.BORDER};border-radius:12px;
            padding:2rem;text-align:center">
            <div style="font-size:2rem;margin-bottom:0.8rem;opacity:0.6">⚠️</div>
            <div style="font-family:'{T.FONT_DISPLAY}',serif;font-size:0.95rem;font-weight:500;
            color:{T.TEXT_SOFT};margin-bottom:0.3rem">Neo4j 未连接</div>
            <div style="font-size:0.82rem;color:{T.TEXT_MUTED};margin-bottom:1rem">
            确认 Neo4j 已启动：bolt://localhost:7687</div>
            <code style="font-size:0.75rem;background:{T.BG_SIDEBAR};padding:4px 10px;border-radius:4px">
            cd docker && docker compose up -d neo4j</code></div>""",
            unsafe_allow_html=True,
        )
        return

    search = st.text_input("搜索实体", placeholder="输入 entity_type:value 查询关联图谱...", label_visibility="collapsed")
    st.divider()

    nodes, edges = _fetch_graph(search if search else "")

    if nodes is None:
        st.error("Neo4j 查询失败，请检查连接")
        return

    if not nodes:
        st.markdown(
            T.empty("🕸", "图谱暂无数据", "分析情报后实体关系将自动同步至 Neo4j"),
            unsafe_allow_html=True,
        )
        return

    try:
        from pyvis.network import Network
        net = Network(height="530px", width="100%", bgcolor=T.BG_CARD, font_color=T.TEXT_MAIN)
        net.repulsion(node_distance=180, spring_length=180)

        colors = {
            "intel": T.SAGE, "phone": T.SLATE, "wechat": T.ROSE, "qq": "#A0ACBA",
            "url": "#B0A0B0", "domain": "#9AAFA0", "ip": "#B0A898",
            "bank_card": "#A5B0A0", "alipay": "#ACA8B0", "slang": "#A0AAB0",
            "tool": "#B0A8A0", "feature": "#9EA8B0",
        }

        for n in nodes:
            g = n.get("group", "intel")
            net.add_node(
                n["id"], label=n["label"],
                color=colors.get(g, T.SAGE),
                shape="dot" if g == "intel" else "box",
                title=n["label"],
            )
        for e in edges:
            net.add_edge(e["from"], e["to"], color=T.BORDER, width=1.2)

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            net.save_graph(tmp.name)
            html_str = Path(tmp.name).read_text(encoding="utf-8")
            Path(tmp.name).unlink()

        st.components.v1.html(html_str, height=550, scrolling=True)
        st.caption("● 情报  |  □ 实体  |  — EXTRACTED_FROM")

    except ImportError:
        st.markdown(T.empty("📦", "pyvis 未安装", "pip install pyvis"), unsafe_allow_html=True)
    except Exception as exc:
        st.error(f"渲染失败: {exc}")
