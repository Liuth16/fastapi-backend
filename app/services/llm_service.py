import json
import logging
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from google import genai
from google.genai import errors as genai_errors
from app.config import settings  # centralized config
from app.models import Effect, CombatStateModel, EnemyDefeatedReward, LLMEffect


# Initialize Gemini client using settings
_client = genai.Client(api_key=settings.gemini_api_key)
_MODEL = "gemini-2.5-flash-lite"


# =======================
# MODELS
# =======================

class LLMActionOutcome(BaseModel):
    narrative: str
    enemy_health_change: int = 0
    character_health_change: int = 0
    status_effects: List[str] = Field(default_factory=list)


class IntroInit(BaseModel):
    narrative: str


class LLMFreeOutcome(BaseModel):
    narrative: str
    effects: List[LLMEffect] = Field(default_factory=list)
    enemy_health: Optional[int] = None  # null/None if no enemy
    combat_state: Optional[CombatStateModel] = None  # {} -> None in schema
    enemy_defeated_reward: EnemyDefeatedReward = Field(
        default_factory=lambda: EnemyDefeatedReward(
            gainedExperience=None, loot=[]),
        alias="enemyDefeatedReward"
    )

    # Combat state flag
    active_combat: Optional[bool] = Field(default=False)

    # Suggestions
    suggested_actions: List[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True


class EnemyInit(BaseModel):
    enemy_name: str
    enemy_description: str
    enemy_health: int


# =======================
# PROMPTS
# =======================

ACTION_PROMPT = """You are the game narrator for a text-based RPG.

Player action: "{action}"
Outcome decided by game engine: {outcome}  # do NOT override this outcome

Game state:
- Character: {character_name}
- Enemy: {enemy_name} (health: {enemy_health})
- Enemy description: {enemy_description}
- Level: {level_number}

Previous turns (most recent first):
{previous}

Instructions:
- Write a short, vivid narrative (1–3 sentences) describing the outcome consistent with {outcome}.
- Do not mention dice rolls, random numbers, or the word "success"/"failure".
- Update health deltas accordingly (negative = damage taken, positive = healing).
- Return only JSON that matches the provided schema.
"""

_INTRO_PROMPT = """You are the narrator.
Context:
Campaign description: {campaign_description}
Enemy: {enemy_name} - {enemy_description}

Write an engaging introductory narrative (2–3 sentences).
Output JSON with field "narrative".
"""

FREE_PROMPT_TEMPLATE = """Você é o narrador do jogo para um RPG baseado em texto livre.

Ação do jogador: "{action}"

Estado do jogo:
- Personagem: {character_name}

Estado de combate (sempre fornecido — ignore a menos que ocorra hostilidade):
{combat_state}

Contexto:
O contexto abaixo contém DUAS partes:
1. **Turnos Recentes** (os últimos 5 turnos, sempre diretamente relevantes para a ação atual).
2. **Contexto Passado Relevante** (turnos mais antigos recuperados da memória; estes podem ou não ser relevantes).

Você deve:
- Sempre priorizar **Turnos Recentes** ao determinar a continuidade e o que acontece a seguir.
- Usar **Contexto Passado Relevante** SOMENTE se realmente ajudar a manter a narrativa ou consistência do mundo (ignore se irrelevante).

{previous} 

### Manipulação de Diálogo
1.  **Identificar Diálogo vs. Ação:** Sua primeira tarefa é determinar se a entrada do jogador é fala ou uma ação física. Entradas entre aspas ("...") ou formuladas como pergunta/afirmação a um NPC são diálogos.
2.  **Manter o Fluxo da Conversa:** Se o turno mais recente envolveu um NPC falando com o jogador, você DEVE assumir que a entrada do jogador é uma resposta a esse NPC, a menos que ele declare explicitamente uma nova ação física (ex.: "Eu vou embora", "Eu ataco o espadachim").
3.  **Garantir que os NPCs Respondam:** Quando o jogador fala com um NPC, a narrativa que você gerar *deve* conter a resposta falada desse NPC. Não narre o personagem do jogador realizando uma nova ação não relacionada que encerre a conversa.
4.  **Atribuir Toda a Fala:** Todo diálogo em sua narrativa deve ser claramente atribuído a um falante. Por exemplo: 'O espadachim debocha: "Você acha que é tão fácil assim?"' ou 'Um guarda próximo ouve você e diz: "..."'. Nunca forneça falas sem atribuição ou desincorporadas.

### Manipulação de Combate
1. **Ordem do fluxo de combate** (sempre siga estes passos nesta ordem):
   - Detectar uma agressão física ou ação hostil.
   - Escolher o atributo relevante para a ação agressiva (deve ser o mesmo atributo para ambos os lados).
   - Verificar as rolagens para determinar o resultado:
     - Exemplo: player_total = player.roll + player.dexterity
     - Exemplo: enemy_total = enemy.roll + enemy.strength
   - Gerar o efeito baseado em quem venceu a comparação de rolagem.
   - Gerar a narrativa de forma coerente com o resultado (se o player possuir um roll total maior a narrativa deve ser um ataque bem sucedido, se o inimigo possuir um roll maior a narrativa deve ser um ataque falhado ou um contra ataque bem sucedido do inimigo) e o histórico.
     *Você tem liberdade criativa aqui, especialmente com ataques mágicos: falhas podem falhar por completo, serem desviadas ou contra-atacadas pela magia inimiga; sucessos podem se manifestar de formas variadas e criativas. A mesma lógica vale para ataques físicos.*

2. Se **não houver combate neste turno**: defina "combat_state": {{}} e "active_combat": false.

3. Se **o combate ocorrer ou continuar**:
   - Use o combat_state fornecido como base.
   - **Sempre recalcule as rolagens a cada turno.** Os valores de "roll" dentro do combat_state são gerados novamente a cada turno pelo backend, e devem ser usados de forma nova a cada turno.
   - **Recalcule player_total e enemy_total a cada turno** com as novas rolagens e o atributo escolhido. Nunca reutilize totais de turnos anteriores.
   - Compare os totais:
     - O lado com o maior total (player_total vs enemy_total) vence.
     - O lado com o menor total sofre a consequência.
     - Empates podem ser narrados como impasses (sem efeito ou ambos com pequenos arranhões).
   - Atualize "combat_state" com o atributo escolhido e os *novos totais calculados* para este turno.
   - NÃO invente valores de dano; apenas retorne o tipo de efeito ("damage" ou "heal").

4. Efeitos devem usar SOMENTE este formato:
   - {{ "type": "damage" | "heal" }}
   - NÃO inclua "target" ou "value". O backend calculará isso.
   - Não altere valores numéricos de vida em combat_state. Apenas narre os efeitos e forneça objetos de efeito. O backend irá calcular e atualizar a vida.

### Diretrizes de Narrativa
5a. **Narrativas de Combate**
   - Mantenha curtas, diretas e focadas na ação (1–3 frases).
   - Descreva claramente o resultado do confronto (ataque acerta, erra, bloqueio, ferimento, etc.).
   - Enfatize tensão, velocidade e consequências, em vez de cenários ou construção de mundo.
   - Seja especialmente criativo com desfechos mágicos: feitiços falhos podem se dissipar, sair pela culatra ou ser desviados pelos poderes do oponente; feitiços bem-sucedidos podem explodir em efeitos únicos e vívidos.

5b. **Narrativas Fora de Combate**
   - Seja mais detalhado, rico e imersivo (3–6 frases).
   - Foque em construção de mundo, diálogo, exploração, atmosfera e interações sociais.
   - Incentive a curiosidade, interpretação e interação com o ambiente ou NPCs.
   - Estimule oportunidades de diálogo e novos caminhos que o jogador possa explorar.

### Sugestões de Ação
No final de sua resposta, SEMPRE forneça um campo "suggested_actions".
"""


_ENEMY_PROMPT = """You are the dungeon master.
Campaign context:
Name: {campaign_name}
Description: {campaign_description}

Generate the first enemy (name, description, and health 20–50).
Output JSON strictly matching the schema.
"""

_PLAYER_KO_PROMPT = """Você é o narrador de um RPG livre em texto.

O jogador chegou a 0 de vida e foi nocauteado.

Contexto:
O contexto abaixo contém DUAS partes:
1. **Turnos Recentes** (os últimos 5 turnos, sempre diretamente relevantes para a ação atual).
2. **Contexto Passado Relevante** (turnos mais antigos recuperados da memória; estes podem ou não ser relevantes).

Instruções:
- Sempre priorize os **Turnos Recentes** para garantir a continuidade.
- Use o **Contexto Passado Relevante** apenas se ajudar claramente a manter a narrativa ou consistência do mundo.
- NÃO mate o jogador.
- Narre como o jogador sobrevive por meio de intervenção externa (resgate, inconsciência, alguém o encontra ou sendo poupado).
- Mantenha a narrativa imersiva e consistente com o tom da história até aqui.
- Sua narração deve parecer a continuação natural da história.
- O backend cuidará do estado de combate e do reset da vida, então você só precisa fornecer a narrativa e as sugestões.

{previous_turns}
"""


_ENEMY_KO_PROMPT = """Você é o narrador de um RPG livre em texto.

O inimigo chegou a 0 de vida e foi derrotado.

Contexto:
O contexto abaixo contém DUAS partes:
1. **Turnos Recentes** (os últimos 5 turnos, sempre diretamente relevantes para a ação atual).
2. **Contexto Passado Relevante** (turnos mais antigos recuperados da memória; estes podem ou não ser relevantes).

Instruções:
- Sempre priorize os **Turnos Recentes** para garantir a continuidade.
- Use o **Contexto Passado Relevante** apenas se ajudar claramente a manter a narrativa ou consistência do mundo.
- Narre a queda ou derrota do inimigo de forma vívida e dramática, lembre-se que a vida chegou a 0 então deve ser narrado o nocaute do inimigo.
- Certifique-se de que a descrição corresponda ao tom e aos eventos dos turnos anteriores.
- Forneça uma recompensa significativa em "enemy_defeated_reward" (saque, XP ou ambos) que faça sentido com o contexto.
- O backend cuidará do estado de combate e das atualizações de vida, então você só precisa fornecer a narrativa, as recompensas e as sugestões.

{previous_turns}
"""

# =======================
# HELPERS
# =======================


def _format_previous(previous_turns: List[str]) -> str:
    if not previous_turns:
        return "- (no prior turns)"
    return "\n".join(f"- {p}" for p in previous_turns)


# =======================
# FUNCTIONS
# =======================

async def generate_narrative_with_schema(
    *,
    action: str,
    outcome_success: bool,
    character_name: str,
    enemy_name: str,
    enemy_description: str,
    enemy_health: int,
    level_number: int,
    previous_turns: List[str],
) -> LLMActionOutcome:
    outcome = "SUCCESS" if outcome_success else "FAILURE"

    contents = ACTION_PROMPT.format(
        action=action,
        outcome=outcome,
        character_name=character_name,
        enemy_name=enemy_name,
        enemy_description=enemy_description,
        enemy_health=enemy_health,
        level_number=level_number,
        previous=_format_previous(previous_turns),
    )

    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_schema": LLMActionOutcome,
            },
        )
        return resp.parsed if getattr(resp, "parsed", None) else LLMActionOutcome(
            narrative="You act, but the outcome is unclear.",
        )
    except genai_errors.ServerError as e:
        logging.error(f"Gemini server error: {e}")
        return LLMActionOutcome(
            narrative="The battle is chaotic, and the outcome is unclear.",
        )
    except Exception as e:
        logging.error(f"Unexpected LLM error: {e}")
        return LLMActionOutcome(
            narrative="You act, but nothing seems to happen.",
        )


