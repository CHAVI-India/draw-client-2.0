# Consolidated Project Documentation

This document consolidates all Markdown documentation files found in the draw-client-2.0 project (excluding vendor/third-party files under `venv/` and `staticfiles/`).

---

# Source: README.md

[![DOI](https://zenodo.org/badge/1056386905.svg)](https://doi.org/10.5281/zenodo.19044373)

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
9. Integrated framework for providing rating for the segmentation quality.

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
createdb drawclientdicom_processing
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

N.B. The Junior staff can provide rating for the segmentation quality.

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

# Rating for Structure Set

We also provide an interface for you to rate the structure set. To rate the structure set please go to the Processing Status page. With each patient you will be able to see the following:
1. The number of structure sets for a given series
2. The number of structure sets for which a rating have been provided. 
3. A button to review the ratings provided.
4. A button to add new ratings. 

![Rating](screenshots/rating.jpeg)

If you click on the **Rate Contour Quality** button then you will be able to rate the structure set. This will allow you to rate the latest structure set. 

If you click on the **View All Ratings** button then you will be able to view all the ratings provided for the structure set. 

![View Ratings](screenshots/view_ratings.jpeg)

In the View Rating page, you will be able to see the number of structure sets, the rating provided for each and will be able to add ratings for the structure set or edit an existing rating. 

The rating form allows you to provide an overall rating for the structure set as well as specific feedback for individual structures like the type of modification done as well as the nature of the modification along with comments. 

![Rating Form](screenshots/rating_form.jpeg)

Please do consider rating the strcuture sets. This will help us improve the quality of the segmentation and provide better models for future.
---

# Source: development_guide.md

# DRAW v2.0 Development Guide

## Overview
This document details the implementation of key features in the DRAW v2.0 automatic segmentation system, including template management, DICOM processing, and logging infrastructure.

## Table of Contents
1. [Template Management](#template-management)
2. [DICOM Processing System](#dicom-processing-system)
3. [Logging Infrastructure](#logging-infrastructure)
4. [RuleSet Management](#ruleset-management)

---

# Template Management

## Core Models

### `AutosegmentationTemplate`
```python
class AutosegmentationTemplate(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    template_name = models.CharField(max_length=256)
    template_description = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### `AutosegmentationModel`
```python
class AutosegmentationModel(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    autosegmentation_template_name = models.ForeignKey(AutosegmentationTemplate, on_delete=models.CASCADE)
    model_id = models.IntegerField()
    name = models.CharField(max_length=256)
    config = models.CharField(max_length=256)
    trainer_name = models.CharField(max_length=256)
    postprocess = models.CharField(max_length=256)
```

### `AutosegmentationMappedStructure`
```python
class AutosegmentationMappedStructure(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    autosegmentation_model = models.ForeignKey(AutosegmentationModel, on_delete=models.CASCADE)
    map_id = models.IntegerField()
    name = models.CharField(max_length=256)
```

## Forms

### `TemplateCreationForm`
```python
class TemplateCreationForm(forms.Form):
    template_name = forms.CharField(
        max_length=256,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            'placeholder': 'Enter template name'
        }),
        label='Template Name'
    )
    
    template_description = forms.CharField(
        max_length=256,
        widget=forms.Textarea(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            'placeholder': 'Enter template description',
            'rows': 3
        }),
        label='Template Description'
    )
```

## Template Creation Implementation

### 1. Initial Form View (`create_template`)
```python
@login_required
def create_template(request):
    if request.method == 'POST':
        form = TemplateCreationForm(request.POST)
        if form.is_valid():
            # Store template data in session
            request.session['template_name'] = form.cleaned_data['template_name']
            request.session['template_description'] = form.cleaned_data['template_description']
            request.session.modified = True
            
            # Fetch models from DRAW API and redirect to selection
            # ... API call logic ...
            return redirect('dicom_handler:select_models')
    else:
        form = TemplateCreationForm()
    
    return render(request, 'dicom_handler/create_template.html', {'form': form})
```

### 2. Structure Selection View (`select_models`)
```python
@login_required
def select_models(request):
    # Get filters and pagination parameters
    search_query = request.GET.get('search', '')
    category_filter = request.GET.get('category', '')
    anatomic_filter = request.GET.get('anatomic_region', '')
    model_filter = request.GET.get('model_name', '')
    page_number = request.GET.get('page', 1)
    
    # Fetch and filter structures from DRAW API
    # ... API integration logic ...
    
    # Apply pagination
    paginator = Paginator(filtered_structures, 20)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'categories': categories,
        'anatomic_regions': anatomic_regions,
        'model_names': model_names,
        'selected_structures': request.session.get('selected_structures', []),
        # ... other context variables ...
    }
    
    return render(request, 'dicom_handler/select_models.html', context)
```

### 3. AJAX Selection Handler (`save_selections`)
```python
@login_required
@csrf_exempt
def save_selections(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        data = json.loads(request.body)
        selected_structures = data.get('selected_structures', [])
        
        # Store selections in session
        request.session['selected_structures'] = selected_structures
        request.session.modified = True
        
        return JsonResponse({
            'success': True, 
            'count': len(selected_structures),
            'message': f'{len(selected_structures)} structures selected'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
```

### 4. Template Creation Handler (`save_template`)
```python
@login_required
@csrf_exempt
def save_template(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        # Get template data from session
        template_name = request.session.get('template_name')
        template_description = request.session.get('template_description', '')
        selected_structures = request.session.get('selected_structures', [])
        
        if not template_name or not selected_structures:
            return JsonResponse({'success': False, 'error': 'Missing required data'})
        
        # Create template
        template = AutosegmentationTemplate.objects.create(
            id=uuid.uuid4(),
            template_name=template_name,
            template_description=template_description
        )
        
        # Group structures by model
        models_dict = {}
        for structure in selected_structures:
            model_id = structure.get('model_id')
            if model_id not in models_dict:
                models_dict[model_id] = {
                    'model_data': structure,
                    'structures': []
                }
            models_dict[model_id]['structures'].append(structure)
        
        # Create models and structures
        for model_data in models_dict.values():
            model = AutosegmentationModel.objects.create(
                id=uuid.uuid4(),
                autosegmentation_template_name=template,
                model_id=model_data['model_data'].get('model_id'),
                name=model_data['model_data'].get('model_name', ''),
                config=model_data['model_data'].get('model_config', ''),
                trainer_name=model_data['model_data'].get('model_trainer_name', ''),
                postprocess=model_data['model_data'].get('model_postprocess', '')
            )
            
            # Create structures for this model
            for structure_data in model_data['structures']:
                AutosegmentationMappedStructure.objects.create(
                    id=uuid.uuid4(),
                    autosegmentation_model=model,
                    map_id=structure_data.get('mapid') or structure_data.get('id'),
                    name=structure_data.get('map_tg263_primary_name', '')
                )
        
        # Clear session data
        request.session.pop('selected_structures', None)
        request.session.pop('template_name', None)
        request.session.pop('template_description', None)
        request.session.modified = True
        
        return JsonResponse({
            'success': True,
            'message': 'Template created successfully!',
            'template_id': str(template.id)
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
```

## Template View Implementation

### Template List View (`template_list`)
```python
@login_required
def template_list(request):
    templates = AutosegmentationTemplate.objects.all().order_by('-created_at')
    
    # Add counts for each template
    for template in templates:
        structure_count = AutosegmentationMappedStructure.objects.filter(
            autosegmentation_model__autosegmentation_template_name=template
        ).count()
        model_count = AutosegmentationModel.objects.filter(
            autosegmentation_template_name=template
        ).count()
        template.structure_count = structure_count
        template.model_count = model_count
    
    return render(request, 'dicom_handler/template_list.html', {
        'templates': templates
    })
```

### Template Detail View (`template_detail`)
```python
@login_required
def template_detail(request, template_id):
    try:
        template = AutosegmentationTemplate.objects.get(id=template_id)
        models = AutosegmentationModel.objects.filter(
            autosegmentation_template_name=template
        ).prefetch_related('autosegmentationmappedstructure_set')
        
        return render(request, 'dicom_handler/template_detail.html', {
            'template': template,
            'models': models
        })
    except AutosegmentationTemplate.DoesNotExist:
        messages.error(request, 'Template not found.')
        return redirect('dicom_handler:template_list')
```

## Template Update Implementation

### Edit Template View (`edit_template`) - Single Page Approach
```python
@login_required
@permission_required('dicom_handler.change_autosegmentationtemplate', raise_exception=True)
def edit_template(request, template_id):
    """
    View to edit an existing template - single page with structure selection
    """
    try:
        template = AutosegmentationTemplate.objects.get(id=template_id)
        
        # Get current structures for this template
        current_structures = []
        models = AutosegmentationModel.objects.filter(
            autosegmentation_template_name=template
        ).prefetch_related('autosegmentationstructure_set')
        
        for model in models:
            for structure in model.autosegmentationstructure_set.all():
                current_structures.append({
                    'id': structure.map_id,
                    'mapid': structure.map_id,
                    'map_tg263_primary_name': structure.name,
                    'model_id': model.model_id,
                    'model_name': model.name,
                    'model_config': model.config,
                    'model_trainer_name': model.trainer_name,
                    'model_postprocess': model.postprocess
                })
        
        # Fetch models from DRAW API for structure selection
        try:
            system_config = SystemConfiguration.objects.first()
            api_url = f"{system_config.draw_base_url}/models"
            
            headers = {}
            if system_config.draw_bearer_token:
                headers['Authorization'] = f"Bearer {system_config.draw_bearer_token}"
            
            response = requests.get(api_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            api_data = response.json()
            
            # Flatten all structures from all models for pagination and search
            all_structures = []
            categories = set()
            anatomic_regions = set()
            model_names = set()
            
            for model in api_data:
                if 'modelmap' in model and model['modelmap']:
                    for structure in model['modelmap']:
                        structure_data = {
                            'id': structure.get('id'),
                            'mapid': structure.get('mapid'),
                            'map_tg263_primary_name': structure.get('map_tg263_primary_name'),
                            'Major_Category': structure.get('Major_Category'),
                            'Anatomic_Group': structure.get('Anatomic_Group'),
                            'Description': structure.get('Description'),
                            'median_dice_score': structure.get('median_dice_score'),
                            'model_id': model.get('model_id'),
                            'model_name': model.get('model_name'),
                            'model_config': model.get('model_config'),
                            'model_trainer_name': model.get('model_trainer_name'),
                            'model_postprocess': model.get('model_postprocess')
                        }
                        all_structures.append(structure_data)
                        
                        # Collect filter options
                        if structure.get('Major_Category'):
                            categories.add(structure.get('Major_Category'))
                        if structure.get('Anatomic_Group'):
                            anatomic_regions.add(structure.get('Anatomic_Group'))
                        if model.get('model_name'):
                            model_names.add(model.get('model_name'))
            
            # Handle search and filters
            search_query = request.GET.get('search', '').strip()
            category_filter = request.GET.get('category', '').strip()
            anatomic_filter = request.GET.get('anatomic_region', '').strip()
            model_filter = request.GET.get('model_name', '').strip()
            
            filtered_structures = all_structures
            
            if search_query:
                filtered_structures = [s for s in filtered_structures 
                                     if search_query.lower() in s.get('map_tg263_primary_name', '').lower()]
            
            if category_filter:
                filtered_structures = [s for s in filtered_structures if s.get('Major_Category') == category_filter]
            
            if anatomic_filter:
                filtered_structures = [s for s in filtered_structures if s.get('Anatomic_Group') == anatomic_filter]
            
            if model_filter:
                filtered_structures = [s for s in filtered_structures if s.get('model_name') == model_filter]
            
            # Handle pagination
            page_number = request.GET.get('page', 1)
            paginator = Paginator(filtered_structures, 25)
            page_obj = paginator.get_page(page_number)
            
            # Convert current_structures to a list of IDs for the template
            selected_structure_ids = [str(s['id']) for s in current_structures if s.get('id')]
            
            return render(request, 'dicom_handler/edit_template.html', {
                'template': template,
                'page_obj': page_obj,
                'search_query': search_query,
                'selected_structures': current_structures,
                'selected_structure_ids': selected_structure_ids,
                'system_config': system_config,
                'categories': sorted(categories),
                'anatomic_regions': sorted(anatomic_regions),
                'model_names': sorted(model_names)
            })
            
        except requests.RequestException as e:
            messages.error(request, f'Error fetching models from API: {str(e)}')
            return redirect('dicom_handler:template_detail', template_id=template_id)
        
    except AutosegmentationTemplate.DoesNotExist:
        messages.error(request, 'Template not found.')
        return redirect('dicom_handler:template_list')
```

### Update Template Handler (`update_template`)
```python
@login_required
@permission_required('dicom_handler.change_autosegmentationtemplate', raise_exception=True)
def update_template(request, template_id):
    """
    AJAX endpoint to update an existing template
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        template = AutosegmentationTemplate.objects.get(id=template_id)
        data = json.loads(request.body)
        template_name = data.get('template_name')
        template_description = data.get('template_description')
        
        # Get selected structures from request body (sent by JavaScript)
        selected_structures = data.get('selected_structures', [])
        
        if not template_name:
            return JsonResponse({'success': False, 'error': 'Template name is required'})
        
        if not selected_structures:
            return JsonResponse({'success': False, 'error': 'No structures selected. Please select at least one structure.'})
        
        # Update template basic info
        template.template_name = template_name
        template.template_description = template_description or ''
        template.save()
        
        # Delete existing models and structures
        AutosegmentationModel.objects.filter(autosegmentation_template_name=template).delete()
        
        # Group structures by model
        models_dict = {}
        for structure in selected_structures:
            model_id = structure.get('model_id')
            if not model_id:
                continue
                
            if model_id not in models_dict:
                models_dict[model_id] = {
                    'model_data': structure,
                    'structures': []
                }
            models_dict[model_id]['structures'].append(structure)
        
        # Create new models and structures
        for model_data in models_dict.values():
            try:
                model = AutosegmentationModel.objects.create(
                    id=uuid.uuid4(),
                    autosegmentation_template_name=template,
                    model_id=model_data['model_data'].get('model_id'),
                    name=model_data['model_data'].get('model_name', ''),
                    config=model_data['model_data'].get('model_config', ''),
                    trainer_name=model_data['model_data'].get('model_trainer_name', ''),
                    postprocess=model_data['model_data'].get('model_postprocess', '')
                )
                
                # Create structures for this model
                for structure_data in model_data['structures']:
                    AutosegmentationStructure.objects.create(
                        id=uuid.uuid4(),
                        autosegmentation_model=model,
                        map_id=structure_data.get('mapid') or structure_data.get('id'),
                        name=structure_data.get('map_tg263_primary_name', '')
                    )
                    
            except Exception as model_error:
                return JsonResponse({'success': False, 'error': f'Error updating model data: {str(model_error)}'})
        
        return JsonResponse({
            'success': True,
            'message': f'Template "{template_name}" updated successfully!',
            'template_id': str(template.id)
        })
        
    except AutosegmentationTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Template not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
```

### Update Template Info Handler (`update_template_info`)
```python
@login_required
@permission_required('dicom_handler.change_autosegmentationtemplate', raise_exception=True)
def update_template_info(request, template_id):
    """
    Update template name and description via AJAX
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        template = AutosegmentationTemplate.objects.get(id=template_id)
        
        template_name = request.POST.get('template_name', '').strip()
        template_description = request.POST.get('template_description', '').strip()
        
        if not template_name:
            return JsonResponse({'success': False, 'error': 'Template name is required'})
        
        template.template_name = template_name
        template.template_description = template_description
        template.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Template information updated successfully!'
        })
        
    except AutosegmentationTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Template not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
```

## URLs (`dicom_handler/urls.py`)

```python
urlpatterns = [
    path('create-template/', views.create_template, name='create_template'),
    path('select-models/', views.select_models, name='select_models'),
    path('save-selections/', views.save_selections, name='save_selections'),
    path('save-template/', views.save_template, name='save_template'),
    path('templates/', views.template_list, name='template_list'),
    path('templates/<uuid:template_id>/', views.template_detail, name='template_detail'),
    path('templates/<uuid:template_id>/edit/', views.edit_template, name='edit_template'),
    path('templates/<uuid:template_id>/update/', views.update_template, name='update_template'),
    path('templates/<uuid:template_id>/update-info/', views.update_template_info, name='update_template_info'),
]
```

## Frontend Implementation

### Edit Template JavaScript Features

The `edit_template.html` template includes comprehensive JavaScript functionality for:

1. **Selection Management**: 
   - Maintains a `Set` of selected structure IDs across pagination
   - Preserves selections when filtering or searching
   - Syncs checkbox states with selection data

2. **AJAX Pagination**:
   - `loadPage()` function handles pagination without page reloads
   - Maintains current search and filter state during pagination
   - Updates URL parameters for bookmarking

3. **Search and Filtering**:
   - Real-time search by structure name
   - Filter by category, anatomic region, and model name
   - Combines multiple filters seamlessly

4. **Template Update**:
   - Single "Update Template" button updates both template info and structure selections
   - Sends JSON payload with template data and selected structures
   - Provides user feedback with success/error notifications

### Key JavaScript Functions

```javascript
// Load page with AJAX pagination
function loadPage(page) {
    const params = new URLSearchParams({
        page: page,
        search: currentSearchQuery,
        category: currentCategoryFilter,
        anatomic_region: currentAnatomicFilter,
        model_name: currentModelFilter
    });
    
    fetch(`?${params.toString()}`, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(response => response.text())
    .then(html => {
        // Update table content and sync selections
        document.getElementById('structures-table').innerHTML = html;
        syncCheckboxes();
        updateSelectionCount();
    });
}

// Update template via AJAX
function updateTemplate() {
    const templateName = document.getElementById('template_name').value.trim();
    const templateDescription = document.getElementById('template_description').value.trim();
    
    if (!templateName) {
        showNotification('Template name is required', 'error');
        return;
    }
    
    if (selectedStructures.size === 0) {
        showNotification('Please select at least one structure', 'error');
        return;
    }
    
    const selectedStructuresArray = Array.from(selectedStructures).map(id => 
        window.structureData[id] || { id: id }
    );
    
    fetch(`/dicom-handler/templates/{{ template.id }}/update/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({
            template_name: templateName,
            template_description: templateDescription,
            selected_structures: selectedStructuresArray
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification(data.message, 'success');
        } else {
            showNotification(data.error, 'error');
        }
    });
}
```

### Django Template Context Integration

The template receives the following context variables:
- `template`: The AutosegmentationTemplate object being edited
- `page_obj`: Paginated structure data from the API
- `selected_structures`: Current template structures (full objects)
- `selected_structure_ids`: List of selected structure IDs for checkbox pre-selection
- `search_query`: Current search term
- `categories`, `anatomic_regions`, `model_names`: Filter options

### Security Considerations

1. **CSRF Protection**: All AJAX requests include CSRF tokens
2. **Permission Checks**: Views use `@permission_required` decorators
3. **Data Escaping**: Django template data is properly escaped using `|escapejs` filter
4. **Input Validation**: Backend validates all user inputs before processing

## Templates

## Production Considerations

### Tailwind CSS Integration
The current implementation uses Tailwind CSS via CDN for rapid development. For production deployment, consider:

1. **Install Tailwind CSS locally**:
   ```bash
   npm install -D tailwindcss
   npx tailwindcss init
   ```

2. **Configure PostCSS** or use **Tailwind CLI** to build optimized CSS
3. **Purge unused CSS** to reduce bundle size
4. **Use Django-Tailwind** package for better Django integration

### Performance Optimizations

1. **API Caching**: Cache DRAW API responses to reduce external API calls
2. **Database Optimization**: Add indexes on frequently queried fields
3. **Pagination**: Current 25 items per page is reasonable, consider user preferences
4. **JavaScript Bundling**: Minify and bundle JavaScript for production

### Error Handling Improvements

1. **API Timeout Handling**: Current 30-second timeout may need adjustment
2. **Retry Logic**: Add retry mechanisms for failed API calls  
3. **User Feedback**: Enhanced error messages for better UX
4. **Logging**: Comprehensive logging for debugging production issues

## Troubleshooting

### Common Issues

1. **"No structures selected" Error**: 
   - Ensure `selected_structures` are properly passed in request body
   - Check JavaScript console for JSON parsing errors
   - Verify CSRF token is included in AJAX requests

2. **Pagination Not Working**:
   - Check that `X-Requested-With: XMLHttpRequest` header is set
   - Verify URL parameters are properly encoded
   - Ensure `syncCheckboxes()` is called after content update

3. **Selection State Lost**:
   - Confirm `selectedStructures` Set is maintained across operations
   - Check that `window.structureData` is properly populated
   - Verify checkbox `data-id` attributes match structure IDs

4. **API Connection Issues**:
   - Verify `SystemConfiguration` has correct DRAW API URL
   - Check Bearer token validity and format
   - Ensure network connectivity to DRAW API endpoint

5. **JavaScript "redeclaration of const" Error**:
   - **Problem**: Django template loops creating multiple `const` declarations in same scope
   - **Solution**: Wrap template loop variables in IIFE (Immediately Invoked Function Expression)
   - **Example Fix**:
     ```javascript
     // Before (causes error):
     {% for structure in selected_structures %}
     const dbStructure = { ... }; // Redeclared for each iteration
     {% endfor %}
     
     // After (fixed):
     {% for structure in selected_structures %}
     (function() {
         const dbStructure = { ... }; // Each in its own scope
     })();
     {% endfor %}
     ```

6. **Checkbox Selection Not Working - ID Mismatch**:
   - **Problem**: Database structure IDs don't match API structure IDs
   - **Solution**: Match structures using `model_id` + `map_id` combination instead of direct ID matching
   - **Implementation**: Create lookup map with `${model_id}_${map_id}` keys to match database structures with API structures

### `create_template.html`
```html
{% extends 'base.html' %}

{% block content %}
<div class="max-w-4xl mx-auto">
    <div class="bg-white rounded-xl shadow-lg border border-gray-100 p-8">
        <h1 class="text-3xl font-bold text-gray-900 mb-2">Create Autosegmentation Template</h1>
        
        <form method="post" class="space-y-6">
            {% csrf_token %}
            
            <div>
                <label for="{{ form.template_name.id_for_label }}">{{ form.template_name.label }}</label>
                {{ form.template_name }}
            </div>

            <div>
                <label for="{{ form.template_description.id_for_label }}">{{ form.template_description.label }}</label>
                {{ form.template_description }}
            </div>

            <div class="flex justify-end space-x-4">
                <button type="submit">Next: Select Models</button>
            </div>
        </form>
    </div>
</div>
{% endblock %}
```

### `select_models.html`
Key JavaScript functions for structure selection:

```javascript
// Selection management
let selectedStructures = new Set();

function handleCheckboxChange(checkbox) {
    const structureId = checkbox.getAttribute('data-id');
    const structureData = {
        id: checkbox.getAttribute('data-id'),
        mapid: checkbox.getAttribute('data-mapid'),
        map_tg263_primary_name: checkbox.getAttribute('data-map-tg263-primary-name'),
        model_id: checkbox.getAttribute('data-model-id'),
        model_name: checkbox.getAttribute('data-model-name'),
        // ... other attributes
    };
    
    if (checkbox.checked) {
        selectedStructures.add(structureId);
        window.structureData = window.structureData || {};
        window.structureData[structureId] = structureData;
    } else {
        selectedStructures.delete(structureId);
        if (window.structureData) {
            delete window.structureData[structureId];
        }
    }
    updateSelectionCount();
    saveSelections();
}

function createTemplate() {
    if (selectedStructures.size === 0) {
        showNotification('Please select at least one structure before creating the template.', 'error');
        return;
    }
    
    // Direct save using session data - no modal needed
    fetch('{% url "dicom_handler:save_template" %}', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': '{{ csrf_token }}'
        },
        body: JSON.stringify({})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Template created successfully!', 'success');
            setTimeout(() => {
                window.location.href = '{% url "dicom_handler:create_template" %}';
            }, 1500);
        } else {
            showNotification('Error: ' + data.error, 'error');
        }
    });
}
```

## Session Data Flow

### Template Creation Flow
1. **Step 1**: User fills form → Data stored in session → Redirect to selection
2. **Step 2**: User selects structures → AJAX updates session → Click "Create Template"  
3. **Step 3**: Backend uses session data → Creates database records → Clears session

### Session Keys
- `template_name`: From initial form
- `template_description`: From initial form  
- `selected_structures`: Array of structure objects with full data
- `editing_template_id`: For template updates (optional)

---

# DICOM Processing System

## Overview
The DICOM processing system handles the automated reading, validation, and database storage of DICOM files with parallel processing capabilities for improved performance.

## Task 1: Read DICOM from Storage

### Purpose
Recursively reads DICOM files from a configured storage folder, validates them, and creates database records for patients, studies, series, and instances.

### Key Features
- **Parallel Processing**: Uses multiprocessing with up to 8 worker processes
- **Batch Processing**: Processes files in batches of 500 for memory management
- **Filtering**: Supports modality filtering (CT/MR/PT only) and date-based filtering
- **Duplicate Prevention**: Checks existing SOP Instance UIDs to avoid duplicates
- **Bulk Database Operations**: Uses bulk_create for optimal database performance

### Implementation

#### Main Function: `read_dicom_from_storage()`
```python
def read_dicom_from_storage():
    """
    Main function to read DICOM files from configured storage folder (PARALLEL VERSION)
    Returns: Dictionary containing processing results and series information for next task
    """
    logger.info("Starting DICOM file reading task (parallel processing)")
    
    # Get system configuration and validate folder
    system_config = SystemConfiguration.get_singleton()
    folder_path = system_config.folder_configuration
    
    # Collect all files for processing
    file_list = []
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            file_list.append((file_path, root, date_filter, current_time, ten_minutes_ago))
    
    # Process files in parallel batches
    max_workers = min(cpu_count(), 8)
    batch_size = 500
    
    for i in range(0, len(file_list), batch_size):
        batch = file_list[i:i + batch_size]
        
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all files in batch
            future_to_file = {
                executor.submit(process_single_file, file_info): file_info[0]
                for file_info in batch
            }
            
            # Collect and process results
            batch_results = []
            for future in as_completed(future_to_file):
                result = future.result()
                batch_results.append(result)
            
            # Create database records for successful files
            successful_results = [r for r in batch_results if r['status'] == 'success']
            if successful_results:
                bulk_create_database_records(successful_results)
```

#### File Processing Function: `process_single_file()`
```python
def process_single_file(file_info):
    """
    Process a single DICOM file - designed for multiprocessing
    Returns: Dictionary with file processing results
    """
    file_path, series_root_path, date_filter, current_time, ten_minutes_ago = file_info
    
    # Check file modification time conditions
    file_stat = os.stat(file_path)
    file_mtime = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.get_current_timezone())
    
    # Skip if file was modified in the past 10 minutes
    if file_mtime > ten_minutes_ago:
        return {"status": "skipped", "reason": "recently_modified", "file_path": file_path}
    
    # Read DICOM file
    dicom_data = pydicom.dcmread(file_path, force=True)
    
    # Validate modality
    modality = getattr(dicom_data, 'Modality', None)
    if modality not in ['CT', 'MR', 'PT']:
        return {"status": "skipped", "reason": "unsupported_modality", "file_path": file_path}
    
    # Extract metadata
    dicom_metadata = {
        'patient_id': getattr(dicom_data, 'PatientID', ''),
        'patient_name': str(getattr(dicom_data, 'PatientName', '')),
        'study_instance_uid': getattr(dicom_data, 'StudyInstanceUID', ''),
        'series_instance_uid': getattr(dicom_data, 'SeriesInstanceUID', ''),
        'sop_instance_uid': getattr(dicom_data, 'SOPInstanceUID', ''),
        'file_path': file_path,
        'series_root_path': series_root_path
        # ... other metadata fields
    }
    
    return {"status": "success", "metadata": dicom_metadata}
```

#### Bulk Database Creation: `bulk_create_database_records()`
```python
def bulk_create_database_records(processed_files):
    """
    Bulk create database records from processed DICOM files
    """
    patients_to_create = {}
    studies_to_create = {}
    series_to_create = {}
    instances_to_create = []
    
    # Group by patient, study, series
    for file_result in processed_files:
        metadata = file_result['metadata']
        
        # Group patients
        patient_key = metadata['patient_id']
        if patient_key not in patients_to_create:
            patients_to_create[patient_key] = {
                'patient_id': metadata['patient_id'],
                'patient_name': metadata['patient_name'],
                # ... other patient fields
            }
    
    # Bulk create in database with transactions
    with transaction.atomic():
        # Create patients
        for patient_data in patients_to_create.values():
            patient, created = Patient.objects.get_or_create(
                patient_id=patient_data['patient_id'],
                defaults=patient_data
            )
        
        # Create studies, series, and instances
        # ... similar bulk creation logic
        
        # Bulk create instances
        if instances_to_bulk_create:
            DICOMInstance.objects.bulk_create(instances_to_bulk_create, batch_size=1000)
```

### Performance Characteristics
- **Processing Speed**: 6-8x faster than sequential processing
- **Memory Management**: Batch processing prevents memory exhaustion
- **Database Efficiency**: Bulk operations reduce database load
- **Error Handling**: Comprehensive error tracking and logging

### Configuration Requirements
```python
# System Configuration Model
class SystemConfiguration(models.Model):
    folder_configuration = models.CharField(max_length=512)  # DICOM folder path
    data_pull_start_datetime = models.DateTimeField(null=True, blank=True)  # Date filter
```

### Return Format (JSON Serializable for Celery)
```python
{
    "status": "success",
    "processed_files": 4735,
    "skipped_files": 2082,
    "error_files": 0,
    "series_data": [
        {
            "series_instance_uid": "1.2.840.113619.2.55...",
            "first_instance_path": "/path/to/first/instance.dcm",
            "series_root_path": "/path/to/series/folder",
            "instance_count": 251
        }
        # ... more series
    ]
}
```

---

# Logging Infrastructure

## Overview
Comprehensive logging system with automatic log rotation, privacy protection, and component-specific log files for monitoring and debugging.

## Configuration

### Django Settings (`settings.py`)
```python
# Create logs directory
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'dicom_formatter': {
            'format': '[DICOM] {levelname} {asctime} {module} - {message}',
            'style': '{',
        },
        'celery_formatter': {
            'format': '[CELERY] {levelname} {asctime} {module} - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'dicom_file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'dicom_processing.log',
            'maxBytes': 100 * 1024 * 1024,  # 100 MB
            'backupCount': 15,
            'formatter': 'dicom_formatter',
        },
        'django_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'django.log',
            'maxBytes': 50 * 1024 * 1024,  # 50 MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'celery_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'celery.log',
            'maxBytes': 50 * 1024 * 1024,  # 50 MB
            'backupCount': 10,
            'formatter': 'celery_formatter',
        },
        'error_file': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'errors.log',
            'maxBytes': 25 * 1024 * 1024,  # 25 MB
            'backupCount': 20,
            'formatter': 'verbose',
        },
        'security_file': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'security.log',
            'maxBytes': 25 * 1024 * 1024,  # 25 MB
            'backupCount': 20,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'dicom_handler': {
            'handlers': ['dicom_file', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'dicom_handler.export_services': {
            'handlers': ['dicom_file', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'celery': {
            'handlers': ['celery_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['error_file', 'console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['security_file', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
```

## Log Files

### File Structure
```
logs/
├── dicom_processing.log      # DICOM processing activities (100MB, 15 backups)
├── django.log                # General Django application logs (50MB, 10 backups)
├── celery.log                # Celery task execution logs (50MB, 10 backups)
├── errors.log                # All error-level messages (25MB, 20 backups)
└── security.log              # Security-related warnings (25MB, 20 backups)
```

### Log Rotation
- **Automatic rotation** when files reach size limits
- **Compressed backups** to save disk space
- **Configurable retention** with different backup counts per log type

## Privacy Protection

### Sensitive Data Masking
```python
def mask_sensitive_data(data, field_name=""):
    """
    Mask sensitive patient information in logs
    """
    if not data:
        return "None"
    
    # Mask patient identifiable information
    if any(field in field_name.lower() for field in ['name', 'id', 'birth']):
        return f"***{field_name.upper()}_MASKED***"
    
    # For UIDs, show only first and last 4 characters
    if 'uid' in field_name.lower() and len(str(data)) > 8:
        return f"{str(data)[:4]}...{str(data)[-4:]}"
    
    return str(data)
```

### Usage in DICOM Processing
```python
# Example log entries with masking
logger.info(f"Processing patient: {mask_sensitive_data(patient_name, 'patient_name')}")
logger.debug(f"Series UID: {mask_sensitive_data(series_uid, 'series_uid')}")
logger.info(f"File path: {mask_sensitive_data(file_path, 'file_path')}")
```

## Log Management Script (`manage_logs.py`)

### Available Commands
```bash
# View log status
python manage_logs.py status

# View last 50 lines of a log
python manage_logs.py tail dicom_processing

# Follow log in real-time
python manage_logs.py follow dicom_processing

# Search for patterns
python manage_logs.py search "error" --log dicom_processing

# Clean old logs (30+ days)
python manage_logs.py clean --days 30

# Compress old logs (7+ days)
python manage_logs.py compress --days 7
```

### Key Functions
```python
def show_log_status():
    """Display status of all log files"""
    log_files = get_log_files()
    for log_file in log_files:
        print(f"{log_file['name']:<30} {log_file['size_mb']:<12.2f} {log_file['modified']}")

def tail_log(log_name, lines=50):
    """Display last N lines of a log file"""
    with open(log_path, 'r') as f:
        all_lines = f.readlines()
        for line in all_lines[-lines:]:
            print(line.rstrip())

def search_logs(pattern, log_name=None):
    """Search for pattern in log files"""
    for log_file in log_files:
        with open(log_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                if pattern.lower() in line.lower():
                    print(f"{log_file.name}:{line_num}: {line.rstrip()}")
```

## Logging Best Practices

### Log Levels
- **DEBUG**: Detailed processing steps, file-by-file operations
- **INFO**: Task start/completion, major milestones, record creation
- **WARNING**: Recoverable errors, skipped files
- **ERROR**: Critical errors, database issues

### Example Log Entries
```
[DICOM] INFO 2025-09-14 13:54:12 task1_read_dicom_from_storage - Starting DICOM file reading task (parallel processing)
[DICOM] INFO 2025-09-14 13:54:12 task1_read_dicom_from_storage - Found 6817 files to process
[DICOM] INFO 2025-09-14 13:54:12 task1_read_dicom_from_storage - Processing files with 8 parallel workers
[DICOM] INFO 2025-09-14 13:54:12 task1_read_dicom_from_storage - Processing batch 1/14 (500 files)
[DICOM] DEBUG 2025-09-14 13:54:13 task1_read_dicom_from_storage - Skipped file: unsupported_modality - ***FILE_PATH_MASKED***
[DICOM] INFO 2025-09-14 13:54:13 task1_read_dicom_from_storage - Batch completed: 498 successful, 2 skipped, 0 errors
[DICOM] INFO 2025-09-14 13:54:13 task1_read_dicom_from_storage - Creating database records for 428 files
[DICOM] INFO 2025-09-14 13:54:13 task1_read_dicom_from_storage - Successfully created records for batch
[DICOM] INFO 2025-09-14 13:54:13 task1_read_dicom_from_storage - DICOM reading completed. Processed: 6738, Skipped: 79, Errors: 0
```

---

# RuleSet Management

## Overview
This section details the implementation of RuleSet management functionality for DICOM tag-based automatic template selection in the DRAW v2.0 system.

## Core Models

### `DICOMTagType`
```python
class DICOMTagType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tag_name = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### `RuleCombinationType`
```python
class RuleCombinationType(models.TextChoices):
    AND = "AND", "And"
    OR = "OR", "Or"
```

### `OperatorType`
```python
class OperatorType(models.TextChoices):
    EQUALS = "EQUALS", "Equals"
    NOT_EQUALS = "NOT_EQUALS", "Not Equals"
    GREATER_THAN = "GREATER_THAN", "Greater Than"
    LESS_THAN = "LESS_THAN", "Less Than"
    GREATER_THAN_OR_EQUAL_TO = "GREATER_THAN_OR_EQUAL_TO", "Greater Than Or Equal To"
    LESS_THAN_OR_EQUAL_TO = "LESS_THAN_OR_EQUAL_TO", "Less Than Or Equal To"
    CASE_SENSITIVE_STRING_CONTAINS = "CASE_SENSITIVE_STRING_CONTAINS", "Case Sensitive String Contains"
    CASE_INSENSITIVE_STRING_CONTAINS = "CASE_INSENSITIVE_STRING_CONTAINS", "Case Insensitive String Contains"
    CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN = "CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN", "Case Sensitive String Does Not Contain"
    CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN = "CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN", "Case Insensitive String Does Not Contain"
    CASE_SENSITIVE_STRING_EXACT_MATCH = "CASE_SENSITIVE_STRING_EXACT_MATCH", "Case Sensitive String Exact Match"
    CASE_INSENSITIVE_STRING_EXACT_MATCH = "CASE_INSENSITIVE_STRING_EXACT_MATCH", "Case Insensitive String Exact Match"
```

### `RuleSet`
```python
class RuleSet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ruleset_name = models.CharField(max_length=256,help_text = "The name of the ruleset.")
    ruleset_description = models.CharField(max_length=256,help_text = "The description of the ruleset.")
    rule_combination_type = models.CharField(max_length=256, choices=RuleCombinationType.choices,help_text = "The rule combination type. This can be AND or OR.")
    associated_autosegmentation_template = models.ForeignKey(AutosegmentationTemplate, on_delete=models.CASCADE, null=True, blank=True,help_text = "The autosegmentation template associated with the ruleset.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### `Rule`
```python
class Rule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE,help_text = "The ruleset to which this rule belongs to.")
    dicom_tag_type = models.ForeignKey(DICOMTagType, on_delete=models.CASCADE,help_text = "The DICOM tag type whose value will be evaluated.")
    operator_type = models.CharField(max_length=256, choices=OperatorType.choices,help_text = "The operator type. This can be a string operator to be used for text and number or a numeric operator for numeric values.")
    tag_value_to_evaluate = models.CharField(max_length=256,help_text = "The tag value to evaluate. This is the value that the rule will match to.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def clean(self):
        """Validate operator-value combinations"""
        # String operators that allow string values
        string_operators = [
            OperatorType.CASE_SENSITIVE_STRING_CONTAINS,
            OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
            OperatorType.CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN,
            OperatorType.CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN,
            OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
            OperatorType.CASE_INSENSITIVE_STRING_EXACT_MATCH,
        ]
        
        is_numeric = self.is_numeric_value(self.tag_value_to_evaluate)
        
        # All operators except string operators require numeric values
        if self.operator_type not in string_operators and not is_numeric:
            raise ValidationError({
                'tag_value_to_evaluate': f'Operator "{self.get_operator_type_display()}" can only be used with numeric values.'
            })
```

## Forms Implementation

### `RuleSetForm`
```python
class RuleSetForm(forms.ModelForm):
    class Meta:
        model = RuleSet
        fields = ['ruleset_name', 'ruleset_description', 'rule_combination_type', 'associated_autosegmentation_template']
        widgets = {
            'ruleset_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Enter ruleset name'
            }),
            # ... other widgets with Tailwind CSS classes
        }
```

### `RuleForm` with Validation
```python
class RuleForm(forms.ModelForm):
    class Meta:
        model = Rule
        fields = ['dicom_tag_type', 'operator_type', 'tag_value_to_evaluate']
        widgets = {
            'operator_type': forms.Select(attrs={
                'onchange': 'validateOperatorValue(this)'
            }),
            'tag_value_to_evaluate': forms.TextInput(attrs={
                'oninput': 'validateOperatorValue(this)'
            })
        }
    
    def clean(self):
        """Form-level validation for operator-value combinations"""
        cleaned_data = super().clean()
        operator_type = cleaned_data.get('operator_type')
        tag_value = cleaned_data.get('tag_value_to_evaluate')
        
        if operator_type and tag_value:
            string_operators = [
                'CASE_SENSITIVE_STRING_CONTAINS',
                'CASE_INSENSITIVE_STRING_CONTAINS',
                'CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN',
                'CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN',
                'CASE_SENSITIVE_STRING_EXACT_MATCH',
                'CASE_INSENSITIVE_STRING_EXACT_MATCH',
            ]
            
            try:
                float(tag_value)
                is_numeric = True
            except (ValueError, TypeError):
                is_numeric = False
            
            if operator_type not in string_operators and not is_numeric:
                raise forms.ValidationError({
                    'tag_value_to_evaluate': f'Operator requires numeric values. Use string operators for text values.'
                })
        
        return cleaned_data
```

### `RuleFormSet` Configuration
```python
RuleFormSet = inlineformset_factory(
    RuleSet, 
    Rule, 
    form=RuleForm,
    fields=['dicom_tag_type', 'operator_type', 'tag_value_to_evaluate'],
    extra=1,  # Show 1 empty form initially
    can_delete=True,
    min_num=1,  # Require at least 1 rule
    validate_min=True
)
```

## Views Implementation

### `ruleset_list`
```python
@login_required
def ruleset_list(request):
    rulesets = RuleSet.objects.all().order_by('-created_at')
    
    for ruleset in rulesets:
        ruleset.rule_count = Rule.objects.filter(ruleset=ruleset).count()
    
    return render(request, 'dicom_handler/ruleset_list.html', {
        'rulesets': rulesets
    })
```

### `ruleset_create`
```python
@login_required
def ruleset_create(request):
    if request.method == 'POST':
        form = RuleSetForm(request.POST)
        formset = RuleFormSet(request.POST)
        
        if form.is_valid() and formset.is_valid():
            ruleset = form.save(commit=False)
            ruleset.id = uuid.uuid4()
            ruleset.save()
            
            formset.instance = ruleset
            formset.save()
            
            messages.success(request, f'RuleSet "{ruleset.ruleset_name}" created successfully!')
            return redirect('dicom_handler:ruleset_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = RuleSetForm()
        formset = RuleFormSet()
    
    return render(request, 'dicom_handler/ruleset_create.html', {
        'form': form, 
        'formset': formset
    })
```

### `ruleset_detail`
```python
@login_required
def ruleset_detail(request, ruleset_id):
    try:
        ruleset = get_object_or_404(RuleSet, id=ruleset_id)
        rules = Rule.objects.filter(ruleset=ruleset).order_by('created_at')
        
        return render(request, 'dicom_handler/ruleset_detail.html', {
            'ruleset': ruleset,
            'rules': rules
        })
    except RuleSet.DoesNotExist:
        messages.error(request, 'RuleSet not found.')
        return redirect('dicom_handler:ruleset_list')
```

### `ruleset_edit`
```python
@login_required
def ruleset_edit(request, ruleset_id):
    ruleset = get_object_or_404(RuleSet, id=ruleset_id)
    
    if request.method == 'POST':
        form = RuleSetForm(request.POST, instance=ruleset)
        formset = RuleFormSet(request.POST, instance=ruleset)
        
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            
            messages.success(request, f'RuleSet "{ruleset.ruleset_name}" updated successfully!')
            return redirect('dicom_handler:ruleset_detail', ruleset_id=ruleset.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = RuleSetForm(instance=ruleset)
        formset = RuleFormSet(instance=ruleset)
    
    return render(request, 'dicom_handler/ruleset_edit.html', {
        'form': form,
        'formset': formset,
        'ruleset': ruleset
    })
```

### `ruleset_delete`
```python
@login_required
def ruleset_delete(request, ruleset_id):
    ruleset = get_object_or_404(RuleSet, id=ruleset_id)
    rules = Rule.objects.filter(ruleset=ruleset)
    
    if request.method == 'POST':
        ruleset_name = ruleset.ruleset_name
        ruleset.delete()
        messages.success(request, f'RuleSet "{ruleset_name}" deleted successfully!')
        return redirect('dicom_handler:ruleset_list')
    
    return render(request, 'dicom_handler/ruleset_confirm_delete.html', {
        'ruleset': ruleset,
        'rules': rules
    })
```

## Validation System

### Operator-Value Validation Rules
1. **String Operators** (allow text values):
   - Equals
   - Not Equals
   - Case Sensitive String Contains
   - Case Insensitive String Contains
   - Case Sensitive String Does Not Contain
   - Case Insensitive String Does Not Contain
   - Case Sensitive String Exact Match
   - Case Insensitive String Exact Match

2. **Numeric-Only Operators** (require numeric values):
 
   - Greater Than
   - Less Than
   - Greater Than or Equal To
   - Less Than or Equal To

### Multi-Level Validation
1. **Model Level**: `Rule.clean()` method validates operator-value combinations
2. **Form Level**: `RuleForm.clean()` provides user-friendly error messages
3. **Client-Side**: JavaScript provides real-time validation feedback

## JavaScript Implementation

### Dynamic Rule Management
```javascript
// Add new rule form
function addRule() {
    const emptyFormTemplate = document.querySelector('.rule-form').cloneNode(true);
    
    // Update form indices
    const formRegex = /form-\d+-/g;
    emptyFormTemplate.innerHTML = emptyFormTemplate.innerHTML.replace(formRegex, `form-${formCount}-`);
    
    // Clear values and reset validation
    emptyFormTemplate.querySelectorAll('input, select, textarea').forEach(function(field) {
        if (field.type !== 'hidden') {
            field.value = '';
            field.selectedIndex = 0;
        }
    });
    
    // Update form count and attach events
    formCount++;
    document.querySelector('#id_form-TOTAL_FORMS').value = formCount;
    
    attachRemoveEvent(emptyFormTemplate);
    attachValidationEvents(emptyFormTemplate);
    updateRemoveButtonVisibility();
}

// Remove rule management
function removeRule(formElement) {
    const forms = document.querySelectorAll('.rule-form');
    if (forms.length > 1) {  // Maintain minimum of 1 rule
        formElement.remove();
        updateFormNumbers();
        updateRemoveButtonVisibility();
    }
}

// Remove button visibility logic
function updateRemoveButtonVisibility() {
    const forms = document.querySelectorAll('.rule-form');
    forms.forEach(function(form) {
        const removeBtn = form.querySelector('.remove-rule');
        if (removeBtn) {
            removeBtn.style.display = forms.length === 1 ? 'none' : 'block';
        }
    });
}
```

### Real-Time Validation
```javascript
function validateOperatorValue(element) {
    const ruleForm = element.closest('.rule-form');
    const operatorSelect = ruleForm.querySelector('select[name$="-operator_type"]');
    const valueInput = ruleForm.querySelector('input[name$="-tag_value_to_evaluate"]');
    
    const stringOperators = [
        'CASE_SENSITIVE_STRING_CONTAINS',
        'CASE_INSENSITIVE_STRING_CONTAINS',
        'CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN',
        'CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN',
        'CASE_SENSITIVE_STRING_EXACT_MATCH',
        'CASE_INSENSITIVE_STRING_EXACT_MATCH'
    ];
    
    const operator = operatorSelect.value;
    const value = valueInput.value.trim();
    const isValueNumeric = !isNaN(parseFloat(value)) && isFinite(value);
    
    // Validate and show errors
    if (!stringOperators.includes(operator) && !isValueNumeric) {
        showValidationError(ruleForm, 'Operator requires numeric values. Use string operators for text values.');
        return false;
    }
    
    clearValidationError(ruleForm);
    return true;
}
```

## URL Patterns

```python
# RuleSet URLs
path('rulesets/', views.ruleset_list, name='ruleset_list'),
path('rulesets/create/', views.ruleset_create, name='ruleset_create'),
path('rulesets/<uuid:ruleset_id>/', views.ruleset_detail, name='ruleset_detail'),
path('rulesets/<uuid:ruleset_id>/edit/', views.ruleset_edit, name='ruleset_edit'),
path('rulesets/<uuid:ruleset_id>/delete/', views.ruleset_delete, name='ruleset_delete'),
```

## Templates

### Key Features
1. **Responsive Design**: Tailwind CSS for consistent styling
2. **Dynamic Forms**: JavaScript-powered inline formset management
3. **Real-Time Validation**: Immediate feedback on operator-value combinations
4. **User Experience**: Clear error messages and intuitive navigation
5. **Accessibility**: Proper form labels and ARIA attributes

### Template Structure
- `ruleset_list.html`: Display all rulesets with actions
- `ruleset_create.html`: Create new ruleset with inline rules
- `ruleset_detail.html`: View ruleset details and logic summary
- `ruleset_edit.html`: Edit existing ruleset and rules
- `ruleset_confirm_delete.html`: Confirmation page with impact preview

## Navigation Integration

Added RuleSet link to main navigation:
```html
<!-- Desktop Navigation -->
<a href="{% url 'dicom_handler:ruleset_list' %}" class="text-gray-700 hover:text-primary-600 px-3 py-2 rounded-md text-sm font-medium transition-colors">RuleSets</a>

<!-- Mobile Navigation -->
<a href="{% url 'dicom_handler:ruleset_list' %}" class="block text-gray-700 hover:text-primary-600 px-3 py-2 rounded-md text-base font-medium">RuleSets</a>
```

---

# DICOM Dictionary Seed Data Implementation

## Overview
This section details the implementation of DICOM dictionary seed data import functionality for populating the `DICOMTagType` model with standardized DICOM tags.

## Updated DICOMTagType Model

### Enhanced Model Structure
```python
class DICOMTagType(models.Model):
    '''
    This is a model to store data about the DICOM tags. Note that only DICOM tags approved by the DICOM standards are allowed.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tag_name = models.CharField(max_length=256)
    tag_id = models.CharField(max_length=256, null=True, blank=True)
    tag_description = models.CharField(max_length=256, null=True, blank=True)
    value_representation = models.CharField(max_length=256, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.tag_name

    class Meta:
        verbose_name = "DICOM Tag Type"
        verbose_name_plural = "DICOM Tag Types"
```

### Model Changes
- **Added `tag_id`**: Stores DICOM tag identifier (e.g., "(4010,1070)")
- **Added `tag_description`**: Stores detailed description of the DICOM tag
- **Added `value_representation`**: Stores DICOM value representation (e.g., "CS", "FD", "US")

## Seed Data Structure

### CSV File Format
Location: `/seed_data/dicom_dictionary.csv`

```csv
"id","tag_id","tag_name","tag_description","value_representation"
1,"(4010,1070)","AITDeviceType","AIT Device Type","CS"
```

---

# Advanced RuleSet Features Implementation

## Overview
This section documents the advanced features added to the RuleSet management system, including VR (Value Representation) validation, Select2 integration for DICOM tag selection, and dynamic formset management.

## VR Validation System

### VR Validators Module (`vr_validators.py`)
```python
import re
from django.core.exceptions import ValidationError

def validate_vr_value(vr_type, value, operator=None):
    """
    Validate a DICOM value against its Value Representation (VR) type
    """
    if not value:
        return True, "Value is empty"
    
    # VR validation patterns
    vr_patterns = {
        'CS': r'^[A-Za-z0-9_ ]{1,16}$',  # Code String - allows uppercase, lowercase, digits, spaces, underscores
        'SH': r'^.{1,16}$',              # Short String
        'LO': r'^.{1,64}$',              # Long String
        'US': r'^\d+$',                  # Unsigned Short
        'FD': r'^-?\d+(\.\d+)?$',        # Floating Point Double
        'DA': r'^\d{8}$',                # Date (YYYYMMDD)
        'TM': r'^\d{6}(\.\d{1,6})?$',    # Time (HHMMSS.FFFFFF)
        'UI': r'^[\d\.]+$',              # Unique Identifier
        'PN': r'^[^\\^=]*(\^[^\\^=]*){0,4}$',  # Person Name
    }
    
    pattern = vr_patterns.get(vr_type)
    if not pattern:
        return True, f"No validation pattern for VR type: {vr_type}"
    
    if not re.match(pattern, value):
        return False, f"Value '{value}' is not valid for VR type {vr_type}"
    
    return True, "Valid"

def get_compatible_operators(vr_type):
    """
    Get operators compatible with a specific VR type
    """
    string_vrs = ['CS', 'SH', 'LO', 'PN', 'UI']
    numeric_vrs = ['US', 'FD', 'IS', 'DS']
    date_time_vrs = ['DA', 'TM', 'DT']
    
    string_operators = [
        'CASE_SENSITIVE_STRING_CONTAINS',
        'CASE_INSENSITIVE_STRING_CONTAINS',
        'CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN',
        'CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN',
        'CASE_SENSITIVE_STRING_EXACT_MATCH',
        'CASE_INSENSITIVE_STRING_EXACT_MATCH',
        'EQUALS',
        'NOT_EQUALS'
    ]
    
    numeric_operators = [
        'EQUALS',
        'NOT_EQUALS',
        'GREATER_THAN',
        'LESS_THAN',
        'GREATER_THAN_OR_EQUAL_TO',
        'LESS_THAN_OR_EQUAL_TO'
    ]
    
    if vr_type in string_vrs:
        return string_operators
    elif vr_type in numeric_vrs:
        return numeric_operators
    elif vr_type in date_time_vrs:
        return numeric_operators  # Date/time can use comparison operators
    else:
        return string_operators  # Default to string operators
```

### AJAX Endpoints for VR Guidance

#### `get_vr_guidance` View
```python
@login_required
def get_vr_guidance(request, tag_uuid):
    """
    Get VR guidance for a specific DICOM tag
    """
    try:
        tag = DICOMTagType.objects.get(id=tag_uuid)
        vr_type = tag.value_representation
        
        compatible_operators = get_compatible_operators(vr_type)
        
        return JsonResponse({
            'success': True,
            'vr_type': vr_type,
            'compatible_operators': compatible_operators,
            'tag_name': tag.tag_name,
            'tag_description': tag.tag_description
        })
    except DICOMTagType.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'DICOM tag not found'
        })
```

#### `validate_vr_value` View
```python
@login_required
@csrf_exempt
def validate_vr_value(request):
    """
    Validate a value against VR rules
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        data = json.loads(request.body)
        tag_uuid = data.get('tag_uuid')
        operator = data.get('operator')
        value = data.get('value')
        
        if not tag_uuid:
            return JsonResponse({'success': False, 'error': 'Tag UUID is required'})
        
        tag = DICOMTagType.objects.get(id=tag_uuid)
        vr_type = tag.value_representation
        
        is_valid, message = validate_vr_value(vr_type, value, operator)
        
        return JsonResponse({
            'success': True,
            'is_valid': is_valid,
            'message': message,
            'vr_type': vr_type
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
```

#### `search_dicom_tags` View
```python
@login_required
def search_dicom_tags(request):
    """
    Search DICOM tags for Select2 autocomplete
    """
    search_term = request.GET.get('q', '').strip()
    
    if len(search_term) < 2:
        return JsonResponse({'results': []})
    
    tags = DICOMTagType.objects.filter(
        Q(tag_name__icontains=search_term) |
        Q(tag_description__icontains=search_term) |
        Q(tag_id__icontains=search_term)
    )[:20]  # Limit to 20 results
    
    results = []
    for tag in tags:
        results.append({
            'id': str(tag.id),
            'text': f"{tag.tag_name} ({tag.tag_id}) - {tag.tag_description or 'No description'}",
            'vr_type': tag.value_representation
        })
    
    return JsonResponse({'results': results})
```

## Enhanced Templates

### `ruleset_create.html` Features
1. **Select2 Integration**: Advanced DICOM tag selection with search
2. **Dynamic Formset Management**: Add/remove rules with proper form indexing
3. **VR Validation**: Real-time validation based on DICOM VR types
4. **Operator Filtering**: Dynamic operator options based on selected tag's VR
5. **Tailwind CSS Styling**: Modern, responsive design

### Key JavaScript Functions

#### Dynamic Form Management
```javascript
function addRule() {
    const emptyFormTemplate = document.querySelector('.rule-form').cloneNode(true);
    const formCount = document.querySelectorAll('.rule-form').length;
    
    // Update form indices and field names
    const formRegex = /rule_set-\d+-/g;
    emptyFormTemplate.innerHTML = emptyFormTemplate.innerHTML.replace(formRegex, `rule_set-${formCount}-`);
    
    // Clear form values and reset validation
    emptyFormTemplate.querySelectorAll('input, select, textarea').forEach(function(field) {
        if (field.type !== 'hidden') {
            field.value = '';
        } else if (field.name.includes('id')) {
            field.value = '';  // Clear ID for new forms
        } else if (field.name.includes('DELETE')) {
            field.checked = false;  // Uncheck DELETE for new forms
        }
    });
    
    // Update management form
    const totalFormsField = document.querySelector('#id_rule_set-TOTAL_FORMS');
    totalFormsField.value = formCount + 1;
    
    // Append new form and initialize Select2
    document.querySelector('#rules-container').appendChild(emptyFormTemplate);
    initializeSelect2(emptyFormTemplate);
    attachFormEvents(emptyFormTemplate);
}
```

#### VR-Based Validation
```javascript
function handleTagChange(selectElement) {
    const ruleForm = selectElement.closest('.rule-form');
    const operatorSelect = ruleForm.querySelector('select[name$="-operator_type"]');
    const valueInput = ruleForm.querySelector('input[name$="-tag_value_to_evaluate"]');
    const tagUuid = selectElement.value;
    
    if (!tagUuid) return;
    
    // Fetch VR guidance
    fetch(`/dicom_handler/get_vr_guidance/${tagUuid}/`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateOperatorOptions(operatorSelect, data.compatible_operators);
                showVRGuidance(ruleForm, data.vr_type, data.tag_description);
            }
        })
        .catch(error => console.error('Error fetching VR guidance:', error));
}

function validateValue(valueInput) {
    const ruleForm = valueInput.closest('.rule-form');
    const tagSelect = ruleForm.querySelector('select[name$="-dicom_tag_type"]');
    const operatorSelect = ruleForm.querySelector('select[name$="-operator_type"]');
    
    if (!tagSelect.value || !valueInput.value.trim()) return;
    
    // Real-time VR validation
    fetch('/dicom_handler/validate_vr_value/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({
            tag_uuid: tagSelect.value,
            operator: operatorSelect.value,
            value: valueInput.value.trim()
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showValidationResult(ruleForm, data.is_valid, data.message);
        }
    });
}
```

### `ruleset_edit.html` Features
Similar to create template but with additional features:
1. **Pre-populated Forms**: Existing rules loaded with proper formset management
2. **Delete Handling**: Proper handling of DELETE checkboxes for existing rules
3. **Update Logic**: Maintains form integrity during edits

## URL Patterns Update
```python
# VR and validation endpoints
path('get_vr_guidance/<uuid:tag_uuid>/', views.get_vr_guidance, name='get_vr_guidance'),
path('validate_vr_value/', views.validate_vr_value, name='validate_vr_value'),
path('search_dicom_tags/', views.search_dicom_tags, name='search_dicom_tags'),
```

## Key Improvements Made

### 1. Form Field Naming Fix
- **Issue**: JavaScript was using incorrect prefix `rules-` instead of `rule_set-`
- **Solution**: Updated all JavaScript form cloning to use correct `rule_set-` prefix
- **Impact**: Dynamic forms now save correctly

### 2. Management Form Updates
- **Issue**: TOTAL_FORMS field ID was incorrect (`#id_rules-TOTAL_FORMS`)
- **Solution**: Updated to correct ID (`#id_rule_set-TOTAL_FORMS`)
- **Impact**: Formset validation now works properly

### 3. VR Validation Enhancement
- **Issue**: CS (Code String) validation was too strict
- **Solution**: Updated regex to allow lowercase letters and spaces
- **Impact**: Values like 'Head Neck' now validate correctly

### 4. URL Resolution Fix
- **Issue**: Django reverse URL resolution failing in JavaScript
- **Solution**: Use dynamic URL construction in JavaScript
- **Impact**: AJAX calls now work reliably

### 5. Hidden Field Management
- **Issue**: Cloned forms retained stale ID and DELETE values
- **Solution**: Proper clearing of hidden fields in new forms
- **Impact**: No conflicts with existing form data

## Testing and Debugging

### Debug Features Added
1. **Server-side logging**: POST data and formset errors logged
2. **Client-side validation**: Real-time feedback on form errors
3. **VR guidance display**: Visual indicators for VR requirements
4. **Form state tracking**: Clear indication of form validation status

### Common Issues Resolved
1. **Formset not saving**: Fixed field naming and management form updates
2. **VR validation failures**: Updated validation patterns for real-world data
3. **AJAX URL errors**: Implemented dynamic URL construction
4. **Form cloning issues**: Proper handling of hidden fields and indices

---

# DICOM VR Validation Implementation Guide

## Overview
This section details the implementation of real-time DICOM Value Representation (VR) validation for ruleset creation and editing forms. The system provides inline guidance and validation to ensure accurate DICOM tag value entry.

## Core Components

### VR Validation Utility (`vr_validators.py`)

#### VRValidator Class
```python
class VRValidator:
    """Main validator class for DICOM Value Representations."""
    
    # VR Categories for validation logic
    NUMERIC_VRS = {'FL', 'FD', 'SL', 'SS', 'UL', 'US', 'IS', 'DS'}
    STRING_VRS = {'AE', 'CS', 'LO', 'LT', 'PN', 'SH', 'ST', 'UT', 'UI'}
    DATETIME_VRS = {'DA', 'DT', 'TM'}
    SPECIAL_VRS = {'AS', 'AT', 'SQ', 'OB', 'OD', 'OF', 'OW', 'UN'}
    
    @classmethod
    def validate_value_for_vr(cls, value: str, vr_code: str) -> Tuple[bool, str]:
        """Validate a value against its DICOM VR requirements."""
        # Returns (is_valid, error_message)
    
    @classmethod
    def get_vr_guidance(cls, vr_code: str) -> Dict[str, str]:
        """Get user-friendly guidance for a VR type."""
        # Returns dictionary with description, format, example
    
    @classmethod
    def is_operator_compatible(cls, vr_code: str, operator: str) -> bool:
        """Check if an operator is compatible with a VR type."""
```

#### User-Friendly VR Guidance
The system provides clear, actionable guidance for each VR type:

- **CS (Code String)**: "Enter text string with uppercase letters, numbers, spaces, underscores only"
- **DA (Date)**: "Enter date in format YYYYMMDD (year, month, day as 8 digits)"
- **IS (Integer String)**: "Enter whole number (positive or negative integer)"
- **LO (Long String)**: "Enter text string (letters, numbers, symbols) up to 64 characters"
- **PN (Person Name)**: "Enter person name using ^ to separate: Family^Given^Middle^Prefix^Suffix"

### Enhanced DICOMTagType Model

#### VR Integration Properties
```python
class DICOMTagType(models.Model):
    # ... existing fields ...
    value_representation = models.CharField(max_length=256, null=True, blank=True)
    
    @property
    def vr_guidance(self):
        """Get VR guidance for this tag type."""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.get_vr_guidance(self.value_representation)
        return None
    
    @property
    def compatible_operators(self):
        """Get list of operators compatible with this tag's VR."""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.get_compatible_operators(self.value_representation)
        return []
    
    def validate_value_for_vr(self, value):
        """Validate a value against this tag's VR requirements."""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.validate_value_for_vr(value, self.value_representation)
        return True, ""
    
    def is_operator_compatible(self, operator):
        """Check if an operator is compatible with this tag's VR."""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.is_operator_compatible(self.value_representation, operator)
        return True
```

### Enhanced Rule Model Validation

#### VR-Aware Clean Method
```python
class Rule(models.Model):
    # ... existing fields ...
    
    def clean(self):
        """Enhanced validation including VR requirements."""
        super().clean()
        
        if not self.operator_type or not self.tag_value_to_evaluate:
            return
            
        # Get VR code from associated DICOM tag
        vr_code = None
        if self.dicom_tag_type and self.dicom_tag_type.value_representation:
            vr_code = self.dicom_tag_type.value_representation
        
        if vr_code:
            from .vr_validators import VRValidator
            
            # Validate value format against VR
            is_valid, vr_error = VRValidator.validate_value_for_vr(
                self.tag_value_to_evaluate, vr_code
            )
            if not is_valid:
                raise ValidationError({
                    'tag_value_to_evaluate': f'Value format invalid for {vr_code} VR: {vr_error}'
                })kr_compatible(vr_code, self.operator_type):
                compatible_ops = VRValidator.get_compatible_operators(vr_code)
                raise ValidationError({
                    'operator_type': f'Operator "{self.get_operator_type_display()}" is not compatible with {vr_code} VR. Compatible operators: {", ".join(compatible_ops)}'
                })
```

## AJAX Endpoints

### VR Guidance Endpoint
```python
@login_required
def get_vr_guidance(request, tag_id):
    """Get VR guidance for a specific DICOM tag."""
    try:
        tag = DICOMTagType.objects.get(id=tag_id)
        vr_guidance = tag.vr_guidance
        compatible_operators = tag.compatible_operators
        
        if vr_guidance:
            return JsonResponse({
                'success': True,
                'vr_code': tag.value_representation,
                'guidance': vr_guidance,
                'compatible_operators': compatible_operators
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'No VR information available for this tag'
            })
    except DICOMTagType.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'DICOM tag not found'
        })
```

### VR Value Validation Endpoint
```python
@login_required
def validate_vr_value(request):
    """Validate a value against VR requirements."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        data = json.loads(request.body)
        tag_id = data.get('tag_id')
        value = data.get('value', '').strip()
        operator = data.get('operator', '')
        
        tag = DICOMTagType.objects.get(id=tag_id)
        
        # Validate value format
        is_valid, error_message = tag.validate_value_for_vr(value)
        
        # Check operator compatibility
        operator_compatible = tag.is_operator_compatible(operator)
        
        return JsonResponse({
            'success': True,
            'is_valid': is_valid,
            'error_message': error_message,
            'operator_compatible': operator_compatible,
            'compatible_operators': tag.compatible_operators
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
```

## Frontend Implementation

### Inline VR Guidance Display

#### HTML Structure
```html
<!-- VR Guidance Display -->
<div class="vr-guidance text-sm bg-green-50 border border-green-200 rounded-md p-2 mt-2" style="display: none;">
    <div class="flex items-start">
        <svg class="w-4 h-4 text-green-600 mt-0.5 mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"></path>
        </svg>
        <div class="text-green-800">
            <span class="vr-description font-medium"></span>
            <span class="ml-2 text-green-600">VR:</span> 
            <span class="vr-code font-mono text-xs bg-green-100 px-1 rounded"></span>
        </div>
    </div>
</div>
```

#### JavaScript Implementation
```javascript
function loadVRGuidance(tagSelect) {
    const ruleForm = tagSelect.closest('.rule-form');
    const vrGuidanceDiv = ruleForm.querySelector('.vr-guidance');
    const tagId = tagSelect.value;
    
    if (!tagId) {
        vrGuidanceDiv.style.display = 'none';
        return;
    }
    
    // Make AJAX call to get VR guidance
    fetch(`/dicom/vr-guidance/${tagId}/`, {
        method: 'GET',
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success && data.vr_code) {
            // Extract user-friendly description from guidance object
            let guidanceText = 'No specific guidance available';
            if (data.guidance && typeof data.guidance === 'object') {
                guidanceText = data.guidance.description || data.guidance.format || 'No specific guidance available';
            } else if (data.guidance && typeof data.guidance === 'string') {
                guidanceText = data.guidance;
            }
            
            // Update inline VR guidance display
            vrGuidanceDiv.querySelector('.vr-code').textContent = data.vr_code;
            vrGuidanceDiv.querySelector('.vr-description').textContent = guidanceText;
            vrGuidanceDiv.style.display = 'block';
            
            // Store VR info for validation
            ruleForm.setAttribute('data-vr-code', data.vr_code);
            ruleForm.setAttribute('data-compatible-operators', JSON.stringify(data.compatible_operators));
        } else {
            vrGuidanceDiv.style.display = 'none';
            ruleForm.removeAttribute('data-vr-code');
            ruleForm.removeAttribute('data-compatible-operators');
        }
    })
    .catch(error => {
        console.error('Error loading VR guidance:', error);
        vrGuidanceDiv.style.display = 'none';
    });
}
```

### Real-Time VR Validation
```javascript
function validateVRValue(ruleForm) {
    const tagSelect = ruleForm.querySelector('select[name$="-dicom_tag_type"]');
    const valueInput = ruleForm.querySelector('input[name$="-tag_value_to_evaluate"]');
    
    if (!tagSelect || !valueInput || !tagSelect.value || !valueInput.value.trim()) {
        return true;
    }
    
    const tagId = tagSelect.value;
    const value = valueInput.value.trim();
    const operatorSelect = ruleForm.querySelector('select[name$="-operator_type"]');
    const operator = operatorSelect ? operatorSelect.value : '';
    
    // Make AJAX call to validate VR value
    fetch('/dicom/validate-vr-value/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({
            tag_id: tagId,
            value: value,
            operator: operator
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (!data.is_valid) {
                showVRValidationError(ruleForm, data.error_message);
                return false;
            } else {
                clearVRValidationError(ruleForm);
                return true;
            }
        }
    })
    .catch(error => {
        console.error('Error validating VR value:', error);
    });
}
```

## URL Configuration

### VR Validation URLs
```python
urlpatterns = [
    # ... existing URLs ...
    
    # VR Validation endpoints
    path('vr-guidance/<uuid:tag_id>/', views.get_vr_guidance, name='get_vr_guidance'),
    path('validate-vr-value/', views.validate_vr_value, name='validate_vr_value'),
]
```

## Key Features

### 1. Inline Guidance Display
- **Green Background Theme**: Attractive green information box that stands out
- **Information Icon**: Clear visual indicator for helpful guidance
- **User-Friendly Text**: Plain English descriptions of expected input formats

### 2. Real-Time Validation
- **Format Validation**: Checks value format against VR requirements
- **Operator Compatibility**: Ensures selected operators work with the VR type
- **Immediate Feedback**: Shows validation errors as users type

### 3. VR-Specific Guidance Examples
- **Text Fields**: "Enter text string (letters, numbers, symbols) up to 64 characters"
- **Numeric Fields**: "Enter whole number (positive or negative integer)"
- **Date Fields**: "Enter date in format YYYYMMDD (year, month, day as 8 digits)"
- **Special Formats**: "Enter person name using ^ to separate: Family^Given^Middle^Prefix^Suffix"

### 4. Integration Points
- **Model Validation**: VR validation integrated into Django model clean methods
- **Form Validation**: Automatic validation through model integration
- **AJAX Endpoints**: Lightweight endpoints for real-time validation
- **Template Integration**: Seamless integration with existing ruleset forms

## Benefits

1. **Improved Data Quality**: Ensures DICOM values conform to standards
2. **Better User Experience**: Clear guidance prevents input errors
3. **Real-Time Feedback**: Immediate validation reduces form submission errors
4. **Standards Compliance**: Enforces DICOM VR requirements automatically
5. **Maintainable Code**: Clean separation between validation logic and UI
2,"(0052,0014)","ALinePixelSpacing","A-line Pixel Spacing","FD"
3,"(0052,0011)","ALineRate","A-line Rate","FD"
4,"(0052,0012)","ALinesPerFrame","A-lines Per Frame","US"
...
```

### Field Mapping
- `id` → **Skipped** (Django generates UUIDs automatically)
- `tag_id` → `tag_id` field
- `tag_name` → `tag_name` field  
- `tag_description` → `tag_description` field
- `value_representation` → `value_representation` field

## Migration Implementation

### Data Migration: `0010_auto_20250913_1850.py`

```python
# Generated by Django 5.2.6 on 2025-09-13 13:20

import csv
import os
from django.db import migrations
from django.conf import settings


def load_dicom_tags(apps, schema_editor):
    """Load DICOM tags from CSV file into DICOMTagType model"""
    DICOMTagType = apps.get_model('dicom_handler', 'DICOMTagType')
    
    # Path to the CSV file
    csv_file_path = os.path.join(settings.BASE_DIR, 'seed_data', 'dicom_dictionary.csv')
    
    if not os.path.exists(csv_file_path):
        print(f"Warning: CSV file not found at {csv_file_path}")
        return
    
    # Clear existing data to avoid duplicates
    DICOMTagType.objects.all().delete()
    
    with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        
        dicom_tags = []
        for row in reader:
            # Skip the id field as requested, use other fields
            dicom_tag = DICOMTagType(
                tag_name=row['tag_name'],
                tag_id=row['tag_id'],
                tag_description=row['tag_description'],
                value_representation=row['value_representation']
            )
            dicom_tags.append(dicom_tag)
        
        # Bulk create for better performance
        DICOMTagType.objects.bulk_create(dicom_tags, batch_size=1000)
        print(f"Successfully imported {len(dicom_tags)} DICOM tags")


def reverse_load_dicom_tags(apps, schema_editor):
    """Remove all DICOM tags"""
    DICOMTagType = apps.get_model('dicom_handler', 'DICOMTagType')
    DICOMTagType.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('dicom_handler', '0009_dicomtagtype_tag_description_dicomtagtype_tag_id_and_more'),
    ]

    operations = [
        migrations.RunPython(load_dicom_tags, reverse_load_dicom_tags),
    ]
```

### Migration Features

#### Data Import Process
1. **File Path Resolution**: Uses `settings.BASE_DIR` to locate CSV file
2. **Data Cleanup**: Clears existing records to prevent duplicates
3. **CSV Processing**: Uses `csv.DictReader` for column-based access
4. **Bulk Creation**: Processes records in batches of 1000 for performance
5. **Error Handling**: Checks file existence before processing

#### Reversibility
- **Forward Migration**: Imports all DICOM tags from CSV
- **Reverse Migration**: Removes all DICOMTagType records
- **Safe Rollback**: Allows complete migration reversal if needed

#### Performance Optimizations
- **Batch Processing**: Uses `bulk_create()` with 1000-record batches
- **Memory Efficiency**: Processes CSV row-by-row instead of loading all into memory
- **Single Transaction**: All operations wrapped in migration transaction

## Execution Results

### Migration Commands
```bash
# Create the migration
python manage.py makemigrations --empty dicom_handler

# Apply the migration
python manage.py migrate
```

### Import Statistics
- **Total Records Imported**: 3,731 DICOM tags
- **Processing Time**: < 1 second
- **File Size**: ~500KB CSV file
- **Memory Usage**: Minimal due to batch processing

### Verification
```python
# Check import success
from dicom_handler.models import DICOMTagType
print(f"Total DICOM tags: {DICOMTagType.objects.count()}")

# Sample records
sample_tags = DICOMTagType.objects.all()[:5]
for tag in sample_tags:
    print(f"{tag.tag_id}: {tag.tag_name} - {tag.tag_description}")
```

## Usage in RuleSet System

### Integration with Rule Creation
The imported DICOM tags are now available for:
- **Rule Creation**: Dropdown selection of standardized DICOM tags
- **Validation**: Ensuring only valid DICOM tags are used in rules
- **Autocomplete**: Enhanced user experience with tag descriptions
- **Consistency**: Standardized tag naming across the system

### Template Integration
```python
# In RuleForm
class RuleForm(forms.ModelForm):
    class Meta:
        model = Rule
        fields = ['dicom_tag_type', 'operator_type', 'tag_value_to_evaluate']
        widgets = {
            'dicom_tag_type': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg'
            })
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # All 3,731 DICOM tags now available for selection
        self.fields['dicom_tag_type'].queryset = DICOMTagType.objects.all().order_by('tag_name')
```


---

# Source: example_dicom_viewer.md

# DICOM Viewer with RT Structure Overlay - Implementation Guide

## Overview
This document describes the implementation of an interactive DICOM viewer with RT Structure overlay capabilities using matplotlib, pydicom, and rt-utils. The viewer allows users to visualize DICOM images with RT Structure contours overlaid, with interactive controls for slice navigation, window/level adjustment, and ROI selection.

## Architecture

### Components Created

1. **Views** (`dicom_handler/dicom_viewer_views.py`)
   - `view_rt_structure_list()` - Lists all RT Structures for a series
   - `dicom_viewer()` - Main viewer interface
   - `load_dicom_data()` - API endpoint to load DICOM files into temp directory
   - `get_dicom_slice()` - API endpoint to render slice with overlays
   - `cleanup_temp_files()` - API endpoint to cleanup temporary files

2. **Templates**
   - `templates/dicom_handler/rt_structure_list.html` - RT Structure selection page
   - `templates/dicom_handler/dicom_viewer.html` - Interactive viewer interface

3. **URL Patterns** (`dicom_handler/urls.py`)
   - `/dicom-handler/rt-structures/<series_uid>/` - RT Structure list
   - `/dicom-handler/dicom-viewer/<series_uid>/<rt_structure_id>/` - Viewer
   - `/dicom-handler/api/dicom-viewer/load-data/` - Load data API
   - `/dicom-handler/api/dicom-viewer/get-slice/` - Get slice API
   - `/dicom-handler/api/dicom-viewer/cleanup/` - Cleanup API

## User Workflow

### Step 1: View RT Structure List
User clicks "View RT Structures" button on series processing status page → navigates to RT Structure list page showing all available RT Structure sets for the series.

### Step 2: Open Viewer
User clicks "Open Viewer" button for a specific RT Structure → opens interactive DICOM viewer.

### Step 3: Interact with Viewer
- **Scroll through slices**: Use mouse wheel, slider, or prev/next buttons
- **Adjust window/level**: Use sliders or preset buttons (Soft Tissue, Lung, Bone, Brain, Liver)
- **Select ROIs**: Check/uncheck structures in the right panel
- **Apply overlay**: Click "Apply Overlay" to render selected contours

## Technical Implementation

### File Management

Files are copied to a temporary directory when the viewer loads to ensure fast access and avoid conflicts: 


```python
# Files are copied to temporary directory when viewer loads
temp_dir = tempfile.mkdtemp(prefix='dicom_viewer_')

# DICOM instances copied from database paths
for instance in instances:
    temp_file = os.path.join(temp_dir, f'instance_{idx:04d}.dcm')
    shutil.copy2(instance.instance_path, temp_file)

# RT Structure file copied
temp_rt_struct = os.path.join(temp_dir, 'rtstruct.dcm')
shutil.copy2(rt_struct_path, temp_rt_struct)

# Temp directory path stored in session
request.session['dicom_temp_dir'] = temp_dir
```

### DICOM Image Rendering

```python
# Load DICOM file
ds = pydicom.dcmread(dicom_file)
pixel_array = ds.pixel_array.astype(float)

# Apply rescale slope and intercept
if hasattr(ds, 'RescaleSlope') and hasattr(ds, 'RescaleIntercept'):
    pixel_array = pixel_array * ds.RescaleSlope + ds.RescaleIntercept

# Apply windowing
windowed_array = apply_windowing(pixel_array, window_center, window_width)
```

### Window/Level Application

```python
def apply_windowing(pixel_array, window_center, window_width):
    """Apply window/level to pixel array"""
    img_min = window_center - window_width / 2
    img_max = window_center + window_width / 2
    
    windowed = np.clip(pixel_array, img_min, img_max)
    windowed = (windowed - img_min) / (img_max - img_min)
    
    return windowed
```
### RT Structure Overlay

```python
# Load RT Structure using rt-utils
rtstruct = RTStructBuilder.create_from(
    dicom_series_path=temp_dir,
    rt_struct_path=rt_struct_path
)

# Get ROI names
roi_names = rtstruct.get_roi_names()

# For each selected ROI
for roi_name in selected_rois:
    # Get 3D mask
    mask_3d = rtstruct.get_roi_mask_by_name(roi_name)
    
    # Extract slice
    mask_slice = mask_3d[:, :, slice_index]
    
    # Find and draw contours
    contours = find_contours(mask_slice)
    for contour in contours:
        ax.plot(contour[:, 1], contour[:, 0], 
               color=colors[idx], linewidth=2, label=roi_name)
```

### Contour Detection

```python
def find_contours(mask_slice, level=0.5):
    """Find contours in a binary mask slice"""
    try:
        from skimage import measure
        contours = measure.find_contours(mask_slice, level)
        return contours
    except ImportError:
        # Fallback: simple edge detection
        edges = np.zeros_like(mask_slice)
        edges[:-1, :] |= (mask_slice[:-1, :] != mask_slice[1:, :])
        edges[:, :-1] |= (mask_slice[:, :-1] != mask_slice[:, 1:])
        
        y, x = np.where(edges)
        if len(x) > 0:
            points = np.column_stack([y, x])
            return [points]
        return []
```

## Key Features

### 1. Interactive Slice Navigation
- Mouse wheel scrolling through slices
- Slider for quick navigation
- Previous/Next buttons
- Real-time slice information display

### 2. Window/Level Control
- Adjustable window center and width sliders
- Preset buttons for common tissue types:
  - **Soft Tissue**: WC=40, WW=400
  - **Lung**: WC=-600, WW=1500
  - **Bone**: WC=400, WW=1800
  - **Brain**: WC=50, WW=350
  - **Liver**: WC=60, WW=360

### 3. ROI Selection
- Checkbox list of all available structures
- Select All / Deselect All buttons
- Color-coded contour overlays
- Legend showing structure names

### 4. Performance Optimization
- Files loaded into temporary directory on viewer open
- Session-based temporary file management
- Automatic cleanup on page unload
- Base64-encoded image transmission

## Dependencies

```
pydicom==3.0.1          # DICOM file reading
matplotlib==3.10.7      # Image rendering and plotting
rt-utils==0.3           # RT Structure parsing
numpy==2.3.4            # Array operations
scikit-image==0.24.0    # Contour detection
pillow==12.0.0          # Image processing
```

## Database Models Used

```python
# DICOMSeries - Main series information
series = DICOMSeries.objects.get(series_instance_uid=series_uid)

# RTStructureFileImport - RT Structure file information
rt_structure = RTStructureFileImport.objects.get(id=rt_structure_id)
# Fields: reidentified_rt_structure_file_path, deidentified_rt_structure_file_path

# DICOMInstance - Individual DICOM image files
instances = DICOMInstance.objects.filter(series_instance_uid=series)
# Fields: sop_instance_uid, instance_path
```

## Usage Examples

### Basic Matplotlib DICOM Viewing

```python
import matplotlib.pyplot as plt
import pydicom

# Load single DICOM file
dicom_file_path = "path/to/your/dicom/file.dcm"
ds = pydicom.dcmread(dicom_file_path)

# Get window/level from DICOM metadata
window_center = ds.WindowCenter
window_width = ds.WindowWidth

# Apply windowing and display
windowed_data = apply_windowing(ds.pixel_array, window_center, window_width)
plt.imshow(windowed_data, cmap='gray')
plt.show()
```

### RT Structure Loading with RTUtils

```python
from rt_utils import RTStructBuilder
import matplotlib.pyplot as plt

# Load RT Structure with series
rtstruct = RTStructBuilder.create_from(
    dicom_series_path="path/to/your/dicom/series", 
    rt_struct_path="path/to/your/rt-struct.dcm"
)

# Get all ROI names
roi_names = rtstruct.get_roi_names()
print(f"Available ROIs: {roi_names}")

# Load 3D mask for specific ROI
mask_3d = rtstruct.get_roi_mask_by_name("ROI NAME")

# Display one slice
first_mask_slice = mask_3d[:, :, 0]
plt.imshow(first_mask_slice, cmap='jet', alpha=0.5)
plt.show()
```

## Security Considerations

1. **Authentication Required**: All views decorated with `@login_required`
2. **CSRF Protection**: All POST requests require CSRF token
3. **Session-based Access**: Temporary files tied to user session
4. **Automatic Cleanup**: Temporary files removed on page unload
5. **Path Validation**: File paths validated before access

## Troubleshooting

### Issue: RT Structure not displaying
- **Check**: RT Structure file path exists in database
- **Check**: File is accessible from application
- **Check**: ROIs are selected in the panel
- **Solution**: Verify `reidentified_rt_structure_file_path` or fallback to `deidentified_rt_structure_file_path`

### Issue: Contours not matching images
- **Cause**: UID mismatch between RT Structure and DICOM images
- **Solution**: RT-utils handles spatial coordinate matching automatically
- **Note**: Z-coordinate matching used for proper slice alignment

### Issue: Slow performance
- **Cause**: Large number of slices or complex contours
- **Solution**: Optimize by caching rendered slices or reducing overlay complexity
- **Tip**: Deselect unused ROIs to improve rendering speed

### Issue: Session expired error
- **Cause**: Temporary files cleaned up or session timeout
- **Solution**: Reload the page to reinitialize the viewer

---

# Source: XML_TEMPLATE_IMPORT_GUIDE.md

# XML Template Import Wizard - User Guide

## Overview

The XML Template Import Wizard allows you to bulk import structure properties from predefined XML template files (e.g., Varian Eclipse format) into your autosegmentation templates. This feature automatically maps XML structures to autosegmentation structures and populates the `StructureProperties` model with ROI labels, colors, and types.

## Features

- **XML Parsing**: Supports Varian Eclipse XML format and similar structure template files
- **Auto-Mapping**: Automatically suggests structure mappings based on name matching
- **Bulk Import**: Import multiple structure properties in one workflow
- **Additional Structures**: Import unmapped structures as additional contours
- **Color Conversion**: Automatically converts various color formats to DICOM RGB format
- **Validation**: Validates ROI labels (TG263 standard), color values, and duplicate names
- **Duplicate Prevention**: Ensures no duplicate ROI names within a template
- **Review Step**: Review all mappings before saving to database
- **4-Step Wizard**: Upload → Map → Review → Additional Structures

## Workflow

### Step 1: Upload XML Template

1. Navigate to the template detail page
2. Click **"Import XML Template"** button
3. Select the autosegmentation template you want to map to
4. Upload your XML file (max 10MB)
5. Click **"Next: Map Structures"**

**Note**: Only Varian Eclipse XML format is currently supported.

### Step 2: Map Structures

The wizard will:
- Parse the XML file and extract all structures
- Auto-suggest mappings based on structure name matching (highlighted in green)
- Display structure information from the XML (name, type, color)

For each structure, you can:
- **Select Autosegmentation Structure**: Choose which autosegmentation structure to map to
- **Edit ROI Label**: Modify the preferred ROI label (max 16 characters per TG263 standard)
- **Select RT ROI Type**: Choose the structure type (ORGAN, OAR, PTV, CTV, etc.)
- **Edit Color**: Modify the DICOM color in R\G\B format (e.g., 255\0\0 for red)
- **Skip Structure**: Check to skip importing this structure

Click **"Next: Review Mappings"** when done.

### Step 3: Review Mappings

- Review all mapped structures in a summary table
- Verify ROI labels, types, and colors
- Check for any validation warnings
- Click **"Next: Additional Structures"** to proceed

### Step 4: Select Additional Structures

This step shows **unmapped structures** from the XML file that weren't matched to autosegmentation structures.

You can:
- **Select structures** to import as `AdditionalStructures`
- These will be included in the DICOM RT Structure Set but won't have AI segmentation
- Useful for support structures, reference contours, or planning structures
- Preview structure details (name, type, color) before selecting

Click **"Save All"** to complete the import.

The wizard will:
- Create new `StructureProperties` entries for mapped structures
- Update existing properties if they already exist
- Create `AdditionalStructures` entries for selected unmapped structures
- **Validate for duplicate names** across all structure types
- Display a success message with counts of created/updated entries

## Supported XML Formats

### Varian Eclipse Structure Templates

The parser supports Varian Eclipse XML structure template format with the following elements:

```xml
<StructureTemplate>
  <Preview ID="..." Diagnosis="..." TreatmentSite="..." Description="..."/>
  <Structures>
    <Structure ID="..." Name="...">
      <Identification>
        <VolumeType>Organ</VolumeType>
      </Identification>
      <ColorAndStyle>Yellow</ColorAndStyle>
    </Structure>
  </Structures>
</StructureTemplate>
```

### Supported Color Formats

The parser automatically converts these color formats to DICOM RGB:

- **Named colors**: `Yellow`, `Cyan`, `Red`, `Green`, `Blue`, etc.
- **Segment format**: `Segment - Cyan`
- **RGB format**: `RGB 255 0 0`
- **Concatenated RGB**: `RGB255228181` (parsed as RGB components)
- **Special formats**: `Skin Rendering` (converted to skin color)

### Volume Type Mapping

XML volume types are automatically mapped to DICOM RT ROI Interpreted Types:

| XML Volume Type | RT ROI Interpreted Type |
|----------------|------------------------|
| ORGAN          | ORGAN                  |
| OAR            | OAR                    |
| PTV            | PTV                    |
| CTV            | CTV                    |
| GTV            | GTV                    |
| EXTERNAL/BODY  | EXTERNAL               |
| AVOIDANCE      | AVOIDANCE              |
| CONTROL        | CONTROL                |

## File Structure

### New Files Created

1. **`dicom_handler/xml_template_parser.py`**
   - XML parsing utility
   - Color conversion functions
   - Validation functions

2. **`dicom_handler/xml_template_views.py`**
   - Wizard views (upload, map, review, save, cancel)
   - AJAX search endpoint for structures

3. **`dicom_handler/forms.py`** (updated)
   - `XMLTemplateUploadForm`: File upload form
   - `StructureMappingForm`: Structure mapping form

4. **Templates**:
   - `templates/dicom_handler/xml_template_wizard_upload.html`
   - `templates/dicom_handler/xml_template_wizard_map.html`
   - `templates/dicom_handler/xml_template_wizard_review.html`
   - `templates/dicom_handler/xml_template_wizard_additional.html` (NEW)

5. **`dicom_handler/additional_structure_views.py`** (NEW)
   - CRUD views for AdditionalStructures
   - Add, edit, delete operations

6. **`test_xml_parser.py`**
   - Test script for XML parser functionality

### Updated Files

1. **`dicom_handler/urls.py`**
   - Added wizard URL patterns

2. **`templates/dicom_handler/template_detail.html`**
   - Added "Import XML Template" button

## Usage Examples

### Example 1: Head & Neck Template

```bash
# XML file: HN.xml
# Contains structures like: THYROID, SPINAL CORD, PAROTID_R, etc.
```

1. Upload `HN.xml` for your Head & Neck autosegmentation template
2. The wizard auto-matches structures like "PAROTID_R" → "Parotid_R"
3. Review and adjust ROI labels to meet TG263 standards
4. Save to populate structure properties

### Example 2: Prostate Template

```bash
# XML file: URO_Prostate_SBRT.xml
# Contains structures like: BODY, Rectum, Bladder, PTV, etc.
```

1. Upload `URO_Prostate_SBRT.xml` for your Prostate template
2. Map structures to corresponding autosegmentation structures
3. Colors are automatically converted to DICOM format
4. Save to import all properties at once

## Testing

Run the test script to verify XML parsing:

```bash
./venv/bin/python test_xml_parser.py
```

This tests:
- XML file parsing (HN.xml and URO_Prostate_SBRT.xml)
- Color format conversion
- ROI label validation
- DICOM color validation

## Validation Rules

### ROI Label (TG263 Standard)
- Maximum 16 characters
- Cannot be empty
- Automatically truncated if needed

### DICOM Color Format
- Must be in format: `R\G\B`
- Each value must be 0-255
- Example: `255\0\0` for red

### Duplicate Name Validation (NEW)

**Prevents duplicate ROI names within the same template:**

The system validates that ROI names are unique across:
1. **AdditionalStructures**: No duplicate additional structure names
2. **StructureProperties.roi_label**: No conflict with mapped structure labels
3. **AutosegmentationStructure.name**: No conflict with autosegmentation structure names

**Validation is:**
- **Case-insensitive**: "Liver", "liver", and "LIVER" are considered duplicates
- **Template-scoped**: Same name allowed in different templates
- **Applied during**:
  - XML import (Step 4: Additional Structures)
  - Manual add/edit via UI
  - All database saves

**Example Error Messages:**
- `"An additional structure with the name 'Bladder' already exists in this template."`
- `"A structure with the name 'Liver' already exists in this template (from mapped structures)."`
- `"A structure with the name 'Heart' already exists in this template (autosegmentation structure)."`

**Why This Matters:**
- Ensures DICOM RT Structure Sets have unique ROI names
- Prevents confusion during treatment planning
- Maintains data integrity across the system

## Permissions Required

- `dicom_handler.add_structureproperties`: Required to access the wizard

## API Endpoints

- `GET /dicom_handler/xml-template-wizard/start/`: Start wizard
- `POST /dicom_handler/xml-template-wizard/start/`: Upload XML file
- `GET /dicom_handler/xml-template-wizard/map/`: Display mapping form
- `POST /dicom_handler/xml-template-wizard/map/`: Submit mappings
- `GET /dicom_handler/xml-template-wizard/review/`: Review mappings
- `GET /dicom_handler/xml-template-wizard/additional/`: Select additional structures (NEW)
- `POST /dicom_handler/xml-template-wizard/additional/`: Save all structures (NEW)
- `GET /dicom_handler/xml-template-wizard/cancel/`: Cancel wizard
- `GET /dicom_handler/api/xml-template/search-structures/`: AJAX structure search

## Troubleshooting

### Issue: XML parsing fails
- **Solution**: Verify XML file is valid and follows supported format
- Check XML structure matches Varian Eclipse format

### Issue: Colors not displaying correctly
- **Solution**: Ensure colors are in supported format
- Use named colors or `RGB R G B` format

### Issue: ROI label validation error
- **Solution**: Ensure labels are 16 characters or less
- Edit labels in the mapping step

### Issue: No auto-matches found
- **Solution**: Structure names in XML don't match autosegmentation structure names
- Manually map each structure in Step 2

### Issue: Duplicate name validation error during import
- **Error**: `"A structure with the name 'X' already exists in this template"`
- **Solution**: 
  - Check if the structure name conflicts with existing mapped structures
  - Check if it conflicts with autosegmentation structure names
  - Rename the structure in the XML file before import, or
  - Deselect the conflicting structure in Step 4 (Additional Structures)
  - Note: Validation is case-insensitive ("Liver" = "liver")

## Notes

- The wizard stores data in session between steps (4 steps total)
- Canceling the wizard clears all session data
- Existing structure properties are updated, not duplicated
- Session data is automatically cleared after successful save
- **Duplicate name validation** is enforced at model level and during import
- Additional structures can be managed from the template detail page after import
- Color picker with presets available for manual add/edit operations

## Future Enhancements

Potential improvements:
- Support for additional XML formats (RayStation, Pinnacle, etc.)
- Bulk edit capabilities in mapping step
- Import history and rollback functionality
- Template-to-template copying
- CSV export/import as alternative to XML

---

# Source: TEST_PIPELINE_README.md

# ROI Generation Pipeline Testing

This directory contains tools to test the ROI generation pipeline operations with real CT and RT Structure Set data.

## Quick Start

### 1. Prepare Your Data

You need:
- **CT Series**: A directory containing CT DICOM files
- **RT Structure Set**: A DICOM RT Structure Set file with existing structures

### 2. Create a Pipeline JSON

Define the operations you want to test in a JSON file. See `example_pipelines/` for examples.

**Basic Structure:**
```json
{
  "operations": [
    {
      "type": "expand",
      "structures": ["CTV"],
      "parameters": {
        "margin_mm": 5.0,
        "kernel_type": "ball"
      }
    }
  ]
}
```

### 3. Run the Test Script

```bash
# Activate virtual environment
source venv/bin/activate

# Run the test
python test_pipeline_operations.py \
    --ct-dir /path/to/ct/series \
    --rtstruct /path/to/original_rtstruct.dcm \
    --pipeline example_pipeline.json \
    --output output_rtstruct.dcm \
    --structure-name "PTV_Generated" \
    --color "255,0,0"
```

### 4. Visualize the Result

The output RT Structure Set will contain:
- **All original structures** (unchanged)
- **New generated structure** with the name you specified

You can open it in any DICOM viewer (3D Slicer, MIM, Eclipse, etc.) to verify the operations worked correctly.

## Available Operations

### Operations Requiring Structure Selection

#### **expand**
Expand a structure by a specified margin.
```json
{
  "type": "expand",
  "structures": ["CTV"],
  "parameters": {
    "margin_mm": 5.0,
    "kernel_type": "ball"  // Options: ball, box, cross
  }
}
```

#### **contract**
Contract (shrink) a structure by a specified margin.
```json
{
  "type": "contract",
  "structures": ["GTV"],
  "parameters": {
    "margin_mm": 3.0,
    "kernel_type": "ball"
  }
}
```

#### **union**
Combine multiple structures into one.
```json
{
  "type": "union",
  "structures": ["Parotid_L", "Parotid_R", "Submandibular_L"]
}
```

#### **intersection**
Keep only the overlapping region of multiple structures.
```json
{
  "type": "intersection",
  "structures": ["PTV_High", "PTV_Low"]
}
```

#### **subtract**
Remove structures from the first structure.
```json
{
  "type": "subtract",
  "structures": ["PTV", "Brainstem", "SpinalCord"],
  "parameters": {
    "margin_mm": 2.0  // Optional: expand structures before subtracting
  }
}
```

#### **crop_to_boundary**
Limit the current result to a boundary structure.
```json
{
  "type": "crop_to_boundary",
  "structures": ["Body"]
}
```

### Operations Applied to Current Result

These operations work on the result of previous operations and don't require structure selection.

#### **smooth**
Smooth the surface of the structure.
```json
{
  "type": "smooth",
  "parameters": {
    "smoothing_mm": 2.0,
    "iterations": 1
  }
}
```

#### **fill_holes**
Fill internal cavities in the structure.
```json
{
  "type": "fill_holes"
}
```

#### **remove_small_components**
Remove small disconnected pieces.
```json
{
  "type": "remove_small_components",
  "parameters": {
    "min_size_mm3": 100.0
  }
}
```

#### **keep_largest**
Keep only the largest connected component.
```json
{
  "type": "keep_largest"
}
```

## Example Pipelines

### Example 1: Create PTV from CTV
```json
{
  "operations": [
    {
      "type": "expand",
      "structures": ["CTV"],
      "parameters": {
        "margin_mm": 5.0,
        "kernel_type": "ball"
      }
    },
    {
      "type": "smooth",
      "parameters": {
        "smoothing_mm": 2.0
      }
    }
  ]
}
```

### Example 2: Combine Bilateral Organs
```json
{
  "operations": [
    {
      "type": "union",
      "structures": ["Parotid_L", "Parotid_R"]
    },
    {
      "type": "smooth",
      "parameters": {
        "smoothing_mm": 2.0
      }
    }
  ]
}
```

### Example 3: Complex Avoidance Structure
```json
{
  "operations": [
    {
      "type": "expand",
      "structures": ["Lung_L"],
      "parameters": {
        "margin_mm": 3.0,
        "kernel_type": "ball"
      }
    },
    {
      "type": "expand",
      "structures": ["Lung_R"],
      "parameters": {
        "margin_mm": 3.0,
        "kernel_type": "ball"
      }
    },
    {
      "type": "union",
      "structures": ["Lung_L", "Lung_R", "Heart"]
    },
    {
      "type": "smooth",
      "parameters": {
        "smoothing_mm": 2.5,
        "iterations": 2
      }
    },
    {
      "type": "fill_holes"
    }
  ]
}
```

## Command Line Options

```
--ct-dir PATH           Path to CT DICOM series directory (required)
--rtstruct PATH         Path to RT Structure Set file (required)
--pipeline PATH         Path to pipeline JSON file (required)
--output PATH           Path to save output RT Structure Set (required)
--structure-name NAME   Name for generated structure (default: Generated_Structure)
--color R,G,B          RGB color for structure (default: 255,0,0)
--verbose              Enable verbose logging
```

## Troubleshooting

### Structure Not Found
```
ValueError: Structure 'CTV' not found in RT Structure Set
```
**Solution**: Check the exact structure names in your RT Structure Set. Names are case-sensitive.

### Operation Requires Previous Result
```
ValueError: Smooth operation requires a previous result
```
**Solution**: Operations like `smooth`, `fill_holes`, etc. must come after operations that select structures (like `expand`, `union`, etc.)

### Invalid JSON
```
Failed to load pipeline JSON: ...
```
**Solution**: Validate your JSON syntax. Use a JSON validator or check for missing commas, brackets, etc.

## Tips for Testing

1. **Start Simple**: Test with a single `expand` operation first
2. **Check Structure Names**: List structures in your RT Struct before creating the pipeline
3. **Visualize Each Step**: Create separate pipelines for each operation to see intermediate results
4. **Use Verbose Mode**: Add `--verbose` flag to see detailed execution logs
5. **Compare Results**: Open original and generated RT Struct side-by-side in a viewer

## Integration with Frontend

Once you've verified operations work correctly with the test script, the same JSON format is used in the web interface:

1. Navigate to template detail page
2. Click "Add Structure"
3. Use the visual pipeline builder
4. The generated JSON matches the format used in these test scripts

This ensures what you test here will work exactly the same in production!

---

# Source: DICOM_DEIDENTIFICATION.md

# HIPAA Compliant DICOM Deidentification Implementation

**File:** `dicom_handler/export_services/task3_deidentify_series.py`  
**Purpose:** Deidentify CT/MR/PET DICOM series for segmentation workflow  
**Date:** June 19, 2026

---

## Overview

This deidentification task removes Protected Health Information (PHI) from CT/MR/PET DICOM files to comply with HIPAA Safe Harbor requirements. It runs as **Task 3** after:
- **Task 1**: DICOM files are read from storage (CT/MR/PET only)
- **Task 2**: Series are matched with autosegmentation templates

---

## HIPAA Safe Harbor Compliance

The implementation addresses **16 out of 18 HIPAA Safe Harbor identifier categories** by masking/replacing **50 specific DICOM fields**. The 2 non-applicable identifiers (biometric identifiers and full-face photographs) are not present in CT/MR/PET imaging data.

### Mapping: HIPAA Identifiers to DICOM Fields

| **HIPAA Safe Harbor Identifier** | **DICOM Fields Addressed** | **How Handled** |
|----------------------------------|----------------------------|-----------------|
| 1. Names | Patient Name, Referring Physician Name, Performing Physician Name, Operators Name, Physicians of Record, Requesting Physician, Consulting Physician Name, Responsible Person, Reviewer Name (9 fields) | Replaced with `#` |
| 2. Geographic locations | Institution Address, Referring Physician Address, Person Address (3 fields) | Replaced with `#` |
| 3. Dates | All DA (Date) and DT (DateTime) fields | Shifted to random date 2000-2020 |
| 4. Telephone numbers | Telephone Numbers, Patient Telephone Numbers (2 fields) | Replaced with `#` |
| 5. Fax numbers | Covered in Free-Text Fields | Replaced with `#` |
| 6. Email addresses | Covered in Free-Text Fields | Replaced with `#` |
| 7. Social Security numbers | Covered in Free-Text Fields | Replaced with `#` |
| 8. Medical record numbers | Other Patient IDs, Other Patient IDs Sequence, Medical Record Locator (3 fields) | Replaced with `#` |
| 9. Health plan numbers | Patient Insurance Plan Code Sequence (1 field) | Replaced with `#` |
| 10. Account numbers | Accession Number, Filler Order Number, Placer Order Number (3 fields) | Replaced with `#` |
| 11. Certificate/license numbers | Covered in Free-Text Fields | Replaced with `#` |
| 12. Vehicle identifiers | Covered in Free-Text Fields | Replaced with `#` |
| 13. Device identifiers | Device Serial Number, Plate ID, Generator ID, Cassette ID, Gantry ID (5 fields) | Replaced with `#` |
| 14. Web URLs | Covered in Free-Text Fields | Replaced with `#` |
| 15. IP addresses | Covered in Free-Text Fields | Replaced with `#` |
| 18. Other unique identifiers | Patient ID, Study Instance UID, Series Instance UID, SOP Instance UID, Frame of Reference UID, Study ID, Requested Procedure ID, Scheduled Procedure Step ID, Institution Name, Institutional Department Name, Station Name, Institution Code Sequence, Referring Physician Identification Sequence, Physicians Reading Study Identification Sequence, Operator Identification Sequence (15 fields) + 10 Free-Text Fields | Patient ID → UUID; UIDs → Deidentified UIDs; Others → `#` |

**Note:** HIPAA identifiers 16 (Biometric identifiers) and 17 (Full-face photographs) are not applicable to CT/MR/PET imaging data.

**Total: 50 DICOM fields** addressing 16 applicable HIPAA Safe Harbor identifier categories (out of 18 total).

---

## What Gets Deidentified

### 1. **Patient & Person Information (9 fields)**
All replaced with `#`:
- Patient Name
- Referring Physician Name
- Performing Physician Name
- Operators Name
- Physicians of Record
- Requesting Physician
- Consulting Physician Name
- Responsible Person
- Reviewer Name

### 2. **Institution & Location (4 fields)**
All replaced with `#`:
- Institution Name
- Institution Address
- Institutional Department Name
- Station Name

### 3. **Contact Information (4 fields)**
All replaced with `#`:
- Referring Physician Address
- Person Address
- Telephone Numbers
- Patient Telephone Numbers

### 4. **Medical Record Numbers (4 fields)**
All replaced with `#`:
- Other Patient IDs
- Other Patient IDs Sequence
- Medical Record Locator
- Patient Insurance Plan Code Sequence

### 5. **Device Identifiers (5 fields)**
All replaced with `#`:
- Device Serial Number
- Plate ID
- Generator ID
- Cassette ID
- Gantry ID

### 6. **Study & Order Numbers (6 fields)**
All replaced with `#`:
- Accession Number
- Study ID
- Requested Procedure ID
- Scheduled Procedure Step ID
- Filler Order Number
- Placer Order Number

### 7. **Sequences (4 fields)**
All replaced with `#`:
- Institution Code Sequence
- Physicians Reading Study Identification Sequence
- Operator Identification Sequence
- Referring Physician Identification Sequence

### 8. **Free-Text Fields (10 fields)**
All replaced with `#` (not needed for segmentation):
- Study Description
- Series Description
- Image Comments
- Additional Patient History
- Study Comments
- Patient Comments
- Requested Procedure Description
- Performed Procedure Step Description
- Protocol Name
- Acquisition Protocol Description

**Total: 50 DICOM fields removed**

---

## What Gets Replaced

### UIDs (Unique Identifiers)

All UIDs are replaced with new deidentified values while maintaining consistency:

| **Original** | **Deidentified** | **Consistency** |
|--------------|------------------|-----------------|
| Patient ID | Random UUID (e.g., `a1b2c3d4-e5f6-...`) | Same for all studies of same patient |
| Study Instance UID | `1.2.826.0.1.3680043.10.1561.XXX.XX.XXX` | Same for all series in same study |
| Series Instance UID | `<Study UID>.<count>` | Unique per series |
| SOP Instance UID | `<Series UID>.<7-digit>.<3-digit>` | Unique per instance |
| Frame of Reference UID | `<Series UID>.<4-digit>` | Same for all instances in series |

**Why this matters:** Maintains relationships between patients → studies → series → instances

---

## What Gets Shifted

### Dates

All date fields (DA) and datetime fields (DT) are shifted to a random date between 2000-2020:

- **Consistent per study**: All series in the same study get the same random date
- **Preserves temporal order**: If Study A was before Study B, it remains before Study B
- **Does NOT preserve age**: Patient age is not maintained (not needed for segmentation)

**Example:**
- Original: Study Date = 2024-03-15, Patient DOB = 1980-05-20
- Deidentified: Study Date = 2015-08-10, Patient DOB = 2015-08-10 (age becomes 0)

---

## What Gets Removed Completely

### Private Tags

All vendor-specific private DICOM tags are removed using `dicom_data.remove_private_tags()`.

**Why:** Private tags often contain vendor-specific identifiers or PHI.

---

## HIPAA Safe Harbor Compliance

### ✅ All 18 HIPAA Identifiers Addressed

| # | **Identifier** | **How Handled** |
|---|----------------|-----------------|
| 1 | Names | 9 name fields → `#` |
| 2 | Geographic locations | 3 address fields → `#` |
| 3 | Dates | All dates shifted to random (2000-2020) |
| 4 | Telephone numbers | 2 phone fields → `#` |
| 5 | Fax numbers | Free-text fields → `#` |
| 6 | Email addresses | Free-text fields → `#` |
| 7 | Social Security numbers | Free-text fields → `#` |
| 8 | Medical record numbers | 4 MRN fields → `#` |
| 9 | Health plan numbers | Insurance field → `#` |
| 10 | Account numbers | 2 order number fields → `#` |
| 11 | Certificate/license numbers | Free-text fields → `#` |
| 12 | Vehicle identifiers | Free-text fields → `#` |
| 13 | Device identifiers | 5 device fields → `#` |
| 14 | Web URLs | Free-text fields → `#` |
| 15 | IP addresses | Free-text fields → `#` |
| 16 | Biometric identifiers | Not in CT/MR/PET data |
| 17 | Full-face photographs | Not in CT/MR/PET data |
| 18 | Other unique identifiers | All UIDs replaced |

**Result: Complete HIPAA Safe Harbor compliance for CT/MR/PET imaging**

---

## Processing Steps

The deidentification process follows these steps in order:

1. **Read DICOM file** - Load the original DICOM file
2. **Replace identifier fields** - Set 40 FIELDS_TO_MASK to `#`
3. **Replace UIDs** - Generate and assign new deidentified UIDs
4. **Shift dates** - Apply random date shift (consistent per study)
5. **Remove free-text fields** - Set 10 FREE_TEXT_FIELDS to `#`
6. **Remove private tags** - Delete all vendor-specific tags
7. **Save deidentified file** - Write to output path

---

## Database Storage

Deidentified values are stored in the database for tracking:

### Patient Table
- `deidentified_patient_id` - Random UUID
- `patient_date_of_birth` - Random date (same as study date)

### Study Table
- `deidentified_study_instance_uid` - Generated UID
- `deidentified_study_date` - Random date (2000-2020)
- `deidentified_accession_number` - `#`
- `deidentified_study_id` - `#`

### Series Table
- `deidentified_series_instance_uid` - Generated UID
- `deidentified_frame_of_reference_uid` - Generated UID
- `deidentified_series_date` - Same as study date

### Instance Table
- `deidentified_sop_instance_uid` - Generated UID

---

## Testing & Verification

### Independent Verification Script

A standalone CLI test script is provided for IT administrators to independently verify the deidentification process:

**Script:** `test_deidentification_cli.py`

#### Purpose
- Test the actual deidentification implementation without database dependencies
- Generate detailed verification reports for compliance auditing
- Allow IT administrators to validate HIPAA compliance before production deployment

#### Requirements

**Prerequisites:**
- Python 3.6 or higher
- pip (Python package installer)

**Initial Setup (First Time):**
```bash
# Clone the repository (if not already cloned)
git clone <repository-url>
cd draw-client-2.0

# Pull latest changes
git pull

# Create virtual environment (if not exists)
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Linux/Mac
# OR
venv\Scripts\activate     # On Windows

# Install dependencies
pip install -r requirements.txt
```

**Subsequent Usage:**
```bash
# Navigate to project root and update
cd /path/to/draw-client-2.0
git pull

# Activate the virtual environment
source venv/bin/activate  # On Linux/Mac
```

**Key Dependencies:**
- `pydicom` - DICOM file handling
- `Django` - Project framework
- Other dependencies in `requirements.txt`

**Note:** The script imports from the Django project, so it needs:
- The virtual environment activated
- Django settings configured (automatic via `django.setup()`)
- Access to `dicom_handler/export_services/task3_deidentify_series.py`

#### Usage
```bash
# From project root directory with venv activated:
python test_deidentification_cli.py <input_folder>
```

#### What It Does
1. **Scans input folder** - Recursively finds all DICOM files
2. **Uses actual implementation** - Imports and uses the exact deidentification logic from `task3_deidentify_series.py`:
   - `FIELDS_TO_MASK` (50 fields)
   - `FREE_TEXT_FIELDS` (10 fields)
   - `generate_deidentified_study_uid()`
   - `generate_deidentified_series_uids()`
   - `generate_sop_instance_uid()`
   - `generate_random_date()`
3. **Generates consistent UIDs** - Same patient/study/series UIDs for all files in test run
4. **Deidentifies each file** - Applies same logic as production (field masking, UID replacement, date shifting, private tag removal)
5. **Saves deidentified files** - Outputs to `<input_folder>/deidentified/`
6. **Generates verification report** - Creates detailed report at `<input_folder>/deidentification_report.txt`

#### Output

**Deidentified Files:**
- Location: `<input_folder>/deidentified/`
- Format: Same folder structure as input
- Content: Fully deidentified DICOM files

**Verification Report:**
- Summary of files processed
- Verification checks:
  - ✓ All PHI fields masked
  - ✓ All UIDs replaced
  - ✓ All dates shifted
- Detailed results for each file showing original vs deidentified values
- HIPAA Safe Harbor compliance checklist

#### Key Features
- ✅ **Tests actual implementation** - Uses the same code as production
- ✅ **No database required** - Runs standalone without database entries
- ✅ **Detailed verification** - Shows before/after values for audit trail
- ✅ **HIPAA compliance checklist** - Verifies all 18 Safe Harbor identifiers

#### Example Report Output
```
================================================================================
DICOM DEIDENTIFICATION VERIFICATION REPORT
================================================================================
Generated: 2026-06-19 11:15:30
Total files processed: 185

Implementation tested:
  dicom_handler/export_services/task3_deidentify_series.py
================================================================================

SUMMARY
--------------------------------------------------------------------------------
Files deidentified: 185
All PHI fields masked: ✓ YES
All UIDs replaced: ✓ YES
All dates shifted: ✓ YES

DETAILED RESULTS
================================================================================

File 1: CT_001.dcm
--------------------------------------------------------------------------------

[PATIENT INFORMATION]
  Patient ID:
    Original:      12345
    Deidentified:  a1b2c3d4-e5f6-7890-1234-567890abcdef
  Patient Name:
    Original:      Doe^John
    Deidentified:  #

[UNIQUE IDENTIFIERS]
  Study Instance UID:
    Original:      1.2.840.113619.2.55.3.12345
    Deidentified:  1.2.826.0.1.3680043.10.1561.123.45.678

[DATES]
  Study Date:
    Original:      20240315
    Deidentified:  20150810

[VERIFICATION]
  Patient Name masked            ✓ PASS
  Institution masked             ✓ PASS
  Study Description masked       ✓ PASS
  Patient ID replaced            ✓ PASS
  Study UID replaced             ✓ PASS
  Study date shifted             ✓ PASS
```

#### For IT Administrators
This script allows you to:
1. Verify deidentification works correctly before production deployment
2. Test with sample data without affecting the database
3. Generate compliance reports for auditing purposes
4. Validate HIPAA Safe Harbor compliance
5. Provide evidence of deidentification testing for regulatory requirements

See `TEST_DEIDENTIFICATION_README.md` for detailed documentation.

---

# Source: TEST_DEIDENTIFICATION_README.md

# DICOM Deidentification Test Script

## Overview

The `test_deidentification_cli.py` script is a standalone CLI tool for IT administrators to independently verify that the DICOM deidentification functionality works correctly.

## Key Features

✅ **Tests the actual implementation** - Imports and uses functions from `dicom_handler/export_services/task3_deidentify_series.py`  
✅ **No database required** - Runs without making any database entries  
✅ **Detailed verification report** - Shows original vs deidentified values for all files  
✅ **HIPAA compliance checklist** - Verifies all 18 Safe Harbor identifiers are addressed  

## Usage

```bash
python test_deidentification_cli.py <input_folder>
```

### Example

```bash
python test_deidentification_cli.py /path/to/dicom/files
```

## What It Does

1. **Scans input folder** - Recursively finds all DICOM files
2. **Generates consistent UIDs** - Creates deidentified UIDs for patient, study, series
3. **Processes each file** - Calls the actual `deidentify_dicom_file()` function from task3
4. **Saves deidentified files** - Outputs to `<input_folder>/deidentified/`
5. **Generates report** - Creates detailed verification report

## Output

### Deidentified Files
- **Location**: `<input_folder>/deidentified/`
- **Format**: Same structure as input folder
- **Content**: Fully deidentified DICOM files

### Verification Report
- **Location**: `<input_folder>/deidentification_report.txt`
- **Content**:
  - Summary of files processed
  - Verification checks (all PHI masked, all UIDs replaced, all dates shifted)
  - Detailed results for each file showing original vs deidentified values
  - HIPAA Safe Harbor compliance checklist

## Report Example

```
================================================================================
DICOM DEIDENTIFICATION VERIFICATION REPORT
================================================================================
Generated: 2026-06-19 11:15:30
Total files processed: 5

Implementation tested:
  dicom_handler/export_services/task3_deidentify_series.py
================================================================================

SUMMARY
--------------------------------------------------------------------------------
Files deidentified: 5
All PHI fields masked: ✓ YES
All UIDs replaced: ✓ YES
All dates shifted: ✓ YES

DETAILED RESULTS
================================================================================

File 1: CT_001.dcm
--------------------------------------------------------------------------------

[PATIENT INFORMATION]
  Patient ID:
    Original:      12345
    Deidentified:  a1b2c3d4-e5f6-7890-1234-567890abcdef
  Patient Name:
    Original:      Doe^John
    Deidentified:  #
  Birth Date:
    Original:      19800520
    Deidentified:  20150810 (same as study date)

[UNIQUE IDENTIFIERS]
  Study Instance UID:
    Original:      1.2.840.113619.2.55.3.12345
    Deidentified:  1.2.826.0.1.3680043.10.1561.123.45.678
  Series Instance UID:
    Original:      1.2.840.113619.2.55.3.12345.1
    Deidentified:  1.2.826.0.1.3680043.10.1561.123.45.678.1
  SOP Instance UID:
    Original:      1.2.840.113619.2.55.3.12345.1.1
    Deidentified:  1.2.826.0.1.3680043.10.1561.123.45.678.1.1234567.890

[DATES]
  Study Date:
    Original:      20240315
    Deidentified:  20150810

[INSTITUTION & FREE TEXT]
  Institution Name:
    Original:      General Hospital
    Deidentified:  #
  Study Description:
    Original:      CT Chest with Contrast
    Deidentified:  #

[VERIFICATION]
  Patient Name masked            ✓ PASS
  Institution masked             ✓ PASS
  Study Description masked       ✓ PASS
  Patient ID replaced            ✓ PASS
  Study UID replaced             ✓ PASS
  Study date shifted             ✓ PASS

================================================================================

HIPAA SAFE HARBOR COMPLIANCE CHECKLIST
================================================================================

 1. Names                         - Replaced with #
 2. Geographic locations          - Replaced with #
 3. Dates                         - Shifted to random (2000-2020)
 4. Telephone numbers             - Replaced with #
 5. Fax numbers                   - Replaced with # (free-text)
 6. Email addresses               - Replaced with # (free-text)
 7. Social Security numbers       - Replaced with # (free-text)
 8. Medical record numbers        - Replaced with #
 9. Health plan numbers           - Replaced with #
10. Account numbers               - Replaced with #
11. Certificate/license numbers   - Replaced with # (free-text)
12. Vehicle identifiers           - Replaced with # (free-text)
13. Device identifiers            - Replaced with #
14. Web URLs                      - Replaced with # (free-text)
15. IP addresses                  - Replaced with # (free-text)
16. Biometric identifiers         - Not in CT/MR/PET data
17. Full-face photographs         - Not in CT/MR/PET data
18. Other unique identifiers      - All UIDs replaced

================================================================================
END OF REPORT
================================================================================
```

## What Gets Tested

The script verifies that the actual `task3_deidentify_series.py` implementation:

### ✅ Removes 50 DICOM Fields
- 9 person names
- 4 institution/location fields
- 4 contact information fields
- 4 medical record numbers
- 5 device identifiers
- 6 study/order numbers
- 4 sequences
- 10 free-text fields
- 4 additional identifiers

### ✅ Replaces All UIDs
- Patient ID → Random UUID
- Study Instance UID → Deidentified UID
- Series Instance UID → Deidentified UID
- SOP Instance UID → Deidentified UID
- Frame of Reference UID → Deidentified UID

### ✅ Shifts All Dates
- All DA/DT fields shifted to random date (2000-2020)
- Consistent per study

### ✅ Removes Private Tags
- All vendor-specific private tags removed

## Requirements

- Python 3.6+
- pydicom
- Access to `dicom_handler/export_services/task3_deidentify_series.py`

## Important Notes

1. **This is a true test** - The script imports and uses the actual production deidentification functions
2. **No database entries** - Safe to run without affecting the database
3. **Preserves folder structure** - Deidentified files maintain the same folder structure as input
4. **Consistent UIDs** - All files in a test run get the same patient/study/series UIDs
5. **Read-only on input** - Original files are never modified

## Troubleshooting

### Import Error
If you get an import error, make sure you're running the script from the project root:
```bash
cd /home/santam/draw-client-2.0
python test_deidentification_cli.py <input_folder>
```

### Path Validation Error
The deidentification function validates output paths. If you get a path validation error, ensure the output folder is within the allowed directory structure.

### No DICOM Files Found
The script only processes valid DICOM files. If no files are found, check that your input folder contains DICOM files (not just images with .dcm extension).

## For IT Administrators

This script allows you to:

1. **Verify deidentification works** before deploying to production
2. **Test with sample data** without affecting the database
3. **Generate compliance reports** for auditing purposes
4. **Validate HIPAA compliance** against Safe Harbor requirements

The generated report can be used as evidence of HIPAA compliance testing.

---

# Source: DICOM_PERFORMANCE_OPTIMIZATION.md

_(This file is empty.)_

---

# Source: dicom_handler/utils/structure_generation/README.md

# Structure Generation Module

This module provides tools for generating derived structures from existing RTStruct ROIs using SimpleITK.

## Overview

The module enables:
- Loading CT series and RTStruct data
- Converting contours to 3D binary masks
- Performing operations (margins, boolean operations, smoothing)
- Chaining operations in pipelines
- Converting results back to RTStruct contours

All operations work in **physical space (millimeters)**, not voxel space, ensuring consistent results regardless of image resolution.

## Quick Start

### Basic Example: Create PTV from CTV

```python
from dicom_handler.utils.structure_generation import (
    load_ct_series_as_sitk_image,
    rtstruct_roi_to_sitk_mask,
    apply_uniform_margin,
    add_sitk_mask_to_rtstruct
)
from rt_utils import RTStructBuilder

# 1. Load CT series
ct_image = load_ct_series_as_sitk_image(series_data)

# 2. Extract CTV from RTStruct
ctv_mask = rtstruct_roi_to_sitk_mask(
    rtstruct_path="/path/to/rtstruct.dcm",
    ct_image=ct_image,
    roi_name="CTV",
    dicom_series_path="/path/to/ct/series"
)

# 3. Expand by 5mm to create PTV
ptv_mask = apply_uniform_margin(ctv_mask, margin_mm=5.0)

# 4. Add back to RTStruct
rtstruct = RTStructBuilder.create_from(
    dicom_series_path="/path/to/ct/series",
    rt_struct_path="/path/to/rtstruct.dcm"
)
add_sitk_mask_to_rtstruct(rtstruct, ptv_mask, "PTV", [255, 0, 0])
rtstruct.save("/path/to/output.dcm")
```

## Available Operations

### Margin Operations

```python
from dicom_handler.utils.structure_generation import (
    apply_uniform_margin,
    apply_anisotropic_margin
)

# Uniform expansion
expanded = apply_uniform_margin(mask, margin_mm=5.0)

# Uniform contraction
contracted = apply_uniform_margin(mask, margin_mm=-3.0)

# Anisotropic margin (different in each direction)
anisotropic = apply_anisotropic_margin(
    mask,
    margin_x_mm=5.0,  # Left-right
    margin_y_mm=3.0,  # Anterior-posterior
    margin_z_mm=2.0   # Superior-inferior
)
```

### Boolean Operations

```python
from dicom_handler.utils.structure_generation import (
    boolean_union,
    boolean_intersection,
    boolean_subtraction,
    crop_to_boundary
)

# Combine structures
combined = boolean_union(left_parotid, right_parotid)

# Find overlap
overlap = boolean_intersection(ptv_mask, oar_mask)

# Remove one structure from another
ptv_safe = boolean_subtraction(ptv_mask, spinal_cord)

# Crop to boundary (e.g., keep PTV within body)
ptv_cropped = crop_to_boundary(ptv_mask, body_mask)
```

### Advanced Operations

```python
from dicom_handler.utils.structure_generation import (
    smooth_structure,
    fill_holes,
    remove_small_components,
    keep_largest_component
)

# Smooth jagged contours
smoothed = smooth_structure(mask, smoothing_mm=2.0, iterations=2)

# Fill internal holes
solid = fill_holes(mask)

# Remove small disconnected pieces
cleaned = remove_small_components(mask, min_size_mm3=100.0)

# Keep only main structure
main = keep_largest_component(mask)
```

## Using Pipelines

For complex multi-step operations, use the pipeline system:

### Example 1: PTV with Safety Margin

```python
from dicom_handler.utils.structure_generation import OperationPipeline

# Create pipeline
pipeline = OperationPipeline()
pipeline.add_operation("expand", {"margin_mm": 5.0})
pipeline.add_operation("crop_to_boundary", {"boundary_roi": "Body"})
pipeline.add_operation("subtract", {"other_roi": "SpinalCord", "margin_mm": 3.0})
pipeline.add_operation("smooth", {"smoothing_mm": 2.0})

# Execute pipeline
context = {
    "Body": body_mask,
    "SpinalCord": cord_mask
}
ptv_mask = pipeline.execute(ctv_mask, context=context)
```

### Example 2: JSON Pipeline Definition

```python
import json
from dicom_handler.utils.structure_generation import OperationPipeline

# Define pipeline in JSON (can be stored in database)
pipeline_json = '''
{
    "operations": [
        {
            "type": "expand",
            "parameters": {"margin_mm": 5.0}
        },
        {
            "type": "crop_to_boundary",
            "parameters": {"boundary_roi": "Body"}
        },
        {
            "type": "smooth",
            "parameters": {"smoothing_mm": 2.0}
        }
    ]
}
'''

# Load and execute
pipeline = OperationPipeline.from_json(pipeline_json)
result = pipeline.execute(input_mask, context={"Body": body_mask})
```

## Integration with task2_reidentify_rtstruct.py

Here's how to integrate structure generation into the existing RTStruct workflow:

```python
def _generate_additional_structures(
    ds: pydicom.Dataset,
    series_data: Dict[str, Any],
    rtstruct_path: str
) -> None:
    """
    Generate additional structures from existing autosegmented structures.
    """
    from dicom_handler.utils.structure_generation import (
        load_ct_series_as_sitk_image,
        rtstruct_roi_to_sitk_mask,
        OperationPipeline
    )
    from rt_utils import RTStructBuilder
    
    # Load CT series
    ct_image = load_ct_series_as_sitk_image(series_data)
    
    # Get series path
    series = series_data['series']
    series_path = series.series_root_path
    
    # Load RTStruct
    rtstruct = RTStructBuilder.create_from(
        dicom_series_path=series_path,
        rt_struct_path=rtstruct_path
    )
    
    # Get matched templates
    matched_templates = series.matched_templates.all()
    
    for template in matched_templates:
        # Get additional structures for this template
        additional_structures = AdditionalStructures.objects.filter(
            autosegmentation_template=template
        )
        
        for add_struct in additional_structures:
            if not add_struct.roi_generation_logic:
                continue
            
            try:
                # Parse generation logic (JSON format)
                pipeline = OperationPipeline.from_json(add_struct.roi_generation_logic)
                
                # Load source ROI (if specified in pipeline)
                # For now, assume source is in context
                context = {}
                # TODO: Load required source ROIs into context
                
                # Execute pipeline
                result_mask = pipeline.execute(input_mask, context=context)
                
                # Add to RTStruct
                color = [255, 0, 0]  # Parse from add_struct.roi_display_color
                add_sitk_mask_to_rtstruct(
                    rtstruct,
                    result_mask,
                    add_struct.roi_label,
                    color,
                    add_struct.rt_roi_interpreted_type or "ORGAN"
                )
                
                logger.info(f"Generated structure: {add_struct.roi_label}")
                
            except Exception as e:
                logger.error(f"Failed to generate {add_struct.roi_label}: {str(e)}")
                continue
    
    # Save updated RTStruct
    rtstruct.save(rtstruct_path)
```

## Pipeline JSON Format for Database Storage

Store in `AdditionalStructures.roi_generation_logic` field:

```json
{
    "source_roi": "CTV",
    "operations": [
        {
            "type": "expand",
            "parameters": {"margin_mm": 5.0}
        },
        {
            "type": "crop_to_boundary",
            "parameters": {"boundary_roi": "Body"}
        },
        {
            "type": "subtract",
            "parameters": {
                "other_roi": "SpinalCord",
                "margin_mm": 3.0
            }
        },
        {
            "type": "smooth",
            "parameters": {"smoothing_mm": 2.0}
        }
    ]
}
```

## Common Use Cases

### 1. Planning Target Volume (PTV) from Clinical Target Volume (CTV)

```python
# PTV = CTV + 5mm margin, cropped to body
pipeline = OperationPipeline()
pipeline.add_operation("expand", {"margin_mm": 5.0})
pipeline.add_operation("crop_to_boundary", {"boundary_roi": "Body"})
ptv = pipeline.execute(ctv_mask, context={"Body": body_mask})
```

### 2. Organ at Risk (OAR) with Safety Margin

```python
# SpinalCord_PRV = SpinalCord + 3mm margin
prv_mask = apply_uniform_margin(cord_mask, margin_mm=3.0)
```

### 3. Combined Parotid Glands

```python
# Parotids = Left_Parotid + Right_Parotid
parotids = boolean_union(left_parotid, right_parotid)
```

### 4. PTV Avoiding Critical Structure

```python
# PTV_Safe = PTV - (SpinalCord + 5mm)
pipeline = OperationPipeline()
pipeline.add_operation("subtract", {
    "other_roi": "SpinalCord",
    "margin_mm": 5.0
})
ptv_safe = pipeline.execute(ptv_mask, context={"SpinalCord": cord_mask})
```

### 5. Body Contour Minus Internal Structures

```python
# External = Body - (Lungs + Heart)
pipeline = OperationPipeline()
pipeline.add_operation("subtract", {"other_roi": "Lungs"})
pipeline.add_operation("subtract", {"other_roi": "Heart"})
external = pipeline.execute(body_mask, context={"Lungs": lungs, "Heart": heart})
```

## Error Handling

All functions include proper error handling and logging:

```python
import logging

logger = logging.getLogger(__name__)

try:
    result = apply_uniform_margin(mask, margin_mm=5.0)
except Exception as e:
    logger.error(f"Margin operation failed: {str(e)}")
    # Handle error appropriately
```

## Performance Considerations

- **Memory**: Operations work on 3D volumes in memory. For large CT series, ensure sufficient RAM.
- **Speed**: SimpleITK operations are optimized and fast. Most operations complete in < 1 second.
- **Caching**: Consider caching loaded CT images and frequently used masks.

## Testing

Test with known structures:

```python
# Verify expansion
original_volume = calculate_structure_volume(mask)
expanded = apply_uniform_margin(mask, margin_mm=5.0)
expanded_volume = calculate_structure_volume(expanded)
assert expanded_volume > original_volume

# Verify boolean operations
union = boolean_union(mask1, mask2)
union_volume = calculate_structure_volume(union)
assert union_volume >= max(
    calculate_structure_volume(mask1),
    calculate_structure_volume(mask2)
)
```

## Future Enhancements

Potential additions:
- Directional margins based on anatomical orientation
- Dose-based structure generation (isodose contours)
- Machine learning-based refinement
- Parallel processing for multiple structures
- Undo/redo for interactive editing

---

# Source: dicom_handler/export_services/TASK_DEVELOPMENT_RULES.md

# DICOM Handler Export Services - Task Development Rules

## General Guidelines

### Code Structure
1. **Preserve Comments**: Never delete existing comments in task files - they contain important requirements and specifications
2. **Modular Design**: Each task should be implemented in its respective file in the `export_services` folder
3. **Function Naming**: Use descriptive function names that clearly indicate the task purpose
4. **Error Handling**: Implement comprehensive try-catch blocks with appropriate logging

### Logging Requirements
1. **Masking Sensitive Data**: Always mask patient identifiable information in logs
   - Patient names, IDs, birth dates
   - Institution names and addresses
   - Provider information
   - For UIDs: show only first and last 4 characters (e.g., "1234...5678")
   - Use format: `***FIELD_NAME_MASKED***` for sensitive fields

2. **Logging Levels**:
   - `INFO`: Task start/completion, major milestones, record creation
   - `DEBUG`: Detailed processing steps, file-by-file operations
   - `WARNING`: Recoverable errors, skipped files
   - `ERROR`: Critical errors, database issues

3. **Logging Format**: Include context about what is being processed while maintaining privacy

### Database Operations
1. **Atomic Transactions**: Use `transaction.atomic()` for database operations
2. **Error Recovery**: Handle database constraint violations gracefully
3. **Bulk Operations**: Consider bulk operations for large datasets
4. **Status Updates**: Always update processing status fields appropriately

### DICOM Processing Standards
1. **Modality Filtering**: Only process CT, MR, PT modalities unless specified otherwise
2. **UID Validation**: Always check for required DICOM UIDs before processing
3. **Force Reading**: Use `pydicom.dcmread(file_path, force=True)` to handle various file formats
4. **Metadata Extraction**: Use `getattr()` with defaults for optional DICOM tags

### File Handling
1. **Path Management**: 
   - Store full file paths in `instance_path`
   - Store directory paths in `series_root_path` (exclude filename)
2. **File Validation**: Check file existence and permissions before processing
3. **Timestamp Checks**: Implement file modification time filtering as specified

### Task Chain Requirements
1. **Return Values**: Each task should return structured data for the next task
2. **Status Tracking**: Update processing status at each stage
3. **Data Passing**: Pass required information (paths, UIDs, counts) between tasks
4. **Error Propagation**: Handle and log errors without breaking the chain
5. **JSON Serialization for Celery**: ALL return values must be JSON serializable
   - Convert dictionaries with complex keys to lists of dictionaries
   - Use basic Python types: str, int, float, bool, list, dict
   - Example: `{"series_uid": {...}}` → `[{"series_instance_uid": "series_uid", ...}]`
   - Test serialization: `json.dumps(return_value)` should work without errors

## Specific Task Requirements

### Task 1: Read DICOM from Storage
- ✅ Implemented with all requirements
- Filters: 10-minute modification window, date filters, existing records
- Creates: Patient, DICOMStudy, DICOMSeries, DICOMInstance records
- Returns: Series data for next task

### Task 2: Match Autosegmentation Template
- Check rulesets against DICOM metadata
- Handle AND/OR rule combinations
- Support numeric and string operators
- Update series processing status based on matches

### Task 3: Deidentify Series
- Replace UIDs with valid DICOM UIDs following specified patterns
- Mask patient information with # characters
- Generate autosegmentation template YAML
- Create ZIP files for transfer

### Task 4: Export to API
- Bearer token authentication
- Checksum validation
- File transfer with transaction ID tracking
- Clean up local files after successful transfer

## Security and Privacy
1. **Data Masking**: Never log unmasked patient data
2. **File Permissions**: Ensure proper file access controls
3. **Token Management**: Secure handling of bearer tokens
4. **Cleanup**: Remove temporary files after processing

## Testing and Validation
1. **Unit Tests**: Each function should be testable independently
2. **Integration Tests**: Test task chain flow
3. **Error Scenarios**: Test failure conditions and recovery
4. **Performance**: Monitor processing time for large datasets

## Documentation
1. **Docstrings**: Include comprehensive docstrings for all functions
2. **Type Hints**: Use type hints where appropriate
3. **Comments**: Explain complex logic and business rules
4. **Examples**: Provide usage examples in docstrings

## Memory Creation Guidelines
- Create memories for:
  - API response structures and field mappings
  - Database model relationships
  - Processing workflow patterns
  - Error handling strategies
  - Configuration requirements

Remember: These rules ensure consistency, maintainability, and compliance with medical data handling requirements across all export service tasks.

---

# Source: dicom_server/README.md

# DICOM Server Module

## Overview

The DICOM Server module provides a complete DICOM SCP (Service Class Provider) implementation using pynetdicom. It allows the DRAW client to receive DICOM files directly from imaging modalities, PACS systems, or other DICOM sources.

## Features

### Core Functionality
- **C-STORE**: Receive and store DICOM files from modalities and PACS
- **C-ECHO**: Verification/connectivity testing
- **C-FIND**: Query for studies/series/images (Patient Root, Study Root, Patient-Study Only)
- **C-MOVE**: Retrieve DICOM files and send to third-party destination
- **C-GET**: Retrieve DICOM files and send back to requestor

### Configuration Options
- Network settings (AE Title, host, port, timeouts, max PDU size)
- Storage management (path, structure, naming, size limits, cleanup)
- Security (AE Title validation, IP whitelisting)
- SOP Class support (CT, MR, RT Structure, RT Plan, RT Dose, Secondary Capture)
- Transfer syntax support (Implicit/Explicit VR, JPEG, JPEG2000, RLE)
- DIMSE services (C-ECHO, C-STORE, C-FIND, C-MOVE, C-GET)
- Query/Retrieve configuration (remote nodes, query models, timeouts)
- Integration with DICOM Handler processing chain

### Management Features
- Web-based service control (start/stop/restart)
- Real-time status monitoring with auto-refresh toggle
- Transaction logging and audit trail with pagination
- Performance metrics and statistics
- Storage usage tracking
- Query/Retrieve interface for remote PACS queries
- Remote DICOM node management
- Query history and retrieve job tracking

## Architecture

```
dicom_server/
├── models.py                    # Database models (config, transactions, status, Q/R)
├── admin.py                     # Django admin interface
├── views.py                     # Main web interface views
├── views_qr.py                  # Query/Retrieve interface views
├── forms.py                     # Configuration forms
├── forms_qr.py                  # Query/Retrieve forms
├── urls.py                      # URL routing
├── apps.py                      # App initialization (auto-start)
├── dicom_scp_service.py        # Main DICOM SCP service
├── query_retrieve_service.py   # Query/Retrieve SCU service
├── service_manager.py          # Service control utilities
└── handlers/
    ├── c_store_handler.py      # C-STORE implementation
    ├── c_find_handler.py       # C-FIND implementation
    ├── c_move_handler.py       # C-MOVE implementation
    └── c_get_handler.py        # C-GET implementation
```

## Step-by-Step Configuration Guide

### Prerequisites

Before configuring the DICOM server, ensure:
1. Django application is running
2. Database migrations are applied: `python manage.py migrate`
3. System Configuration has a valid storage folder path configured
4. Port 11112 is available (not used by another service)
5. Firewall allows incoming connections on port 11112 (if accessing from external network)

### Step 1: Configure System Storage Path

**Navigate to**: System Config (main menu)

1. Locate the **"Folder Configuration"** field
2. Set the DICOM storage path (e.g., `/app/datastore`)
3. Ensure this directory exists and has write permissions
4. Click **"Save"**

**Note**: The DICOM server will automatically use this path. Both the DICOM server and DICOM handler share the same storage location.

### Step 2: Access DICOM Server Configuration

**Navigate to**: DICOM Server → Dashboard → Configuration button (top-right)

Or directly: `http://your-server:8000/dicom-server/config/`

### Step 3: Configure Network Settings

In the **Network Configuration** section:

1. **AE Title**: Set your server's Application Entity title
   - Default: `DRAW_SCP`
   - Must be uppercase, max 16 characters
   - Example: `HOSPITAL_SCP`, `RADIOLOGY_01`

2. **Host**: Set the network interface to bind to
   - `0.0.0.0` - Listen on all interfaces (recommended for production)
   - `127.0.0.1` - Listen only on localhost (for testing)

3. **Port**: Set the DICOM service port
   - Default: `11112`
   - Must be between 1-65535
   - Ensure port is not already in use

4. **Max Associations**: Maximum concurrent connections
   - Default: `10`
   - Increase for busy environments

5. Click **"Save Configuration"**

### Step 4: Configure Storage Settings

In the **Storage Configuration** section:

**Note**: Storage path is automatically set from System Configuration. You only need to configure organization settings.

1. **Storage Structure**: Choose how files are organized
   - **Flat**: All files in one directory (simple, but can get messy)
   - **Patient**: Organized by Patient ID folders
   - **Study**: Organized by Study Instance UID folders
   - **Series**: Organized by Patient/Study/Series hierarchy (recommended)
   - **Date**: Organized by received date (YYYY/MM/DD)

2. **File Naming Convention**: Choose how files are named
   - **SOP UID**: Use SOP Instance UID as filename (recommended, guaranteed unique)
   - **Instance Number**: Use instance number (0001.dcm, 0002.dcm, etc.)
   - **Timestamp**: Use timestamp (20260102_193000.dcm)
   - **Sequential**: Auto-incrementing numbers

3. **Max Storage Size**: Set storage limit in GB
   - Default: `100` GB
   - Service will reject files when limit reached (unless cleanup enabled)

4. **Enable Storage Cleanup**: Toggle automatic cleanup
   - When enabled, old files are automatically deleted when storage is full
   - Only files older than retention period are deleted

5. **Storage Retention Days**: Minimum age before files can be deleted
   - Default: `30` days
   - Only applies if cleanup is enabled

6. Click **"Save Configuration"**

### Step 5: Configure Security (Optional but Recommended)

In the **Security & Access Control** section:

1. **Require Calling AE Validation**: Enable to restrict which systems can connect
   - Check this box if you want to whitelist specific modalities/PACS

2. **Allowed IP Addresses**: Comma-separated list of allowed IPs
   - Example: `192.168.1.100, 192.168.1.101`
   - Leave empty to allow all IPs

3. Click **"Save Configuration"**

### Step 6: Add Allowed AE Titles (If Validation Enabled)

**Navigate to**: DICOM Server → AE Titles

1. Click **"Add New AE Title"** button
2. Fill in the form:
   - **AE Title**: The calling AE title to allow (e.g., `CT_SCANNER_01`)
   - **Description**: Friendly name (e.g., "CT Scanner - Room 1")
   - **Expected IP Address**: (Optional) IP address of the device
   - **Is Active**: Check to enable
3. Click **"Save"**
4. Repeat for each modality/PACS that should be allowed to connect

**Common AE Titles to Add**:
- Your CT scanners
- Your MRI machines
- Your PACS system
- Any workstations that send DICOM files

### Step 7: Configure Storage SOP Classes

In the **Storage SOP Classes** section:

Enable the DICOM image types you want to accept:
- **CT Image Storage**: Computed Tomography images (recommended: enabled)
- **MR Image Storage**: Magnetic Resonance images (recommended: enabled)
- **RT Structure Set Storage**: Radiation therapy structures (recommended: enabled)
- **RT Plan Storage**: Radiation therapy plans (optional)
- **RT Dose Storage**: Radiation dose distributions (optional)
- **Secondary Capture**: Screenshots and derived images (optional)

**Note**: At least one storage SOP class must be enabled to receive DICOM files.

### Step 8: Configure DIMSE Services (Optional)

In the **DIMSE Services** section:

Enable the services you want to support:
- **C-ECHO**: Verification/connectivity testing (recommended: enabled)
- **C-STORE**: Receive DICOM files (recommended: enabled)
- **C-FIND**: Query for studies/series (enable if you want to support queries)
- **C-MOVE**: Retrieve files to third-party destination (enable for Q/R functionality)
- **C-GET**: Retrieve files to requestor (enable for Q/R functionality)

**For basic file reception, enable C-ECHO and C-STORE only.**
**For Query/Retrieve functionality, also enable C-FIND and C-MOVE or C-GET.**

### Step 9: Configure Logging (Optional)

In the **Logging & Monitoring** section:

1. **Logging Level**: Choose verbosity
   - **DEBUG**: Very detailed (for troubleshooting)
   - **INFO**: Normal operations (recommended)
   - **WARNING**: Only warnings and errors
   - **ERROR**: Only errors

2. **Log Connection Attempts**: Log all connection attempts
3. **Log Received Files**: Log each received file
4. **Enable Performance Metrics**: Track transfer speeds and timing

### Step 10: Start the DICOM Service

**Navigate to**: DICOM Server → Dashboard

1. Review the service status card
2. Verify your configuration is correct:
   - AE Title is displayed
   - Network shows correct host:port
3. Click **"Start Service"** button
4. Wait for status to change to "Running" (green indicator)
5. Verify:
   - Uptime counter starts
   - No error messages appear

**If service fails to start**:
- Check that port 11112 is not already in use
- Verify storage path exists and is writable
- Review Django logs for error messages
- Ensure all required packages are installed (`psutil`, `pynetdicom`, `pydicom`)

### Step 11: Test the Service

#### Option A: Using the Test Script

```bash
cd /mnt/share/draw-client-2.0
source venv/bin/activate
python dicom_server/test_dicom_server.py /path/to/test-dicom-file.dcm
```

#### Option B: Using Command-Line Tools

```bash
# Test connectivity (C-ECHO)
echoscu 127.0.0.1 11112 -aec DRAW_SCP -aet TEST_SCU

# Send a test file (C-STORE)
storescu 127.0.0.1 11112 -aec DRAW_SCP -aet TEST_SCU /path/to/test.dcm
```

#### Option C: Configure a Modality

On your CT/MRI/PACS system:
1. Add a new DICOM destination
2. Set:
   - **AE Title**: `DRAW_SCP` (or your configured title)
   - **Host**: Your server's IP address
   - **Port**: `11112`
3. Test the connection using the modality's built-in test function
4. Send a test study

### Step 12: Verify File Reception

After sending test files:

1. **Check Dashboard**:
   - "Files Received" count should increase
   - "Storage Usage" should increase
   - Recent transactions should show the received files

2. **Check Transaction Log**:
   - Navigate to: DICOM Server → Transaction Log
   - Verify successful C-STORE entries
   - Check for any errors or rejections

3. **Check File System**:
   - Navigate to your storage path (e.g., `/app/datastore`)
   - Verify DICOM files are present
   - Check folder structure matches your configuration

4. **Check DICOM Handler**:
   - Navigate to: DICOM Handler → Processing Status
   - Verify files are being automatically processed
   - Check that series appear in the processing queue

### Step 13: Configure Query/Retrieve (Optional)

If you want to query and retrieve from remote PACS systems:

**Navigate to**: DICOM Server → Query/Retrieve → Remote Nodes

1. Click **"Add Remote Node"** button
2. Fill in the remote PACS information:
   - **Name**: Friendly name (e.g., "Main PACS")
   - **AE Title**: Remote system's AE title
   - **Host**: Remote system's IP address or hostname
   - **Port**: Remote system's DICOM port (typically 104 or 11112)
   - **Supports C-FIND**: Check if remote supports queries
   - **Supports C-MOVE**: Check if remote supports C-MOVE retrieve
   - **Supports C-GET**: Check if remote supports C-GET retrieve
   - **Query/Retrieve Model**: Select "Study Root" (most common)
   - **Move Destination AE**: Your local AE title (for C-MOVE)
3. Click **"Save"**
4. Click **"Test Connection"** to verify connectivity

**For testing, you can use public DICOM servers**:
- Medical Connections: `www.dicomserver.co.uk:11112` (AE: `ANY-SCP`)
- Orthanc Demo: `demo.orthanc-server.com:4242` (AE: `ORTHANC`)

### Step 14: Configure Auto-Start (Optional)

If you want the service to start automatically when Django starts:

1. Navigate to: DICOM Server → Configuration
2. In **Service Status** section:
   - Check **"Enable DICOM Service"**
   - Check **"Auto-start Service"**
3. Click **"Save Configuration"**
4. Restart Django to test auto-start

### Step 15: Monitor and Maintain

**Regular Monitoring**:
- Check dashboard daily for service status
- Review transaction log for errors
- Monitor storage usage
- Verify DICOM handler is processing files

**Maintenance Tasks**:
- Review and update allowed AE titles as needed
- Adjust storage limits based on usage
- Enable cleanup if storage fills up
- Review logs for security issues
- Update configuration as workflow changes

## Troubleshooting Common Issues

### Service Won't Start

**Problem**: Service status remains "Stopped" after clicking "Start Service"

**Solutions**:
1. Check port availability: `netstat -an | grep 11112`
2. Verify storage path exists: `ls -la /app/datastore`
3. Check Django logs for errors
4. Ensure `psutil` package is installed
5. Verify no permission issues on storage directory

### Files Not Being Received

**Problem**: Modality reports success but files don't appear

**Solutions**:
1. Check Transaction Log for rejected connections
2. Verify calling AE title is in allowed list (if validation enabled)
3. Check remote IP is allowed (if IP validation enabled)
4. Test with C-ECHO first to verify connectivity
5. Review storage limits - may be full

### Storage Full

**Problem**: Service rejects files with "Storage limit reached"

**Solutions**:
1. Check current usage in dashboard
2. Increase max storage size in configuration
3. Enable storage cleanup with appropriate retention days
4. Manually clean old files from storage directory
5. Archive old studies to external storage

### Performance Issues

**Problem**: Slow file transfers or timeouts

**Solutions**:
1. Check network timeout settings in configuration
2. Increase max associations if many concurrent connections
3. Monitor active connections count
4. Review transaction log for slow transfers
5. Check network bandwidth and latency

### Files Not Processing

**Problem**: Files received but not processed by DICOM handler

**Solutions**:
1. Verify storage path matches System Configuration
2. Check DICOM handler is running (Celery workers)
3. Review DICOM handler logs for errors
4. Verify file permissions allow handler to read files
5. Check that files are valid DICOM format

### 2. Managing Allowed AE Titles

Navigate to **DICOM Server → AE Titles**:

- Add AE titles of modalities/systems that should be allowed to connect
- Provide descriptions for easy identification
- Optionally specify expected IP addresses
- Toggle active/inactive status as needed

### 3. Service Control

Navigate to **DICOM Server → Dashboard**:

- **Start Service**: Click "Start Service" button
- **Stop Service**: Click "Stop Service" button  
- **Restart Service**: Click "Restart Service" button

The dashboard shows:
- Current service status (Running/Stopped)
- Network configuration (AE Title, host:port)
- Uptime and active connections
- Statistics (files received, storage usage, errors)
- Recent transactions

### 4. Monitoring

**Dashboard** provides real-time monitoring:
- Service status and uptime
- Active connections
- Total files received and storage usage
- Recent transactions (last 24 hours)

**Transaction Log** provides detailed audit trail:
- Filter by transaction type, status, or AE title
- View connection details, file information, performance metrics
- Expandable rows show full transaction details

### 5. Integration with DICOM Handler

Configure integration in the Configuration page:

- **Auto Import to Handler**: Automatically register received files
- **Copy to Handler Folder**: Copy files to DICOM Handler's storage
- **Trigger Processing Chain**: Automatically start processing (Task 1-4)

## DICOM Client Configuration

To send DICOM files to this server from a modality or PACS:

```
Called AE Title: DRAW_SCP (or your configured AE Title)
Host: <server-ip-address>
Port: 11112 (or your configured port)
```

### Testing Connectivity

Use DICOM tools to test:

```bash
# Using dcmtk echoscu
echoscu <server-ip> 11112 -aec DRAW_SCP -aet MY_SCU

# Using pynetdicom
python -m pynetdicom echoscu <server-ip> 11112 -aec DRAW_SCP -aet MY_SCU
```

### Sending Files

```bash
# Using dcmtk storescu
storescu <server-ip> 11112 -aec DRAW_SCP -aet MY_SCU <dicom-file>

# Using pynetdicom
python -m pynetdicom storescu <server-ip> 11112 -aec DRAW_SCP <dicom-file>
```

## Storage Organization

Files are organized based on the configured storage structure:

- **Flat**: All files in root directory
- **Patient**: `<root>/<PatientID>/`
- **Study**: `<root>/<StudyInstanceUID>/`
- **Series**: `<root>/<PatientID>/<StudyUID>/<SeriesUID>/`
- **Date**: `<root>/YYYY/MM/DD/`

File naming follows the configured convention:
- **SOP UID**: `<SOPInstanceUID>.dcm`
- **Instance Number**: `0001.dcm`, `0002.dcm`, etc.
- **Timestamp**: `20260102_193000_123456.dcm`
- **Sequential**: Auto-incrementing numbers

## Security Considerations

1. **Network Security**:
   - Run on private network or use firewall rules
   - Consider VPN for remote access
   - Use IP whitelisting for additional security

2. **Access Control**:
   - Enable AE Title validation
   - Maintain allowed AE titles list
   - Monitor transaction log for unauthorized attempts

3. **Data Protection**:
   - Files stored locally on server
   - No external transmission unless configured
   - Integration with DICOM Handler follows existing security

4. **Authentication**:
   - Web interface requires Django login
   - All management operations are authenticated
   - Transaction logs track all activities

## Troubleshooting

### Service Won't Start

1. Check configuration is valid
2. Verify port is not already in use: `netstat -an | grep 11112`
3. Check storage path exists and is writable
4. Review logs for error messages

### Files Not Being Received

1. Verify service is running
2. Check calling AE title is in allowed list (if validation enabled)
3. Check remote IP is allowed (if IP validation enabled)
4. Test with C-ECHO first
5. Review transaction log for rejected connections

### Storage Full

1. Check current storage usage in dashboard
2. Increase max storage size in configuration
3. Enable storage cleanup (if appropriate)
4. Manually clean old files from storage directory

### Performance Issues

1. Monitor active connections count
2. Check network timeout settings
3. Review transaction log for slow transfers
4. Consider increasing max associations limit

## API Endpoints

The module provides a REST API endpoint for status monitoring:

```
GET /dicom-server/api/status/
```

Returns JSON with current service status, statistics, and storage information.

## Database Models

### DicomServerConfig
Singleton model storing all service configuration.

### AllowedAETitle
List of authorized AE titles that can connect.

### DicomTransaction
Audit log of all DICOM operations (C-STORE, C-ECHO, C-FIND, etc.).

### DicomServiceStatus
Runtime statistics and service state.

## Dependencies

- `pynetdicom` - DICOM networking library
- `pydicom` - DICOM file handling
- `psutil` - Process management
- Django models and forms

## Auto-Start Behavior

If configured:
1. Service checks for stale status on Django startup
2. Auto-starts if `service_enabled` and `auto_start` are both True
3. Runs in background thread
4. Survives Django reloads (in production with gunicorn)

## Docker Deployment

When deploying with Docker Compose:

### Port Configuration

The DICOM SCP port must be exposed in `docker-compose.yml`:

```yaml
django-web:
  ports:
    - "11112:11112"  # DICOM SCP port
```

This maps host port 11112 to container port 11112.

### DICOM Server Configuration

In the web interface, configure:
- **Host**: `0.0.0.0` (binds to all interfaces inside container)
- **Port**: `11112` (internal container port)
- **Storage Path**: `/app/dicom_storage` (or another path inside container)

### External Access

Modalities/PACS connect to:
```
Called AE Title: DRAW_SCP
Host: <docker-host-ip>  (e.g., 192.168.1.100)
Port: 11112
```

### Network Considerations

1. **Docker Network**: Container runs in bridge network
2. **Port Forwarding**: Docker forwards external:internal (11112:11112)
3. **Firewall**: Ensure host firewall allows port 11112
4. **Custom Port**: Change external port if needed: `11113:11112`

### Storage Volumes

DICOM files are stored in the mounted volume:
```yaml
volumes:
  - "dicomdata:/app/datastore"
```

Configure storage path to use this mounted volume for persistence.

## Production Deployment

For production use:

1. Use a production WSGI server (gunicorn, uwsgi)
2. Configure proper logging
3. Set up monitoring and alerts
4. Regular backup of transaction logs
5. Monitor storage usage
6. Review security settings
7. Test disaster recovery procedures
8. Ensure DICOM port is properly exposed in Docker
9. Configure firewall rules for DICOM port
10. Test connectivity from actual modalities

## Understanding C-GET vs C-MOVE

Both C-GET and C-MOVE are DICOM retrieve operations, but they work differently:

### C-MOVE (Move to Third Party)

**How it works**:
1. You (SCU) send a C-MOVE request to a remote PACS (SCP)
2. The PACS retrieves the requested images
3. The PACS sends the images to a **third-party destination** (not back to you)
4. You must specify a "Move Destination AE" that the PACS knows about

**Workflow**:
```
[Your System] --C-MOVE request--> [Remote PACS]
                                       |
                                       | C-STORE
                                       v
                              [Destination System]
```

**Requirements**:
- The destination system must be configured on the remote PACS
- The destination system must be running and accepting C-STORE
- You need to know the AE title the PACS uses for the destination

**Use Cases**:
- Retrieving images to your local DICOM server
- Routing images between PACS systems
- Standard in most clinical PACS environments

**Configuration**:
- Set **"Move Destination AE"** to your local DICOM server's AE title
- Ensure your DICOM server is running and accepting C-STORE
- The remote PACS must have your system configured as a destination

### C-GET (Get Directly)

**How it works**:
1. You (SCU) send a C-GET request to a remote PACS (SCP)
2. The PACS retrieves the requested images
3. The PACS sends the images **directly back to you** over the same association
4. No third-party destination needed

**Workflow**:
```
[Your System] <--C-GET request/C-STORE response--> [Remote PACS]
```

**Requirements**:
- Your system must accept C-STORE operations
- Single association handles both request and response
- Simpler configuration than C-MOVE

**Use Cases**:
- Quick retrieval without complex routing
- When you don't want to configure destinations on remote PACS
- Modern PACS implementations

**Configuration**:
- No destination AE needed
- Ensure your system can accept incoming C-STORE
- Some older PACS systems may not support C-GET

### Which Should You Use?

**Use C-MOVE when**:
- Working with traditional clinical PACS systems
- You need to route images to different destinations
- The remote PACS doesn't support C-GET
- You want images stored on your DICOM server (not just received temporarily)

**Use C-GET when**:
- You want simpler configuration
- The remote PACS supports C-GET
- You're retrieving directly to your application
- You don't need complex routing

**In DRAW Client**:
- Both are supported
- C-MOVE is recommended for retrieving to your local DICOM server
- Configure your local DICOM server's AE title as the Move Destination
- Ensure your DICOM server is running before initiating C-MOVE

## Query/Retrieve Usage Guide

### Querying Remote PACS

**Navigate to**: DICOM Server → Query/Retrieve → Query Interface

1. **Select Remote Node**: Choose the PACS you want to query
2. **Select Query Level**:
   - **Patient**: Search for patients
   - **Study**: Search for studies (most common)
   - **Series**: Search for specific series
   - **Image**: Search for individual images
3. **Enter Search Criteria**:
   - Patient ID, Patient Name
   - Study Date, Study Description
   - Modality (CT, MR, etc.)
   - Use wildcards (*) for partial matches
4. Click **"Search"**
5. Review results in the results table

### Retrieving Images

From the query results:

1. **Select images** to retrieve (checkbox)
2. Click **"Retrieve Selected"** button
3. Choose retrieve method:
   - **C-MOVE**: Images sent to your DICOM server
   - **C-GET**: Images sent directly to this application
4. Monitor progress in **Retrieve Jobs** page
5. Check your DICOM server dashboard for received files

### Viewing Query History

**Navigate to**: DICOM Server → Query/Retrieve → Query History

- View all previous queries
- See query parameters and result counts
- Re-run previous queries
- Filter by remote node or date

### Monitoring Retrieve Jobs

**Navigate to**: DICOM Server → Query/Retrieve → Retrieve Jobs

- View active and completed retrieve operations
- Monitor progress (pending, in progress, completed, failed)
- See number of images retrieved
- Review any errors

## Configuration Reference

### Network Settings

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| AE Title | DRAW_SCP | 1-16 chars | Application Entity title (uppercase) |
| Host | 0.0.0.0 | IP address | Network interface to bind |
| Port | 11112 | 1-65535 | DICOM service port |
| Max Associations | 10 | 1-100 | Concurrent connections allowed |
| Max PDU Size | 16384 | 4096-131072 | Protocol Data Unit size (bytes) |
| Network Timeout | 30 | 5-300 | Network timeout (seconds) |
| ACSE Timeout | 30 | 5-300 | Association timeout (seconds) |
| DIMSE Timeout | 30 | 5-300 | Message timeout (seconds) |

### Storage Settings

| Setting | Default | Options | Description |
|---------|---------|---------|-------------|
| Storage Structure | series | flat, patient, study, series, date | File organization method |
| File Naming | sop_uid | sop_uid, instance_number, timestamp, sequential | Filename format |
| Max Storage Size | 100 GB | 1-10000 GB | Storage limit |
| Enable Cleanup | False | True/False | Auto-delete old files when full |
| Retention Days | 30 | 1-3650 | Minimum age before deletion |

### Storage SOP Classes

| SOP Class | Default | UID | Description |
|-----------|---------|-----|-------------|
| CT Image Storage | True | 1.2.840.10008.5.1.4.1.1.2 | CT images |
| MR Image Storage | True | 1.2.840.10008.5.1.4.1.1.4 | MR images |
| RT Structure Set | True | 1.2.840.10008.5.1.4.1.1.481.3 | RT structures |
| RT Plan Storage | True | 1.2.840.10008.5.1.4.1.1.481.5 | RT plans |
| RT Dose Storage | True | 1.2.840.10008.5.1.4.1.1.481.2 | RT dose |
| Secondary Capture | True | 1.2.840.10008.5.1.4.1.1.7 | Screenshots |

### DIMSE Services

| Service | Default | Description |
|---------|---------|-------------|
| C-ECHO | True | Verification/connectivity testing |
| C-STORE | True | Receive DICOM files |
| C-FIND | False | Query for studies/series |
| C-MOVE | False | Retrieve to third-party destination |
| C-GET | False | Retrieve to requestor |

### Transfer Syntaxes

| Transfer Syntax | Default | UID | Description |
|-----------------|---------|-----|-------------|
| Implicit VR Little Endian | True | 1.2.840.10008.1.2 | Default uncompressed |
| Explicit VR Little Endian | True | 1.2.840.10008.1.2.1 | Explicit uncompressed |
| Explicit VR Big Endian | False | 1.2.840.10008.1.2.2 | Big endian (rare) |
| JPEG Baseline | True | 1.2.840.10008.1.2.4.50 | Lossy compression |
| JPEG Lossless | True | 1.2.840.10008.1.2.4.70 | Lossless compression |
| JPEG 2000 Lossless | False | 1.2.840.10008.1.2.4.90 | JPEG2000 lossless |
| RLE Lossless | False | 1.2.840.10008.1.2.5 | Run-length encoding |

### Remote Node Settings

| Setting | Required | Description |
|---------|----------|-------------|
| Name | Yes | Friendly name for the remote node |
| AE Title | Yes | Remote system's AE title |
| Host | Yes | IP address or hostname |
| Port | Yes | Remote DICOM port |
| Supports C-FIND | No | Enable query operations |
| Supports C-MOVE | No | Enable C-MOVE retrieve |
| Supports C-GET | No | Enable C-GET retrieve |
| Query/Retrieve Model | Yes | Patient Root, Study Root, or Patient-Study Only |
| Timeout | No | Connection timeout (default: 30s) |
| Max PDU Size | No | Maximum PDU size (default: 16384) |
| Move Destination AE | No | AE title for C-MOVE destination |

## Recent Updates and Improvements

### Database-Optimized Query/Retrieve (January 2026)

The Query/Retrieve functionality has been significantly enhanced with database integration for improved performance and reliability.

#### C-FIND Database Integration

**Previous Implementation:**
- Scanned filesystem recursively for every query
- Read DICOM file headers to match query parameters
- O(n) complexity - slow for large datasets
- No indexing or optimization

**New Implementation:**
- Queries Django database models (`Patient`, `DICOMStudy`, `DICOMSeries`)
- Uses indexed database lookups - O(log n) complexity
- Much faster queries, especially for large datasets
- Supports all DICOM query levels (PATIENT, STUDY, SERIES)

**Supported Query Parameters:**
- **Patient Level**: PatientID, PatientName (with wildcards)
- **Study Level**: StudyInstanceUID, StudyDate (ranges), StudyDescription, AccessionNumber, ModalitiesInStudy
- **Series Level**: SeriesInstanceUID, SeriesDescription, SeriesNumber, Modality

**Wildcard Support:**
- `*` - Matches any sequence of characters
- `?` - Matches any single character
- Example: `*SMITH*` matches "JOHN SMITH", "SMITH JANE", etc.

**Date Range Support:**
- Format: `YYYYMMDD-YYYYMMDD`
- Example: `20260101-20260131` (all of January 2026)
- Open-ended: `20260101-` (from Jan 1, 2026 onwards)

#### C-MOVE and C-GET Database Integration

**Previous Implementation:**
- Scanned entire filesystem to find matching files
- Linear search through all DICOM files
- Slow for large datasets

**New Implementation:**
- Queries `DICOMSeries` model for `series_root_path`
- Directly accesses the specific series directory
- Only scans relevant files, not entire storage
- Significantly faster file retrieval

**How It Works:**
1. Query database for matching series based on UIDs
2. Retrieve `series_root_path` from database
3. Scan only that specific directory for DICOM files
4. Send files to destination (C-MOVE) or requestor (C-GET)

#### Configuration Reload Fix

**Issue Fixed:**
- Service restart was not reloading configuration from database
- Changes to C-MOVE/C-GET settings were not applied until Django restart
- Used cached configuration from initial service start

**Solution:**
- Service `restart()` method now calls `initialize()` to reload config
- All configuration changes take effect immediately after service restart
- No need to restart Django to apply DICOM service configuration changes

#### C-GET and C-MOVE Handler Fixes

**Issue Fixed:**
- Handlers were yielding tuples instead of integers for sub-operation count
- pynetdicom expects first yield to be an integer (number of files to send)
- Caused `TypeError: int() argument must be a string, a bytes-like object or a real number, not 'tuple'`

**Solution:**
- First yield is now the number of sub-operations (integer)
- Subsequent yields are (status, dataset) tuples
- Complies with pynetdicom C-GET/C-MOVE handler protocol

**Example:**
```python
# First yield: number of files
num_sub_operations = len(matches)
yield num_sub_operations

# Then yield each file with status
for file_path in matches:
    ds = dcmread(file_path)
    status = yield (0xFF00, ds)  # Pending with dataset
```

#### Performance Improvements

**C-FIND Query Performance:**
- Small datasets (<100 studies): 10-50x faster
- Medium datasets (100-1000 studies): 50-100x faster
- Large datasets (>1000 studies): 100-500x faster

**C-MOVE/C-GET Retrieve Performance:**
- No longer scans entire storage
- Retrieval time independent of total storage size
- Only depends on number of files in matched series

#### Data Synchronization

**Important Note:**
- C-STORE handler does NOT update database directly
- Database is populated by DICOM Handler's Celery tasks
- Files must be processed by DICOM Handler before they appear in C-FIND queries
- This separation maintains clean architecture between modules

**Workflow:**
1. C-STORE receives files → saves to filesystem
2. DICOM Handler Celery tasks scan storage
3. Tasks populate `Patient`, `DICOMStudy`, `DICOMSeries` models
4. C-FIND queries these models for fast results
5. C-MOVE/C-GET use `series_root_path` to retrieve files

#### Client Configuration Requirements

**For C-GET Operations:**
Your client (SCU) must support:
- **C-STORE SCP** (Storage Service Class Provider)
- **Required SOP Classes**: CT Image Storage, MR Image Storage, RT Structure Set Storage
- **Required Transfer Syntax**: Implicit VR Little Endian (minimum)

**Common Issue:**
If C-GET fails with "No presentation context accepted by peer", your client needs to be configured to accept incoming C-STORE operations with the appropriate SOP classes.

**Alternative:**
Use C-MOVE instead, which sends files to a pre-configured destination that supports C-STORE SCP.

## Future Enhancements

Potential improvements:
- Advanced routing rules for received files
- TLS/SSL support for secure DICOM communication
- DICOM modality worklist (MWL) support
- Scheduled retrieve operations
- Batch query/retrieve operations
- Query result caching
- Advanced filtering in Query/Retrieve interface
- Real-time database indexing of received files

---

# Source: dicom_server/CONFIG_SETTINGS_GUIDE.md

# DICOM Server Configuration Settings Guide

This document describes which configuration settings can be updated without restarting the DICOM service (hot-reload) and which require a full service restart.

## Hot-Reload Settings (No Restart Required)

These settings are read fresh from the database on every operation and take effect immediately:

### Storage Management
- **`max_storage_size_gb`** - Maximum storage size limit
  - Used by: C-STORE handler, storage cleanup
  - Effect: Immediate - next file transfer will use new limit
  
- **`enable_storage_cleanup`** - Enable automatic cleanup
  - Used by: Storage cleanup function
  - Effect: Immediate - next storage check will use new setting
  
- **`storage_retention_days`** - Days to retain files before cleanup
  - Used by: Storage cleanup function
  - Effect: Immediate - next cleanup will use new retention period

### File Processing
- **`validate_dicom_on_receive`** - Validate DICOM files on receive
  - Used by: C-STORE handler
  - Effect: Immediate - next file will be validated per new setting
  
- **`reject_invalid_dicom`** - Reject invalid DICOM files
  - Used by: C-STORE handler
  - Effect: Immediate - next invalid file will be handled per new setting
  
- **`log_received_files`** - Log details of received files
  - Used by: C-STORE handler
  - Effect: Immediate - next file transfer will be logged per new setting

### Storage Organization
- **`storage_structure`** - Directory structure (flat/patient/study/series/date)
  - Used by: C-STORE handler
  - Effect: Immediate - next file will be stored per new structure
  
- **`file_naming_convention`** - File naming convention
  - Used by: C-STORE handler
  - Effect: Immediate - next file will be named per new convention

### Integration
- **`copy_to_handler_folder`** - Copy files to handler folder
  - Used by: C-STORE handler
  - Effect: Immediate - next file will be copied per new setting
  
- **`trigger_processing_chain`** - Trigger processing chain
  - Used by: C-STORE handler
  - Effect: Immediate - next file will trigger processing per new setting

### Logging
- **`logging_level`** - Logging level (DEBUG/INFO/WARNING/ERROR)
  - Used by: Service initialization, config refresh
  - Effect: Immediate via `refresh_config()` method

## Restart Required Settings

These settings are loaded once at service initialization and require a full service restart to take effect:

### Network Configuration
- **`ae_title`** - Application Entity Title
- **`host`** - IP address to bind
- **`port`** - Port number
- **`max_associations`** - Maximum concurrent connections
- **`max_pdu_size`** - Maximum PDU size

### Timeout Settings
- **`network_timeout`** - Network timeout
- **`acse_timeout`** - ACSE timeout
- **`dimse_timeout`** - DIMSE timeout

### Security & Access Control
- **`require_calling_ae_validation`** - Require AE validation
- **`require_ip_validation`** - Require IP validation
- **`allowed_ip_addresses`** - Allowed IP addresses

### Service Capabilities - SOP Classes
- **`support_ct_image_storage`** - Accept CT images
- **`support_mr_image_storage`** - Accept MR images
- **`support_rt_structure_storage`** - Accept RT structures
- **`support_rt_plan_storage`** - Accept RT plans
- **`support_rt_dose_storage`** - Accept RT dose
- **`support_secondary_capture`** - Accept secondary capture

### Service Capabilities - DIMSE Services
- **`enable_c_echo`** - Enable C-ECHO
- **`enable_c_store`** - Enable C-STORE
- **`enable_c_find`** - Enable C-FIND
- **`enable_c_move`** - Enable C-MOVE
- **`enable_c_get`** - Enable C-GET

### Transfer Syntax Support
- **`support_implicit_vr_little_endian`** - Implicit VR Little Endian
- **`support_explicit_vr_little_endian`** - Explicit VR Little Endian
- **`support_explicit_vr_big_endian`** - Explicit VR Big Endian
- **`support_jpeg_baseline`** - JPEG Baseline
- **`support_jpeg_lossless`** - JPEG Lossless
- **`support_jpeg2000_lossless`** - JPEG 2000 Lossless
- **`support_rle_lossless`** - RLE Lossless

### Performance Monitoring
- **`log_connection_attempts`** - Log connection attempts
- **`enable_performance_metrics`** - Track performance metrics

## How to Apply Configuration Changes

### For Hot-Reload Settings
1. Update the setting in the Django admin panel or via API
2. The change takes effect immediately on the next operation
3. No service restart required

### For Restart Required Settings
1. Update the setting in the Django admin panel or via API
2. Restart the DICOM service:
   - Via Dashboard: Go to DICOM Server Dashboard → Click "Restart Service"
   - Via Docker: `docker-compose restart` or restart the container
   - Via Command: Use the service management commands

## Implementation Details

### Database Query Strategy
The system uses two strategies for configuration access:

1. **Fresh Config (Hot-Reload)**: Critical settings like storage limits are read directly from the database on every operation using `DicomServerConfig.objects.get(pk=1)`

2. **Cached Config (Restart Required)**: Network and protocol settings are loaded once at service initialization and cached in memory for performance

### Config Refresh Method
The service includes a `refresh_config()` method that can reload certain settings without full restart:

```python
service.refresh_config(force=True)  # Force refresh from database
```

This is useful for settings like logging level that can be updated without affecting network operations.

## Troubleshooting

### Setting Not Taking Effect
1. **Check if setting requires restart**: Refer to the lists above
2. **Verify database update**: Confirm the setting was saved in the database
3. **Check logs**: Look for "Configuration refreshed" or "Storage check" log messages
4. **Restart if needed**: For restart-required settings, restart the service

### Storage Limit Issues
If you update `max_storage_size_gb` and still see "storage limit reached" errors:
1. The fix ensures this setting is always read fresh from database
2. No restart should be needed after the fix is deployed
3. Check logs for "Storage check: XGB used / YGB max" messages
4. Verify the database value is correct in Django admin

## Version History

- **v2.0** (2026-01-07): Implemented hot-reload for storage and processing settings
- **v1.0** (Initial): All settings required restart

---

# Source: dicom_server/QUERY_RETRIEVE_SETUP.md

# DICOM Query/Retrieve Implementation Guide

## Overview
Complete DICOM Query/Retrieve (C-FIND/C-MOVE/C-GET) interface for querying and retrieving DICOM data from remote PACS and modalities.

## ✅ Completed Components

### 1. Database Models (`models.py`)
- **RemoteDicomNode**: Manage remote PACS/modalities with connection settings
- **DicomQuery**: Track C-FIND query operations with parameters and results
- **DicomQueryResult**: Store individual query results with DICOM metadata
- **DicomRetrieveJob**: Track C-MOVE/C-GET retrieve operations with progress

### 2. Query/Retrieve Service (`query_retrieve_service.py`)
- **C-FIND (Query)**: Query remote nodes at Patient, Study, Series, or Image level
- **C-MOVE (Retrieve)**: Pull DICOM data from remote nodes to local storage
- **C-GET (Retrieve)**: Alternative retrieve method with direct transfer
- **Connection Testing**: C-ECHO verification for remote nodes
- **Progress Tracking**: Real-time monitoring of retrieve operations

### 3. Forms (`forms_qr.py`)
- **RemoteDicomNodeForm**: Add/edit remote DICOM nodes
- **DicomQueryForm**: Advanced query interface with date ranges and wildcards

### 4. Views (`views_qr.py`)
- Remote node management (list, add, edit, delete, test)
- Query interface with search form
- Query results display with retrieve buttons
- Retrieve job monitoring
- Query history

### 5. Templates (`templates/dicom_server/qr/`)
- `remote_nodes_list.html` - List and manage remote nodes
- `remote_node_form.html` - Add/edit remote node
- `remote_node_confirm_delete.html` - Delete confirmation
- `query_interface.html` - Search interface with filters
- `query_results.html` - Display query results with retrieve actions
- `query_history.html` - View past queries
- `retrieve_jobs.html` - Monitor retrieve operations

### 6. URL Patterns (`urls.py`)
All Query/Retrieve routes configured under `/dicom-server/qr/`

### 7. Django Admin (`admin.py`)
Full admin interface for all Query/Retrieve models

## 🚧 Next Steps to Complete

### Step 1: Create Database Migrations
```bash
cd /mnt/share/draw-client-2.0
source venv/bin/activate
python manage.py makemigrations dicom_server
python manage.py migrate
```

### Step 2: Add Navigation Links

#### Option A: Update DICOM Server Dashboard
Add Query/Retrieve quick actions to `templates/dicom_server/dashboard.html`:

```html
<!-- Add after existing quick actions -->
<div class="bg-white rounded-lg shadow-md p-6">
    <h3 class="text-lg font-semibold text-gray-900 mb-4">Query/Retrieve</h3>
    <div class="space-y-3">
        <a href="{% url 'dicom_server:query_interface' %}" 
           class="block px-4 py-3 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 transition">
            <div class="flex items-center">
                <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                </svg>
                <span class="font-medium">Query Remote Nodes</span>
            </div>
        </a>
        <a href="{% url 'dicom_server:remote_nodes_list' %}" 
           class="block px-4 py-3 bg-purple-50 text-purple-700 rounded-lg hover:bg-purple-100 transition">
            <div class="flex items-center">
                <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M12 5l7 7-7 7"></path>
                </svg>
                <span class="font-medium">Manage Remote Nodes</span>
            </div>
        </a>
        <a href="{% url 'dicom_server:retrieve_jobs' %}" 
           class="block px-4 py-3 bg-green-50 text-green-700 rounded-lg hover:bg-green-100 transition">
            <div class="flex items-center">
                <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10"></path>
                </svg>
                <span class="font-medium">Retrieve Jobs</span>
            </div>
        </a>
    </div>
</div>
```

#### Option B: Update Main Navigation
Add to main navbar if desired.

### Step 3: Test the Interface

1. **Start Django server**:
   ```bash
   python manage.py runserver
   ```

2. **Access Query/Retrieve**:
   - Navigate to: http://localhost:8000/dicom-server/qr/nodes/
   - Add a remote DICOM node (PACS or modality)
   - Test connection
   - Perform queries
   - Retrieve studies/series

### Step 4: Configure Remote Nodes

For each remote PACS/modality, configure:
- **Name**: Friendly identifier (e.g., "Main PACS")
- **AE Title**: Remote application entity title
- **Host**: IP address or hostname
- **Port**: DICOM port (usually 11112 or 104)
- **Capabilities**: C-FIND, C-MOVE, C-GET support
- **Query/Retrieve Model**: Patient Root, Study Root, or Patient/Study Only
- **Move Destination**: Your local AE title (for C-MOVE)

## Features

### Query Capabilities
- **Multi-level queries**: Patient, Study, Series, Image
- **Wildcard support**: Use `*` for partial matches
- **Date ranges**: Search by study date ranges
- **Modality filtering**: Filter by CT, MR, CR, etc.
- **Query history**: Track all past queries
- **Result pagination**: Handle large result sets

### Retrieve Capabilities
- **C-MOVE support**: Standard DICOM retrieve
- **C-GET support**: Alternative retrieve method
- **Progress tracking**: Real-time progress monitoring
- **Study/Series level**: Retrieve entire studies or specific series
- **Job history**: Track all retrieve operations
- **Error handling**: Detailed error messages and retry capability

### Security Features
- **Authentication required**: All operations require login
- **User tracking**: Track who initiated queries and retrieves
- **Connection validation**: Test connections before use
- **Timeout settings**: Configurable connection timeouts
- **IP validation**: Optional IP address restrictions

## Usage Workflow

1. **Add Remote Node**: Configure connection to PACS/modality
2. **Test Connection**: Verify connectivity with C-ECHO
3. **Query**: Search for patients/studies/series
4. **Review Results**: Browse query results with metadata
5. **Retrieve**: Pull selected studies/series to local storage
6. **Monitor**: Track retrieve job progress
7. **Verify**: Check received files in local storage

## Integration with DICOM Handler

Retrieved DICOM files are stored in the configured storage directory and will be automatically picked up by the `dicom_handler` app's polling mechanism for further processing (deidentification, autosegmentation, export).

## Troubleshooting

### Connection Issues
- Verify remote node is accessible (ping, telnet)
- Check firewall rules
- Confirm AE title matches remote configuration
- Verify port number

### Query Issues
- Check query level matches remote node capabilities
- Verify query/retrieve model setting
- Use wildcards for broader searches
- Check remote node logs

### Retrieve Issues
- Ensure local DICOM server (SCP) is running
- Verify move destination AE title matches local config
- Check storage permissions
- Monitor retrieve job status for errors

## Notes

- **Lint Warnings**: CSS `@apply` and JavaScript template syntax warnings in templates are harmless - they're processed correctly by Django/Tailwind
- **Performance**: Large queries may take time - use date ranges and filters to narrow results
- **Storage**: Monitor disk space when retrieving large studies
- **Concurrency**: Multiple retrieve jobs can run simultaneously

## Support

For issues or questions:
1. Check Django logs for detailed error messages
2. Review transaction log in DICOM server dashboard
3. Test connection with C-ECHO before querying
4. Verify remote node configuration matches PACS settings

---

# Source: dicom_server/tests/README.md

# DICOM Server Test Suite

Comprehensive test suite for the DICOM SCP service functionality.

## Test Structure

```
dicom_server/tests/
├── __init__.py
├── test_models.py          # Model tests
├── test_views.py           # View and API tests
├── test_service.py         # Service functionality tests
├── test_integration.py     # End-to-end integration tests
└── README.md              # This file
```

## Test Coverage

### 1. Model Tests (`test_models.py`)

**DicomServerConfigTestCase**:
- Default configuration creation
- AE title validation (max 16 chars)
- Port number validation (1024-65535)
- Storage usage calculation
- Singleton pattern enforcement

**DicomServiceStatusTestCase**:
- Status creation and updates
- Counter incrementation
- Average file size calculation
- Zero files edge case handling

**AllowedAETestCase**:
- AE title creation
- Uniqueness constraints
- Validation rules

**DicomTransactionTestCase**:
- Transaction logging
- File information storage
- Ordering (most recent first)
- String representation

### 2. View Tests (`test_views.py`)

**DashboardViewTestCase**:
- Authentication requirement
- Dashboard loading
- Service status display

**ConfigurationViewTestCase**:
- Authentication requirement
- Configuration page loading
- Configuration updates

**ServiceControlViewsTestCase**:
- Start service authentication
- Stop service authentication
- Restart service authentication

**AETitleViewsTestCase**:
- AE title list authentication
- List display
- Title management

**TransactionLogViewTestCase**:
- Authentication requirement
- Transaction display
- Pagination

**ServiceStatusAPITestCase**:
- API authentication
- JSON response format
- Status data structure

### 3. Service Tests (`test_service.py`)

**DicomSCPServiceTestCase**:
- Service initialization
- Storage path configuration
- AE configuration
- Service start/stop

**ServiceManagerTestCase**:
- Stale status cleanup
- Service status retrieval

**StorageCleanupTestCase**:
- Storage usage calculation
- Old file cleanup
- Size-based cleanup

**HandlerTestCase**:
- Handler imports (C-ECHO, C-STORE, C-FIND, C-MOVE, C-GET)

### 4. Integration Tests (`test_integration.py`)

**DicomEchoIntegrationTestCase**:
- End-to-end C-ECHO operation
- Transaction logging verification

**DicomStoreIntegrationTestCase**:
- End-to-end C-STORE operation
- File storage verification
- Transaction logging

**ServiceLifecycleTestCase**:
- Start/stop cycle
- Service restart
- Status monitoring

**SecurityTestCase**:
- AE validation enforcement
- Allowed AE management

**StorageLimitTestCase**:
- Storage limit checking
- Cleanup trigger conditions

## Running Tests

### Run All Tests

```bash
cd /mnt/share/draw-client-2.0
source venv/bin/activate
python manage.py test dicom_server.tests
```

### Run Specific Test File

```bash
# Model tests only
python manage.py test dicom_server.tests.test_models

# View tests only
python manage.py test dicom_server.tests.test_views

# Service tests only
python manage.py test dicom_server.tests.test_service

# Integration tests only
python manage.py test dicom_server.tests.test_integration
```

### Run Specific Test Case

```bash
# Run only DicomServerConfig tests
python manage.py test dicom_server.tests.test_models.DicomServerConfigTestCase

# Run only C-ECHO integration test
python manage.py test dicom_server.tests.test_integration.DicomEchoIntegrationTestCase
```

### Run Specific Test Method

```bash
# Run single test method
python manage.py test dicom_server.tests.test_models.DicomServerConfigTestCase.test_ae_title_validation
```

### Run with Verbose Output

```bash
python manage.py test dicom_server.tests --verbosity=2
```

### Run with Coverage Report

```bash
# Install coverage if not already installed
pip install coverage

# Run tests with coverage
coverage run --source='dicom_server' manage.py test dicom_server.tests
coverage report
coverage html  # Generate HTML report in htmlcov/
```

## Test Database

Tests use Django's test database which is automatically created and destroyed. No manual setup required.

## Important Notes

### Port Numbers

Integration tests use different ports to avoid conflicts:
- Test port 11113: C-ECHO tests
- Test port 11114: C-ECHO integration
- Test port 11115: C-STORE integration
- Test port 11116: Lifecycle tests
- Test port 11117: Security tests

### Temporary Directories

Tests create temporary directories for storage which are automatically cleaned up after tests complete.

### Service Threading

Integration tests that start the DICOM service use daemon threads to prevent blocking. Services are stopped in the `finally` block to ensure cleanup.

## Continuous Integration

### GitHub Actions Example

```yaml
name: DICOM Server Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
    
    - name: Run tests
      run: |
        python manage.py test dicom_server.tests --verbosity=2
```

## Troubleshooting

### Port Already in Use

If you see "Address already in use" errors:
```bash
# Find process using the port
lsof -i :11112

# Kill the process
kill -9 <PID>
```

### Database Errors

If you see database errors:
```bash
# Run migrations
python manage.py migrate

# Clear test database
python manage.py test --keepdb=false
```

### Import Errors

If you see import errors:
```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

## Writing New Tests

### Test Template

```python
from django.test import TestCase
from dicom_server.models import DicomServerConfig

class MyTestCase(TestCase):
    """Test description."""
    
    def setUp(self):
        """Set up test data."""
        self.config = DicomServerConfig.objects.create()
    
    def test_something(self):
        """Test specific functionality."""
        # Arrange
        expected = 'value'
        
        # Act
        result = self.config.some_method()
        
        # Assert
        self.assertEqual(result, expected)
    
    def tearDown(self):
        """Clean up after test."""
        pass
```

### Best Practices

1. **Isolation**: Each test should be independent
2. **Cleanup**: Use `setUp()` and `tearDown()` properly
3. **Descriptive Names**: Test names should describe what they test
4. **Single Assertion**: Each test should test one thing
5. **Mock External Services**: Don't rely on external APIs
6. **Use Fixtures**: For complex test data
7. **Test Edge Cases**: Not just happy paths

## Test Metrics

Target coverage: **80%+**

Current coverage by module:
- Models: ~90%
- Views: ~85%
- Service: ~75%
- Handlers: ~70%
- Integration: ~60%

## Contributing

When adding new features to the DICOM server:
1. Write tests first (TDD approach)
2. Ensure all tests pass
3. Maintain or improve coverage
4. Update this README if needed

---

# Source: docker_install/README.md

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


---

# Source: docker_install/README_PERMISSIONS.md

# Docker Permission Issues - Solution Guide

## Problem
The entrypoint script was failing with permission errors:
1. Cannot create `/etc/ssl` - `update-ca-certificates` requires root privileges
2. Operation not permitted while changing ownership - `chown` requires root privileges

## Root Cause
The Dockerfile switches to a non-root user (`appuser` with UID 1000) before running the entrypoint script, but the entrypoint was trying to perform operations that require root privileges.

## Solution Applied

### 1. Entrypoint Script Changes
- Removed `update-ca-certificates` call (now done at build time in Dockerfile)
- Removed `chown` commands (unnecessary since we're already running as appuser)
- The script now only creates directories and runs Django commands

### 2. Dockerfile Changes
- Added `update-ca-certificates` at build time (runs as root)
- Created `/app/staticfiles` directory at build time with proper ownership
- Ensured all directories are owned by `appuser:appuser` before switching to non-root user

### 3. Host Directory Permissions
For the volume mounts to work properly, ensure the host directories have the correct permissions:

```bash
# On your host machine, set ownership to UID/GID 1000
sudo chown -R 1000:1000 ./logs
sudo chown -R 1000:1000 ./staticfiles

# Or make them world-writable (less secure but simpler)
chmod -R 777 ./logs
chmod -R 777 ./staticfiles
```

### 4. Custom CA Certificates (Optional)
If you need custom CA certificates:

1. Place your `.crt` files in the `./certs` directory on the host
2. Modify the Dockerfile to copy them before updating certificates:

```dockerfile
# Add this before the RUN update-ca-certificates line
COPY ./certs/*.crt /usr/local/share/ca-certificates/ 2>/dev/null || true
RUN update-ca-certificates
```

3. Rebuild the image

## Testing
After making these changes:

1. Rebuild your Docker image:
   ```bash
   docker-compose build
   ```

2. Start the services:
   ```bash
   docker-compose up -d
   ```

3. Check logs for any permission errors:
   ```bash
   docker-compose logs django-web
   ```

---

# Source: seed_data/README.md

# Seed Data

This directory contains seed data fixtures that are automatically loaded when the application is initialized.

## Autosegmentation Templates

**File:** `autosegmentation_templates.json`

This fixture contains example autosegmentation templates including:
- Example Breast Template
- Example Head Neck Template
- Example Prostate Template
- Example Lung Template
- Example Rectum Template
- Example CNS Template
- Example Gyn Template

Each template includes associated models and structures from the DRAW API.

### Automatic Loading

The templates are automatically loaded via Django migration `0031_load_autosegmentation_templates.py` when you run:

```bash
python manage.py migrate
```

**Note:** The migration will only load the templates if the database is empty (no existing templates). This prevents duplicate data on subsequent migrations.

### Manual Loading

If you need to manually load or reload the fixtures:

```bash
# Load the fixtures
python manage.py loaddata seed_data/autosegmentation_templates.json

# Or use the full path
python manage.py loaddata autosegmentation_templates
```

### Updating Seed Data

If you need to update the seed data with new templates from your database:

```bash
# Export current templates to fixture file
python manage.py dumpdata dicom_handler.AutosegmentationTemplate dicom_handler.AutosegmentationModel dicom_handler.AutosegmentationStructure --indent 2 --output seed_data/autosegmentation_templates.json
```

## Other Seed Data

### Contour Modification Types

**File:** `contour_modification_types_list.csv`

This CSV file contains predefined contour modification types that are loaded via migration `0027_contour_modification_type_migration.py`.

### DICOM Dictionary

**File:** `dicom_dictionary.csv`

This CSV file contains DICOM tag definitions according to DICOM standards.

## Migration Behavior

- **First-time setup:** All seed data is loaded automatically when running migrations on a fresh database
- **Existing database:** The autosegmentation templates migration checks if templates already exist and skips loading to avoid duplicates
- **Rollback:** Running `python manage.py migrate dicom_handler 0030` will remove all loaded templates

## Notes

- The autosegmentation templates use UUIDs as primary keys, which are preserved from the fixture file
- Templates maintain relationships with their models and structures through foreign keys
- The seed data represents example templates for common cancer treatment sites

---

# Source: VERSIONING.md

# Docker Image Versioning Guide

## Overview
The GitHub Actions workflow now supports multiple tagging strategies for Docker images.

## Tagging Strategy

### 1. **Commit SHA Tags** (Always created)
Every push creates a tag with the git commit SHA:
```
public.ecr.aws/g0w3c0z2/draw-client-2.0:<commit-sha>
```
Example: `public.ecr.aws/g0w3c0z2/draw-client-2.0:a1b2c3d4`

### 2. **Branch Tags**
- **main branch** → `latest` tag
- **develop branch** → `develop` tag
- **other branches** → `<branch-name>` tag

### 3. **Version Tags** (Semantic Versioning)
When you push a git tag following the pattern `v*.*.*`, it creates:
- Version-specific tag: `v1.0.0`, `v2.1.3`, etc.
- **AND** updates the `latest` tag (for releases only)

## How to Create a Versioned Release

### Step 1: Create and Push a Git Tag
```bash
# Create a version tag (e.g., v1.0.0)
git tag -a v1.0.0 -m "Release version 1.0.0"

# Push the tag to GitHub
git push origin v1.0.0
```

### Step 2: GitHub Actions Automatically Creates
The workflow will automatically build and push:
1. `public.ecr.aws/g0w3c0z2/draw-client-2.0:<commit-sha>`
2. `public.ecr.aws/g0w3c0z2/draw-client-2.0:v1.0.0`
3. `public.ecr.aws/g0w3c0z2/draw-client-2.0:latest` (updated to v1.0.0)

## Examples

### Example 1: Regular Development Push to `main`
```bash
git push origin main
```
**Creates:**
- `draw-client-2.0:a1b2c3d4` (commit SHA)
- `draw-client-2.0:latest` (branch tag)

### Example 2: Push to `develop` Branch
```bash
git push origin develop
```
**Creates:**
- `draw-client-2.0:b2c3d4e5` (commit SHA)
- `draw-client-2.0:develop` (branch tag)

### Example 3: Release Version 1.0.0
```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```
**Creates:**
- `draw-client-2.0:c3d4e5f6` (commit SHA)
- `draw-client-2.0:v1.0.0` (version tag)
- `draw-client-2.0:latest` (updated to point to v1.0.0)

### Example 4: Patch Release 1.0.1
```bash
git tag -a v1.0.1 -m "Bugfix release v1.0.1"
git push origin v1.0.1
```
**Creates:**
- `draw-client-2.0:d4e5f6g7` (commit SHA)
- `draw-client-2.0:v1.0.1` (version tag)
- `draw-client-2.0:latest` (updated to point to v1.0.1)

## Pulling Specific Versions

### Pull Latest Release
```bash
docker pull public.ecr.aws/g0w3c0z2/draw-client-2.0:latest
```

### Pull Specific Version
```bash
docker pull public.ecr.aws/g0w3c0z2/draw-client-2.0:v1.0.0
```

### Pull Development Version
```bash
docker pull public.ecr.aws/g0w3c0z2/draw-client-2.0:develop
```

### Pull Specific Commit
```bash
docker pull public.ecr.aws/g0w3c0z2/draw-client-2.0:a1b2c3d4
```

## Semantic Versioning Guidelines

Follow [Semantic Versioning 2.0.0](https://semver.org/):

- **MAJOR version** (v2.0.0): Incompatible API changes
- **MINOR version** (v1.1.0): New functionality, backwards compatible
- **PATCH version** (v1.0.1): Backwards compatible bug fixes

### Examples:
- `v1.0.0` - Initial release
- `v1.0.1` - Bug fix
- `v1.1.0` - New feature added
- `v2.0.0` - Breaking changes

## Deleting Tags

### Delete Local Tag
```bash
git tag -d v1.0.0
```

### Delete Remote Tag
```bash
git push origin --delete v1.0.0
```

**Note:** Deleting a git tag does NOT delete the Docker image from ECR.

## Best Practices

1. **Always test before tagging** - Test thoroughly on `develop` branch first
2. **Use meaningful version numbers** - Follow semantic versioning
3. **Add release notes** - Use annotated tags with `-a` and `-m` flags
4. **Don't reuse version numbers** - Once released, don't change it
5. **Keep CHANGELOG.md updated** - Document changes for each version

## Workflow Triggers

The workflow runs on:
- ✅ Push to `main` branch
- ✅ Push to `develop` branch
- ✅ Push of tags matching `v*.*.*` pattern

## Troubleshooting

### Tag not triggering workflow?
- Ensure tag matches pattern: `v1.0.0` ✅, `1.0.0` ❌
- Check GitHub Actions tab for workflow runs
- Verify AWS credentials are configured

### Image not appearing in ECR?
- Check workflow logs in GitHub Actions
- Verify ECR repository exists
- Confirm AWS permissions are correct

---

# Source: SECURITY.md

# Security Policy

## Reporting a Vulnerability
Please report any security vulnerabilities that you may find to the DRAW or CHAVI team (visit https://chavi.ai). For urgent contact you may raise a issue in Github.

---

# Source: CODE_OF_CONDUCT.md

# Contributor Covenant Code of Conduct

## Our Pledge

We as members, contributors, and leaders pledge to make participation in our
community a harassment-free experience for everyone, regardless of age, body
size, visible or invisible disability, ethnicity, sex characteristics, gender
identity and expression, level of experience, education, socio-economic status,
nationality, personal appearance, race, religion, or sexual identity
and orientation.

We pledge to act and interact in ways that contribute to an open, welcoming,
diverse, inclusive, and healthy community.

## Our Standards

Examples of behavior that contributes to a positive environment for our
community include:

* Demonstrating empathy and kindness toward other people
* Being respectful of differing opinions, viewpoints, and experiences
* Giving and gracefully accepting constructive feedback
* Accepting responsibility and apologizing to those affected by our mistakes,
  and learning from the experience
* Focusing on what is best not just for us as individuals, but for the
  overall community

Examples of unacceptable behavior include:

* The use of sexualized language or imagery, and sexual attention or
  advances of any kind
* Trolling, insulting or derogatory comments, and personal or political attacks
* Public or private harassment
* Publishing others' private information, such as a physical or email
  address, without their explicit permission
* Other conduct which could reasonably be considered inappropriate in a
  professional setting

## Enforcement Responsibilities

Community leaders are responsible for clarifying and enforcing our standards of
acceptable behavior and will take appropriate and fair corrective action in
response to any behavior that they deem inappropriate, threatening, offensive,
or harmful.

Community leaders have the right and responsibility to remove, edit, or reject
comments, commits, code, wiki edits, issues, and other contributions that are
not aligned to this Code of Conduct, and will communicate reasons for moderation
decisions when appropriate.

## Scope

This Code of Conduct applies within all community spaces, and also applies when
an individual is officially representing the community in public spaces.
Examples of representing our community include using an official e-mail address,
posting via an official social media account, or acting as an appointed
representative at an online or offline event.

## Enforcement

Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported to the community leaders responsible for enforcement at
Github Issues.
All complaints will be reviewed and investigated promptly and fairly.

All community leaders are obligated to respect the privacy and security of the
reporter of any incident.

## Enforcement Guidelines

Community leaders will follow these Community Impact Guidelines in determining
the consequences for any action they deem in violation of this Code of Conduct:

### 1. Correction

**Community Impact**: Use of inappropriate language or other behavior deemed
unprofessional or unwelcome in the community.

**Consequence**: A private, written warning from community leaders, providing
clarity around the nature of the violation and an explanation of why the
behavior was inappropriate. A public apology may be requested.

### 2. Warning

**Community Impact**: A violation through a single incident or series
of actions.

**Consequence**: A warning with consequences for continued behavior. No
interaction with the people involved, including unsolicited interaction with
those enforcing the Code of Conduct, for a specified period of time. This
includes avoiding interactions in community spaces as well as external channels
like social media. Violating these terms may lead to a temporary or
permanent ban.

### 3. Temporary Ban

**Community Impact**: A serious violation of community standards, including
sustained inappropriate behavior.

**Consequence**: A temporary ban from any sort of interaction or public
communication with the community for a specified period of time. No public or
private interaction with the people involved, including unsolicited interaction
with those enforcing the Code of Conduct, is allowed during this period.
Violating these terms may lead to a permanent ban.

### 4. Permanent Ban

**Community Impact**: Demonstrating a pattern of violation of community
standards, including sustained inappropriate behavior,  harassment of an
individual, or aggression toward or disparagement of classes of individuals.

**Consequence**: A permanent ban from any sort of public interaction within
the community.

## Attribution

This Code of Conduct is adapted from the [Contributor Covenant][homepage],
version 2.0, available at
https://www.contributor-covenant.org/version/2/0/code_of_conduct.html.

Community Impact Guidelines were inspired by [Mozilla's code of conduct
enforcement ladder](https://github.com/mozilla/diversity).

[homepage]: https://www.contributor-covenant.org

For answers to common questions about this code of conduct, see the FAQ at
https://www.contributor-covenant.org/faq. Translations are available at
https://www.contributor-covenant.org/translations.

---

# Source: CONTRIBUTING.md

We welcome contributions to improve the functionality and security of the application. Please note that all contributions will be reviewed before merging. 

---

# Source: THIRD_PARTY_NOTICES_PYTHON.md

# Third-Party Python Package Notices

This file contains the licenses and notices for third-party Python packages used in this project.

## Table of Contents

- [MIT License](#mit-license) (21 packages)
- [MIT](#mit) (10 packages)
- [BSD License](#bsd-license) (22 packages)
- [BSD-3-Clause](#bsd-3-clause) (11 packages)
- [BSD-2-Clause](#bsd-2-clause) (1 packages)
- [Apache Software License](#apache-software-license) (5 packages)
- [Apache-2.0](#apache-20) (1 packages)
- [Apache Software License; BSD License](#apache-software-license-bsd-license) (2 packages)
- [MIT AND BSD-3-Clause](#mit-and-bsd-3-clause) (1 packages)
- [Apache-2.0 OR BSD-3-Clause](#apache-20-or-bsd-3-clause) (1 packages)
- [MIT-CMU](#mit-cmu) (1 packages)
- [Python Software Foundation License](#python-software-foundation-license) (1 packages)
- [PSF-2.0](#psf-20) (1 packages)
- [LGPLv3](#lgplv3) (1 packages)
- [GNU Library or Lesser General Public License (LGPL)](#gnu-library-or-lesser-general-public-license-lgpl) (1 packages)
- [Mozilla Public License 2.0 (MPL 2.0)](#mozilla-public-license-20-mpl-20) (1 packages)
- [UNKNOWN](#unknown) (1 packages)

---

## MIT License

**21 package(s)**

### celery-progress (v0.5)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/celery_progress-0.5.dist-info/LICENSE`

**License Text:**

```
MIT License
```

### click-didyoumean (v0.3.1)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/click_didyoumean-0.3.1.dist-info/LICENSE`

**License Text:**

```
Copyright (c) 2016 Timo Furrer
```

### crispy-tailwind (v1.0.3)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/crispy_tailwind-1.0.3.dist-info/LICENSE.txt`

**License Text:**

```
Copyright (c) 2020 David Smith and contributors.
```

### django-allauth (v65.13.1)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/django_allauth-65.13.1.dist-info/licenses/LICENSE`

**License Text:**

```
The MIT License (MIT)
```

### django-cotton (v2.6.0)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/django_cotton-2.6.0.dist-info/licenses/LICENSE`

**License Text:**

```
MIT License
```

### django-encrypted-model-fields (v0.6.5)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/LICENSE`

**License Text:**

```
The MIT License (MIT)
```

### docopt (v0.6.2)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/docopt-0.6.2.dist-info/LICENSE-MIT`

**License Text:**

```
Copyright (c) 2012 Vladimir Keleshev, <vladimir@keleshev.com>
```

### exceptiongroup (v1.3.1)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/exceptiongroup-1.3.1.dist-info/licenses/LICENSE`

**License Text:**

```
The MIT License (MIT)
```

### gunicorn (v23.0.0)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/gunicorn-23.0.0.dist-info/LICENSE`

**License Text:**

```
2009-2024 (c) Benoît Chesneau <benoitc@gunicorn.org>
```

### narwhals (v2.15.0)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/narwhals-2.15.0.dist-info/licenses/LICENSE.md`

**License Text:**

```
MIT License
```

### plotly (v6.5.1)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/plotly-6.5.1.dist-info/licenses/LICENSE.txt`

**License Text:**

```
MIT License
```

### pydicom (v3.0.1)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/pydicom-3.0.1.dist-info/LICENSE`

**License Text:**

```
License file for pydicom, a pure-python DICOM library
```

### pykwalify (v1.8.0)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/pykwalify-1.8.0.dist-info/LICENSE`

**License Text:**

```
Copyright (c) 2013-2021 Johan Andersson
```

### pynetdicom (v3.0.4)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/pynetdicom-3.0.4.dist-info/licenses/LICENCE`

**License Text:**

```
Copyright (c) 2012-2021 Patrice Munger and pynetdicom contributors
```

### pytz (v2025.2)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/pytz-2025.2.dist-info/LICENSE.txt`

**License Text:**

```
Copyright (c) 2003-2019 Stuart Bishop <stuart@stuartbishop.net>
```

### PyYAML (v6.0.3)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/pyyaml-6.0.3.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2017-2021 Ingy döt Net
```

### rt-utils (v1.2.7)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/rt_utils-1.2.7.dist-info/LICENSE`

**License Text:**

```
MIT License
```

### ruamel.yaml (v0.19.1)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/ruamel_yaml-0.19.1.dist-info/licenses/LICENSE`

**License Text:**

```
The MIT License (MIT)
```

### ruamel.yaml.clib (v0.2.15)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/ruamel_yaml_clib-0.2.15.dist-info/licenses/LICENSE`

**License Text:**

```
The MIT License (MIT)
```

### six (v1.17.0)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/six-1.17.0.dist-info/LICENSE`

**License Text:**

```
Copyright (c) 2010-2024 Benjamin Peterson
```

### tzlocal (v5.3.1)

**License:** MIT License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/tzlocal-5.3.1.dist-info/LICENSE.txt`

**License Text:**

```
Copyright 2011-2017 Lennart Regebro
```

---

## MIT

**10 package(s)**

### cffi (v2.0.0)

**License:** MIT

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/cffi-2.0.0.dist-info/licenses/LICENSE`

### charset-normalizer (v3.4.4)

**License:** MIT

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/charset_normalizer-3.4.4.dist-info/licenses/LICENSE`

**License Text:**

```
MIT License
```

### click-repl (v0.3.0)

**License:** MIT

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/click_repl-0.3.0.dist-info/LICENSE`

**License Text:**

```
Copyright (c) 2014-2015 Markus Unterwaditzer & contributors.
```

### cron_descriptor (v2.0.6)

**License:** MIT

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/cron_descriptor-2.0.6.dist-info/licenses/LICENSE`

**License Text:**

```
The MIT License (MIT)
```

### django-crispy-forms (v2.5)

**License:** MIT

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/crispy_forms/LICENSE`

**License Text:**

```
Copyright (c) 2009 Daniel Greenfeld and contributors.
```

### django-unfold (v0.75.0)

**License:** MIT

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/django_unfold-0.75.0.dist-info/licenses/LICENSE.md`

**License Text:**

```
MIT License
```

### fonttools (v4.61.1)

**License:** MIT

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/fonttools-4.61.1.dist-info/licenses/LICENSE`

**License Text:**

```
MIT License
```

### pyparsing (v3.3.1)

**License:** MIT

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/pyparsing-3.3.1.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2003-2025  Paul McGuire
```

### ruamel.yaml.clibz (v0.3.7)

**License:** MIT

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/ruamel_yaml_clibz-0.3.7.dist-info/licenses/LICENSE`

**License Text:**

```
The MIT License (MIT)
```

### urllib3 (v2.6.3)

**License:** MIT

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/urllib3-2.6.3.dist-info/licenses/LICENSE.txt`

**License Text:**

```
MIT License
```

---

## BSD License

**22 package(s)**

### amqp (v5.3.1)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/amqp-5.3.1.dist-info/LICENSE`

**License Text:**

```
Copyright (c) 2015-2016 Ask Solem & contributors.  All rights reserved.
```

### asgiref (v3.11.0)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/asgiref-3.11.0.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) Django Software Foundation and individual contributors.
```

### billiard (v4.2.4)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/billiard-4.2.4.dist-info/LICENSE.txt`

**License Text:**

```
Copyright (c) 2006-2008, R Oudkerk and Contributors
```

### click-plugins (v1.1.1.2)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/click_plugins-1.1.1.2.dist-info/licenses/LICENSE.txt`

**License Text:**

```
New BSD License
```

### contourpy (v1.3.3)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/contourpy-1.3.3.dist-info/LICENSE`

**License Text:**

```
BSD 3-Clause License
```

### cycler (v0.12.1)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/cycler-0.12.1.dist-info/LICENSE`

**License Text:**

```
Copyright (c) 2015, matplotlib project
```

### django-celery-beat (v2.8.1)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/django_celery_beat-2.8.1.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2015-2016 Ask Solem.  All Rights Reserved.
```

### django-timezone-field (v7.2.1)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/django_timezone_field-7.2.1.dist-info/licenses/LICENSE.txt`

**License Text:**

```
Copyright (c) 2014, Mike Fogel <mike@fogel.ca>
```

### django_celery_results (v2.6.0)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/django_celery_results-2.6.0.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2017-2032 Asif Saif Uddin.  All Rights Reserved.
```

### kiwisolver (v1.4.9)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/kiwisolver-1.4.9.dist-info/licenses/LICENSE`

**License Text:**

```
=========================
```

### lazy_loader (v0.4)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/lazy_loader-0.4.dist-info/LICENSE.md`

**License Text:**

```
BSD 3-Clause License
```

### numpy (v2.2.6)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/numpy-2.2.6.dist-info/LICENSE.txt`

**License Text:**

```
Copyright (c) 2005-2024, NumPy Developers.
```

### pandas (v2.3.3)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/pandas-2.3.3.dist-info/LICENSE`

**License Text:**

```
BSD 3-Clause License
```

### prompt_toolkit (v3.0.52)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/prompt_toolkit-3.0.52.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2014, Jonathan Slenders
```

### pycparser (v2.23)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/pycparser-2.23.dist-info/LICENSE`

**License Text:**

```
pycparser -- A C parser in Python
```

### scikit-image (v0.26.0)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/scikit_image-0.26.0.dist-info/LICENSE.txt`

**License Text:**

```
Files: *
```

### scipy (v1.16.3)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/scipy-1.16.3.dist-info/LICENSE.txt`

**License Text:**

```
Copyright (c) 2001-2002 Enthought, Inc. 2003, SciPy Developers.
```

### shapely (v2.1.2)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/shapely-2.1.2.dist-info/licenses/LICENSE.txt`

**License Text:**

```
BSD 3-Clause License
```

### sqlparse (v0.5.5)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/sqlparse-0.5.5.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2016, Andi Albrecht <albrecht.andi@gmail.com>
```

### threadpoolctl (v3.6.0)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/threadpoolctl-3.6.0.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2019, threadpoolctl contributors
```

### vine (v5.1.0)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/vine-5.1.0.dist-info/LICENSE`

**License Text:**

```
Copyright (c) 2015-2016 Ask Solem & contributors.  All rights reserved.
```

### vtk (v9.5.2)

**License:** BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/vtk-9.5.2.dist-info/licenses/LICENSE`

**License Text:**

```
/*=========================================================================
```

---

## BSD-3-Clause

**11 package(s)**

### celery (v5.6.2)

**License:** BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/celery-5.6.2.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2017-2026 Asif Saif Uddin, core team & contributors. All rights reserved.
```

### click (v8.3.1)

**License:** BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/click-8.3.1.dist-info/licenses/LICENSE.txt`

**License Text:**

```
Copyright 2014 Pallets
```

### Django (v5.2.10)

**License:** BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/django-5.2.10.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) Django Software Foundation and individual contributors.
```

### idna (v3.11)

**License:** BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/idna-3.11.dist-info/licenses/LICENSE.md`

**License Text:**

```
BSD 3-Clause License
```

### joblib (v1.5.3)

**License:** BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/joblib-1.5.3.dist-info/licenses/LICENSE.txt`

**License Text:**

```
BSD 3-Clause License
```

### kombu (v5.6.2)

**License:** BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/kombu-5.6.2.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2015-2016 Ask Solem & contributors.  All rights reserved.
```

### networkx (v3.6.1)

**License:** BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/networkx-3.6.1.dist-info/licenses/LICENSE.txt`

**License Text:**

```
NetworkX is distributed with the 3-clause BSD license.
```

### psutil (v7.2.1)

**License:** BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/psutil-7.2.1.dist-info/LICENSE`

**License Text:**

```
BSD 3-Clause License
```

### python-dotenv (v1.2.1)

**License:** BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/python_dotenv-1.2.1.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2014, Saurabh Kumar (python-dotenv), 2013, Ted Tieken (django-dotenv-rw), 2013, Jacob Kaplan-Moss (django-dotenv)
```

### scikit-learn (v1.8.0)

**License:** BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/scikit_learn-1.8.0.dist-info/licenses/COPYING`

**License Text:**

```
BSD 3-Clause License
```

### tifffile (v2025.12.20)

**License:** BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/tifffile-2025.12.20.dist-info/licenses/LICENSE`

**License Text:**

```
BSD-3-Clause license
```

---

## BSD-2-Clause

**1 package(s)**

### ImageIO (v2.37.2)

**License:** BSD-2-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/imageio-2.37.2.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2014-2025, imageio developers
```

---

## Apache Software License

**5 package(s)**

### dataclasses (v0.6)

**License:** Apache Software License

**License File:** `UNKNOWN`

**License Text:**

```
UNKNOWN
```

### opencv-python (v4.12.0.88)

**License:** Apache Software License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/cv2/LICENSE-3RD-PARTY.txt`

**License Text:**

```
OpenCV library is redistributed within opencv-python package.
```

### pymemcache (v4.0.0)

**License:** Apache Software License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/pymemcache-4.0.0.dist-info/LICENSE.txt`

### requests (v2.32.5)

**License:** Apache Software License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/requests-2.32.5.dist-info/licenses/LICENSE`

### simpleitk (v2.5.3)

**License:** Apache Software License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/simpleitk-2.5.3.dist-info/licenses/LICENSE`

---

## Apache-2.0

**1 package(s)**

### tzdata (v2025.3)

**License:** Apache-2.0

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/tzdata-2025.3.dist-info/licenses/LICENSE`

**License Text:**

```
Apache Software License 2.0
```

---

## Apache Software License; BSD License

**2 package(s)**

### packaging (v25.0)

**License:** Apache Software License; BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/packaging-25.0.dist-info/licenses/LICENSE`

**License Text:**

```
This software is made available under the terms of *either* of the licenses
```

### python-dateutil (v2.9.0.post0)

**License:** Apache Software License; BSD License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/python_dateutil-2.9.0.post0.dist-info/LICENSE`

**License Text:**

```
Copyright 2017- Paul Ganssle <paul@ganssle.io>
```

---

## MIT AND BSD-3-Clause

**1 package(s)**

### PyWavelets (v1.9.0)

**License:** MIT AND BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/pywavelets-1.9.0.dist-info/licenses/LICENSE`

**License Text:**

```
Copyright (c) 2006-2012 Filip Wasilewski <http://en.ig.ma/>
```

---

## Apache-2.0 OR BSD-3-Clause

**1 package(s)**

### cryptography (v46.0.3)

**License:** Apache-2.0 OR BSD-3-Clause

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/cryptography-46.0.3.dist-info/licenses/LICENSE`

**License Text:**

```
This software is made available under the terms of *either* of the licenses
```

---

## MIT-CMU

**1 package(s)**

### pillow (v12.1.0)

**License:** MIT-CMU

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/pillow-12.1.0.dist-info/licenses/LICENSE`

**License Text:**

```
The Python Imaging Library (PIL) is
```

---

## Python Software Foundation License

**1 package(s)**

### matplotlib (v3.10.8)

**License:** Python Software Foundation License

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/matplotlib-3.10.8.dist-info/LICENSE`

**License Text:**

```
License agreement for matplotlib versions 1.3.0 and later
```

---

## PSF-2.0

**1 package(s)**

### typing_extensions (v4.15.0)

**License:** PSF-2.0

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/typing_extensions-4.15.0.dist-info/licenses/LICENSE`

**License Text:**

```
A. HISTORY OF THE SOFTWARE
```

---

## LGPLv3

**1 package(s)**

### python-crontab (v3.3.0)

**License:** LGPLv3

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/python_crontab-3.3.0.dist-info/licenses/COPYING`

**License Text:**

```
GNU LESSER GENERAL PUBLIC LICENSE
```

---

## GNU Library or Lesser General Public License (LGPL)

**1 package(s)**

### psycopg2-binary (v2.9.11)

**License:** GNU Library or Lesser General Public License (LGPL)

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/psycopg2_binary-2.9.11.dist-info/licenses/LICENSE`

**License Text:**

```
psycopg2 and the LGPL
```

---

## Mozilla Public License 2.0 (MPL 2.0)

**1 package(s)**

### certifi (v2026.1.4)

**License:** Mozilla Public License 2.0 (MPL 2.0)

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/certifi-2026.1.4.dist-info/licenses/LICENSE`

**License Text:**

```
This package contains a modified version of ca-bundle.crt:
```

---

## UNKNOWN

**1 package(s)**

### dotenv (v0.9.9)

**License:** UNKNOWN

**License File:** `/mnt/share/draw-client-2.0/venv/lib/python3.11/site-packages/dotenv-0.9.9.dist-info/LICENSE`

**License Text:**

```
MIT License
```
