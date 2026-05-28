"""Knowledge graph — Neo4j + pyvis visualization."""

import os
import tempfile
import streamlit as st
from pathlib import Path

import ui.theme as T


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

    search = st.text_input(
        "搜索实体", placeholder="输入 entity value 查询关联图谱...",
        label_visibility="collapsed",
    )
    st.divider()

    try:
        from storage.neo4j_store import neo4j
        nodes, edges = neo4j.get_refined_graph(
            search=search if search else "", limit=60
        )
    except Exception as exc:
        st.error(f"Neo4j 查询失败: {exc}")
        return

    if not nodes:
        st.markdown(
            T.empty("🕸", "图谱暂无数据", "分析情报后实体关系将自动同步至 Neo4j"),
            unsafe_allow_html=True,
        )
        return

    try:
        from pyvis.network import Network

        net = Network(
            height="530px", width="100%",
            bgcolor=T.BG_CARD, font_color=T.TEXT_MAIN,
        )
        net.repulsion(node_distance=180, spring_length=180)

        colors = {
            "intel": T.SAGE,
            "account": T.ROSE,
            "tool": "#C4A35A",
            "link": "#A0A0C0",
            "contact": T.SLATE,
            "entity": "#8EA0A8",
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
            net.add_edge(
                e["from"], e["to"],
                color=T.BORDER, width=1.2,
                title=e.get("label", ""),
            )

        fd, path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        try:
            net.save_graph(path)
            html_str = Path(path).read_text(encoding="utf-8")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

        st.components.v1.html(html_str, height=550, scrolling=True)

        # Legend
        st.caption(
            "● 情报 (Intel)  |  ■ 实体 (Account/Contact/Tool/Link)  |  "
            "边: MENTIONS / PROMOTES / USES_CONTACT / EXTRACTED_FROM"
        )

    except ImportError:
        st.markdown(
            T.empty("📦", "pyvis 未安装", "pip install pyvis"),
            unsafe_allow_html=True,
        )
    except Exception as exc:
        st.error(f"渲染失败: {exc}")
