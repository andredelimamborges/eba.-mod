from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st
from email.message import EmailMessage
import smtplib

from eba_config import (
    APP_NAME,
    APP_TAGLINE,
    APP_VERSION,
)
from eba_llm import (
    TokenTracker,
    get_api_key_for_provider,
    extract_bfa_data,
    analyze_bfa_data,
    send_admin_report_if_configured,
)
from eba_reports import (
    criar_radar_bfa,
    criar_grafico_competencias,
    criar_gauge_fit,
    gerar_pdf_corporativo,
)
from eba_utils import (
    ler_texto_de_arquivo,
    load_all_training_texts,
    save_training_snippet,
)


# =================== CONFIG BÁSICA ===================
LLM_PROVIDER = "Groq"
LLM_MODEL_ID = "llama-3.3-70b-versatile"   # modelo atualizado da Groq

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🧠",
    layout="wide",
)


# =================== HELPERS: E-MAIL / EXCEL ===================

def _get_email_config() -> Optional[Dict[str, Any]]:
    """Lê as configs de e-mail do secrets. Retorna None se incompleto."""
    host = st.secrets.get("EMAIL_HOST", "")
    port = int(st.secrets.get("EMAIL_PORT", 587))
    user = st.secrets.get("EMAIL_USER", "")
    pwd = st.secrets.get("EMAIL_PASS", "")
    to_main = st.secrets.get("EMAIL_TO", "")
    to_finance = st.secrets.get("EBA_FINANCE_TO", "")

    if not (host and user and pwd and to_main):
        return None

    return {
        "host": host,
        "port": port,
        "user": user,
        "pwd": pwd,
        "to_main": to_main,
        "to_finance": to_finance,
    }


