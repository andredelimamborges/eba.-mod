from __future__ import annotations

import json
import re
import smtplib
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from eba_config import (
    MAX_TOKENS_FIXED,
    TEMP_FIXED,
    GPT_PRICE_INPUT_PER_1K,
    GPT_PRICE_OUTPUT_PER_1K,
)

# libs opcionais
try:
    import tiktoken
except Exception:
    tiktoken = None  # type: ignore

try:
    from groq import Groq
except Exception:
    Groq = None  # type: ignore

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore


# =============================================================================
# token accounting (mantido, mas agora compatível com UsageTracker do app)
# =============================================================================
@dataclass
class TokenStep:
    prompt: int = 0
    completion: int = 0

    @property
    def total(self) -> int:
        return self.prompt + self.completion


@dataclass
class TokenTracker:
    steps: Dict[str, TokenStep] = field(
        default_factory=lambda: {
            "extracao": TokenStep(),
            "analise": TokenStep(),
            "chat": TokenStep(),
            "pdf": TokenStep(),
        }
    )
    model: str = ""
    provider: str = ""

    def add(self, step: str, prompt_tokens: int, completion_tokens: int) -> None:
        if step not in self.steps:
            self.steps[step] = TokenStep()
        self.steps[step].prompt += int(prompt_tokens or 0)
        self.steps[step].completion += int(completion_tokens or 0)

    def dict(self) -> Dict[str, Dict[str, int]]:
        return {
            k: {"prompt": v.prompt, "completion": v.completion, "total": v.total}
            for k, v in self.steps.items()
        }

    @property
    def total_prompt(self) -> int:
        return sum(s.prompt for s in self.steps.values())

    @property
    def total_completion(self) -> int:
        return sum(s.completion for s in self.steps.values())

    @property
    def total_tokens(self) -> int:
        return self.total_prompt + self.total_completion

    def cost_usd_gpt(self) -> float:
        return (self.total_prompt / 1000.0) * GPT_PRICE_INPUT_PER_1K + (
            self.total_completion / 1000.0
        ) * GPT_PRICE_OUTPUT_PER_1K


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        if tiktoken:
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
    except Exception:
        pass
    # fallback heurístico
    return max(1, int(len(text) / 4))


def _tracker_add_step_compatible(
    tracker: Any,
    step: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """
    compatibilidade com:
      - TokenTracker (add)
      - UsageTracker (geralmente add_step)
    sem quebrar prod se tracker não tiver nada disso.
    """
    if tracker is None:
        return

    # 1) padrão “novo” (UsageTracker)
    if hasattr(tracker, "add_step") and callable(getattr(tracker, "add_step")):
        try:
            tracker.add_step(step, prompt_tokens, completion_tokens)
            return
        except Exception:
            pass

    # 2) padrão “antigo” (TokenTracker)
    if hasattr(tracker, "add") and callable(getattr(tracker, "add")):
        try:
            tracker.add(step, prompt_tokens, completion_tokens)
            return
        except Exception:
            pass

    # 3) se nada funcionar, não quebra


def _estimate_and_add(
    tracker: Any,
    step: str,
    messages: List[Dict[str, str]],
    completion_text: str,
    usage: Optional[Dict[str, Any]],
) -> None:
    """
    tenta usar usage real da api; se não existir, estima.
    """
    prompt_tokens = 0
    completion_tokens = 0

    if usage:
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)

    if prompt_tokens <= 0:
        prompt_text = "\n".join([m.get("content", "") for m in messages])
        prompt_tokens = _estimate_tokens(prompt_text)

    if completion_tokens <= 0:
        completion_tokens = _estimate_tokens(completion_text or "")

    _tracker_add_step_compatible(tracker, step, prompt_tokens, completion_tokens)


