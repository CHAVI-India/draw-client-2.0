# Welcome

This is a revamped version of the DRAW Client with the following enhancements:
1. A more robust ruleset system, which allows us to match the rules using operators other than equal to.
2. Validation for the dicom tags in ruleset based on the allowed value representation. Thus if a tag has a VR which accepts only date then only date can be entered as a evaluable value for the rule.
3. A refreshed autosegmentation template system which does not rely on creating YAML files but instead stores the template data on database. This allows us to update the templates without having to recreate them.
4. A less I/O intensive DICOM flow with no extra copying of DICOM files to save space on the disc. The DICOM files are only copied when they have to be deidentified and exported. After export the dICOM files are deleted.
5. A more integrated view of the DICOM data processing in the system by integrating the deidentification system with the original system so that a holistic view of the process can be seen.
6. This also has a secondary benefit of reducing the complexity of the celery task chain
7. Better logging with integrating masking of identifiers. This prevents information leakage in the log files.
8. Parallel processing of reading DICOM files to speed up the process.

# Technology Stack Used

1. Django (https://www.djangoproject.com/)
2. Celery (https://docs.celeryproject.org/en/stable/)
3. RabbitMQ (https://www.rabbitmq.com/)
4. Memcached (https://memcached.org/)
5. PostgresSQL (https://www.postgresql.org/)
6. Python (https://www.python.org/)

# Getting Started

## Local Installation 

If you wish to evaluate the system for a local development or wish to install on a standalone Linux based system then you will need a the following :
1. Ubuntu Linux 22.04 or later
2. RabbitMQ server
3. Memcached
4. PostgresSQL database

To start locally install the following packages in the your Ubuntu System

### Python with virtual environment

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-dev
```
### RabbitMQ
```bash
sudo apt update
sudo apt install rabbitmq-server
```
### Memcached
```bash
sudo apt update
sudo apt install memcached
```
### PostgresSQL
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
```
Also we recommend that you use PGAdmin to manage your database. 
Please check your system repository on how to use PGAdmin.

### 
Clone the repository into a directory of your choice. Please remember that this directory will need appropriate privileges.

```bash
git clone https://github.com/draw-client/draw-client.git
cd draw-client
```

### Create a virtual environment

We recommend using a virtual environment to install the dependencies and isolate these from the system packages.

```bash
python3 -m venv venv
source venv/bin/activate
```

### Install dependencies

Inside your virtual environment install the dependencies. Whilst gunicorn is required for a server based install for development use the Django development server can be used.

```bash

pip install -r requirements.txt
```


### Environment Variables

Copy the file .env.sample to a file called .env

```bash

cp .env.sample .env
```

Edit the .env file to set the environment variables. The following are the important environment variables that will need to be setup.

1. DJANGO SECRET KEY: You can create a new Django secret key by going to https://djecrety.ir/. This secret key is important and should be stored securely

2. DJANGO ALLOWED HOSTS: This is the list of hosts that are allowed to access the server. For development use localhost,127.0.0.1,*. For production use your actual domain names.

3. DJANGO DEBUG: Set this to True for development and False for production.

4. CSRF_TRUSTED_ORIGINS: This is the list of origins that are trusted. For development use http://localhost,http://127.0.0.1,*. For production use your actual domain names.

5. Database settings: You will need to setup the username and password for the database along with the database name and host. The following variables will need values:

```bash

DJANGO_DB_NAME=drawclient
DJANGO_DB_USER=postgres
DJANGO_DB_PASSWORD=your_db_password
DJANGO_DB_HOST=localhost
DJANGO_DB_PORT=5432
```

6. If you have installed RabbitMQ and have created a dedicated vHost then the appropriate settings need to be provided. The following variables will need values:

```bash

RABBITMQ_URL=amqp://guest:guest@localhost:5672/
```
In this guest refers to the username and guest refers to the password. localhost refers to the host and 5672 refers to the port.

7. Proxy configuration

If the computer you are using will need a proxy configuration to communicate with external services then use the proxy configuration variables to set the proxy settings.

```bash

HTTP_PROXY=http://your-proxy:port
HTTPS_PROXY=http://your-proxy:port
NO_PROXY=localhost,127.0.0.1
``` 
8. Field Encryption Key: This is the key that is used to encrypt the fields in the database. It is important to store this securely. You can generate a new key using the following command:

```bash
python manage.py generate_encryption_key
```
Alternatively you can visit the site https://fernetkeygen.com/ to generate a new fernet encryption key.

### Create the database in PostgresSQL

 You will need to create the database in your postgres database before running this command. If you are using PGAdmin this can be done graphically. 

If not you can use the following command after dropping into the postgres user:

```bash
sudo -u postgres psql
createdb drawclient
```
In the above command the database drawclient has been created using the user postgres.

### Create the database structure

You will need to create the database structure using the following command:

```bash
python manage.py migrate
```
Note that this would create the application database tables in your postgres database.

### Create a superuser

You will need to create a superuser to access the admin interface. You can create a superuser using the following command:

```bash
python manage.py createsuperuser
```

### Start the server along with celery

You can start the server using the following command: Better validation of DICOM tags by ensuring that the value representation is taken into account. 
```
Two celery services will need to be started. One for the worker and one for the beat.

```bash
python celery -A draw_client worker -l INFO
python celery -A draw_client beat -l INFO

```

## Docker based installation

Docker provides a simple way to install the DRAW client system irrespective of your native operating system. 

For installation using Docker you will need to have docker and docker desktop installed in your local computer. We recommend following the official documentation for installation of docker and docker desktop based on your OS. 

Please checkout the README ([docker_install/README.md](docker_install/README.md)) provided in the docker_install folder for more information on how to install the system using Docker.

# Post Install configuration

## Browser based Application Access
Irrespective of docker based or local installation you will need to configure the applicaiton to communicate with the server. The application will be available on the url http://127.0.0.1:8000 if you have installed it locally or http://127.0.0.1:8003 if you have installed it using docker. Note that the IP address 127.0.0.1 resolves to localhost so you can use http://localhost:8000 (or http://localhost:8003) to access the application. 

## Logging In
When you open the application you will see the following screen:

![Initial Screen](screenshots/initial_screen.png)

To Login click the button on the top right of the screen (navigation bar). This will open a new window where you can enter your username and password. You will need to login with the admin user username and password that you have created. 

![Login Screen](screenshots/login_screen.png)


## Role and User group Configuration
Once you have logged in we recommend that you go to the administration and create user groups to restrict access to the administrative section. 

The user groups allows you to provide fine grained control over what the users can do in the system. 

The key functionality that will be required are:

1. To view the Processing Status of the DICOM files and trigger the autosegmentation process manually. 

2. To view the autosegmentation templates and create new templates. 

3. To view Rulesets and create new rulesets. 

4. To view and manage users and user groups. 

5. To manage system configuration.


We recommend the following groups to be created:

| Group Name | Description |
| --- | --- |
| Admin | Full access to the system |
| Senior Staff | Ability to create automatic segmentation templates and associate them with rulesets |
| Junior Staff | Ability to view the processing status of DICOM files and trigger the autosegmentation process manually |

The following permissions are required for each group:

### Admin user
This can be the superuser you have created in the first step or if you wish to create a new user with admin permissions you can do so by going to the user management section in the admin interface.

Click on the link called Admin at the top navbar to access to the Admin section. This will open the admin page which allows full access to all parts of the application. 

![Admin Page](screenshots/admin_page.png)

Click on the Groups link under Authentication and Authorization to access the user groupBefore setting up the system configuration we will need to create an account for you on the DRAW Server. This will be needed for the client to securely connect to the server. up button to create a new group. Give the name Admin to the group and Select the list of permissions from the box. The following minimum set of permissions are recommended:

#### System Configuration

1. Dicom_Handler|System Configuration| Can Add System Configuration
2. Dicom_Handler|System Configuration| Can Change System Configuration
3. Dicom_Handler|System Configuration| Can Delete System Configuration
4. Dicom_Handler|System Configuration| Can View System Configuration


#### User management

1. Authentication_and_Authorization|User| Can Add User
2. Authentication_and_Authorization|User| Can Change User
3. Authentication_and_Authorization|User| Can View User

#### Group management

1. Authentication_and_Authorization|Group| Can Add Group
2. Authentication_and_Authorization|Group| Can View Group

#### Ruleset management

1. Dicom_Handler|Ruleset| Can Add Ruleset
2. Dicom_Handler|Ruleset| Can Change Ruleset
3. Dicom_Handler|Ruleset| Can Delete Ruleset
4. Dicom_Handler|Ruleset| Can View Ruleset
5. Dicom_Handler|Rule| Can Add Rule
6. Dicom_Handler|Rule| Can Change Rule
7. Dicom_Handler|Rule| Can Delete Rule
8. Dicom_Handler|Rule| Can View Rule

#### Template Management

1. Dicom_Handler|Template| Can Add Template
2. Dicom_Handler|Template| Can Change Template
3. Dicom_Handler|Template| Can Delete Template
4. Dicom_Handler|Template| Can View Template
5. Dicom_Handler|AutosegmentationModel| Can Add AutosegmentationModel
6. Dicom_Handler|AutosegmentationModel| Can Change AutosegmentationModel
7. Dicom_Handler|AutosegmentationModel| Can Delete AutosegmentationModel
8. Dicom_Handler|AutosegmentationModel| Can View AutosegmentationModel
9. Dicom_Handler|Autosegmentation Mapped Structure| Can Add Autosegmentation Mapped Structure
10. Dicom_Handler|Autosegmentation Mapped Structure| Can Change Autosegmentation Mapped Structure
11. Dicom_Handler|Autosegmentation Mapped Structure| Can Delete Autosegmentation Mapped Structure
12. Dicom_Handler|Autosegmentation Mapped Structure| Can View Autosegmentation Mapped Structure


#### DICOM Series Management

1. Dicom_Handler|DICOM Series| Can View DICOM Series


### Senior Staff

We recommend that the senior staff role be created to allow users to create automatic segmentation templates and associate them with rulesets and view the dicom series processing results. The following permissions are recommended:


#### Ruleset management

1. Dicom_Handler|Ruleset| Can Add Ruleset
2. Dicom_Handler|Ruleset| Can Change Ruleset
3. Dicom_Handler|Ruleset| Can Delete Ruleset
4. Dicom_Handler|Ruleset| Can View Ruleset
5. Dicom_Handler|Rule| Can Add Rule
6. Dicom_Handler|Rule| Can Change Rule
7. Dicom_Handler|Rule| Can Delete Rule
8. Dicom_Handler|Rule| Can View Rule

#### Template Management

1. Dicom_Handler|Template| Can Add Template
2. Dicom_Handler|Template| Can Change Template
3. Dicom_Handler|Template| Can Delete Template
4. Dicom_Handler|Template| Can View Template
5. Dicom_Handler|AutosegmentationModel| Can Add AutosegmentationModel
6. Dicom_Handler|AutosegmentationModel| Can Change AutosegmentationModel
7. Dicom_Handler|AutosegmentationModel| Can Delete AutosegmentationModel
8. Dicom_Handler|AutosegmentationModel| Can View AutosegmentationModel
9. Dicom_Handler|Autosegmentation Mapped Structure| Can Add Autosegmentation Mapped Structure
10. Dicom_Handler|Autosegmentation Mapped Structure| Can Change Autosegmentation Mapped Structure
11. Dicom_Handler|Autosegmentation Mapped Structure| Can Delete Autosegmentation Mapped Structure
12. Dicom_Handler|Autosegmentation Mapped Structure| Can View Autosegmentation Mapped Structure Better validation of DICOM tags by ensuring that the value representation is taken into account. 


#### DICOM Series Management

1. Dicom_Handler|DICOM Series| Can View DICOM Series

### Junior Staff

For these staff we just need to give them permission to view DICOM Series and trigger the autosegmentation process manually. The following permissions are recommended:

#### DICOM Series Management

1. Dicom_Handler|DICOM Series| Can View DICOM Series


## Adding Users

Once the groups are created, then the users can be added to the roles based on your requirements. The process to add the user for an administrative user is as follows:
 Better validation of DICOM tags by ensuring that the value representation is taken into account. 
1. Go to the admin interface and click on the Users link under Authentication and Authorization.
2. Click on the Add user button to create a new user.
3. Fill in the required fields and select the group that you want to assign to the user.
4. Click on the Save button to save the user.

> [!IMPORTANT]
> Special note about Staff user role: In Django, access to the admin interface is restricted to staff users. Unless the "Staff status" checkbox is selected for a user, they will not be able to access the admin interface.


![Staff user](screenshots/staff_user.png)


## Setup the System Configuration

Click on the link called System Config to access the System Configuration page. 

![System Configuration](screenshots/system_config.png)

We will need to complete the following sections:

### DRAW Base URL

This will be the base URL for the DRAW website : https://draw.chavi.ai 

### Client ID

This will be an alphanumeric string to identify the client. This will be provided to you by the DRAW team. Please ensure that you enter the string exactly as provided by the DRAW team.

### Authentication

The DRAW team will guide you how to create the bearer token on the DRAW API server. This will need to be pasted into the box. Addtionationlly a Refersh token will also be provided which will be used to refresh the bearer token. The default validity period of the bearer token is 30 days. The expiry date will be provided to you. Note that this token will not be shown to you again once you have entered it in the box and saved the configuration. After the token is set a green checkbox will indicate that the token has been setup properly. 

![Token Set View](screenshots/token_set.png)

Click on save configuration button to save the configuration. 

> [!WARNING]
> It is important that you DO NOT setup the Date pull start datetime yet till the automatic segmentation templates have not been setup. If this is setup then the system will start pulling the dicom series from the DRAW API server and it will start processing them. 

![Date Pull Start](screenshots/date_pull_start.png)

Click on save configuration button to save the configuration. 

## Create Automatic Segmentation Templates

After the users and gorups have been created, please navigate to the main site (link in the top right corner or just enter http://localhost:8000 or http://localhost:8003). Once there click the Templates link in the navigation bar. This will open the templates page where you can create new templates.

![Templates](screenshots/templates.png)

Click on Create new Template button at the top right to create a new template.

![Create Template](screenshots/template_step1.png)

In the next page you will be able to see all the structures that are available from the DRAW models. You can search and filter the list to narrow down the choices. Each strucutre will also have a link which you can click to view details on the DRAW website. 

![Create Template](screenshots/template_step2.png)

Click on the checkbox beside the structure to select the structure for the template. Click on Save template button to save the template. After the template is created, you can click on the Templates link to view the newly created template. Clicking the view button beside the template name will open the template details page where you can view the template details.

![Template Details](screenshots/template_step3.png)

You can edit the template if you desire by clicking the Edit button at the top. 

> [!NOTE]
> We recommend that you have a discussion with the key stakeholders before setting up the templates. 

## Add the Rulesets

For each template that you create, we will need to define a set of rules which will define when this template should be used. To add a ruleset click on the RuleSets link in the top navbar. 
![RuleSets](screenshots/ruleset_list.png)

Click on the Create new RuleSet button at the top right to create a new ruleset.

![Create RuleSet](screenshots/ruleset_step1.png)

### Ruleset Information
This section allows you to provide basic information regarding the rules:
1. Ruleset Name: This is the name for the Ruileset
2. Ruleset Combination Type: This defines how the individual rules will be combined. There are two options 
  a. AND : This will ensure that all rules have to be evaluated to true for the ruleset to be true.
  b. OR : This will ensure that at least one rule has to be evaluated to true for the ruleset to be true.
3. Ruleset Description: This is a description for the ruleset. Please make this descriptive for future use and maintainence. 
4. Associated Autosegemntation template: When the ruleset is evaluated to be true, then this autosegmentation template will be used to generate the segmentation. Note that the DRAW client automatically sends the template to the remote server.

### Rules 
In this section you define the actual combination of rules for the ruleset. Each rule has the following components:

1. DICOM Tag: This is the DICOM Tag whose value is to be checked or evaluated. 
2. Operator: This defines how the evaluation will be performed
3. Value: This is the value which will be checked or evaluated. 

The following operators are available:

| Operatore Name | Description |
| --- | --- |
|Equals| This will evaluate to true if the value of the DICOM Tag is equal to the value specified in the rule. |
|Not Equals| This will evaluate to true if the value of the DICOM Tag is not equal to the value specified in the rule. | Better validation of DICOM tags by ensuring that the value representation is taken into account. 
|Greater Than| This will evaluate to true if the value of the DICOM Tag is greater than the value specified in the rule. |
|Less Than| This will evaluate to true if the value of the DICOM Tag is less than the value specified in the rule. |
|Greater Than or Equal To| This will evaluate to true if the value of the DICOM Tag is greater than or equal to the value specified in the rule. |
|Less Than or Equal To| This will evaluate to true if the value of the DICOM Tag is less than or equal to the value specified in the rule. |
|Case Insensitive String Contains| This will evaluate to true if the value of the DICOM Tag contains the string specified in the rule. |
|Case Insensitive String Does Not Contain| This will evaluate to true if the value of the DICOM Tag does not contain the string specified in the rule. |
|Case Sensitive String Contains| This will evaluate to true if the value of the DICOM Tag contains the string specified in the rule. Note in this case the string case should be matched exactly. |
|Case Sensitive String Does Not Contain| This will evaluate to true if the value of the DICOM Tag does not contain the string specified in the rule. Note in this case the string case should be matched exactly. |
|Case Sensitive Exact Match| This will evaluate to true if the value of the DICOM Tag is exactly equal to the string specified in the rule. Note in this case the string case should be matched exactly. |
|Case Insensitive Exact Match| This will evaluate to true if the value of the DICOM Tag is exactly equal to the string specified in the rule. The case is not matched in the evaluation. |


We provide the full list of DICOM tags which are specified in the DICOM standards for you to use. So you can define rules like this:

The template Breast DIBH should be used when the patient has a ProtocolName DIBH Breast

The template Prostate SBRT should be used to when the Modality is CT and ProtocolName Contains SBRT and BodyPartExamined is Prostate and ContrastVolume is Less than equal to 50.

Note that we provide guidance regarding the operator to be used for each tag type also. 

![Ruleset VR Guidance](screenshots/ruleset_step2.png)


You can add any number of rules to the ruleset. Once the Create Ruleset button is clicked then the ruleset will be created. 

> [!NOTE]
> We recommend that you have a discussion with the key stakeholders before setting up the rulesets. It is preferable to have a single ruleset for a single template and ensure that the rules do not overlap. 


## Complete the System Configuration

After the rulesets and templates are properly created you can go back to the System Configuration page and set the Date pull start datetime. This will enable the system to start pulling the DICOM data.


# Automatic DICOM Data Processing

The system uses celery for automatic processing of DICBefore setting up the system configuration we will need to create an account for you on the DRAW Server. This will be needed for the client to securely connect to the server. OM data. Therefore a set of tasks is defined by default which are started when you start the celery worker and celery beat in the steps noted above. 

The two key tasks that are pre-defined are:

1. dicom-export: Set to run every 5 minutes
2. dicom-import: Set to rune every 3 minutes. 

![Task Definition](screenshots/task_defination.png)

To view and modify the task please navigate to the Django admin interface and go to the Periodic Tasks section. 

![Periodic Tasks](screenshots/periodic_tasks.png)

Note that we recommend that these tasks are modified by users with administrative privileges only. 


# Manual Autosegmentation Template Association

While the system is designed to automatically handle DICOM some or all of the files may be handled manually. This can be done for any series and thus you can use this to segment a specific series manually. 

In order to trigger automatic segmentation using a template manually please go to the Processing Status page. 

![Manual Segmentation](screenshots/manual_segmentation.png)

Search or filter the case you wish to send for segmentation and select the case by clicking on the checkbox. After that a Button called Manual Autosegmentation will appear. Click this button which will open a modal dialog where you can setup the autosegmentation template for each case separately and click the Start Processing button to start the segmentation. 

![Template Selection](screenshots/template_selection.png)


# Segmentation Status

The Segmentation status is displayed in the Processing Status page. This will be updated with information retrieved from the server. When the processing is completed, you will seee a **RT Structure Exported** as the Processing status which indicates that the segmentation is completed. 

![Processing Status](screenshots/processing_status.png)

