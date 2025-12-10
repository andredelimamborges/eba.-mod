from __future__ import annotations

import os
import io
import re
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
from fpdf import FPDF


# =========================================================
#  PALETA DE CORES PREMIUM ELEGANTE
# =========================================================

COLOR_PRIMARY = "#54428E"         # Roxo corporativo premium
COLOR_PRIMARY_LIGHT = "#7D6BB3"
COLOR_ACCENT = "#2ECC71"          # Verde para destaques positivos
COLOR_WARNING = "#F39C12"
COLOR_DANGER = "#E74C3C"

COLOR_RADAR = "#60519b"
COLOR_IDEAL_MAX = "rgba(46, 213, 115, 0.35)"
COLOR_IDEAL_MIN = "rgba(46, 213, 115, 0.15)"


# =========================================================
#  GRÁFICOS
# =========================================================

def criar_radar_bfa(traits: Dict[str, float], traits_ideais: Dict[str, Tuple[float, float]]):
    labels = [
        "Abertura",
        "Conscienciosidade",
        "Extroversão",
        "Amabilidade",
        "Neuroticismo",
    ]

    # normalizar valores
    vals = []
    for k in labels:
        v = traits.get(k, traits.get(k.lower(), 0))
        vals.append(float(v or 0))

    fig = go.Figure()

    # faixa ideal
    vmax = [traits_ideais.get(k, (0, 10))[1] for k in labels]
    vmin = [traits_ideais.get(k, (0, 10))[0] for k in labels]

    fig.add_trace(go.Scatterpolar(
        r=vmax, theta=labels,
        fill="toself",
        name="Faixa Ideal (Máx)",
        line=dict(color=COLOR_ACCENT),
        fillcolor=COLOR_IDEAL_MAX
    ))

    fig.add_trace(go.Scatterpolar(
        r=vmin, theta=labels,
        fill="tonext",
        name="Faixa Ideal (Mín)",
        line=dict(color=COLOR_ACCENT),
        fillcolor=COLOR_IDEAL_MIN
    ))

    # valores do candidato
    fig.add_trace(go.Scatterpolar(
        r=vals, theta=labels,
        fill="toself", name="Candidato",
        line=dict(color=COLOR_RADAR, width=3),
        fillcolor="rgba(96,81,155,0.4)"
    ))

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 10])),
        showlegend=True,
        title="Radar Big Five x Perfil Ideal",
        height=500,
    )
    return fig


def criar_grafico_competencias(competencias: List[Dict[str, Any]]) -> Optional[go.Figure]:
    if not competencias:
        return None

    df = pd.DataFrame(competencias)
    if df.empty or "nota" not in df.columns:
        return None

    df = df.sort_values("nota", ascending=True).tail(15)

    # cores premium
    cores = []
    for n in df["nota"]:
        if n < 45:
            cores.append(COLOR_DANGER)
        elif n < 55:
            cores.append(COLOR_WARNING)
        else:
            cores.append(COLOR_ACCENT)

    fig = go.Figure(go.Bar(
        x=df["nota"],
        y=df["nome"],
        orientation="h",
        marker=dict(color=cores),
        text=df["nota"].round(0).astype(int),
        textposition="outside",
    ))

    fig.update_layout(
        title="Top 15 Competências (MS)",
        height=600,
        xaxis_title="Nota",
        yaxis_title=""
    )

    return fig


def criar_gauge_fit(fit_score: float) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=float(fit_score or 0),
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': "Fit para o Cargo"},
        gauge={
            'axis': {'range': [None, 100]},
            'bar': {'color': COLOR_PRIMARY},
            'steps': [
                {'range': [0, 40], 'color': COLOR_DANGER},
                {'range': [40, 70], 'color': COLOR_WARNING},
                {'range': [70, 100], 'color': COLOR_ACCENT},
            ],
        }
    ))
    fig.update_layout(height=420)
    return fig


# =========================================================
#  CONVERSÃO DE FIGURA PARA PNG TEMPORÁRIO
# =========================================================

def fig_to_png_path(fig, width=1400, height=900, scale=2):
    try:
        import plotly.io as pio
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            pio.write_image(fig, tmp.name, format="png", width=width, height=height, scale=scale)
            return tmp.name
    except Exception:
        return None


# =========================================================
#  CLASSE DE PDF — PREMIUM CORPORATE DESIGN
# =========================================================

