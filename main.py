import os
import json
from collections import defaultdict, deque

import httpx
from fastapi import FastAPI, Request, HTTPException, Query
from dotenv import load_dotenv
from ia import gerar_resposta

load_dotenv()

with open(os.path.join(os.path.dirname(__file__), "fluxo_aprovado.json"), "r", encoding="utf-8") as arquivo_fluxo:
    FLUXOS = json.load(arquivo_fluxo)["fluxos"]

# Estado temporário por pessoa: etapa atual e dados preenchidos.
ESTADO_USUARIAS = {}

app = FastAPI(
    title="Sistema de Atendimento Instagram",
    description="Atendimento inicial automatizado do Instagram",
    version="1.3.0"
)

VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_USER_ID = "17841466582361771"
GRAPH_API_VERSION = "v23.0"

# Histórico temporário por remetente. É perdido quando o servidor reinicia.
HISTORICO_CONVERSAS = defaultdict(lambda: deque(maxlen=12))

# Payloads enviados nos botões de resposta rápida do Instagram.
# As telas e destinos aprovados estão documentados em fluxo_aprovado.json.
OPCOES_MENU = {
    "MENU_GRUPO": "Quero conhecer o grupo Olhando para Mim.",
    "MENU_INDIVIDUAL": "Quero informações sobre o atendimento individual.",
}

TEXTO_BOAS_VINDAS = (
    "Olá! 💗 Seja bem-vinda!\n\n"
    "Sou a assistente virtual da Terapeuta Luana Soares e estou aqui para "
    "ajudar você a encontrar o atendimento que faz mais sentido para o seu momento.\n\n"
    "🫶 Você pode conhecer as opções de atendimento individual ou participar "
    "do grupo de mulheres Olhando para Mim, um espaço de acolhimento, troca e autocuidado.\n\n"
    "Como posso ajudar você hoje? 🌷"
)

# Os títulos das respostas rápidas são curtos para respeitar os limites da API do Instagram.
BOTOES_INICIAIS = [
    {"content_type": "text", "title": "💜 Individual", "payload": "MENU_INDIVIDUAL"},
    {"content_type": "text", "title": "🫶 Grupo", "payload": "MENU_GRUPO"},
]


# A API do Instagram aceita até 13 respostas rápidas, com títulos curtos.
def titulo_botao(texto):
    mapa = {
        "💜 Atendimento individual": "💜 Individual",
        "🫶 Grupo: Olhando para Mim": "🫶 Grupo",
        "🏠 Voltar ao menu principal": "Menu",
        "🏠 Voltar ao menu inicial": "Menu",
        "⬅️ Voltar ao passo anterior": "⬅️ Voltar",
        "✅ Confirmar e continuar": "✅ Confirmar",
        "✅ Confirmar meus dados": "✅ Confirmar",
        "🌷 Atendimento escolhido": "🌷 Atendimento",
        "💳 Forma de pagamento": "💳 Pagamento",
        "👤 Nome completo": "👤 Nome",
        "🎂 Data de nascimento": "🎂 Nascimento",
        "📱 WhatsApp": "📱 WhatsApp",
        "💗 Detalhes dos planos": "💗 Planos",
        "🫶 Detalhes sobre o grupo": "🫶 Detalhes do grupo",
        "✨ Condição especial": "✨ Plano anual",
        "💗 Realizar inscrição": "💗 Inscrever-se",
        "💗 Quero saber mais": "💗 Saber mais",
        "🌷 Sessão individual": "🌷 Sessão",
        "💗 Pacote mensal": "💗 Pacote mensal",
        "💗 Quero continuar": "💗 Continuar",
        "💗 Vamos começar": "💗 Começar",
        "🌸 Trimestral": "🌸 3 meses",
        "🌿 Semestral": "🌿 6 meses",
        "🌷 9 meses": "🌷 9 meses",
        "✨ Anual": "✨ Anual",
        "✏️ Corrigir informações": "✏️ Corrigir dados",
        "⬅️ Voltar ao resumo": "⬅️ Resumo",
        "💠 Pix": "💠 Pix",
        "💳 Cartão de crédito": "💳 Cartão",
        "🏠 Menu principal": "Menu",
        "⬅️ Voltar": "⬅️ Voltar",
    }
    return mapa.get(texto, texto[:20])
    return mapa.get(texto, texto[:20])


