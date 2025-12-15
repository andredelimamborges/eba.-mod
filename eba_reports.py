# eba_reports.py
from __future__ import annotations

import io
import math
import re
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
from fpdf import FPDF

from eba_config import APP_NAME, APP_VERSION

# gráficos no PDF (sem kaleido / sem chrome)
import matplotlib.pyplot as plt

try:
    from PIL import Image
except Exception:
    Image = None  # type: ignore


# =========================
# CONFIG VISUAL (PDF)
# =========================
PRIMARY_RGB = (44, 16, 156)     # #2C109C
DARK_RGB = (20, 20, 30)
MUTED_RGB = (105, 105, 120)
BG_CARD = (246, 246, 250)
LINE_RGB = (225, 225, 235)

GOOD_RGB = (21, 128, 61)
WARN_RGB = (180, 83, 9)
BAD_RGB = (185, 28, 28)

PLOT_EXPORT_W = 1100
PLOT_EXPORT_H = 700
PLOT_EXPORT_SCALE = 2


# =========================
# HELPERS: texto seguro p/ FPDF (Helvetica / latin-1)
# =========================
def _norm_key(s: str) -> str:
    return (
        s.replace("ã", "a")
        .replace("ç", "c")
        .replace("õ", "o")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("á", "a")
        .replace("à", "a")
        .replace("ú", "u")
        .replace("ó", "o")
    )


def _break_long_tokens(t: str, max_len: int = 40) -> str:
    def _split(m):
        w = m.group(0)
        return " ".join(w[i : i + max_len] for i in range(0, len(w), max_len))

    return re.sub(rf"\S{{{max_len},}}", _split, t)


def _pdf_safe(text: Any) -> str:
    if text is None:
        return ""
    s = str(text)

    # troca unicode problemático
    repl = {
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "’": "'",
        "‘": "'",
        "…": "...",
        "\u00A0": " ",
        "•": "-",
        "→": "->",
    }
    for k, v in repl.items():
        s = s.replace(k, v)

    s = _break_long_tokens(s, 40)

    # garante latin-1 (helvetica)
    try:
        s = s.encode("latin-1", "ignore").decode("latin-1")
    except Exception:
        pass

    return s


def safe_multi_cell(pdf: FPDF, h: float, text: Any, w: float = 0) -> None:
    """multi_cell anti-crash (cursor + tokens longos + fallback em chunks)."""
    pdf.set_x(pdf.l_margin)
    t = _pdf_safe(text)
    try:
        pdf.multi_cell(w, h, t)
        pdf.set_x(pdf.l_margin)
        return
    except Exception:
        pdf.set_x(pdf.l_margin)
        chunk = 120
        for i in range(0, len(t), chunk):
            pdf.multi_cell(w, h, t[i : i + chunk])
            pdf.set_x(pdf.l_margin)


def _set_color(pdf: FPDF, rgb: Tuple[int, int, int]) -> None:
    pdf.set_text_color(rgb[0], rgb[1], rgb[2])


def _draw_box(pdf: FPDF, x: float, y: float, w: float, h: float, r: float = 3, style: str = "DF") -> None:
    """compatibilidade com versões diferentes de fpdf2 (rounded_rect / round_rect / rect)."""
    if hasattr(pdf, "rounded_rect"):
        getattr(pdf, "rounded_rect")(x, y, w, h, r, style=style)
        return
    if hasattr(pdf, "round_rect"):
        getattr(pdf, "round_rect")(x, y, w, h, r, style=style)
        return

    # fallback: sem arredondado
    if style in ("F", "DF"):
        pdf.rect(x, y, w, h, style="F")
    if style in ("D", "DF"):
        pdf.rect(x, y, w, h, style="D")


def _section_title(pdf: FPDF, title: str, subtitle: str = "") -> None:
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 14)
    _set_color(pdf, DARK_RGB)
    pdf.cell(0, 8, _pdf_safe(title), ln=1)
    if subtitle:
        pdf.set_font("Helvetica", "", 10)
        _set_color(pdf, MUTED_RGB)
        safe_multi_cell(pdf, 5, subtitle)
    pdf.ln(2)


def _card(pdf: FPDF, title: str, body_lines: List[str]) -> None:
    x = pdf.l_margin
    w = pdf.w - pdf.l_margin - pdf.r_margin
    y = pdf.get_y()

    line_h = 5.3
    h = 8 + max(1, len(body_lines)) * line_h + 6

    pdf.set_fill_color(*BG_CARD)
    pdf.set_draw_color(*LINE_RGB)
    _draw_box(pdf, x, y, w, h, r=3, style="DF")

    pdf.set_xy(x + 6, y + 5)
    pdf.set_font("Helvetica", "B", 11)
    _set_color(pdf, DARK_RGB)
    pdf.cell(0, 6, _pdf_safe(title), ln=1)

    pdf.set_x(x + 6)
    pdf.set_font("Helvetica", "", 10)
    _set_color(pdf, DARK_RGB)
    safe_multi_cell(pdf, line_h, "\n".join(_pdf_safe(l) for l in body_lines))

    pdf.set_y(y + h + 4)


