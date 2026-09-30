/* =========================================================================
 * Tempo real do LiaanCore — polling com ETag.
 *
 * Estratégia: o navegador pergunta a cada 5s se algo mudou. A resposta vem
 * com um ETag; se o cliente enviar o mesmo If-None-Match, o servidor devolve
 * 304 sem corpo e sem consultar os cards. Só re-renderizamos quando há
 * alteração de verdade, então o custo por usuário ocioso é ~1 query leve.
 *
 * Por que polling e não WebSocket: funciona no deploy atual (Gunicorn/WSGI
 * no Render) sem Redis, sem ASGI e sem custo de infraestrutura. Se um dia
 * vir WebSocket, basta este arquivo ser trocado — o contrato com o servidor
 * (endpoint `estado/` + ETag) continua válido.
 * ========================================================================= */

(function() {
    'use strict';

    const INTERVALO_MS = 5000;

    const grid = document.getElementById('computadores-grid');
    if (!grid) return;

    const urlEstado = grid.dataset.estadoUrl || '/agendamento/estado/';
    // O HTML já foi renderizado com este ETag, então a primeira leitura
    // responds 304 e não redesenha nada.
    let etagAtual = grid.dataset.etag || null;
    let timer = null;
    let ocupado = false;
    let encerrado = false;

    // ---------------------------------------------------------------- utils

    function toast(mensagem, isErro) {
        const area = document.getElementById('toast-area');
        if (!area) return;

        const item = document.createElement('div');
        item.className = 'toast' + (isErro ? ' toast-erro' : '');
        item.textContent = mensagem;
        area.appendChild(item);

        setTimeout(() => {
            item.classList.add('toast-saindo');
            setTimeout(() => item.remove(), 300);
        }, 4000);
    }

    function avisarSessaoExpirada() {
        parar();
        toast('Sua sessão expirou. Atualize a página para entrar novamente.', true);
    }

    // ------------------------------------------------------------- render

    function montarItemAgendamento(agendamento) {
        const li = document.createElement('li');

        const usuario = document.createElement('span');
        usuario.className = 'agendamento-user';
        usuario.textContent = agendamento.usuario;
        li.appendChild(usuario);

        const tempo = document.createElement('span');
        tempo.className = 'agendamento-time';
        tempo.textContent = agendamento.inicio + ' - ' + agendamento.fim;
        li.appendChild(tempo);

        if (agendamento.pode_excluir) {
            const botao = document.createElement('button');
            botao.type = 'submit';
            botao.form = 'form-excluir';
            botao.name = 'agendamento_id';
            botao.value = agendamento.id;
            botao.className = 'btn-excluir-agendamento';
            botao.dataset.agendamento = agendamento.id;
            botao.dataset.pcNome = agendamento.pcNome || '';
            botao.title = 'Excluir agendamento';
            botao.setAttribute('aria-label', 'Excluir agendamento de ' + agendamento.usuario);
            botao.textContent = 'Excluir';
            li.appendChild(botao);
        }

        return li;
    }

    function aplicarCard(card, dados) {
        const lista = card.querySelector('.agendamento-list');
        if (!lista) return;

        // O modal em aberto nunca é tocado: o usuário não perde o preenchimento.
        lista.innerHTML = '';

        if (!dados.agendamentos || dados.agendamentos.length === 0) {
            const li = document.createElement('li');
            li.className = 'no-agendamento';
            li.textContent = 'Livre de agendamentos.';
            lista.appendChild(li);
        } else {
            dados.agendamentos.forEach(agendamento => {
                agendamento.pcNome = dados.nome;
                lista.appendChild(montarItemAgendamento(agendamento));
            });
        }

        // Status visual: a classe do card, o data-status (usado pelos filtros)
        // e o texto precisam sair sincronizados.
        if (card.dataset.status !== dados.status) {
            card.classList.remove('status-D', 'status-O', 'status-M');
            card.classList.add('status-' + dados.status);
            card.dataset.status = dados.status;
        }

        const dot = card.querySelector('.status-dot');
        if (dot) {
            dot.classList.remove('status-D', 'status-O', 'status-M');
            dot.classList.add('status-' + dados.status);
        }

        const texto = card.querySelector('.status-text');
        if (texto) texto.textContent = dados.rotulo;
    }

    function reaplicarFiltros() {
        // Os filtros são reaplicados para respeitar a mudança de status.
        const selectStatus = document.getElementById('filter-status');
        const btnAll = document.getElementById('btn-filter-all');
        if (!selectStatus || !btnAll) return;

        selectStatus.dispatchEvent(new Event('change'));
    }

    function renderizar(computadores) {
        const porId = new Map();
        computadores.forEach(c => porId.set(String(c.id), c));

        document.querySelectorAll('.card').forEach(card => {
            const dados = porId.get(card.dataset.pcId);
            if (dados) aplicarCard(card, dados);
        });

        reaplicarFiltros();
    }

    // -------------------------------------------------------------- poll

    function recarregar() {
        if (ocupado || encerrado) return Promise.resolve();

        ocupado = true;

        const headers = { 'Accept': 'application/json' };
        if (etagAtual) headers['If-None-Match'] = etagAtual;

        return fetch(urlEstado, {
            headers: headers,
            credentials: 'same-origin',
            cache: 'no-store'
        })
        .then(response => {
            if (response.status === 304) return null;

            if (response.redirected && response.url.includes('/accounts/login/')) {
                avisarSessaoExpirada();
                return null;
            }

            if (!response.ok) throw new Error('HTTP ' + response.status);

            const novoEtag = response.headers.get('ETag');
            if (novoEtag) etagAtual = novoEtag;

            return response.json();
        })
        .then(dados => {
            if (dados && dados.computadores) {
                renderizar(dados.computadores);
                if (grid.dataset.versao !== dados.versao) {
                    grid.dataset.versao = dados.versao;
                }
            }
        })
        .catch(error => {
            console.warn('Polling falhou:', error);
        })
        .finally(() => {
            ocupado = false;
        });
    }

    function iniciar() {
        if (timer) return;
        timer = setInterval(() => {
            // Aba em segundo plano: não gastamos consulta à toa.
            if (document.hidden) return;
            recarregar();
        }, INTERVALO_MS);
    }

    function parar() {
        encerrado = true;
        if (timer) {
            clearInterval(timer);
            timer = null;
        }
    }

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) recarregar();
    });

    window.addEventListener('offline', parar);
    window.addEventListener('online', () => { encerrado = false; iniciar(); recarregar(); });

    // API usada por script.js (exclusão) para forçar uma atualização imediata.
    window.LiaancoreRealTime = { recarregar: recarregar, notificar: toast };

    // Primeira leitura já usa o ETag implícito do servidor; a resposta 304
    // evita inclusive renderizar algo que acabou de ser desenhado no HTML.
    window.LiaancoreRealTime.recarregar().then(iniciar);
})();
