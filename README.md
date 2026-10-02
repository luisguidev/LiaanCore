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
| **Rate Limiting** | Cadastro, login e **login do admin** são limitados. O limite por usuário é o que fecha a força bruta: não depende de IP. | ✅ **Completo** |
| **Administração (Django Admin)** | Interface nativa do Django para gerenciar Usuários, Computadores e Agendamentos, com auditoria de cancelamento. O login do painel tem rate limit próprio. | ✅ **Completo** |
| **Testes** | 101 testes automatizados cobrindo conflito de horário, concorrência, permissões, soft delete, fuso horário, o contrato de ETag e as travas de segurança de produção. | ✅ **Completo** |

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

- 🐍 Python **3.10+** (o Django 5.2 declara suporte até 3.13)  
- 📦 pip (gerenciador de pacotes Python)  
- 🐳 Docker Desktop (ou Docker Engine no Linux)

> **A versão do Python é fixada em `.python-version` (3.13)** porque o Render lê
> esse arquivo no build. Sem ele o deploy usa o Python padrão do Render, que
> muda de tempos em tempos — e um build que roda numa máquina pode falhar na
> seguinte. Atenção: em desenvolvimento local muita gente está em **3.14**, que o
> Django 5.2 ainda não declara suportar. Funciona, mas a diferença entre o que
> você testa e o que é publicado é justamente o tipo de coisa que vira incidente
> numa sexta.

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
o mesmo slot ao mesmo tempo**, a permissão de exclusão (dono/admin/terceiro), o
`304` do ETag e as travas de segurança de produção (rate limit do admin, bypass
por `X-Forwarded-For`, recusa de subir sem host válido, trava do simulador).
São **101 testes** e levam cerca de 2min30.

> A suíte inteira passa em ~2min30. Se ela parecer travada, quase sempre é o
> `test_postgres` deixado para trás por uma interrupção: rode
> `python manage.py test --noinput`, que ele aparece e é destruído.

---

## 📡 **Testar o Tempo Real com Vários Dispositivos**

Os testes automatizados provam o contrato do endpoint `estado/`, mas não que um
cliente HTTP real consegue consumi-lo. Para isso existe o simulador: ele abre N
sessões independentes (cookies próprios, como navegadores distintos), agenda em
uma delas e confere se as outras enxergam a reserva, se o `304` para de vir
quando algo muda e se o cancelamento some da tela de todo mundo.

```bash
# terminal 1
python manage.py runserver

# terminal 2
python manage.py simular_dispositivos
python manage.py simular_dispositivos --dispositivos 5 --intervalo 2
```

| **Opção** | **Padrão** | **Para quê** |
|---|---|---|
| `--url` | `http://127.0.0.1:8000` | Endereço do servidor. |
| `--dispositivos` | `3` | Quantas sessões simultâneas (mínimo 2). |
| `--intervalo` | `5.0` | Segundos entre polls — o mesmo `5s` do `realtime.js`. |
| `--espera` | `12.0` | Tempo máximo para a reserva chegar aos outros. |
| `--manter` | desligado | Não cancela o agendamento no fim. |
| `--permitir-producao` | desligado | Destrava o comando fora do ambiente local. |

Ele sai com código `1` e lista as falhas se algum passo não bater, então serve
como verificação antes de deploy. Os agendamentos criados são removidos no fim.

> ⚠️ **É um comando de desenvolvimento.** Ele cria os usuários `disp1..N` com
> `is_active=True` — exatamente o que o fluxo de aprovação do cadastro existe
> para impedir — e a senha padrão está escrita no código, ou seja, publicada.
> Por isso ele **recusa** rodar com `DEBUG=0` ou apontando para um host que não
> seja localhost. Com `--permitir-producao` ele passa, mas apaga os usuários no
> final. Os usuários `disp1..N` ficam no banco quando roda localmente, para você
> entrar e olhar.

---

## 🚦 **Rate Limiting**

Tentativas de login, de login no admin e de cadastro são contadas no próprio
Postgres (modelo `TentativaRateLimit`), em janela fixa alinhada por bloco de
tempo. Não há Redis nem cache: o `LocMem` do Django é **por processo**, então
com vários workers do Gunicorn cada um contaria separado e o limite seria burlado.

