FROM apache/airflow:2.10.5-python3.12

COPY requirements.txt /requirements-airflow.txt

# A imagem ja e um virtualenv; instalamos direto nele (sem --user).
# Usamos --no-cache-dir e ignoramos o aviso de root.
RUN pip install --no-cache-dir -r /requirements-airflow.txt || \
    PIP_ROOT_USER_ACTION=ignore pip install --no-cache-dir -r /requirements-airflow.txt
