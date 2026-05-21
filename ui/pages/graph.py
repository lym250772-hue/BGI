"""Knowledge graph page — interactive entity graph visualization with pyvis."""

import streamlit as st
import tempfile
from pathlib import Path

from ui.theme import empty_state


def _neo4j():
    from storage.neo4j_store import neo4j as n
    return n


def _build_graph(entity_value: str = ""):
    """Fetch graph data from Neo4j and build a pyvis network."""
    try:
        neo4j = _neo4j()
        if entity_value:
            neighborhood = neo4j.find_entity_neighborhood(entity_value)
        else:
            # Get overview — sample some intel nodes and their entities
            neighborhood = {"nodes": [], "edges": []}
            with neo4j.driver.session() as session:
                result = session.run("""
                    MATCH (i:Intel)-[:EXTRACTED_FROM]-(e:Entity)
                    RETURN i.raw_id as intel_id, i.text as text,
                           e.type as entity_type, e.value as entity_value,
                           e.uuid as entity_uuid
                    LIMIT 50
                """)
                seen_nodes = set()
                for record in result:
                    iid = str(record["intel_id"])
                    eid = record["entity_uuid"]
                    if iid not in seen_nodes:
                        neighborhood["nodes"].append({
                            "id": iid,
                            "label": (record["text"] or "")[:30],
                            "group": "intel",
                        })
                        seen_nodes.add(iid)
                    if eid not in seen_nodes:
                        neighborhood["nodes"].append({
                            "id": eid,
                            "label": f"{record['entity_type']}:{record['entity_value']}",
                            "group": record["entity_type"],
                        })
                        seen_nodes.add(eid)
                    neighborhood["edges"].append({"from": iid, "to": eid})
        return neighborhood
    except Exception as exc:
        return None


def show():
    st.markdown("## 知识图谱")
    st.caption("基于 Neo4j 的实体关系可视化")

    # Search bar
    search = st.text_input(
        "搜索实体",
        placeholder="输入 entity_type:value 查询关联图谱…",
        label_visibility="collapsed",
    )

    st.divider()

    graph_data = _build_graph(search if search else "")

    if graph_data is None:
        st.markdown(
            empty_state("⚠️", "Neo4j 未连接", "请确认 Neo4j 服务已启动 · bolt://localhost:7687"),
            unsafe_allow_html=True,
        )
        return

    if not graph_data["nodes"]:
        st.markdown(
            empty_state("🕸️", "图谱暂无数据", "分析情报后实体关系将自动同步至 Neo4j"),
            unsafe_allow_html=True,
        )
        return

    # Build pyvis graph
    try:
        from pyvis.network import Network

        net = Network(height="550px", width="100%", bgcolor="#FDFBF9", font_color="#3D3929")
        net.repulsion(node_distance=200, spring_length=200)

        # Color map for entity types
        color_map = {
            "intel": "#8B9D83",
            "phone": "#7E8FA6",
            "wechat": "#C4A8A3",
            "qq": "#A3B0C4",
            "url": "#B5A0B5",
            "domain": "#9BAFA5",
            "ip": "#B8A596",
            "bank_card": "#A8B5A0",
            "alipay": "#B0A8B5",
            "slang": "#A5B0A8",
            "tool": "#B5A8A0",
            "feature": "#A0A8B5",
        }

        for node in graph_data["nodes"]:
            group = node.get("group", "intel")
            net.add_node(
                node["id"],
                label=node["label"],
                color=color_map.get(group, "#8B9D83"),
                shape="dot" if group == "intel" else "box",
                title=node["label"],
            )

        for edge in graph_data["edges"]:
            net.add_edge(edge["from"], edge["to"], color="#D8D3CB", width=1.5)

        # Save to temp file and render
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            net.save_graph(tmp.name)
            html = Path(tmp.name).read_text(encoding="utf-8")
            Path(tmp.name).unlink()

        st.components.v1.html(html, height=580, scrolling=True)

        # Legend
        st.caption("图例：● 情报节点 | □ 实体节点 | — 提取关系")

    except ImportError:
        st.markdown(
            empty_state("📦", "pyvis 未安装", "运行 pip install pyvis 启用图谱可视化"),
            unsafe_allow_html=True,
        )
    except Exception as exc:
        st.error(f"图谱渲染失败: {exc}")
