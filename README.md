# Welcome

This is a revamped version of the DRAW Client with the following enhancements:
1. A more robust ruleset system, which allows us to match the rules using other operators.
2. Validation for the dicom tags in ruleset based on the allowed value representation. Thus if a tag has a VR which accepts only date then only date can be entered as a evaluable value for the rule.
3. A refreshed autosegmentation template system which does not rely on creating YAML files but instead stores the template data on database. This allows us to update the templates without having to recreate them.
4. A less I/O intensive DICOM flow with no extra copying of DICOM files to save space on the disc. The DICOM files are only copied when they have to be deidentified and exported. After export the dICOM files are deleted.
5. A more integrated view of the DICOM data processing in the system by integrating the deidentification system with the original system so that a holistic view of the process can be seen.
6. This also has a secondary benefit of reducing the celery task chain
7. Better logging with integrating masking of identifiers.
8. Parallel processing of reading DICOM files to speed up the process.
9. Better validation of DICOM tags by ensuring that the value representation is taken into account. 


# Technology Stack 
1. Django
2. PostgresSQL database
3. Celery and Celery beat
4. RabbitMQ server
5. Tailwind CSS

# Setup notes for dockerized installation
When run as a docker container the following services will be needed:
1. Nginx
2. Postgres
3. Celery and Celery beat
4. RabbitMQ
5. Memcached
