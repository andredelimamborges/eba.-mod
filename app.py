# app.py
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import streamlit as st

from eba_config import (
    APP_NAME,
    APP_VERSION,
    APP_TAGLINE,
    gerar_perfil_cargo_dinamico,
)
from eba_llm import (
    TokenTracker,
    get_api_key_for_provider,
    extract_bfa_data,
    analyze_bfa_data,
    chat_with_elder_brain,
    send_admin_report_if_configured,
    send_pdf_report_email,
)
from eba_reports import gerar_pdf_corporativo


# ========= EXTRAÇÃO DE TEXTO DE PDF =========
try:
    import pypdf  # biblioteca leve para leitura de PDF
except Exception:
    pypdf = None  # type: ignore


def extract_text_from_pdf(file) -> str:
    """Extrai texto de um PDF usando pypdf, se disponível."""
    if pypdf is None:
        raise RuntimeError(
            "Biblioteca 'pypdf' não está instalada. "
            "Adicione 'pypdf' ao requirements.txt para habilitar extração de PDF."
        )
    reader = pypdf.PdfReader(file)
    texts = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        texts.append(txt)
    return "\n\n".join(texts).strip()


# ========= CONFIG BÁSICA =========
DEFAULT_PROVIDER = "groq"
DEFAULT_MODEL_ID = "llama-3.1-8b-instant"


def init_session_state() -> None:
    if "email_empresarial" not in st.session_state:
        st.session_state.email_empresarial = ""
    if "bfa_data" not in st.session_state:
        st.session_state.bfa_data = None
    if "analysis" not in st.session_state:
        st.session_state.analysis = None
    if "pdf_buffer" not in st.session_state:
        st.session_state.pdf_buffer = None
    if "last_error" not in st.session_state:
        st.session_state.last_error = ""


# ========= UI AUXILIAR =========
def render_header():
    st.title(APP_NAME)
    st.caption(f"{APP_TAGLINE} · v{APP_VERSION}")


def render_sidebar():
    st.sidebar.markdown("### Sobre o Elder Brain Analytics")
    st.sidebar.write(
        "Ferramenta de apoio à decisão para **análise comportamental BFA** "
        "e aderência a cargos, desenvolvida para uso corporativo."
    )
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Versão:** " + APP_VERSION)
    st.sidebar.markdown("**Módulo:** Relatórios BFA → PDF corporativo")


def render_result_panel():
    """Painel da direita com resumo do resultado e botão de download."""
    bfa_data = st.session_state.bfa_data
    analysis = st.session_state.analysis
    pdf_buffer: Optional[io.BytesIO] = st.session_state.pdf_buffer

    if not analysis or not bfa_data:
        st.info(
            "📄 Após processar um laudo BFA, o resumo executivo e o botão de download "
            "do relatório em PDF aparecerão aqui."
        )
        return

    st.subheader("Resumo Executivo")

    # métricas principais
    col_a, col_b, col_c = st.columns(3)
    compat = float(analysis.get("compatibilidade_geral", 0) or 0)
    decisao = analysis.get("decisao", "N/A")
    cargos_alt = analysis.get("cargos_alternativos", []) or []

    with col_a:
        st.metric("Compatibilidade Geral", f"{compat:.0f}%")
    with col_b:
        st.metric("Decisão", decisao)
    with col_c:
        st.metric("Cargos alternativos sugeridos", len(cargos_alt))

    resumo_exec = analysis.get("resumo_executivo") or ""
    if resumo_exec:
        st.markdown("#### Síntese da Avaliação")
        st.write(resumo_exec)

    # recomendações
    recs = analysis.get("recomendacoes_desenvolvimento", []) or []
    if recs:
        st.markdown("#### Recomendações de desenvolvimento")
        for r in recs:
            if r:
                st.write(f"- {r}")

    # botão de download do PDF
    if pdf_buffer is not None:
        st.markdown("---")
        candidato = (bfa_data or {}).get("candidato", {}) or {}
        nome_cand = candidato.get("nome") or "candidato"
        file_name = f"eba_relatorio_{nome_cand.replace(' ', '_')}.pdf"

        st.download_button(
            label="⬇️ Baixar relatório em PDF",
            data=pdf_buffer,
            file_name=file_name,
            mime="application/pdf",
            use_container_width=True,
        )
    else:
        st.warning(
            "O relatório ainda não foi gerado em PDF nesta sessão. "
            "Clique em **Processar relatório** novamente se necessário."
        )