# =============================================================================
# client / keys
# =============================================================================
@st.cache_resource(show_spinner=False)
def get_llm_client_cached(provider: str, api_key: str):
    """cria cliente LLM (Groq/OpenAI) usando o SDK."""
    if not api_key:
        raise RuntimeError("chave da api não configurada. defina nos secrets do streamlit.")
    pv = (provider or "groq").lower()

    if pv == "groq":
        if Groq is None:
            raise RuntimeError("sdk groq não instalado.")
        return Groq(api_key=api_key)

    if pv == "openai":
        if OpenAI is None:
            raise RuntimeError("sdk openai não instalado.")
        return OpenAI(api_key=api_key)

    raise RuntimeError(f"provedor não suportado: {provider}")


def get_api_key_for_provider(provider: str) -> str:
    provider = (provider or "groq").lower()
    if provider == "groq":
        key = st.secrets.get("GROQ_API_KEY", "")
        if not key:
            raise RuntimeError("GROQ_API_KEY não configurada nos secrets do streamlit.")
        return key
    if provider == "openai":
        key = st.secrets.get("OPENAI_API_KEY", "")
        if not key:
            raise RuntimeError("OPENAI_API_KEY não configurada nos secrets do streamlit.")
        return key
    raise RuntimeError(f"provedor não suportado: {provider}")


def _get_provider_and_model() -> Tuple[str, str]:
    """
    resolve provider/model sem quebrar por var inexistente em eba_config.
    prioridade:
      1) st.secrets (LLM_PROVIDER / LLM_MODEL_ID)
      2) eba_config (LLM_PROVIDER/LLM_MODEL_ID ou DEFAULT_PROVIDER/DEFAULT_MODEL_ID)
      3) fallback seguro
    """
    # 1) secrets
    provider = (st.secrets.get("LLM_PROVIDER", "") or "").strip()
    model_id = (st.secrets.get("LLM_MODEL_ID", "") or "").strip()

    if provider and model_id:
        return provider, model_id

    # 2) config (sem crash)
    try:
        import eba_config as cfg  # type: ignore

        provider = provider or getattr(cfg, "LLM_PROVIDER", "") or getattr(cfg, "DEFAULT_PROVIDER", "")
        model_id = model_id or getattr(cfg, "LLM_MODEL_ID", "") or getattr(cfg, "DEFAULT_MODEL_ID", "")
    except Exception:
        pass

    # 3) fallback final
    provider = (provider or "groq").strip()
    model_id = (model_id or "llama-3.1-8b-instant").strip()
    return provider, model_id


# =============================================================================
# email admin (mantido)
# =============================================================================
def send_admin_report_if_configured(tracker: TokenTracker, provider: str, model: str) -> None:
    """
    envia por email o “relatório admin” (tokens, custo, modelo, provider),
    apenas se secrets de email existirem.
    """
    try:
        host = st.secrets.get("EMAIL_HOST", "")
        user = st.secrets.get("EMAIL_USER", "")
        pwd = st.secrets.get("EMAIL_PASS", "")
        to = st.secrets.get("EMAIL_TO", "")
        finance_to = st.secrets.get("EBA_FINANCE_TO", "")
        port = int(st.secrets.get("EMAIL_PORT", 587))

        if not (host and user and pwd and to):
            return

        td = tracker.dict()
        total_tokens = tracker.total_tokens
        cost = tracker.cost_usd_gpt()

        linhas = [
            "Elder Brain Analytics — Uso de Relatório",
            f"Data/Hora: {datetime.now():%d/%m/%Y %H:%M}",
            "",
            f"Provider: {provider}",
            f"Modelo:   {model}",
            "",
            "Uso de tokens por etapa:",
        ]
        for step, vals in td.items():
            linhas.append(
                f"- {step}: total={vals['total']} (prompt={vals['prompt']} / completion={vals['completion']})"
            )
        linhas.append("")
        linhas.append(f"Total de tokens: {total_tokens}")
        linhas.append(f"Custo estimado (tabela GPT): ${cost:.4f}")

        body = "\n".join(linhas)

        msg = EmailMessage()
        msg["Subject"] = "[EBA] Relatório processado (uso de tokens)"
        msg["From"] = user

        destinatarios = [to]
        if finance_to:
            destinatarios.append(finance_to)

        msg["To"] = ", ".join(destinatarios)
        msg.set_content(body)

        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, pwd)
            server.send_message(msg)

    except Exception as e:
        st.warning(f"falha ao enviar email de log admin: {e}")