def _centered_image(pdf: FPDF, img_path: str, max_w_mm: float, max_h_mm: float) -> None:
    """
    Centraliza imagem respeitando limites A4.
    Usa PIL se disponível para manter proporção com segurança.
    """
    x0 = pdf.l_margin
    page_w = pdf.w - pdf.l_margin - pdf.r_margin

    w_mm = min(max_w_mm, page_w)
    h_mm = max_h_mm

    if Image is not None:
        try:
            im = Image.open(img_path)
            iw, ih = im.size
            im.close()
            if iw > 0 and ih > 0:
                ratio = iw / ih
                # tenta caber por altura
                w_by_h = h_mm * ratio
                if w_by_h <= w_mm:
                    w_mm = w_by_h
                else:
                    # caber por largura
                    h_mm = w_mm / ratio
        except Exception:
            pass

    x = x0 + (page_w - w_mm) / 2
    pdf.image(img_path, x=x, w=w_mm)


# =========================
# UI: gráficos Plotly (para o dashboard)
# =========================
def criar_radar_bfa(
    traits: Dict[str, Any],
    traits_ideais: Optional[Dict[str, Tuple[float, float]]] = None,
) -> go.Figure:
    labels = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]

    def _get(trait: str) -> float:
        v = traits.get(trait)
        if v is None:
            v = traits.get(_norm_key(trait), 0)
        try:
            return float(v or 0)
        except Exception:
            return 0.0

    values = [_get(k) for k in labels]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=values,
            theta=labels,
            fill="toself",
            name="Candidato",
            line=dict(color="rgb(44,16,156)", width=3),
            fillcolor="rgba(44,16,156,0.12)",
        )
    )

    if traits_ideais:
        vmax = [float(traits_ideais.get(k, (0, 10))[1]) for k in labels]
        fig.add_trace(
            go.Scatterpolar(
                r=vmax,
                theta=labels,
                name="Ideal Máx",
                line=dict(color="rgb(21,128,61)", dash="dash", width=2),
            )
        )

    fig.update_layout(
        title="Big Five x Perfil Ideal",
        polar=dict(radialaxis=dict(range=[0, 10])),
        showlegend=True,
        height=520,
        margin=dict(l=40, r=40, t=70, b=30),
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

    def _color(n: float) -> str:
        if n < 45:
            return "rgb(185,28,28)"
        if n < 55:
            return "rgb(180,83,9)"
        return "rgb(21,128,61)"

    fig = go.Figure(
        go.Bar(
            x=notas,
            y=nomes,
            orientation="h",
            marker_color=[_color(n) for n in notas],
            text=[f"{n:.0f}" for n in notas],
            textposition="outside",
        )
    )
    fig.update_layout(
        title="Competências (Barras)",
        height=620,
        margin=dict(l=180, r=40, t=70, b=30),
        showlegend=False,
    )
    return fig


def criar_gauge_fit(valor: float) -> go.Figure:
    v = float(valor or 0)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=v,
            title={"text": "Fit para o Cargo"},
            gauge={"axis": {"range": [0, 100]}, "bar": {"color": "rgb(44,16,156)"}},
        )
    )
    fig.update_layout(height=420, margin=dict(l=40, r=40, t=70, b=30))
    return fig


# =========================
# PDF: gráficos Matplotlib (sem Chrome)
# =========================
def _mpl_save_png(fig, dpi: int = 170) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    fig.savefig(tmp.name, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return tmp.name


def _mpl_radar_bigfive(traits: Dict[str, Any], title: str = "Big Five") -> str:
    labels = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]
    vals: List[float] = []
    for k in labels:
        v = traits.get(k, traits.get(_norm_key(k), 0))
        try:
            vals.append(float(v or 0))
        except Exception:
            vals.append(0.0)

    angles = [n / float(len(labels)) * 2 * math.pi for n in range(len(labels))]
    angles += angles[:1]
    vals2 = vals + vals[:1]

    fig = plt.figure(figsize=(5.8, 4.3))
    ax = plt.subplot(111, polar=True)
    ax.set_title(title, pad=18)
    ax.set_ylim(0, 10)
    ax.plot(angles, vals2, linewidth=2)
    ax.fill(angles, vals2, alpha=0.12)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels(["2", "4", "6", "8", "10"], fontsize=8)

    return _mpl_save_png(fig)


