from __future__ import annotations

import re
from datetime import datetime

import streamlit as st

from eba_reports import (
    criar_radar_bfa,
    criar_grafico_competencias,
    criar_gauge_fit,
    gerar_pdf_corporativo,
)
from eba_config import gerar_perfil_cargo_dinamico
from eba_utils import (
    extract_text_from_pdf,
    limpar_nome_empresa,
    UsageTracker,
    send_usage_excel_if_configured,
    send_report_email_if_configured,
)
from eba_llm import run_extracao, run_analise


# ======================================================
# EXTRAÇÕES AUXILIARES (PDF -> TEXTO)
# ======================================================
def extrair_cargo_do_texto(texto: str) -> str:
    if not texto:
        return ""

    # caso 1: "Cargo: alguma coisa"
    m = re.search(r"\bcargo\b\s*[:\-]\s*(.+)", texto, flags=re.IGNORECASE)
    if m:
        cargo = m.group(1).strip()
        cargo = cargo.split("\n")[0].strip()
        return cargo

    # caso 2: bloco "Cargo" numa linha e valor na linha seguinte
    m = re.search(r"\bcargo\b\s*\n\s*([^\n]{2,80})", texto, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return ""


def interpretar_big_five(nome, valor):
    v = float(valor)
    if nome == "Neuroticismo":
        if v <= 4.5:
            return "nível saudável → boa regulação emocional."
        elif v <= 6:
            return "nível moderado → atenção situacional."
        return "nível elevado → risco emocional."

    if v < 4.5:
        return "nível baixo → ponto de desenvolvimento."
    elif v < 6.5:
        return "nível moderado → equilíbrio natural."
    return "nível alto → força clara nesse traço."


def classificar_competencias(lista):
    fortes, criticas = [], []
    for c in lista:
        try:
            nota = float(c.get("nota", 0))
        except Exception:
            continue
        nome = c.get("nome", "")
        if nota >= 55:
            fortes.append(nome)
        elif nota < 45:
            criticas.append(nome)
    return fortes, criticas


# ======================================================
# UI
# ======================================================
st.set_page_config(page_title="Elder Brain Analytics", page_icon="🧠", layout="wide")
st.title("🧠 Elder Brain Analytics")
st.caption("Avaliação comportamental avançada para tomada de decisão em RH")

with st.form("eba_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        email_analista = st.text_input("e-mail do analista", placeholder="analista@empresa.com")
    with col2:
        cargo_input = st.text_input("cargo avaliado", placeholder="ex: engenheiro de software pleno (opcional)")
    with col3:
        empresa_input = st.text_input("empresa", placeholder="ex: ms solutions (opcional)")

    uploaded_file = st.file_uploader("upload do relatório bfa (pdf ou txt)", type=["pdf", "txt"])
    submitted = st.form_submit_button("processar relatório")


# ======================================================
# PROCESSAMENTO
# ======================================================
if submitted:
    if not uploaded_file:
        st.error("envie o relatório.")
        st.stop()

    # 1) extrai texto
    texto = extract_text_from_pdf(uploaded_file)
    if not texto.strip():
        st.error("não foi possível extrair texto do relatório.")
        st.stop()

    # 2) cargo: input tem prioridade; se vazio, tenta extrair do pdf
    cargo_final = cargo_input.strip() if cargo_input else ""
    if not cargo_final:
        cargo_final = extrair_cargo_do_texto(texto)

    if not cargo_final:
        st.error("não consegui identificar o cargo no pdf. preencha o campo 'cargo avaliado'.")
        st.stop()

    # 3) empresa: input tem prioridade; se vazio, tenta extrair do texto
    empresa = limpar_nome_empresa(empresa_input) if empresa_input else ""

    if not empresa:
        empresa_match = re.search(
            r"(empresa|organização|companhia)\s*[:\-]\s*(.+)",
            texto,
            re.I,
        )
        empresa = limpar_nome_empresa(empresa_match.group(2)) if empresa_match else ""

    if not empresa:
        st.error("empresa é obrigatória. informe no formulário ou no relatório.")
        st.stop()

    # 4) tracker
    tracker = UsageTracker(
        provider="groq",
        email=email_analista or "",
        empresa=empresa,
        cargo=cargo_final,
    )

    # 5) extração llm
    with st.spinner("extraindo dados do relatório..."):
        bfa_data = run_extracao(text=texto, cargo=cargo_final, tracker=tracker)

        # garante empresa no payload (top-level e candidato)
        if empresa:
            bfa_data["empresa"] = empresa
            if "candidato" not in bfa_data or not isinstance(bfa_data["candidato"], dict):
                bfa_data["candidato"] = {}
            bfa_data["candidato"]["empresa"] = empresa

    # 6) análise llm
    with st.spinner("analisando perfil comportamental..."):
        analysis = run_analise(bfa_data=bfa_data, cargo=cargo_final, tracker=tracker)

    # 7) pdf
    with st.spinner("gerando relatório pdf..."):
        pdf_buf = gerar_pdf_corporativo(bfa_data, analysis, cargo_final)

    pdf_bytes = pdf_buf.getvalue() if hasattr(pdf_buf, "getvalue") else bytes(pdf_buf)

    # 8) sessão
    st.session_state["analysis"] = analysis
    st.session_state["bfa_data"] = bfa_data
    st.session_state["pdf_bytes"] = pdf_bytes
    st.session_state["cargo"] = cargo_final

    # 9) e-mails
    send_usage_excel_if_configured(tracker, email_analista, cargo_final)
    send_report_email_if_configured(tracker, email_analista, cargo_final, pdf_bytes)


# ======================================================
# DASHBOARD
# ======================================================
if "analysis" in st.session_state and "bfa_data" in st.session_state:
    analysis = st.session_state.get("analysis") or {}
    bfa_data = st.session_state.get("bfa_data") or {}
    cargo = st.session_state.get("cargo", "")

    if not cargo:
        st.warning("sessão recarregada. refaça o processamento do relatório.")
        st.stop()

    st.divider()
    st.header("📊 dashboard analítico — elder brain")

    perfil = gerar_perfil_cargo_dinamico(cargo)
    traits_ideais = (perfil or {}).get("traits_ideais", {})

    tabs = st.tabs(["🎯 perfil big five", "💼 competências", "🧘 saúde emocional", "📈 desenvolvimento", "📄 dados brutos"])

    with tabs[0]:
        traits = bfa_data.get("traits_bfa", {}) or {}
        ordem = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]
        st.subheader("🎯 perfil big five — interpretação")
        for k in ordem:
            v = traits.get(k)
            if v is None:
                k2 = k.replace("ã", "a").replace("ç", "c").replace("õ", "o").replace("é", "e")
                v = traits.get(k2)
            if v is not None:
                st.write(f"• **{k} ({float(v):.1f}/10)**: {interpretar_big_five(k, v)}")
        st.plotly_chart(criar_radar_bfa(traits, traits_ideais), use_container_width=True)

    with tabs[1]:
        competencias = bfa_data.get("competencias_ms", []) or []
        fortes, criticas = classificar_competencias(competencias)

        st.subheader("💼 competências — leitura geral")
        if fortes:
            st.markdown("🔹 **pontos de força**")
            for f in fortes:
                st.write(f"• {f} — desempenho consistente para o cargo.")
        if criticas:
            st.markdown("🔸 **pontos críticos**")
            for c in criticas:
                st.write(f"• {c} — requer acompanhamento e plano de desenvolvimento.")

        fig_comp = criar_grafico_competencias(competencias)
        if fig_comp:
            st.plotly_chart(fig_comp, use_container_width=True)

    with tabs[2]:
        saude = bfa_data.get("indicadores_saude_emocional", {}) or {}
        st.subheader("🧘 saúde emocional — justificativa completa")
        for k, v in saude.items():
            if v is not None:
                st.write(f"• **{k.replace('_',' ').capitalize()}**: {int(v)}/100 → nível saudável, dentro do esperado.")

        contexto = (analysis or {}).get("saude_emocional_contexto", "")
        if contexto:
            st.markdown("**contextualização da ia**")
            st.write(contexto)

        st.plotly_chart(criar_gauge_fit((analysis or {}).get("compatibilidade_geral", 0)), use_container_width=True)

    with tabs[3]:
        st.subheader("📈 recomendações de desenvolvimento — versão ampliada")
        for i, rec in enumerate((analysis or {}).get("recomendacoes_desenvolvimento", []) or [], 1):
            st.write(f"{i}. {rec}")

        st.markdown("**sugestões adicionais (elder brain)**")
        st.write("• treinamentos recomendados: inteligência emocional, comunicação assertiva, gestão de conflitos.")
        st.write("• rotina sugerida: feedback quinzenal estruturado com liderança.")
        st.write("• foco de curto prazo: trabalhar competências críticas e traços ligados à resiliência.")

        cargos_alt = (analysis or {}).get("cargos_alternativos", []) or []
        if cargos_alt:
            st.markdown("**cargos alternativos sugeridos**")
            for c in cargos_alt:
                st.write(f"• **{c.get('cargo')}** — {c.get('justificativa')}")

    with tabs[4]:
        st.json(bfa_data)

    if st.session_state.get("pdf_bytes"):
        st.download_button(
            "📄 baixar relatório em pdf",
            data=st.session_state["pdf_bytes"],
            file_name=f"EBA_Relatorio_{cargo.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}.pdf",
            mime="application/pdf",
            key="download_pdf_final",
        )
