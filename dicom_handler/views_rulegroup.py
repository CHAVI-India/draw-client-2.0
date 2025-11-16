"""
Views for RuleGroup management with multiple RuleSets
This is a separate file to handle the complex nested formset logic
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.forms import inlineformset_factory
import uuid

from .models import RuleGroup, RuleSet, Rule, AutosegmentationTemplate
from .forms import RuleGroupForm, RuleSetForm, RuleForm


@login_required
@permission_required('dicom_handler.add_ruleset', raise_exception=True)
def rulegroup_create_with_rulesets(request):
    """
    Create a RuleGroup with multiple RuleSets, each with multiple Rules
    This uses a simplified approach: create RuleGroup first, then add RuleSets via AJAX
    """
    template_id = request.GET.get('template')
    rulegroup_initial = {}
    
    if template_id:
        try:
            template = AutosegmentationTemplate.objects.get(id=template_id)
            rulegroup_initial['associated_autosegmentation_template'] = template
        except AutosegmentationTemplate.DoesNotExist:
            messages.warning(request, 'The specified template was not found.')
    
    if request.method == 'POST':
        rulegroup_form = RuleGroupForm(request.POST)
        
        if rulegroup_form.is_valid():
            # Create the rulegroup
            rulegroup = rulegroup_form.save(commit=False)
            rulegroup.id = uuid.uuid4()
            rulegroup.save()
            
            messages.success(request, f'Rule Group "{rulegroup.rulegroup_name}" created successfully! Now add RuleSets to it.')
            return redirect('dicom_handler:rulegroup_add_ruleset', rulegroup_id=rulegroup.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        rulegroup_form = RuleGroupForm(initial=rulegroup_initial)
    
    return render(request, 'dicom_handler/rulegroup_create.html', {
        'rulegroup_form': rulegroup_form,
    })


@login_required
@permission_required('dicom_handler.add_ruleset', raise_exception=True)
def rulegroup_add_ruleset(request, rulegroup_id):
    """
    Add a RuleSet with Rules to an existing RuleGroup
    This preserves all the Select2 and VR validation functionality
    """
    from .forms import RuleFormSet, RuleFormSetHelper
    
    rulegroup = get_object_or_404(RuleGroup, id=rulegroup_id)
    
    if request.method == 'POST':
        ruleset_form = RuleSetForm(request.POST)
        formset = RuleFormSet(request.POST)
        
        if ruleset_form.is_valid() and formset.is_valid():
            # Create the ruleset and associate with rulegroup
            ruleset = ruleset_form.save(commit=False)
            ruleset.id = uuid.uuid4()
            ruleset.rulegroup = rulegroup
            ruleset.save()
            
            # Save the rules
            formset.instance = ruleset
            formset.save()
            
            messages.success(request, f'RuleSet "{ruleset.ruleset_name}" added successfully!')
            
            # Check if user wants to add another ruleset
            if 'add_another' in request.POST:
                return redirect('dicom_handler:rulegroup_add_ruleset', rulegroup_id=rulegroup.id)
            else:
                return redirect('dicom_handler:ruleset_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Auto-increment the ruleset order
        existing_rulesets_count = RuleSet.objects.filter(rulegroup=rulegroup).count()
        ruleset_form = RuleSetForm(initial={'rulset_order': existing_rulesets_count + 1})
        formset = RuleFormSet()
    
    # Get existing rulesets for this rulegroup
    existing_rulesets = RuleSet.objects.filter(rulegroup=rulegroup).order_by('rulset_order')
    
    formset_helper = RuleFormSetHelper()
    
    return render(request, 'dicom_handler/rulegroup_add_ruleset.html', {
        'rulegroup': rulegroup,
        'form': ruleset_form,
        'formset': formset,
        'formset_helper': formset_helper,
        'existing_rulesets': existing_rulesets,
    })