def _mpl_bar_competencias(competencias: List[Dict[str, Any]], title: str = "Competências (Top 15)") -> Optional[str]:
    if not competencias:
        return None

    df = pd.DataFrame(competencias).copy()
    if df.empty or "nota" not in df.columns or "nome" not in df.columns:
        return None

    df["nota"] = pd.to_numeric(df["nota"], errors="coerce").fillna(0)
    df["nome"] = df["nome"].astype(str)
    df = df.sort_values("nota", ascending=True).tail(15)

    nomes = df["nome"].tolist()
    notas = df["nota"].astype(float).tolist()

    fig_h = max(3.8, 0.32 * len(nomes))
    fig = plt.figure(figsize=(7.2, fig_h))
    ax = plt.gca()
    y = list(range(len(nomes)))
    ax.barh(y, notas)
    ax.set_yticks(y)
    ax.set_yticklabels(nomes, fontsize=9)
    ax.set_xlim(0, 100)
    ax.set_title(title)
    ax.grid(axis="x", alpha=0.25)
    ax.axvline(45, linestyle="--", linewidth=1)
    ax.axvline(55, linestyle="--", linewidth=1)

    return _mpl_save_png(fig)


def _mpl_gauge_fit(score: float, title: str = "Fit para o Cargo") -> str:
    s = max(0.0, min(float(score or 0), 100.0))
    fig = plt.figure(figsize=(6.2, 2.4))
    ax = plt.gca()
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.barh(0.5, 100, height=0.22, alpha=0.12)
    ax.barh(0.5, s, height=0.22, alpha=0.35)
    ax.text(0, 0.85, title, fontsize=11, fontweight="bold")
    ax.text(100, 0.85, f"{s:.0f}%", fontsize=11, fontweight="bold", ha="right")
    ax.text(0, 0.10, "0", fontsize=9)
    ax.text(100, 0.10, "100", fontsize=9, ha="right")
    return _mpl_save_png(fig)


# =========================
# PDF Engine (layout)
# =========================
class PDFReport(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(15, 16, 15)
        self.set_auto_page_break(auto=True, margin=16)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_y(10)
        self.set_font("Helvetica", "B", 10)
        _set_color(self, PRIMARY_RGB)
        self.cell(0, 6, _pdf_safe("Elder Brain Analytics"), align="L")
        self.ln(0)
        _set_color(self, MUTED_RGB)
        self.set_font("Helvetica", "", 9)
        self.cell(0, 6, _pdf_safe(f"{APP_NAME} {APP_VERSION}"), align="R")
        self.set_draw_color(*LINE_RGB)
        self.line(self.l_margin, 17, self.w - self.r_margin, 17)
        self.ln(10)

    def footer(self):
        self.set_y(-12)
        self.set_draw_color(*LINE_RGB)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)
        self.set_font("Helvetica", "", 8)
        _set_color(self, MUTED_RGB)
        self.cell(0, 8, _pdf_safe(f"Página {self.page_no()}"), align="C")


