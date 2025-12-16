# eba_reports.py
from __future__ import annotations

import io
import os
import re
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from fpdf import FPDF

from eba_config import APP_NAME, APP_TAGLINE, APP_VERSION

# =========================
# PALETA CORPORATIVA
# =========================
COLOR_PRIMARY = "#2C109C"  # roxo oficial
COLOR_TEXT = "#1F1F1F"
COLOR_MUTED = "#6B7280"
COLOR_BORDER = "#D1D5DB"

# gráficos
COLOR_CANDIDATO = "#2C109C"
COLOR_IDEAL_LINE = "#15803D"  # verde escuro
COLOR_IDEAL_FILL_MAX = "rgba(21, 128, 61, 0.18)"
COLOR_IDEAL_FILL_MIN = "rgba(21, 128, 61, 0.08)"

COLOR_WARN = "#B45309"  # âmbar escuro
COLOR_GOOD = "#15803D"  # verde escuro
COLOR_BAD = "#B91C1C"   # vermelho escuro

# export de imagens plotly
PLOT_EXPORT_W = 1000
PLOT_EXPORT_H = 680
PLOT_EXPORT_SCALE = 1

FOOTER_TEXT = (
    "Este relatório tem caráter de apoio à decisão e deve ser interpretado em conjunto com entrevistas. "
    "O Elder Brain Analytics atua como um braço direito analítico de suporte."
)

# =========================
# HELPERS
# =========================
def _norm_key(k: str) -> str:
    return (
        k.replace("ã", "a")
        .replace("ç", "c")
        .replace("õ", "o")
        .replace("é", "e")
        .replace("ó", "o")
        .replace("ê", "e")
    )


def _safe_remove_file(p: Optional[str]) -> None:
    if p and os.path.exists(p):
        try:
            os.remove(p)
        except Exception:
            pass


# =========================
# GRÁFICOS (PLOTLY)
# =========================
def criar_radar_bfa(
    traits: Dict[str, Optional[float]],
    traits_ideais: Optional[Dict[str, Tuple[float, float]]] = None,
) -> go.Figure:
    labels = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]

    vals: List[float] = []
    for k in labels:
        v = traits.get(k, None)
        if v is None:
            v = traits.get(_norm_key(k), 0)
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
            fillcolor="rgba(44, 16, 156, 0.12)",
        )
    )

    if traits_ideais:
        vmin = [float(traits_ideais.get(k, (0, 10))[0]) for k in labels]
        vmax = [float(traits_ideais.get(k, (0, 10))[1]) for k in labels]

        fig.add_trace(
            go.Scatterpolar(
                r=vmax,
                theta=labels,
                fill="toself",
                name="Faixa Ideal (Máx)",
                line=dict(color=COLOR_IDEAL_LINE, width=2, dash="dash"),
                fillcolor=COLOR_IDEAL_FILL_MAX,
            )
        )
        fig.add_trace(
            go.Scatterpolar(
                r=vmin,
                theta=labels,
                fill="tonext",
                name="Faixa Ideal (Mín)",
                line=dict(color=COLOR_IDEAL_LINE, width=2, dash="dash"),
                fillcolor=COLOR_IDEAL_FILL_MIN,
            )
        )

    fig.update_layout(
        title="Big Five x Perfil Ideal",
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10], tickfont=dict(size=11)),
            angularaxis=dict(tickfont=dict(size=12)),
        ),
        showlegend=True,
        height=520,
        margin=dict(l=40, r=40, t=70, b=30),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig


def criar_grafico_competencias(competencias: List[Dict[str, Any]]) -> Optional[go.Figure]:
    if not competencias:
        return None

    df = pd.DataFrame(competencias).copy()
    if df.empty or "nota" not in df.columns or "nome" not in df.columns:
        return None

    df["nota"] = pd.to_numeric(df["nota"], errors="coerce").fillna(0)
    df = df.sort_values("nota", ascending=True).tail(15)

    cores = [
        COLOR_BAD if n < 45 else COLOR_WARN if n < 55 else COLOR_GOOD
        for n in df["nota"].tolist()
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
        height=620,
        showlegend=False,
        margin=dict(l=160, r=40, t=70, b=30),
    )
    fig.add_vline(x=45, line_dash="dash", line_color=COLOR_WARN)
    fig.add_vline(x=55, line_dash="dash", line_color=COLOR_GOOD)
    return fig


