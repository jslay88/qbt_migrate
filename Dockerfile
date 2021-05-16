FROM python:3-alpine
ENV BT_BACKUP_PATH=/tmp/BT_backup
WORKDIR /opt/qbt_migrate
COPY qbt_migrate qbt_migrate
COPY requirements.txt requirements.txt
COPY setup.py setup.py
COPY LICENSE.md LICENSE.md
COPY README.md README.md
RUN pip install -e .
ENTRYPOINT ["/bin/sh", "-c", "qbt_migrate -b $BT_BACKUP_PATH"]
