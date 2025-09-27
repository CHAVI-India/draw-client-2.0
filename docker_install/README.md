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