def criar_gauge_fit(fit_score: float) -> go.Figure:
    score = float(fit_score or 0)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            domain={"x": [0, 1], "y": [0, 1]},
            title={"text": "Fit para o Cargo", "font": {"size": 22}},
            gauge={
                "axis": {"range": [None, 100]},
                "bar": {"color": COLOR_CANDIDATO},
                "steps": [
                    {"range": [0, 40], "color": "rgba(185, 28, 28, 0.25)"},
                    {"range": [40, 70], "color": "rgba(180, 83, 9, 0.22)"},
                    {"range": [70, 100], "color": "rgba(21, 128, 61, 0.20)"},
                ],
                "threshold": {
                    "line": {"color": "#111827", "width": 4},
                    "thickness": 0.75,
                    "value": 70,
                },
            },
        )
    )
    fig.update_layout(height=420, margin=dict(l=40, r=40, t=70, b=30))
    return fig


def fig_to_png_path(
    fig: "go.Figure",
    width: int = PLOT_EXPORT_W,
    height: int = PLOT_EXPORT_H,
    scale: int = PLOT_EXPORT_SCALE,
) -> Optional[str]:
    """
    Exporta figura plotly para PNG e retorna path temporário.

    PROD SAFE:
    - tenta configurar o chromium/chrome para o kaleido (necessário no streamlit.app)
    - exporta por bytes (pio.to_image / fig.to_image) e só então escreve no disco
    - warnings com erro real (não silencioso)
    """
    try:
        import plotly.io as pio
    except Exception as e:
        try:
            st.warning(f"plotly.io indisponível para exportar imagem: {e}")
        except Exception:
            pass
        return None

    # tenta garantir que kaleido existe
    try:
        import kaleido  # noqa: F401
        has_kaleido = True
    except Exception:
        has_kaleido = False

    # 🔥 correção do teu log: "Kaleido requires Google Chrome"
    # tenta apontar o executável do chromium/chrome (linux/streamlit cloud/vps)
    try:
        candidates = [
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
        ]
        for c in candidates:
            if os.path.exists(c):
                pio.kaleido.scope.chromium_executable = c
                break
    except Exception:
        pass

    img_bytes: Optional[bytes] = None
    err_msgs: List[str] = []

    try:
        img_bytes = pio.to_image(
            fig,
            format="png",
            width=int(width),
            height=int(height),
            scale=int(scale),
            engine="kaleido",
        )
    except Exception as e:
        err_msgs.append(f"pio.to_image falhou: {e}")

    if img_bytes is None:
        try:
            img_bytes = fig.to_image(
                format="png",
                width=int(width),
                height=int(height),
                scale=int(scale),
                engine="kaleido",
            )
        except Exception as e:
            err_msgs.append(f"fig.to_image falhou: {e}")

    if not img_bytes:
        try:
            base = "falha ao exportar gráfico para png."
            if not has_kaleido:
                base += " kaleido não está disponível no ambiente."
            st.warning(base + (" detalhes: " + " | ".join(err_msgs[:2]) if err_msgs else ""))
        except Exception:
            pass
        return None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(img_bytes)
            return tmp.name
    except Exception as e:
        try:
            st.warning(f"falha ao gravar png temporário: {e}")
        except Exception:
            pass
        return None


# =========================
# FONTE (Montserrat)
# =========================
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