async def generate_intro_narrative(campaign_description: str, enemy_name: str, enemy_description: str) -> IntroInit:
    contents = _INTRO_PROMPT.format(
        campaign_description=campaign_description,
        enemy_name=enemy_name,
        enemy_description=enemy_description,
    )
    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={"response_mime_type": "application/json",
                    "response_schema": IntroInit},
        )
        return resp.parsed if getattr(resp, "parsed", None) else IntroInit(
            narrative="Your adventure begins as you face your first foe."
        )
    except Exception as e:
        logging.error(f"Intro generation error: {e}")
        return IntroInit(narrative="Your journey begins in a mysterious land.")


async def generate_free_intro(campaign_description: str, character_name: str) -> IntroInit:
    """Generates the intro narrative for free mode (Turn 1)."""
    contents = f"""Você é o narrador.
    Contexto:
    Descrição da campanha: {campaign_description}
    Personagem: {character_name}

    Escreva uma narrativa introdutória envolvente (2–3 frases).
    A narrativa deve ambientar a cena, apresentar o personagem e sugerir possíveis aventuras futuras.
    Mantenha a narrativa introdutória no mesmo idioma da descrição da campanha.
    Retorne em JSON com o campo "narrative".
    """
    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={"response_mime_type": "application/json",
                    "response_schema": IntroInit},
        )
        return resp.parsed if getattr(resp, "parsed", None) else IntroInit(
            narrative="A new adventure begins, full of possibilities."
        )
    except Exception as e:
        logging.error(f"Free intro generation error: {e}")
        return IntroInit(narrative="The story begins, waiting for your choices.")


