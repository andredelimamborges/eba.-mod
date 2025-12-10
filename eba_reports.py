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
import streamlit as st

from eba_config import APP_NAME, APP_VERSION, APP_TAGLINE

# =================== CORES (ESTILO B - NEUTRO CORPORATIVO) ===================

COLOR_PRIMARY = "#2d3e50"   # azul petróleo
COLOR_SECONDARY = "#4b6584"  # azul acinzentado
COLOR_MUTED = "#e5e7eb"      # cinza claro de fundo/box

COLOR_CANDIDATO = "#34495e"  # traço do candidato
COLOR_IDEAL_MAX = "rgba(46, 213, 115, 0.35)"  # verde claro
COLOR_IDEAL_MIN = "rgba(46, 213, 115, 0.15)"  # verde mais suave

COLOR_WARN = "#F39C12"
COLOR_GOOD = "#2ECC71"
COLOR_BAD = "#E74C3C"

# texto fixo de rodapé
FOOTER_TEXT = (
    "Este relatório tem caráter de apoio à decisão e deve ser interpretado em conjunto "
    "com entrevistas. O Elden Brain trabalha como um braço direito, lembre-se disto."
)


# =================== GRÁFICOS ===================

def criar_radar_bfa(
    traits: Dict[str, Optional[float]],
    traits_ideais: Optional[Dict[str, Tuple[float, float]]] = None,
) -> go.Figure:
    """
    Radar Big Five x Perfil Ideal.
    """
    labels = [
        "Abertura",
        "Conscienciosidade",
        "Extroversão",
        "Amabilidade",
        "Neuroticismo",
    ]
    vals: List[float] = []
    for k in labels:
        v = traits.get(k, None)
        if v is None:
            norm = (
                k.replace("ã", "a")
                .replace("ç", "c")
                .replace("õ", "o")
                .replace("é", "e")
                .replace("ó", "o")
            )
            v = traits.get(norm, 0)
        try:
            vals.append(float(v or 0))
        except Exception:
            vals.append(0.0)

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=vals,
            theta=labels,
            fill="toself",
            name="Candidato",
            line=dict(color=COLOR_CANDIDATO, width=3),
        )
    )

    if traits_ideais:
        vmin = [traits_ideais.get(k, (0, 10))[0] for k in labels]
        vmax = [traits_ideais.get(k, (0, 10))[1] for k in labels]
        fig.add_trace(
            go.Scatterpolar(
                r=vmax,
                theta=labels,
                fill="toself",
                name="Faixa Ideal (Máx)",
                line=dict(color=COLOR_GOOD, width=1),
                fillcolor=COLOR_IDEAL_MAX,
            )
        )
        fig.add_trace(
            go.Scatterpolar(
                r=vmin,
                theta=labels,
                fill="tonext",
                name="Faixa Ideal (Mín)",
                line=dict(color=COLOR_GOOD, width=1),
                fillcolor=COLOR_IDEAL_MIN,
            )
        )

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 10],
                tickfont=dict(size=10),
            )
        ),
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, x=0.5, xanchor="center"),
        showlegend=True,
        title="Big Five x Perfil Ideal",
        height=500,
        margin=dict(l=60, r=60, t=60, b=80),
    )
    return fig


def criar_grafico_competencias(competencias: List[Dict[str, Any]]) -> Optional[go.Figure]:
    """
    Gráfico horizontal de competências MS.
    """
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
        elif n < 56:
            cores.append(COLOR_WARN)
        else:
            cores.append(COLOR_GOOD)

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
        height=600,
        showlegend=False,
        margin=dict(l=120, r=40, t=60, b=60),
    )
    fig.add_vline(x=45, line_dash="dash", line_color=COLOR_BAD)
    fig.add_vline(x=55, line_dash="dash", line_color=COLOR_WARN)
    fig.add_vline(x=70, line_dash="dot", line_color=COLOR_GOOD)
    return fig