# =========================
# PDF ENGINE
# =========================
class PDFReport(FPDF):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(15, 16, 15)
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
            "\u2022": "-",
            "\u25cf": "-",
        }
        for k, v in rep.items():
            s = s.replace(k, v)

        def _break_long_tokens(text: str, max_len: int = 80) -> str:
            def _split(m):
                t = m.group(0)
                chunks = [t[i:i + max_len] for i in range(0, len(t), max_len)]
                return " ".join(chunks)
            return re.sub(rf"\S{{{max_len},}}", _split, text)

        s = _break_long_tokens(s, 80)

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
                super().multi_cell(w, h, self._safe("[Texto truncado para preservar o PDF.]"), *args, **kwargs)
            except Exception:
                pass

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font(self._family, "B", 10)
        self.set_text_color(107, 114, 128)
        self.safe_cell(0, 8, "Elder Brain Analytics — Relatório Corporativo", align="C", ln=1)
        self.set_text_color(0, 0, 0)

    def footer(self) -> None:
        self.set_y(-16)
        self.set_font(self._family, "", 7)
        self.set_text_color(107, 114, 128)
        self.safe_multi_cell(0, 3.2, FOOTER_TEXT, align="C")

        self.set_y(-6.5)
        self.set_font(self._family, "", 7)
        self.safe_cell(0, 3, f"Página {self.page_no()}", align="C")
        self.set_text_color(0, 0, 0)

    def divider(self, space: float = 2.5) -> None:
        self.ln(space)
        x1 = self.l_margin
        x2 = self.w - self.r_margin
        y = self.get_y()
        self.set_draw_color(209, 213, 219)
        self.line(x1, y, x2, y)
        self.ln(space)

    def heading(self, title: str) -> None:
        self.set_fill_color(44, 16, 156)
        self.set_text_color(255, 255, 255)
        self.set_font(self._family, "B", 12)
        self.safe_cell(0, 9, self._safe(title), ln=1, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def paragraph(self, body: str, size: int = 10, gap: float = 1.5) -> None:
        self.set_font(self._family, "", size)
        self.safe_multi_cell(0, 5.2, self._safe(body or ""))
        self.ln(gap)

    def cover(self, titulo: str, subtitulo: str) -> None:
        self.add_page()
        self.set_fill_color(44, 16, 156)
        self.rect(0, 0, self.w, 26, "F")

        self.set_y(38)
        self.set_font(self._family, "B", 22)
        self.safe_multi_cell(0, 10, titulo, align="C")
        self.ln(1)
        self.set_font(self._family, "", 12)
        self.safe_multi_cell(0, 6, subtitulo, align="C")
        self.ln(4)

        self.set_font(self._family, "", 10)
        meta = f"{APP_NAME} — {APP_VERSION}\n{datetime.now():%d/%m/%Y %H:%M}"
        self.set_text_color(107, 114, 128)
        self.safe_multi_cell(0, 5, meta, align="C")
        self.set_text_color(0, 0, 0)

        self.set_y(self.h - 42)
        self.set_draw_color(209, 213, 219)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)
        self.set_font(self._family, "I", 9)
        self.set_text_color(107, 114, 128)
        self.safe_multi_cell(0, 4.6, APP_TAGLINE, align="C")
        self.set_text_color(0, 0, 0)


# =========================
# LAYOUT HELPERS (IMAGEM)
# =========================
def _centered_image(
    pdf: PDFReport,
    image_path: str,
    max_width_mm: float = 160,
    space_after: float = 3.0,
    top_padding_mm: float = 2.0,
) -> None:
    if not image_path or not os.path.exists(image_path):
        return

    page_width = pdf.w - pdf.l_margin - pdf.r_margin
    w_mm = min(max_width_mm, page_width)
    x_mm = (pdf.w - w_mm) / 2

    # estima altura do PNG em mm
    h_mm_est: Optional[float] = None
    try:
        from PIL import Image
        with Image.open(image_path) as im:
            px_w, px_h = im.size
        if px_w > 0:
            h_mm_est = (w_mm * float(px_h)) / float(px_w)
    except Exception:
        h_mm_est = None

    if h_mm_est is None:
        h_mm_est = 70.0

    footer_guard = 18.0
    remaining = (pdf.h - footer_guard) - pdf.get_y()
    required = top_padding_mm + h_mm_est + space_after

    if required > remaining:
        pdf.add_page()

    try:
        pdf.ln(top_padding_mm)
        pdf.image(image_path, x=x_mm, w=w_mm, h=h_mm_est)
        pdf.ln(space_after)
    except Exception:
        pdf.paragraph("Falha ao inserir imagem do gráfico.", size=9, gap=2.0)


