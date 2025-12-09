# app.py
"""
Elder Brain Analytics — Corporate (Módulos)
Front principal com:
- Upload de relatório BFA
- Extração + Análise (via eba_llm)
- Visualizações e PDF corporativo (via eba_reports)
"""

from __future__ import annotations

import os
import re
import json
import time
from datetime import datetime
from typing import Any, Dict

import pandas as pd
import streamlit as st
from pdfminer.high_level import extract_text

# ===== imports internos =====
from eba_llm import (
    TokenTracker,
    extract_bfa_data,
    analyze_bfa_data,
    chat_with_elder_brain,
    send_admin_report_if_configured,
    get_api_key_for_provider,
)

from eba_reports import (
    criar_radar_bfa,
    criar_grafico_competencias,
    criar_gauge_fit,
    gerar_pdf_corporativo,
)

# tentar importar configs/cosmeticos; se não existir, usa defaults
try:
    from eba_config import (
        DARK_CSS,
        PROCESSED_DIR,
        TRAINING_DIR,
        gerar_perfil_cargo_dinamico,
    )
except Exception:  # fallback seguro
    DARK_CSS = ""
    PROCESSED_DIR = "relatorios_processados"
    TRAINING_DIR = "training_data"

    def gerar_perfil_cargo_dinamico(cargo: str) -> Dict[str, Any]:
        return {"traits_ideais": {}, "competencias_criticas": []}

# garantir pastas
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(TRAINING_DIR, exist_ok=True)


# ===== utils de PDF / treinamento =====
def extract_pdf_text_bytes(file) -> str:
    """Lê o PDF enviado e retorna o texto plano."""
    try:
        return extract_text(file)
    except Exception as e:
        return f"[ERRO_EXTRACAO_PDF] {e}"


def load_all_training_texts() -> str:
    """
    Carrega todos os PDFs/TXTs da pasta TRAINING_DIR e junta num contexto.
    (treinamento em segundo plano, sem UI).
    """
    texts = []
    try:
        fnames = sorted(os.listdir(TRAINING_DIR))
    except FileNotFoundError:
        return ""

    for fname in fnames:
        path = os.path.join(TRAINING_DIR, fname)
        try:
            if fname.lower().endswith(".pdf"):
                with open(path, "rb") as f:
                    txt = extract_text(f)
            else:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
            texts.append(f"--- {fname} ---\n{txt[:2000]}\n")
        except Exception:
            continue
    return "\n".join(texts)


