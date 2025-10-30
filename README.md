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

