from __future__ import annotations

import io
import time
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
    gerar_perfil_cargo_dinamico,
)
from eba_llm import (
    TokenTracker,
    get_api_key_for_provider,
    extract_bfa_data,
    analyze_bfa_data,
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
LLM_MODEL_ID = "llama-3.3-70b-versatile"   # modelo Groq atual

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🧠",
    layout="wide",
)


# =================== HELPERS: E-MAIL / CONFIG ===================

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


def _build_usage_row(
    tracker: TokenTracker,
    provider: str,
    model: str,
    email_empresarial: str,
    empresa: Optional[str],
    cargo: str,
    nome_candidato: str,
) -> Dict[str, Any]:
    td = tracker.dict()

    def _step_vals(step: str) -> Dict[str, int]:
        return td.get(step, {"prompt": 0, "completion": 0, "total": 0})

    return {
        "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "email_empresarial": email_empresarial,
        "empresa": empresa or "",
        "nome_candidato": nome_candidato or "",
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


def send_eba_email_with_attachments(
    tracker: TokenTracker,
    provider: str,
    model: str,
    email_empresarial: str,
    empresa: Optional[str],
    cargo: str,
    nome_candidato: str,
    pdf_bytes: bytes,
    pdf_filename: str,
) -> None:
    """
    Envia um único e-mail contendo:
      - planilha (XLSX, com fallback para CSV) com log de uso
      - PDF do relatório gerado
    """
    cfg = _get_email_config()
    if cfg is None:
        return  # silencioso se não houver config de e-mail

    row = _build_usage_row(
        tracker=tracker,
        provider=provider,
        model=model,
        email_empresarial=email_empresarial,
        empresa=empresa,
        cargo=cargo,
        nome_candidato=nome_candidato,
    )

    df = pd.DataFrame([row])

    # tenta XLSX, se falhar cai para CSV
    anex_planilha_bytes: bytes
    planilha_filename: str
    planilha_maintype: str
    planilha_subtype: str

    try:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="uso_eba")
        buf.seek(0)
        anex_planilha_bytes = buf.getvalue()
        planilha_filename = f"eba_uso_{datetime.now():%Y%m%d_%H%M}.xlsx"
        planilha_maintype = "application"
        planilha_subtype = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except Exception:
        # fallback CSV
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=False)
        anex_planilha_bytes = csv_buf.getvalue().encode("utf-8")
        planilha_filename = f"eba_uso_{datetime.now():%Y%m%d_%H%M}.csv"
        planilha_maintype = "text"
        planilha_subtype = "csv"

    msg = EmailMessage()
    msg["Subject"] = "[EBA] Relatório gerado + log de uso (tokens)"
    msg["From"] = cfg["user"]

    destinatarios = [cfg["to_main"]]
    if cfg["to_finance"]:
        destinatarios.append(cfg["to_finance"])
    msg["To"] = ", ".join(destinatarios)

    corpo = (
        "Relatório gerado pelo Elder Brain Analytics.\n\n"
        f"Data/Hora: {row['data_hora']}\n"
        f"Candidato: {nome_candidato or 'não informado'}\n"
        f"Empresa (laudo): {empresa or 'não informado'}\n"
        f"Cargo avaliado: {cargo}\n"
        f"E-mail empresarial informado: {email_empresarial}\n\n"
        f"Provider: {provider}\n"
        f"Modelo: {model}\n"
        f"Total de tokens: {row['total_tokens']}\n"
        f"Custo estimado (tabela GPT): ${row['custo_estimado_usd']:.4f}\n\n"
        "Anexos:\n"
        "- Planilha de uso (tokens por etapa)\n"
        "- PDF do relatório corporativo\n"
    )
    msg.set_content(corpo)

    # anexa planilha
    msg.add_attachment(
        anex_planilha_bytes,
        maintype=planilha_maintype,
        subtype=planilha_subtype,
        filename=planilha_filename,
    )

    # anexa PDF do relatório
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=pdf_filename,
    )

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
            server.starttls()
            server.login(cfg["user"], cfg["pwd"])
            server.send_message(msg)
    except Exception as e:
        st.warning(f"Falha ao enviar e-mail com relatório + planilha: {e}")


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

    # -------- Corpo: dados básicos --------
    st.markdown("### Dados do Laudo")

    cargo = st.text_input(
        "Cargo avaliado",
        placeholder="Ex.: Engenheiro de Software Pleno",
        value=st.session_state.get("cargo", ""),
    )

    col_btn1, col_btn2 = st.columns([1, 3])
    with col_btn1:
        processar = st.button("Gerar relatório corporativo", type="primary")

    status_placeholder = st.empty()

    # -------- Clique no botão: processa LLM + gera PDF + envia e-mail --------
    if processar:

        # validações
        if not email_empresarial.strip():
            status_placeholder.error("Informe o **e-mail empresarial** para continuar.")
            return

        if not cargo.strip():
            status_placeholder.error("Informe o **cargo avaliado** para continuar.")
            return

        if uploaded_file is not None:
            laudo_texto = ler_texto_de_arquivo(uploaded_file)
        else:
            laudo_texto = ""

        if not laudo_texto.strip():
            status_placeholder.error("Envie o laudo em arquivo (PDF ou TXT) para continuar.")
            return

        # guarda no estado (para manter depois do download)
        st.session_state["cargo"] = cargo

        tracker = TokenTracker(provider=LLM_PROVIDER, model=LLM_MODEL_ID)
        api_key = get_api_key_for_provider(LLM_PROVIDER)
        training_context = load_all_training_texts()

        # animação 1: extração
        with st.spinner("Etapa 1/2 — Extraindo informações do laudo..."):
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
            status_placeholder.error(f"Falha na etapa de extração: {raw_extraction}")
            return

        # animação 2: análise
        with st.spinner("Etapa 2/2 — Analisando perfil comportamental e gerando relatório..."):
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
            status_placeholder.error(f"Falha na etapa de análise: {raw_analysis}")
            return

        # pequeno "respiro" pra sensação de animaçãozinha
        time.sleep(0.3)

        # salva snippet pra "treinamento" incremental
        candidato = bfa_data.get("candidato", {}) or {}
        empresa = candidato.get("empresa") or ""
        nome_candidato = candidato.get("nome") or "Não informado"

        save_training_snippet(
            report_text=laudo_texto,
            cargo=cargo,
            empresa=empresa,
        )

        # gera PDF uma vez aqui e guarda em memória
        pdf_buffer = gerar_pdf_corporativo(
            bfa_data=bfa_data,
            analysis=analysis,
            cargo=cargo,
            save_path=None,
            logo_path=None,
        )
        pdf_bytes = pdf_buffer.getvalue()
        pdf_filename = f"Relatorio_EBA_{nome_candidato}_{datetime.now():%Y%m%d}.pdf"

        # salva tudo em session_state para persistir na tela
        st.session_state["bfa_data"] = bfa_data
        st.session_state["analysis"] = analysis
        st.session_state["perfil_cargo"] = perfil_cargo
        st.session_state["pdf_bytes"] = pdf_bytes
        st.session_state["pdf_filename"] = pdf_filename
        st.session_state["empresa"] = empresa
        st.session_state["nome_candidato"] = nome_candidato

        # envia e-mail único (PDF + planilha de uso)
        send_eba_email_with_attachments(
            tracker=tracker,
            provider=LLM_PROVIDER,
            model=LLM_MODEL_ID,
            email_empresarial=email_empresarial,
            empresa=empresa,
            cargo=cargo,
            nome_candidato=nome_candidato,
            pdf_bytes=pdf_bytes,
            pdf_filename=pdf_filename,
        )

        status_placeholder.success("Relatório gerado com sucesso! Resultados exibidos abaixo.")

    # -------- Exibição dos resultados (sempre que existirem na sessão) --------
    bfa_data = st.session_state.get("bfa_data")
    analysis = st.session_state.get("analysis")
    perfil_cargo = st.session_state.get("perfil_cargo")
    pdf_bytes = st.session_state.get("pdf_bytes")
    pdf_filename = st.session_state.get("pdf_filename") or "Relatorio_EBA.pdf"
    empresa = st.session_state.get("empresa") or ""
    nome_candidato = st.session_state.get("nome_candidato") or "Não informado"
    cargo_result = st.session_state.get("cargo") or cargo

    if bfa_data and analysis and perfil_cargo:
        st.markdown("## Resultado do Laudo")

        col_a, col_b, col_c = st.columns(3)
        compat = float(analysis.get("compatibilidade_geral", 0) or 0)
        decisao = analysis.get("decisao", "N/A")
        traits = (bfa_data.get("traits_bfa") or {}) or {}

        with col_a:
            st.metric("Compatibilidade geral", f"{compat:.0f}%")
        with col_b:
            st.metric("Decisão", decisao)
        with col_c:
            neuro = traits.get("Neuroticismo", "N/D")
            st.metric("Neuroticismo (quanto menor, melhor)", f"{neuro}")

        st.markdown(
            f"**Candidato:** {nome_candidato}  \n"
            f"**Empresa (extraída do laudo):** {empresa or 'não informado'}  \n"
            f"**Cargo avaliado:** {cargo_result}"
        )

        st.markdown("---")

        # ---------- GRÁFICOS ----------
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

        if pdf_bytes:
            pdf_buffer = io.BytesIO(pdf_bytes)
            st.download_button(
                label="📄 Baixar relatório corporativo (PDF)",
                data=pdf_buffer.getvalue(),
                file_name=pdf_filename,
                mime="application/pdf",
            )
        else:
            # fallback – se por algum motivo não tiver bytes em sessão, regenera
            pdf_buffer = gerar_pdf_corporativo(
                bfa_data=bfa_data,
                analysis=analysis,
                cargo=cargo_result,
                save_path=None,
                logo_path=None,
            )
            st.download_button(
                label="📄 Baixar relatório corporativo (PDF)",
                data=pdf_buffer.getvalue(),
                file_name=pdf_filename,
                mime="application/pdf",
            )

        st.info(
            "Os resultados permanecem na tela após o download. "
            "Um e-mail único foi enviado com o PDF do relatório e a planilha de uso."
        )


if __name__ == "__main__":
    main()