A limpeza das janelas vencidas acontece sozinha (1 em cada 50 chamadas). Para
forçar:

```bash
python manage.py limpar_rate_limit           # só as vencidas (>24h)
python manage.py limpar_rate_limit --tudo    # zera tudo
```

### Por que existe um limite **por usuário**

O limite por IP sozinho **não fecha** a força bruta. O `X-Forwarded-For` que o
Render entrega tem o valor escolhido pelo cliente na primeira posição — mandar
`X-Forwarded-For: 1.2.3.4` numa requisição por vez faz cada tentativa cair numa
janela diferente, e o contador nunca acumula.

Por isso existe um segundo contador, por nome de usuário
(`RATE_LIMIT_LOGIN_POR_USUARIO`), que não depende de IP nem de header nenhum: é
preciso errar a senha muitas vezes seguidas contra a mesma conta. O teto é
propositalmente mais alto e a janela mais curta que o do IP — travar conta é
DoS, e isso não pode virar um botão de bloqueio de usuário.

O `client_ip()` também passou a preferir `True-Client-Ip` e `CF-Connecting-IP`,
que a borda do Render **sobrescreve** (o cliente não consegue forjar). O
`X-Forwarded-For` continua como último recurso: a documentação do Render não
garante se o proxy reescreve ou apenas anexa o header, e trocar a posição com
base em suposição faria todo mundo cair no mesmo bucket do IP da borda.

### Limites configuráveis

| **Variável** | **Padrão** | **Protege** |
|---|---|---|
| `RATE_LIMIT_LOGIN` | `(300, 10)` | login, por IP |
| `RATE_LIMIT_LOGIN_POR_USUARIO` | `(300, 15)` | login, por conta |
| `RATE_LIMIT_LOGIN_ADMIN` | `(300, 10)` | `/admin/login/`, por IP |
| `RATE_LIMIT_CADASTRO` | `(3600, 5)` | cadastro, por IP |

O limite do admin conta **tentativas**, não falhas: se contasse só os erros, o
próprio limite viraria o que o atacante quer, porque ele erra N vezes e então
acerta a senha.

---

## 🚀 **Deploy no Render**

O deploy é controlado pelo `Procfile`, que o Render executa sozinho — não é
preciso configurar build command no painel:

```
release: python manage.py collectstatic --noinput && python manage.py migrate --noinput
web:     gunicorn liaancore.wsgi:application --workers 2 --threads 4 --timeout 120
```

A fase `release` roda **depois do build e antes do novo deploy receber tráfego**.
Ela não é opcional: com `DEBUG=0` o storage de estáticos é
`CompressedManifestStaticFilesStorage`, que dá erro em qualquer `{% static %}`
sem o manifest — todas as páginas responderiam 500. E sem `migrate`, a tabela do
rate limit não existe e toda tentativa de login com senha errada dá 500.

### Variáveis de ambiente no painel

| **Variável** | **Valor** |
|---|---|
| `DEBUG` | `0` |
| `SECRET_KEY` | obrigatória — o Django **recusa subir** sem ela |
| `ALLOWED_HOSTS` | `liaancore.onrender.com` (opcional: o Render define `RENDER_EXTERNAL_URL`) |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | do Supabase |
| `DB_HOST` | `aws-1-us-east-1.pooler.supabase.com` |
| `DB_PORT` | `6543` |
| `DB_SSLMODE` | `require` (padrão em produção) |
| `CONN_MAX_AGE` | `60` (padrão) |
| `RESEND_API_KEY` / `LIAAN_ADMIN_EMAIL` | para o aviso de cadastro |
| `RESEND_FROM_EMAIL` | remetente do aviso — **veja o aviso abaixo** |
| `DJANGO_ADMINS` | quem recebe o relatório de erro (`Nome <email>`) |
| `DJANGO_LOG_LEVEL` | `INFO` (padrão) |

Sem `ALLOWED_HOSTS` **e** sem `RENDER_EXTERNAL_URL` o Django **recusa subir** em
produção. Antes havia um fallback para o curinga `.onrender.com`, que aceitava
qualquer subdomínio do Render no cabeçalho `Host` — brecha de host-header
injection, já que o domínio não é seu.

