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

from eba_config import gerar_perfil_cargo_dinamico, APP_VERSION

# =========================
# Cores
# =========================
COLOR_PRIMARY = (84, 66, 142)   # roxo
COLOR_HEADER_BG = (235, 237, 240)
COLOR_OK = (46, 204, 113)
COLOR_WARN = (243, 156, 18)
COLOR_BAD = (231, 76, 60)

COLOR_CANDIDATO = "#60519b"
COLOR_IDEAL_MAX = "rgba(46, 213, 115, 0.35)"
COLOR_IDEAL_MIN = "rgba(46, 213, 115, 0.15)"


# =========================
# Helpers gráficos
# =========================
def criar_radar_bfa(
    traits: Dict[str, Optional[float]],
    traits_ideais: Optional[Dict[str, Tuple[float, float]]] = None,
) -> go.Figure:
    labels = [
        "Abertura",
        "Conscienciosidade",
        "Extroversao",
        "Amabilidade",
        "Neuroticismo",
    ]
    vals: List[float] = []
    for k in labels:
        v = traits.get(k, traits.get(k.replace("ã", "a"), 0))
        try:
            vals.append(float(v or 0))
        except Exception:
            vals.append(0.0)

    fig = go.Figure()

    if traits_ideais:
        vmin = [traits_ideais.get(k, (0, 10))[0] for k in labels]
        vmax = [traits_ideais.get(k, (0, 10))[1] for k in labels]
        fig.add_trace(
            go.Scatterpolar(
                r=vmax,
                theta=labels,
                fill="toself",
                name="Faixa Ideal (Máx)",
                line=dict(color=COLOR_OK),
                fillcolor=COLOR_IDEAL_MAX,
            )
        )
        fig.add_trace(
            go.Scatterpolar(
                r=vmin,
                theta=labels,
                fill="tonext",
                name="Faixa Ideal (Mín)",
                line=dict(color=COLOR_OK),
                fillcolor=COLOR_IDEAL_MIN,
            )
        )

    fig.add_trace(
        go.Scatterpolar(
            r=vals,
            theta=labels,
            fill="toself",
            name="Candidato",
            line=dict(color=COLOR_CANDIDATO),
            fillcolor="rgba(96,81,155,0.45)",
        )
    )

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 10])),
        showlegend=True,
        title="Big Five x Perfil Ideal",
        height=500,
    )
    return fig


def criar_grafico_competencias(competencias: List[Dict[str, Any]]) -> Optional[go.Figure]:
    if not competencias:
        return None
    df = pd.DataFrame(competencias).copy()
    if df.empty or "nota" not in df.columns:
        return None

    df = df.sort_values("nota", ascending=True).tail(15)

    cores = []
    for n in df["nota"]:
        if n < 45:
            cores.append(COLOR_BAD)
        elif n < 55:
            cores.append(COLOR_WARN)
        else:
            cores.append(COLOR_OK)

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
        title="Competências MS (Top 15)",
        xaxis_title="Nota",
        yaxis_title="",
        height=550,
        showlegend=False,
    )
    return fig


def criar_gauge_fit(fit_score: float) -> go.Figure:
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=float(fit_score or 0),
            domain={"x": [0, 1], "y": [0, 1]},
            title={"text": "Fit para o Cargo"},
            delta={"reference": 70},
            gauge={
                "axis": {"range": [None, 100]},
                "bar": {"color": "#54428E"},
                "steps": [
                    {"range": [0, 40], "color": "#E74C3C"},
                    {"range": [40, 70], "color": "#F39C12"},
                    {"range": [70, 100], "color": "#2ECC71"},
                ],
                "threshold": {
                    "line": {"color": "#000000", "width": 2},
                    "thickness": 0.75,
                    "value": 70,
                },
            },
        )
    )
    fig.update_layout(height=420)
    return fig


def fig_to_png_path(
    fig: "go.Figure",
    width: int = 1200,
    height: int = 800,
    scale: int = 2,
) -> Optional[str]:
    try:
        import plotly.io as pio

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            pio.write_image(fig, tmp.name, format="png", width=width, height=height, scale=scale)
            return tmp.name
    except Exception:
        return None


