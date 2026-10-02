# 💻 **LIAAN Core: Sistema de Gerenciamento de Laboratório**

---

## 🌟 **Visão Geral do Projeto**

O **LIAAN Core** é um sistema web desenvolvido em **Django (Python)** projetado para gerenciar e agendar o uso de recursos de hardware, como computadores de um laboratório de **IA** ou **P&D**.  
O principal objetivo é fornecer uma interface clara onde usuários autenticados podem verificar a disponibilidade das máquinas em tempo real e agendar blocos de tempo para seus projetos.

O sistema adota uma arquitetura **"login-first"**, onde a primeira página do site é a de autenticação — garantindo que apenas membros autorizados possam visualizar o status do laboratório.

---

## ✨ **Funcionalidades Principais**

| **Módulo** | **Descrição** | **Status** |
|-------------|----------------|-------------|
| **Autenticação Completa** | Fluxo de Login, Cadastro de novos usuários e Logout. A aplicação segue um padrão *login-first*. | ✅ **Completo** |
| **Visualização (Dashboard)** | Exibição de *cards* dinâmicos para cada computador com Nome, IP do LM-Studio, GPU e ID do AnyDesk. | ✅ **Completo** |
| **Status Dinâmico** | Os cards indicam se o PC está **Disponível**, **Em Manutenção** ou **Ocupado**, com base nos agendamentos. "Ocupado" é sempre **calculado**, nunca gravado no banco. | ✅ **Completo** |
| **Agendamento Flexível** | Usuários logados podem agendar horários de Início e Fim. O sistema valida conflitos no *back-end* em tempo real, com **lock transacional** para impedir reservas simultâneas no mesmo horário. | ✅ **Completo** |
| **Horários Livres** | O formulário só oferece slots de 30 min que estão **realmente livres** para aquele computador, considerando os agendamentos dos outros usuários. | ✅ **Completo** |
| **Lista de Agendamentos** | Cada card exibe uma lista de agendamentos futuros/atuais (com *scroll* para listas longas). | ✅ **Completo** |
| **Exclusão de Agendamentos** | Apenas **administradores ou o dono** do agendamento pode excluir. O cancelamento é **soft delete**: o histórico é preservado e o horário volta a ficar livre. | ✅ **Completo** |
| **Tempo Real** | Os usuários veem as alterações uns dos outros automaticamente: o painel faz *polling* a cada 5s com **ETag** e recebe `304 Not Modified` quando nada mudou, ou o snapshot completo quando algo muda. | ✅ **Completo** |
| **Rate Limiting** | Cadastro e login são limitados por IP para impedir abuso e ataques de força bruta. | ✅ **Completo** |
| **Administração (Django Admin)** | Interface nativa do Django para gerenciar Usuários, Computadores e Agendamentos, com auditoria de cancelamento. | ✅ **Completo** |
| **Testes** | 64 testes automatizados cobrindo conflito de horário, concorrência, permissões, soft delete, fuso horário e o contrato de ETag. | ✅ **Completo** |

---

## 🔌 **Endpoints JSON**

| **Rota** | **Método** | **Descrição** |
|----------|------------|---------------|
| `/agendamento/horarios_disponiveis/?computador_id=&data=[&inicio=]` | GET | Slots de 30 min **livres** para aquele computador no dia informado. `inicio` (opcional) filtra só o que vem depois do horário de início escolhido. |
| `/agendamento/estado/` | GET | Snapshot do laboratório para o *polling*. Responde `304` com `If-None-Match` igual ao `ETag` devolvido. |
| `/agendamento/<pk>/excluir/` | POST | Cancela um agendamento. `403` para quem não é dono nem admin. |

O `ETag` é "salted" com o usuário (`W/"v<total>-<maior_id>-<timestamp>-u<user_id>"`) porque o campo
`pode_excluir` da resposta depende de quem está logado — sem isso um `304` poderia
reaproveitar permissões de outra pessoa.