def criar_gauge_fit(fit_score: float) -> go.Figure:
    """
    Gauge de fit para o cargo.
    """
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=float(fit_score or 0),
            domain={"x": [0, 1], "y": [0, 1]},
            title={"text": "Fit para o Cargo", "font": {"size": 22}},
            delta={"reference": 70},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": COLOR_PRIMARY},
                "steps": [
                    {"range": [0, 40], "color": COLOR_BAD},
                    {"range": [40, 70], "color": COLOR_WARN},
                    {"range": [70, 100], "color": COLOR_GOOD},
                ],
                "threshold": {
                    "line": {"color": "#ff0040", "width": 4},
                    "thickness": 0.75,
                    "value": 70,
                },
            },
        )
    )
    fig.update_layout(height=400, margin=dict(l=40, r=40, t=60, b=40))
    return fig


def fig_to_png_path(
    fig: "go.Figure", width: int = 1280, height: int = 800, scale: int = 2
) -> Optional[str]:
    """
    Converte uma Figure Plotly em PNG temporário (usa kaleido).
    """
    try:
        import plotly.io as pio

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            pio.write_image(fig, tmp.name, format="png", width=width, height=height, scale=scale)
            return tmp.name
    except Exception:
        return None


# =================== PDF / FONTES ===================

def _download_font(dst: str, url: str) -> bool:
    try:
        import requests

        r = requests.get(url, timeout=15)
        if r.ok:
            with open(dst, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass
    return False


def _register_montserrat(pdf: FPDF) -> bool:
    os.makedirs("fonts", exist_ok=True)
    font_map = {
        "Montserrat-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Regular.ttf",
        "Montserrat-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf",
        "Montserrat-Italic.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Italic.ttf",
    }
    ok = True
    for fname, url in font_map.items():
        path = os.path.join("fonts", fname)
        if not os.path.exists(path):
            if not _download_font(path, url):
                ok = False
    if not ok:
        return False
    try:
        pdf.add_font("Montserrat", "", os.path.join("fonts", "Montserrat-Regular.ttf"), uni=True)
        pdf.add_font("Montserrat", "B", os.path.join("fonts", "Montserrat-Bold.ttf"), uni=True)
        pdf.add_font("Montserrat", "I", os.path.join("fonts", "Montserrat-Italic.ttf"), uni=True)
        return True
    except Exception:
        return False


# =================== CLASSE PDF ===================

class PDFReport(FPDF):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 18, 18)
        self._family = "Helvetica"
        self._unicode = False

    def set_main_family(self, fam: str, uni: bool) -> None:
        self._family, self._unicode = fam, uni

    def _safe(self, s: Optional[str]) -> str:
        s = s or ""
        rep = {
            "\u2014": "-",
            "\u2013": "-",
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2026": "...",
            "\u00a0": " ",
        }
        for k, v in rep.items():
            s = s.replace(k, v)

        def _break_long_tokens(text: str, max_len: int = 80) -> str:
            def _split_token(m):
                token = m.group(0)
                chunks = [token[i : i + max_len] for i in range(0, len(token), max_len)]
                return " ".join(chunks)

            return re.sub(rf"\S{{{max_len},}}", _split_token, text)

        s = _break_long_tokens(s, max_len=80)

        try:
            return s if self._unicode else s.encode("latin-1", "ignore").decode("latin-1")
        except Exception:
            return s

    def safe_cell(self, w, h=0, txt="", *args, **kwargs):
        txt = self._safe(txt)
        try:
            super().cell(w, h, txt, *args, **kwargs)
        except Exception:
            try:
                short = (txt[:60] + "...") if len(txt) > 60 else txt
                super().cell(w, h, short, *args, **kwargs)
            except Exception:
                pass

    def safe_multi_cell(self, w, h, txt="", *args, **kwargs):
        txt = self._safe(txt)
        try:
            super().multi_cell(w, h, txt, *args, **kwargs)
        except Exception:
            try:
                super().multi_cell(
                    w,
                    h,
                    self._safe(
                        "[Trecho original muito longo ou inválido. Texto truncado para preservar o PDF.]"
                    ),
                    *args,
                    **kwargs,
                )
            except Exception:
                pass

    # -------- CAPA --------
    def cover(
        self,
        titulo: str,
        subtitulo: str,
        autor: str,
        versao: str,
        logo_path: Optional[str] = None,  # mantido só na assinatura, mas ignorado
    ) -> None:
        self.add_page()

        # faixa superior
        self.set_fill_color(45, 62, 80)
        self.rect(0, 0, self.w, 24, "F")

        # título
        self.set_y(40)
        self.set_font(self._family, "B", 22)
        self.set_text_color(45, 62, 80)
        self.safe_multi_cell(0, 10, titulo, align="C")

        self.ln(2)
        self.set_font(self._family, "", 12)
        self.set_text_color(80, 80, 80)
        self.safe_multi_cell(0, 6, subtitulo, align="C")

        self.ln(8)
        self.set_font(self._family, "", 10)
        self.safe_multi_cell(
            0,
            6,
            self._safe(
                f"Desenvolvedor responsável: {autor}\n"
                f"Versão: {versao}\n"
                f"Data: {datetime.now():%d/%m/%Y}"
            ),
            align="C",
        )

        # divisória
        self.ln(6)
        self.set_draw_color(220, 220, 220)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())

        self.set_text_color(0, 0, 0)

    # -------- HEADER / FOOTER --------
    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font(self._family, "B", 9)
        self.set_text_color(90, 90, 90)
        self.safe_cell(
            0,
            7,
            f"Elder Brain Analytics — Relatório Corporativo | {APP_VERSION}",
            align="R",
            ln=1,
        )
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def footer(self) -> None:
        if self.page_no() == 1:
            return
        # linha divisória
        self.set_y(-20)
        self.set_draw_color(220, 220, 220)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())

        # texto
        self.set_y(-16)
        self.set_font(self._family, "", 7)
        self.set_text_color(120, 120, 120)
        self.safe_multi_cell(0, 3.5, self._safe(FOOTER_TEXT), align="C")
        self.set_text_color(0, 0, 0)

    # -------- ELEMENTOS DE LAYOUT --------
    def heading(self, title: str, number: Optional[int] = None) -> None:
        self.ln(1)
        self.set_font(self._family, "B", 12)
        self.set_fill_color(229, 231, 235)  # cinza claro
        self.set_text_color(45, 62, 80)
        label = f"{number}. {title}" if number is not None else title
        self.safe_cell(0, 9, label, align="L", ln=1, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def subheading(self, text: str) -> None:
        self.set_font(self._family, "B", 10)
        self.safe_cell(0, 6, text, ln=1)
        self.ln(1)

    def paragraph(self, body: str, size: int = 9) -> None:
        txt = self._safe(body or "")
        self.set_font(self._family, "", size)

        def _break_long_tokens(s: str, max_len: int = 80) -> str:
            def _split_token(m):
                token = m.group(0)
                chunks = [token[i : i + max_len] for i in range(0, len(token), max_len)]
                return " ".join(chunks)

            return re.sub(rf"\S{{{max_len},}}", _split_token, s)

        txt = _break_long_tokens(txt, max_len=80)
        self.safe_multi_cell(0, 4.5, txt)
        self.ln(1)

    def bullet_list(self, items: List[str], size: int = 9, bullet: str = "•") -> None:
        self.set_font(self._family, "", size)
        for item in items:
            if not item:
                continue
            self.safe_cell(4, 4, bullet)
            self.safe_multi_cell(0, 4, self._safe(item))
        self.ln(1)

    def divider(self) -> None:
        self.ln(2)
        self.set_draw_color(220, 220, 220)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)


