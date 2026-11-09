# Installation Guide

This is a guide on how to install the Draw Client 2.0 using Docker.

Copy the contents of the folder and rename the files as follows:

- .example.env to .env
- .example.docker-compose.yml to docker-compose.yml
- .example.nginx.conf to nginx.conf

## Credentials and Passwords

The important parameters that need to changed in the .env.docker file are:

```bash
- DJANGO_SECRET_KEY : Create a new one from https://djecrety.ir/ 
- DJANGO_DB_PASSWORD : Set a password for the database
- DJANGO_SUPERUSER_PASSWORD : Set a password for the superuser
- DJANGO_SUPERUSER_EMAIL : Set an email for the superuser
- DJANGO_SUPERUSER_USERNAME : Set a username for the superuser
```

Also set the Postgres parameters:

```bash
POSTGRES_USER = postgres
POSTGRES_PASSWORD = postgres
POSTGRES_DB = drawclient 
```

Note that the Rabbitmq and Memcached container parameters are set to default values. 

## Storage Configuration

In the docker componse the following parameters need to be changed. 

Location of the shared folder when DICOM images are to be stored. 
"/mnt/share/dicom_processing_test/datastore:/app/datastore"

In this example the section "/mnt/share/dicom_processing_test/datastore" is the path to the local storage. For the appropriate volume section has to be uncommented and used. 

Then the following volume configuration should be used (please uncomment the section in the docker compose called local storage).

```bash
volumes:
  postgres_data:
  app_data:
  dicomdata:
    driver: local
    driver_opts:
      o: bind
      type: none
      device: "/mnt/share/dicom_processing_test/datastore"   
```

Note that in case of windows machines you can use D:/dicomdata if the folder is located in the D drive in a folder called dicomdata

If for example your folder is a network shared folder then the CIFS configuration has to be set such that the folder can be accessed. 
```bash
volumes:
  postgres_data:
  app_data:
  dicomdata:
    driver_opts:
      type: cifs
      o: "username=${NETWORK_USER},domain=${NETWORK_DOMAIN},password=${NETWORK_PASSWORD},rw,uid=1000,gid=1000,file_mode=0660,dir_mode=0770"
      device: ${NETWORK_PATH}   
```


Typically for CIFS we will need the following parameters to be set:

1. NETWORK_USER : Set the username for the network share
2. NETWORK_DOMAIN : Set the domain for the network share
3. NETWORK_PASSWORD : Set the password for the network share
4. NETWORK_PATH : Set the path to the network share

Note that these values should be saved in the .env file in the section for the same. 

## Fernet secret

A 32 bit url safe fernet encryption key is required. This enables the fields to be properly encrypted (specifically the bearer token and refresh token). 

In order to create a key you can visit the following site : https://fernetkeygen.com/

Remeber that this key typically ends with an equal to sign (=). 


## Ports

Port configuration may need to be changed for the following containers if you have other containers using the same port. Specifically the following ports may need to be changed (see the docker compose for the details):

1. Postgres port 
2. Rabbitmq port and Rabbitmq Management Port
3. Memcached port
4. Nginx port

Remeber that the port that is exposed to the outside needs to be changed. 
For example if the port configuration for postgres reads like below:

```bash
  db:
    image: postgres:17
    container_name: draw-client-postgres-docker
    ports:
      - "5433:5432" # External port for postgres may need to be changed.
    volumes:
      - postgres_data:/var/lib/postgresql/data
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5
```

And the port is used then the following will change the external port.

```bash
  db:
    image: postgres:17
    container_name: draw-client-postgres-docker
    ports:
      - "5436:5432" # External port for postgres may need to be changed.
    volumes:
      - postgres_data:/var/lib/postgresql/data
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5

```

Here we have mapped the port 5436 on the host machine to the container 5432 port. Note that in the previous section the mapped host port was 5433.


# Database migrations and container startup

Only one container migrates the database. The compose file defines a one-shot
`migrate` service (`./entrypoint.docker.sh migrate`) that runs collectstatic,
migrations and the superuser creation, then exits. `django-web`, `celery` and
`celery-beat` set `RUN_MIGRATIONS=false` and wait for it via
`depends_on: migrate: condition: service_completed_successfully`.