def obter_tela(chave):
    if chave == "01":
        return FLUXOS["menu_principal"]
    return FLUXOS.get(chave)


def botoes_tela(chave):
    tela = obter_tela(chave)
    if not tela:
        return []
    resultado = []
    for i, botao in enumerate(tela.get("botoes", [])[:13]):
        resultado.append({
            "content_type": "text",
            "title": titulo_botao(botao["texto"]),
            "payload": f"IR:{chave}:{i}"
        })
    return resultado


async def enviar_tela(destinatario, chave):
    tela = obter_tela(chave)
    if not tela:
        tela = FLUXOS["menu_principal"]
        chave = "01"
    ESTADO_USUARIAS.setdefault(destinatario, {"tela": "01", "dados": {}})["tela"] = chave
    await enviar_mensagem_instagram(destinatario, tela["texto"], botoes_tela(chave))


@app.get("/")
def inicio():
    return {"status": "online", "mensagem": "Sistema de atendimento Instagram funcionando!"}


@app.get("/health")
def verificar_saude():
    return {"status": "ok"}


@app.get("/webhook")
def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        if hub_challenge is not None:
            return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Token de verificação inválido.")


# Opções de navegação exibidas também após respostas livres da IA e mensagens de erro.
# Os payloads são tratados no webhook e levam a telas existentes do fluxo aprovado.
BOTOES_CONTINUAR = [
    {"content_type": "text", "title": "🫶 Grupo", "payload": "MENU_GRUPO"},
    {"content_type": "text", "title": "💜 Individual", "payload": "MENU_INDIVIDUAL"},
    {"content_type": "text", "title": "Menu", "payload": "MENU_PRINCIPAL"},
]


