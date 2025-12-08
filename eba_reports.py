# eba_reports.py
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

# cores
COLOR_CANDIDATO = "#60519b"
COLOR_IDEAL_MAX = "rgba(46, 213, 115, 0.35)"
COLOR_IDEAL_MIN = "rgba(46, 213, 115, 0.15)"
COLOR_WARN = "#F39C12"
COLOR_GOOD = "#2ECC71"
COLOR_BAD = "#E74C3C"


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
            line=dict(color=COLOR_CANDIDATO),
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
                line=dict(color=COLOR_GOOD),
                fillcolor=COLOR_IDEAL_MAX,
            )
        )
        fig.add_trace(
            go.Scatterpolar(
                r=vmin,
                theta=labels,
                fill="tonext",
                name="Faixa Ideal (Mín)",
                line=dict(color=COLOR_GOOD),
                fillcolor=COLOR_IDEAL_MIN,
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
    cores = [
        COLOR_BAD if n < 45 else COLOR_WARN if n < 55 else COLOR_GOOD
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
        height=600,
        showlegend=False,
    )
    fig.add_vline(x=45, line_dash="dash", line_color=COLOR_WARN)
    fig.add_vline(x=55, line_dash="dash", line_color=COLOR_GOOD)
    return fig


def criar_gauge_fit(fit_score: float) -> go.Figure:
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=float(fit_score or 0),
            domain={"x": [0, 1], "y": [0, 1]},
            title={"text": "Fit para o Cargo", "font": {"size": 24}},
            delta={"reference": 70},
            gauge={
                "axis": {"range": [None, 100]},
                "bar": {"color": COLOR_CANDIDATO},
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
    fig.update_layout(height=400)
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


# ======== PDF ========
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
        self.set_margins(15, 15, 15)
        self._family = "Helvetica"
        self._unicode = False

    def set_main_family(self, fam: str, uni: bool) -> None:
        self._family, self._unicode = fam, uni

    def _safe(self, s: Optional[str]) -> str:
        s = s or ""

        # substitui caracteres estranhos por equivalentes simples
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

        # >>> NOVO: quebra qualquer "palavra" sem espaço muito longa <<<
        import re as _re

        def _break_long_tokens(text: str, max_len: int = 60) -> str:
            def _split_token(m):
                token = m.group(0)
                chunks = [token[i : i + max_len] for i in range(0, len(token), max_len)]
                # adiciona espaço entre os pedaços pra permitir quebra
                return " ".join(chunks)

            # \S{max_len,} = sequência de caracteres sem espaço com tamanho >= max_len
            return _re.sub(rf"\S{{{max_len},}}", _split_token, text)

        s = _break_long_tokens(s, max_len=60)

        # encoding seguro
        try:
            return s if self._unicode else s.encode("latin-1", "ignore").decode("latin-1")
        except Exception:
            return s
        
    def cover(self, titulo: str, subtitulo: str, autor: str, versao: str, logo_path: Optional[str] = None) -> None:
        self.add_page()
        if logo_path and os.path.exists(logo_path):
            try:
                self.image(logo_path, x=15, y=18, w=28)
            except Exception:
                pass
        self.set_font(self._family, "B", 22)
        self.ln(18)
        self.cell(0, 12, self._safe(titulo), align="C", ln=1)
        self.set_font(self._family, "", 12)
        self.cell(0, 8, self._safe(subtitulo), align="C", ln=1)
        self.ln(6)
        self.set_font(self._family, "", 11)
        self.multi_cell(
            0,
            7,
            self._safe(
                f"Desenvolvedor Responsável: {autor}\nVersão: {versao}\nData: {datetime.now():%d/%m/%Y}"
            ),
            align="C",
        )
        self.ln(4)

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font(self._family, "B", 12)
        self.cell(
            0,
            8,
            self._safe("Elder Brain Analytics — Relatório Corporativo"),
            align="C",
            ln=1,
        )
        self.ln(1)

    def footer(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(-15)
        self.set_font(self._family, "", 8)
        self.cell(0, 10, self._safe(f"Página {self.page_no()}"), align="C")

    def heading(self, title: str) -> None:
        self.set_font(self._family, "B", 12)
        self.set_fill_color(96, 81, 155)
        self.set_text_color(255, 255, 255)
        self.cell(0, 10, self._safe(title), align="L", ln=1, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def paragraph(self, body: str, size: int = 10) -> None:
        txt = self._safe(body or "")
        self.set_font(self._family, "", size)

        import re as _re

        def _break_long_tokens(s: str, max_len: int = 60) -> str:
            def _split_token(m):
                token = m.group(0)
                chunks = [
                    token[i : i + max_len] for i in range(0, len(token), max_len)
                ]
                # insere espaço entre pedaços para o multi_cell conseguir quebrar
                return " ".join(chunks)

            # \S{max_len,} = sequência de caracteres sem espaço com tamanho >= max_len
            return _re.sub(rf"\S{{{max_len},}}", _split_token, s)

        txt = _break_long_tokens(txt, max_len=60)

        try:
            self.multi_cell(0, 5, txt)
        except Exception:
            # fallback extremo: se ainda assim der erro, corta o texto
            try:
                self.multi_cell(
                    0,
                    5,
                    self._safe(
                        "[Trecho original muito longo ou inválido. Texto truncado para preservar o PDF.]"
                    ),
                )
            except Exception:
                # em último caso, ignora o parágrafo
                pass
        self.ln(1)


def gerar_pdf_corporativo(
    bfa_data: Dict[str, Any],
    analysis: Dict[str, Any],
    cargo: str,
    save_path: Optional[str] = None,
    logo_path: Optional[str] = None,
) -> io.BytesIO:
    """Gera o relatório PDF completo (versão deluxe)."""
    try:
        pdf = PDFReport(orientation="P", unit="mm", format="A4")
        if _register_montserrat(pdf):
            pdf.set_main_family("Montserrat", True)
        else:
            pdf.set_main_family("Helvetica", False)

        # CAPA
        pdf.cover(APP_NAME, APP_TAGLINE, "André de Lima", APP_VERSION, logo_path)

        # 1. INFOS
        pdf.heading("1. INFORMAÇÕES DO CANDIDATO")
        candidato = bfa_data.get("candidato", {}) or {}
        info_text = f"""Nome: {candidato.get('nome', 'Não informado')}
Cargo Avaliado: {cargo}
Data da Análise: {datetime.now():%d/%m/%Y %H:%M}"""
        pdf.paragraph(info_text, size=10)

        # 2. DECISÃO
        pdf.heading("2. DECISÃO E COMPATIBILIDADE")
        decisao = (analysis or {}).get("decisao", "N/A")
        compat = float((analysis or {}).get("compatibilidade_geral", 0) or 0)
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font(pdf._family, "B", 12)
        pdf.cell(
            0,
            8,
            pdf._safe(f"DECISÃO: {decisao} | COMPATIBILIDADE: {compat:.0f}%"),
            align="C",
            ln=1,
            fill=True,
        )
        justificativa = (analysis or {}).get("justificativa_decisao", "")
        if justificativa:
            pdf.paragraph(justificativa, size=10)

        # 3. RESUMO
        pdf.heading("3. RESUMO EXECUTIVO")
        resumo = (analysis or {}).get("resumo_executivo", justificativa)
        if resumo:
            pdf.paragraph(resumo, size=10)

        # 4. BIG FIVE
        pdf.heading("4. TRAÇOS DE PERSONALIDADE (BIG FIVE)")
        traits = (bfa_data or {}).get("traits_bfa", {}) or {}
        for trait_name, valor in traits.items():
            if valor is None:
                continue
            pdf.set_font(pdf._family, "B", 10)
            pdf.cell(70, 6, pdf._safe(f"{trait_name}:"))
            pdf.set_font(pdf._family, "", 10)
            try:
                txt_val = f"{float(valor):.1f}/10"
            except Exception:
                txt_val = f"{valor}/10"
            pdf.cell(0, 6, pdf._safe(txt_val), ln=1)

        analise_tracos = (analysis or {}).get("analise_tracos", {}) or {}
        for trait, analise_txt in analise_tracos.items():
            if analise_txt:
                pdf.paragraph(f"{trait}: {analise_txt}", size=9)

        # 5. VISUALIZAÇÕES
        from eba_config import gerar_perfil_cargo_dinamico
        perfil = gerar_perfil_cargo_dinamico(cargo)
        radar_fig = criar_radar_bfa(traits, perfil.get("traits_ideais", {}))
        comp_fig = criar_grafico_competencias(
            (bfa_data or {}).get("competencias_ms", []) or []
        )
        gauge_fig = criar_gauge_fit(
            float((analysis or {}).get("compatibilidade_geral", 0) or 0)
        )

        pdf.add_page()
        pdf.heading("5. VISUALIZAÇÕES (GRÁFICOS)")

        def _embed(fig: "go.Figure", w: int) -> bool:
            path = fig_to_png_path(fig, width=1200, height=900, scale=2)
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

        if not _embed(radar_fig, 180):
            pdf.paragraph("⚠️ Instale 'kaleido' para embutir gráficos no PDF.", size=9)
        if comp_fig:
            if not _embed(comp_fig, 180):
                pdf.paragraph("⚠️ Falha ao embutir gráfico de Competências.", size=9)
        else:
            pdf.paragraph("Sem competências para exibir.", size=9)
        if not _embed(gauge_fig, 150):
            pdf.paragraph("⚠️ Falha ao embutir gráfico de Fit.", size=9)

        # 6. SAÚDE
        pdf.heading("6. SAÚDE EMOCIONAL E RESILIÊNCIA")
        saude = (analysis or {}).get("saude_emocional_contexto", "")
        if saude:
            pdf.paragraph(saude, size=10)
        indicadores = (bfa_data or {}).get("indicadores_saude_emocional", {}) or {}
        for k, v in indicadores.items():
            if v is None:
                continue
            pdf.set_font(pdf._family, "", 9)
            pdf.cell(70, 5, pdf._safe(f"{k.replace('_', ' ').capitalize()}: "))
            pdf.cell(0, 5, pdf._safe(f"{float(v):.0f}/100"), ln=1)

        # 7. PONTOS
        pf = (bfa_data or {}).get("pontos_fortes", []) or []
        if pf:
            pdf.heading("7. PONTOS FORTES")
            for item in pf:
                if item:
                    pdf.paragraph(f"+ {item}", size=10)
        pa = (bfa_data or {}).get("pontos_atencao", []) or []
        if pa:
            pdf.heading("8. PONTOS DE ATENÇÃO")
            for item in pa:
                if item:
                    pdf.paragraph(f"! {item}", size=10)

        # 9/10. RECOMENDAÇÕES / CARGOS
        pdf.add_page()
        pdf.heading("9. RECOMENDAÇÕES DE DESENVOLVIMENTO")
        recs = (analysis or {}).get("recomendacoes_desenvolvimento", []) or []
        for i, rec in enumerate(recs, 1):
            if rec:
                pdf.set_font(pdf._family, "B", 10)
                pdf.cell(10, 6, pdf._safe(f"{i}."))
                pdf.set_font(pdf._family, "", 10)
                pdf.multi_cell(0, 6, pdf._safe(rec))
        cargos_alt = (analysis or {}).get("cargos_alternativos", []) or []
        if cargos_alt:
            pdf.heading("10. CARGOS ALTERNATIVOS SUGERIDOS")
            for cargo_info in cargos_alt:
                nome_alt = cargo_info.get("cargo", "")
                just = cargo_info.get("justificativa", "")
                if not nome_alt:
                    continue
                pdf.set_font(pdf._family, "B", 10)
                pdf.multi_cell(0, 6, pdf._safe(f"- {nome_alt}"))
                if just:
                    pdf.set_font(pdf._family, "", 9)
                    pdf.multi_cell(0, 5, pdf._safe(f"   {just}"))

        pdf.ln(2)
        pdf.set_font(pdf._family, "I", 8)
        pdf.multi_cell(
            0,
            4,
            pdf._safe(
                "Este relatório auxilia a decisão e não substitui avaliação profissional. "
                "Uso interno — Elder Brain Analytics PRO (Versão Deluxe)."
            ),
        )

        # saída
        try:
            out_bytes = pdf.output(dest="S")
            if isinstance(out_bytes, str):
                out_bytes = out_bytes.encode("latin-1", "replace")
        except Exception:
            fb = PDFReport()
            fb.set_main_family("Helvetica", False)
            fb.add_page()
            fb.set_font(fb._family, "B", 14)
            fb.cell(0, 10, fb._safe("RELATÓRIO DE ANÁLISE COMPORTAMENTAL"), ln=1, align="C")
            fb.set_font(fb._family, "", 11)
            fb.multi_cell(
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
        return io.BytesIO(b"%PDF-1.4\n%EOF\n")
