# eba_utils.py
from __future__ import annotations

import io
import os
import re
import time
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Optional, Dict, Any, List

import streamlit as st

from eba_config import MAX_INPUT_TEXT_CHARS, MAX_TRAINING_CONTEXT_CHARS
from eba_llm import TokenTracker

# ================== dependências opcionais ==================
try:
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:
    pdf_extract_text = None  # type: ignore

try:
    import pandas as pd
except Exception:
    pd = None  # type: ignore


# ================== paths ==================
TRAINING_DIR = "training_data"


# ================== PDF/TEXTO ==================
def extract_pdf_text_bytes(file) -> str:
    """
    Extrai texto de PDF a partir de um file-like (Streamlit UploadedFile).
    PROD: nunca quebra o app; retorna "" se falhar.
    """
    if pdf_extract_text is None:
        st.warning("pdfminer.six não está disponível; não foi possível ler o pdf.")
        return ""

    pos_backup: Optional[int] = None
    try:
        pos_backup = file.tell()
        file.seek(0)
    except Exception:
        pass

    try:
        text = pdf_extract_text(file) or ""
        text = text.strip()
        # corta para proteção (evita prompt enorme)
        return text[:MAX_INPUT_TEXT_CHARS]
    except Exception as e:
        st.warning(f"falha ao extrair texto do pdf: {e}")
        return ""
    finally:
        try:
            if pos_backup is not None:
                file.seek(pos_backup)
        except Exception:
            pass


def ler_texto_de_arquivo(uploaded_file) -> str:
    """
    Lê arquivo (pdf ou texto). PROD: defensivo + corta tamanho.
    """
    if uploaded_file is None:
        return ""

    nome = (getattr(uploaded_file, "name", "") or "").lower()
    mime = (getattr(uploaded_file, "type", "") or "").lower()

    if mime == "application/pdf" or nome.endswith(".pdf"):
        return extract_pdf_text_bytes(uploaded_file)

    try:
        raw = uploaded_file.read()
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
        text = raw.decode("utf-8", errors="ignore").strip()
        return text[:MAX_INPUT_TEXT_CHARS]
    except Exception as e:
        st.warning(f"falha ao ler arquivo: {e}")
        return ""


def extract_text_from_pdf(uploaded_file) -> str:
    """
    compat com app.py (nome esperado).
    """
    return ler_texto_de_arquivo(uploaded_file)


# ================== sanitização empresa ==================
_EMPRESA_STOPWORDS = {
    "ltda", "me", "epp", "sa", "s/a", "s.a", "s.a.", "mei",
    "industria", "indústria", "comercio", "comércio", "servicos", "serviços",
}

