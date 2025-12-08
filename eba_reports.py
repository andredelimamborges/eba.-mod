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

# ======== PALETA DE CORES MAIS CORPORATIVA ========
COLOR_PRIMARY = "#1F4E79"      # azul marinho principal
COLOR_SECONDARY = "#4F6D7A"    # azul acinzentado
COLOR_CANDIDATO = "#1F4E79"    # candidato sempre em azul corporativo

COLOR_IDEAL_MAX = "rgba(154, 190, 214, 0.5)"
COLOR_IDEAL_MIN = "rgba(198, 224, 241, 0.35)"

COLOR_WARN = "#F0B429"         # âmbar
COLOR_GOOD = "#2E7D32"         # verde escuro
COLOR_BAD = "#C62828"          # vermelho escuro


# ======== GRÁFICOS ========
def criar_radar_bfa(
    traits: Dict[str, Optional[float]],
    traits_ideais: Optional[Dict[str, Tuple[float, float]]] = None,
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
            fillcolor="rgba(31, 78, 121, 0.3)",
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
        polar=dict(radialaxis=dict(visible=True, range=[0, 10])),
        showlegend=True,
        title="Big Five x Perfil Ideal",
        height=420,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig


def criar_grafico_competencias(competencias: List[Dict[str, Any]]) -> Optional[go.Figure]:
    if not competencias:
        return None
    df = pd.DataFrame(competencias).copy()
    if df.empty or "nota" not in df.columns:
        return None
    df = df.sort_values("nota", ascending=True).tail(15)

    cores = [
        COLOR_BAD if n < 45 else COLOR_WARN if n < 60 else COLOR_PRIMARY
        for n in df["nota"]
    ]

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
        height=480,
        showlegend=False,
        margin=dict(l=80, r=40, t=60, b=40),
    )
    fig.add_vline(x=45, line_dash="dash", line_color=COLOR_BAD)
    fig.add_vline(x=60, line_dash="dash", line_color=COLOR_GOOD)
    return fig


def criar_gauge_fit(fit_score: float) -> go.Figure:
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
                    {"range": [0, 40], "color": "rgba(198, 40, 40, 0.4)"},
                    {"range": [40, 70], "color": "rgba(240, 180, 41, 0.4)"},
                    {"range": [70, 100], "color": "rgba(46, 125, 50, 0.4)"},
                ],
                "threshold": {
                    "line": {"color": "#000000", "width": 3},
                    "thickness": 0.75,
                    "value": 70,
                },
            },
        )
    )
    fig.update_layout(height=320, margin=dict(l=40, r=40, t=40, b=20))
    return fig


def fig_to_png_path(
    fig: "go.Figure", width: int = 1280, height: int = 800, scale: int = 2
) -> Optional[str]:
    try:
        import plotly.io as pio

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            pio.write_image(fig, tmp.name, format="png", width=width, height=height, scale=scale)
            return tmp.name
    except Exception:
        return None


# ======== PDF / FONTES ========
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


