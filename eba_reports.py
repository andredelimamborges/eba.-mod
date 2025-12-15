# eba_reports.py
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import plotly.graph_objects as go
from fpdf import FPDF

from eba_config import APP_NAME, APP_VERSION

PRIMARY_RGB = (44, 16, 156)
DARK_RGB = (20, 20, 30)
MUTED_RGB = (100, 100, 110)
BG_CARD = (246, 246, 250)
LINE_RGB = (225, 225, 235)

GOOD_RGB = (21, 128, 61)
WARN_RGB = (180, 83, 9)
BAD_RGB = (185, 28, 28)


# =========================
# SAFE TEXT / WRAP
# =========================
def _break_long_tokens(t: str, max_len: int = 40) -> str:
    def _split(m):
        w = m.group(0)
        return " ".join(w[i:i + max_len] for i in range(0, len(w), max_len))
    return re.sub(rf"\S{{{max_len},}}", _split, t)


def _pdf_safe(text: str) -> str:
    if text is None:
        return ""
    s = str(text)

    repl = {
        "—": "-", "–": "-",
        "“": '"', "”": '"',
        "’": "'", "‘": "'",
        "…": "...",
        "\u00A0": " ",
        "•": "-",
        "→": "->",
    }
    for k, v in repl.items():
        s = s.replace(k, v)

    s = _break_long_tokens(s, 40)
    try:
        s = s.encode("latin-1", "ignore").decode("latin-1")
    except Exception:
        pass
    return s


def safe_multi_cell(pdf: FPDF, h: float, text: str, w: float = 0) -> None:
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
            pdf.multi_cell(w, h, t[i:i + chunk])
            pdf.set_x(pdf.l_margin)


def _set_color(pdf: FPDF, rgb):
    pdf.set_text_color(*rgb)


# =========================
# RECT fallback (rounded -> rect)
# =========================
def _draw_card_box(pdf: FPDF, x: float, y: float, w: float, h: float, r: float = 3, style: str = "DF"):
    """
    Compat com versões diferentes do fpdf2:
    - tenta rounded_rect
    - tenta round_rect
    - fallback: rect normal
    """
    if hasattr(pdf, "rounded_rect"):
        getattr(pdf, "rounded_rect")(x, y, w, h, r, style=style)
        return
    if hasattr(pdf, "round_rect"):
        getattr(pdf, "round_rect")(x, y, w, h, r, style=style)
        return
    # fallback
    if style in ("F", "DF"):
        pdf.rect(x, y, w, h, style="F")
    if style in ("D", "DF"):
        pdf.rect(x, y, w, h, style="D")


# =========================
# UI GRÁFICOS (mantidos p/ app.py)
# =========================
def criar_radar_bfa(traits: Dict[str, Any], traits_ideais: Optional[Dict[str, Tuple[float, float]]] = None) -> go.Figure:
    labels = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]

    def _get(trait: str) -> float:
        v = traits.get(trait)
        if v is None:
            k2 = trait.replace("ã", "a").replace("ç", "c").replace("õ", "o").replace("é", "e")
            v = traits.get(k2, 0)
        try:
            return float(v or 0)
        except Exception:
            return 0.0

    values = [_get(k) for k in labels]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values, theta=labels, fill="toself", name="Candidato",
        line=dict(color="rgb(44,16,156)", width=3),
        fillcolor="rgba(44, 16, 156, 0.12)",
    ))
    if traits_ideais:
        vmax = [float(traits_ideais.get(k, (0, 10))[1]) for k in labels]
        fig.add_trace(go.Scatterpolar(
            r=vmax, theta=labels, name="Ideal Máx",
            line=dict(color="rgb(21,128,61)", dash="dash", width=2),
        ))
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

    fig = go.Figure(go.Bar(
        x=notas, y=nomes, orientation="h",
        marker_color=[_color(n) for n in notas],
        text=[f"{n:.0f}" for n in notas],
        textposition="outside",
    ))
    fig.update_layout(
        title="Competências (Barras)",
        height=620,
        margin=dict(l=180, r=40, t=70, b=30),
        showlegend=False,
    )
    return fig


def criar_gauge_fit(valor: float) -> go.Figure:
    v = float(valor or 0)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=v,
        title={"text": "Fit para o Cargo"},
        gauge={"axis": {"range": [0, 100]}, "bar": {"color": "rgb(44,16,156)"}},
    ))
    fig.update_layout(height=420, margin=dict(l=40, r=40, t=70, b=30))
    return fig


# =========================
# PDF ENGINE (pretty + compat)
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


def _section_title(pdf: FPDF, title: str, subtitle: str = ""):
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 14)
    _set_color(pdf, DARK_RGB)
    pdf.cell(0, 8, _pdf_safe(title), ln=1)
    if subtitle:
        pdf.set_font("Helvetica", "", 10)
        _set_color(pdf, MUTED_RGB)
        safe_multi_cell(pdf, 5, subtitle)
    pdf.ln(2)


def _card(pdf: FPDF, title: str, body_lines: List[str]):
    x = pdf.l_margin
    w = pdf.w - pdf.l_margin - pdf.r_margin
    y = pdf.get_y()

    line_h = 5.3
    h = 8 + max(1, len(body_lines)) * line_h + 6

    pdf.set_fill_color(*BG_CARD)
    pdf.set_draw_color(*LINE_RGB)
    _draw_card_box(pdf, x, y, w, h, r=3, style="DF")

    pdf.set_xy(x + 6, y + 5)
    pdf.set_font("Helvetica", "B", 11)
    _set_color(pdf, DARK_RGB)
    pdf.cell(0, 6, _pdf_safe(title), ln=1)

    pdf.set_x(x + 6)
    pdf.set_font("Helvetica", "", 10)
    _set_color(pdf, DARK_RGB)
    safe_multi_cell(pdf, line_h, "\n".join(_pdf_safe(l) for l in body_lines))

    pdf.set_y(y + h + 4)


