# eba_reports.py
from __future__ import annotations

import io
import os
import tempfile
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import plotly.graph_objects as go
import streamlit as st
from fpdf import FPDF

from eba_config import APP_NAME, APP_VERSION


PRIMARY = "#2C109C"
GOOD = "#15803D"
WARN = "#B45309"
BAD = "#B91C1C"


# -------------------------
# safe text for fpdf latin-1 fonts (helvetica)
# -------------------------
def _pdf_safe(text: str) -> str:
    if text is None:
        return ""
    s = str(text)

    # troca caracteres comuns que quebram helvetica/latin-1
    repl = {
        "—": "-",  # travessão
        "–": "-",  # meia-risca
        "“": '"',
        "”": '"',
        "’": "'",
        "‘": "'",
        "…": "...",
        "\u00A0": " ",  # nbsp
        "•": "-",
        "→": "->",
    }
    for k, v in repl.items():
        s = s.replace(k, v)

    # quebra tokens absurdos (urls gigantes etc.)
    def break_long_tokens(t: str, max_len: int = 80) -> str:
        def _split(m):
            w = m.group(0)
            return " ".join(w[i:i+max_len] for i in range(0, len(w), max_len))
        return re.sub(rf"\S{{{max_len},}}", _split, t)

    s = break_long_tokens(s, 80)

    # força latin-1 "seguro" (remove o que não suportar)
    try:
        s = s.encode("latin-1", "ignore").decode("latin-1")
    except Exception:
        pass
    return s


# =========================
# GRÁFICOS
# =========================
def criar_radar_bfa(traits: Dict[str, float], traits_ideais: Optional[Dict[str, Tuple[float, float]]] = None) -> go.Figure:
    labels = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]
    values = [float(traits.get(k, 0) or 0) for k in labels]

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
        fig.add_trace(go.Scatterpolar(
            r=[float(traits_ideais.get(k, (0, 10))[1]) for k in labels],
            theta=labels,
            name="Ideal Máx",
            line=dict(color=GOOD, dash="dash", width=2),
        ))

    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 10])),
        showlegend=True,
        height=450,
        margin=dict(l=30, r=30, t=60, b=30),
    )
    return fig


def criar_grafico_competencias(competencias: List[Dict[str, Any]]) -> Optional[go.Figure]:
    if not competencias:
        return None

    nomes = [str(c.get("nome", "")) for c in competencias]
    notas = []
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
    ))
    fig.update_layout(height=520, margin=dict(l=160, r=30, t=50, b=30))
    return fig


def criar_gauge_fit(valor: float) -> go.Figure:
    return go.Figure(go.Indicator(
        mode="gauge+number",
        value=float(valor or 0),
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


def _fig_to_png(fig: go.Figure) -> Optional[str]:
    try:
        import plotly.io as pio
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            pio.write_image(fig, tmp.name, width=950, height=650, scale=1)
            return tmp.name
    except Exception as e:
        st.warning(f"Falha ao gerar gráfico (kaleido): {e}")
        return None


# =========================
# PDF
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

    # CAPA (primeira página SEM branco)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 15, _pdf_safe("Relatório Comportamental"), ln=1, align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, _pdf_safe(f"Elder Brain Analytics - {cargo}"), ln=1, align="C")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, _pdf_safe(f"{APP_NAME} {APP_VERSION}"), ln=1, align="C")
    pdf.cell(0, 7, _pdf_safe(f"{datetime.now():%d/%m/%Y %H:%M}"), ln=1, align="C")

    # ================== GRÁFICOS ==================
    traits = bfa_data.get("traits_bfa", {}) or {}
    radar_path = _fig_to_png(criar_radar_bfa(traits))
    if radar_path:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe("Big Five (Radar)"), ln=1)
        pdf.image(radar_path, x=18, w=175)
        try:
            os.remove(radar_path)
        except Exception:
            pass

    comp_fig = criar_grafico_competencias(bfa_data.get("competencias_ms", []) or [])
    if comp_fig:
        comp_path = _fig_to_png(comp_fig)
        if comp_path:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, _pdf_safe("Competências (Barras)"), ln=1)
            pdf.image(comp_path, x=18, w=175)
            try:
                os.remove(comp_path)
            except Exception:
                pass

    fit_path = _fig_to_png(criar_gauge_fit((analysis or {}).get("compatibilidade_geral", 0)))
    if fit_path:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe("Fit para o Cargo"), ln=1)
        pdf.image(fit_path, x=40, w=120)
        try:
            os.remove(fit_path)
        except Exception:
            pass

    out = pdf.output(dest="S")
    if isinstance(out, str):
        out = out.encode("latin-1", "ignore")
    buf = io.BytesIO(out)
    buf.seek(0)
    return buf