# ===== componente KPI =====
def kpi_card(title: str, value: str, sub: str | None = None) -> None:
    st.markdown(
        f"""
        <div class="kpi-card">
          <div style="font-weight:700;font-size:1.02rem">{title}</div>
          <div style="font-size:1.9rem;margin:.2rem 0 .25rem 0">{value}</div>
          <div class="small">{sub or ""}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ===== app principal =====
def main() -> None:
    st.set_page_config(
        page_title="EBA — Corporate",
        page_icon="🧠",
        layout="wide",
    )
    if DARK_CSS:
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
    ss.setdefault("email_empresarial", "")

    tracker: TokenTracker = ss["tracker"]

    # ===== topo =====
    st.markdown("## 🧠 Elder Brain Analytics — Corporate")
    st.markdown(
        '<span class="badge">PDF Corporativo</span> '
        '<span class="badge">Seguro</span> '
        '<span class="badge">Streamlit Cloud</span>',
        unsafe_allow_html=True,
    )

    # ===== sidebar (config enxuta) =====
    with st.sidebar:
        st.header("⚙️ configuração")

        # provedor/modelo fixos (Groq) — não aparecem na UI
        provider = "Groq"
        modelo = "llama-3.1-8b-instant"
        ss["provider"] = provider
        ss["modelo"] = modelo

        # token via secrets
        try:
            token = get_api_key_for_provider(provider)
        except Exception as e:
            st.error(f"Erro na configuração da API: {e}")
            token = ""

        st.caption("motor de ia: Groq · temperatura 0.3 · máx. 4096 tokens")

        # cargo
        ss["cargo"] = st.text_input("Cargo para análise", value=ss.get("cargo", ""))

        # email empresarial
        email_empresarial = st.text_input(
            "Email empresarial (opcional)",
            value=ss.get("email_empresarial", ""),
            placeholder="ex.: pessoa@empresa.com",
        )
        ss["email_empresarial"] = email_empresarial

        # perfil dinâmico (ajuda na leitura, mas discreto)
        if ss["cargo"]:
            from eba_config import gerar_perfil_cargo_dinamico as _perfil  # reforço caso exista

            with st.expander("Perfil gerado (dinâmico)"):
                st.json(_perfil(ss["cargo"]))

        st.markdown("---")
        st.caption("admin: logs detalhados são enviados por e-mail (quando configurado).")

    # ===== KPIs =====
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi_card("Status", "Pronto", "aguardando PDF")
    # sem “modo sessão” / sem custo na UI
    with c2:
        kpi_card("Relatórios", "—", "")
    with c3:
        kpi_card("Andamento", "—", "")
    with c4:
        kpi_card("Disponibilidade", "Online", "")

    # ===== upload de relatório =====
    st.markdown("### 📄 Upload do Relatório BFA")
    uploaded_file = st.file_uploader("Carregue o PDF do relatório BFA", type=["pdf"])

    # ===== processamento =====
    if uploaded_file:
        if not ss["cargo"]:
            st.error("Informe o cargo na sidebar antes de processar.")
            st.stop()
        if not token:
            st.error(
                "Chave da API não configurada nos Secrets do Streamlit "
                "(GROQ_API_KEY)."
            )
            st.stop()

        with st.spinner("Extraindo texto do PDF..."):
            raw_text = extract_pdf_text_bytes(uploaded_file)
        if raw_text.startswith("[ERRO_EXTRACAO_PDF]"):
            st.error(raw_text)
            st.stop()
        st.success("✓ texto extraído com sucesso")

        # sem prévia de texto para não poluir a UI

        if st.button("🔬 ANALISAR RELATÓRIO", type="primary", use_container_width=True):
            with st.spinner("Preparando contexto de treinamento..."):
                training_context = load_all_training_texts()  # silencioso

            # etapa 1 — extração estruturada
            with st.spinner("Etapa 1/2: extraindo dados do relatório..."):
                bfa_data, raw1 = extract_bfa_data(
                    text=raw_text,
                    cargo=ss["cargo"],
                    training_context=training_context,
                    provider=provider,
                    model_id=ss["modelo"],
                    token=token,
                    tracker=tracker,
                )

            if not bfa_data:
                st.error("Falha na extração do relatório.")
                with st.expander("Resposta bruta da IA"):
                    st.code(raw1)
                st.stop()

            # etapa 2 — análise de compatibilidade
            perfil_cargo = gerar_perfil_cargo_dinamico(ss["cargo"])
            with st.spinner("Etapa 2/2: analisando compatibilidade..."):
                analysis, raw2 = analyze_bfa_data(
                    bfa_data=bfa_data,
                    cargo=ss["cargo"],
                    perfil_cargo=perfil_cargo,
                    provider=provider,
                    model_id=ss["modelo"],
                    token=token,
                    tracker=tracker,
                )

            if not analysis:
                st.error("Falha na análise de compatibilidade.")
                with st.expander("Resposta bruta da IA"):
                    st.code(raw2)
                st.stop()

            # salvar na sessão
                        # salvar na sessão
            ss["bfa_data"] = bfa_data
            ss["analysis"] = analysis
            ss["analysis_complete"] = True

            st.success("✓ análise concluída!")

            # rerun compatível com versões novas/antigas do Streamlit
            if hasattr(st, "rerun"):
                st.rerun()
            elif hasattr(st, "experimental_rerun"):
                st.experimental_rerun()


    # ===== resultados =====
    if ss.get("analysis_complete") and ss.get("bfa_data") and ss.get("analysis"):
        st.markdown("## 📊 Resultados")

        decisao = ss["analysis"].get("decisao", "N/A")
        compat = float(ss["analysis"].get("compatibilidade_geral", 0) or 0)

        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.markdown(f"### 🏷️ decisão: **{decisao}**")
        with c2:
            st.metric("Compatibilidade", f"{compat:.0f}%")
        with c3:
            st.metric(
                "Liderança",
                ss["bfa_data"].get("potencial_lideranca", "N/A"),
            )

        with st.expander("📋 Resumo Executivo", expanded=True):
            st.write(ss["analysis"].get("resumo_executivo", ""))
        st.info(ss["analysis"].get("justificativa_decisao", ""))

        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            [
                "🎯 Big Five",
                "💼 Competências",
                "🧘 Saúde Emocional",
                "📈 Desenvolvimento",
                "📄 Dados Brutos",
            ]
        )

        # ---- Big Five ----
        with tab1:
            traits = ss["bfa_data"].get("traits_bfa", {}) or {}
            fig_radar = criar_radar_bfa(
                traits,
                gerar_perfil_cargo_dinamico(ss["cargo"]).get("traits_ideais", {}),
            )
            st.plotly_chart(fig_radar, use_container_width=True)

        # ---- Competências ----
        with tab2:
            comps = ss["bfa_data"].get("competencias_ms", []) or []
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
                    df_comp = pd.DataFrame(comps).sort_values(
                        "nota", ascending=False
                    )
                    st.dataframe(
                        df_comp,
                        use_container_width=True,
                        hide_index=True,
                    )
            else:
                st.warning("Nenhuma competência extraída.")

        # ---- Saúde Emocional ----
        with tab3:
            st.subheader("Saúde Emocional e Resiliência")
            st.write(ss["analysis"].get("saude_emocional_contexto", ""))
            indicadores = ss["bfa_data"].get(
                "indicadores_saude_emocional", {}
            ) or {}
            if any(v is not None for v in indicadores.values()):
                st.markdown("##### Indicadores (0–100, menor melhor)")
                cols = st.columns(2)
                for i, (k, v) in enumerate(indicadores.items()):
                    if v is None:
                        continue
                    with cols[i % 2]:
                        st.metric(k.replace("_", " ").title(), f"{float(v):.0f}")
            facetas = ss["bfa_data"].get("facetas_relevantes", []) or []
            if facetas:
                st.markdown("##### Facetas Relevantes")
                for fct in facetas:
                    st.write(f"- **{fct.get('nome','')}**")
                    st.caption(fct.get("interpretacao", ""))

        # ---- Desenvolvimento ----
        with tab4:
            st.subheader("Recomendações de Desenvolvimento")
            recs = ss["analysis"].get("recomendacoes_desenvolvimento", []) or []
            if recs:
                for i, rec in enumerate(recs, 1):
                    st.markdown(f"**{i}. {rec}**")
            else:
                st.caption("Nenhuma recomendação específica foi gerada.")
            cargos_alt = ss["analysis"].get("cargos_alternativos", []) or []
            if cargos_alt:
                st.markdown("##### Cargos Alternativos")
                for c in cargos_alt:
                    st.write(f"- **{c.get('cargo','')}** — {c.get('justificativa','')}")

        # ---- Dados Brutos ----
        with tab5:
            c1, c2 = st.columns(2)
            with c1:
                st.json(ss["bfa_data"])
            with c2:
                st.json(ss["analysis"])

        # gauge de compatibilidade
        st.markdown("### 🎯 Compatibilidade Geral")
        st.plotly_chart(criar_gauge_fit(compat), use_container_width=True)

        # ===== geração de PDF =====
        st.markdown("### 📄 Gerar PDF corporativo")
        logo_path = st.text_input("Caminho para logo (opcional)", value="")

        if st.button("🔨 Gerar PDF", key="gen_pdf"):
            # injeta email empresarial no bfa_data
            email_emp = (ss.get("email_empresarial") or "").strip()
            if email_emp:
                ss.setdefault("bfa_data", {})
                ss["bfa_data"].setdefault("candidato", {})
                ss["bfa_data"]["candidato"]["email_empresarial"] = email_emp

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            nome = (
                (ss["bfa_data"].get("candidato", {}) or {}).get("nome") or "candidato"
            )
            nome = re.sub(r"[^\w\s-]", "", str(nome)).strip().replace(" ", "_")
            fname = f"relatorio_{nome}_{ts}.pdf"
            path = os.path.join(PROCESSED_DIR, fname)

            buf = gerar_pdf_corporativo(
                bfa_data=ss["bfa_data"],
                analysis=ss["analysis"],
                cargo=ss["cargo"],
                save_path=path,
                logo_path=logo_path if logo_path else None,
            )

            # registra passo pdf no tracker
            tracker.add("pdf", 0, 0)

            if buf.getbuffer().nbytes > 100:
                ss["pdf_generated"] = {"buffer": buf, "filename": fname}
                st.success(f"✓ PDF gerado: {fname}")

                # envia relatório admin por e-mail, se configurado
                send_admin_report_if_configured(
                    tracker=tracker,
                    provider=provider,
                    model=modelo,
                )
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

        # ===== chat contextualizado =====
        st.markdown("### 💬 Chat com o Elder Brain")
        q = st.text_input(
            "Pergunte sobre este relatório",
            placeholder="ex.: Principais riscos para este cargo?",
        )
        if q and st.button("Enviar", key="ask"):
            with st.spinner("Pensando..."):
                ans = chat_with_elder_brain(
                    question=q,
                    bfa_data=ss["bfa_data"],
                    analysis=ss["analysis"],
                    cargo=ss["cargo"],
                    provider=provider,
                    model_id=ss["modelo"],
                    token=token,
                    tracker=tracker,
                )
            st.markdown(f"**Você:** {q}")
            st.markdown(f"**Elder Brain:** {ans}")

    st.caption(f"📁 Relatórios salvos em: `{PROCESSED_DIR}`")


if __name__ == "__main__":
    main()