def limpar_nome_empresa(raw: str, max_len: int = 80) -> str:
    """
    sanitiza string de empresa para evitar lixo em logs/pdf/xlsx.
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""

    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"[^0-9A-Za-zÀ-ÿ&().,/\- ]+", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()

    parts = [p for p in re.split(r"\s+", s) if p]
    while parts:
        tail = parts[-1].lower().strip(".,()")
        if tail in _EMPRESA_STOPWORDS:
            parts.pop()
        else:
            break
    s = " ".join(parts).strip(" ,.-/")

    if len(s) > max_len:
        s = s[:max_len].rstrip()

    return s


# ================== training snippets ==================
def _slug(text: str, max_len: int = 40) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text or "na"


def ensure_training_dir() -> str:
    os.makedirs(TRAINING_DIR, exist_ok=True)
    return TRAINING_DIR


def save_training_snippet(
    report_text: str,
    cargo: str,
    empresa: Optional[str] = None,
    max_chars: int = 10_000,
) -> None:
    """
    salva laudo/trecho para dataset incremental (sem quebrar prod).
    """
    if not (isinstance(report_text, str) and report_text.strip()):
        return

    try:
        ensure_training_dir()
        ts = int(time.time())
        fname = f"{ts}_{_slug(cargo)}_{_slug(empresa or 'empresa', 30)}.txt"
        path = os.path.join(TRAINING_DIR, fname)

        snippet = report_text[:max_chars]
        with open(path, "w", encoding="utf-8", errors="ignore") as f:
            f.write(snippet)
    except Exception as e:
        st.warning(f"falha ao salvar snippet de treinamento: {e}")


def load_all_training_texts(max_files: int = 50) -> str:
    """
    carrega dataset incremental com limite centralizado (config).
    """
    try:
        ensure_training_dir()
        files = sorted(os.listdir(TRAINING_DIR))[:max_files]

        texts: List[str] = []
        total = 0
        for fname in files:
            path = os.path.join(TRAINING_DIR, fname)
            if not os.path.isfile(path):
                continue

            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue

            if not content:
                continue

            remaining = MAX_TRAINING_CONTEXT_CHARS - total
            if remaining <= 0:
                break

            chunk = content[:remaining]
            texts.append(f"--- {fname} ---\n{chunk}\n")
            total += len(chunk)

        return "\n".join(texts)
    except Exception as e:
        st.warning(f"falha ao carregar training texts: {e}")
        return ""


# ================== uso/tokens + excel ==================
@dataclass
class UsageTracker(TokenTracker):
    """
    compat total com:
      - TokenTracker.add(step, prompt, completion)
      - handlers que esperam add_step(...)
    """
    provider: str = "groq"
    email: str = ""
    empresa: str = ""
    cargo: str = ""
    created_at: str = datetime.now().isoformat(timespec="seconds")

    def add_step(self, step: str, prompt_tokens: int, completion_tokens: int) -> None:
        # alias estável para qualquer padrão do restante do sistema
        self.add(step, prompt_tokens, completion_tokens)


def _get_email_secrets() -> Dict[str, Any]:
    return {
        "host": st.secrets.get("EMAIL_HOST", ""),
        "user": st.secrets.get("EMAIL_USER", ""),
        "pwd": st.secrets.get("EMAIL_PASS", ""),
        "to": st.secrets.get("EMAIL_TO", ""),
        "finance_to": st.secrets.get("EBA_FINANCE_TO", ""),
        "port": int(st.secrets.get("EMAIL_PORT", 587)),
    }


def send_usage_excel_if_configured(tracker: UsageTracker, email_analista: str, cargo: str) -> None:
    """
    gera e envia .xlsx de uso.
    PROD: se não estiver configurado, só retorna. se falhar, não derruba.
    """
    try:
        secrets = _get_email_secrets()
        if not (secrets["host"] and secrets["user"] and secrets["pwd"] and secrets["to"]):
            return

        if pd is None:
            st.warning("pandas indisponível; não foi possível gerar planilha de uso.")
            return

        usage = tracker.dict()
        rows = []
        for step, v in usage.items():
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
                {"field": "email_analista", "value": email_analista or getattr(tracker, "email", "")},
                {"field": "empresa", "value": getattr(tracker, "empresa", "")},
                {"field": "cargo", "value": cargo or getattr(tracker, "cargo", "")},
                {"field": "total_prompt", "value": tracker.total_prompt},
                {"field": "total_completion", "value": tracker.total_completion},
                {"field": "total_tokens", "value": tracker.total_tokens},
                {"field": "custo_estimado_usd_gpt", "value": round(tracker.cost_usd_gpt(), 6)},
            ]
        )

        buff = io.BytesIO()
        with pd.ExcelWriter(buff, engine="openpyxl") as writer:
            df_meta.to_excel(writer, index=False, sheet_name="meta")
            df_steps.to_excel(writer, index=False, sheet_name="steps")
        buff.seek(0)

        msg = EmailMessage()
        msg["Subject"] = "[EBA] Uso de tokens (planilha)"
        msg["From"] = secrets["user"]

        destinatarios = [secrets["to"]]
        if secrets["finance_to"]:
            destinatarios.append(secrets["finance_to"])
        msg["To"] = ", ".join(destinatarios)

        body = (
            "Elder Brain Analytics — planilha de uso anexada\n\n"
            f"Data/Hora: {datetime.now():%d/%m/%Y %H:%M}\n"
            f"Analista: {email_analista}\n"
            f"Empresa: {getattr(tracker, 'empresa', '')}\n"
            f"Cargo: {cargo}\n"
            f"Total tokens: {tracker.total_tokens}\n"
            f"Custo estimado (tabela GPT): ${tracker.cost_usd_gpt():.4f}\n"
        )
        msg.set_content(body)

        filename = f"eba_usage_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        msg.add_attachment(
            buff.read(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename,
        )

        with smtplib.SMTP(secrets["host"], secrets["port"]) as server:
            server.starttls()
            server.login(secrets["user"], secrets["pwd"])
            server.send_message(msg)

    except Exception as e:
        st.warning(f"falha ao enviar planilha de uso por e-mail: {e}")