# =============================================================================
# prompts
# =============================================================================
EXTRACTION_PROMPT = """Você é um especialista em análise de relatórios BFA (Big Five Analysis) para seleção de talentos.
Sua tarefa: extrair dados do relatório abaixo e retornar APENAS um JSON válido, sem texto adicional.

ESTRUTURA OBRIGATÓRIA:
{
  "candidato": {
    "nome": "string ou null",
    "cargo_avaliado": "string ou null",
    "empresa": "string ou null"
  },
  "traits_bfa": {
    "Abertura": número 0-10 ou null,
    "Conscienciosidade": número 0-10 ou null,
    "Extroversao": número 0-10 ou null,
    "Amabilidade": número 0-10 ou null,
    "Neuroticismo": número 0-10 ou null
  },
  "competencias_ms": [
    {
      "nome": "string",
      "nota": número,
      "classificacao": "string"
    }
  ],
  "facetas_relevantes": [
    {
      "nome": "string",
      "percentil": número,
      "interpretacao": "string resumida"
    }
  ],
  "indicadores_saude_emocional": {
    "ansiedade": número 0-100 ou null,
    "irritabilidade": número 0-100 ou null,
    "estado_animo": número 0-100 ou null,
    "impulsividade": número 0-100 ou null
  },
  "potencial_lideranca": "BAIXO" | "MÉDIO" | "ALTO" ou null,
  "integridade_fgi": número 0-100 ou null,
  "resumo_qualitativo": "texto do resumo presente no relatório",
  "pontos_fortes": ["string"],
  "pontos_atencao": ["string"],
  "fit_geral_cargo": número 0-100
}

REGRAS DE EXTRAÇÃO:
1. normalize percentis/notas para escalas apropriadas
2. big five: percentil 60 -> ~6.0/10
3. extraia todas as competências ms que aparecerem
4. use null quando não houver informação confiável
5. resumo_qualitativo deve ser o texto original do relatório
6. pontos_fortes: retorne APENAS os 2 ou 3 pontos mais relevantes para o cargo, em frases curtas
7. pontos_atencao: retorne APENAS os 1 ou 2 pontos mais críticos para o cargo, em frases curtas
8. evite descrições genéricas; priorize impacto no cargo
9. fit_geral_cargo: calcule compatibilidade 0-100 baseado no cargo: {cargo}

RELATÓRIO:
\"\"\"
{text}
\"\"\"

CONTEXTO ADICIONAL:
\"\"\"
{training_context}
\"\"\"

retorne apenas o json, sem markdown, sem explicações.
"""

ANALYSIS_PROMPT = """Você é um consultor sênior de RH especializado em análise comportamental e fit cultural.

Baseado nos dados extraídos do BFA, faça uma análise profissional para o cargo: {cargo}

DADOS DO CANDIDATO:
{json_data}

PERFIL IDEAL DO CARGO:
{perfil_cargo}

Retorne APENAS um JSON válido seguindo este formato:

{
  "compatibilidade_geral": número 0-100,
  "decisao": "RECOMENDADO" | "RECOMENDADO COM RESSALVAS" | "NÃO RECOMENDADO",
  "justificativa_decisao": "parágrafo explicativo",
  "analise_tracos": {
    "Abertura": "análise específica",
    "Conscienciosidade": "análise específica",
    "Extroversao": "análise específica",
    "Amabilidade": "análise específica",
    "Neuroticismo": "análise específica"
  },
  "competencias_criticas": [
    {
      "competencia": "nome",
      "avaliacao": "texto",
      "status": "ATENDE" | "PARCIAL" | "NÃO ATENDE"
    }
  ],
  "saude_emocional_contexto": "parágrafo",
  "recomendacoes_desenvolvimento": [
    {
      "titulo": "string",
      "descricao": "explicação objetiva conectada ao perfil",
      "impacto_esperado": "impacto direto no desempenho do cargo"
    }
  ],
  "cargos_alternativos": [
    {
      "cargo": "nome",
      "aderencia_estimada": "ALTA | MÉDIA | BAIXA",
      "justificativa": "por que este cargo se encaixa melhor no perfil"
    }
  ]
}

REGRAS IMPORTANTES:
- priorize impacto no cargo avaliado
- limite a 2–3 recomendações de desenvolvimento
- limite a 1–3 cargos alternativos
- evite descrições longas ou genéricas
- cada item deve caber em UMA frase curta
- não repita informações já citadas em outras seções
- seja objetivo, profissional e orientado à decisão

responda estritamente em json. sem texto fora do json. sem markdown.
"""

