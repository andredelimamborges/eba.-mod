# app.py
from __future__ import annotations

import os
import re
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from eba_config import (
    APP_NAME,
    APP_TAGLINE,
    DARK_CSS,
    MODELOS_SUGERIDOS_GROQ,
    MODELOS_SUGERIDOS_OPENAI,
    PROCESSED_DIR,
    extract_pdf_text_bytes,
    gerar_perfil_cargo_dinamico,
    load_all_training_texts,
)
from eba_llm import (
    TokenTracker,
    get_api_key_for_provider,
    extract_bfa_data,
    analyze_bfa_data,
    chat_with_elder_brain,
    send_admin_report_if_configured,
)
from eba_reports import (
    criar_radar_bfa,
    criar_grafico_competencias,
    criar_gauge_fit,
    gerar_pdf_corporativo,
)


def kpi_card(title: str, value: str, sub: str | None = None) -> None:
    st.markdown(
        f'<div class="kpi-card"><div style="font-weight:700;font-size:1.02rem">{title}</div>'
        f'<div style="font-size:1.9rem;margin:.2rem 0 .25rem 0">{value}</div>'
        f'<div class="small">{sub or ""}</div></div>',
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title=f"{APP_NAME} (PROD)",
        page_icon="🧠",
        layout="wide",
    )
    st.markdown(DARK_CSS, unsafe_allow_html=True)

    ss = st.session_state
    ss.setdefault("provider", "Groq")
    ss.setdefault("modelo", "llama-3.1-8b-instant")
    ss.setdefault("cargo", "")
    ss.setdefault("analysis_complete", False)
    ss.setdefault("bfa_data", None)
    ss.setdefault("analysis", None)
    ss.setdefault("pdf_generated", None)
    ss.setdefault("tracker", TokenTracker())

    # título
    st.markdown(f"## 🧠 {APP_NAME} — Corporate (PROD • Full)")
    st.markdown(
        '<span class="badge">PDF Deluxe</span> '
        '<span class="badge">Seguro</span> '
        '<span class="badge">Streamlit Cloud</span>',
        unsafe_allow_html=True,
    )

    # sidebar
    with st.sidebar:
        st.header("⚙️ Configuração")
        provider = st.radio("Provedor", ["Groq", "OpenAI"], index=0, key="provider")
        modelo = st.text_input(
            "Modelo",
            value=ss["modelo"],
            help=(
                "Sugestões: "
                + ", ".join(
                    MODELOS_SUGERIDOS_GROQ
                    if provider == "Groq"
                    else MODELOS_SUGERIDOS_OPENAI
                )
            ),
        )
        ss["modelo"] = modelo

        # API key via secrets (sem campo visível)
        try:
            token = get_api_key_for_provider(provider)
        except RuntimeError as e:
            token = ""
            st.error(str(e))

        st.caption("Configuração de IA controlada via secrets (segura).")
        ss["cargo"] = st.text_input("Cargo para análise", value=ss["cargo"])

    # KPIs topo (sem admin, sem custo visível)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        status_txt = "Pronto" if not ss.get("analysis_complete") else "Concluído"
        kpi_card("Status", status_txt, "Pipeline de análise")
    with c2:
        kpi_card("Relatórios (sessão)", "—", "controle futuro")
    with c3:
        kpi_card("Andamento", "Online", "IA disponível")
    with c4:
        kpi_card("Modo", "Usuário", "sem painel admin")

    # upload + treinamento
    st.markdown("### 📄 Upload do Relatório BFA")
    uploaded_file = st.file_uploader("Carregue o PDF do relatório BFA", type=["pdf"])

    with st.expander("📚 Materiais de Treinamento (Opcional)"):
        training_files = st.file_uploader(
            "Arraste PDFs/TXTs", accept_multiple_files=True, key="training"
        )
        if training_files:
            from eba_config import TRAINING_DIR

            for f in training_files:
                save_path = os.path.join(TRAINING_DIR, f"{int(time.time())}_{f.name}")
                with open(save_path, "wb") as out:
                    out.write(f.getbuffer())
            st.success(f"{len(training_files)} arquivo(s) salvos")

    # processamento
    if uploaded_file:
        if not ss["cargo"]:
            st.error("Informe o cargo na sidebar antes de processar.")
            st.stop()
        if not token:
            # erro de secrets já foi mostrado
            st.stop()
        if not (ss["modelo"] and ss["modelo"].strip()):
            st.error("Informe o modelo de IA na sidebar.")
            st.stop()

        with st.spinner("Extraindo texto do PDF..."):
            raw_text = extract_pdf_text_bytes(uploaded_file)
        if raw_text.startswith("[ERRO"):
            st.error(raw_text)
            st.stop()
        st.success("✓ Texto extraído com sucesso")

        # (removido: prévia do texto)

        if st.button("🔬 ANALISAR RELATÓRIO", type="primary", use_container_width=True):
            training_context = load_all_training_texts()
            tracker: TokenTracker = ss["tracker"]
            tracker.model, tracker.provider = ss["modelo"], ss["provider"]

            perfil_cargo = gerar_perfil_cargo_dinamico(ss["cargo"])

            with st.spinner("Etapa 1/2: Extraindo dados estruturados..."):
                bfa_data, raw1 = extract_bfa_data(
                    raw_text,
                    ss["cargo"],
                    training_context,
                    ss["provider"],
                    ss["modelo"],
                    token,
                    tracker,
                )
            if not bfa_data:
                st.error("Falha na extração de dados do relatório.")
                with st.expander("Resposta bruta da IA"):
                    st.code(raw1)
                st.stop()

            with st.spinner("Etapa 2/2: Analisando compatibilidade..."):
                analysis, raw2 = analyze_bfa_data(
                    bfa_data,
                    ss["cargo"],
                    perfil_cargo,
                    ss["provider"],
                    ss["modelo"],
                    token,
                    tracker,
                )
            if not analysis:
                st.error("Falha na análise de compatibilidade.")
                with st.expander("Resposta bruta da IA"):
                    st.code(raw2)
                st.stop()

            ss["bfa_data"], ss["analysis"], ss["analysis_complete"] = (
                bfa_data,
                analysis,
                True,
            )

            # envia o "relatório admin" de tokens/custo por email, se configurado
            send_admin_report_if_configured(
                tracker=tracker,
                provider=ss["provider"],
                model=ss["modelo"],
            )

            st.success("✓ Análise concluída!")
            st.rerun()

    # resultados
    if ss.get("analysis_complete") and ss.get("bfa_data") and ss.get("analysis"):
        st.markdown("## 📊 Resultados")
        decisao = ss["analysis"].get("decisao", "N/A")
        compat = float(ss["analysis"].get("compatibilidade_geral", 0) or 0)

        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.markdown(f"### 🏷️ Decisão: **{decisao}**")
        with c2:
            st.metric("Compatibilidade", f"{compat:.0f}%")
        with c3:
            st.metric("Liderança", ss["bfa_data"].get("potencial_lideranca", "N/A"))

        with st.expander("📋 Resumo Executivo", expanded=True):
            st.write(ss["analysis"].get("resumo_executivo", ""))
        st.info(ss["analysis"].get("justificativa_decisao", ""))

        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            ["🎯 Big Five", "💼 Competências", "🧘 Saúde Emocional", "📈 Desenvolvimento", "📄 Dados Brutos"]
        )

        perfil_tab = gerar_perfil_cargo_dinamico(ss["cargo"])

        with tab1:
            traits = ss["bfa_data"].get("traits_bfa", {})
            fig_radar = criar_radar_bfa(
                traits, perfil_tab.get("traits_ideais", {})
            )
            st.plotly_chart(fig_radar, use_container_width=True)
            traits_ideais = perfil_tab.get("traits_ideais", {})
            df_traits = pd.DataFrame(
                [
                    {
                        "Traço": k,
                        "Valor": (
                            f"{(traits.get(k) if traits.get(k) is not None else 0):.1f}/10"
                            if traits.get(k) is not None
                            else "N/A"
                        ),
                        "Faixa Ideal": f"{traits_ideais.get(k, (0, 10))[0]:.0f}-{traits_ideais.get(k, (0, 10))[1]:.0f}",
                    }
                    for k in [
                        "Abertura",
                        "Conscienciosidade",
                        "Extroversão",
                        "Amabilidade",
                        "Neuroticismo",
                    ]
                ]
            )
            st.dataframe(df_traits, use_container_width=True, hide_index=True)
            st.markdown("##### Análise Detalhada")
            for trait, txt in (ss["analysis"].get("analise_tracos", {}) or {}).items():
                with st.expander(f"**{trait}**"):
                    st.write(txt)

        with tab2:
            comps = ss["bfa_data"].get("competencias_ms", [])
            figc = criar_grafico_competencias(comps)
            if figc:
                st.plotly_chart(figc, use_container_width=True)
            st.markdown("##### Competências Críticas")
            for comp in ss["analysis"].get("competencias_criticas", []):
                status = comp.get("status")
                compn = comp.get("competencia")
                txt = comp.get("avaliacao", "")
                if status == "ATENDE":
                    st.success(f"✓ {compn} — {status}")
                    st.caption(txt)
                elif status == "PARCIAL":
                    st.warning(f"⚠ {compn} — {status}")
                    st.caption(txt)
                else:
                    st.error(f"✗ {compn} — {status}")
                    st.caption(txt)
            if comps:
                with st.expander("Ver todas as competências"):
                    df_comp = pd.DataFrame(comps).sort_values("nota", ascending=False)
                    st.dataframe(df_comp, use_container_width=True, hide_index=True)
            else:
                st.warning("Nenhuma competência extraída.")

        with tab3:
            st.subheader("Saúde Emocional e Resiliência")
            st.write(ss["analysis"].get("saude_emocional_contexto", ""))
            indicadores = ss["bfa_data"].get("indicadores_saude_emocional", {})
            if any(v is not None for v in indicadores.values()):
                st.markdown("##### Indicadores (0-100, menor melhor)")
                cols = st.columns(2)
                for i, (k, v) in enumerate(indicadores.items()):
                    if v is None:
                        continue
                    with cols[i % 2]:
                        st.metric(k.replace("_", " ").title(), f"{float(v):.0f}")
            facetas = ss["bfa_data"].get("facetas_relevantes", [])
            if facetas:
                with st.expander("Facetas detalhadas"):
                    for f in facetas:
                        st.markdown(
                            f"**{f.get('nome','')}** (Percentil: {f.get('percentil',0):.0f})"
                        )
                        st.caption(f.get("interpretacao", ""))
                        st.markmarkdown("---")

        with tab4:
            st.subheader("Plano de Desenvolvimento")
            recs = ss["analysis"].get("recomendacoes_desenvolvimento", [])
            if recs:
                for i, r in enumerate(recs, 1):
                    st.markdown(f"**{i}.** {r}")
            pf = ss["bfa_data"].get("pontos_fortes", [])
            if pf:
                st.markdown("##### ✅ Pontos Fortes")
                for x in pf:
                    st.success(f"• {x}")
            pa = ss["bfa_data"].get("pontos_atencao", [])
            if pa:
                st.markdown("##### ⚠️ Pontos de Atenção")
                for x in pa:
                    st.warning(f"• {x}")
            alt = ss["analysis"].get("cargos_alternativos", [])
            if alt:
                st.markdown("##### 🔄 Cargos Alternativos")
                for c in alt:
                    with st.expander(f"**{c.get('cargo','')}**"):
                        st.write(c.get("justificativa", ""))

        with tab5:
            c1, c2 = st.columns(2)
            with c1:
                st.json(ss["bfa_data"])
            with c2:
                st.json(ss["analysis"])

        st.markdown("### 🎯 Compatibilidade")
        st.plotly_chart(criar_gauge_fit(compat), use_container_width=True)

        st.markdown("### 📄 Gerar PDF")
        logo_path = st.text_input("Caminho para logo (opcional)", value="")
        if logo_path and not os.path.exists(logo_path):
            st.warning("Caminho de logo informado não existe; logo será ignorado no PDF.")

        if st.button("🔨 Gerar PDF", key="gen_pdf"):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            nome = ((ss["bfa_data"].get("candidato", {}) or {}).get("nome") or "candidato")
            nome = re.sub(r"[^\w\s-]", "", str(nome)).strip().replace(" ", "_")
            fname = f"relatorio_{nome}_{ts}.pdf"
            path = os.path.join(PROCESSED_DIR, fname)
            buf = gerar_pdf_corporativo(
                ss["bfa_data"],
                ss["analysis"],
                ss["cargo"],
                save_path=path,
                logo_path=logo_path if logo_path and os.path.exists(logo_path) else None,
            )
            ss["tracker"].add("pdf", 0, 0)
            if buf.getbuffer().nbytes > 100:
                ss["pdf_generated"] = {"buffer": buf, "filename": fname}
                st.success(f"✓ PDF gerado: {fname}")
            else:
                st.error("Arquivo PDF vazio (erro na geração).")

        if ss.get("pdf_generated"):
            st.download_button(
                "⬇️ Download do PDF",
                data=ss["pdf_generated"]["buffer"].getvalue(),
                file_name=ss["pdf_generated"]["filename"],
                mime="application/pdf",
                use_container_width=True,
            )

        st.markdown("### 💬 Chat com o Elder Brain")
        q = st.text_input(
            "Pergunte sobre este relatório",
            placeholder="Ex.: Principais riscos para este cargo?",
        )
        if q and st.button("Enviar", key="ask"):
            with st.spinner("Pensando..."):
                ans = chat_with_elder_brain(
                    q,
                    ss["bfa_data"],
                    ss["analysis"],
                    ss["cargo"],
                    ss["provider"],
                    ss["modelo"],
                    token,
                    ss["tracker"],
                )
            st.markdown(f"**Você:** {q}")
            st.markdown(f"**Elder Brain:** {ans}")

    st.caption(f"📁 Relatórios salvos em: `{PROCESSED_DIR}`")


if __name__ == "__main__":
    main()
