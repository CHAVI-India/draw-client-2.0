This is a guide on how to install the Draw Client 2.0 using Docker.

Copy the contents of the folder and rename the files as follows:

- .example.env.docker to .env.docker
- .example.docker-compose.yml to docker-compose.yml
- .example.nginx.conf to nginx.conf

The important parameters that need to changed in the .env.docker file are:

- DJANGO_SECRET_KEY : Create a new one from https://djecrety.ir/ 
- DJANGO_DB_PASSWORD : Set a password for the database
- DJANGO_SUPERUSER_PASSWORD : Set a password for the superuser
- DJANGO_SUPERUSER_EMAIL : Set an email for the superuser
- DJANGO_SUPERUSER_USERNAME : Set a username for the superuser


Note that the Rabbitmq and Memcached container parameters are set to default values. 

In the docker componse the following parameters need to be changed. 

Location of the shared folder when DICOM images are to be stored. 
"/mnt/share/dicom_processing_test/datastore:/app/datastore"

In this example the section "/mnt/share/dicom_processing_test/datastore" is the path to the local storage. 
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

For the appropriate volume section has to be uncommented and used. 