# =========================
# PDF Principal (com gráficos)
# =========================
def gerar_pdf_corporativo(bfa_data: Dict[str, Any], analysis: Dict[str, Any], cargo: str) -> io.BytesIO:
    pdf = PDFReport()
    pdf.add_page()

    # CAPA
    pdf.set_y(30)
    pdf.set_font("Helvetica", "B", 22)
    _set_color(pdf, PRIMARY_RGB)
    pdf.cell(0, 12, _pdf_safe("Relatório Corporativo"), ln=1, align="C")
    pdf.set_font("Helvetica", "", 13)
    _set_color(pdf, DARK_RGB)
    pdf.cell(0, 8, _pdf_safe(f"Elder Brain Analytics - {cargo}"), ln=1, align="C")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 10)
    _set_color(pdf, MUTED_RGB)
    pdf.cell(0, 6, _pdf_safe(f"{APP_NAME} - {APP_VERSION}"), ln=1, align="C")
    pdf.cell(0, 6, _pdf_safe(f"{datetime.now():%d/%m/%Y %H:%M}"), ln=1, align="C")
    pdf.ln(16)

    decisao = (analysis or {}).get("decisao", "N/A")
    comp = float((analysis or {}).get("compatibilidade_geral", 0) or 0)

    _card(
        pdf,
        "visão geral",
        [
            f"decisão: {decisao}",
            f"compatibilidade (fit): {comp:.0f}%",
            "observação: gráficos completos também estão disponíveis no dashboard do sistema.",
        ],
    )

    # =========================
    # DECISÃO + GAUGE FIT
    # =========================
    pdf.add_page()
    _section_title(pdf, "decisão e compatibilidade", "síntese objetiva para tomada de decisão.")

    _card(
        pdf,
        "resultado",
        [
            f"decisão final sugerida: {decisao}",
            f"fit para o cargo: {comp:.0f}%",
        ],
    )

    # gráfico do fit (matplotlib)
    fit_img = _mpl_gauge_fit(comp, "Fit para o Cargo")
    pdf.ln(2)
    _centered_image(pdf, fit_img, max_w_mm=175, max_h_mm=55)

    resumo = (analysis or {}).get("resumo_executivo", "")
    if resumo:
        pdf.ln(6)
        _card(pdf, "resumo executivo", [_pdf_safe(resumo)])

    # =========================
    # BIG FIVE + RADAR
    # =========================
    pdf.add_page()
    _section_title(pdf, "perfil big five", "pontuações de 0 a 10 + radar resumido.")

    traits = (bfa_data or {}).get("traits_bfa", {}) or {}
    ordem = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]

    linhas = []
    for k in ordem:
        v = traits.get(k, traits.get(_norm_key(k), 0))
        try:
            vv = float(v or 0)
        except Exception:
            vv = 0.0
        linhas.append(f"{k}: {vv:.1f}/10")
    _card(pdf, "pontuação (resumo)", linhas)

    radar_img = _mpl_radar_bigfive(traits, "Big Five (Radar)")
    pdf.ln(2)
    _centered_image(pdf, radar_img, max_w_mm=170, max_h_mm=120)

    # =========================
    # COMPETÊNCIAS + BARRAS
    # =========================
    pdf.add_page()
    _section_title(pdf, "competências", "visualização em barras (top 15) + leitura geral.")

    competencias = (bfa_data or {}).get("competencias_ms", []) or []
    if competencias:
        comp_img = _mpl_bar_competencias(competencias, "Competências (Top 15)")
        if comp_img:
            _centered_image(pdf, comp_img, max_w_mm=180, max_h_mm=170)

        # leitura geral
        fortes, criticas = [], []
        for c in competencias:
            nome = str(c.get("nome", "")).strip()
            try:
                nota = float(c.get("nota", 0) or 0)
            except Exception:
                continue
            if not nome:
                continue
            if nota >= 55:
                fortes.append(f"{nome} — {nota:.0f}/100")
            elif nota < 45:
                criticas.append(f"{nome} — {nota:.0f}/100")

        pdf.ln(4)
        _card(pdf, "pontos de força", fortes[:12] if fortes else ["nenhum ponto de força acima do limiar."])
        _card(pdf, "pontos críticos", criticas[:12] if criticas else ["nenhum ponto crítico abaixo do limiar."])
    else:
        _card(pdf, "competências", ["não há competências disponíveis nesta execução."])

    # =========================
    # SAÚDE EMOCIONAL
    # =========================
    pdf.add_page()
    _section_title(pdf, "saúde emocional", "indicadores (0 a 100) + contextualização.")

    saude = (bfa_data or {}).get("indicadores_saude_emocional", {}) or {}
    if saude:
        linhas = []
        for k, v in saude.items():
            try:
                vv = int(float(v or 0))
            except Exception:
                vv = 0
            linhas.append(f"{k.replace('_', ' ').capitalize()}: {vv}/100")
        _card(pdf, "indicadores", linhas)
    else:
        _card(pdf, "indicadores", ["não há indicadores de saúde emocional nesta execução."])

    contexto = (analysis or {}).get("saude_emocional_contexto", "")
    if contexto:
        _card(pdf, "contextualização da ia", [_pdf_safe(contexto)])

    # =========================
    # DESENVOLVIMENTO
    # =========================
    pdf.add_page()
    _section_title(pdf, "desenvolvimento", "recomendações e próximos passos.")

    recs = (analysis or {}).get("recomendacoes_desenvolvimento", []) or []
    if recs:
        _card(pdf, "plano sugerido", [f"{i}. {r}" for i, r in enumerate(recs[:10], 1)])
    else:
        _card(pdf, "plano sugerido", ["não foram geradas recomendações nesta execução."])

    cargos_alt = (analysis or {}).get("cargos_alternativos", []) or []
    if cargos_alt:
        linhas_alt = [f"{c.get('cargo')}: {c.get('justificativa')}" for c in cargos_alt[:6]]
        _card(pdf, "cargos alternativos sugeridos", linhas_alt)

    out = pdf.output(dest="S")
    if isinstance(out, str):
        out = out.encode("latin-1", "ignore")

    buf = io.BytesIO(out)
    buf.seek(0)
    return buf
