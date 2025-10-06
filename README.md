# ⚙️ Dank Dungeon — Backend (FastAPI + MongoDB + ChromaDB + Gemini API)

Este repositório contém o **backend completo do projeto Dank Dungeon**, uma plataforma de RPG baseada em texto e combate interativo, com geração narrativa controlada por IA.  
A API foi desenvolvida em **FastAPI** e integra autenticação, gerenciamento de campanhas, personagens e um sistema de narrativa dinâmica com **LLM (Gemini API)** e **memória vetorial (ChromaDB)**.

---

## 🚀 Funcionalidades Principais

### 🧙‍♂️ Sistema de RPG Narrativo
- Geração dinâmica de narrativas com IA usando **Gemini API**.
- Interpretação de ações do jogador e progressão de história.
- Gerenciamento de **estado de combate** (ataques, magias, resultados e efeitos).
- Registro contínuo de turnos de jogo e contexto passado.

### 🪄 Manipulação de Contexto e Memória
- Utiliza **ChromaDB** como banco vetorial para armazenar e recuperar turnos passados.
- Cada campanha tem seu próprio espaço vetorial, permitindo consultas contextuais.
- Implementa **query semântica + reranker interno** para buscar turnos mais relevantes.

### 👤 Sistema de Usuários
- Registro e autenticação com **JWT**.
- Endpoints para **login**, **signup** e **perfil do usuário**.
- Armazenamento seguro de senhas com **bcrypt**.
- Middleware para validação automática de tokens.

### 🧝‍♀️ Gerenciamento de Personagens
- Criação e listagem de personagens vinculados a cada usuário.
- Atributos suportados:
  - Nome, raça, classe, nível, vida e descrição.
- Modelagem orientada a documentos via **Beanie ODM** (sobre MongoDB).

### ⚔️ Campanhas e Turnos
- Criação e continuidade de campanhas individuais.
- Cada turno é armazenado com:
  - Ação do jogador
  - Resposta narrativa
  - Estado de combate (JSON)
  - Contexto e ID da campanha
- Requisições podem recuperar histórico e gerar novas ações dentro da mesma linha narrativa.

---

## 🧩 Estrutura do Projeto

```
backend/
│
├── .devcontainer/
│   └── devcontainer.json               # Configuração do ambiente DevContainer (Python 3.12)
│
├── app/
│   ├── chromadb/
│   │   ├── insert.py                   # Inserção de turnos no banco vetorial
│   │   ├── query.py                    # Consulta e reranqueamento de turnos similares
│   │   └── setup.py                    # Configuração do cliente ChromaDB e funções de embedding
│   │
│   ├── services/
│   │   ├── gameplay_service.py         # Lógica principal de combate, ações e rolagens
│   │   └── llm_service.py              # Integração com Gemini API e geração de narrativas
│   │
│   ├── utils/
│   │   ├── cheats.py                   # Funções de trapaça (ajustes de vida, etc.)
│   │   └── combat.py                   # Funções auxiliares de combate e rolagens
│   │
│   ├── auth.py                         # Autenticação JWT e verificação de usuário
│   ├── config.py                       # Configuração de ambiente e variáveis (.env)
│   ├── models.py                       # Modelos Pydantic e Beanie (User, Character, Campaign, Turn, etc.)
│   └── routes.py                       # Rotas FastAPI (auth, personagem, campanha, histórico)
│
├── main.py                             # Ponto de entrada FastAPI (CORS, inicialização Beanie, rotas)
├── requirements.txt                    # Dependências do projeto
├── .gitignore                          # Ignora cache, .env, e arquivos temporários
└── vectordb/                           # Diretório persistente do ChromaDB (armazenamento vetorial)

```


---

## 🧠 Tecnologias Utilizadas

### 🐍 Backend
- **FastAPI** — framework web moderno, rápido e tipado.
- **Python 3.12** — linguagem principal.
- **Uvicorn** — servidor ASGI para execução da API.

### 💾 Banco de Dados
- **MongoDB** — banco principal de documentos.
- **Beanie ODM** — integração assíncrona e orientada a modelos com MongoDB.
- **ChromaDB** — armazenamento vetorial para contexto e histórico narrativo.

### 🤖 Inteligência Artificial
- **Gemini API** — geração narrativa, resolução de combates e diálogos.
- **Prompt Builder** — estrutura dinâmica de prompts baseada em estado e contexto.

### 🔐 Segurança
- **JWT** — autenticação segura baseada em tokens.
- **argon2** — hashing de senhas.
- **CORS Middleware** — integração com o frontend Angular.