class PDFReport(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(15, 15, 15)
        self._family = "Helvetica"  # será substituído se Montserrat carregar
        self._unicode = False

    def footer(self):
        if self.page_no() == 1:
            return
        
        self.set_y(-15)
        self.set_font(self._family, "I", 8)
        self.set_text_color(120, 120, 120)
        txt = (
            "Este relatório tem caráter de apoio à decisão e deve ser interpretado em conjunto com entrevistas. "
            "O Elden Brain trabalha como um braço direito — lembre-se disto."
        )
        self.multi_cell(0, 4, txt, align="C")

    def heading(self, number: int, title: str):
        self.set_font(self._family, "B", 13)
        self.set_text_color(255, 255, 255)
        self.set_fill_color(84, 66, 142)
        self.cell(0, 10, f"{number}. {title}", ln=1, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def paragraph(self, text: str, size=10):
        self.set_font(self._family, "", size)
        cleaned = self._clean_text(text)
        self.multi_cell(0, 5, cleaned)
        self.ln(1)

    def safe_add_page(self):
        """Evita páginas em branco entre seções."""
        # se estamos muito perto do final da página, quebra antes
        if self.get_y() > 240:
            self.add_page()

    def _clean_text(self, s: str):
        if not s:
            return ""
        rep = {
            "\u2014": "-",
            "\u2013": "-",
            "\u00a0": " ",
        }
        for k, v in rep.items():
            s = s.replace(k, v)

        # quebra palavras gigantes
        s = re.sub(r"\S{60,}", lambda m: " ".join(
            m.group(0)[i:i+60] for i in range(0, len(m.group(0)), 60)
        ), s)

        try:
            return s.encode("latin-1", "ignore").decode("latin-1")
        except:
            return s


# =========================================================
#  CAPA
# =========================================================

def pdf_cover(pdf: PDFReport, titulo, subtitulo):
    pdf.add_page()
    pdf.set_fill_color(84, 66, 142)
    pdf.rect(0, 0, pdf.w, 30, "F")

    pdf.ln(45)
    pdf.set_font(pdf._family, "B", 26)
    pdf.set_text_color(84, 66, 142)
    pdf.cell(0, 12, titulo, align="C", ln=1)

    pdf.set_font(pdf._family, "", 13)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, subtitulo, align="C", ln=1)

    pdf.ln(10)
    pdf.set_font(pdf._family, "", 9)
    pdf.cell(
        0, 6,
        f"Gerado em {datetime.now():%d/%m/%Y %H:%M} | Versão Premium",
        align="C",
        ln=1,
    )


# =========================================================
#  RESUMO DOS GRÁFICOS
# =========================================================

def resumo_radar(traits: Dict[str, float]) -> str:
    neuro = traits.get("Neuroticismo", 0)
    ext = traits.get("Extroversão", 0)

    msg = []
    
    if neuro > 60:
        msg.append("• Neuroticismo elevado → pode prejudicar resiliência emocional.")
    else:
        msg.append("• Neuroticismo dentro da faixa → boa estabilidade emocional.")

    if ext < 40:
        msg.append("• Extroversão baixa → estilo mais reservado, atenção em funções de contato contínuo.")
    else:
        msg.append("• Extroversão adequada ao perfil esperado.")

    return "\n".join(msg)


def resumo_competencias(competencias: List[Dict[str, Any]]) -> str:
    if not competencias:
        return "Nenhuma competência encontrada no laudo."

    acima = sum(1 for c in competencias if c["nota"] >= 55)
    abaixo = sum(1 for c in competencias if c["nota"] < 45)

    return (
        f"• {acima} competências acima da linha verde (fortes).  \n"
        f"• {abaixo} competências abaixo da linha vermelha (pontos críticos)."
    )


def resumo_fit(fit: float) -> str:
    if fit >= 80:
        return "Fit muito alto: forte aderência ao cargo."
    elif fit >= 60:
        return "Fit moderado: alguns pontos precisam de desenvolvimento."
    else:
        return "Fit baixo: risco de desalinhamento com as exigências do cargo."


# =========================================================
#  GERAÇÃO COMPLETA DO PDF
# =========================================================

def gerar_pdf_corporativo(bfa_data, analysis, cargo, save_path=None, logo_path=None):
    pdf = PDFReport()

    # --- CAPA ---
    pdf_cover(pdf, "Relatório Corporativo", f"Elder Brain Analytics — {cargo}")

    # --- SEÇÃO 1 ---
    pdf.heading(1, "Informações do Candidato")
    cand = bfa_data.get("candidato", {})

    pdf.paragraph(
        f"Nome: {cand.get('nome', 'Não informado')}\n"
        f"Empresa (extraída do laudo): {cand.get('empresa', 'Não informado')}\n"
        f"Cargo Avaliado: {cargo}"
    )

    # --- SEÇÃO 2 ---
    pdf.heading(2, "Decisão e Compatibilidade")
    decisao = analysis.get("decisao", "N/A")
    compat = float(analysis.get("compatibilidade_geral", 0))

    pdf.paragraph(f"Decisão: {decisao}")
    pdf.paragraph(f"Compatibilidade Geral: {compat:.0f}%")
    pdf.paragraph(resumo_fit(compat))

    # --- SEÇÃO 3 ---
    pdf.heading(3, "Resumo Executivo")
    pdf.paragraph(analysis.get("resumo_executivo", ""))

    # --- SEÇÃO 4 ---
    pdf.heading(4, "Traços de Personalidade (Big Five)")

    traits = bfa_data.get("traits_bfa", {})

    for k, v in traits.items():
        pdf.paragraph(f"{k}: {v}")

    pdf.paragraph("Interpretação:\n" + resumo_radar(traits))

    # --- SEÇÃO 5: GRÁFICOS ---
    pdf.safe_add_page()
    pdf.heading(5, "Visualizações (Gráficos)")

    # Radar
    radar = criar_radar_bfa(traits, analysis.get("perfil_ideal", {}))
    path = fig_to_png_path(radar)
    if path:
        pdf.image(path, w=180)
        os.remove(path)
    pdf.paragraph(resumo_radar(traits))

    # Fit gauge
    gauge = criar_gauge_fit(compat)
    path = fig_to_png_path(gauge)
    if path:
        pdf.image(path, w=120)
        os.remove(path)
    pdf.paragraph(resumo_fit(compat))

    # Competências
    competencias = bfa_data.get("competencias_ms", [])
    comp_fig = criar_grafico_competencias(competencias)
    if comp_fig:
        path = fig_to_png_path(comp_fig)
        if path:
            pdf.image(path, w=180)
            os.remove(path)
        pdf.paragraph(resumo_competencias(competencias))

    # SALVAR
    out = pdf.output(dest="S").encode("latin-1", "replace")
    buf = io.BytesIO(out)
    buf.seek(0)

    if save_path:
        with open(save_path, "wb") as f:
            f.write(buf.getvalue())

    return buf