# ========= FLUXO PRINCIPAL =========
def main():
    st.set_page_config(
        page_title=APP_NAME,
        page_icon="🧠",
        layout="wide",
    )
    init_session_state()

    render_header()
    render_sidebar()

    col_left, col_right = st.columns([1.2, 1])

    with col_left:
        st.subheader("Entrada do Laudo BFA")

        cargo = st.text_input(
            "Cargo avaliado",
            value="",
            placeholder="Ex.: Engenheiro de Software Pleno",
            help="Nome do cargo ou função que está sendo avaliada.",
        )

        email_empresarial = st.text_input(
            "Email empresarial *",
            key="email_empresarial",
            placeholder="nome.sobrenome@empresa.com",
            help=(
                "E-mail corporativo utilizado para registro de uso e envio automático do relatório. "
                "Campo obrigatório."
            ),
        )

        st.markdown("##### Laudo BFA")
        uploaded_pdf = st.file_uploader(
            "Anexe o laudo BFA em PDF (opcional)",
            type=["pdf"],
            help="Se preferir, você também pode colar o laudo em texto logo abaixo.",
        )
        raw_text = st.text_area(
            "Ou cole o laudo BFA em formato de texto",
            value="",
            height=260,
        )

        processar = st.button(
            "⚙️ Processar relatório",
            type="primary",
            use_container_width=True,
        )

        if processar:
            # validações básicas
            if not email_empresarial or "@" not in email_empresarial:
                st.error("Informe um **e-mail empresarial válido** para continuar.")
                return

            if not cargo.strip():
                st.error("Informe o **cargo avaliado** para continuar.")
                return

            texto_laudo = ""
            if uploaded_pdf is not None:
                try:
                    texto_laudo = extract_text_from_pdf(uploaded_pdf)
                except Exception as e:
                    st.error(
                        f"Não foi possível extrair o texto do PDF: {e}. "
                        "Você pode colar o texto manualmente no campo abaixo."
                    )
                    return
            elif raw_text.strip():
                texto_laudo = raw_text.strip()
            else:
                st.error(
                    "Anexe um PDF ou cole o laudo em texto para que o Elder Brain Analytics possa analisar."
                )
                return

            if len(texto_laudo) < 500:
                st.warning(
                    "O laudo parece muito curto. Considere utilizar o relatório completo "
                    "para obter uma análise mais robusta."
                )

            with st.spinner("Processando laudo com o Elder Brain Analytics..."):
                provider = DEFAULT_PROVIDER
                model_id = DEFAULT_MODEL_ID

                # token da API (Groq ou outro) vem dos secrets
                try:
                    api_key = get_api_key_for_provider(provider)
                except Exception as e:
                    st.error(f"Erro ao obter chave da API: {e}")
                    return

                tracker = TokenTracker(model=model_id, provider=provider)

                # contexto de treinamento → por enquanto vazio (rodando "em segundo plano" no futuro)
                training_context = ""

                # 1) Extração estruturada
                bfa_data, extr_raw = extract_bfa_data(
                    text=texto_laudo,
                    cargo=cargo,
                    training_context=training_context,
                    provider=provider,
                    model_id=model_id,
                    token=api_key,
                    tracker=tracker,
                )
                if bfa_data is None:
                    st.error(
                        "Falha na etapa de **extração dos dados BFA**. "
                        f"Detalhes: {extr_raw}"
                    )
                    return

                # 2) Geração de perfil ideal dinâmico + análise de fit
                try:
                    perfil_cargo = gerar_perfil_cargo_dinamico(cargo)
                except Exception:
                    perfil_cargo = {}

                analysis, anal_raw = analyze_bfa_data(
                    bfa_data=bfa_data,
                    cargo=cargo,
                    perfil_cargo=perfil_cargo,
                    provider=provider,
                    model_id=model_id,
                    token=api_key,
                    tracker=tracker,
                )
                if analysis is None:
                    st.error(
                        "Falha na etapa de **análise de compatibilidade**. "
                        f"Detalhes: {anal_raw}"
                    )
                    return

                # guarda no session_state
                st.session_state.bfa_data = bfa_data
                st.session_state.analysis = analysis

                # 3) Geração do PDF corporativo
                try:
                    pdf_buffer = gerar_pdf_corporativo(
                        bfa_data=bfa_data,
                        analysis=analysis,
                        cargo=cargo,
                        logo_path=None,  # se tiver logo, coloque o caminho aqui
                    )
                    st.session_state.pdf_buffer = pdf_buffer
                except Exception as e:
                    st.session_state.pdf_buffer = None
                    st.error(f"Erro ao gerar o PDF corporativo: {e}")
                    return

                # 4) Envio de log técnico (Excel) para o administrador
                candidato = (bfa_data or {}).get("candidato", {}) or {}
                nome_candidato = candidato.get("nome", "")

                send_admin_report_if_configured(
                    tracker=tracker,
                    provider=provider,
                    model=model_id,
                    meta={
                        "cargo": cargo,
                        "email_empresarial": email_empresarial,
                        "nome_candidato": nome_candidato,
                    },
                )

                # 5) Envio automático do PDF por e-mail (cofre + analista)
                try:
                    pdf_bytes = pdf_buffer.getvalue()
                except Exception:
                    pdf_bytes = None

                if pdf_bytes:
                    send_pdf_report_email(
                        pdf_bytes=pdf_bytes,
                        meta={
                            "cargo": cargo,
                            "email_empresarial": email_empresarial,
                            "nome_candidato": nome_candidato,
                        },
                    )

                st.success("Relatório processado com sucesso! 🎯")

    with col_right:
        render_result_panel()

        # opcional: espaço para dúvidas ao Elder Brain sobre o mesmo laudo
        bfa_data = st.session_state.bfa_data
        analysis = st.session_state.analysis
        if bfa_data and analysis:
            st.markdown("---")
            st.markdown("#### Pergunte ao Elder Brain sobre este candidato")
            question = st.text_input(
                "Digite uma pergunta (opcional)",
                placeholder="Ex.: Quais são os principais riscos deste perfil para uma função de liderança?",
            )
            if st.button("Perguntar", use_container_width=True):
                provider = DEFAULT_PROVIDER
                model_id = DEFAULT_MODEL_ID

                try:
                    api_key = get_api_key_for_provider(provider)
                except Exception as e:
                    st.error(f"Erro ao obter chave da API: {e}")
                    return

                tracker = TokenTracker(model=model_id, provider=provider)
                answer = chat_with_elder_brain(
                    question=question,
                    bfa_data=bfa_data,
                    analysis=analysis,
                    cargo="",
                    provider=provider,
                    model_id=model_id,
                    token=api_key,
                    tracker=tracker,
                )
                st.write(answer)


if __name__ == "__main__":
    main()