class PDFReport(FPDF):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(20, 20, 20)
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

    def cover(
        self,
        titulo: str,
        subtitulo: str,
        autor: str,
        versao: str,
        logo_path: Optional[str] = None,
    ) -> None:
        self.add_page()
        if logo_path and os.path.exists(logo_path):
            try:
                self.image(logo_path, x=20, y=18, w=26)
            except Exception:
                pass

        self.set_fill_color(31, 78, 121)
        self.rect(0, 0, self.w, 22, "F")

        self.set_y(32)
        self.set_font(self._family, "B", 22)
        self.safe_multi_cell(0, 9, titulo, align="C")
        self.ln(1)
        self.set_font(self._family, "", 12)
        self.safe_multi_cell(0, 6, subtitulo, align="C")
        self.ln(4)
        self.set_font(self._family, "", 10)
        self.safe_multi_cell(
            0,
            5,
            f"Desenvolvedor Responsável: {autor}\nVersão: {versao}\nData: {datetime.now():%d/%m/%Y}",
            align="C",
        )
        self.ln(2)

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font(self._family, "B", 9)
        self.set_text_color(120, 120, 120)
        self.safe_cell(
            0,
            7,
            "Elder Brain Analytics — Relatório Corporativo",
            align="C",
            ln=1,
        )
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def footer(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(-15)
        self.set_font(self._family, "", 8)
        self.set_text_color(150, 150, 150)
        self.safe_cell(0, 10, f"Página {self.page_no()}", align="C")

    def heading(self, title: str) -> None:
        self.set_font(self._family, "B", 11)
        self.set_fill_color(31, 78, 121)
        self.set_text_color(255, 255, 255)
        self.safe_cell(0, 8, title.upper(), align="L", ln=1, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def paragraph(self, body: str, size: int = 10) -> None:
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
        self.ln(0.5)


# ======== RESUMOS DE GRÁFICOS (MAIS FORTES) ========
def _resumo_radar(traits: Dict[str, Any], traits_ideais: Dict[str, Tuple[float, float]]) -> str:
    if not traits or not traits_ideais:
        return (
            "O gráfico de radar compara os traços do candidato com a faixa ideal esperada para o cargo, "
            "permitindo visualizar rapidamente onde há maior aderência e quais fatores se afastam do perfil-alvo."
        )

    desvios = []
    for k, v in traits.items():
        try:
            v = float(v or 0)
        except Exception:
            continue
        faixa = traits_ideais.get(k, (0, 10))
        medio = (faixa[0] + faixa[1]) / 2
        desvios.append(abs(v - medio))

    if not desvios:
        return (
            "O gráfico de radar apresenta o posicionamento geral do candidato frente ao perfil-alvo do cargo, "
            "reforçando o entendimento sobre como sua personalidade se distribui nos cinco grandes fatores."
        )

    media_desvio = sum(desvios) / len(desvios)
    if media_desvio <= 1.0:
        nivel = "fortemente alinhado ao perfil ideal, com variações mínimas"
    elif media_desvio <= 2.0:
        nivel = "razoavelmente alinhado, com alguns fatores que requerem monitoramento"
    else:
        nivel = "com diferenças mais marcantes em relação ao perfil ideal, indicando pontos de atenção"

    return (
        "O gráfico de radar ilustra o grau de aderência do candidato ao perfil comportamental esperado. "
        f"De forma geral, o conjunto de traços mostra-se {nivel}. "
        "Esse equilíbrio (ou desvio) deve ser considerado em conjunto com os requisitos críticos da função."
    )


def _resumo_competencias(competencias: List[Dict[str, Any]]) -> str:
    if not competencias:
        return "Não há competências suficientes para a construção do gráfico correspondente."

    df = pd.DataFrame(competencias)
    if "nota" not in df.columns or "nome" not in df.columns:
        return "As competências não estão estruturadas de forma completa para análise gráfica."

    df = df.sort_values("nota", ascending=False)
    top = df.head(3)
    low = df.tail(3)

    destaques = ", ".join(
        f"{row['nome']} ({int(row['nota'])})" for _, row in top.iterrows()
    )
    frag = ", ".join(
        f"{row['nome']} ({int(row['nota'])})" for _, row in low.iterrows()
    )

    media = df["nota"].mean()
    acima = (df["nota"] >= 60).sum()
    abaixo = (df["nota"] < 45).sum()

    return (
        "O gráfico de competências sintetiza a força do candidato frente às principais exigências da função. "
        f"Destacam-se positivamente: {destaques}. "
        f"Entre os pontos que merecem maior desenvolvimento, observam-se: {frag}. "
        f"No conjunto, as notas apresentam média em torno de {media:.0f}, com {acima} competências em nível satisfatório "
        f"e {abaixo} abaixo do patamar esperado."
    )


def _resumo_fit(fit_score: float) -> str:
    fit = float(fit_score or 0)
    if fit < 40:
        nivel = (
            "um baixo alinhamento global ao cargo, sugerindo prudência na recomendação e eventual busca por posições "
            "alternativas mais aderentes ao perfil atual"
        )
    elif fit < 70:
        nivel = (
            "um alinhamento moderado, indicando que o candidato pode performar bem, desde que haja suporte, "
            "acompanhamento e ações estruturadas de desenvolvimento"
        )
    else:
        nivel = (
            "um alto alinhamento ao cargo, reforçando a indicação e sugerindo boa probabilidade de integração e desempenho "
            "positivos no contexto da função"
        )

    return (
        f"O indicador de fit aponta um nível de compatibilidade de aproximadamente {fit:.0f}%. "
        f"Na prática, isso representa {nivel}. "
        "Este indicador deve ser considerado em conjunto com a análise qualitativa e demais etapas do processo seletivo."
    )


# ======== GERADOR DE PDF ========
def gerar_pdf_corporativo(
    bfa_data: Dict[str, Any],
    analysis: Dict[str, Any],
    cargo: str,
    save_path: Optional[str] = None,
    logo_path: Optional[str] = None,
) -> io.BytesIO:
    """
    Gera o relatório PDF completo (versão deluxe).
    Se algo der errado, cai para uma versão simplificada, mas corporativa.
    """
    try:
        pdf = PDFReport(orientation="P", unit="mm", format="A4")
        if _register_montserrat(pdf):
            pdf.set_main_family("Montserrat", True)
        else:
            pdf.set_main_family("Helvetica", False)

        # 1. CAPA
        pdf.cover(APP_NAME, APP_TAGLINE, "André de Lima", APP_VERSION, logo_path)

        # 2. INFORMAÇÕES DO CANDIDATO
        pdf.heading("1. Informações do Candidato")
        candidato = bfa_data.get("candidato", {}) or {}
        info_text = (
            f"Nome: {candidato.get('nome', 'Não informado')}\n"
            f"Cargo Avaliado: {cargo}\n"
            f"Data da Análise: {datetime.now():%d/%m/%Y %H:%M}"
        )
        pdf.paragraph(info_text, size=10)

        # 3. DECISÃO E COMPATIBILIDADE
        pdf.heading("2. Decisão e Compatibilidade")
        decisao = (analysis or {}).get("decisao", "N/A")
        compat = float((analysis or {}).get("compatibilidade_geral", 0) or 0)

        pdf.set_fill_color(245, 245, 245)
        pdf.set_draw_color(210, 210, 210)
        pdf.set_line_width(0.3)
        x0, y0 = pdf.get_x(), pdf.get_y()
        box_width = pdf.w - 40
        pdf.rect(x0, y0, box_width, 14)
        pdf.set_xy(x0 + 3, y0 + 2)
        pdf.set_font(pdf._family, "B", 11)
        pdf.safe_cell(
            0,
            5,
            f"DECISÃO: {decisao}   |   COMPATIBILIDADE: {compat:.0f}%",
            ln=1,
        )
        pdf.set_font(pdf._family, "", 9)
        pdf.safe_cell(
            0,
            5,
            "Interpretação baseada em análise comportamental e requisitos do cargo.",
            ln=1,
        )
        pdf.ln(3)

        justificativa = (analysis or {}).get("justificativa_decisao", "")
        if justificativa:
            pdf.paragraph(justificativa, size=10)

        # 4. RESUMO EXECUTIVO
        pdf.heading("3. Resumo Executivo")
        resumo = (analysis or {}).get("resumo_executivo", justificativa)
        if resumo:
            pdf.paragraph(resumo, size=10)

        # 5. BIG FIVE
        pdf.heading("4. Traços de Personalidade (Big Five)")
        traits = (bfa_data or {}).get("traits_bfa", {}) or {}
        for trait_name, valor in traits.items():
            if valor is None:
                continue
            pdf.set_font(pdf._family, "B", 9)
            pdf.safe_cell(70, 4.5, f"{trait_name}:")
            pdf.set_font(pdf._family, "", 9)
            try:
                txt_val = f"{float(valor):.1f}/10"
            except Exception:
                txt_val = f"{valor}/10"
            pdf.safe_cell(0, 4.5, txt_val, ln=1)

        analise_tracos = (analysis or {}).get("analise_tracos", {}) or {}
        for trait, analise_txt in analise_tracos.items():
            if analise_txt:
                pdf.paragraph(f"{trait}: {analise_txt}", size=9)

        # 6. VISUALIZAÇÕES (GRÁFICOS)
        pdf.heading("5. Visualizações (Gráficos)")

        from eba_config import gerar_perfil_cargo_dinamico

        perfil = gerar_perfil_cargo_dinamico(cargo)
        radar_fig = criar_radar_bfa(traits, perfil.get("traits_ideais", {}))
        comp_fig = criar_grafico_competencias(
            (bfa_data or {}).get("competencias_ms", []) or []
        )
        gauge_fig = criar_gauge_fit(
            float((analysis or {}).get("compatibilidade_geral", 0) or 0)
        )

        def _embed(fig: "go.Figure", w: int) -> bool:
            path = fig_to_png_path(fig, width=1100, height=700, scale=2)
            if path:
                try:
                    pdf.image(path, w=w)
                except Exception:
                    pass
                try:
                    os.remove(path)
                except Exception:
                    pass
                return True
            return False

        # 5.1 Radar
        if _embed(radar_fig, 170):
            pdf.ln(1)
            pdf.set_font(pdf._family, "I", 8)
            pdf.paragraph(_resumo_radar(traits, perfil.get("traits_ideais", {})), size=8)
        else:
            pdf.paragraph("⚠️ Não foi possível renderizar o gráfico de radar.", size=8)

        pdf.ln(1)

        # 5.2 Competências
        if comp_fig and _embed(comp_fig, 170):
            pdf.ln(1)
            pdf.set_font(pdf._family, "I", 8)
            pdf.paragraph(
                _resumo_competencias(
                    (bfa_data or {}).get("competencias_ms", []) or []
                ),
                size=8,
            )
        else:
            pdf.paragraph("Sem competências suficientes para exibição gráfica.", size=8)

        pdf.ln(1)

        # 5.3 Gauge Fit
        if _embed(gauge_fig, 110):
            pdf.ln(1)
            pdf.set_font(pdf._family, "I", 8)
            pdf.paragraph(_resumo_fit(compat), size=8)
        else:
            pdf.paragraph("⚠️ Não foi possível renderizar o indicador de fit.", size=8)

        # 7. SAÚDE EMOCIONAL
        pdf.heading("6. Saúde Emocional e Resiliência")
        saude = (analysis or {}).get("saude_emocional_contexto", "")
        if saude:
            pdf.paragraph(saude, size=10)
        indicadores = (bfa_data or {}).get("indicadores_saude_emocional", {}) or {}
        for k, v in indicadores.items():
            if v is None:
                continue
            pdf.set_font(pdf._family, "", 9)
            pdf.safe_cell(70, 4.5, f"{k.replace('_', ' ').capitalize()}: ")
            pdf.safe_cell(0, 4.5, f"{float(v):.0f}/100", ln=1)

        # 8. PONTOS FORTES (sempre aparece)
        pdf.heading("7. Pontos Fortes")
        pf = (bfa_data or {}).get("pontos_fortes", []) or []
        if pf:
            for item in pf:
                if item:
                    pdf.paragraph(f"+ {item}", size=10)
        else:
            pdf.paragraph(
                "Não foram identificados pontos fortes específicos suficientemente marcantes no relatório para destaque individual.",
                size=9,
            )

        # 9. PONTOS DE ATENÇÃO (sempre aparece)
        pdf.heading("8. Pontos de Atenção")
        pa = (bfa_data or {}).get("pontos_atencao", []) or []
        if pa:
            for item in pa:
                if item:
                    pdf.paragraph(f"! {item}", size=10)
        else:
            pdf.paragraph(
                "O relatório não evidencia pontos de atenção críticos, mas recomenda-se acompanhamento regular no período de adaptação.",
                size=9,
            )

        # 10. RECOMENDAÇÕES DE DESENVOLVIMENTO (inclui cursos/trilhas)
        pdf.heading("9. Recomendações de Desenvolvimento")
        recs = (analysis or {}).get("recomendacoes_desenvolvimento", []) or []
        for i, rec in enumerate(recs, 1):
            if rec:
                pdf.set_font(pdf._family, "B", 10)
                pdf.safe_cell(10, 5, f"{i}.")
                pdf.set_font(pdf._family, "", 10)
                pdf.safe_multi_cell(0, 5, rec)

        # bloco genérico de cursos/trilhas – sempre aparece de forma suave
        pdf.ln(1)
        pdf.set_font(pdf._family, "B", 10)
        pdf.safe_cell(0, 6, "Sugestões complementares de desenvolvimento:", ln=1)
        pdf.set_font(pdf._family, "", 9)
        pdf.safe_multi_cell(
            0,
            4.5,
            (
                "- Participação em cursos de atualização técnica relacionados à área de atuação e às ferramentas-chave do cargo.\n"
                "- Trilhas de desenvolvimento em competências comportamentais (comunicação, trabalho em equipe, gestão de conflitos).\n"
                "- Programas de mentoring ou coaching interno, com foco em aceleração de desempenho e adaptação cultural.\n"
                "- Workshops pontuais de liderança, negociação e visão de negócio, conforme o nível de senioridade esperado."
            ),
        )

        # 11. CARGOS ALTERNATIVOS
        cargos_alt = (analysis or {}).get("cargos_alternativos", []) or []
        pdf.heading("10. Cargos Alternativos Sugeridos")
        if cargos_alt:
            for cargo_info in cargos_alt:
                nome_alt = cargo_info.get("cargo", "")
                just = cargo_info.get("justificativa", "")
                if not nome_alt:
                    continue
                pdf.set_font(pdf._family, "B", 10)
                pdf.safe_multi_cell(0, 5, f"- {nome_alt}")
                if just:
                    pdf.set_font(pdf._family, "", 9)
                    pdf.safe_multi_cell(0, 4.5, f"   {just}")
        else:
            pdf.paragraph(
                "Não foram sugeridos cargos alternativos específicos neste relatório. "
                "Caso necessário, recomenda-se avaliar posições com escopo e senioridade próximos ao cargo atualmente analisado.",
                size=9,
            )

        # 12. RODAPÉ / CONSIDERAÇÕES FINAIS
        pdf.heading("11. Considerações Finais")
        pdf.paragraph(
            (
                "Este relatório tem caráter de apoio à decisão e deve ser interpretado em conjunto com entrevistas, "
                "histórico profissional, referências e demais etapas do processo seletivo. "
                "A utilização responsável das informações aqui apresentadas contribui para decisões mais consistentes, "
                "transparentes e alinhadas à cultura organizacional."
            ),
            size=9,
        )

        # saída deluxe
        try:
            out_bytes = pdf.output(dest="S")
            if isinstance(out_bytes, str):
                out_bytes = out_bytes.encode("latin-1", "replace")
        except Exception:
            fb = PDFReport()
            fb.set_main_family("Helvetica", False)
            fb.add_page()
            fb.set_font(fb._family, "B", 14)
            fb.safe_cell(0, 10, "RELATÓRIO DE ANÁLISE COMPORTAMENTAL", ln=1, align="C")
            fb.set_font(fb._family, "", 11)
            fb.safe_multi_cell(
                0,
                8,
                f"Relatório gerado para: {cargo}\nData: {datetime.now():%d/%m/%Y %H:%M}",
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
        # fallback simplificado (último recurso)
        st.error(f"Erro crítico na geração do PDF completo. Gerando versão simplificada: {e}")

        try:
            fb = PDFReport()
            fb.set_main_family("Helvetica", False)
            fb.add_page()

            fb.set_font(fb._family, "B", 14)
            fb.safe_cell(0, 10, "RELATÓRIO DE ANÁLISE COMPORTAMENTAL", ln=1, align="C")
            fb.ln(3)

            candidato = (bfa_data or {}).get("candidato", {}) or {}
            nome_cand = candidato.get("nome", "Não informado")
            decisao = (analysis or {}).get("decisao", "N/A")
            compat = float((analysis or {}).get("compatibilidade_geral", 0) or 0)
            resumo_exec = (analysis or {}).get("resumo_executivo", "") or ""
            pontos_fortes = (bfa_data or {}).get("pontos_fortes", []) or []
            pontos_atencao = (bfa_data or {}).get("pontos_atencao", []) or []

            fb.set_font(fb._family, "", 11)
            fb.safe_multi_cell(
                0,
                6,
                (
                    f"Nome: {nome_cand}\n"
                    f"Cargo Avaliado: {cargo}\n"
                    f"Data da Análise: {datetime.now():%d/%m/%Y %H:%M}\n"
                    f"Decisão: {decisao}\n"
                    f"Compatibilidade Geral: {compat:.0f}%"
                ),
            )
            fb.ln(3)

            if resumo_exec:
                fb.set_font(fb._family, "B", 11)
                fb.safe_cell(0, 7, "Resumo Executivo", ln=1)
                fb.set_font(fb._family, "", 10)
                fb.safe_multi_cell(0, 5, resumo_exec)
                fb.ln(2)

            if pontos_fortes:
                fb.set_font(fb._family, "B", 11)
                fb.safe_cell(0, 7, "Pontos Fortes", ln=1)
                fb.set_font(fb._family, "", 10)
                for item in pontos_fortes[:5]:
                    if item:
                        fb.safe_multi_cell(0, 5, f"+ {item}")
                fb.ln(1)

            if pontos_atencao:
                fb.set_font(fb._family, "B", 11)
                fb.safe_cell(0, 7, "Pontos de Atenção", ln=1)
                fb.set_font(fb._family, "", 10)
                for item in pontos_atencao[:5]:
                    if item:
                        fb.safe_multi_cell(0, 5, f"! {item}")
                fb.ln(1)

            fb.ln(2)
            fb.set_font(fb._family, "I", 8)
            fb.safe_multi_cell(
                0,
                4,
                (
                    "Este relatório apresenta uma síntese da análise comportamental realizada para o cargo em questão. "
                    "Recomenda-se complementar a leitura com entrevistas e demais etapas do processo seletivo."
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
                except Exception as e2:
                    st.error(f"Erro ao salvar PDF simplificado: {e2}")

            return buf
        except Exception:
            return io.BytesIO(b"%PDF-1.4\n%EOF\n")