# =================== GERAÇÃO DO PDF ===================

def gerar_pdf_corporativo(
    bfa_data: Dict[str, Any],
    analysis: Dict[str, Any],
    cargo: str,
    save_path: Optional[str] = None,
    logo_path: Optional[str] = None,  # ignorado, mantido só para compatibilidade
) -> io.BytesIO:
    """
    Gera o relatório PDF completo (versão premium corporativa).
    """
    try:
        pdf = PDFReport(orientation="P", unit="mm", format="A4")
        if _register_montserrat(pdf):
            pdf.set_main_family("Montserrat", True)
        else:
            pdf.set_main_family("Helvetica", False)

        # ---------------- CAPA ----------------
        pdf.cover(APP_NAME, APP_TAGLINE, "André de Lima", APP_VERSION, logo_path)

        # ---------------- 1. INFORMAÇÕES DO CANDIDATO ----------------
        pdf.heading("Informações do Candidato", number=1)
        candidato = bfa_data.get("candidato", {}) or {}
        nome = candidato.get("nome", "Não informado")
        empresa = candidato.get("empresa", "Não informado")

        info_text = (
            f"Nome: {nome}\n"
            f"Empresa (quando presente no laudo): {empresa}\n"
            f"Cargo avaliado: {cargo}\n"
            f"Data da análise: {datetime.now():%d/%m/%Y %H:%M}"
        )
        pdf.paragraph(info_text, size=9)

        # ---------------- 2. DECISÃO E COMPATIBILIDADE ----------------
        pdf.heading("Decisão e Compatibilidade", number=2)
        decisao = (analysis or {}).get("decisao", "N/A")
        compat = float((analysis or {}).get("compatibilidade_geral", 0) or 0)

        pdf.set_fill_color(245, 245, 245)
        pdf.set_draw_color(210, 210, 210)
        pdf.set_line_width(0.3)
        x0, y0 = pdf.get_x(), pdf.get_y()
        box_width = pdf.w - pdf.l_margin - pdf.r_margin
        pdf.rect(x0, y0, box_width, 18)
        pdf.set_xy(x0 + 2, y0 + 2)

        pdf.set_font(pdf._family, "B", 11)
        pdf.safe_cell(
            0,
            6,
            f"DECISÃO: {decisao}   |   COMPATIBILIDADE GLOBAL: {compat:.0f}%",
            ln=1,
        )
        pdf.set_font(pdf._family, "", 8)
        pdf.safe_cell(
            0,
            5,
            "Leitura baseada em traços de personalidade, competências críticas e fatores de saúde emocional.",
            ln=1,
        )
        pdf.ln(4)

        justificativa = (analysis or {}).get("justificativa_decisao", "")
        if justificativa:
            pdf.subheading("Justificativa resumida")
            pdf.paragraph(justificativa, size=9)

        # ---------------- 3. RESUMO EXECUTIVO ----------------
        pdf.heading("Resumo Executivo", number=3)
        resumo = (analysis or {}).get("resumo_executivo", justificativa)
        if resumo:
            pdf.paragraph(resumo, size=9)

        # ---------------- 4. TRAÇOS BIG FIVE ----------------
        pdf.heading("Traços de Personalidade (Big Five)", number=4)
        traits = (bfa_data or {}).get("traits_bfa", {}) or {}

        # tabela simples de traços
        for trait_name, valor in traits.items():
            if valor is None:
                continue
            pdf.set_font(pdf._family, "B", 9)
            pdf.safe_cell(65, 5, f"{trait_name}:")
            pdf.set_font(pdf._family, "", 9)
            try:
                txt_val = f"{float(valor):.1f}/10"
            except Exception:
                txt_val = f"{valor}/10"
            pdf.safe_cell(0, 5, txt_val, ln=1)

        analise_tracos = (analysis or {}).get("analise_tracos", {}) or {}
        if analise_tracos:
            pdf.ln(2)
            pdf.subheading("Leitura dos traços")
            for trait, analise_txt in analise_tracos.items():
                if analise_txt:
                    pdf.paragraph(f"{trait}: {analise_txt}", size=9)

        # ---------------- 5. VISUALIZAÇÕES (GRÁFICOS) ----------------
        from eba_config import gerar_perfil_cargo_dinamico

        perfil = gerar_perfil_cargo_dinamico(cargo)
        radar_fig = criar_radar_bfa(traits, perfil.get("traits_ideais", {}))
        comp_fig = criar_grafico_competencias(
            (bfa_data or {}).get("competencias_ms", []) or []
        )
        gauge_fig = criar_gauge_fit(compat)

        pdf.add_page()
        pdf.heading("Visualizações (Gráficos)", number=5)

        def _embed_center(fig: "go.Figure", w_mm: int, center: bool = False) -> bool:
            path = fig_to_png_path(fig, width=1200, height=900, scale=2)
            if path:
                try:
                    if center:
                        x = (pdf.w - w_mm) / 2.0
                        pdf.image(path, x=x, w=w_mm)
                    else:
                        pdf.image(path, w=w_mm)
                except Exception:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    return False
                try:
                    os.remove(path)
                except Exception:
                    pass
                return True
            return False

        # Radar
        pdf.subheading("Big Five x Perfil Ideal")
        if not _embed_center(radar_fig, 170, center=False):
            pdf.paragraph("⚠️ Instale 'kaleido' para embutir gráficos no PDF.", size=8)
        else:
            pdf.ln(2)
            pdf.paragraph(
                "Este radar compara o perfil do candidato às faixas ideais para o cargo. "
                "Dê atenção especial a Extroversão, Amabilidade e Abertura (Inovação), "
                "bem como a Neuroticismo (quanto menor, melhor).",
                size=8,
            )

        pdf.divider()

        # Gauge de fit
        pdf.subheading("Fit global para o cargo")
        if not _embed_center(gauge_fig, 110, center=True):
            pdf.paragraph("⚠️ Falha ao embutir gráfico de Fit.", size=8)
        else:
            pdf.ln(2)
            pdf.paragraph(
                "O indicador de fit sintetiza os principais fatores comportamentais e emocionais. "
                "Valores acima de 70% indicam boa aderência geral; valores entre 40% e 70% sugerem "
                "aderência parcial com necessidade de desenvolvimento; abaixo de 40% indicam risco "
                "maior para o desempenho esperado.",
                size=8,
            )

        pdf.divider()

        # Competências
        pdf.subheading("Competências MS (Top 15)")
        if comp_fig:
            if not _embed_center(comp_fig, 170, center=False):
                pdf.paragraph("⚠️ Falha ao embutir gráfico de Competências.", size=8)
            else:
                pdf.ln(2)
                pdf.paragraph(
                    "As barras em verde indicam boas evidências de desempenho para a competência. "
                    "Barras em amarelo sugerem atenção ou desenvolvimento desejável. "
                    "Barras em vermelho apontam competências potencialmente críticas para o cargo.",
                    size=8,
                )
        else:
            pdf.paragraph("Sem competências mapeadas para exibição.", size=8)

        # ---------------- 6. SAÚDE EMOCIONAL E RESILIÊNCIA ----------------
        pdf.add_page()
        pdf.heading("Saúde Emocional e Resiliência", number=6)
        saude = (analysis or {}).get("saude_emocional_contexto", "")
        if saude:
            pdf.paragraph(saude, size=9)

        indicadores = (bfa_data or {}).get("indicadores_saude_emocional", {}) or {}
        if indicadores:
            pdf.ln(1)
            pdf.subheading("Indicadores quantitativos")
            for k, v in indicadores.items():
                if v is None:
                    continue
                pdf.set_font(pdf._family, "", 9)
                label = k.replace("_", " ").capitalize()
                pdf.safe_cell(70, 5, f"{label}: ")
                pdf.safe_cell(0, 5, f"{float(v):.0f}/100", ln=1)
            pdf.ln(2)
            pdf.paragraph(
                "Valores mais elevados em estresse, ansiedade ou impulsividade podem indicar "
                "maior vulnerabilidade emocional. Valores mais baixos tendem a favorecer "
                "resiliência e estabilidade, especialmente em funções de alta pressão.",
                size=8,
            )

        # ---------------- 7. PONTOS FORTES ----------------
        pf = (bfa_data or {}).get("pontos_fortes", []) or []
        if pf:
            pdf.heading("Pontos Fortes", number=7)
            pdf.paragraph(
                "Aspectos em que o candidato demonstra maior aderência ao cargo ou potenciais "
                "diferenciais competitivos.",
                size=8,
            )
            pdf.bullet_list(pf, size=9)

        # ---------------- 8. PONTOS DE ATENÇÃO ----------------
        pa = (bfa_data or {}).get("pontos_atencao", []) or []
        if pa:
            pdf.heading("Pontos de Atenção", number=8)
            pdf.paragraph(
                "Aspectos que podem demandar acompanhamento próximo, feedback estruturado ou "
                "plano de desenvolvimento, especialmente nos primeiros meses.",
                size=8,
            )
            pdf.bullet_list(pa, size=9, bullet="•")

        # ---------------- 9. RECOMENDAÇÕES DE DESENVOLVIMENTO ----------------
        pdf.add_page()
        pdf.heading("Recomendações de Desenvolvimento", number=9)
        recs = (analysis or {}).get("recomendacoes_desenvolvimento", []) or []
        if recs:
            pdf.paragraph(
                "Sugestões de ações práticas, trilhas de aprendizagem e focos de desenvolvimento "
                "para apoiar a evolução do candidato no médio prazo.",
                size=8,
            )
            for i, rec in enumerate(recs, 1):
                if not rec:
                    continue
                pdf.set_font(pdf._family, "B", 9)
                pdf.safe_cell(8, 5, f"{i}.")
                pdf.set_font(pdf._family, "", 9)
                pdf.safe_multi_cell(0, 5, pdf._safe(rec))
            pdf.ln(1)
        else:
            pdf.paragraph("Não foram mapeadas recomendações específicas nesta análise.", size=9)

        # ---------------- 10. CARGOS ALTERNATIVOS ----------------
        cargos_alt = (analysis or {}).get("cargos_alternativos", []) or []
        if cargos_alt:
            pdf.heading("Cargos Alternativos Sugeridos", number=10)
            pdf.paragraph(
                "Sugestões de posições em que o perfil mapeado pode apresentar maior ou "
                "boa aderência, considerando os traços comportamentais observados.",
                size=8,
            )
            for cargo_info in cargos_alt:
                nome_alt = cargo_info.get("cargo", "")
                just = cargo_info.get("justificativa", "")
                if not nome_alt:
                    continue
                pdf.set_font(pdf._family, "B", 9)
                pdf.safe_multi_cell(0, 5, f"- {nome_alt}")
                if just:
                    pdf.set_font(pdf._family, "", 8)
                    pdf.safe_multi_cell(0, 4, "   " + pdf._safe(just))
                pdf.ln(1)

        # rodapé institucional extra no corpo do relatório
        pdf.ln(3)
        pdf.set_font(pdf._family, "I", 7)
        pdf.safe_multi_cell(
            0,
            3.5,
            pdf._safe(
                "Este documento não substitui entrevistas, referências e demais etapas do processo "
                "seletivo. Recomenda-se leitura conjunta com o contexto da vaga e cultura da empresa."
            ),
        )

        # ---------------- SAÍDA ----------------
        try:
            out_bytes = pdf.output(dest="S")
            if isinstance(out_bytes, str):
                out_bytes = out_bytes.encode("latin-1", "replace")
        except Exception:
            # fallback simples
            fb = PDFReport()
            fb.set_main_family("Helvetica", False)
            fb.add_page()
            fb.set_font(fb._family, "B", 14)
            fb.safe_cell(0, 10, "RELATÓRIO DE ANÁLISE COMPORTAMENTAL", ln=1, align="C")
            fb.set_font(fb._family, "", 11)
            fb.safe_multi_cell(
                0,
                8,
                fb._safe(
                    f"Relatório gerado para: {cargo}\nData: {datetime.now():%d/%m/%Y %H:%M}"
                ),
            )
            out_bytes = fb.output(dest="S")
            if isinstance(out_bytes, str):
                out_bytes = out_bytes.encode("latin-1", "replace")

        buf = io.BytesIO(out_bytes)
        buf.seek(0)

        if save_path:
            try:
                with open(save_path, "wb") as f:
                    f.write(buf.getbuffer())
            except Exception as e:
                st.error(f"Erro ao salvar PDF: {e}")

        return buf

    except Exception as e:
        st.error(f"Erro crítico na geração do PDF: {e}")
        # PDF mínimo, só para não quebrar o download
        return io.BytesIO(b"%PDF-1.4\n%EOF\n")
