# eba_reports.py
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import plotly.graph_objects as go
from fpdf import FPDF

from eba_config import APP_NAME, APP_VERSION


PRIMARY = "#2C109C"
GOOD = "#15803D"
WARN = "#B45309"
BAD = "#B91C1C"


# =========================
# SAFE TEXT (FPDF)
# =========================
def _pdf_safe(text: str) -> str:
    if text is None:
        return ""
    s = str(text)

    repl = {
        "—": "-", "–": "-", "“": '"', "”": '"', "’": "'",
        "‘": "'", "…": "...", "\u00A0": " ", "•": "-",
        "→": "->",
    }
    for k, v in repl.items():
        s = s.replace(k, v)

    def break_long_tokens(t: str, max_len: int = 80) -> str:
        def _split(m):
            w = m.group(0)
            return " ".join(w[i:i+max_len] for i in range(0, len(w), max_len))
        return re.sub(rf"\S{{{max_len},}}", _split, t)

    s = break_long_tokens(s, 80)

    try:
        s = s.encode("latin-1", "ignore").decode("latin-1")
    except Exception:
        pass
    return s


# =========================
# GRÁFICOS (UI - Plotly)
# =========================
def criar_radar_bfa(
    traits: Dict[str, Any],
    traits_ideais: Optional[Dict[str, Tuple[float, float]]] = None
) -> go.Figure:
    labels = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]

    def _get(trait: str) -> float:
        v = traits.get(trait)
        if v is None:
            # fallback sem acento
            k2 = trait.replace("ã", "a").replace("ç", "c").replace("õ", "o").replace("é", "e")
            v = traits.get(k2, 0)
        try:
            return float(v or 0)
        except Exception:
            return 0.0

    values = [_get(k) for k in labels]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=labels,
        fill="toself",
        name="Candidato",
        line=dict(color=PRIMARY, width=3),
        fillcolor="rgba(44, 16, 156, 0.12)",
    ))

    if traits_ideais:
        vmax = [float(traits_ideais.get(k, (0, 10))[1]) for k in labels]
        vmin = [float(traits_ideais.get(k, (0, 10))[0]) for k in labels]

        fig.add_trace(go.Scatterpolar(
            r=vmax,
            theta=labels,
            name="Ideal Máx",
            line=dict(color=GOOD, dash="dash", width=2),
        ))
        fig.add_trace(go.Scatterpolar(
            r=vmin,
            theta=labels,
            name="Ideal Mín",
            line=dict(color=GOOD, dash="dash", width=2),
        ))

    fig.update_layout(
        title="Big Five x Perfil Ideal",
        polar=dict(radialaxis=dict(range=[0, 10])),
        showlegend=True,
        height=520,
        margin=dict(l=40, r=40, t=70, b=30),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig


def criar_grafico_competencias(competencias: List[Dict[str, Any]]) -> Optional[go.Figure]:
    if not competencias:
        return None

    nomes = [str(c.get("nome", "")) for c in competencias]
    notas: List[float] = []
    for c in competencias:
        try:
            notas.append(float(c.get("nota", 0) or 0))
        except Exception:
            notas.append(0.0)

    cores = [BAD if n < 45 else WARN if n < 55 else GOOD for n in notas]

    fig = go.Figure(go.Bar(
        x=notas,
        y=nomes,
        orientation="h",
        marker_color=cores,
        text=[f"{n:.0f}" for n in notas],
        textposition="outside",
    ))
    fig.update_layout(
        title="Competências (Barras)",
        height=620,
        margin=dict(l=180, r=40, t=70, b=30),
        showlegend=False,
    )
    fig.add_vline(x=45, line_dash="dash", line_color=WARN)
    fig.add_vline(x=55, line_dash="dash", line_color=GOOD)
    return fig


def criar_gauge_fit(valor: float) -> go.Figure:
    v = float(valor or 0)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=v,
        title={"text": "Fit para o Cargo"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": PRIMARY},
            "steps": [
                {"range": [0, 40], "color": "rgba(185, 28, 28, 0.25)"},
                {"range": [40, 70], "color": "rgba(180, 83, 9, 0.22)"},
                {"range": [70, 100], "color": "rgba(21, 128, 61, 0.20)"},
            ],
        },
    ))
    fig.update_layout(height=420, margin=dict(l=40, r=40, t=70, b=30))
    return fig


# =========================
# PDF (SEM KALEIDO / SEM CHROME)
# =========================
class PDFReport(FPDF):
    def __init__(self):
        super().__init__()
        self.set_margins(15, 16, 15)
        self.set_auto_page_break(auto=True, margin=18)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.cell(0, 8, _pdf_safe(f"Página {self.page_no()}"), align="C")


