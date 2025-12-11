from __future__ import annotations

import io
import os
import re
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
from fpdf import FPDF

from eba_config import gerar_perfil_cargo_dinamico

# =========================================================
#  PALETA DE CORES PREMIUM
# =========================================================

COLOR_PRIMARY = "#54428E"         # roxo corporativo premium
COLOR_ACCENT = "#2ECC71"          # verde positivo
COLOR_WARNING = "#F39C12"
COLOR_DANGER = "#E74C3C"

COLOR_RADAR = "#60519b"
COLOR_IDEAL_MAX = "rgba(46, 213, 115, 0.35)"
COLOR_IDEAL_MIN = "rgba(46, 213, 115, 0.15)"


# =========================================================
#  GRÁFICOS
# =========================================================

def criar_radar_bfa(
    traits: Dict[str, float],
    traits_ideais: Dict[str, Tuple[float, float]],
) -> go.Figure:
    labels = [
        "Abertura",
        "Conscienciosidade",
        "Extroversão",
        "Amabilidade",
        "Neuroticismo",
    ]

    vals: List[float] = []
    for k in labels:
        v = traits.get(k, traits.get(k.lower(), 0))
        vals.append(float(v or 0))

    fig = go.Figure()

    vmax = [traits_ideais.get(k, (0, 10))[1] for k in labels]
    vmin = [traits_ideais.get(k, (0, 10))[0] for k in labels]

    # faixa ideal
    fig.add_trace(
        go.Scatterpolar(
            r=vmax,
            theta=labels,
            fill="toself",
            name="Faixa Ideal (Máx)",
            line=dict(color=COLOR_ACCENT),
            fillcolor=COLOR_IDEAL_MAX,
        )
    )

    fig.add_trace(
        go.Scatterpolar(
            r=vmin,
            theta=labels,
            fill="tonext",
            name="Faixa Ideal (Mín)",
            line=dict(color=COLOR_ACCENT),
            fillcolor=COLOR_IDEAL_MIN,
        )
    )

    # candidato
    fig.add_trace(
        go.Scatterpolar(
            r=vals,
            theta=labels,
            fill="toself",
            name="Candidato",
            line=dict(color=COLOR_RADAR, width=3),
            fillcolor="rgba(96,81,155,0.4)",
        )
    )

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 10])),
        showlegend=True,
        title="Radar Big Five x Perfil Ideal",
        height=500,
    )
    return fig


def criar_grafico_competencias(
    competencias: List[Dict[str, Any]]
) -> Optional[go.Figure]:
    if not competencias:
        return None

    df = pd.DataFrame(competencias)
    if df.empty or "nota" not in df.columns:
        return None

    df = df.sort_values("nota", ascending=True).tail(15)

    cores = []
    for n in df["nota"]:
        if n < 45:
            cores.append(COLOR_DANGER)
        elif n < 55:
            cores.append(COLOR_WARNING)
        else:
            cores.append(COLOR_ACCENT)

    fig = go.Figure(
        go.Bar(
            x=df["nota"],
            y=df["nome"],
            orientation="h",
            marker=dict(color=cores),
            text=df["nota"].round(0).astype(int),
            textposition="outside",
        )
    )

    fig.update_layout(
        title="Top 15 Competências (MS)",
        height=600,
        xaxis_title="Nota",
        yaxis_title="",
    )
    return fig


def criar_gauge_fit(fit_score: float) -> go.Figure:
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=float(fit_score or 0),
            domain={"x": [0, 1], "y": [0, 1]},
            title={"text": "Fit para o Cargo"},
            gauge={
                "axis": {"range": [None, 100]},
                "bar": {"color": COLOR_PRIMARY},
                "steps": [
                    {"range": [0, 40], "color": COLOR_DANGER},
                    {"range": [40, 70], "color": COLOR_WARNING},
                    {"range": [70, 100], "color": COLOR_ACCENT},
                ],
            },
        )
    )
    fig.update_layout(height=420)
    return fig


# =========================================================
#  FIG → PNG
# =========================================================

def fig_to_png_path(
    fig: "go.Figure",
    width: int = 1400,
    height: int = 900,
    scale: int = 2,
) -> Optional[str]:
    try:
        import plotly.io as pio

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            pio.write_image(
                fig, tmp.name, format="png", width=width, height=height, scale=scale
            )
            return tmp.name
    except Exception:
        return None


# =========================================================
#  RESUMOS (VERSÃO COMPLETA)
# =========================================================