async def enviar_mensagem_instagram(destinatario: str, texto: str, respostas_rapidas=None):
    if not INSTAGRAM_ACCESS_TOKEN:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN não está configurado.")

    # Toda mensagem enviada pelo sistema terá opções clicáveis.
    # Telas do fluxo mantêm seus próprios botões; respostas livres usam navegação geral.
    if not respostas_rapidas:
        respostas_rapidas = BOTOES_CONTINUAR

    url = f"https://graph.instagram.com/{GRAPH_API_VERSION}/{INSTAGRAM_USER_ID}/messages"
    cabecalhos = {
        "Authorization": f"Bearer {INSTAGRAM_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    mensagem = {"text": texto[:1000]}
    if respostas_rapidas:
        mensagem["quick_replies"] = respostas_rapidas
    dados = {"recipient": {"id": destinatario}, "message": mensagem}

    async with httpx.AsyncClient(timeout=30) as cliente_http:
        resposta = await cliente_http.post(url, headers=cabecalhos, json=dados)

    if resposta.is_error:
        print("Erro ao enviar resposta ao Instagram. Status HTTP:", resposta.status_code, "Detalhe:", resposta.text[:1000])
        # Não imprimir tokens; detalhe da API é limitado para diagnóstico.
        resposta.raise_for_status()
    print("Resposta enviada ao Instagram com sucesso.")


@app.post("/webhook")
async def receber_webhook(request: Request):
    try:
        dados = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="O corpo da requisição deve conter um JSON válido.")

    if dados.get("object") != "instagram":
        return {"status": "recebido"}

    for entrada in dados.get("entry", []):
        for evento in entrada.get("messaging", []):
            mensagem = evento.get("message")
            if not mensagem or mensagem.get("is_echo"):
                continue

            remetente = evento.get("sender", {}).get("id")
            if not remetente:
                continue

            texto_recebido = (mensagem.get("text") or "").strip().lower()
            quick = mensagem.get("quick_reply") or {}
            payload = quick.get("payload", "")

            try:
                # Botões gerais usados nas respostas livres e mensagens de validação.
                if payload == "MENU_PRINCIPAL":
                    HISTORICO_CONVERSAS[remetente].clear()
                    await enviar_tela(remetente, "01")
                    continue
                if payload == "MENU_GRUPO":
                    await enviar_tela(remetente, "B")
                    continue
                if payload == "MENU_INDIVIDUAL":
                    await enviar_tela(remetente, "A1")
                    continue

                if texto_recebido in {"menu", "início", "inicio", "menu principal", "voltar ao menu", "bom dia", "boa tarde", "boa noite", "oi", "olá", "ola", "oii", "olaaa"}:
                    HISTORICO_CONVERSAS[remetente].clear()
                    await enviar_tela(remetente, "01")
                    continue

                # Clique em qualquer botão de qualquer tela documentada.
                if payload.startswith("IR:"):
                    _, tela_atual, indice_txt = payload.split(":", 2)
                    tela = obter_tela(tela_atual)
                    indice = int(indice_txt)
                    botao = tela.get("botoes", [])[indice]
                    destino = botao.get("destino", "01")
                    titulo = botao.get("texto", "")

                    # Guardar escolhas para a tela de resumo.
                    estado = ESTADO_USUARIAS.setdefault(remetente, {"tela": "01", "dados": {}})
                    dados = estado.setdefault("dados", {})
                    if tela_atual in {"A2"} and destino in {"A3.1", "A3.2"}:
                        dados["atendimento"] = "Sessão individual" if destino == "A3.1" else "Pacote mensal"
                    if tela_atual == "B8" and destino == "B9":
                        dados["plano"] = titulo
                    if tela_atual in {"A8", "B9"} and destino in {"A9", "B10"}:
                        dados["pagamento"] = titulo
                    if destino.startswith("CORRIGIR_"):
                        await enviar_tela(remetente, destino)
                        continue
                    if tela_atual in {"A5", "A6", "A7", "B5", "B6", "B7"} and destino in {"A6", "A7", "A8", "B6", "B7", "B8"}:
                        campo = {"A5":"nome", "A6":"nascimento", "A7":"whatsapp", "B5":"nome", "B6":"nascimento", "B7":"whatsapp"}[tela_atual]
                        if not dados.get(campo):
                            await enviar_mensagem_instagram(remetente, "Por favor, envie essa informação por mensagem antes de confirmar.")
                            await enviar_tela(remetente, tela_atual)
                            continue
                    await enviar_tela(remetente, destino)
                    continue

                # Nas etapas de inscrição, a mensagem digitada é registrada e o fluxo avança automaticamente.
                # Cada tela de coleta mantém apenas o botão Voltar; não é necessário confirmar separadamente.
                estado = ESTADO_USUARIAS.get(remetente)
                if estado and estado.get("tela") in {"A5", "A6", "A7", "B5", "B6", "B7"} and texto_recebido:
                    tela_atual = estado["tela"]
                    campo = {"A5":"nome", "A6":"nascimento", "A7":"whatsapp", "B5":"nome", "B6":"nascimento", "B7":"whatsapp"}[tela_atual]
                    estado.setdefault("dados", {})[campo] = mensagem.get("text", "").strip()
                    proxima_tela = {"A5":"A6", "A6":"A7", "A7":"A8", "B5":"B6", "B6":"B7", "B7":"B8"}[tela_atual]
                    await enviar_tela(remetente, proxima_tela)
                    continue

                # Primeira mensagem abre o menu; as demais mensagens fora de botões recebem resposta da IA.
                if not HISTORICO_CONVERSAS[remetente]:
                    await enviar_tela(remetente, "01")
                    HISTORICO_CONVERSAS[remetente].append({"papel": "assistente", "texto": TEXTO_BOAS_VINDAS})
                    continue

                historico = list(HISTORICO_CONVERSAS[remetente])
                resposta_ia = gerar_resposta(mensagem.get("text", "").strip(), historico=historico)
                if resposta_ia:
                    await enviar_mensagem_instagram(destinatario=remetente, texto=resposta_ia)
                    HISTORICO_CONVERSAS[remetente].append({"papel": "mulher", "texto": mensagem.get("text", "").strip()})
                    HISTORICO_CONVERSAS[remetente].append({"papel": "assistente", "texto": resposta_ia})
            except Exception as erro:
                print("Erro no atendimento automático:", type(erro).__name__, str(erro)[:500])

        for alteracao in entrada.get("changes", []):
            if alteracao.get("field") == "messages":
                print("Evento de mensagem recebido no formato changes.")

    return {"status": "recebido"}
