FROM python:3-alpine
ENV BT_BACKUP_PATH=/tmp/BT_backup
WORKDIR /opt/qbt_migrate
COPY qbt_migrate qbt_migrate
COPY pyproject.toml pyproject.toml
COPY LICENSE.md LICENSE.md
COPY README.md README.md
RUN pip install flit
ENV FLIT_ROOT_INSTALL=1
RUN flit install --symlink --deps production
RUN printf '#!/bin/ash\nexec qbt_migrate -b $BT_BACKUP_PATH $@' > entrypoint.sh
RUN chmod +x entrypoint.sh
ENTRYPOINT ["./entrypoint.sh"]
