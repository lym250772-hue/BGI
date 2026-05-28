"""FastAPI REST API for BGI Intelligence Analysis Agent.

Endpoints:
    /health                            — health check
    /api/stats                         — dashboard stats
    /api/intel                         — list intel items
    /api/intel/{raw_id}                — single intel detail
    /api/entities                      — list entities
    /api/entities/{entity_id}/graph    — Neo4j subgraph around an entity
    /api/slang                         — list slang dictionary
    /internal/v1/agent/analyze         — Agent analysis (PROJECT_PLAN 8.1 contract)
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime
from loguru import logger

app = FastAPI(title="BGI Intelligence API", version="0.2.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ============================================================================
# Response models
# ============================================================================

class StatsResponse(BaseModel):
    today_total: int = 0
    high_priority: int = 0
    risk_distribution: dict = {}
    entities_total: int = 0
    pending_count: int = 0
    today_count: int = 0
    high_risk_count: int = 0
    entity_count: int = 0
    label_distribution: dict = {}
    recent_items: list = []


class IntelItem(BaseModel):
    id: int
    source_platform: str = ""
    content: str = ""
    content_type: str = "text"
    priority: str = "normal"
    status: str = "pending"
    collected_at: Optional[datetime] = None
    intent_label: Optional[str] = None
    sub_label: Optional[str] = None
    confidence: Optional[float] = None


class EntityItem(BaseModel):
    id: int
    entity_type: str
    entity_value: str
    extraction_method: str = ""
    first_seen: Optional[datetime] = None


# ============================================================================
# Agent Analyze — PROJECT_PLAN.md Section 8.1 contract
# ============================================================================

class AnalyzeOptions(BaseModel):
    enable_graph_expand: bool = True
    enable_report: bool = True
    enable_llm: bool = True


class AnalyzeRequest(BaseModel):
    raw_id: int
    platform: str = "unknown"
    text: str
    metadata: Optional[dict] = None
    options: Optional[AnalyzeOptions] = None


class EvidenceSpanDTO(BaseModel):
    text: str
    start: int = 0
    end: int = 0
    risk_point: str = ""
    reason: str = ""
    confidence: float = 0.0
    method: str = ""


class EntityDTO(BaseModel):
    entity_type: str
    entity_value: str
    context: str = ""
    confidence: float = 0.0
    extraction_method: str = ""


class SlangTermDTO(BaseModel):
    term: str
    meaning: str = ""
    risk_category: str = ""
    source: str = ""


class AnalyzeResponse(BaseModel):
    raw_id: int
    clean_text: str = ""
    risk_label: str = ""
    risk_sub_label: str = ""
    risk_score: float = 0.0
    risk_level: str = "normal"
    evidence_spans: list[dict] = []
    entities: list[dict] = []
    slang_terms: list[dict] = []
    graph_result: dict = {}
    agent_summary: str = ""
    disposal_advice: list[dict] = []
    training_sample: dict = {}


# ============================================================================
# Routes — Health
# ============================================================================

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ============================================================================
# Routes — Agent Analyze (P0: core API)
# ============================================================================

@app.post("/internal/v1/agent/analyze", response_model=AnalyzeResponse)
def agent_analyze(req: AnalyzeRequest):
    """Run full analysis pipeline on a single intel item.

    PROJECT_PLAN.md Section 8.1 contract:
        POST /internal/v1/agent/analyze
        Request:  {raw_id, platform, text, metadata, options}
        Response: {raw_id, risk_label, risk_score, evidence_spans, entities,
                   slang_terms, graph_result, agent_summary, disposal_advice}
    """
    opts = req.options or AnalyzeOptions()
    try:
        from analyzer.engine import engine
        result = engine.run(
            raw_data_id=req.raw_id,
            text=req.text,
            platform=req.platform,
            enable_graph_expand=opts.enable_graph_expand,
            enable_report=opts.enable_report,
        )
        # If LLM is disabled externally, force circuit open
        if not opts.enable_llm and not engine.is_degraded:
            engine._circuit_open = True
            result = engine.run(
                raw_data_id=req.raw_id,
                text=req.text,
                platform=req.platform,
                enable_graph_expand=opts.enable_graph_expand,
                enable_report=opts.enable_report,
            )
            engine.reset_circuit()

        return AnalyzeResponse(
            raw_id=result["raw_id"],
            clean_text=result["clean_text"],
            risk_label=result["risk_label"],
            risk_sub_label=result["risk_sub_label"],
            risk_score=result["risk_score"],
            risk_level=result["risk_level"],
            evidence_spans=result.get("evidence_spans", []),
            entities=result.get("entities", []),
            slang_terms=result.get("slang_terms", []),
            graph_result=result.get("graph_result", {}),
            agent_summary=result.get("agent_summary", ""),
            disposal_advice=result.get("disposal_advice", []),
            training_sample={},
        )
    except Exception as exc:
        logger.error(f"Agent analyze failed for raw_id={req.raw_id}: {exc}")
        return AnalyzeResponse(raw_id=req.raw_id, clean_text=req.text)


# ============================================================================
# Routes — Stats
# ============================================================================

@app.get("/api/stats", response_model=StatsResponse)
def get_stats():
    """Get dashboard statistics. Matches daily_stats() return fields."""
    try:
        from storage.mysql_store import mysql
        stats = mysql.daily_stats()
        return StatsResponse(
            today_total=stats.get("today_count", 0),
            today_count=stats.get("today_count", 0),
            high_priority=stats.get("high_risk_count", 0),
            high_risk_count=stats.get("high_risk_count", 0),
            risk_distribution=stats.get("label_distribution", {}),
            label_distribution=stats.get("label_distribution", {}),
            entities_total=stats.get("entity_count", 0),
            entity_count=stats.get("entity_count", 0),
            pending_count=stats.get("pending_count", 0),
            recent_items=stats.get("recent_items", []),
        )
    except Exception as exc:
        logger.error(f"Stats failed: {exc}")
        return StatsResponse()


# ============================================================================
# Routes — Intel
# ============================================================================

@app.get("/api/intel")
def list_intel(
    status: str = Query(default="ANALYZED"),
    platform: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    intent: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0),
):
    """List intelligence items with optional filters."""
    try:
        from storage.mysql_store import mysql
        rows = mysql.list_raw(
            status=status, platform=platform, priority=priority,
            limit=limit, offset=offset,
        )
        for row in rows:
            with mysql.cursor() as c:
                c.execute(
                    """SELECT risk_label, risk_sub_label, risk_score
                       FROM dwd_intel_analysis
                       WHERE raw_id=%s ORDER BY created_at DESC LIMIT 1""",
                    (row["id"],),
                )
                ar = c.fetchone()
                if ar:
                    row["intent_label"] = ar["risk_label"]
                    row["sub_label"] = ar["risk_sub_label"]
                    row["confidence"] = ar["risk_score"]
        return {"total": len(rows), "items": rows}
    except Exception as exc:
        logger.error(f"List intel failed: {exc}")
        return {"total": 0, "items": [], "error": str(exc)}


@app.get("/api/intel/{raw_id}")
def get_intel_detail(raw_id: int):
    """Get full detail for a single intel item including analysis + entities."""
    try:
        from storage.mysql_store import mysql
        rows = mysql.list_raw(limit=1, offset=raw_id - 1)
        if not rows:
            return {"error": "Not found"}
        intel = rows[0]

        with mysql.cursor() as c:
            c.execute(
                "SELECT * FROM dwd_intel_analysis WHERE raw_id=%s ORDER BY created_at DESC LIMIT 1",
                (raw_id,),
            )
            analysis = c.fetchone()
            c.execute(
                "SELECT * FROM dwd_entity WHERE raw_id=%s ORDER BY first_seen DESC",
                (raw_id,),
            )
            entities = c.fetchall()
            c.execute(
                "SELECT * FROM agent_report WHERE raw_id=%s ORDER BY created_at DESC LIMIT 1",
                (raw_id,),
            )
            report = c.fetchone()

        return {
            "intel": intel,
            "analysis": analysis,
            "entities": entities,
            "report": report,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ============================================================================
# Routes — Entities
# ============================================================================

@app.get("/api/entities")
def list_entities(
    entity_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
):
    """List extracted entities."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            if entity_type:
                c.execute(
                    "SELECT * FROM dwd_entity WHERE entity_type=%s ORDER BY first_seen DESC LIMIT %s OFFSET %s",
                    (entity_type, limit, offset),
                )
            else:
                c.execute(
                    "SELECT * FROM dwd_entity ORDER BY first_seen DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
            items = c.fetchall()

            c.execute("SELECT COUNT(*) as cnt FROM dwd_entity")
            total = c.fetchone()["cnt"]

        return {"total": total, "items": items}
    except Exception as exc:
        logger.error(f"List entities failed: {exc}")
        return {"total": 0, "items": [], "error": str(exc)}


@app.get("/api/entities/{entity_id}/graph")
def entity_graph(entity_id: int):
    """Get the Neo4j subgraph around an entity."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT * FROM dwd_entity WHERE id=%s", (entity_id,))
            ent = c.fetchone()
        if not ent:
            return {"error": "Entity not found"}
        from storage.neo4j_store import neo4j
        results = neo4j.find_entity_neighborhood(
            ent["entity_type"], ent["entity_value"]
        )
        return {"entity": ent, "neighborhood": results}
    except Exception as exc:
        return {"error": str(exc)}


# ============================================================================
# Routes — Slang, Cheat Scripts
# ============================================================================

@app.get("/api/slang")
def list_slang(status: str = Query(default="active")):
    """List slang dictionary entries."""
    try:
        from storage.mysql_store import mysql
        rows = mysql.list_slang(status=status)
        return {"total": len(rows), "items": rows}
    except Exception as exc:
        return {"total": 0, "items": [], "error": str(exc)}


@app.get("/api/cheat-scripts")
def list_cheat_scripts():
    """List generated cheat scripts."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT * FROM cheat_scripts ORDER BY created_at DESC LIMIT 50")
            return {"items": c.fetchall()}
    except Exception as exc:
        return {"items": [], "error": str(exc)}