# =============================================================================
# core LLM call
# =============================================================================
_JSON_RE = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", re.DOTALL)


def _extract_first_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _looks_like_rate_limit(err: Exception) -> bool:
    s = str(err).lower()
    return ("rate limit" in s) or ("429" in s) or ("too many requests" in s) or ("rate_limit" in s)


def _chat_completion_json(
    provider: str,
    client: Any,
    model_id: str,
    messages: List[Dict[str, str]],
    force_json: bool,
    max_retries: int = 3,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    retorna (content, usage_dict)
    - em groq/openai o sdk costuma expor resp.usage com prompt_tokens/completion_tokens
    """
    last_err: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            pv = (provider or "groq").lower()

            if pv == "groq":
                # groq suporta response_format={"type":"json_object"} em muitos modelos
                kwargs = {
                    "model": model_id,
                    "messages": messages,
                    "max_tokens": int(MAX_TOKENS_FIXED),
                    "temperature": float(TEMP_FIXED),
                }
                if force_json:
                    kwargs["response_format"] = {"type": "json_object"}

                resp = client.chat.completions.create(**kwargs)
                content = (resp.choices[0].message.content or "").strip()
                usage = None
                if getattr(resp, "usage", None):
                    usage = {
                        "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(resp.usage, "completion_tokens", 0),
                    }
                return content, usage

            if pv == "openai":
                kwargs = {
                    "model": model_id,
                    "messages": messages,
                    "max_tokens": int(MAX_TOKENS_FIXED),
                    "temperature": float(TEMP_FIXED),
                }
                if force_json:
                    # openai: response_format pode variar conforme sdk/modelo; mantemos simples
                    pass

                resp = client.chat.completions.create(**kwargs)
                content = (resp.choices[0].message.content or "").strip()
                usage = None
                if getattr(resp, "usage", None):
                    usage = {
                        "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(resp.usage, "completion_tokens", 0),
                    }
                return content, usage

            raise RuntimeError(f"provedor não suportado: {provider}")

        except Exception as e:
            last_err = e
            if _looks_like_rate_limit(e) and attempt < max_retries:
                # backoff curto
                sleep_s = min(8.0, 1.2 * (2 ** (attempt - 1)))
                time.sleep(sleep_s)
                continue
            break

    raise RuntimeError(f"falha na chamada llm: {last_err}")


# =============================================================================
# business functions
# =============================================================================
def extract_bfa_data(
    text: str,
    cargo: str,
    training_context: str,
    provider: str,
    model_id: str,
    token: str,
    tracker: Any,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """etapa 1: extração estruturada."""
    client = get_llm_client_cached(provider, token)

    # limites conservadores (prod)
    text_limit = 12000
    training_limit = 3000

    prompt = (
        EXTRACTION_PROMPT.replace("{cargo}", cargo)
        .replace("{text}", (text or "")[:text_limit])
        .replace("{training_context}", (training_context or "")[:training_limit])
    )

    messages = [
        {"role": "system", "content": "responda estritamente em json."},
        {"role": "user", "content": prompt},
    ]

    content, usage = _chat_completion_json(provider, client, model_id.strip(), messages, True)
    _estimate_and_add(tracker, "extracao", messages, content, usage)

    parsed = _extract_first_json(content)
    if parsed is not None:
        return parsed, content

    # tentativa de “repair”
    fix_msgs = [
        {"role": "system", "content": "retorne apenas o json válido."},
        {"role": "user", "content": f"converta para json válido:\n{content}"},
    ]
    fix, usage2 = _chat_completion_json(provider, client, model_id.strip(), fix_msgs, True)
    _estimate_and_add(tracker, "extracao", fix_msgs, fix, usage2)

    parsed2 = _extract_first_json(fix)
    if parsed2 is not None:
        return parsed2, fix

    return None, f"nenhum json válido encontrado: {content[:800]}..."


def analyze_bfa_data(
    bfa_data: Dict[str, Any],
    cargo: str,
    perfil_cargo: Dict[str, Any],
    provider: str,
    model_id: str,
    token: str,
    tracker: Any,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """etapa 2: análise de compatibilidade/fit."""
    client = get_llm_client_cached(provider, token)

    prompt = (
        ANALYSIS_PROMPT.replace("{cargo}", cargo)
        .replace("{json_data}", json.dumps(bfa_data, ensure_ascii=False, indent=2))
        .replace("{perfil_cargo}", json.dumps(perfil_cargo, ensure_ascii=False, indent=2))
    )

    messages = [
        {"role": "system", "content": "responda estritamente em json."},
        {"role": "user", "content": prompt},
    ]

    content, usage = _chat_completion_json(provider, client, model_id.strip(), messages, True)
    _estimate_and_add(tracker, "analise", messages, content, usage)

    parsed = _extract_first_json(content)
    if parsed is not None:
        return parsed, content

    fix_msgs = [
        {"role": "system", "content": "retorne apenas o json válido."},
        {"role": "user", "content": f"converta para json válido:\n{content}"},
    ]
    fix, usage2 = _chat_completion_json(provider, client, model_id.strip(), fix_msgs, True)
    _estimate_and_add(tracker, "analise", fix_msgs, fix, usage2)

    parsed2 = _extract_first_json(fix)
    if parsed2 is not None:
        return parsed2, fix

    return None, f"nenhum json válido encontrado: {content[:800]}..."


def chat_with_elder_brain(
    question: str,
    bfa_data: Dict[str, Any],
    analysis: Dict[str, Any],
    cargo: str,
    provider: str,
    model_id: str,
    token: str,
    tracker: Any,
) -> str:
    """chat contextualizado (mantido para evolução futura)."""
    client = get_llm_client_cached(provider, token)

    contexto = f"""
você é um consultor executivo de rh analisando um relatório bfa.

dados (json): {json.dumps(bfa_data, ensure_ascii=False)}
análise (json): {json.dumps(analysis, ensure_ascii=False)}
cargo: {cargo}

pergunta: {question}
responda de forma objetiva e profissional.
""".strip()

    messages = [{"role": "user", "content": contexto}]
    content, usage = _chat_completion_json(provider, client, model_id.strip(), messages, False)
    _estimate_and_add(tracker, "chat", messages, content, usage)
    return content


# =============================================================================
# wrappers usados pelo app.py
# =============================================================================
def run_extracao(text: str, cargo: str, tracker: Any):
    provider, model_id = _get_provider_and_model()
    api_key = get_api_key_for_provider(provider)

    bfa_data, raw = extract_bfa_data(
        text=text,
        cargo=cargo,
        training_context="",
        provider=provider,
        model_id=model_id,
        token=api_key,
        tracker=tracker,
    )

    if bfa_data is None:
        raise RuntimeError(raw or "falha na extração.")
    return bfa_data


def run_analise(bfa_data: dict, cargo: str, tracker: Any):
    provider, model_id = _get_provider_and_model()
    api_key = get_api_key_for_provider(provider)

    # perfil do cargo (se existir no config)
    try:
        from eba_config import gerar_perfil_cargo_dinamico  # type: ignore

        perfil_cargo = gerar_perfil_cargo_dinamico(cargo)
    except Exception:
        perfil_cargo = {}

    analysis, raw = analyze_bfa_data(
        bfa_data=bfa_data,
        cargo=cargo,
        perfil_cargo=perfil_cargo,
        provider=provider,
        model_id=model_id,
        token=api_key,
        tracker=tracker,
    )

    if analysis is None:
        raise RuntimeError(raw or "falha na análise.")
    return analysis