# =========================
# PDF
# =========================
class PDFReport(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(15, 15, 15)
        self._family = "Helvetica"

    # limpar texto para evitar erros de unicode
    def _clean(self, s: Optional[str]) -> str:
        if not s:
            return ""
        s = str(s)

        rep = {
            "\u2014": "-",
            "\u2013": "-",
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2026": "...",
            "\u00a0": " ",
            "•": "-",
            "→": "->",
        }
        for k, v in rep.items():
            s = s.replace(k, v)

        # quebra palavras gigantes
        def _split_long(m):
            token = m.group(0)
            parts = [token[i : i + 60] for i in range(0, len(token), 60)]
            return " ".join(parts)

        s = re.sub(r"\S{60,}", _split_long, s)

        try:
            return s.encode("latin-1", "ignore").decode("latin-1")
        except Exception:
            return s

    def header(self):
        # capa (página 1) não tem header
        if self.page_no() == 1:
            return
        self.set_y(10)
        self.set_font(self._family, "B", 9)
        self.set_fill_color(*COLOR_HEADER_BG)
        self.set_text_color(60, 60, 60)
        self.cell(
            0,
            8,
            self._clean(f"Elder Brain Analytics - Relatório Corporativo | {APP_VERSION}"),
            ln=1,
            align="R",
            fill=True,
        )
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def footer(self):
        self.set_y(-18)
        self.set_font(self._family, "", 7)
        self.set_text_color(120, 120, 120)
        txt = (
            "Este relatório tem caráter de apoio à decisão e deve ser interpretado em conjunto com entrevistas. "
            "O Elden Brain trabalha como um braço direito, lembre-se disto."
        )
        self.multi_cell(0, 4, self._clean(txt), align="C")

    def heading(self, numero: int, titulo: str):
        self.set_font(self._family, "B", 11)
        self.set_text_color(40, 40, 40)
        self.set_fill_color(*COLOR_HEADER_BG)
        self.cell(0, 8, self._clean(f"{numero}. {titulo}"), ln=1, fill=True)
        self.ln(2)

    def subheading(self, titulo: str):
        self.set_font(self._family, "B", 10)
        self.cell(0, 6, self._clean(titulo), ln=1)
        self.ln(1)

    def paragraph(self, txt: str, size: int = 9):
        self.set_font(self._family, "", size)
        self.multi_cell(0, 4.5, self._clean(txt))
        self.ln(1)


def _add_capa(pdf: PDFReport):
    pdf.add_page()
    pdf.set_font(pdf._family, "B", 20)
    pdf.ln(10)
    pdf.cell(0, 10, pdf._clean("Elder Brain Analytics"), ln=1, align="C")
    pdf.set_font(pdf._family, "", 11)
    pdf.cell(
        0,
        6,
        pdf._clean("Avaliações comportamentais com inteligência analítica"),
        ln=1,
        align="C",
    )
    pdf.ln(10)
    pdf.set_font(pdf._family, "", 9)
    pdf.paragraph("Desenvolvedor responsável: André de Lima")
    pdf.paragraph(f"Versão: {APP_VERSION}")
    pdf.paragraph(f"Data: {datetime.now():%d/%m/%Y}")


# =========================
# PDF principal
# =========================
def gerar_pdf_corporativo(
    bfa_data: Dict[str, Any],
    analysis: Dict[str, Any],
    cargo: str,
    save_path: Optional[str] = None,
    logo_path: Optional[str] = None,  # mantido só por compat
) -> io.BytesIO:
    pdf = PDFReport()
    _add_capa(pdf)

    # -------- 1. Informações do candidato --------
    pdf.heading(1, "Informações do Candidato")
    cand = bfa_data.get("candidato", {}) or {}
    nome = cand.get("nome", "Não informado") or "Não informado"
    empresa_raw = cand.get("empresa", "Não informado") or "Não informado"
    # remove coisas entre parênteses
    empresa = re.sub(r"\s*\([^)]*\)", "", empresa_raw).strip() or "Não informado"

    pdf.paragraph(f"Nome: {nome}")
    pdf.paragraph(f"Empresa (quando presente no laudo): {empresa}")
    pdf.paragraph(f"Cargo avaliado: {cargo}")
    pdf.paragraph(f"Data da análise: {datetime.now():%d/%m/%Y %H:%M}")

    # -------- 2. Decisão e compatibilidade --------
    pdf.heading(2, "Decisão e Compatibilidade")
    decisao = analysis.get("decisao", "N/A")
    compat = float(analysis.get("compatibilidade_geral", 0) or 0)
    pdf.set_font(pdf._family, "B", 10)
    pdf.paragraph(
        f"DECISÃO: {decisao} | COMPATIBILIDADE GLOBAL: {compat:.0f}%"
    )
    pdf.set_font(pdf._family, "", 9)
    pdf.paragraph(
        "Leitura baseada em traços de personalidade, competências críticas e fatores de saúde emocional."
    )
    justificativa = analysis.get("justificativa_decisao", "")
    if justificativa:
        pdf.subheading("Justificativa resumida")
        pdf.paragraph(justificativa)

    # -------- 3. Resumo executivo --------
    pdf.heading(3, "Resumo Executivo")
    resumo_exec = analysis.get("resumo_executivo", "")
    if resumo_exec:
        pdf.paragraph(resumo_exec)
    else:
        pdf.paragraph(
            "O laudo não trouxe um resumo executivo estruturado. Recomenda-se leitura das seções seguintes."
        )

    # -------- 4. Traços de personalidade --------
    pdf.heading(4, "Traços de Personalidade (Big Five)")
    traits = bfa_data.get("traits_bfa", {}) or {}
    for nome_traco, valor in traits.items():
        try:
            val_str = f"{float(valor):.1f}/10"
        except Exception:
            val_str = f"{valor}/10"
        pdf.paragraph(f"{nome_traco}: {val_str}")

    analise_tracos = analysis.get("analise_tracos", {}) or {}
    if analise_tracos:
        pdf.subheading("Leitura dos traços")
        for nome_traco, texto in analise_tracos.items():
            pdf.paragraph(f"{nome_traco}: {texto}")

    # -------- 5. Visualizações (gráficos) --------
    pdf.add_page()
    pdf.heading(5, "Visualizações (Gráficos)")

    perfil_cargo = gerar_perfil_cargo_dinamico(cargo)
    traits_ideais = perfil_cargo.get("traits_ideais", {}) or {}

    # Radar
    pdf.subheading("Big Five x Perfil Ideal")
    radar_fig = criar_radar_bfa(traits, traits_ideais)
    path = fig_to_png_path(radar_fig, width=1200, height=900, scale=2)
    if path:
        pdf.image(path, w=180)
        try:
            os.remove(path)
        except Exception:
            pass
    pdf.paragraph(
        "Este radar compara o perfil do candidato às faixas ideais para o cargo. "
        "Observe Extroversão, Amabilidade e Abertura (Inovação), além de Neuroticismo (quanto menor, melhor)."
    )

    # Gauge fit
    pdf.subheading("Fit global para o cargo")
    gauge_fig = criar_gauge_fit(compat)
    path = fig_to_png_path(gauge_fig, width=900, height=500, scale=2)
    if path:
        pdf.image(path, w=150)
        try:
            os.remove(path)
        except Exception:
            pass

    pdf.paragraph(
        "O indicador de fit sintetiza os principais fatores comportamentais e emocionais. "
        "Acima de 70% indica boa aderência; entre 40% e 70% sugere aderência parcial com necessidade de "
        "desenvolvimento; abaixo de 40% indica risco maior."
    )

    # -------- Competências MS (top 15) --------
    competencias = bfa_data.get("competencias_ms", []) or []
    if competencias:
        comp_fig = criar_grafico_competencias(competencias)
        if comp_fig:
            pdf.subheading("Competências MS (Top 15)")
            path = fig_to_png_path(comp_fig, width=1400, height=700, scale=2)
            if path:
                pdf.image(path, w=180)
                try:
                    os.remove(path)
                except Exception:
                    pass
            pdf.paragraph(
                "Barras em verde indicam boas evidências de desempenho. Amarelo sugere ponto de atenção e "
                "desenvolvimento. Vermelho indica competências potencialmente críticas para o cargo."
            )

    # -------- 6. Saúde emocional e resiliência --------
    pdf.heading(6, "Saúde Emocional e Resiliência")
    saude_txt = analysis.get("saude_emocional_contexto", "")
    if saude_txt:
        pdf.paragraph(saude_txt)

    indicadores = bfa_data.get("indicadores_saude_emocional", {}) or {}
    if indicadores:
        pdf.subheading("Indicadores quantitativos")
        for k, v in indicadores.items():
            if v is None:
                continue
            nome = k.replace("_", " ").capitalize()
            pdf.paragraph(f"{nome}: {float(v):.0f}/100")
        pdf.paragraph(
            "Valores mais elevados em estresse, ansiedade ou impulsividade podem indicar maior "
            "vulnerabilidade emocional. Valores mais baixos favorecem resiliência e estabilidade, "
            "principalmente em funções de alta pressão."
        )

    # -------- 7. Pontos fortes --------
    pontos_fortes = bfa_data.get("pontos_fortes", []) or []
    pdf.heading(7, "Pontos Fortes")
    if pontos_fortes:
        pdf.paragraph(
            "Aspectos em que o candidato demonstra maior aderência ao cargo ou potenciais diferenciais competitivos."
        )
        for item in pontos_fortes:
            pdf.paragraph(f"- {item}")
    else:
        pdf.paragraph("Não foram destacados pontos fortes específicos no laudo.")

    # -------- 8. Pontos de atenção --------
    pontos_atencao = bfa_data.get("pontos_atencao", []) or []
    pdf.heading(8, "Pontos de Atenção")
    if pontos_atencao:
        pdf.paragraph(
            "Aspectos que podem demandar acompanhamento próximo, feedback estruturado ou plano de desenvolvimento, "
            "especialmente nos primeiros meses."
        )
        for item in pontos_atencao:
            pdf.paragraph(f"- {item}")
    else:
        pdf.paragraph("Não foram identificados pontos de atenção estruturados no laudo.")

    # -------- 9. Recomendações de desenvolvimento --------
    pdf.heading(9, "Recomendações de Desenvolvimento")
    recs = analysis.get("recomendacoes_desenvolvimento", []) or []
    if recs:
        pdf.paragraph(
            "Sugestões de ações práticas e trilhas de aprendizagem para apoiar o desenvolvimento do candidato "
            "no médio prazo."
        )
        for i, rec in enumerate(recs, start=1):
            pdf.paragraph(f"{i}. {rec}")
    else:
        pdf.paragraph(
            "Não foram sugeridas recomendações específicas de desenvolvimento pelo modelo neste laudo."
        )

    # -------- 10. Cargos alternativos --------
    pdf.heading(10, "Cargos Alternativos Sugeridos")
    alt = analysis.get("cargos_alternativos", []) or []
    if alt:
        pdf.paragraph(
            "Sugestões de posições em que o perfil mapeado pode apresentar boa aderência, "
            "considerando os traços comportamentais observados."
        )
        for cargo_alt in alt:
            nome_cargo = cargo_alt.get("cargo", "")
            just = cargo_alt.get("justificativa", "")
            if not nome_cargo:
                continue
            pdf.paragraph(f"- {nome_cargo}")
            if just:
                pdf.paragraph(f"  {just}")
    else:
        pdf.paragraph(
            "Não foram sugeridos cargos alternativos específicos com base neste laudo."
        )

    # observação final (igual ao modelo)
    pdf.paragraph(
        "Este documento não substitui entrevistas, referências e demais etapas do processo seletivo. "
        "Recomenda-se leitura conjunta com o contexto da vaga e cultura da empresa."
    )

    out = pdf.output(dest="S")
    if isinstance(out, str):
        out = out.encode("latin-1", "replace")
    buf = io.BytesIO(out)
    buf.seek(0)

    if save_path:
        try:
            with open(save_path, "wb") as f:
                f.write(buf.getbuffer())
        except Exception:
            pass

    return buf
