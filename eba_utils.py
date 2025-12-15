# eba_utils.py
from __future__ import annotations

import io
import os
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Dict, Any, Optional

import streamlit as st
import pandas as pd

from eba_llm import TokenTracker


# =========================
# PDF / TEXTO
# =========================
def extract_text_from_pdf(uploaded_file) -> str:
    try:
        from pdfminer.high_level import extract_text
        return extract_text(uploaded_file) or ""
    except Exception:
        return ""


def limpar_nome_empresa(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    s = re.sub(r"[^0-9A-Za-zÀ-ÿ &\-]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s[:80]


# =========================
# TRACKER
# =========================
@dataclass
class UsageTracker(TokenTracker):
    provider: str = "groq"
    email: str = ""
    empresa: str = ""
    cargo: str = ""
    created_at: str = datetime.now().isoformat(timespec="seconds")


# =========================
# EMAIL HELPERS
# =========================
def _get_email_secrets() -> Dict[str, Any]:
    return {
        "host": st.secrets.get("EMAIL_HOST", ""),
        "user": st.secrets.get("EMAIL_USER", ""),
        "pwd": st.secrets.get("EMAIL_PASS", ""),
        "to": st.secrets.get("EMAIL_TO", ""),
        "finance_to": st.secrets.get("EBA_FINANCE_TO", ""),
        "port": int(st.secrets.get("EMAIL_PORT", 587)),
    }


def _build_usage_excel_bytes(tracker: UsageTracker) -> Optional[bytes]:
    try:
        rows = []
        for step, v in tracker.dict().items():
            rows.append({
                "etapa": step,
                "prompt_tokens": v["prompt"],
                "completion_tokens": v["completion"],
                "total_tokens": v["total"],
            })

        df_steps = pd.DataFrame(rows)
        df_meta = pd.DataFrame([
            {"campo": "data", "valor": tracker.created_at},
            {"campo": "empresa", "valor": tracker.empresa},
            {"campo": "cargo", "valor": tracker.cargo},
            {"campo": "total_tokens", "valor": tracker.total_tokens},
        ])

        buff = io.BytesIO()
        with pd.ExcelWriter(buff, engine="openpyxl") as writer:
            df_meta.to_excel(writer, index=False, sheet_name="meta")
            df_steps.to_excel(writer, index=False, sheet_name="uso")

        buff.seek(0)
        return buff.read()
    except Exception:
        return None


# =========================
# EMAIL PRINCIPAL (PDF + XLSX)
# =========================
def send_report_email_if_configured(
    tracker: UsageTracker,
    email_analista: str,
    cargo: str,
    pdf_bytes: bytes,
) -> None:
    """
    Envia e-mail corporativo com:
    - PDF do relatório
    - XLSX de uso interno
    """
    try:
        secrets = _get_email_secrets()
        if not (secrets["host"] and secrets["user"] and secrets["pwd"] and secrets["to"]):
            return

        msg = EmailMessage()
        msg["Subject"] = f"[EBA] Relatório Comportamental — {cargo}"
        msg["From"] = secrets["user"]

        recipients = [secrets["to"]]
        if secrets["finance_to"]:
            recipients.append(secrets["finance_to"])
        msg["To"] = ", ".join(recipients)

        msg.set_content(
            f"""Elder Brain Analytics — Relatório Comportamental

Cargo avaliado: {cargo}
Analista: {email_analista}
Empresa: {tracker.empresa}
Data: {datetime.now():%d/%m/%Y %H:%M}

Segue em anexo o relatório completo em PDF.
"""
        )

        # 📎 PDF
        msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=f"EBA_Relatorio_{cargo.replace(' ', '_')}.pdf",
        )

        # 📎 XLSX (interno)
        excel_bytes = _build_usage_excel_bytes(tracker)
        if excel_bytes:
            msg.add_attachment(
                excel_bytes,
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename="EBA_uso_interno.xlsx",
            )

        with smtplib.SMTP(secrets["host"], secrets["port"]) as server:
            server.starttls()
            server.login(secrets["user"], secrets["pwd"])
            server.send_message(msg)

    except Exception as e:
        st.warning(f"Falha ao enviar e-mail do relatório: {e}")
