document.addEventListener('DOMContentLoaded', function() {
    
    // =========================================================================
    // 0. SELETORES GLOBAIS (Mapeamento do DOM)
    // =========================================================================
    
    // Cards e Filtros
    const cards = document.querySelectorAll('.card');
    const btnAll = document.getElementById('btn-filter-all');
    const selectGpu = document.getElementById('filter-gpu');
    const selectStatus = document.getElementById('filter-status');
    
    // Modal e Elementos do Formulário
    const modal = document.getElementById('agendamento-modal');
    const closeButton = document.querySelector('.close-button');
    const pcIdInput = document.getElementById('computador-id-input');
    const pcNomeDisplay = document.getElementById('pc-nome-display');
    
    const dataInicioInput = document.getElementById('data-inicio');
    const dataFimInput = document.getElementById('data-fim');
    const horarioInicioSelect = document.getElementById('horario-inicio-select');
    const horarioFimSelect = document.getElementById('horario-fim-select');
    const horarioInicioHidden = document.getElementById('horario-inicio-input');
    const horarioFimHidden = document.getElementById('horario-fim-input');
    
    const horariosFeedback = document.getElementById('horarios-feedback');
    const btnSubmit = document.getElementById('btn-submit-agendamento');
    
    // Variáveis de Estado
    let pcIdAtual = null; 
    let todosPontosDeTempo = []; // Armazena os horários do dia selecionado

    // =========================================================================
    // 1. MÓDULO DE FILTROS E POPULAÇÃO DINÂMICA
    // =========================================================================
    
    // Extrai as GPUs únicas dos cards renderizados e popula o select
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

    // Lógica de Ocultar/Exibir Cards baseada nos selects
    function aplicarFiltros() {
        const gpuSelecionada = selectGpu.value.toLowerCase();
        const statusSelecionado = selectStatus.value; 

        cards.forEach(card => {
            const cardGpu = card.getAttribute('data-gpu').toLowerCase();
            const cardStatus = card.getAttribute('data-status');

            const passaFiltroGpu = (gpuSelecionada === 'all' || cardGpu === gpuSelecionada);
            const passaFiltroStatus = (statusSelecionado === 'all' || cardStatus === statusSelecionado);

            if (passaFiltroGpu && passaFiltroStatus) {
                card.style.display = 'flex'; 
            } else {
                card.style.display = 'none'; 
            }
        });

        // Alterna o visual do botão "All"
        if (gpuSelecionada === 'all' && statusSelecionado === 'all') {
            btnAll.classList.add('active');
        } else {
            btnAll.classList.remove('active');
        }
    }

    if (selectGpu) selectGpu.addEventListener('change', aplicarFiltros);
    if (selectStatus) selectStatus.addEventListener('change', aplicarFiltros);

    // Botão de Reset
    if (btnAll) {
        btnAll.addEventListener('click', () => {
            selectGpu.value = 'all';
            selectStatus.value = 'all';
            aplicarFiltros(); 
        });
    }

    // =========================================================================
    // 2. MÓDULO DO MODAL (Abertura, Limpeza e Prevenção de Conflitos)
    // =========================================================================
    
    // --- Lógica 1: Detecção de Seleção de Texto (Usuário Tradicional) ---
    cards.forEach(card => {
        card.addEventListener('click', function() {
            
            // VERIFICAÇÃO NOVA: O usuário está selecionando/arrastando texto?
            const textoSelecionado = window.getSelection().toString();
            if (textoSelecionado.length > 0) {
                // Se tem texto selecionado, abortamos a abertura do modal
                return; 
            }

            // Bloqueia clique se o PC estiver em manutenção
            if(this.classList.contains('status-M')) {
                console.warn("Máquina em manutenção. Agendamento bloqueado.");
                return; 
            }
            
            // Coleta dados e injeta no modal
            pcIdAtual = this.getAttribute('data-pc-id');
            const pcNome = this.getAttribute('data-pc-nome');
            pcIdInput.value = pcIdAtual;
            pcNomeDisplay.textContent = pcNome; 
            
            // RESET CRÍTICO: Limpa todos os campos
            dataInicioInput.value = '';
            horarioInicioSelect.innerHTML = '<option value="">Selecione a data</option>';
            horarioInicioSelect.disabled = true;
            
            dataFimInput.value = '';
            dataFimInput.disabled = true;
            horarioFimSelect.innerHTML = '<option value="">Selecione a hora de início</option>';
            horarioFimSelect.disabled = true;
            
            btnSubmit.disabled = true;
            horariosFeedback.textContent = '';
            
            // Exibe o modal
            modal.style.display = 'flex'; 
        });
    });

    // --- Lógica 2: Click-to-Copy (Usuário Moderno) ---
    const copyableElements = document.querySelectorAll('.copyable-data');
    
    copyableElements.forEach(el => {
        el.addEventListener('click', function(e) {
            // STOP PROPAGATION: Impede que o clique "suba" para o card e abra o modal
            e.stopPropagation(); 
            
            const textToCopy = this.innerText;
            
            // Usa a API moderna do navegador para jogar na área de transferência
            navigator.clipboard.writeText(textToCopy).then(() => {
                // Feedback visual: Guarda o texto original e mostra que copiou
                const originalText = this.innerText;
                const originalColor = this.style.color;
                
                this.innerText = 'Copiado!';
                this.style.color = '#00e676'; // Fica verde vibrante (sua cor de status-D)
                
                // Retorna ao estado original após 1 segundo
                setTimeout(() => {
                    this.innerText = originalText;
                    this.style.color = originalColor;
                }, 1000);
            }).catch(err => {
                console.error('Falha ao copiar texto: ', err);
            });
        });
    });

    // Funções de fechamento do modal mantidas iguais...
    if (closeButton) {
        closeButton.addEventListener('click', () => modal.style.display = 'none');
    }
    
    window.addEventListener('click', (event) => {
        if (event.target === modal) modal.style.display = 'none';
    });

    // =========================================================================
    // 3. MÓDULO DE COMUNICAÇÃO AJAX E LÓGICA DE DATAS
    // =========================================================================
    
    // Função utilitária para renderizar as tags <option>
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

    // Busca os horários livres no Django via fetch API
    function buscarPontosDeTempo(dataSelecionada, callback) {
        horariosFeedback.textContent = 'Buscando pontos de tempo...';
        
        if (!pcIdAtual) {
            horariosFeedback.textContent = 'Erro: Computador não identificado.';
            return; 
        }

        const url = '/agendamento/horarios_disponiveis/?computador_id=' + pcIdAtual + '&data=' + dataSelecionada;

        fetch(url)
            .then(response => response.json())
            .then(data => {
                horariosFeedback.textContent = '';
                if (data.pontos && data.pontos.length > 0) {
                    callback(data.pontos);
                } else {
                    horariosFeedback.textContent = 'Erro ao carregar horários para este dia.';
                    callback([]);
                }
            })
            .catch(error => {
                console.error('Erro AJAX:', error);
                horariosFeedback.textContent = 'Erro na comunicação com o servidor.';
                callback([]);
            });
    }

    // --- Lógica: Data de Início ---
    dataInicioInput.addEventListener('change', function() {
        const dataSelecionada = this.value;

        dataFimInput.value = '';
        dataFimInput.min = dataSelecionada; 
        dataFimInput.disabled = false;
        horarioFimSelect.innerHTML = '<option value="">Selecione a data final</option>';
        horarioFimSelect.disabled = true;

        if (!dataSelecionada) {
            horarioInicioSelect.disabled = true;
            return;
        }

        buscarPontosDeTempo(dataSelecionada, (pontos) => {
            todosPontosDeTempo = pontos;
            popularHorariosSelect(horarioInicioSelect, pontos.slice(0, -1), 'Selecione a hora de início...');
            horarioInicioSelect.dispatchEvent(new Event('change'));
        });
    });

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
            const startIndex = todosPontosDeTempo.findIndex(p => p.value === inicioValue);
            const pontosFim = todosPontosDeTempo.slice(startIndex + 1);
            popularHorariosSelect(horarioFimSelect, pontosFim, 'Selecione a hora final...');
        } else {
            dataFimInput.dispatchEvent(new Event('change'));
        }
    });

    // --- Lógica: Data de Fim ---
    dataFimInput.addEventListener('change', function() {
        const dataFim = this.value;
        const dataInicio = dataInicioInput.value;
        const inicioValue = horarioInicioSelect.value;
        
        horarioFimSelect.innerHTML = '<option value="">Buscando horários...</option>';
        horarioFimSelect.disabled = true;
        btnSubmit.disabled = true;
        horarioFimHidden.value = '';

        if (!dataFim || !dataInicio) return;
        
        buscarPontosDeTempo(dataFim, (pontos) => {
            popularHorariosSelect(horarioFimSelect, pontos.slice(1), 'Selecione a hora final...');
            
            if (dataInicio === dataFim && inicioValue) {
                const startIndex = todosPontosDeTempo.findIndex(p => p.value === inicioValue);
                const pontosFim = todosPontosDeTempo.slice(startIndex + 1);
                popularHorariosSelect(horarioFimSelect, pontosFim, 'Selecione a hora final...');
            } else {
                 popularHorariosSelect(horarioFimSelect, pontos, 'Selecione a hora final...');
            }
        });
    });

    horarioFimSelect.addEventListener('change', function() {
        const fimValue = this.value;
        horarioFimHidden.value = fimValue;

        if (horarioInicioSelect.value && fimValue) {
            btnSubmit.disabled = false; 
            horariosFeedback.textContent = '';
        } else {
            btnSubmit.disabled = true;
        }
    });
    
    // --- Tratamento de Erros do Django ---
    const hasDjangoErrors = document.querySelector('.messages li.error') !== null;
    if (hasDjangoErrors) {
        modal.style.display = 'flex';
    }
});