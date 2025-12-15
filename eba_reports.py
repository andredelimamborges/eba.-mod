# eba_reports.py
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from fpdf import FPDF

from eba_config import APP_NAME, APP_VERSION


# =========================
# SAFE TEXT (FPDF)
# =========================
def _pdf_safe(text: str) -> str:
    if text is None:
        return ""
    s = str(text)
    repl = {
        "—": "-", "–": "-", "“": '"', "”": '"', "’": "'",
        "‘": "'", "…": "...", "\u00A0": " ", "•": "-",
        "→": "->",
    }
    for k, v in repl.items():
        s = s.replace(k, v)

    try:
        s = s.encode("latin-1", "ignore").decode("latin-1")
    except Exception:
        pass
    return s


# =========================
# PDF ENGINE
# =========================
class PDFReport(FPDF):
    def __init__(self):
        super().__init__()
        self.set_margins(15, 16, 15)
        self.set_auto_page_break(auto=True, margin=18)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.cell(0, 8, _pdf_safe(f"Página {self.page_no()}"), align="C")


# =========================
# TEXT HELPERS
# =========================
def _fmt_list(items: List[str]) -> str:
    return "\n".join(f"- {i}" for i in items if i)


# =========================
# PDF PRINCIPAL
# =========================
def gerar_pdf_corporativo(
    bfa_data: Dict[str, Any],
    analysis: Dict[str, Any],
    cargo: str,
) -> io.BytesIO:
    pdf = PDFReport()
    pdf.add_page()

    # CAPA
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 15, _pdf_safe("Relatório Comportamental"), ln=1, align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, _pdf_safe(f"Elder Brain Analytics - {cargo}"), ln=1, align="C")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _pdf_safe(f"{APP_NAME} {APP_VERSION}"), ln=1, align="C")
    pdf.cell(0, 6, _pdf_safe(f"{datetime.now():%d/%m/%Y %H:%M}"), ln=1, align="C")

    pdf.add_page()

    # =========================
    # BIG FIVE
    # =========================
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, _pdf_safe("Perfil Big Five — Interpretação"), ln=1)

    traits = bfa_data.get("traits_bfa", {}) or {}
    for k, v in traits.items():
        try:
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(
                0, 7,
                _pdf_safe(f"{k}: {float(v):.1f}/10"),
            )
        except Exception:
            pass

    pdf.ln(3)

    # =========================
    # COMPETÊNCIAS
    # =========================
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, _pdf_safe("Competências — Leitura Geral"), ln=1)

    fortes = []
    criticas = []
    for c in bfa_data.get("competencias_ms", []) or []:
        try:
            nota = float(c.get("nota", 0))
            nome = c.get("nome", "")
            if nota >= 55:
                fortes.append(nome)
            elif nota < 45:
                criticas.append(nome)
        except Exception:
            continue

    if fortes:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe("Pontos de Força"), ln=1)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 7, _pdf_safe(_fmt_list(fortes)))

    if criticas:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe("Pontos Críticos"), ln=1)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 7, _pdf_safe(_fmt_list(criticas)))

    pdf.add_page()

    # =========================
    # SAÚDE EMOCIONAL
    # =========================
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, _pdf_safe("Saúde Emocional — Justificativa"), ln=1)

    for k, v in (bfa_data.get("indicadores_saude_emocional", {}) or {}).items():
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(
            0, 7,
            _pdf_safe(f"{k.replace('_',' ').capitalize()}: {int(v)}/100"),
        )

    contexto = analysis.get("saude_emocional_contexto", "")
    if contexto:
        pdf.ln(3)
        pdf.set_font("Helvetica", "I", 11)
        pdf.multi_cell(0, 7, _pdf_safe(contexto))

    pdf.add_page()

    # =========================
    # DESENVOLVIMENTO
    # =========================
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, _pdf_safe("Recomendações de Desenvolvimento"), ln=1)

    recs = analysis.get("recomendacoes_desenvolvimento", []) or []
    if recs:
        pdf.set_font("Helvetica", "", 11)
        for i, r in enumerate(recs, 1):
            pdf.multi_cell(0, 7, _pdf_safe(f"{i}. {r}"))

    cargos_alt = analysis.get("cargos_alternativos", []) or []
    if cargos_alt:
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe("Cargos Alternativos Sugeridos"), ln=1)
        pdf.set_font("Helvetica", "", 11)
        for c in cargos_alt:
            pdf.multi_cell(0, 7, _pdf_safe(f"- {c.get('cargo')}: {c.get('justificativa')}"))

    out = pdf.output(dest="S")
    if isinstance(out, str):
        out = out.encode("latin-1", "ignore")
    buf = io.BytesIO(out)
    buf.seek(0)
    return buf
