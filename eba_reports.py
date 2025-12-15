# eba_reports.py
from __future__ import annotations

import io
import os
import tempfile
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import plotly.graph_objects as go
import streamlit as st
from fpdf import FPDF

from eba_config import APP_NAME, APP_VERSION


# =========================
# CORES
# =========================
PRIMARY = "#2C109C"
GOOD = "#15803D"
WARN = "#B45309"
BAD = "#B91C1C"


# =========================
# GRÁFICOS
# =========================
def criar_radar_bfa(traits: Dict[str, float], traits_ideais: Optional[Dict[str, Tuple[float, float]]] = None) -> go.Figure:
    labels = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]
    values = [float(traits.get(k, 0)) for k in labels]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=labels,
        fill="toself",
        name="Candidato",
        line=dict(color=PRIMARY),
    ))

    if traits_ideais:
        fig.add_trace(go.Scatterpolar(
            r=[traits_ideais[k][1] for k in labels],
            theta=labels,
            name="Ideal Máx",
            line=dict(color=GOOD, dash="dash"),
        ))

    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 10])),
        showlegend=True,
        height=450,
    )
    return fig


def criar_grafico_competencias(competencias: List[Dict[str, Any]]) -> Optional[go.Figure]:
    if not competencias:
        return None

    nomes = [c["nome"] for c in competencias]
    notas = [float(c["nota"]) for c in competencias]
    cores = [BAD if n < 45 else WARN if n < 55 else GOOD for n in notas]

    fig = go.Figure(go.Bar(
        x=notas,
        y=nomes,
        orientation="h",
        marker_color=cores,
    ))
    fig.update_layout(height=500)
    return fig


def criar_gauge_fit(valor: float) -> go.Figure:
    return go.Figure(go.Indicator(
        mode="gauge+number",
        value=float(valor),
        gauge={"axis": {"range": [0, 100]}},
    ))


def _fig_to_png(fig: go.Figure) -> Optional[str]:
    try:
        import plotly.io as pio
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            pio.write_image(fig, tmp.name, width=900, height=600, scale=1)
            return tmp.name
    except Exception as e:
        st.warning(f"Falha ao gerar gráfico: {e}")
        return None


# =========================
# PDF
# =========================
class PDFReport(FPDF):
    def __init__(self):
        super().__init__()
        self.set_margins(15, 16, 15)
        self.set_auto_page_break(auto=True, margin=18)

    def header(self):
        pass

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.cell(0, 8, f"Página {self.page_no()}", align="C")


def gerar_pdf_corporativo(
    bfa_data: Dict[str, Any],
    analysis: Dict[str, Any],
    cargo: str,
) -> io.BytesIO:
    pdf = PDFReport()

    # CAPA (ÚNICA CHAMADA add_page)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 15, "Relatório Comportamental", ln=1, align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"Elder Brain Analytics — {cargo}", ln=1, align="C")
    pdf.ln(10)
    pdf.cell(0, 8, f"{APP_NAME} {APP_VERSION}", ln=1, align="C")
    pdf.cell(0, 8, f"{datetime.now():%d/%m/%Y %H:%M}", ln=1, align="C")

    # GRÁFICOS
    traits = bfa_data.get("traits_bfa", {})
    radar = _fig_to_png(criar_radar_bfa(traits))
    if radar:
        pdf.add_page()
        pdf.image(radar, x=20, w=170)
        os.remove(radar)

    comp_fig = criar_grafico_competencias(bfa_data.get("competencias_ms", []))
    if comp_fig:
        comp = _fig_to_png(comp_fig)
        if comp:
            pdf.add_page()
            pdf.image(comp, x=20, w=170)
            os.remove(comp)

    gauge = _fig_to_png(criar_gauge_fit(analysis.get("compatibilidade_geral", 0)))
    if gauge:
        pdf.add_page()
        pdf.image(gauge, x=40, w=120)
        os.remove(gauge)

    out = pdf.output(dest="S").encode("latin-1")
    buf = io.BytesIO(out)
    buf.seek(0)
    return buf