# =========================
# RESUMOS (SEM LLM)
# =========================
def _summarize_radar(traits: Dict[str, Any], traits_ideais: Optional[Dict[str, Tuple[float, float]]]) -> str:
    labels = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]
    lines = []
    for k in labels:
        v = traits.get(k, traits.get(_norm_key(k), None))
        if v is None:
            continue
        try:
            fv = float(v)
        except Exception:
            continue

        if traits_ideais and k in traits_ideais:
            mn, mx = traits_ideais[k]
            status = "dentro" if (mn <= fv <= mx) else ("acima" if fv > mx else "abaixo")
            lines.append(f"- {k}: {fv:.1f}/10 (ideal {mn:.1f}–{mx:.1f}: {status} da faixa)")
        else:
            lines.append(f"- {k}: {fv:.1f}/10")

    if not lines:
        return "Não foi possível montar o resumo do radar por ausência de dados estruturados."
    return "Resumo do gráfico (Big Five x Ideal):\n" + "\n".join(lines)


def _summarize_competencias(competencias: List[Dict[str, Any]]) -> str:
    if not competencias:
        return "Resumo do gráfico (Competências): não há competências estruturadas no laudo."

    df = pd.DataFrame(competencias).copy()
    if df.empty or "nota" not in df.columns or "nome" not in df.columns:
        return "Resumo do gráfico (Competências): formato de dados inválido."

    df["nota"] = pd.to_numeric(df["nota"], errors="coerce").fillna(0)
    top = df.sort_values("nota", ascending=False).head(3)
    low = df.sort_values("nota", ascending=True).head(3)

    def _fmt(row):
        return f"{str(row['nome'])} ({float(row['nota']):.0f})"

    top_s = ", ".join(_fmt(r) for _, r in top.iterrows())
    low_s = ", ".join(_fmt(r) for _, r in low.iterrows())

    return (
        "Resumo do gráfico (Competências):\n"
        f"- destaques (maiores notas): {top_s}\n"
        f"- pontos de atenção (menores notas): {low_s}\n"
        "- referência visual: <45 (baixo), 45–54 (moderado), ≥55 (bom)."
    )


def _summarize_fit(score: float) -> str:
    s = float(score or 0)
    if s >= 70:
        faixa = "forte"
    elif s >= 40:
        faixa = "moderada"
    else:
        faixa = "baixa"
    return f"Resumo do gráfico (Fit): {s:.0f}% — compatibilidade {faixa} considerando traços e aderência ao perfil do cargo."