def resumo_radar(traits: Dict[str, float]) -> str:
    """
    Versão detalhada baseada no trecho antigo:
      - destaca Neuroticismo (resiliência emocional)
      - destaca Extroversão (estilo de interação)
    """
    neuro = float(traits.get("Neuroticismo", 0) or 0)
    ext = float(traits.get("Extroversão", 0) or 0)

    msgs: List[str] = []

    if neuro > 60:
        msgs.append(
            "- Neuroticismo elevado -> pode prejudicar resiliência emocional e aumentar "
            "sensibilidade a críticas, frustrações e ambientes de alta pressão."
        )
    else:
        msgs.append(
            "- Neuroticismo dentro de faixa adequada -> tendência a maior estabilidade emocional "
            "e melhor recuperação após situações de estresse."
        )

    if ext < 40:
        msgs.append(
            "- Extroversão baixa -> estilo mais reservado, com preferência por interações focadas "
            "e contextos de menor exposição social."
        )
    else:
        msgs.append(
            "- Extroversão adequada ao perfil esperado -> maior conforto em interagir, comunicar-se "
            "com o time e atuar em ambientes colaborativos."
        )

    return "\n".join(msgs)


def resumo_competencias(competencias: List[Dict[str, Any]]) -> str:
    """
    Versão detalhada: destaca forças (>=55) e gaps (<45).
    """
    if not competencias:
        return "Nenhuma competência foi identificada de forma estruturada no laudo."

    acima = sum(1 for c in competencias if c.get("nota", 0) >= 55)
    abaixo = sum(1 for c in competencias if c.get("nota", 0) < 45)

    return (
        f"- {acima} competências acima da linha verde (forças consolidadas).\n"
        f"- {abaixo} competências abaixo da linha vermelha (pontos críticos de atenção, "
        "que podem comprometer o desempenho se não forem trabalhados)."
    )


def resumo_fit(fit: float) -> str:
    """
    Versão explicativa da aderência geral.
    """
    fit = float(fit or 0)
    if fit >= 80:
        return (
            "Fit muito alto: forte aderência ao cargo, com riscos comportamentais bem controlados. "
            "O perfil tende a sustentar desempenho consistente, com menor probabilidade de conflitos "
            "com as demandas típicas da função."
        )
    elif fit >= 60:
        return (
            "Fit moderado: aderência geral boa, porém com alguns pontos específicos que exigem plano "
            "de desenvolvimento. A recomendação é observar os pontos de atenção e alinhar expectativas "
            "claramente com liderança e RH."
        )
    else:
        return (
            "Fit baixo: desalinhamento relevante entre o perfil atual e as demandas do cargo. "
            "Este candidato pode performar melhor em funções com outra dinâmica de cobrança, "
            "complexidade ou relacionamento interpessoal."
        )


# =========================================================
#  PDF PREMIUM
# =========================================================