Before this, all three long-running containers called the same entrypoint and
ran `manage.py migrate` at once, which produced `DuplicateTable` /
`DuplicateColumn` errors, deadlocks, and lock waits that looked like hangs.

```bash
docker compose up -d          # migrator runs first, then the services start
docker compose logs -f migrate
```

Migrations are also safe to re-run by hand:

```bash
docker compose run --rm migrate
docker compose exec django-web python manage.py migrate_locked
```

`migrate_locked` wraps `migrate` in a Postgres advisory lock, so if two
containers do arrive together they queue instead of corrupting each other's
schema work. The wait is bounded by `MIGRATE_LOCK_TIMEOUT` (default 1800s) and
fails with an explicit message rather than hanging forever. On SQLite the lock
is skipped and `migrate` runs directly.

## Long migrations and maintenance windows

`dicom_handler` migration `0057` merges duplicate study/series/instance rows and
`0059` then adds the UID unique constraints with `CREATE UNIQUE INDEX
CONCURRENTLY`. Concurrent builds take no blocking write lock, but they *wait*
for other sessions that hold conflicting locks or old snapshots — including
`idle in transaction` sessions from the web and Celery containers, and
autovacuum on freshly churned tables. For big databases run it with the
long-running containers stopped:

```bash
docker compose stop django-web celery celery-beat
docker compose run --rm migrate
docker compose up -d
```

To see whether such a step is working or merely waiting:

```sql
SELECT phase, blocks_done, blocks_total, tuples_done, tuples_total,
       wait_event_type, wait_event
  FROM pg_stat_progress_create_index;

SELECT pid, pg_blocking_pids(pid) AS blocked_by, wait_event_type, wait_event,
       state, now() - query_start AS running_for
  FROM pg_stat_activity
 WHERE pid <> pg_backend_pid() ORDER BY running_for NULLS LAST;
```

A `waiting for writers` / `waiting for old snapshots` phase means something else
is holding it up; a `building index: scanning table` phase whose `blocks_done`
is climbing is real work. Raising `maintenance_work_mem` (default 64MB) before
the build avoids a slow external sort. Cancelling is safe: the migration is
re-runnable and drops any invalid leftover index itself.

## After an image upgrade, check the app_data volume

The services mount the named volume `app_data` at `/app`. Compose copies the
image's contents into a named volume only when that volume is **first created**;
it does not refresh it when the image changes. An environment that has been
upgraded can therefore keep running code from the old image, and a newly added
migration will simply not exist there. Confirm what the container is really
running:

```bash
docker compose run --rm django-web python manage.py showmigrations dicom_handler | tail
```

If it is stale, recreate the volume. The documented Docker install uses
Postgres (`DJANGO_DB_HOST=db`), so `app_data` holds only application code: the
database is in `postgres_data`, DICOM data in `dicomdata`, and `logs` /
`staticfiles` are bind mounts, all of which survive. **If you changed
`DJANGO_DB_ENGINE` to SQLite and left `DJANGO_DB_NAME` inside `/app`, the
database itself lives in `app_data` — back it up before removing the volume.**

```bash
docker compose down
docker volume rm <project>_app_data
docker compose up -d
```

# Additional Note on Extra Hosts Parameter

There is an extra hosts parameter provided in the docker compose to allow the dicom server to provide C-MOVE services. During C-MOVE service, the server has to negotitate the external IP address. 

In the extra hosts section (needs to be uncommented) the IP address of the remote machine where the DICOM files will be transferred using the C-MOVE command needs to be provided. 

Note that C-FIND and C-ECHO work without this paramter. 

```bash
    extra_hosts:
      - "ctkstore=172.12.12.21"
      - 'varian=172.16.23.1'
```

Note that this is only required if the C-MOVE service is used. You can add multiple extra hosts. 

If the extra hosts parameter is used in the application the remote service should be identified by the hostname instead of the IP Address.

