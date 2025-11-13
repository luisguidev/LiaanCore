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
| **Status Dinâmico** | Os cards indicam se o PC está **Disponível**, **Em Manutenção** ou **Ocupado**, com base nos agendamentos. | ✅ **Completo** |
| **Agendamento Flexível** | Usuários logados podem agendar horários de Início e Fim. O sistema valida conflitos no *back-end* em tempo real. | ✅ **Completo** |
| **Lista de Agendamentos** | Cada card exibe uma lista de agendamentos futuros/atuais (com *scroll* para listas longas). | ✅ **Completo** |
| **Administração (Django Admin)** | Interface nativa do Django para gerenciar Usuários, Computadores e Agendamentos. | ✅ **Completo** |

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

O **Django** precisa de variáveis de ambiente para se conectar ao banco de dados local.

Crie um arquivo chamado **`.env`** na raiz do projeto (mesma pasta onde está o arquivo `manage.py`) e adicione o conteúdo abaixo:

```bash
# .env (Configuração para DESENVOLVIMENTO LOCAL com Docker)

SECRET_KEY='django-insecure-local-key'  # Pode ser qualquer string
DEBUG='1'

DB_NAME='postgres'
DB_USER='postgres'
DB_PASSWORD='docker'
DB_HOST='localhost'
DB_PORT='5432'

## 3️⃣ **Iniciar o Banco de Dados com Docker**

Com o **Docker** em execução, rode o comando abaixo para criar e iniciar o contêiner do banco de dados **PostgreSQL**:

```bash
# Baixa e inicia um contêiner Postgres na porta 5432 com a senha 'docker'
docker run --name liaan-postgres -e POSTGRES_PASSWORD=docker -p 5432:5432 -d postgres:15

# 1. Aplicar Migrações (cria as tabelas no banco Docker)
python manage.py migrate

# 2. Criar um Superusuário (necessário para acessar o /admin local)
python manage.py createsuperuser

# 3. Executar o servidor de desenvolvimento
python manage.py runserver