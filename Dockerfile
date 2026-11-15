FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dashboard/app.py dashboard/app.py
COPY dashboard/metricas.py dashboard/metricas.py
COPY dashboard/assets dashboard/assets
COPY bi/*.sql bi/*.py bi/decisiones_vigentes.csv bi/
COPY datamart/*.sql datamart/
COPY deploy/init_db.py deploy/init_db.py
ENV MUSEOS_HOST=0.0.0.0 MUSEOS_PORT=8050
WORKDIR /srv/dashboard
EXPOSE 8050
CMD ["gunicorn","-b","0.0.0.0:8050","--workers","1","--timeout","120","app:server"]