# =========================
# PDF PRINCIPAL
# =========================
def gerar_pdf_corporativo(bfa_data, analysis, cargo_input, empresa_override: str = "", **kwargs):
    cargo = cargo_input or ""
    candidato = (bfa_data or {}).get("candidato", {}) or {}

    empresa_pdf = (
        empresa_override
        or (bfa_data or {}).get("empresa")
        or candidato.get("empresa")
        or (bfa_data or {}).get("company")
        or ""
    )
 
    try:
        pdf = PDFReport(orientation="P", unit="mm", format="A4")
        if _register_montserrat(pdf):
            pdf.set_main_family("Montserrat", True)
        else:
            pdf.set_main_family("Helvetica", False)
            try:
                st.info("Fonte Montserrat não disponível no ambiente; usando Helvetica (fallback).")
            except Exception:
                pass

        # CAPA
        pdf.cover("Relatório Corporativo", f"Elder Brain Analytics — {cargo}")

        candidato = (bfa_data or {}).get("candidato", {}) or {}
        nome = candidato.get("nome", "Não informado")

        # ✅ empresa: vem do app (injeta em bfa_data["empresa"]) ou de outras integrações
        empresa_pdf = (bfa_data or {}).get("empresa") or (bfa_data or {}).get("company") or ""

        # 1
        pdf.heading("1. Informações do Candidato")
        empresa_line = f"Empresa: {empresa_pdf}\n" if empresa_pdf else ""
        pdf.paragraph(
            f"{empresa_line}"
            f"Nome: {nome}\n"
            f"Cargo Avaliado: {cargo}\n"
            f"Data da Análise: {datetime.now():%d/%m/%Y %H:%M}",
            size=10,
            gap=1.5,
        )
        pdf.divider(2.0)

        # 2
        pdf.heading("2. Decisão e Compatibilidade")
        decisao = (analysis or {}).get("decisao", "N/A")
        compat = float((analysis or {}).get("compatibilidade_geral", 0) or 0)

        pdf.set_fill_color(245, 246, 248)
        pdf.set_draw_color(209, 213, 219)
        pdf.set_line_width(0.3)
        x0, y0 = pdf.l_margin, pdf.get_y()
        box_w = pdf.w - pdf.l_margin - pdf.r_margin
        box_h = 18
        pdf.rect(x0, y0, box_w, box_h, style="DF")
        pdf.set_xy(x0 + 3, y0 + 3)
        pdf.set_font(pdf._family, "B", 11)
        pdf.safe_cell(0, 6, f"DECISÃO: {decisao}   |   COMPATIBILIDADE: {compat:.0f}%", ln=1)
        pdf.set_font(pdf._family, "", 9)
        pdf.set_text_color(107, 114, 128)
        pdf.safe_cell(0, 5, "Interpretação baseada em análise comportamental e requisitos do cargo.", ln=1)
        pdf.set_text_color(0, 0, 0)
        pdf.set_y(y0 + box_h + 4)

        justificativa = (analysis or {}).get("justificativa_decisao", "")
        if justificativa:
            pdf.paragraph(justificativa, size=10, gap=1.0)

        pdf.divider(2.0)

        # 3
        pdf.heading("3. Resumo Executivo")
        resumo = (analysis or {}).get("resumo_executivo", justificativa)
        if resumo:
            pdf.paragraph(resumo, size=10, gap=1.2)

        # 4
        pdf.heading("4. Traços de Personalidade (Big Five)")
        traits = (bfa_data or {}).get("traits_bfa", {}) or {}
        labels = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]
        pdf.set_font(pdf._family, "", 10)
        for k in labels:
            v = traits.get(k, traits.get(_norm_key(k), None))
            if v is None:
                continue
            try:
                vv = float(v)
                txt_val = f"{vv:.1f}/10"
            except Exception:
                txt_val = f"{v}/10"
            pdf.safe_cell(78, 6, f"{k}:", ln=0)
            pdf.set_font(pdf._family, "B", 10)
            pdf.safe_cell(0, 6, txt_val, ln=1)
            pdf.set_font(pdf._family, "", 10)

        analise_tracos = (analysis or {}).get("analise_tracos", {}) or {}
        for trait, analise_txt in analise_tracos.items():
            if analise_txt:
                pdf.set_text_color(107, 114, 128)
                pdf.paragraph(f"{trait}: {analise_txt}", size=9, gap=0.8)
                pdf.set_text_color(0, 0, 0)

        pdf.divider(2.0)

        # 5 - GRÁFICOS
        pdf.heading("5. Visualizações (Gráficos)")
        from eba_config import gerar_perfil_cargo_dinamico
        perfil = gerar_perfil_cargo_dinamico(cargo)
        traits_ideais = (perfil or {}).get("traits_ideais", {}) or None

        radar_fig = criar_radar_bfa(traits, traits_ideais)
        comp_fig = criar_grafico_competencias((bfa_data or {}).get("competencias_ms", []) or [])
        gauge_fig = criar_gauge_fit(float((analysis or {}).get("compatibilidade_geral", 0) or 0))

        # SAFE: inicializa paths
        p_radar: Optional[str] = None
        p_comp: Optional[str] = None
        p_fit: Optional[str] = None

        p_radar = fig_to_png_path(radar_fig)
        if p_radar:
            _centered_image(pdf, p_radar, max_width_mm=145, space_after=2.0)
            pdf.paragraph(_summarize_radar(traits, traits_ideais), size=9, gap=1.0)
            pdf.divider(1.5)
        else:
            pdf.paragraph(
                "ATENÇÃO: não foi possível exportar o radar para PNG. "
                "No streamlit.app, adicione 'chromium' em packages.txt.",
                size=9,
                gap=1.0,
            )

        if comp_fig:
            p_comp = fig_to_png_path(comp_fig)
            if p_comp:
                _centered_image(pdf, p_comp, max_width_mm=155, space_after=2.0, top_padding_mm=3.0)
                pdf.paragraph(
                    _summarize_competencias((bfa_data or {}).get("competencias_ms", []) or []),
                    size=9,
                    gap=1.0,
                )
                pdf.divider(1.5)
            else:
                pdf.paragraph(
                    "ATENÇÃO: falha ao exportar gráfico de competências para PNG (kaleido/chromium).",
                    size=9,
                    gap=1.0,
                )
        else:
            pdf.paragraph("Sem competências estruturadas para exibição.", size=9, gap=1.0)

        p_fit = fig_to_png_path(gauge_fig)
        if p_fit:
            _centered_image(pdf, p_fit, max_width_mm=115, space_after=2.0)
            pdf.paragraph(_summarize_fit(float((analysis or {}).get("compatibilidade_geral", 0) or 0)), size=9, gap=1.0)
        else:
            pdf.paragraph(
                "ATENÇÃO: falha ao exportar gráfico de Fit para PNG (kaleido/chromium).",
                size=9,
                gap=1.0,
            )

        _safe_remove_file(p_radar)
        _safe_remove_file(p_comp)
        _safe_remove_file(p_fit)

        pdf.divider(2.0)

        # 6
        pdf.heading("6. Saúde Emocional e Resiliência")
        saude = (analysis or {}).get("saude_emocional_contexto", "")
        if saude:
            pdf.paragraph(saude, size=10, gap=1.0)

        indicadores = (bfa_data or {}).get("indicadores_saude_emocional", {}) or {}
        for k, v in indicadores.items():
            if v is None:
                continue
            try:
                fv = float(v)
            except Exception:
                continue
            pdf.set_font(pdf._family, "", 9)
            pdf.safe_cell(80, 5, f"{k.replace('_', ' ').capitalize()}: ")
            pdf.set_font(pdf._family, "B", 9)
            pdf.safe_cell(0, 5, f"{fv:.0f}/100", ln=1)

        pdf.divider(2.0)

        # 7
        pf = (bfa_data or {}).get("pontos_fortes", []) or []
        if pf:
            pdf.heading("7. Pontos Fortes")
            for item in pf:
                if item:
                    pdf.paragraph(f"- {item}", size=10, gap=0.6)
            pdf.divider(1.5)

        # 8
        pa = (bfa_data or {}).get("pontos_atencao", []) or []
        if pa:
            pdf.heading("8. Pontos de Atenção")
            for item in pa:
                if item:
                    pdf.paragraph(f"- {item}", size=10, gap=0.6)
            pdf.divider(1.5)

        # 9
        pdf.heading("9. Recomendações de Desenvolvimento")
        recs = (analysis or {}).get("recomendacoes_desenvolvimento", []) or []
        if recs:
            for i, rec in enumerate(recs, 1):
                if rec:
                    pdf.set_font(pdf._family, "B", 10)
                    pdf.safe_cell(10, 6, f"{i}.")
                    pdf.set_font(pdf._family, "", 10)
                    pdf.safe_multi_cell(0, 6, rec)
                    pdf.ln(1)
        else:
            pdf.paragraph("Não foram encontradas recomendações estruturadas.", size=10, gap=1.0)

        # 10
        cargos_alt = (analysis or {}).get("cargos_alternativos", []) or []
        if cargos_alt:
            pdf.divider(2.0)
            pdf.heading("10. Cargos Alternativos Sugeridos")
            for c in cargos_alt:
                nome_alt = c.get("cargo", "")
                just = c.get("justificativa", "")
                if not nome_alt:
                    continue
                pdf.set_font(pdf._family, "B", 10)
                pdf.safe_multi_cell(0, 6, f"- {nome_alt}")
                if just:
                    pdf.set_font(pdf._family, "", 9)
                    pdf.set_text_color(107, 114, 128)
                    pdf.safe_multi_cell(0, 5, f"  {just}")
                    pdf.set_text_color(0, 0, 0)

        out_bytes = pdf.output(dest="S")
        if isinstance(out_bytes, str):
            out_bytes = out_bytes.encode("latin-1", "replace")

        buf = io.BytesIO(out_bytes)
        buf.seek(0)

        # ✅ correção mínima: evita NameError caso save_path não exista no escopo
        try:
            _save_path = save_path
        except NameError:
            _save_path = None

        if _save_path:
            try:
                with open(_save_path, "wb") as f:
                    f.write(buf.getbuffer())
            except Exception as e:
                st.error(f"Erro ao salvar PDF: {e}")

        return buf


    except Exception as e:
        st.error(f"Erro crítico na geração do PDF: {e}")
        return io.BytesIO(b"%PDF-1.4\n%EOF\n")