> **O aviso de cadastro não funciona com o remetente padrão.** O
> `onboarding@resend.dev` só é aceito pela Resend quando o destinatário é o
> dono da conta. Verifique um domínio na Resend e aponte `RESEND_FROM_EMAIL`
> para ele, senão o admin nunca recebe o aviso de novo usuário. A falha agora
> vai para o log (`liaancore.cadastro`) com traceback, em vez de sumir num
> `print`.

### Depois do primeiro deploy

O banco de produção começa vazio, e a fixture **não** é carregada
automaticamente. Sem os computadores, o painel mostra "Nenhum computador
cadastrado". Após o deploy:

```bash
# 1. Criar o superusuário (para /admin e para aprovar os cadastros)
python manage.py createsuperuser

# 2. Cadastrar os computadores reais — pelo /admin, não pela fixture.
#    A fixture tem dados fictícios (IPs de documentação, AnyDesk zerado) e
#    serves só para desenvolvimento.
```

### Logs

Os logs vão para o console (é o que o Render coleta). Erros de requisição
aparecem em `ERROR` e o relatório do Django sai por e-mail para `DJANGO_ADMINS`.
`django.server` fica em `WARNING` para o polling de 5s não virar um fluxo de
log.

> **Porta `6543` = modo transação do PgBouncer.** Foi verificado nesta
> configuração que o psycopg2 2.9.11 (libpq 17) **não** cria prepared statements,
> então esse modo é seguro aqui. O `select_for_update()` do formulário de
> agendamento roda dentro de `transaction.atomic()`, e uma transação mantém a
> mesma conexão no pooler. Se um dia der erro do tipo *prepared statement
> already exists*, troque `DB_PORT` para `5432` (modo sessão).

> **Ponto de atenção no HSTS:** `SECURE_HSTS_SECONDS` vale 1 ano. Depois que um
> navegador recebe esse header, ele recusa HTTP naquele domínio por um ano. Para
> desligar temporariamente, defina a variável como `0`.

Gerando a `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## 🐘 **Sobre a versão do PostgreSQL**

O `docker-compose.yml` fixa o **PostgreSQL 17**, que é a versão mais nova
suportada pelo Django 5.2 (13 a 17). O container que existia na máquina rodava a
18, fora desse intervalo — por isso foi recriado na 17.

---

## 🔐 **Segurança**

⚠️ **Nunca versione `cert.key`/`cert.crt` nem o `.env`.** O `.gitignore` já cobre
ambos, mas confira antes de qualquer `git add -A`. Se uma chave privada entrou no
histórico do repositório, **rotacione o certificado** — removê-la do índice não
apaga o histórico.

### O que já está no histórico do repositório

O repositório é **público**, e a fixture `Mapeamento/fixtures/dados_iniciais.json`
original trazia dados reais do laboratório: IPs internos (`192.168.68.x`), IDs do
AnyDesk e nomes das máquinas. A fixture foi trocada por dados fictícios (IPs da
faixa de documentação `192.0.2.0/24`, AnyDesk zerado), **mas os dados antigos
continuaram no histórico do git** — quem clonar e olhar o log encontra.

Se isso é sensível para a instituição, dá para limpar com `git filter-repo`
(filtra blobs) ou BFG e reescrever o histórico. Como é operação destrutiva
(force-push), não foi feita automaticamente.

Por isso: **nunca commite dados reais de infraestrutura.** A fixture é de
exemplo e deve continuar assim.

### Demais pontos de atenção

- O simulador (`simular_dispositivos`) cria usuários **ativos** com senha fixa.
  Ele recusa rodar com `DEBUG=0` ou contra host que não seja localhost, e
  apaga os usuários ao final quando roda com `--permitir-producao`. A senha
  padrão está no código, ou seja, publicada — nunca use esse comando em
  produção.
- `EMAIL_BACKEND` está como `console` em todos os ambientes. Não quebra nada
  hoje (o envio real é feito pela API do Resend), mas se alguém plugar
  "esqueci minha senha" sem trocar isso, a senha vai para o stdout.