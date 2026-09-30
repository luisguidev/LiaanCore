document.addEventListener('DOMContentLoaded', function() {

    // =========================================================================
    // 0. SELETORES GLOBAIS
    // =========================================================================

    const grid = document.getElementById('computadores-grid');

    const cards = document.querySelectorAll('.card');
    const btnAll = document.getElementById('btn-filter-all');
    const selectGpu = document.getElementById('filter-gpu');
    const selectStatus = document.getElementById('filter-status');

    const modal = document.getElementById('agendamento-modal');
    const closeButton = document.querySelector('.close-button');
    const pcInput = document.getElementById('computador-input');
    const pcNomeDisplay = document.getElementById('pc-nome-display');

    const dataInicioInput = document.getElementById('data-inicio');
    const dataFimInput = document.getElementById('data-fim');
    const horarioInicioSelect = document.getElementById('horario-inicio-select');
    const horarioFimSelect = document.getElementById('horario-fim-select');
    const horarioInicioHidden = document.getElementById('horario-inicio-input');
    const horarioFimHidden = document.getElementById('horario-fim-input');

    const horariosFeedback = document.getElementById('horarios-feedback');
    const btnSubmit = document.getElementById('btn-submit-agendamento');

    // Estado
    let pcIdAtual = null;
    let pontosDoDia = [];   // pontos livres do dia da data de início
    let requestEmAndamento = false;  // evitaRace no polling

    // =========================================================================
    // 1. FILTROS
    // =========================================================================

    const gpusUnicas = new Set();
    cards.forEach(card => {
        const gpu = card.getAttribute('data-gpu');
        if (gpu && gpu.trim() !== '' && gpu !== 'None') {
            gpusUnicas.add(gpu.trim());
        }
    });

    gpusUnicas.forEach(gpu => {
        const option = document.createElement('option');
        option.value = gpu.toLowerCase();
        option.textContent = gpu;
        selectGpu.appendChild(option);
    });

    function aplicarFiltros() {
        const gpuSelecionada = selectGpu.value.toLowerCase();
        const statusSelecionado = selectStatus.value;

        cards.forEach(card => {
            const cardGpu = (card.getAttribute('data-gpu') || '').toLowerCase();
            const cardStatus = card.getAttribute('data-status');

            const passaFiltroGpu = (gpuSelecionada === 'all' || cardGpu === gpuSelecionada);
            const passaFiltroStatus = (statusSelecionado === 'all' || cardStatus === statusSelecionado);

            card.style.display = (passaFiltroGpu && passaFiltroStatus) ? 'flex' : 'none';
        });

        if (gpuSelecionada === 'all' && statusSelecionado === 'all') {
            btnAll.classList.add('active');
        } else {
            btnAll.classList.remove('active');
        }
    }

    if (selectGpu) selectGpu.addEventListener('change', aplicarFiltros);
    if (selectStatus) selectStatus.addEventListener('change', aplicarFiltros);

    if (btnAll) {
        btnAll.addEventListener('click', () => {
            selectGpu.value = 'all';
            selectStatus.value = 'all';
            aplicarFiltros();
        });
    }

    // =========================================================================
    // 2. MODAL
    // =========================================================================

    function resetarFormulario() {
        dataInicioInput.value = '';
        horarioInicioSelect.innerHTML = '<option value="">Selecione a data</option>';
        horarioInicioSelect.disabled = true;

        dataFimInput.value = '';
        dataFimInput.disabled = true;
        dataFimInput.removeAttribute('min');
        horarioFimSelect.innerHTML = '<option value="">Selecione a hora de início</option>';
        horarioFimSelect.disabled = true;

        btnSubmit.disabled = true;
        horariosFeedback.textContent = '';
        horarioInicioHidden.value = '';
        horarioFimHidden.value = '';
    }

    function abrirModal(pcId, pcNome) {
        pcIdAtual = pcId;
        pcInput.value = pcId;
        pcNomeDisplay.textContent = pcNome;
        resetarFormulario();
        modal.style.display = 'flex';
    }

    cards.forEach(card => {
        card.addEventListener('click', function(event) {
            // Não abre o modal ao clicar em um botão (ex.: Excluir) ou em texto
            // que o usuário esteja selecionando.
            if (event.target.closest('button')) return;

            if (window.getSelection().toString().length > 0) return;

            if (this.classList.contains('status-M')) {
                console.warn('Máquina em manutenção. Agendamento bloqueado.');
                return;
            }

            abrirModal(this.getAttribute('data-pc-id'), this.getAttribute('data-pc-nome'));
        });
    });

    // Click-to-Copy
    document.querySelectorAll('.copyable-data').forEach(el => {
        el.addEventListener('click', function(e) {
            e.stopPropagation();

            const originalText = this.innerText;
            const originalColor = this.style.color;

            navigator.clipboard.writeText(originalText).then(() => {
                this.innerText = 'Copiado!';
                this.style.color = '#00e676';
                setTimeout(() => {
                    this.innerText = originalText;
                    this.style.color = originalColor;
                }, 1000);
            }).catch(err => {
                console.error('Falha ao copiar texto: ', err);
            });
        });
    });

    if (closeButton) {
        closeButton.addEventListener('click', () => modal.style.display = 'none');
    }

    window.addEventListener('click', (event) => {
        if (event.target === modal) modal.style.display = 'none';
    });

    // =========================================================================
    // 3. HORÁRIOS (AJAX)
    // =========================================================================

    function popularHorariosSelect(selectElement, pontosArray, defaultValue) {
        selectElement.innerHTML = `<option value="">${defaultValue}</option>`;
        if (pontosArray && pontosArray.length > 0) {
            pontosArray.forEach(ponto => {
                const option = document.createElement('option');
                option.value = ponto.value;
                option.textContent = ponto.display;
                selectElement.appendChild(option);
            });
            selectElement.disabled = false;
        } else {
            selectElement.disabled = true;
        }
    }

    // O endpoint agora devolve APENAS os pontos livres para o computador.
    function buscarPontosDeTempo(dataSelecionada, inicioSelecionado, callback) {
        if (!pcIdAtual) {
            horariosFeedback.textContent = 'Erro: Computador não identificado.';
            return callback([]);
        }

        let url = `/agendamento/horarios_disponiveis/?computador_id=${encodeURIComponent(pcIdAtual)}` +
                  `&data=${encodeURIComponent(dataSelecionada)}`;
        if (inicioSelecionado) {
            url += `&inicio=${encodeURIComponent(inicioSelecionado)}`;
        }

        fetch(url, { headers: { 'Accept': 'application/json' } })
            .then(response => {
                if (response.redirected && response.url.includes('/accounts/login/')) {
                    throw new Error('SESSAO_EXPIRADA');
                }
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    horariosFeedback.textContent = data.error;
                    return callback([]);
                }
                horariosFeedback.textContent = '';
                callback(data.pontos || []);
            })
            .catch(error => {
                console.error('Erro AJAX:', error);
                horariosFeedback.textContent = 'Erro na comunicação com o servidor.';
                callback([]);
            });
    }

    // --- Data de início ---
    dataInicioInput.addEventListener('change', function() {
        const dataSelecionada = this.value;

        dataFimInput.value = '';
        dataFimInput.min = dataSelecionada;
        dataFimInput.disabled = false;
        horarioFimSelect.innerHTML = '<option value="">Selecione a data final</option>';
        horarioFimSelect.disabled = true;
        btnSubmit.disabled = true;
        horarioFimHidden.value = '';
        horarioInicioHidden.value = '';

        if (!dataSelecionada) {
            horarioInicioSelect.disabled = true;
            return;
        }

        horariosFeedback.textContent = 'Buscando horários livres...';
        buscarPontosDeTempo(dataSelecionada, null, (pontos) => {
            pontosDoDia = pontos;
            // O último ponto é removido porque não há como ser horário de início.
            popularHorariosSelect(horarioInicioSelect, pontos.slice(0, -1), 'Selecione a hora de início...');
        });
    });

    // --- Hora de início ---
    horarioInicioSelect.addEventListener('change', function() {
        const inicioValue = this.value;
        const dataInicio = dataInicioInput.value;
        const dataFim = dataFimInput.value;

        horarioInicioHidden.value = inicioValue;

        horarioFimSelect.innerHTML = '<option value="">Selecione a hora final...</option>';
        horarioFimSelect.disabled = true;
        btnSubmit.disabled = true;
        horarioFimHidden.value = '';

        if (!inicioValue || !dataFim) return;

        if (dataInicio === dataFim) {
            const indice = pontosDoDia.findIndex(p => p.value === inicioValue);
            // Sem este guard, `slice(0)` liberaria horários ANTERIORES ao início.
            if (indice === -1) return;
            popularHorariosSelect(
                horarioFimSelect,
                pontosDoDia.slice(indice + 1),
                'Selecione a hora final...'
            );
        } else {
            dataFimInput.dispatchEvent(new Event('change'));
        }
    });

    // --- Data final ---
    dataFimInput.addEventListener('change', function() {
        const dataFim = this.value;
        const dataInicio = dataInicioInput.value;
        const inicioValue = horarioInicioSelect.value;

        btnSubmit.disabled = true;
        horarioFimHidden.value = '';

        if (!dataFim || !dataInicio) return;

        if (dataFim < dataInicio) {
            horariosFeedback.textContent = 'A data final não pode ser anterior à data de início.';
            horarioFimSelect.innerHTML = '<option value="">Selecione a data final</option>';
            horarioFimSelect.disabled = true;
            return;
        }

        // Mesmo dia: reaproveita os pontos já carregados, sem nova requisição.
        // Outro dia: pede os pontos livres daquele dia, já depois do início.
        if (dataInicio === dataFim) {
            const indice = pontosDoDia.findIndex(p => p.value === inicioValue);
            if (indice === -1) {
                horarioFimSelect.innerHTML = '<option value="">Selecione a hora de início</option>';
                horarioFimSelect.disabled = true;
                return;
            }
            popularHorariosSelect(
                horarioFimSelect,
                pontosDoDia.slice(indice + 1),
                'Selecione a hora final...'
            );
            return;
        }

        horariosFeedback.textContent = 'Buscando horários livres...';
        buscarPontosDeTempo(dataFim, inicioValue, (pontos) => {
            popularHorariosSelect(horarioFimSelect, pontos, 'Selecione a hora final...');
        });
    });

    // --- Hora final ---
    horarioFimSelect.addEventListener('change', function() {
        horarioFimHidden.value = this.value;

        const pronto = Boolean(horarioInicioSelect.value) && Boolean(this.value);
        btnSubmit.disabled = !pronto;
        if (pronto) horariosFeedback.textContent = '';
    });

    // =========================================================================
    // 4. REABRINDO O MODAL APÓS ERRO DE VALIDAÇÃO
    // =========================================================================
    // A view re-renderiza a página (HTTP 200) com o formulário vinculado,
    // em vez de redirecionar e perder o que o usuário preencheu.

    if (grid && grid.dataset.modalAberto === '1') {
        const pcId = grid.dataset.pcId;
        if (pcId) {
            const card = grid.querySelector(`.card[data-pc-id="${CSS.escape(pcId)}"]`);
            abrirModal(pcId, card ? card.getAttribute('data-pc-nome') : '');

            // Reaproveita a data já escolhida, se o navegador a tiver.
            const inicio = document.getElementById('horario-inicio-input').value;
            if (inicio) {
                dataInicioInput.value = inicio.slice(0, 10);
                dataInicioInput.dispatchEvent(new Event('change'));
            }
        }
    }

    // =========================================================================
    // 5. EXCLUSÃO (soft delete) com confirmação
    // =========================================================================

    const formExcluir = document.getElementById('form-excluir');
    const CSRF_TOKEN = document.querySelector('[name=csrfmiddlewaretoken]');

    if (formExcluir) {
        formExcluir.addEventListener('submit', function(event) {
            const botao = event.submitter;
            if (!botao || !botao.dataset.agendamento) return;

            const card = botao.closest('.card');
            const pcNome = card ? card.getAttribute('data-pc-nome') : 'este computador';
            const item = botao.closest('li');
            const usuario = item ? item.querySelector('.agendamento-user').textContent : '';
            const horario = item ? item.querySelector('.agendamento-time').textContent : '';

            const confirmado = window.confirm(
                `Excluir o agendamento de ${usuario} (${horario.trim()}) em ${pcNome}?`
            );
            if (!confirmado) {
                event.preventDefault();
                return;
            }

            // Envia via fetch para não recarregar a página; se o fetch falhar,
            // o proprio form segue com o POST normal (fallback sem JS).
            if (typeof window.LiaancoreRealTime === 'undefined') return;

            event.preventDefault();

            const url = botao.getAttribute('formaction');
            const formData = new FormData();
            formData.append('agendamento_id', botao.dataset.agendamento);
            if (CSRF_TOKEN) formData.append('csrfmiddlewaretoken', CSRF_TOKEN.value);

            fetch(url, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin'
            })
            .then(response => {
                if (response.status === 403) throw new Error('SEM_PERMISSAO');
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(data => {
                window.LiaancoreRealTime.notificar(data.mensagem || 'Agendamento excluído.');
                window.LiaancoreRealTime.recarregar();
            })
            .catch(error => {
                if (error.message === 'SEM_PERMISSAO') {
                    window.LiaancoreRealTime.notificar('Você não tem permissão para excluir este agendamento.', true);
                } else {
                    // Volta ao submit nativo para não perder a operação.
                    formExcluir.submit();
                }
            });
        });
    }

    // =========================================================================
    // 6. LOGOUT
    // =========================================================================

    document.querySelectorAll('.logout-form').forEach(form => {
        form.addEventListener('submit', event => {
            if (!window.confirm('Deseja realmente sair do sistema?')) {
                event.preventDefault();
            }
        });
    });
});