def _bar(pdf: FPDF, label: str, value: float, max_value: float, color_rgb):
    value = max(0.0, min(float(value or 0), max_value))
    x = pdf.l_margin
    w = pdf.w - pdf.l_margin - pdf.r_margin
    y = pdf.get_y()

    pdf.set_font("Helvetica", "", 10)
    _set_color(pdf, DARK_RGB)
    pdf.cell(0, 5, _pdf_safe(f"{label}: {value:.1f}/{max_value:.0f}"), ln=1)

    track_h = 4.5
    pdf.set_fill_color(235, 235, 242)
    _draw_card_box(pdf, x, y + 6, w, track_h, r=2, style="F")

    fill_w = w * (value / max_value if max_value else 0)
    pdf.set_fill_color(*color_rgb)
    if fill_w > 0.5:
        _draw_card_box(pdf, x, y + 6, fill_w, track_h, r=2, style="F")

    pdf.set_y(y + 14)


def gerar_pdf_corporativo(bfa_data: Dict[str, Any], analysis: Dict[str, Any], cargo: str) -> io.BytesIO:
    pdf = PDFReport()
    pdf.add_page()

    # CAPA
    pdf.set_y(30)
    pdf.set_font("Helvetica", "B", 22)
    _set_color(pdf, PRIMARY_RGB)
    pdf.cell(0, 12, _pdf_safe("Relatório Comportamental"), ln=1, align="C")
    pdf.set_font("Helvetica", "", 13)
    _set_color(pdf, DARK_RGB)
    pdf.cell(0, 8, _pdf_safe(f"{cargo}"), ln=1, align="C")
    pdf.ln(6)

    pdf.set_font("Helvetica", "", 10)
    _set_color(pdf, MUTED_RGB)
    pdf.cell(0, 6, _pdf_safe(f"{APP_NAME} {APP_VERSION}"), ln=1, align="C")
    pdf.cell(0, 6, _pdf_safe(f"gerado em {datetime.now():%d/%m/%Y %H:%M}"), ln=1, align="C")
    pdf.ln(18)

    decisao = (analysis or {}).get("decisao", "N/A")
    comp = float((analysis or {}).get("compatibilidade_geral", 0) or 0)

    _card(pdf, "visão geral", [
        f"decisão: {decisao}",
        f"compatibilidade (fit): {comp:.0f}%",
        "observação: gráficos completos disponíveis no dashboard do sistema.",
    ])

    # BIG FIVE
    pdf.add_page()
    _section_title(pdf, "perfil big five", "interpretação resumida (barras de 0 a 10).")
    traits = (bfa_data or {}).get("traits_bfa", {}) or {}
    ordem = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]
    for k in ordem:
        v = traits.get(k)
        if v is None:
            k2 = k.replace("ã", "a").replace("ç", "c").replace("õ", "o").replace("é", "e")
            v = traits.get(k2, 0)
        try:
            vv = float(v or 0)
        except Exception:
            vv = 0.0

        color = GOOD_RGB if (k == "Neuroticismo" and vv <= 5.0) else PRIMARY_RGB
        _bar(pdf, k, vv, 10.0, color)

    # COMPETÊNCIAS
    pdf.add_page()
    _section_title(pdf, "competências", "pontos críticos e forças (texto).")
    competencias = (bfa_data or {}).get("competencias_ms", []) or []
    fortes, criticas = [], []
    for c in competencias:
        nome = str(c.get("nome", "")).strip()
        if not nome:
            continue
        try:
            nota = float(c.get("nota", 0) or 0)
        except Exception:
            continue
        if nota >= 55:
            fortes.append(f"{nome} — {nota:.0f}/100")
        elif nota < 45:
            criticas.append(f"{nome} — {nota:.0f}/100")

    _card(pdf, "pontos de força", fortes[:12] if fortes else ["nenhum ponto de força acima do limiar."])
    _card(pdf, "pontos críticos", criticas[:12] if criticas else ["nenhum ponto crítico abaixo do limiar."])

    # SAÚDE EMOCIONAL
    pdf.add_page()
    _section_title(pdf, "saúde emocional", "indicadores normalizados (0 a 100).")
    saude = (bfa_data or {}).get("indicadores_saude_emocional", {}) or {}
    for k, v in saude.items():
        try:
            vv = float(v or 0)
        except Exception:
            vv = 0.0
        color = GOOD_RGB if vv <= 55 else WARN_RGB
        _bar(pdf, k.replace("_", " ").capitalize(), vv, 100.0, color)

    contexto = (analysis or {}).get("saude_emocional_contexto", "")
    if contexto:
        _card(pdf, "contextualização da ia", [_pdf_safe(contexto)])

    # DESENVOLVIMENTO
    pdf.add_page()
    _section_title(pdf, "desenvolvimento", "recomendações e próximos passos.")
    recs = (analysis or {}).get("recomendacoes_desenvolvimento", []) or []
    _card(pdf, "recomendações principais", [f"{i}. {r}" for i, r in enumerate(recs[:10], 1)] if recs else ["não há recomendações nesta execução."])

    cargos_alt = (analysis or {}).get("cargos_alternativos", []) or []
    if cargos_alt:
        linhas = [f"{c.get('cargo')}: {c.get('justificativa')}" for c in cargos_alt[:6]]
        _card(pdf, "cargos alternativos sugeridos", linhas)

    out = pdf.output(dest="S")
    if isinstance(out, str):
        out = out.encode("latin-1", "ignore")
    buf = io.BytesIO(out)
    buf.seek(0)
    return buf