def send_usage_excel_if_configured(
    tracker: TokenTracker,
    provider: str,
    model: str,
    email_empresarial: str,
    empresa: Optional[str],
    cargo: str,
) -> None:
    """Gera um Excel com o uso de tokens + metadados e envia por e-mail."""

    cfg = _get_email_config()
    if cfg is None:
        return  # silencioso

    td = tracker.dict()

    def _step_vals(step: str) -> Dict[str, int]:
        return td.get(step, {"prompt": 0, "completion": 0, "total": 0})

    row = {
        "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "email_empresarial": email_empresarial,
        "empresa": empresa or "",
        "cargo_avaliado": cargo,
        "provider": provider,
        "modelo": model,
        "extracao_prompt": _step_vals("extracao")["prompt"],
        "extracao_completion": _step_vals("extracao")["completion"],
        "extracao_total": _step_vals("extracao")["total"],
        "analise_prompt": _step_vals("analise")["prompt"],
        "analise_completion": _step_vals("analise")["completion"],
        "analise_total": _step_vals("analise")["total"],
        "chat_total": _step_vals("chat")["total"],
        "pdf_total": _step_vals("pdf")["total"],
        "total_prompt": tracker.total_prompt,
        "total_completion": tracker.total_completion,
        "total_tokens": tracker.total_tokens,
        "custo_estimado_usd": round(tracker.cost_usd_gpt(), 4),
    }

    df = pd.DataFrame([row])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="uso_eba")
    buf.seek(0)

    filename = f"eba_uso_{datetime.now():%Y%m%d_%H%M}.xlsx"

    msg = EmailMessage()
    msg["Subject"] = "[EBA] Log de uso (planilha de tokens)"
    msg["From"] = cfg["user"]

    destinatarios = [cfg["to_main"]]
    if cfg["to_finance"]:
        destinatarios.append(cfg["to_finance"])

    msg["To"] = ", ".join(destinatarios)

    corpo = (
        "Segue em anexo a planilha de uso do Elder Brain Analytics.\n\n"
        f"Data/Hora: {row['data_hora']}\n"
        f"E-mail empresarial: {email_empresarial}\n"
        f"Empresa: {empresa or 'não informado'}\n"
        f"Cargo avaliado: {cargo}\n"
        f"Total de tokens: {row['total_tokens']}\n"
        f"Custo estimado: ${row['custo_estimado_usd']:.4f}\n"
    )
    msg.set_content(corpo)

    msg.add_attachment(
        buf.getvalue(),
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
            server.starttls()
            server.login(cfg["user"], cfg["pwd"])
            server.send_message(msg)
    except Exception as e:
        st.warning(f"Falha ao enviar planilha Excel: {e}")


# =================== UI PRINCIPAL ===================

def _header():
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"## 🧠 {APP_NAME}")
        st.markdown(f"<span style='color:#777'>{APP_TAGLINE}</span>", unsafe_allow_html=True)
    with col2:
        st.markdown(
            f"<div style='text-align:right;color:#999'>Versão {APP_VERSION}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("---")


def main():
    _header()

    # -------- Sidebar --------
    with st.sidebar:
        st.markdown("### Identificação do Analista")
        email_empresarial = st.text_input(
            "E-mail empresarial (obrigatório)",
            value=st.session_state.get("email_empresarial", ""),
        )
        if email_empresarial:
            st.session_state["email_empresarial"] = email_empresarial

        st.markdown("---")
        st.markdown("### Arquivo do Laudo")
        uploaded_file = st.file_uploader(
            "Envie o laudo em PDF ou TXT",
            type=["pdf", "txt"],
        )

    # -------- Corpo --------
    st.markdown("### Dados do Laudo")

    cargo = st.text_input(
        "Cargo avaliado",
        placeholder="Ex.: Engenheiro de Software Pleno",
    )

    col_btn1, col_btn2 = st.columns([1, 3])
    with col_btn1:
        processar = st.button("Gerar relatório corporativo", type="primary")

    status_placeholder = st.empty()

    if processar:

        # validações
        if not email_empresarial.strip():
            status_placeholder.error("Informe o e-mail empresarial.")
            return

        if not cargo.strip():
            status_placeholder.error("Informe o cargo avaliado.")
            return

        # obter texto do laudo — agora obrigatório via arquivo
        if uploaded_file is not None:
            laudo_texto = ler_texto_de_arquivo(uploaded_file)
        else:
            laudo_texto = ""

        if not laudo_texto.strip():
            status_placeholder.error("Envie o laudo em arquivo (PDF ou TXT).")
            return

        status_placeholder.info("Processando laudo com o Elder Brain Analytics...")

        # ---------- PIPELINE LLM ----------
        tracker = TokenTracker(provider=LLM_PROVIDER, model=LLM_MODEL_ID)
        api_key = get_api_key_for_provider(LLM_PROVIDER)

        # carregamento dos laudos anteriores (treinamento invisível)
        training_context = load_all_training_texts()

        # 1) EXTRAÇÃO
        bfa_data, raw_extraction = extract_bfa_data(
            text=laudo_texto,
            cargo=cargo,
            training_context=training_context,
            provider=LLM_PROVIDER,
            model_id=LLM_MODEL_ID,
            token=api_key,
            tracker=tracker,
        )
        if bfa_data is None:
            status_placeholder.error(f"Falha na extração: {raw_extraction}")
            return

        # 2) ANÁLISE
        from eba_config import gerar_perfil_cargo_dinamico

        perfil_cargo = gerar_perfil_cargo_dinamico(cargo)
        analysis, raw_analysis = analyze_bfa_data(
            bfa_data=bfa_data,
            cargo=cargo,
            perfil_cargo=perfil_cargo,
            provider=LLM_PROVIDER,
            model_id=LLM_MODEL_ID,
            token=api_key,
            tracker=tracker,
        )
        if analysis is None:
            status_placeholder.error(f"Falha na análise: {raw_analysis}")
            return

        status_placeholder.success("Relatório gerado com sucesso!")

        st.session_state["bfa_data"] = bfa_data
        st.session_state["analysis"] = analysis
        st.session_state["cargo"] = cargo

        # pegar nome / empresa do laudo
        candidato = bfa_data.get("candidato", {}) or {}
        nome_candidato = candidato.get("nome") or "Não informado"
        empresa = candidato.get("empresa") or ""

        # salvar o snippet para treinamento futuro
        save_training_snippet(
            report_text=laudo_texto,
            cargo=cargo,
            empresa=empresa,
        )

        # ---------- UI RESULTADOS ----------
        st.markdown("## Resultado do Laudo")

        col_a, col_b, col_c = st.columns(3)
        compat = float(analysis.get("compatibilidade_geral", 0) or 0)
        decisao = analysis.get("decisao", "N/A")

        with col_a:
            st.metric("Compatibilidade geral", f"{compat:.0f}%")
        with col_b:
            st.metric("Decisão", decisao)
        with col_c:
            st.metric(
                "Neuroticismo",
                f"{(bfa_data.get('traits_bfa', {}) or {}).get('Neuroticismo', 'N/D')}",
            )

        st.markdown(
            f"**Candidato:** {nome_candidato}  \n"
            f"**Empresa (retirada do laudo):** {empresa or 'não informado'}  \n"
            f"**Cargo avaliado:** {cargo}"
        )

        st.markdown("---")

        # ---------- GRÁFICOS ----------
        traits = (bfa_data or {}).get("traits_bfa", {}) or {}
        competencias = (bfa_data or {}).get("competencias_ms", []) or []

        radar_fig = criar_radar_bfa(traits, perfil_cargo.get("traits_ideais", {}))
        comp_fig = criar_grafico_competencias(competencias)
        gauge_fig = criar_gauge_fit(compat)

        st.subheader("Visualizações")

        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.plotly_chart(radar_fig, use_container_width=True)
        with col_g2:
            st.plotly_chart(gauge_fig, use_container_width=True)

        if comp_fig:
            st.plotly_chart(comp_fig, use_container_width=True)

        st.markdown("---")

        # ---------- PDF ----------
        st.subheader("Relatório em PDF")

        pdf_buffer = gerar_pdf_corporativo(
            bfa_data=bfa_data,
            analysis=analysis,
            cargo=cargo,
            save_path=None,
            logo_path=None,
        )

        st.download_button(
            label="📄 Baixar relatório corporativo (PDF)",
            data=pdf_buffer.getvalue(),
            file_name=f"Relatorio_EBA_{nome_candidato}_{datetime.now():%Y%m%d}.pdf",
            mime="application/pdf",
        )

        # ---------- LOGS INTERNO ----------
        send_admin_report_if_configured(tracker, LLM_PROVIDER, LLM_MODEL_ID)

        send_usage_excel_if_configured(
            tracker=tracker,
            provider=LLM_PROVIDER,
            model=LLM_MODEL_ID,
            email_empresarial=email_empresarial,
            empresa=empresa,
            cargo=cargo,
        )

        st.info("Uso registrado e enviado para os e-mails configurados.")


if __name__ == "__main__":
    main()