async def generate_free_narrative(
    *,
    action: str,
    character_name: str,
    combat_state: dict,
    previous_turns: List[str],
) -> LLMFreeOutcome:
    contents = FREE_PROMPT_TEMPLATE.format(
        action=action,
        character_name=character_name,
        combat_state=json.dumps(combat_state, indent=2, ensure_ascii=False),
        previous=_format_previous(previous_turns),
    )

    print(contents)

    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_schema": LLMFreeOutcome,
            },
        )

        if getattr(resp, "parsed", None):
            out: LLMFreeOutcome = resp.parsed
        else:
            out = LLMFreeOutcome(**json.loads(resp.text))

        # ✅ Normalize reward
        if out.enemy_defeated_reward is None:
            out.enemy_defeated_reward = EnemyDefeatedReward(
                gainedExperience=None, loot=[])

        # ✅ Force active_combat to a real bool, even if missing/None
        out.active_combat = bool(
            out.active_combat) if out.active_combat is not None else False

        # ✅ Ensure combat_state and enemy_health consistency
        if not out.active_combat:
            out.combat_state = None
            out.enemy_health = None

        # ✅ Ensure effects omit "value" (if your Effect model still has it floating around)
        for e in out.effects:
            if hasattr(e, "value"):
                e.value = None

        # ✅ Ensure suggestions list
        if out.suggested_actions is None:
            out.suggested_actions = []

        return out

    except Exception as e:
        logging.error(f"Error in generate_free_narrative: {e}")
        return LLMFreeOutcome(
            narrative="You act, but nothing conclusive happens.",
            effects=[],
            combat_state=None,
            active_combat=False,
            enemy_health=None,
            enemy_defeated_reward=EnemyDefeatedReward(
                gainedExperience=None, loot=[]
            ),
            suggested_actions=[],
        )


