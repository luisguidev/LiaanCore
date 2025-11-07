// Mapeamento/static/mapeamento/script.js

document.addEventListener('DOMContentLoaded', function() {
    console.log("Script JS inicializado para Agendamento Múltiplos Dias.");
    
    // --- Seletores ---
    const modal = document.getElementById('agendamento-modal');
    const closeButton = document.querySelector('.close-button');
    const agendarButtons = document.querySelectorAll('.btn-agendar');
    
    // Elementos do Formulário
    const pcIdInput = document.getElementById('computador-id-input');
    const pcNomeDisplay = document.getElementById('pc-nome-display');
    const dataInicioInput = document.getElementById('data-inicio');     // NOVO
    const dataFimInput = document.getElementById('data-fim');           // NOVO
    const horarioInicioSelect = document.getElementById('horario-inicio-select');
    const horarioFimSelect = document.getElementById('horario-fim-select');
    const horariosFeedback = document.getElementById('horarios-feedback');
    const btnSubmit = document.getElementById('btn-submit-agendamento');
    const horarioInicioHidden = document.getElementById('horario-inicio-input');
    const horarioFimHidden = document.getElementById('horario-fim-input');
    
    let pcIdAtual = null; 
    let todosPontosDeTempo = []; // Todos os horários de 00:00 a 23:30

    // --- FUNÇÃO PARA POPULAR LISTAS DE HORÁRIOS ---
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

    // --- 1. ABRIR O MODAL E INICIALIZAR ---
    agendarButtons.forEach(button => {
        button.addEventListener('click', function() {
            pcIdAtual = this.getAttribute('data-pc-id');
            const pcNome = this.getAttribute('data-pc-nome');
            
            // Limpa e reinicializa os campos
            pcIdInput.value = pcIdAtual;
            pcNomeDisplay.textContent = pcNome; 
            
            // Reseta todos os 4 campos
            dataInicioInput.value = '';
            horarioInicioSelect.innerHTML = '<option value="">Selecione a data</option>';
            horarioInicioSelect.disabled = true;
            dataFimInput.value = '';
            dataFimInput.disabled = true;
            horarioFimSelect.innerHTML = '<option value="">Selecione a hora de início</option>';
            horarioFimSelect.disabled = true;
            
            btnSubmit.disabled = true;
            horariosFeedback.textContent = '';
            
            modal.style.display = 'flex'; 
        });
    });

    // --- FUNÇÕES DE FECHAR MODAL ---
    closeButton.addEventListener('click', () => modal.style.display = 'none');
    window.addEventListener('click', (event) => {
        if (event.target === modal) modal.style.display = 'none';
    });


    // --- 2. AJAX: BUSCAR TODOS OS PONTOS DE TEMPO PARA UM DIA ---
    // Esta função será chamada quando a data de início ou fim for alterada.
    function buscarPontosDeTempo(dataSelecionada, callback) {
        horariosFeedback.textContent = 'Buscando pontos de tempo...';
        
        // URL que retorna todos os pontos (00:00 a 23:30)
        const url = `/horarios_disponiveis/?data=${dataSelecionada}`; 

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


    // --- 3. LÓGICA DE INÍCIO (Data e Hora) ---
    dataInicioInput.addEventListener('change', function() {
        const dataSelecionada = this.value;

        // Reseta os campos Fim
        dataFimInput.value = '';
        dataFimInput.min = dataSelecionada; // Data Fim deve ser >= Data Início
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
            
            // Dispara o evento de mudança na hora de início para recalcular o FIM
            horarioInicioSelect.dispatchEvent(new Event('change'));
        });
    });

    horarioInicioSelect.addEventListener('change', function() {
        const inicioValue = this.value;
        const dataInicio = dataInicioInput.value;
        const dataFim = dataFimInput.value;
        
        // Se a hora de início for selecionada, atualiza o hidden input
        horarioInicioHidden.value = inicioValue; 

        // Reseta os campos finais
        horarioFimSelect.innerHTML = '<option value="">Selecione a hora final...</option>';
        horarioFimSelect.disabled = true;
        btnSubmit.disabled = true;
        horarioFimHidden.value = '';

        if (!inicioValue || !dataFim) return; 

        // Se Data de Início == Data Final: Filtra horários de Fim (deve ser depois do Início)
        if (dataInicio === dataFim) {
            const startIndex = todosPontosDeTempo.findIndex(p => p.value === inicioValue);
            const pontosFim = todosPontosDeTempo.slice(startIndex + 1);
            
            popularHorariosSelect(horarioFimSelect, pontosFim, 'Selecione a hora final...');
        } else {
            // Se Data de Início < Data Final: Todos os horários são válidos para a Data Fim
            // Chamamos a busca novamente para a data final
            dataFimInput.dispatchEvent(new Event('change'));
        }
    });

    // --- 4. LÓGICA DE FIM (Data e Hora) ---
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
            // Aqui, todos os pontos do dia final são carregados
            popularHorariosSelect(horarioFimSelect, pontos.slice(1), 'Selecione a hora final...');
            
            // Se a data de início e fim forem iguais, aplica o filtro de hora
            if (dataInicio === dataFim && inicioValue) {
                const startIndex = todosPontosDeTempo.findIndex(p => p.value === inicioValue);
                const pontosFim = todosPontosDeTempo.slice(startIndex + 1);
                
                popularHorariosSelect(horarioFimSelect, pontosFim, 'Selecione a hora final...');
            } else {
                 // Se datas diferentes, a hora de início não importa (qualquer horário do dia seguinte é válido)
                 popularHorariosSelect(horarioFimSelect, pontos, 'Selecione a hora final...');
            }
        });
    });

    horarioFimSelect.addEventListener('change', function() {
        const fimValue = this.value;
        
        horarioFimHidden.value = fimValue;

        if (horarioInicioSelect.value && fimValue) {
            btnSubmit.disabled = false; // Habilita o botão se ambos os horários estiverem preenchidos
            horariosFeedback.textContent = '';
        } else {
            btnSubmit.disabled = true;
        }
    });
    
    // --- 5. Opcional: Mostrar erros de validação do Django (após redirect) ---
    const hasDjangoErrors = document.querySelector('.messages li.error') !== null;
    if (hasDjangoErrors) {
        modal.style.display = 'flex';
    }
});