---

## 🛠️ **Tecnologias e Arquitetura**

O **LIAAN Core** foi desenvolvido com uma arquitetura profissional que separa os ambientes de **desenvolvimento** e **produção**.

**Stack Tecnológica:**

- **Back-end:** Django (Python)  
- **Servidor de Produção:** Gunicorn  
- **Deploy (Produção):** Render  
- **Banco de Dados (Produção):** Supabase (PostgreSQL via Pooler)  
- **Ambiente de Desenvolvimento:** Docker (Contêiner PostgreSQL)

---

### 🌍 **Ambientes**

| **Ambiente** | **Host** | **Servidor** | **Banco de Dados** |
|---------------|-----------|----------------|----------------|
| **Produção** | [liaancore.onrender.com](https://liaancore.onrender.com) | Gunicorn | Supabase (PostgreSQL Remoto) |
| **Desenvolvimento** | [http://127.0.0.1:8000](http://127.0.0.1:8000) | Django runserver | Docker (PostgreSQL Local) |

---

## 🚀 **Guia de Instalação Local (Docker)**

Siga estes passos para configurar e executar o projeto em seu ambiente local.  
O guia utiliza **Docker** para rodar o banco de dados **PostgreSQL**, garantindo um ambiente idêntico ao de produção.

---

### 📋 **Pré-requisitos**

- 🐍 Python **3.10+**  
- 📦 pip (gerenciador de pacotes Python)  
- 🐳 Docker Desktop (ou Docker Engine no Linux)

---

### 1️⃣ **Clonar e Configurar o Ambiente Virtual**

```bash
# 1. Clone o repositório
git clone https://github.com/luisguidev/LiaanCore.git
cd LiaanCore

# 2. Crie e ative o ambiente virtual (Recomendado)
python -m venv venv
source venv/bin/activate  # Linux/macOS
.\venv\Scripts\activate   # Windows PowerShell

# 3. Instale as dependências
pip install -r requirements.txt

## 2️⃣ **Configurar o Ambiente Local (`.env`)**

O **Django** lê a configuração do arquivo **`.env`** na raiz do projeto (mesma pasta
do `manage.py`). O `docker-compose.yml` usa o mesmo arquivo, então as credenciais
do banco só precisam existir em um lugar.

```bash
cp .env.example .env
```

Abra o `.env` e ajuste. Para desenvolvimento local basta manter os valores do
exemplo — em especial a senha do banco, que **precisa ser a mesma** no `.env` e no
container.

| **Variável** | **Para quê** |
|--------------|--------------|
| `SECRET_KEY` | Chave do Django. Gere com `python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"` |
| `DEBUG` | `1` em desenvolvimento. |
| `DB_PASSWORD` | Senha do Postgres — é a mesma que o compose cria no container. |
| `DB_PORT` | Porta **na sua máquina**. O padrão do compose é `5433`, porque a `5432` costuma estar ocupada por outros projetos. |

## 3️⃣ **Subir o Banco de Dados com Docker Compose**

Com o **Docker** em execução:

```bash
# Cria e sobe o Postgres (imagem postgres:17-alpine, a última suportada pelo Django 5.2)
docker compose up -d

# Verificar se ficou saudável
docker compose ps
```

Para desligar: `docker compose down` (os dados ficam no volume `pgdata`).
Para **apagar** os dados: `docker compose down -v`.

## 4️⃣ **Preparar o Banco e Rodar**

```bash
# 1. Aplicar migrações (cria as tabelas)
python manage.py migrate

# 2. Carregar os computadores de exemplo (5 PCs)
python manage.py loaddata dados_iniciais

# 3. Criar um superusuário (necessário para acessar o /admin e para testar)
python manage.py createsuperuser

# 4. Executar o servidor
python manage.py runserver
```

Acesse **http://127.0.0.1:8000** e logue com o superusuário. Os 5 computadores
aparecerão no painel já com os dados da fixture.

### ❌ Se der erro ao rodar

| **Erro** | **Causa** | **Solução** |
|----------|-----------|-------------|
| `FATAL: password authentication failed for user "..."` | A senha do `.env` não é a do container. | Confira se `DB_PASSWORD` do `.env` é igual ao `POSTGRES_PASSWORD` com que o volume foi criado. Se trocar a senha depois, o volume antigo **ignora** a variável: `docker compose down -v && docker compose up -d` e refaça as migrações. |
| `connection refused ... port 5432/5433` | O banco não está rodando. | `docker compose up -d` e veja `docker compose ps`. |
| `could not translate host name` | `DB_HOST` errado. | Deve ser `localhost`. |
| `relation "auth_user" does not exist` | Migrações não aplicadas. | `python manage.py migrate`. |
| `Invalid HTTP_HOST header` | `DEBUG=0` sem `ALLOWED_HOSTS`. | Defina `ALLOWED_HOSTS` ou use `DEBUG=1` no local. |
| `no module named django` | Ambiente virtual não ativado. | `source venv/bin/activate` e `pip install -r requirements.txt`. |

---

## 🧪 **Rodar os Testes**

```bash
python manage.py test
```

A suíte cria e destrói um banco `test_<DB_NAME>` automaticamente (com o `.env`
atual, `test_postgres`, dentro do mesmo container). Ela cobre, entre outras
coisas, a regra de conflito de horário, a **corrida entre dois usuários reservando
o mesmo slot ao mesmo tempo**, a permissão de exclusão (dono/admin/terceiro) e o
`304` do ETag. São **75 testes**.

---

## 🚦 **Rate Limiting**

Tentativas de login e de cadastro são contadas no próprio Postgres (modelo
`TentativaRateLimit`), em janela fixa alinhada por bloco de tempo. Não há Redis
nem cache: o `LocMem` do Django é **por processo**, então com vários workers do
Gunicorn cada um contaria separado e o limite seria burlado.

A limpeza das janelas vencidas acontece sozinha (1 em cada 50 chamadas). Para
forçar:

```bash
python manage.py limpar_rate_limit           # só as vencidas (>24h)
python manage.py limpar_rate_limit --tudo    # zera tudo
```

---

## 🐘 **Sobre a versão do PostgreSQL**

O `docker-compose.yml` fixa o **PostgreSQL 17**, que é a versão mais nova
suportada pelo Django 5.2 (13 a 17). O container que existia na máquina rodava a
18, fora desse intervalo — por isso foi recriado na 17.

---

## 🔐 **Variáveis de Ambiente (Produção)**

| **Variável** | **Obrigatória** | **Descrição** |
|--------------|-----------------|---------------|
| `SECRET_KEY` | sim | Chave secreta do Django. Nunca use o valor de exemplo. |
| `DEBUG` | sim | `1`/`true` liga o modo debug. **Em produção use `0`/`false`**, o que ativa `SECURE_SSL_REDIRECT`, cookies `secure` e HSTS. |
| `ALLOWED_HOSTS` | recomendado | Domínios separados por vírgula, ex.: `liaancore.onrender.com,laboratorio.iac.gov.br`. Sem isso, o fallback é `.onrender.com`. |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | sim | Conexão com o Postgres. |
| `RESEND_API_KEY` | para o cadastro | Chave da API do Resend. |
| `LIAAN_ADMIN_EMAIL` | para o cadastro | Quem recebe o aviso de novo usuário. |
| `SECURE_HSTS_SECONDS` | opcional | Padrão `31536000` (1 ano). Use `0` para desativar o HSTS. |

⚠️ **Nunca versione `cert.key`/`cert.crt` nem o `.env`.** O `.gitignore` já cobre
ambos, mas confira antes de qualquer `git add -A`. Se uma chave privada entrou no
histórico do repositório, **rotacione o certificado** — removê-la do índice não
apaga o histórico.