async def generate_enemy_for_level(campaign_name: str, campaign_description: str) -> EnemyInit:
    contents = _ENEMY_PROMPT.format(
        campaign_name=campaign_name,
        campaign_description=campaign_description,
    )
    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={"response_mime_type": "application/json",
                    "response_schema": EnemyInit},
        )
        return resp.parsed if getattr(resp, "parsed", None) else EnemyInit(
            enemy_name="Goblin",
            enemy_description="A nasty little goblin snarls at you.",
            enemy_health=30,
        )
    except Exception as e:
        logging.error(f"Enemy generation error: {e}")
        return EnemyInit(
            enemy_name="Orc",
            enemy_description="A brutish orc stares you down.",
            enemy_health=40,
        )


async def player_knocked_out(previous_turns: list[str]) -> LLMFreeOutcome:
    """Generate narrative when the player is reduced to 0 HP."""
    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=_PLAYER_KO_PROMPT.format(
                previous_turns="\n".join(previous_turns)),
            config={
                "response_mime_type": "application/json",
                "response_schema": LLMFreeOutcome,
            },
        )

        if getattr(resp, "parsed", None):
            out: LLMFreeOutcome = resp.parsed
        else:
            out = LLMFreeOutcome(**json.loads(resp.text))

        # Always enforce defaults
        out.active_combat = False
        out.combat_state = None
        out.enemy_health = None

        if out.enemy_defeated_reward is None:
            out.enemy_defeated_reward = EnemyDefeatedReward(
                gainedExperience=None, loot=[]
            )

        return out

    except Exception as e:
        logging.error(f"Error in player_knocked_out: {e}")
        return LLMFreeOutcome(
            narrative="You collapse into darkness, but fate spares your life. Someone finds you before it is too late.",
            effects=[],
            combat_state=None,
            active_combat=False,
            enemy_health=None,
            enemy_defeated_reward=EnemyDefeatedReward(
                gainedExperience=None, loot=[]
            ),
            suggested_actions=["Recover your strength", "Plan your next step"],
        )


async def enemy_knocked_out(previous_turns: list[str]) -> LLMFreeOutcome:
    """Generate narrative when the enemy is reduced to 0 HP."""
    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=_ENEMY_KO_PROMPT.format(
                previous_turns="\n".join(previous_turns)),
            config={
                "response_mime_type": "application/json",
                "response_schema": LLMFreeOutcome,
            },
        )

        if getattr(resp, "parsed", None):
            out: LLMFreeOutcome = resp.parsed
        else:
            out = LLMFreeOutcome(**json.loads(resp.text))

        # Always enforce defaults
        out.active_combat = False
        out.combat_state = None

        if out.enemy_defeated_reward is None:
            out.enemy_defeated_reward = EnemyDefeatedReward(
                gainedExperience=10, loot=["Gold Coin"]
            )

        return out

    except Exception as e:
        logging.error(f"Error in enemy_knocked_out: {e}")
        return LLMFreeOutcome(
            narrative="The enemy crumples to the ground, defeated once and for all.",
            effects=[],
            combat_state=None,
            active_combat=False,
            enemy_health=0,
            enemy_defeated_reward=EnemyDefeatedReward(
                gainedExperience=10, loot=["Gold Coin"]
            ),
            suggested_actions=["Collect your reward", "Search the area"],
        )