class PDFReport(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(15, 15, 15)
        self._family = "Helvetica"

    # rodapé em todas as páginas
    def footer(self):
        self.set_y(-20)
        self.set_font(self._family, "I", 8)
        self.set_text_color(120, 120, 120)
        txt = (
            "Este relatório tem caráter de apoio à decisão e deve ser interpretado em conjunto com entrevistas. "
            "O Elden Brain trabalha como um braço direito, lembre-se disto."
        )
        cleaned = self._clean_text(txt)
        self.multi_cell(0, 4, cleaned, align="C")

    def heading(self, number: int, title: str):
        self.set_font(self._family, "B", 13)
        self.set_text_color(255, 255, 255)
        self.set_fill_color(84, 66, 142)
        texto = self._clean_text(f"{number}. {title}")
        self.cell(0, 10, texto, ln=1, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def paragraph(self, text: str, size: int = 10):
        self.set_font(self._family, "", size)
        cleaned = self._clean_text(text)
        self.multi_cell(0, 5, cleaned)
        self.ln(1)

    def _clean_text(self, s: str) -> str:
        if not s:
            return ""

        rep = {
            "\u2014": "-",   # em dash
            "\u2013": "-",   # en dash
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2026": "...",
            "\u00a0": " ",
            "•": "-",        # bullet
            "→": "->",       # seta
        }
        for k, v in rep.items():
            s = s.replace(k, v)

        # quebra palavras gigantes sem espaço
        s = re.sub(
            r"\S{60,}",
            lambda m: " ".join(
                m.group(0)[i : i + 60] for i in range(0, len(m.group(0)), 60)
            ),
            s,
        )

        try:
            return s.encode("latin-1", "ignore").decode("latin-1")
        except Exception:
            return s


def pdf_cover(pdf: PDFReport, titulo: str, subtitulo: str):
    pdf.add_page()

    # faixa roxa no topo
    pdf.set_fill_color(84, 66, 142)
    pdf.rect(0, 0, pdf.w, 30, "F")

    pdf.ln(45)
    pdf.set_font(pdf._family, "B", 26)
    pdf.set_text_color(84, 66, 142)
    pdf.cell(0, 12, pdf._clean_text(titulo), ln=1, align="C")

    pdf.set_font(pdf._family, "", 13)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, pdf._clean_text(subtitulo), ln=1, align="C")

    pdf.ln(10)
    pdf.set_font(pdf._family, "", 9)
    pdf.set_text_color(100, 100, 100)
    info = f"Gerado em {datetime.now():%d/%m/%Y %H:%M} | Versão Premium"
    pdf.cell(0, 6, pdf._clean_text(info), ln=1, align="C")
    pdf.set_text_color(0, 0, 0)


# =========================================================
#  GERAÇÃO DO PDF COMPLETO
# =========================================================

def gerar_pdf_corporativo(
    bfa_data: Dict[str, Any],
    analysis: Dict[str, Any],
    cargo: str,
    save_path: Optional[str] = None,
    logo_path: Optional[str] = None,  # mantido só p/ compatibilidade
) -> io.BytesIO:
    pdf = PDFReport()

    # CAPA
    pdf_cover(pdf, "Relatório Corporativo", f"Elder Brain Analytics - {cargo}")

    # 1. INFORMAÇÕES DO CANDIDATO
    pdf.heading(1, "Informações do Candidato")
    cand = bfa_data.get("candidato", {}) or {}
    nome = cand.get("nome", "Não informado") or "Não informado"

    # empresa limpando qualquer coisa entre parênteses
    empresa_raw = cand.get("empresa", "Não informado") or "Não informado"
    empresa = re.sub(r"\s*\([^)]*\)", "", empresa_raw).strip() or "Não informado"

    pdf.paragraph(
        f"Nome: {nome}\n"
        f"Empresa (extraída do laudo): {empresa}\n"
        f"Cargo avaliado: {cargo}"
    )

    # 2. DECISÃO E COMPATIBILIDADE
    pdf.heading(2, "Decisão e Compatibilidade")
    decisao = analysis.get("decisao", "N/A")
    compat = float(analysis.get("compatibilidade_geral", 0) or 0)
    pdf.paragraph(f"Decisão final: {decisao}")
    pdf.paragraph(f"Compatibilidade geral com o cargo: {compat:.0f}%")
    pdf.paragraph(resumo_fit(compat))

    # 3. RESUMO EXECUTIVO
    pdf.heading(3, "Resumo Executivo")
    resumo_exec = analysis.get("resumo_executivo", "")
    if resumo_exec:
        pdf.paragraph(resumo_exec)
    else:
        pdf.paragraph(
            "O laudo não trouxe um resumo executivo estruturado. Recomenda-se a leitura "
            "integral das seções de personalidade, competências e saúde emocional."
        )

    # 4. TRAÇOS DE PERSONALIDADE (BIG FIVE)
    pdf.heading(4, "Traços de Personalidade (Big Five)")
    traits = bfa_data.get("traits_bfa", {}) or {}
    for nome_traco, valor in traits.items():
        pdf.paragraph(f"{nome_traco}: {valor}/10")
    pdf.paragraph("Leitura sintética:\n" + resumo_radar(traits))

    # 5. VISUALIZAÇÕES (GRÁFICOS)
    pdf.heading(5, "Visualizações (Gráficos)")

    perfil_cargo = gerar_perfil_cargo_dinamico(cargo)
    traits_ideais = perfil_cargo.get("traits_ideais", {}) or {}

    # Radar
    radar_fig = criar_radar_bfa(traits, traits_ideais)
    path = fig_to_png_path(radar_fig)
    if path:
        pdf.image(path, w=180)
        try:
            os.remove(path)
        except Exception:
            pass
    pdf.paragraph("Resumo do radar Big Five:\n" + resumo_radar(traits))

    # Gauge de fit
    gauge_fig = criar_gauge_fit(compat)
    path = fig_to_png_path(gauge_fig)
    if path:
        pdf.image(path, w=120)
        try:
            os.remove(path)
        except Exception:
            pass
    pdf.paragraph("Resumo do fit:\n" + resumo_fit(compat))

    # Competências
    competencias = bfa_data.get("competencias_ms", []) or []
    comp_fig = criar_grafico_competencias(competencias)
    if comp_fig:
        path = fig_to_png_path(comp_fig)
        if path:
            pdf.image(path, w=180)
            try:
                os.remove(path)
            except Exception:
                pass
        pdf.paragraph("Leitura das competências:\n" + resumo_competencias(competencias))
    else:
        pdf.paragraph("Não foi possível gerar gráfico de competências estruturadas.")

    # SAÍDA
    out = pdf.output(dest="S")
    if isinstance(out, str):
        out = out.encode("latin-1", "replace")
    buf = io.BytesIO(out)
    buf.seek(0)

    if save_path:
        try:
            with open(save_path, "wb") as f:
                f.write(buf.getvalue())
        except Exception:
            pass

    return buf
