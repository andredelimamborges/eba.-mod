# eba_utils.py
from __future__ import annotations

import io
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Optional, Dict, Any, List

import streamlit as st

try:
    import pandas as pd
except Exception:
    pd = None  # type: ignore

try:
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:
    pdf_extract_text = None  # type: ignore

from eba_llm import TokenTracker


# =========================
# PDF/TEXTO
# =========================
def extract_text_from_pdf(uploaded_file) -> str:
    if uploaded_file is None:
        return ""
    name = (getattr(uploaded_file, "name", "") or "").lower()
    mime = (getattr(uploaded_file, "type", "") or "").lower()

    if mime == "application/pdf" or name.endswith(".pdf"):
        if pdf_extract_text is None:
            st.warning("pdfminer.six não disponível; não foi possível ler o PDF.")
            return ""
        try:
            try:
                uploaded_file.seek(0)
            except Exception:
                pass
            return (pdf_extract_text(uploaded_file) or "").strip()
        except Exception as e:
            st.warning(f"falha ao extrair texto do pdf: {e}")
            return ""

    # txt
    try:
        raw = uploaded_file.read()
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
        return raw.decode("utf-8", errors="ignore").strip()
    except Exception as e:
        st.warning(f"falha ao ler arquivo: {e}")
        return ""


def limpar_nome_empresa(raw: str, max_len: int = 80) -> str:
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"[^0-9A-Za-zÀ-ÿ&().,/\- ]+", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s[:max_len]


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

    # compat (se algum módulo chamar add_step)
    def add_step(self, step: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.add(step, prompt_tokens, completion_tokens)


# =========================
# EMAIL / XLSX
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
    if pd is None:
        return None

    try:
        rows: List[Dict[str, Any]] = []
        for step, v in tracker.dict().items():
            rows.append(
                {
                    "step": step,
                    "prompt_tokens": v.get("prompt", 0),
                    "completion_tokens": v.get("completion", 0),
                    "total_tokens": v.get("total", 0),
                }
            )

        df_steps = pd.DataFrame(rows)
        df_meta = pd.DataFrame(
            [
                {"field": "created_at", "value": tracker.created_at},
                {"field": "provider", "value": getattr(tracker, "provider", "")},
                {"field": "email_analista", "value": getattr(tracker, "email", "")},
                {"field": "empresa", "value": getattr(tracker, "empresa", "")},
                {"field": "cargo", "value": getattr(tracker, "cargo", "")},
                {"field": "total_tokens", "value": tracker.total_tokens},
            ]
        )

        buff = io.BytesIO()
        with pd.ExcelWriter(buff, engine="openpyxl") as writer:
            df_meta.to_excel(writer, index=False, sheet_name="meta")
            df_steps.to_excel(writer, index=False, sheet_name="steps")
        buff.seek(0)
        return buff.read()
    except Exception:
        return None


# ✅ compat: função antiga (app.py atual usa)
def send_usage_excel_if_configured(tracker: UsageTracker, email_analista: str, cargo: str) -> None:
    try:
        secrets = _get_email_secrets()
        if not (secrets["host"] and secrets["user"] and secrets["pwd"] and secrets["to"]):
            return

        excel_bytes = _build_usage_excel_bytes(tracker)
        if not excel_bytes:
            return

        msg = EmailMessage()
        msg["Subject"] = "[EBA] Uso interno (planilha)"
        msg["From"] = secrets["user"]

        destinatarios = [secrets["to"]]
        if secrets["finance_to"]:
            destinatarios.append(secrets["finance_to"])
        msg["To"] = ", ".join(destinatarios)

        msg.set_content(
            f"EBA — planilha de uso interno\n\nCargo: {cargo}\nAnalista: {email_analista}\nData: {datetime.now():%d/%m/%Y %H:%M}\n"
        )

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
        st.warning(f"falha ao enviar planilha: {e}")


# ✅ novo: PDF + XLSX
def send_report_email_if_configured(
    tracker: UsageTracker,
    email_analista: str,
    cargo: str,
    pdf_bytes: bytes,
) -> None:
    try:
        secrets = _get_email_secrets()
        if not (secrets["host"] and secrets["user"] and secrets["pwd"] and secrets["to"]):
            return

        msg = EmailMessage()
        msg["Subject"] = f"[EBA] Relatório — {cargo}"
        msg["From"] = secrets["user"]

        destinatarios = [secrets["to"]]
        if secrets["finance_to"]:
            destinatarios.append(secrets["finance_to"])
        msg["To"] = ", ".join(destinatarios)

        msg.set_content(
            f"Elder Brain Analytics — Relatório Comportamental\n\n"
            f"Cargo: {cargo}\n"
            f"Analista: {email_analista}\n"
            f"Empresa: {getattr(tracker, 'empresa', '')}\n"
            f"Data: {datetime.now():%d/%m/%Y %H:%M}\n\n"
            "Segue em anexo o relatório em PDF."
        )

        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf",
                           filename=f"EBA_Relatorio_{cargo.replace(' ', '_')}.pdf")

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
        st.warning(f"falha ao enviar email do relatório: {e}")
