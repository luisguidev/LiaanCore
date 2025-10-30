# 💻 LIAAN Core: Sistema de Gerenciamento de Laboratório (Mapeamento de Recursos)

## 🌟 Visão Geral do Projeto

O LIAAN Core é um sistema web desenvolvido em **Django (Python)** projetado para gerenciar e agendar o uso de recursos de hardware, como computadores de um laboratório de IA ou P&D. O principal objetivo é fornecer uma interface visual simples (Cards) onde os usuários podem verificar a disponibilidade das máquinas em tempo real e agendar blocos de tempo para seus projetos.

---

## ✨ Funcionalidades Principais

| Módulo | Descrição | Status |
| :--- | :--- | :--- |
| **Visualização (Página Principal)** | Exibição de "Cards" dinâmicos para cada computador com informações como Nome, IP do LM-Studio, Placa de Vídeo e ID do AnyDesk. | ✅ Completo |
| **Status Dinâmico** | Os cards indicam se o PC está **Disponível**, em **Manutenção** ou **Ocupado**. | ✅ Completo |
| **Agendamento Flexível** | Usuários logados podem agendar horários de Início e Fim (incluindo múltiplos dias). O sistema valida conflitos de horário no *back-end*. | ✅ Completo |
| **Lista de Agendamentos** | Cada card exibe uma lista de agendamentos futuros/atuais para a máquina (com scroll para listas longas). | ✅ Completo |
| **Administração (Django Admin)** | Interface para criar/editar PCs, gerenciar usuários e visualizar/deletar todos os agendamentos. | 🛠️ Pendente (Configurado, mas a customização pode ser expandida) |

---

## 🛠️ Guia de Instalação Local

Siga estes passos para configurar e executar o projeto em seu ambiente local.

### Pré-requisitos

* Python (versão recomendada: 3.10+)
* `pip` (gerenciador de pacotes Python)

### 1. Clonar o Repositório e Configurar o Ambiente

```bash
# 1. Clone o repositório
git clone https://github.com/luisguidev/LiaanCore.git
cd Liaancore

# 2. Crie e ative o ambiente virtual (Recomendado)
python -m venv venv
source venv/bin/activate  # Linux/macOS
.\venv\Scripts\activate   # Windows PowerShell

### 3. Configurar e Executar

O projeto usa o SQLite como banco de dados padrão para desenvolvimento.
Bash

# 1. Aplicar Migrações (Cria as tabelas no DB)
python manage.py makemigrations Mapeamento
python manage.py migrate

# 2. Criar um Superusuário (Necessário para acessar o painel Admin)
python manage.py createsuperuser

# 3. Executar o servidor de desenvolvimento
python manage.py runserver

Acesse o site em: http://127.0.0.1:8000/

Acesse a administração em: http://127.0.0.1:8000/admin/ (Use as credenciais criadas)

### 🏗️ Arquitetura e Estrutura

O projeto segue a arquitetura padrão Django (MTV - Model-Template-View).

Estrutura de Diretórios

liaancore/
├── liaancore/        # Configurações do Projeto (settings.py, urls.py principal)
├── Mapeamento/       # Aplicação Principal
│   ├── models.py     # Definição dos modelos Computador e Agendamento
│   ├── views.py      # Lógica de negócio (lista_computadores, agendar_computador, etc.)
│   ├── urls.py       # Rotas do aplicativo
│   ├── templatetags/ # Filtros customizados (ex: get_item para dicionários)
│   ├── static/       # Arquivos front-end (style.css, script.js)
│   └── templates/    # Arquivos HTML
├── db.sqlite3        # Banco de dados local (padrão)
├── manage.py         # Ferramenta de linha de comando
└── README.md

Modelos de Dados

Modelo	Chave Primária	Relacionamentos
Computador	id	-
Agendamento	id	ForeignKey para Computador, ForeignKey para User