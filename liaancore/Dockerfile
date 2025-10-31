# Dockerfile

# Usa uma imagem Python leve e estável
FROM python:3.10-slim

# Define a variável de ambiente para que os logs não sejam armazenados em buffer (melhor para contêineres)
ENV PYTHONUNBUFFERED 1

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copia o arquivo de dependências e o instala primeiro para aproveitar o cache (cache layer)
COPY requirements.txt /app/

# Instala as dependências de produção
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código para o contêiner
COPY . /app

# Coleta arquivos estáticos (CSS/JS) em uma pasta única (staticfiles) para o WhiteNoise servir
RUN python manage.py collectstatic --noinput

# Comando que o Cloud Run irá executar.
# Ele inicia o Gunicorn, ligando-o à porta $PORT (fornecida pelo ambiente do Cloud Run) 
# e apontando para o WSGI do seu projeto (liaancore.wsgi:application).
CMD exec gunicorn --bind :$PORT --workers 2 --threads 4 liaancore.wsgi:application