def gerar_pdf_corporativo(
    bfa_data: Dict[str, Any],
    analysis: Dict[str, Any],
    cargo: str,
) -> io.BytesIO:
    pdf = PDFReport()

    # CAPA (sem página em branco)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 15, _pdf_safe("Relatório Comportamental"), ln=1, align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, _pdf_safe(f"Elder Brain Analytics - {cargo}"), ln=1, align="C")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _pdf_safe(f"{APP_NAME} {APP_VERSION}"), ln=1, align="C")
    pdf.cell(0, 6, _pdf_safe(f"{datetime.now():%d/%m/%Y %H:%M}"), ln=1, align="C")

    # conteúdo (textual)
    pdf.add_page()

    # decisão / fit
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, _pdf_safe("Decisão e Compatibilidade"), ln=1)
    pdf.set_font("Helvetica", "", 11)
    decisao = (analysis or {}).get("decisao", "N/A")
    comp = float((analysis or {}).get("compatibilidade_geral", 0) or 0)
    pdf.multi_cell(0, 6.5, _pdf_safe(f"Decisão: {decisao}\nCompatibilidade: {comp:.0f}%"))
    pdf.ln(2)

    # resumo executivo
    resumo = (analysis or {}).get("resumo_executivo", "")
    if resumo:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 9, _pdf_safe("Resumo Executivo"), ln=1)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6.5, _pdf_safe(resumo))
        pdf.ln(2)

    # big five
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, _pdf_safe("Perfil Big Five"), ln=1)
    pdf.set_font("Helvetica", "", 11)
    traits = (bfa_data or {}).get("traits_bfa", {}) or {}
    for k, v in traits.items():
        try:
            pdf.multi_cell(0, 6.5, _pdf_safe(f"{k}: {float(v):.1f}/10"))
        except Exception:
            continue
    pdf.ln(1)

    # competências
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, _pdf_safe("Competências"), ln=1)
    pdf.set_font("Helvetica", "", 11)
    competencias = (bfa_data or {}).get("competencias_ms", []) or []
    fortes, criticas = [], []
    for c in competencias:
        try:
            nota = float(c.get("nota", 0) or 0)
            nome = str(c.get("nome", ""))
        except Exception:
            continue
        if nota >= 55:
            fortes.append(nome)
        elif nota < 45:
            criticas.append(nome)

    if fortes:
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 6.5, _pdf_safe("Pontos de Força:"))
        pdf.set_font("Helvetica", "", 11)
        safe_multi_cell(pdf, 6.5, "\n".join(f"- {x}" for x in fortes), 0)

    if criticas:
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 6.5, _pdf_safe("Pontos Críticos:"))
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6.5, _pdf_safe("\n".join(f"- {x}" for x in criticas)))

    # saúde emocional
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, _pdf_safe("Saúde Emocional"), ln=1)
    pdf.set_font("Helvetica", "", 11)
    saude = (bfa_data or {}).get("indicadores_saude_emocional", {}) or {}
    for k, v in saude.items():
        try:
            pdf.multi_cell(0, 6.5, _pdf_safe(f"{k.replace('_',' ').capitalize()}: {int(v)}/100"))
        except Exception:
            continue

    contexto = (analysis or {}).get("saude_emocional_contexto", "")
    if contexto:
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 11)
        pdf.multi_cell(0, 6.5, _pdf_safe(contexto))

    # desenvolvimento
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, _pdf_safe("Recomendações de Desenvolvimento"), ln=1)
    pdf.set_font("Helvetica", "", 11)
    recs = (analysis or {}).get("recomendacoes_desenvolvimento", []) or []
    for i, r in enumerate(recs, 1):
        pdf.multi_cell(0, 6.5, _pdf_safe(f"{i}. {r}"))

    cargos_alt = (analysis or {}).get("cargos_alternativos", []) or []
    if cargos_alt:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe("Cargos Alternativos"), ln=1)
        pdf.set_font("Helvetica", "", 11)
        for c in cargos_alt:
            pdf.multi_cell(0, 6.5, _pdf_safe(f"- {c.get('cargo')}: {c.get('justificativa')}"))

    out = pdf.output(dest="S")
    if isinstance(out, str):
        out = out.encode("latin-1", "ignore")
    buf = io.BytesIO(out)
    buf.seek(0)
    return buf
def _break_long_tokens(t: str, max_len: int = 40) -> str:
    # quebra qualquer sequência sem espaço com mais de max_len
    def _split(m):
        w = m.group(0)
        return " ".join(w[i:i+max_len] for i in range(0, len(w), max_len))
    return re.sub(rf"\S{{{max_len},}}", _split, t)


def _pdf_safe(text: str) -> str:
    if text is None:
        return ""
    s = str(text)

    repl = {
        "—": "-", "–": "-", "“": '"', "”": '"', "’": "'",
        "‘": "'", "…": "...", "\u00A0": " ", "•": "-",
        "→": "->",
    }
    for k, v in repl.items():
        s = s.replace(k, v)

    s = _break_long_tokens(s, 40)

    try:
        s = s.encode("latin-1", "ignore").decode("latin-1")
    except Exception:
        pass
    return s


def safe_multi_cell(pdf: FPDF, h: float, text: str, w: float = 0) -> None:
    """
    Multi-cell à prova de crash:
    - reseta X para a margem esquerda
    - quebra tokens longos
    - fallback em chunk se o FPDF ainda reclamar
    """
    pdf.set_x(pdf.l_margin)
    t = _pdf_safe(text)

    try:
        pdf.multi_cell(w, h, t)
        return
    except Exception:
        pass

    # fallback extremo: imprime em blocos curtos
    pdf.set_x(pdf.l_margin)
    chunk = 120
    for i in range(0, len(t), chunk):
        pdf.multi_cell(w, h, t[i:i+chunk])
        pdf.set_x(pdf.l_margin)
