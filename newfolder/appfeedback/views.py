from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.db.models import Max, Q, IntegerField, Exists, OuterRef
from django.db.models.functions import Cast
from django.http import JsonResponse, HttpResponse
from django.forms import formset_factory
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.conf import settings
import pandas as pd
import openpyxl
import json
import csv
import re
from copy import copy
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.formatting.rule import FormulaRule
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, PieChart, LineChart, Reference
from openpyxl.worksheet.pagebreak import Break
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.drawing.image import Image as XLImage
from io import BytesIO
from collections import defaultdict
from .models import (
    Division, Professor, Subject, PracticalBatch, Student, 
    TeacherAssignment, FeedbackForm, FeedbackQuestion, 
    FeedbackResponse, FeedbackAnswer, PracticalAssignment,
    StudentElectiveSelection, StoredExport, UserMailSetup
)
from .forms import (
    FeedbackFormCreationForm, FeedbackQuestionForm, 
    FeedbackResponseForm, FeedbackAnswerFormSet, StoredExportUploadForm
)


def home_view(request):
    return render(request, 'home.html')


def admin_login_view(request):
    """Admin login view with username autofilled as 'admin' and staff-only access"""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('dashboard')
        else:
            messages.error(request, "Access denied. Staff accounts only.")
            return redirect('login')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                if user.is_staff:
                    login(request, user)
                    messages.success(request, f"Welcome back, {user.get_full_name() or user.username}!")
                    return redirect('dashboard')
                else:
                    messages.error(request, "Access denied. This login is for staff accounts only.")
            else:
                messages.error(request, "Invalid username or password.")
        else:
            messages.error(request, "Please provide both username and password.")
    
    return render(request, 'admin_login.html')


@login_required
def dashboard_view(request):
    try:
        student = Student.objects.get(user=request.user)
        
        # Get all active feedback forms for this student
        current_time = timezone.now()
        
        # Get student's selected elective subject IDs
        selected_elective_subject_ids = StudentElectiveSelection.objects.filter(
            student=student,
            semester=student.semester
        ).values_list('subject_id', flat=True)
        
        # Theory forms for student's division
        # Only show forms for non-elective subjects OR elective subjects the student has selected
        theory_forms = FeedbackForm.objects.filter(
            division=student.division,
            subject__subject_type='theory',
            subject__semester=student.semester,
            is_active=True,
            start_date__lte=current_time,
            end_date__gte=current_time
        ).filter(
            Q(subject__elective__isnull=True) |  # Non-elective subjects
            Q(subject__id__in=selected_elective_subject_ids)  # Selected elective subjects
        ).select_related('subject', 'professor', 'division')
        theory_forms = _forms_available_for_student_round(theory_forms, student)
        
        # Practical and tutorial forms for student's practical batch
        # Only show forms for non-elective subjects OR elective subjects the student has selected
        practical_tutorial_forms = []
        if student.practical_batch:
            practical_tutorial_forms = FeedbackForm.objects.filter(
                practical_batch=student.practical_batch,
                subject__subject_type__in=['practical', 'tutorials'],
                subject__semester=student.semester,
                is_active=True,
                start_date__lte=current_time,
                end_date__gte=current_time
            ).filter(
                Q(subject__elective__isnull=True) |  # Non-elective subjects
                Q(subject__id__in=selected_elective_subject_ids)  # Selected elective subjects
            ).select_related('subject', 'professor', 'division', 'practical_batch')
            practical_tutorial_forms = _forms_available_for_student_round(
                practical_tutorial_forms, student
            )
        
        # Combine all available forms
        available_forms = list(theory_forms) + list(practical_tutorial_forms)
        
        # Get completed forms
        completed_forms = FeedbackResponse.objects.filter(
            student=student
        ).select_related('form__subject', 'form__professor', 'form__division')
        
        # Check if there are any electives available for the student's semester
        available_electives = Subject.objects.filter(
            semester=student.semester,
            elective__isnull=False
        ).exists()
        
        # Get student's elective selections
        elective_selections = StudentElectiveSelection.objects.filter(
            student=student,
            semester=student.semester
        ).select_related('subject')
        
        # Check if student has completed elective selection
        electives_completed = True
        missing_electives = []
        if available_electives:
            # Get all unique elective groups for this semester
            elective_groups = Subject.objects.filter(
                semester=student.semester,
                elective__isnull=False
            ).values_list('elective', flat=True).distinct()
            
            # Get selected elective groups
            selected_groups = set(elective_selections.values_list('elective_group', flat=True))
            
            # Check if all elective groups have been selected
            for group in elective_groups:
                if group not in selected_groups:
                    electives_completed = False
                    missing_electives.append(group)
        
        # Only show forms if electives are completed (or not required)
        show_forms = electives_completed
        
        context = {
            'student': student,
            'available_forms': available_forms if show_forms else [],
            'completed_forms': completed_forms,
            'available_electives': available_electives,
            'elective_selections': elective_selections,
            'electives_completed': electives_completed,
            'show_forms': show_forms,
            'missing_electives': missing_electives,
        }
        
        return render(request, 'dashboard.html', context)
    
    except Student.DoesNotExist:
        # User is not a student, check if they're a professor or admin
        try:
            professor = Professor.objects.get(user=request.user)
            return redirect('professor_dashboard')
        except Professor.DoesNotExist:
            if request.user.is_staff:
                return redirect('admin_dashboard')
            else:
                messages.error(request, "Your account is not properly configured. Please contact administrator.")
                return render(request, 'dashboard.html', {'error': True})


@login_required
def select_electives_view(request):
    """View for students to select their elective subjects"""
    try:
        student = Student.objects.get(user=request.user)
        
        # Check if student has already completed elective selection
        # Get all elective groups for the student's semester
        elective_groups_available = Subject.objects.filter(
            semester=student.semester,
            elective__isnull=False
        ).values_list('elective', flat=True).distinct()
        
        # Get student's current selections
        current_selections = StudentElectiveSelection.objects.filter(
            student=student,
            semester=student.semester
        )
        
        selected_groups = set(current_selections.values_list('elective_group', flat=True))
        all_groups_selected = all(group in selected_groups for group in elective_groups_available)
        
        # If all electives are already selected, prevent editing
        if all_groups_selected and elective_groups_available:
            messages.info(request, "You have already submitted your elective selections. They cannot be modified.")
            return redirect('dashboard')
        
        # Get all elective groups available for the student's current semester
        from django.db.models import Count
        
        # Get elective groups for the student's semester
        elective_groups = Subject.objects.filter(
            semester=student.semester,
            elective__isnull=False
        ).values('elective').annotate(
            subject_count=Count('id')
        ).order_by('elective')
        
        # Get subjects organized by elective group
        electives_by_group = {}
        student_selections = {}
        
        for group in elective_groups:
            elective_num = group['elective']
            subjects = Subject.objects.filter(
                semester=student.semester,
                elective=elective_num
            ).order_by('name')
            
            electives_by_group[elective_num] = subjects
            
            # Get student's selection for this group if any
            try:
                selection = StudentElectiveSelection.objects.get(
                    student=student,
                    elective_group=elective_num,
                    semester=student.semester
                )
                student_selections[elective_num] = selection.subject.id
            except StudentElectiveSelection.DoesNotExist:
                student_selections[elective_num] = None
        
        if request.method == 'POST':
            # Process elective selections
            errors = []
            success_count = 0
            
            with transaction.atomic():
                for elective_num in electives_by_group.keys():
                    subject_id = request.POST.get(f'elective_{elective_num}')
                    
                    if subject_id:
                        try:
                            subject = Subject.objects.get(
                                id=subject_id,
                                elective=elective_num,
                                semester=student.semester
                            )
                            
                            # Update or create selection
                            selection, created = StudentElectiveSelection.objects.update_or_create(
                                student=student,
                                elective_group=elective_num,
                                semester=student.semester,
                                defaults={'subject': subject}
                            )
                            success_count += 1
                            
                        except Subject.DoesNotExist:
                            errors.append(f"Invalid subject selected for Elective {elective_num}")
                        except Exception as e:
                            errors.append(f"Error saving Elective {elective_num}: {str(e)}")
            
            if errors:
                for error in errors:
                    messages.error(request, error)
            
            if success_count > 0:
                messages.success(request, f"Successfully saved {success_count} elective selection(s)!")
                return redirect('dashboard')
        
        context = {
            'student': student,
            'electives_by_group': electives_by_group,
            'student_selections': student_selections,
        }
        
        return render(request, 'select_electives.html', context)
        
    except Student.DoesNotExist:
        messages.error(request, "Only students can select electives.")
        return redirect('dashboard')


def is_admin(user):
    return user.is_staff or user.is_superuser


def _forms_available_for_student_round(queryset, student):
    """Return forms for the next enabled feedback round for a student."""
    has_round_one = Exists(FeedbackResponse.objects.filter(
        form_id=OuterRef('pk'), student=student, feedback_round=1
    ))
    has_round_two = Exists(FeedbackResponse.objects.filter(
        form_id=OuterRef('pk'), student=student, feedback_round=2
    ))
    return queryset.annotate(
        has_round_one=has_round_one,
        has_round_two=has_round_two,
    ).filter(
        (Q(second_feedback_enabled=True) & Q(has_round_two=False)) |
        (Q(second_feedback_enabled=False) & Q(has_round_one=False))
    )


def _archive_export_file(user, title, filename, content_bytes):
    """Persist generated export bytes in StoredExport archive."""
    if not content_bytes:
        return
    stored_export = StoredExport(title=title, uploaded_by=user)
    stored_export.export_file.save(filename, ContentFile(content_bytes), save=True)


@login_required
@user_passes_test(is_admin)
def admin_dashboard_view(request):
    """Dashboard for admin users to manage feedback forms"""
    context = {
        'total_forms': FeedbackForm.objects.count(),
        'active_forms': FeedbackForm.objects.filter(is_active=True).count(),
        'total_responses': FeedbackResponse.objects.count(),
        'recent_forms': FeedbackForm.objects.order_by('-created_at')[:5],
    }
    return render(request, 'admin_dashboard.html', context)


@login_required
@user_passes_test(is_admin)
def create_feedback_form_view(request):
    """Create a new feedback form with questions"""
    if request.method == 'POST':
        form = FeedbackFormCreationForm(request.POST)
        
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Create the feedback form
                    feedback_form = form.save(commit=False)
                    feedback_form.created_by = request.user
                    feedback_form.save()
                    
                    # Handle questions data from the dynamic form
                    questions_data = request.POST.get('questions_data')
                    if questions_data:
                        try:
                            import json
                            questions = json.loads(questions_data)
                            
                            for index, q_data in enumerate(questions, 1):
                                question = FeedbackQuestion(
                                    form=feedback_form,
                                    question_text=q_data["text"],
                                    question_type=q_data["type"],
                                    order=index,
                                    is_required=q_data.get("required", True)
                                )
                                
                                # Handle multiple choice questions
                                if q_data["type"] == "multiple_choice" and "choices" in q_data:
                                    question.choices = q_data["choices"]
                                
                                question.save()
                                
                            questions_count = len(questions)
                        except (json.JSONDecodeError, KeyError) as e:
                            # Fall back to default questions if JSON parsing fails
                            questions_count = _create_default_questions(feedback_form)
                    else:
                        # Create default questions if no questions data provided
                        questions_count = _create_default_questions(feedback_form)
                    
                    messages.success(request, f'Feedback form "{feedback_form.title}" created successfully with {questions_count} questions! You can now customize, add more questions, or activate the form.')
                    return redirect('manage_questions', form_id=feedback_form.id)
                    
            except ValidationError as e:
                messages.error(request, f"Error creating form: {e}")
            except Exception as e:
                messages.error(request, f"Unexpected error: {e}")
        else:
            # Show form validation errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
            messages.error(request, "Please correct the errors below.")
    else:
        form = FeedbackFormCreationForm()
    
    return render(request, 'create_feedback_form_new.html', {'form': form})


def _create_default_questions(feedback_form):
    """Helper method to create default questions based on subject type"""
    # Determine subject type to get appropriate questions
    subject_type = feedback_form.subject.subject_type
    
    # Define questions for each subject type
    theory_questions = [
        "Ability to stimulate students interest by generating questions / enquiry during Lectures, Practical and Tutorials",
        "Teaching / Instructing methodology using different facilities (chalkboard / LCD etc.) as appropriate for the topic",
        "Handling doubts/ questions",
        "Approach towards subject, Practical and Tutorials",
        "Organisation of Lecture, Practical and Tutorials",
        "Pace of teaching / Instructions",
        "Knowlege of topic, Practical and Tutorials",
        "Medium of language- Use of English",
        "Manner of initiation of Lecture, Practical and Tutorials by mentioning the aims /Objective of the topics / practical/ assignment – under consideration",
        "Punctuality & Regularity during Lecture, Practical and Tutorials",
        "Behaviour of faculty towards students",
        "Overall impression",
        "Any other criticism",
        "Improvement"
    ]
    
    practical_questions = [
        "Organisation of Lecture, Practical and Tutorials",
        "Pace of teaching / Instructions",
        "Knowlege of topic, Practical and Tutorials",
        "Medium of language- Use of English",
        "Manner of initiation of Lecture, Practical and Tutorials by mentioning the aims /Objective of the topics / practical/ assignment – under consideration",
        "Punctuality & Regularity during Lecture, Practical and Tutorials",
        "Behaviour of faculty towards students",
        "Overall impression",
        "Any other feedback"
    ]
    
    tutorial_questions = [
        "Organisation of Lecture, Practical and Tutorials",
        "Pace of teaching / Instructions",
        "Knowlege of topic, Practical and Tutorials",
        "Medium of language- Use of English",
        "Manner of initiation of Lecture, Practical and Tutorials by mentioning the aims /Objective of the topics / practical/ assignment – under consideration",
        "Punctuality & Regularity during Lecture, Practical and Tutorials",
        "Behaviour of faculty towards students",
        "Overall impression",
        "Any other feedback"
    ]
    
    # Select questions based on subject type
    if subject_type == 'theory':
        selected_questions = theory_questions
    elif subject_type == 'practical':
        selected_questions = practical_questions
    elif subject_type == 'tutorials':
        selected_questions = tutorial_questions
    else:
        # Fallback to theory questions
        selected_questions = theory_questions
    
    # Create question objects
    questions_list = []
    for i, question_text in enumerate(selected_questions, 1):
        # Determine question type based on content
        if any(keyword in question_text.lower() for keyword in ['criticism', 'feedback', 'improvement', 'comment', 'suggestion']):
            question_type = 'text'
            is_required = False
        else:
            question_type = 'rating'
            is_required = True
        
        questions_list.append({
            "text": question_text,
            "type": question_type,
            "order": i,
            "required": is_required
        })
    
    # Create and save questions
    for q_data in questions_list:
        question = FeedbackQuestion(
            form=feedback_form,
            question_text=q_data["text"],
            question_type=q_data["type"],
            order=q_data["order"],
            is_required=q_data.get("required", True)
        )
        question.save()
    
    return len(questions_list)


@login_required
@user_passes_test(is_admin)
def manage_feedback_forms_view(request):
    """View to manage all feedback forms"""
    forms = FeedbackForm.objects.all().select_related(
        'subject', 'professor', 'division', 'practical_batch', 'created_by'
    ).order_by('-created_at')
    
    active_forms_count = forms.filter(is_active=True).count()
    mail_setup = UserMailSetup.objects.filter(user=request.user).first()
    
    return render(request, 'manage_feedback_forms.html', {
        'forms': forms,
        'active_forms_count': active_forms_count,
        'mail_setup': mail_setup,
    })


@login_required
@user_passes_test(is_admin)
def enable_second_feedback_view(request):
    """Open every feedback form for the second round without deleting round one."""
    if request.method != 'POST':
        messages.warning(request, "Invalid request method.")
        return redirect('manage_feedback_forms')

    now = timezone.now()
    updated = FeedbackForm.objects.update(second_feedback_enabled=True, is_active=True)
    FeedbackForm.objects.filter(start_date__gt=now).update(start_date=now)
    FeedbackForm.objects.filter(end_date__lt=now).update(end_date=now + timezone.timedelta(days=30))
    messages.success(request, f"Feedback 2 is now open for all {updated} forms.")
    return redirect('manage_feedback_forms')


@login_required
@user_passes_test(is_admin)
def stored_exports_view(request):
    """Separate page to manage stored export archive."""
    stored_exports = StoredExport.objects.select_related('uploaded_by').all()
    upload_form = StoredExportUploadForm()
    return render(request, 'stored_exports.html', {
        'stored_exports': stored_exports,
        'stored_export_upload_form': upload_form,
    })


@login_required
@user_passes_test(is_admin)
def upload_stored_export_view(request):
    """Upload historical export files for admin archive."""
    if request.method != 'POST':
        messages.warning(request, "Invalid request method.")
        return redirect('stored_exports')

    form = StoredExportUploadForm(request.POST, request.FILES)
    if form.is_valid():
        stored_export = form.save(commit=False)
        stored_export.uploaded_by = request.user
        stored_export.save()
        messages.success(request, f'Export file "{stored_export.title}" uploaded successfully.')
    else:
        messages.error(request, "Upload failed. Please provide a title and a valid file.")

    return redirect('stored_exports')


@login_required
@user_passes_test(is_admin)
def delete_stored_export_view(request, export_id):
    """Delete a stored export file from archive."""
    if request.method != 'POST':
        messages.warning(request, "Invalid request method.")
        return redirect('stored_exports')

    stored_export = get_object_or_404(StoredExport, id=export_id)
    title = stored_export.title
    if stored_export.export_file:
        stored_export.export_file.delete(save=False)
    stored_export.delete()
    messages.success(request, f'Stored export "{title}" deleted successfully.')
    return redirect('stored_exports')


@login_required
@user_passes_test(is_admin)
def update_stored_export_title_view(request, export_id):
    """Update the title of a stored export archive item."""
    if request.method != 'POST':
        messages.warning(request, "Invalid request method.")
        return redirect('stored_exports')

    stored_export = get_object_or_404(StoredExport, id=export_id)
    new_title = (request.POST.get('title') or '').strip()

    if not new_title:
        messages.error(request, "Title cannot be empty.")
        return redirect('stored_exports')

    if len(new_title) > 255:
        messages.error(request, "Title is too long (maximum 255 characters).")
        return redirect('stored_exports')

    old_title = stored_export.title
    stored_export.title = new_title
    stored_export.save(update_fields=['title'])
    messages.success(request, f'Stored export title updated from "{old_title}" to "{new_title}".')
    return redirect('stored_exports')


@login_required
@user_passes_test(is_admin)
def edit_feedback_form_view(request, form_id):
    """Edit an existing feedback form"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    
    if request.method == 'POST':
        form = FeedbackFormCreationForm(request.POST, instance=feedback_form)
        if form.is_valid():
            form.save()
            messages.success(request, f'Feedback form "{feedback_form.title}" updated successfully!')
            return redirect('manage_feedback_forms')
    else:
        form = FeedbackFormCreationForm(instance=feedback_form)
    
    return render(request, 'edit_feedback_form.html', {
        'form': form, 
        'feedback_form': feedback_form
    })


@login_required
@user_passes_test(is_admin)
def manage_questions_view(request, form_id):
    """Manage questions for a feedback form"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    questions = feedback_form.questions.all().order_by('order')
    
    context = {
        'feedback_form': feedback_form,
        'questions': questions,
    }
    return render(request, 'manage_questions.html', context)


@login_required
@user_passes_test(is_admin)
def add_question_view(request, form_id):
    """Add a new question to a feedback form"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    
    if request.method == 'POST':
        form = FeedbackQuestionForm(request.POST)
        if form.is_valid():
            question = form.save(commit=False)
            question.form = feedback_form
            
            # Set order if not provided
            if not question.order:
                max_order = feedback_form.questions.aggregate(
                    max_order=Max('order')
                )['max_order'] or 0
                question.order = max_order + 1
            
            question.save()
            messages.success(request, "Question added successfully!")
            return redirect('manage_questions', form_id=form_id)
    else:
        form = FeedbackQuestionForm()
    
    context = {
        'form': form,
        'feedback_form': feedback_form,
        'action': 'Add',
        'choices_json': '[]',
    }
    return render(request, 'add_edit_question.html', context)


@login_required
@user_passes_test(is_admin)
def edit_question_view(request, form_id, question_id):
    """Edit an existing question"""
    import json
    
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    question = get_object_or_404(FeedbackQuestion, id=question_id, form=feedback_form)
    
    if request.method == 'POST':
        form = FeedbackQuestionForm(request.POST, instance=question)
        if form.is_valid():
            form.save()
            messages.success(request, "Question updated successfully!")
            return redirect('manage_questions', form_id=form_id)
    else:
        form = FeedbackQuestionForm(instance=question)
        # Convert choices list to JSON string for the form
        if question.choices and isinstance(question.choices, list):
            form.initial['choices'] = json.dumps(question.choices)
    
    context = {
        'form': form,
        'feedback_form': feedback_form,
        'question': question,
        'action': 'Edit',
        'choices_json': json.dumps(question.choices) if question.choices else '[]',
    }
    return render(request, 'add_edit_question.html', context)


@login_required
@user_passes_test(is_admin)
def delete_question_view(request, form_id, question_id):
    """Delete a question from a feedback form"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    question = get_object_or_404(FeedbackQuestion, id=question_id, form=feedback_form)
    
    if request.method == 'POST':
        question_text = question.question_text[:50]
        question.delete()
        messages.success(request, f"Question '{question_text}' deleted successfully!")
        return redirect('manage_questions', form_id=form_id)
    
    context = {
        'feedback_form': feedback_form,
        'question': question,
    }
    return render(request, 'confirm_delete_question.html', context)


@login_required
@user_passes_test(is_admin)
def reorder_questions_view(request, form_id):
    """Reorder questions via AJAX"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    
    if request.method == 'POST':
        import json
        try:
            question_orders = json.loads(request.body)
            
            with transaction.atomic():
                for item in question_orders:
                    question_id = item['id']
                    new_order = item['order']
                    FeedbackQuestion.objects.filter(
                        id=question_id, 
                        form=feedback_form
                    ).update(order=new_order)
            
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
@user_passes_test(is_admin)
def update_question_ajax(request, form_id, question_id):
    """Update a question via AJAX for inline editing"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    question = get_object_or_404(FeedbackQuestion, id=question_id, form=feedback_form)
    
    if request.method == 'POST':
        import json
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            question_text = data.get('question_text', '').strip()
            if not question_text:
                return JsonResponse({'success': False, 'error': 'Question text is required'})
            
            question_type = data.get('question_type', 'rating')
            is_required = data.get('is_required', True)
            choices_text = data.get('choices', '').strip()
            
            # Process choices for multiple choice questions
            choices = []
            if question_type == 'multiple_choice':
                if not choices_text:
                    return JsonResponse({'success': False, 'error': 'Choices are required for multiple choice questions'})
                choices = [choice.strip() for choice in choices_text.split('\n') if choice.strip()]
                if len(choices) < 2:
                    return JsonResponse({'success': False, 'error': 'At least 2 choices are required for multiple choice questions'})
            
            # Update the question
            with transaction.atomic():
                question.question_text = question_text
                question.question_type = question_type
                question.is_required = is_required
                question.choices = choices if question_type == 'multiple_choice' else []
                question.save()
            
            # Return updated question data
            return JsonResponse({
                'success': True,
                'question': {
                    'id': question.id,
                    'question_text': question.question_text,
                    'question_type': question.question_type,
                    'is_required': question.is_required,
                    'choices': question.choices
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
@user_passes_test(is_admin)
def delete_question_ajax(request, form_id, question_id):
    """Delete a question via AJAX for inline editing"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    question = get_object_or_404(FeedbackQuestion, id=question_id, form=feedback_form)
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                question.delete()
                
                # Reorder remaining questions
                remaining_questions = FeedbackQuestion.objects.filter(form=feedback_form).order_by('order')
                for index, q in enumerate(remaining_questions, 1):
                    if q.order != index:
                        q.order = index
                        q.save()
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
def fill_feedback_form_view(request, form_id):
    """Student fills out a feedback form"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    
    try:
        student = Student.objects.get(user=request.user)
    except Student.DoesNotExist:
        messages.error(request, "Only students can fill feedback forms.")
        return redirect('dashboard')
    
    feedback_round = 2 if feedback_form.second_feedback_enabled else 1

    # Round one remains immutable; enabling round two permits one new response.
    if FeedbackResponse.objects.filter(
        form=feedback_form, student=student, feedback_round=feedback_round
    ).exists():
        messages.error(request, "You have already submitted feedback for this form.")
        return redirect('dashboard')
    
    # Check if form is active and within time range
    current_time = timezone.now()
    if not (feedback_form.is_active and 
            feedback_form.start_date <= current_time <= feedback_form.end_date):
        messages.error(request, "This feedback form is not currently available.")
        return redirect('dashboard')
    
    # Check if student is eligible for this form
    eligible = False
    if feedback_form.subject.subject_type == 'theory':
        if feedback_form.division == student.division:
            eligible = True
    elif feedback_form.subject.subject_type in ['practical', 'tutorials']:
        if feedback_form.practical_batch == student.practical_batch:
            eligible = True
    
    if not eligible:
        messages.error(request, "You are not eligible to fill this feedback form.")
        return redirect('dashboard')
    
    # Check if form is for an elective subject and if student has selected it
    if feedback_form.subject.elective is not None:
        # This is an elective subject - check if student has selected it
        elective_selected = StudentElectiveSelection.objects.filter(
            student=student,
            subject=feedback_form.subject
        ).exists()
        
        if not elective_selected:
            messages.error(request, "You can only fill feedback forms for elective subjects you have selected.")
            return redirect('dashboard')
    
    questions = feedback_form.questions.all().order_by('order')
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Create feedback response
                response = FeedbackResponse.objects.create(
                    form=feedback_form,
                    student=student,
                    feedback_round=feedback_round,
                    is_anonymous=request.POST.get('is_anonymous') == 'on'
                )
                
                # Save answers
                for question in questions:
                    answer_key = f'question_{question.id}'
                    if answer_key in request.POST:
                        answer_value = request.POST[answer_key].strip()
                        
                        if question.is_required and not answer_value:
                            raise ValidationError(f"Question '{question.question_text}' is required.")
                        
                        if answer_value:  # Only save non-empty answers
                            answer = FeedbackAnswer(response=response, question=question)
                            
                            if question.question_type == 'rating':
                                answer.rating_answer = int(answer_value)
                            elif question.question_type == 'text':
                                answer.text_answer = answer_value
                            elif question.question_type == 'multiple_choice':
                                answer.choice_answer = answer_value
                            
                            answer.save()
                
                # Find next available form for this student
                try:
                    student = Student.objects.get(user=request.user)
                    
                    # Get all available forms for this student (theory and practical/tutorial separately)
                    # Theory forms for student's division (non-elective)
                    theory_forms = FeedbackForm.objects.filter(
                        is_active=True,
                        division=student.division,
                        subject__subject_type='theory',
                        subject__elective__isnull=True,
                        start_date__lte=timezone.now(),
                        end_date__gte=timezone.now(),
                    )
                    theory_forms = _forms_available_for_student_round(theory_forms, student)
                    
                    # Practical/tutorial forms for student's batch (non-elective)
                    practical_forms = FeedbackForm.objects.none()
                    if student.practical_batch:
                        practical_forms = FeedbackForm.objects.filter(
                            is_active=True,
                            practical_batch=student.practical_batch,
                            subject__subject_type__in=['practical', 'tutorials'],
                            subject__elective__isnull=True,
                            start_date__lte=timezone.now(),
                            end_date__gte=timezone.now(),
                        )
                        practical_forms = _forms_available_for_student_round(practical_forms, student)
                    
                    # Elective forms they've selected
                    elective_selected_subjects = StudentElectiveSelection.objects.filter(
                        student=student
                    ).values_list('subject_id', flat=True)
                    
                    elective_forms = FeedbackForm.objects.filter(
                        subject__id__in=elective_selected_subjects,
                        is_active=True
                    ).filter(
                        Q(subject__subject_type='theory', division=student.division) |
                        Q(subject__subject_type__in=['practical', 'tutorials'], practical_batch=student.practical_batch)
                    ).filter(
                        start_date__lte=timezone.now(),
                        end_date__gte=timezone.now(),
                    )
                    elective_forms = _forms_available_for_student_round(elective_forms, student)
                    
                    # Combine all available forms
                    all_available_forms = (theory_forms | practical_forms | elective_forms).distinct()
                    
                    # Find the next form to fill
                    next_form = all_available_forms.first() if all_available_forms.exists() else None
                    
                    if next_form:
                        messages.success(request, f"Feedback submitted successfully! Redirecting to next form: {next_form.title}")
                        return redirect('fill_feedback_form', form_id=next_form.id)
                    else:
                        messages.success(request, "Feedback submitted successfully! All available forms completed.")
                        return redirect('dashboard')
                        
                except Student.DoesNotExist:
                    messages.success(request, "Feedback submitted successfully!")
                    return redirect('dashboard')
                
        except (ValidationError, ValueError) as e:
            messages.error(request, f"Error submitting feedback: {e}")
    
    return render(request, 'fill_feedback_form.html', {
        'form': feedback_form,
        'questions': questions,
    })


@login_required
def feedback_completed_view(request, form_id):
    """View to show feedback completion and available next forms"""
    try:
        student = Student.objects.get(user=request.user)
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('dashboard')
    
    completed_form = get_object_or_404(FeedbackForm, id=form_id)
    
    # Find available feedback forms for this student
    # For theory subjects, match by division only
    # For practical/tutorial subjects, match by division and practical_batch
    # For elective subjects, check if student has selected them
    available_forms = FeedbackForm.objects.filter(
        is_active=True,
        division=student.division
    ).exclude(
        # Exclude forms where student has already submitted feedback
        id__in=FeedbackResponse.objects.filter(student=student).values_list('form_id', flat=True)
    )
    
    # Further filter based on subject type and elective selection
    filtered_forms = []
    for form in available_forms:
        if form.subject.elective is not None:
            # Elective subject - check if student has selected it
            if StudentElectiveSelection.objects.filter(
                student=student,
                subject=form.subject
            ).exists():
                filtered_forms.append(form)
        elif form.subject.subject_type == 'theory':
            # Theory subjects (non-elective) - just check division
            filtered_forms.append(form)
        elif form.subject.subject_type in ['practical', 'tutorials']:
            # Practical/tutorial subjects (non-elective) - check if student's batch matches
            if student.practical_batch and form.practical_batch == student.practical_batch:
                filtered_forms.append(form)
    
    available_forms = sorted(filtered_forms, key=lambda x: x.title)
    
    context = {
        'completed_form': completed_form,
        'available_forms': available_forms,
        'student': student,
    }
    
    return render(request, 'feedback_completed.html', context)


@login_required
@user_passes_test(is_admin)
def toggle_form_status_view(request, form_id):
    """Toggle the active status of a feedback form"""
    if request.method == 'POST':
        feedback_form = get_object_or_404(FeedbackForm, id=form_id)
        feedback_form.is_active = not feedback_form.is_active
        feedback_form.save()
        
        status = "activated" if feedback_form.is_active else "deactivated"
        messages.success(request, f'Form "{feedback_form.title}" has been {status}.')
    
    return redirect('manage_feedback_forms')


@login_required
def professor_dashboard_view(request):
    """Dashboard for professors to view their feedback"""
    try:
        professor = Professor.objects.get(user=request.user)
        
        # Get forms assigned to this professor
        professor_forms = FeedbackForm.objects.filter(
            professor=professor
        ).select_related('subject', 'division', 'practical_batch')
        
        # Get response statistics
        total_responses = FeedbackResponse.objects.filter(
            form__professor=professor
        ).count()
        
        context = {
            'professor': professor,
            'forms': professor_forms,
            'total_responses': total_responses,
        }
        
        return render(request, 'professor_dashboard.html', context)
        
    except Professor.DoesNotExist:
        messages.error(request, "Professor profile not found.")
        return redirect('dashboard')

def _get_students_not_filled_data(students_query, include_forms=True):
    """Compute pending feedback data in bulk to avoid N+1 queries."""
    students = list(
        students_query.select_related('division', 'user', 'practical_batch').order_by(
            Cast('roll_number', IntegerField())
        )
    )

    if not students:
        return []

    student_ids = [student.id for student in students]
    division_ids = {student.division_id for student in students}
    practical_batch_ids = {student.practical_batch_id for student in students if student.practical_batch_id}

    theory_forms_by_division = defaultdict(list)
    theory_forms = FeedbackForm.objects.filter(
        division_id__in=division_ids,
        subject__subject_type='theory',
        subject__elective__isnull=True,
        is_active=True,
    ).select_related('subject', 'professor', 'division', 'practical_batch')
    for form in theory_forms:
        theory_forms_by_division[form.division_id].append(form)

    practical_forms_by_batch = defaultdict(list)
    if practical_batch_ids:
        practical_forms = FeedbackForm.objects.filter(
            practical_batch_id__in=practical_batch_ids,
            subject__subject_type__in=['practical', 'tutorials'],
            subject__elective__isnull=True,
            is_active=True,
        ).select_related('subject', 'professor', 'division', 'practical_batch')
        for form in practical_forms:
            practical_forms_by_batch[form.practical_batch_id].append(form)

    selected_subjects_by_student = defaultdict(set)
    selected_subject_ids = set()
    selections = StudentElectiveSelection.objects.filter(
        student_id__in=student_ids
    ).values_list('student_id', 'subject_id')
    for student_id, subject_id in selections:
        selected_subjects_by_student[student_id].add(subject_id)
        selected_subject_ids.add(subject_id)

    elective_forms_by_subject = defaultdict(list)
    if selected_subject_ids:
        elective_forms = FeedbackForm.objects.filter(
            subject_id__in=selected_subject_ids,
            is_active=True,
        ).select_related('subject', 'professor', 'division', 'practical_batch')
        for form in elective_forms:
            elective_forms_by_subject[form.subject_id].append(form)

    filled_forms_by_student = defaultdict(set)
    filled_pairs = FeedbackResponse.objects.filter(
        student_id__in=student_ids
    ).values_list('student_id', 'form_id')
    for student_id, form_id in filled_pairs:
        filled_forms_by_student[student_id].add(form_id)

    result = []
    for student in students:
        eligible_forms = {}

        for form in theory_forms_by_division.get(student.division_id, []):
            eligible_forms[form.id] = form

        if student.practical_batch_id:
            for form in practical_forms_by_batch.get(student.practical_batch_id, []):
                eligible_forms[form.id] = form

        selected_subjects = selected_subjects_by_student.get(student.id, set())
        if selected_subjects:
            for subject_id in selected_subjects:
                for form in elective_forms_by_subject.get(subject_id, []):

                    if form.subject.subject_type == 'theory' and form.division_id == student.division_id:
                        eligible_forms[form.id] = form
                    elif (
                        form.subject.subject_type in ['practical', 'tutorials']
                        and student.practical_batch_id
                        and form.practical_batch_id == student.practical_batch_id
                    ):
                        eligible_forms[form.id] = form

        if not eligible_forms:
            continue

        filled_form_ids = filled_forms_by_student.get(student.id, set())
        unfilled_forms = [form for form_id, form in eligible_forms.items() if form_id not in filled_form_ids]

        if unfilled_forms:
            item = {
                'student': student,
                'unfilled_forms': len(unfilled_forms),
                'total_forms': len(eligible_forms),
            }
            if include_forms:
                item['forms'] = sorted(unfilled_forms, key=lambda f: f.title)
            result.append(item)

    def _roll_sort_key(item):
        roll = (item['student'].roll_number or '').strip().lower()
        parts = re.split(r'(\d+)', roll)
        return [int(part) if part.isdigit() else part for part in parts]

    result.sort(key=_roll_sort_key)
    return result


@login_required
@user_passes_test(is_admin)
def students_not_filled_forms_view(request):
    """Show students who haven't filled feedback forms filtered by year and division"""
    # Build year and division filter data using one divisions query
    years = list(Division.objects.values_list('year', flat=True).distinct().order_by('year'))
    all_divisions = list(Division.objects.all().order_by('year', 'name'))
    
    # Get filter parameters from request
    selected_year = request.GET.get('year')
    selected_division = request.GET.get('division')
    
    # Build base query for students
    students_query = Student.objects.all()
    
    if selected_year and selected_year.isdigit():
        students_query = students_query.filter(division__year=int(selected_year))
    
    if selected_division and selected_division.isdigit():
        students_query = students_query.filter(division_id=int(selected_division))
    
    students_not_filled = _get_students_not_filled_data(students_query, include_forms=True)
    
    context = {
        'students_not_filled': students_not_filled,
        'years': years,
        'all_divisions': all_divisions,
        'selected_year': selected_year,
        'selected_division': selected_division,
    }
    
    return render(request, 'students_not_filled_forms.html', context)


@login_required
@user_passes_test(is_admin)
def export_students_not_filled_forms_view(request):
    """Export students who haven't filled forms to XLSX or PDF"""
    if request.method != 'POST':
        return redirect('students_not_filled')
    
    # Get filter parameters from POST request
    selected_year = request.POST.get('year')
    selected_division = request.POST.get('division')
    
    export_type = request.POST.get('export_type', 'xlsx').lower()

    # Build base query for students
    students_query = Student.objects.all()
    
    if selected_year and selected_year.isdigit():
        students_query = students_query.filter(division__year=int(selected_year))
    
    if selected_division and selected_division.isdigit():
        students_query = students_query.filter(division_id=int(selected_division))
    
    export_rows = []
    export_data = _get_students_not_filled_data(students_query, include_forms=False)
    for item in export_data:
        student = item['student']
        practical_batch_name = student.practical_batch.name if student.practical_batch else 'N/A'
        export_rows.append([
            student.roll_number,
            student.user.get_full_name(),
            student.user.email or 'N/A',
            student.division.name,
            student.division.get_year_display(),
            student.semester,
            practical_batch_name,
            item['unfilled_forms'],
            item['total_forms'],
        ])

    headers = [
        'Roll Number', 'Student Name', 'Email', 'Division', 'Year', 'Semester',
        'Practical Batch', 'Pending Forms Count', 'Total Forms Count'
    ]
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')

    if export_type == 'xlsx':
        wb = Workbook()
        ws = wb.active
        ws.title = 'Students Not Filled'
        ws.append(headers)

        for row in export_rows:
            ws.append(row)

        for col in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(col)].width = 22

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        filename = f"students_not_filled_forms_{timestamp}.xlsx"

        _archive_export_file(
            request.user,
            "Students Not Filled Export (XLSX)",
            filename,
            output.getvalue(),
        )

        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{filename}"'
        )
        return response

    if export_type == 'pdf':
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.units import mm
            from reportlab.pdfgen import canvas
        except ImportError:
            messages.error(request, 'PDF export requires reportlab. Install it and try again.')
            return redirect('students_not_filled')

        output = BytesIO()
        pdf = canvas.Canvas(output, pagesize=landscape(A4))
        width, height = landscape(A4)

        title = 'Students Not Filled Forms'
        pdf.setFont('Helvetica-Bold', 14)
        pdf.drawString(15 * mm, height - 15 * mm, title)
        pdf.setFont('Helvetica', 9)
        pdf.drawString(15 * mm, height - 22 * mm, f'Generated: {timezone.now().strftime("%Y-%m-%d %H:%M")}')

        x_positions = [10, 28, 72, 128, 149, 166, 185, 214, 244]
        y = height - 32 * mm

        pdf.setFont('Helvetica-Bold', 8)
        header_labels = ['Roll', 'Student', 'Email', 'Div', 'Year', 'Sem', 'Batch', 'Pending', 'Total']
        for i, label in enumerate(header_labels):
            pdf.drawString(x_positions[i] * mm, y, label)

        y -= 6 * mm
        pdf.setFont('Helvetica', 8)

        for row in export_rows:
            if y < 12 * mm:
                pdf.showPage()
                y = height - 15 * mm
                pdf.setFont('Helvetica-Bold', 8)
                for i, label in enumerate(header_labels):
                    pdf.drawString(x_positions[i] * mm, y, label)
                y -= 6 * mm
                pdf.setFont('Helvetica', 8)

            values = [
                str(row[0])[:18],
                str(row[1])[:28],
                str(row[2])[:36],
                str(row[3])[:8],
                str(row[4])[:10],
                str(row[5]),
                str(row[6])[:12],
                str(row[7]),
                str(row[8]),
            ]

            for i, value in enumerate(values):
                pdf.drawString(x_positions[i] * mm, y, value)
            y -= 5 * mm

        pdf.save()
        output.seek(0)
        filename = f"students_not_filled_forms_{timestamp}.pdf"

        #_archive_export_file(
        #    request.user,
        #    "Students Not Filled Export (PDF)",
        #    filename,
        #    output.getvalue(),
        #)

        response = HttpResponse(output.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="{filename}"'
        )
        return response

    messages.error(request, 'Unsupported export type selected.')
    return redirect('students_not_filled')


# AJAX Views for dynamic form population
@login_required
@user_passes_test(is_admin)
def get_subjects_by_type(request):
    """Get subjects filtered by subject type, division, and optionally practical batch"""
    subject_type = request.GET.get('subject_type')
    division_id = request.GET.get('division_id')
    practical_batch_id = request.GET.get('practical_batch_id')
    
    if not subject_type:
        return JsonResponse({'subjects': []})
    
    # Base query for subjects of the specified type
    subjects_query = Subject.objects.filter(subject_type=subject_type)
    
    # If division_id is provided, filter subjects by the calculated year that matches the division's year
    if division_id:
        try:
            division = Division.objects.get(id=division_id)
            division_year = division.year
            
            # Filter subjects where the calculated year matches the division's year
            # Get all subjects for this subject type first
            all_subjects = subjects_query.all()
            matching_subjects = []
            
            for subject in all_subjects:
                calculated_year = ((subject.semester - 1) // 2) + 1
                if calculated_year == division_year:
                    matching_subjects.append(subject.pk)
            
            subjects_query = subjects_query.filter(id__in=matching_subjects)
            
        except Division.DoesNotExist:
            pass  # If division doesn't exist, show all subjects of the type
    
    subjects = subjects_query.values('id', 'code', 'name', 'semester').order_by('semester', 'code')
    
    # Add calculated year to each subject
    subjects_list = []
    for subject in subjects:
        subject['year'] = ((subject['semester'] - 1) // 2) + 1
        subjects_list.append(subject)
    
    return JsonResponse({'subjects': subjects_list})


@login_required
@user_passes_test(is_admin)
def get_professors_by_subject_division(request):
    """Get professors based on subject, division, and optionally practical batch"""
    subject_id = request.GET.get('subject_id')
    division_id = request.GET.get('division_id')
    practical_batch_id = request.GET.get('practical_batch_id')
    
    if not subject_id or not division_id:
        return JsonResponse({'professors': []})
    
    try:
        subject = Subject.objects.get(id=subject_id)
        
        # Get all professors - for form creation, we want to show all available professors
        # The user can choose which professor to create a feedback form for
        professors = Professor.objects.all().values('id', 'user__first_name', 'user__last_name', 'employee_id')
        
        # Format professor names
        professor_list = []
        for prof in professors:
            professor_list.append({
                'id': prof['id'],
                'name': f"{prof['user__first_name']} {prof['user__last_name']} ({prof['employee_id']})"
            })
        
        return JsonResponse({'professors': professor_list})
        
    except Subject.DoesNotExist:
        return JsonResponse({'professors': []})


@login_required
@user_passes_test(is_admin)
def get_batches_by_division(request):
    """Get practical batches for a division"""
    division_id = request.GET.get('division_id')
    
    try:
        division = Division.objects.get(id=division_id)
        batches = PracticalBatch.objects.filter(division=division).values('id', 'name')
        return JsonResponse({'batches': list(batches)})
    except Division.DoesNotExist:
        return JsonResponse({'batches': []})


@login_required
@user_passes_test(is_admin)
def get_default_questions_by_subject_type(request):
    """Get default questions for a subject type"""
    subject_type = request.GET.get('subject_type')
    
    if not subject_type:
        return JsonResponse({'questions': []})
    
    # Define questions for each subject type
    theory_questions = [
        "Ability to stimulate students interest by generating questions / enquiry during Lectures, Practical and Tutorials",
        "Teaching / Instructing methodology using different facilities (chalkboard / LCD etc.) as appropriate for the topic",
        "Handling doubts/ questions",
        "Approach towards subject, Practical and Tutorials",
        "Organisation of Lecture, Practical and Tutorials",
        "Pace of teaching / Instructions",
        "Knowlege of topic, Practical and Tutorials",
        "Medium of language- Use of English",
        "Manner of initiation of Lecture, Practical and Tutorials by mentioning the aims /Objective of the topics / practical/ assignment – under consideration",
        "Punctuality & Regularity during Lecture, Practical and Tutorials",
        "Behaviour of faculty towards students",
        "Overall impression",
        "Any other criticism",
        "Improvement"
    ]
    
    practical_questions = [
        "Organisation of Lecture, Practical and Tutorials",
        "Pace of teaching / Instructions",
        "Knowlege of topic, Practical and Tutorials",
        "Medium of language- Use of English",
        "Manner of initiation of Lecture, Practical and Tutorials by mentioning the aims /Objective of the topics / practical/ assignment – under consideration",
        "Punctuality & Regularity during Lecture, Practical and Tutorials",
        "Behaviour of faculty towards students",
        "Overall impression",
        "Any other feedback"
    ]
    
    tutorial_questions = [
        "Organisation of Lecture, Practical and Tutorials",
        "Pace of teaching / Instructions",
        "Knowlege of topic, Practical and Tutorials",
        "Medium of language- Use of English",
        "Manner of initiation of Lecture, Practical and Tutorials by mentioning the aims /Objective of the topics / practical/ assignment – under consideration",
        "Punctuality & Regularity during Lecture, Practical and Tutorials",
        "Behaviour of faculty towards students",
        "Overall impression",
        "Any other feedback"
    ]
    
    # Select questions based on subject type
    if subject_type == 'theory':
        selected_questions = theory_questions
    elif subject_type == 'practical':
        selected_questions = practical_questions
    elif subject_type == 'tutorials':
        selected_questions = tutorial_questions
    else:
        # Fallback questions
        selected_questions = [
            "Rate the overall teaching quality",
            "How would you rate the clarity of explanations?",
            "Rate the professor's punctuality",
            "How helpful was the professor in addressing doubts?",
            "Any additional comments or suggestions"
        ]
    
    # Create question objects
    questions_list = []
    for question_text in selected_questions:
        # Determine question type based on content
        if any(keyword in question_text.lower() for keyword in ['criticism', 'feedback', 'improvement', 'comment', 'suggestion']):
            question_type = 'text'
            is_required = False
        else:
            question_type = 'rating'
            is_required = True
        
        questions_list.append({
            "text": question_text,
            "type": question_type,
            "required": is_required
        })
    
    return JsonResponse({'questions': questions_list})


@login_required
@user_passes_test(is_admin)
def view_feedback_responses(request, form_id):
    """View all responses for a feedback form with search functionality"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    
    # Check if user has permission to view this form
    if not request.user.is_staff:
        messages.error(request, "You don't have permission to view these responses.")
        return redirect('dashboard')
    
    # Get search parameters
    search_query = request.GET.get('search', '').strip()
    filter_anonymous = request.GET.get('filter_anonymous', '')
    sort_by = request.GET.get('sort_by', '-submitted_at')  # Default: newest first
    
    # Start with all responses for this form
    responses = FeedbackResponse.objects.filter(form=feedback_form).select_related(
        'student__user', 'student__division'
    ).prefetch_related('answers__question')
    
    # Apply search filter
    if search_query:
        responses = responses.filter(
            student__roll_number__icontains=search_query
        ) | responses.filter(
            student__user__first_name__icontains=search_query
        ) | responses.filter(
            student__user__last_name__icontains=search_query
        )
    
    # Apply anonymous filter
    if filter_anonymous == 'anonymous_only':
        responses = responses.filter(is_anonymous=True)
    elif filter_anonymous == 'non_anonymous_only':
        responses = responses.filter(is_anonymous=False)
    
    # Apply sorting
    valid_sort_options = ['-submitted_at', 'submitted_at', 'student__roll_number', '-student__roll_number']
    if sort_by in valid_sort_options:
        responses = responses.order_by(sort_by)
    else:
        responses = responses.order_by('-submitted_at')
    
    questions = feedback_form.questions.all().order_by('order')
    
    # Calculate overall statistics
    total_responses = responses.count()
    
    # Get ALL responses for question analysis (not filtered)
    all_responses = FeedbackResponse.objects.filter(form=feedback_form)
    
    # Calculate eligible students count (including elective-specific eligibility)
    if feedback_form.subject.elective is not None:
        # For elective subjects, only students who selected this subject are eligible
        selected_student_ids = StudentElectiveSelection.objects.filter(
            subject=feedback_form.subject
        ).values_list('student_id', flat=True)

        eligible_students = Student.objects.filter(id__in=selected_student_ids)

        # Keep division/batch constraints for the form target audience
        if feedback_form.division:
            eligible_students = eligible_students.filter(division=feedback_form.division)
        if feedback_form.practical_batch:
            eligible_students = eligible_students.filter(practical_batch=feedback_form.practical_batch)

        eligible_students = eligible_students.distinct()
    elif feedback_form.practical_batch:
        # For non-elective practical subjects, count students in the specific batch
        eligible_students = Student.objects.filter(
            division=feedback_form.division,
            practical_batch=feedback_form.practical_batch
        ).distinct()
    else:
        # For non-elective theory subjects, count all students in the division
        eligible_students = Student.objects.filter(division=feedback_form.division)
    
    eligible_students_count = eligible_students.count()
    
    # Get students who have already submitted responses
    responded_student_ids = all_responses.values_list('student_id', flat=True)
    
    # Get students who haven't submitted responses yet
    pending_students = eligible_students.exclude(id__in=responded_student_ids).select_related('user', 'division', 'practical_batch')
    pending_students_count = pending_students.count()
    
    # Calculate response rate
    response_rate = (total_responses / eligible_students_count * 100) if eligible_students_count > 0 else 0
    
    # Calculate count of active forms
    active_forms_count = FeedbackForm.objects.filter(is_active=True).count()
    
    # Prepare question-wise analysis (using ALL responses, not filtered)
    question_responses = []
    for question in questions:
        question_data = {
            'question': question,
            'total_responses': 0,
        }
        
        if question.question_type == 'rating':
            # Get all rating responses for this question
            rating_answers = FeedbackAnswer.objects.filter(
                question=question,
                response__in=all_responses,  # Use all_responses instead of form filter
                rating_answer__isnull=False
            ).values_list('rating_answer', flat=True)
            
            rating_list = list(rating_answers)
            question_data.update({
                'total_responses': len(rating_list),
                'rating_distribution': {i: rating_list.count(i) for i in range(1, 6)},
                'average': sum(rating_list) / len(rating_list) if rating_list else 0,
                'max_rating': max(rating_list) if rating_list else 0,
                'min_rating': min(rating_list) if rating_list else 0,
            })
        
        elif question.question_type == 'text':
            # Get all text responses for this question
            text_answers = FeedbackAnswer.objects.filter(
                question=question,
                response__in=all_responses,  # Use all_responses instead of form filter
                text_answer__isnull=False
            ).exclude(text_answer='').values_list('text_answer', flat=True)
            
            question_data.update({
                'text_responses': list(text_answers),
                'total_responses': len(text_answers),
            })
        
        elif question.question_type == 'multiple_choice':
            # Get all multiple choice responses for this question
            choice_answers = FeedbackAnswer.objects.filter(
                question=question,
                response__in=all_responses,  # Use all_responses instead of form filter
                choice_answer__isnull=False
            ).exclude(choice_answer='').values_list('choice_answer', flat=True)
            
            choice_list = list(choice_answers)
            
            # Calculate choice distribution
            choice_distribution = {}
            for choice in choice_list:
                choice_distribution[choice] = choice_distribution.get(choice, 0) + 1
            
            question_data.update({
                'choice_distribution': choice_distribution,
                'total_responses': len(choice_list),
            })
        
        question_responses.append(question_data)
    
    context = {
        'form': feedback_form,
        'responses': responses,
        'questions': questions,
        'question_responses': question_responses,
        'total_responses': total_responses,
        'eligible_students_count': eligible_students_count,
        'pending_students': pending_students,
        'pending_students_count': pending_students_count,
        'response_rate': response_rate,
        'active_forms_count': active_forms_count,
        'search_query': search_query,
        'filter_anonymous': filter_anonymous,
        'sort_by': sort_by,
    }
    
    return render(request, 'view_feedback_responses.html', context)


@login_required
@user_passes_test(is_admin)
def delete_feedback_response(request, form_id, response_id):
    """Delete a specific feedback response"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    response = get_object_or_404(FeedbackResponse, id=response_id, form=feedback_form)
    
    if not request.user.is_staff:
        messages.error(request, "You don't have permission to delete responses.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        student_info = f"{response.student.roll_number} - {response.student.user.get_full_name()}"
        response.delete()
        messages.success(request, f"Response from {student_info} has been deleted successfully.")
        return redirect('view_feedback_responses', form_id=form_id)
    
    context = {
        'form': feedback_form,
        'response': response,
    }
    return render(request, 'confirm_delete_response.html', context)


@login_required
@user_passes_test(is_admin)
def bulk_delete_responses(request, form_id):
    """Bulk delete multiple feedback responses"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    
    if not request.user.is_staff:
        messages.error(request, "You don't have permission to delete responses.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        response_ids = request.POST.getlist('response_ids')
        if response_ids:
            deleted_count = FeedbackResponse.objects.filter(
                id__in=response_ids, 
                form=feedback_form
            ).delete()[0]
            messages.success(request, f"Successfully deleted {deleted_count} responses.")
        else:
            messages.warning(request, "No responses were selected for deletion.")
    
    return redirect('view_feedback_responses', form_id=form_id)


@login_required
@user_passes_test(is_admin)
def clear_all_responses_view(request):
    """Export all responses and then delete all feedback responses from all forms."""
    import zipfile
    from io import BytesIO

    if not request.user.is_staff:
        messages.error(request, "You don't have permission to delete responses.")
        return redirect('dashboard')

    if request.method == 'POST':
        # Get all forms that currently have responses.
        forms_with_responses = FeedbackForm.objects.filter(
            responses__isnull=False
        ).distinct().select_related(
            'subject', 'professor__user', 'practical_batch', 'division'
        )

        if not forms_with_responses.exists():
            messages.warning(request, "No responses found to export or clear.")
            return redirect('manage_feedback_forms')

        zip_buffer = BytesIO()

        try:
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Reuse existing single-form export logic for each form.
                class MockRequest:
                    def __init__(self, user):
                        self.user = user

                mock_request = MockRequest(request.user)

                for form in forms_with_responses:
                    excel_response = export_responses(mock_request, form.id, archive=False)
                    excel_content = excel_response.content

                    safe_subject_name = "".join(
                        c for c in form.subject.name if c.isalnum() or c in (' ', '-', '_')
                    ).rstrip()
                    safe_professor_name = "".join(
                        c for c in form.professor.user.get_full_name() if c.isalnum() or c in (' ', '-', '_')
                    ).rstrip()

                    if form.practical_batch:
                        filename = (
                            f"{form.division}/{form.subject.get_subject_type_display()}/"
                            f"{safe_subject_name}_{safe_professor_name}_{form.practical_batch.name}.xlsx"
                        )
                    else:
                        filename = (
                            f"{form.division}/{form.subject.get_subject_type_display()}/"
                            f"{safe_subject_name}_{safe_professor_name}.xlsx"
                        )
                    zipf.writestr(filename, excel_content)

            # Clear responses only after successful export creation.
            deleted_count = FeedbackResponse.objects.count()
            FeedbackResponse.objects.all().delete()

            zip_buffer.seek(0)
            zip_content = zip_buffer.getvalue()

            _archive_export_file(
                request.user,
                "Backup Before Clear All Responses",
                "all_feedback_responses_backup_before_clear.zip",
                zip_content,
            )

            response = HttpResponse(zip_content, content_type='application/zip')
            response['Content-Disposition'] = (
                'attachment; filename="all_feedback_responses_backup_before_clear.zip"'
            )
            return response

        except Exception as e:
            messages.error(request, f"Error exporting responses. Nothing was deleted: {e}")
            return redirect('manage_feedback_forms')
    else:
        messages.warning(request, "Invalid request method.")

    return redirect('manage_feedback_forms')


@login_required
@user_passes_test(is_admin)
def export_responses(request, form_id, archive=True, feedback_round=None):
    """Export feedback responses to XLSX with enhanced format and separate summary sheet"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    
    if not request.user.is_staff:
        messages.error(request, "You don't have permission to export responses.")
        return redirect('dashboard')
    
    # Create workbook
    wb = Workbook()
    
    # Styling
    title_font = Font(bold=True, size=14, color="FFFFFF")
    title_fill = PatternFill(start_color="a50c22", end_color="a50c22", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    info_font = Font(bold=True, size=12)
    stats_font = Font(bold=True, color="FFFFFF")
    stats_fill = PatternFill(start_color="70AD47", end_color="70AD47", fill_type="solid")
    center_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    def apply_print_layout(worksheet, orientation=None, margins=None):
        """Use a consistent print layout across all sheets."""
        worksheet.page_setup.orientation = orientation or worksheet.ORIENTATION_LANDSCAPE
        worksheet.page_setup.paperSize = worksheet.PAPERSIZE_A4
        worksheet.page_setup.fitToWidth = 1
        worksheet.page_setup.fitToHeight = 0
        margin_values = margins or {
            "left": 0.25,
            "right": 0.25,
            "top": 0.5,
            "bottom": 0.5,
            "header": 0.3,
            "footer": 0.3,
        }
        worksheet.page_margins = PageMargins(**margin_values)
        worksheet.print_options.horizontalCentered = True

        if worksheet.sheet_properties.pageSetUpPr is None:
            worksheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        else:
            worksheet.sheet_properties.pageSetUpPr.fitToPage = True

    def write_themed_info_table(ws, info_data, start_row, end_col):
        """Writes the form details in a themed table layout."""
        label_fill = PatternFill(start_color="F2D7D5", end_color="F2D7D5", fill_type="solid")
        label_font = Font(bold=True, color="a50c22", size=10)
        val_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
        val_font = Font(bold=True, color="333333", size=10)
        
        info_border = Border(
            left=Side(style='thin', color="BFBFBF"),
            right=Side(style='thin', color="BFBFBF"),
            top=Side(style='thin', color="BFBFBF"),
            bottom=Side(style='thin', color="BFBFBF")
        )
        
        row = start_row
        for label, value in info_data:
            # Apply formatting/borders to columns B, C, D (2, 3, 4) before merging
            for col in range(2, 5):
                c = ws.cell(row=row, column=col)
                c.fill = label_fill
                c.border = info_border
            
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
            label_cell = ws.cell(row=row, column=2, value=label)
            label_cell.font = label_font
            label_cell.alignment = center_alignment
            
            # Apply formatting/borders to columns E to end_col before merging
            for col in range(5, end_col + 1):
                c = ws.cell(row=row, column=col)
                c.fill = val_fill
                c.border = info_border
                
            ws.merge_cells(start_row=row, start_column=5, end_row=row, end_column=end_col)
            val_cell = ws.cell(row=row, column=5, value=value)
            val_cell.font = val_font
            val_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
            
            row += 1
        return row
    
    # Get questions and responses
    questions = feedback_form.questions.all().order_by('order')
    responses = FeedbackResponse.objects.filter(form=feedback_form)
    if feedback_round in (1, 2):
        responses = responses.filter(feedback_round=feedback_round)
    responses = responses.select_related(
        'student__user'
    ).prefetch_related('answers__question')
    response_filter = {'response__form': feedback_form}
    if feedback_round in (1, 2):
        response_filter['response__feedback_round'] = feedback_round
    total_responses = responses.count()
    
    # SHEET 1: Individual Student Responses
    ws1 = wb.active
    ws1.title = "Student Responses"
    current_row = 1
    response_info_start_col = 2
    response_info_end_col = max(6, len(questions) + 1)
    
    # Add title and form information
    ws1.merge_cells(
        f'{get_column_letter(response_info_start_col)}{current_row}:{get_column_letter(response_info_end_col)}{current_row}'
    )
    title_cell = ws1.cell(row=current_row, column=response_info_start_col, value=f"Feedback Response Report")
    title_cell.font = title_font
    title_cell.fill = title_fill
    title_cell.alignment = center_alignment
    current_row += 2
    
    # Add form details
    info_data = [
        ("Subject:", f"{feedback_form.subject.code} - {feedback_form.subject.name}"),
        ("Division:", str(feedback_form.division)),
        ("Batch:", str(feedback_form.practical_batch) if feedback_form.practical_batch else "All (Theory)"),
        ("Professor:", str(feedback_form.professor)),
        ("Form Title:", feedback_form.title),
        ("Total Responses:", str(total_responses))
    ]
    
    current_row = write_themed_info_table(ws1, info_data, current_row, response_info_end_col)
    current_row += 1

    # Add question legend so compact Q-headers remain understandable.
    legend_header_fill = PatternFill(start_color="a50c22", end_color="a50c22", fill_type="solid")
    legend_header_font = Font(bold=True, color="FFFFFF", size=10)
    
    # Legend Header Row: "Q. No." (B-D) and "Question Text" (E-End)
    for col in range(2, 5):
        c = ws1.cell(row=current_row, column=col)
        c.fill = legend_header_fill
        c.border = thin_border
    ws1.merge_cells(start_row=current_row, start_column=2, end_row=current_row, end_column=4)
    lbl_qno = ws1.cell(row=current_row, column=2, value="Q. No.")
    lbl_qno.font = legend_header_font
    lbl_qno.alignment = center_alignment
    
    for col in range(5, response_info_end_col + 1):
        c = ws1.cell(row=current_row, column=col)
        c.fill = legend_header_fill
        c.border = thin_border
    ws1.merge_cells(start_row=current_row, start_column=5, end_row=current_row, end_column=response_info_end_col)
    lbl_text = ws1.cell(row=current_row, column=5, value="Question Text")
    lbl_text.font = legend_header_font
    lbl_text.alignment = center_alignment
    
    current_row += 1

    # Row styles
    row_label_fill = PatternFill(start_color="F2D7D5", end_color="F2D7D5", fill_type="solid")
    row_label_font = Font(bold=True, color="a50c22", size=10)
    row_val_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    row_val_font = Font(color="333333", size=10)
    
    for question in questions:
        for col in range(2, 5):
            c = ws1.cell(row=current_row, column=col)
            c.fill = row_label_fill
            c.border = thin_border
        ws1.merge_cells(start_row=current_row, start_column=2, end_row=current_row, end_column=4)
        q_cell = ws1.cell(row=current_row, column=2, value=f"Q{question.order}")
        q_cell.font = row_label_font
        q_cell.alignment = center_alignment
        
        for col in range(5, response_info_end_col + 1):
            c = ws1.cell(row=current_row, column=col)
            c.fill = row_val_fill
            c.border = thin_border
        ws1.merge_cells(start_row=current_row, start_column=5, end_row=current_row, end_column=response_info_end_col)
        text_cell = ws1.cell(row=current_row, column=5, value=question.question_text)
        text_cell.font = row_val_font
        text_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        
        current_row += 1
    
    current_row += 2
    
    # Individual Student Responses section
    ws1.merge_cells(
        f'{get_column_letter(response_info_start_col)}{current_row}:{get_column_letter(response_info_end_col)}{current_row}'
    )
    section_cell = ws1.cell(row=current_row, column=response_info_start_col, value="Individual Student Responses")
    section_cell.font = title_font
    section_cell.fill = title_fill
    section_cell.alignment = center_alignment
    current_row += 2
    
    # Create header row for responses
    header = ['Student Roll Number']
    for question in questions:
        header.append(f"Q{question.order}")
    
    # Write and style header row
    responses_header_row = current_row
    for col, header_text in enumerate(header, 1):
        cell = ws1.cell(row=current_row, column=col, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_alignment
        cell.border = thin_border
    
    # Repeat the responses header on every printed page
    ws1.print_title_rows = f"${responses_header_row}:${responses_header_row}"
    ws1.freeze_panes = f"A{responses_header_row + 1}"
    
    current_row += 1
    
    # Write student response data
    for feedback_response in responses:
        # Respect anonymity settings
        if feedback_response.is_anonymous:
            student_roll = f"Anonymous-{feedback_response.id}"
        else:
            student_roll = feedback_response.student.roll_number
        
        # Start row with student roll number
        row_data = [student_roll]
        
        # Add answers in question order
        answers_dict = {answer.question_id: answer for answer in feedback_response.answers.all()}
        for question in questions:
            answer = answers_dict.get(question.id)
            if answer:
                answer_text = answer.get_answer()
                row_data.append(str(answer_text) if answer_text is not None else '')
            else:
                row_data.append('')
        
        # Write row to worksheet
        for col, value in enumerate(row_data, 1):
            cell = ws1.cell(row=current_row, column=col, value=value)
            cell.border = thin_border
            cell.alignment = center_alignment
            
        current_row += 1
        
    # Add signature of faculty
    current_row += 3
    ws1.merge_cells(start_row=current_row, start_column=response_info_end_col - 2, end_row=current_row, end_column=response_info_end_col)
    sig_line = ws1.cell(row=current_row, column=response_info_end_col - 2, value="_________________________")
    sig_line.font = Font(bold=True)
    sig_line.alignment = Alignment(horizontal="center", vertical="center")
    
    ws1.merge_cells(start_row=current_row + 1, start_column=response_info_end_col - 2, end_row=current_row + 1, end_column=response_info_end_col)
    lbl_sig = ws1.cell(row=current_row + 1, column=response_info_end_col - 2, value="Signature of Faculty")
    lbl_sig.font = Font(bold=True)
    lbl_sig.alignment = Alignment(horizontal="center", vertical="center")
    
    ws1.merge_cells(start_row=current_row + 2, start_column=response_info_end_col - 2, end_row=current_row + 2, end_column=response_info_end_col)
    lbl_name = ws1.cell(row=current_row + 2, column=response_info_end_col - 2, value=f"({feedback_form.professor.user.get_full_name()})")
    lbl_name.font = Font(bold=True)
    lbl_name.alignment = Alignment(horizontal="center", vertical="center")
    current_row += 3

    # Keep print compact for response sheet.
    ws1.column_dimensions['A'].width = 16
    for col in range(2, len(header) + 1):
        ws1.column_dimensions[get_column_letter(col)].width = 10

    # Exclude student roll number from printout while keeping it in the workbook data.
    if len(header) > 1:
        ws1.print_area = f"B1:{get_column_letter(len(header))}{current_row - 1}"
    
    # SHEET 2: Summary Statistics
    ws2 = wb.create_sheet(title="Rating Summary")
    current_row = 1
    rating_questions = questions.filter(question_type='rating')
    response_info_end_col_ws2 = max(6, len(rating_questions) + 3)

    # ── LOGO + INSTITUTE HEADER ──────────────────────────────────────────────
    import os
    logo_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'appfeedback', 'static', 'appfeedback', 'images', 'somaiya.png'
    )
    if os.path.exists(logo_path):
        logo_img = XLImage(logo_path)
        # Size logo to fill column B rows 1-2 so it looks centred in the cell
        logo_img.height = 80   # pixels
        logo_img.width  = 80
        ws2.add_image(logo_img, 'B1')
        # Row heights: 72pt total ≈ 96px to contain the 80px logo
        ws2.row_dimensions[1].height = 45
        ws2.row_dimensions[2].height = 27
        # Set column B width to match the logo so it stays within the cell
        ws2.column_dimensions['B'].width = 12   # ~84px

    # Institute name beside the logo (columns C to end)
    ws2.merge_cells(
        f'C1:{get_column_letter(response_info_end_col_ws2)}1'
    )
    inst_cell = ws2.cell(row=1, column=3,
                         value="K J Somaiya Institute of Technology")
    inst_cell.font = Font(bold=True, size=18, color="a50c22", name="Arial")
    inst_cell.alignment = Alignment(horizontal="center", vertical="center")

    ws2.merge_cells(
        f'C2:{get_column_letter(response_info_end_col_ws2)}2'
    )
    dept_cell = ws2.cell(row=2, column=3,
                         value="Somaiya Vidyavihar University, Mumbai")
    dept_cell.font = Font(italic=True, size=11, color="555555", name="Arial")
    dept_cell.alignment = Alignment(horizontal="center", vertical="center")

    current_row = 4   # gap row after logo/header block

    # ── TITLE ────────────────────────────────────────────────────────────────
    ws2.merge_cells(f'B{current_row}:{get_column_letter(response_info_end_col_ws2)}{current_row}')
    title_cell = ws2.cell(row=current_row, column=2, value="Rating Statistics Summary")
    title_cell.font = title_font
    title_cell.fill = title_fill
    title_cell.alignment = center_alignment
    current_row += 2

    # ── FORM INFO TABLE ───────────────────────────────────────────────────────
    info_data_ws2 = list(info_data)
    if rating_questions.exists():
        max_possible_score = len(rating_questions) * total_responses * 5
        info_data_ws2.append(
            ("Max Possible Score:", f"{max_possible_score} (Questions: {len(rating_questions)} × Responses: {total_responses} × Max Rating: 5)")
        )
    current_row = write_themed_info_table(ws2, info_data_ws2, current_row, response_info_end_col_ws2)
    current_row += 1

    # ── OVERALL SUMMARY BOX (shown right after the info table) ────────────────
    if rating_questions.exists():
        # Calculate overall stats needed for the summary box
        _overall_score = 0
        _overall_max   = len(rating_questions) * total_responses * 5
        _total_rating_count = 0
        _total_weighted     = 0
        for _q in rating_questions:
            _q_answers = FeedbackAnswer.objects.filter(
                question=_q, response__form=feedback_form
            )
            for _a in _q_answers:
                if _a.rating_answer:
                    _total_weighted     += _a.rating_answer
                    _total_rating_count += 1
            for _r in range(1, 6):
                _cnt = _q_answers.filter(rating_answer=_r).count()
                _overall_score += _r * _cnt

        _overall_pct = round((_overall_score / _overall_max * 100), 2) if _overall_max > 0 else 0
        _overall_avg = round(_total_weighted / _total_rating_count, 2) if _total_rating_count > 0 else 0

        # Box border style
        box_border = Border(
            left=Side(style='medium', color="a50c22"),
            right=Side(style='medium', color="a50c22"),
            top=Side(style='medium', color="a50c22"),
            bottom=Side(style='medium', color="a50c22")
        )
        box_fill_left  = PatternFill(start_color="FFF0F0", end_color="FFF0F0", fill_type="solid")
        box_fill_right = PatternFill(start_color="F0F0FF", end_color="F0F0FF", fill_type="solid")
        mid_col = response_info_end_col_ws2 // 2 + 1   # split point between two halves

        # Row 1 of box: labels
        lbl_end_col_left  = mid_col - 1
        lbl_start_col_right = mid_col
        lbl_end_col_right = response_info_end_col_ws2

        for col in range(2, lbl_end_col_left + 1):
            ws2.cell(row=current_row, column=col).fill   = box_fill_left
            ws2.cell(row=current_row, column=col).border = box_border
        ws2.merge_cells(start_row=current_row, start_column=2,
                        end_row=current_row,   end_column=lbl_end_col_left)
        lbl1 = ws2.cell(row=current_row, column=2, value="Overall Percentage (%)")
        lbl1.font      = Font(bold=True, size=11, color="a50c22")
        lbl1.alignment = center_alignment

        for col in range(lbl_start_col_right, lbl_end_col_right + 1):
            ws2.cell(row=current_row, column=col).fill   = box_fill_right
            ws2.cell(row=current_row, column=col).border = box_border
        ws2.merge_cells(start_row=current_row, start_column=lbl_start_col_right,
                        end_row=current_row,   end_column=lbl_end_col_right)
        lbl2 = ws2.cell(row=current_row, column=lbl_start_col_right,
                        value="Overall Average Rating")
        lbl2.font      = Font(bold=True, size=11, color="003399")
        lbl2.alignment = center_alignment
        current_row += 1

        # Row 2 of box: values
        for col in range(2, lbl_end_col_left + 1):
            ws2.cell(row=current_row, column=col).fill   = box_fill_left
            ws2.cell(row=current_row, column=col).border = box_border
        ws2.merge_cells(start_row=current_row, start_column=2,
                        end_row=current_row,   end_column=lbl_end_col_left)
        val1 = ws2.cell(row=current_row, column=2, value=f"{_overall_pct}%")
        val1.font      = Font(bold=True, size=20, color="a50c22")
        val1.alignment = center_alignment
        ws2.row_dimensions[current_row].height = 30

        for col in range(lbl_start_col_right, lbl_end_col_right + 1):
            ws2.cell(row=current_row, column=col).fill   = box_fill_right
            ws2.cell(row=current_row, column=col).border = box_border
        ws2.merge_cells(start_row=current_row, start_column=lbl_start_col_right,
                        end_row=current_row,   end_column=lbl_end_col_right)
        val2 = ws2.cell(row=current_row, column=lbl_start_col_right,
                        value=f"{_overall_avg} / 5")
        val2.font      = Font(bold=True, size=20, color="003399")
        val2.alignment = center_alignment
        current_row += 2   # gap before detailed table
    # ─────────────────────────────────────────────────────────────────────────

    
    if rating_questions.exists():
        
        # Create statistics table with ratings as rows and questions as columns
        # Header row: Rating | Q1 | Q2 | Q3 | ... | Total
        header_row = ['Rating']
        for question in rating_questions:
            header_row.append(f"Q{question.order}")
        header_row.append('Total')
        
        # Write header (shifted 1 column to the right, starting at col 2)
        for col, header_text in enumerate(header_row, 2):
            cell = ws2.cell(row=current_row, column=col, value=header_text)
            cell.font = stats_font
            cell.fill = stats_fill
            cell.alignment = center_alignment
            cell.border = thin_border
        
        current_row += 1
        
        # Collect all rating data first
        rating_data = {}
        question_totals = {}
        
        for question in rating_questions:
            question_answers = FeedbackAnswer.objects.filter(
                question=question,
                **response_filter
            )
            
            question_totals[question.id] = 0
            for rating in range(1, 6):
                if rating not in rating_data:
                    rating_data[rating] = {}
                
                count = question_answers.filter(rating_answer=rating).count()
                rating_data[rating][question.id] = count
                question_totals[question.id] += count
        
        # Write rating rows (1-5) (shifted 1 column to the right, starting at col 2)
        for rating in range(1, 6):
            row_data = [f"Rating {rating}"]
            row_total = 0
            
            for question in rating_questions:
                count = rating_data[rating].get(question.id, 0)
                row_data.append(count)
                row_total += count
            
            row_data.append(row_total)
            
            # Write row
            for col, value in enumerate(row_data, 2):
                cell = ws2.cell(row=current_row, column=col, value=value)
                cell.border = thin_border
                cell.alignment = center_alignment
            
            current_row += 1
        
        # Add total row (shifted 1 column to the right, starting at col 2)
        total_row_data = ['Total']
        grand_total = 0
        for question in rating_questions:
            total = question_totals[question.id]
            total_row_data.append(total)
            grand_total += total
        total_row_data.append(grand_total)
        
        # Write total row with bold font
        for col, value in enumerate(total_row_data, 2):
            cell = ws2.cell(row=current_row, column=col, value=value)
            cell.font = Font(bold=True)
            cell.border = thin_border
            cell.alignment = center_alignment
        
        current_row += 1
        
        # Add weighted score row (rating × count) (shifted 1 column to the right, starting at col 2)
        score_row = ['Weighted Score']
        grand_score = 0
        for question in rating_questions:
            question_score = 0
            for rating in range(1, 6):
                count = rating_data[rating].get(question.id, 0)
                question_score += rating * count
            score_row.append(question_score)
            grand_score += question_score
        score_row.append(grand_score)
        
        # Write weighted score row with bold font and different color
        for col, value in enumerate(score_row, 2):
            cell = ws2.cell(row=current_row, column=col, value=value)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="FF6600", end_color="FF6600", fill_type="solid")
            cell.border = thin_border
            cell.alignment = center_alignment
        
        current_row += 1
        
        # Add percentage row (weighted_score / max_possible_score * 100) - Total only (shifted 1 column to the right, starting at col 2)
        overall_max_score = len(rating_questions) * total_responses * 5
        overall_percentage = round((grand_score / overall_max_score * 100), 2) if overall_max_score > 0 else 0
        
        percent_fill = PatternFill(start_color="9966CC", end_color="9966CC", fill_type="solid")
        percent_font = Font(bold=True, color="FFFFFF")
        
        # Format whole row (borders & fill)
        for col in range(2, len(rating_questions) + 4):
            c = ws2.cell(row=current_row, column=col)
            c.fill = percent_fill
            c.border = thin_border
            
        # Merge label columns B to len(rating_questions)+2
        ws2.merge_cells(start_row=current_row, start_column=2, end_row=current_row, end_column=len(rating_questions) + 2)
        lbl_cell = ws2.cell(row=current_row, column=2, value="Overall Percentage (%)")
        lbl_cell.font = percent_font
        lbl_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        
        # Write percentage value in the last column
        val_cell = ws2.cell(row=current_row, column=len(rating_questions) + 3, value=f"{overall_percentage}%")
        val_cell.font = percent_font
        val_cell.alignment = center_alignment
        
        current_row += 3
        
        # Add average rating calculation (shifted 1 column to the right)
        ws2.cell(row=current_row, column=2, value="Average Ratings:").font = info_font
        current_row += 1
        
        avg_header = ['Question']
        for question in rating_questions:
            avg_header.append(f"Q{question.order}")
        avg_header.append('Overall Avg')
        
        # Write average header (shifted 1 column to the right, starting at col 2)
        for col, header_text in enumerate(avg_header, 2):
            cell = ws2.cell(row=current_row, column=col, value=header_text)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_alignment
            cell.border = thin_border
        
        current_row += 1
        
        # Calculate and write averages
        avg_row = ['Average Rating']
        total_avg = 0
        valid_questions = 0
        
        for question in rating_questions:
            question_answers = FeedbackAnswer.objects.filter(
                question=question,
                **response_filter,
                rating_answer__isnull=False
            )
            
            if question_answers.exists():
                total_score = sum(answer.rating_answer for answer in question_answers)
                count = question_answers.count()
                avg_rating = round(total_score / count, 2) if count > 0 else 0
                avg_row.append(avg_rating)
                total_avg += avg_rating
                valid_questions += 1
            else:
                avg_row.append(0)
        
        overall_avg = round(total_avg / valid_questions, 2) if valid_questions > 0 else 0
        avg_row.append(overall_avg)
        
        # Write average row (shifted 1 column to the right, starting at col 2)
        for col, value in enumerate(avg_row, 2):
            cell = ws2.cell(row=current_row, column=col, value=value)
            cell.font = Font(bold=True)
            cell.border = thin_border
            cell.alignment = center_alignment
        current_row += 1
        
    else:
        # No rating questions message (shifted 1 column to the right)
        ws2.cell(row=current_row, column=2, value="No rating questions found in this form.")
        current_row += 1
    
    # Auto-fit columns B onwards — skip top-left cells of multi-column merges
    # so long merged text (e.g. Max Possible Score) does not inflate column E/H.
    multi_col_merge_origins = set()
    for mr in ws2.merged_cells.ranges:
        if mr.max_col > mr.min_col:   # spans more than 1 column
            multi_col_merge_origins.add((mr.min_row, mr.min_col))

    ws2.column_dimensions['A'].width = 16
    for col in range(2, len(rating_questions) + 4):
        max_len = 0
        for row in range(1, current_row):
            if (row, col) in multi_col_merge_origins:
                continue   # skip: text spreads across multiple columns
            val = ws2.cell(row=row, column=col).value
            if val is not None:
                max_len = max(max_len, len(str(val)))
        ws2.column_dimensions[get_column_letter(col)].width = max(6, min(max_len + 2, 25))

    # Set print area for ws2
    num_cols_ws2 = max(6, len(rating_questions) + 3)

    # Add signature of faculty
    current_row += 3
    ws2.merge_cells(start_row=current_row, start_column=num_cols_ws2 - 2, end_row=current_row, end_column=num_cols_ws2)
    sig_line = ws2.cell(row=current_row, column=num_cols_ws2 - 2, value="_________________________")
    sig_line.font = Font(bold=True)
    sig_line.alignment = Alignment(horizontal="center", vertical="center")
    
    ws2.merge_cells(start_row=current_row + 1, start_column=num_cols_ws2 - 2, end_row=current_row + 1, end_column=num_cols_ws2)
    lbl_sig = ws2.cell(row=current_row + 1, column=num_cols_ws2 - 2, value="Signature of Faculty")
    lbl_sig.font = Font(bold=True)
    lbl_sig.alignment = Alignment(horizontal="center", vertical="center")
    
    ws2.merge_cells(start_row=current_row + 2, start_column=num_cols_ws2 - 2, end_row=current_row + 2, end_column=num_cols_ws2)
    lbl_name = ws2.cell(row=current_row + 2, column=num_cols_ws2 - 2, value=f"({feedback_form.professor.user.get_full_name()})")
    lbl_name.font = Font(bold=True)
    lbl_name.alignment = Alignment(horizontal="center", vertical="center")
    current_row += 3

    ws2.print_area = f"B1:{get_column_letter(num_cols_ws2)}{current_row - 1}"
    
    # SHEET 3: Individual Question Rating Charts
    if rating_questions.exists():
        ws3 = wb.create_sheet(title="Question Rating Charts")
        current_row = 1

        ws3.sheet_view.zoomScale = 105
        ws3.freeze_panes = "A4"
        ws3.page_setup.fitToPage = True
        ws3.page_setup.fitToWidth = 1
        ws3.page_setup.fitToHeight = 0
        ws3.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        ws3.print_title_rows = "$1:$3"

        for column, width in {"A": 18, "B": 14, "C": 14, "D": 4, "E": 16, "F": 16, "G": 16, "H": 16}.items():
            ws3.column_dimensions[column].width = width
        
        # Title for charts sheet
        ws3.merge_cells(f'A{current_row}:G{current_row}')
        title_cell = ws3.cell(row=current_row, column=1, value="Individual Question Rating Distribution")
        title_cell.font = title_font
        title_cell.fill = title_fill
        title_cell.alignment = center_alignment
        current_row += 3
        
        # Create individual pie charts for each question
        chart_row = current_row
        chart_block_height = 15
        questions_per_page = 3
        
        for i, question in enumerate(rating_questions):
            # Give each question its own vertical block to avoid chart overlap.
            data_start_row = chart_row + (i * chart_block_height)
            data_col = 1

            # Start each new 3-question group on a fresh printed page.
            if i > 0 and i % questions_per_page == 0:
                ws3.row_breaks.append(Break(id=data_start_row - 1))
            
            # Question title
            question_title = f"Q{question.order}: {question.question_text[:40]}..."
            ws3.merge_cells(f'A{data_start_row}:G{data_start_row}')
            title_cell = ws3.cell(row=data_start_row, column=data_col, value=question_title)
            title_cell.font = Font(bold=True, size=14, color="FFFFFF")
            title_cell.fill = title_fill
            title_cell.alignment = center_alignment
            
            # Data table headers
            data_start_row += 2
            for col, text in enumerate(["Rating", "Students", "Percentage"], 1):
                cell = ws3.cell(row=data_start_row, column=col, value=text)
                cell.font = Font(bold=True, size=12, color="FFFFFF")
                cell.fill = header_fill
                cell.alignment = center_alignment
                cell.border = thin_border
            
            # Get total responses for this question
            question_total = 0
            question_data = {}
            for rating in range(1, 6):
                count = rating_data[rating].get(question.id, 0)
                question_data[rating] = count
                question_total += count
            
            # Data rows with ratings, counts, and percentages
            data_rows_start = data_start_row + 1
            for rating in range(1, 6):
                count = question_data[rating]
                percentage = round((count / question_total * 100), 1) if question_total > 0 else 0
                
                row = data_rows_start + rating - 1
                ws3.cell(row=row, column=1, value=f"Rating {rating}")
                ws3.cell(row=row, column=2, value=count)
                ws3.cell(row=row, column=3, value=f"{percentage}%")
                for col in range(1, 4):
                    data_cell = ws3.cell(row=row, column=col)
                    data_cell.font = Font(size=12)
                    data_cell.border = thin_border
                    data_cell.alignment = center_alignment
            
            # Add total row
            total_row = data_rows_start + 5
            ws3.cell(row=total_row, column=1, value="Total").font = Font(bold=True, size=12, color="FFFFFF")
            ws3.cell(row=total_row, column=2, value=question_total).font = Font(bold=True, size=12, color="FFFFFF")
            ws3.cell(row=total_row, column=3, value="100.0%").font = Font(bold=True, size=12, color="FFFFFF")
            for col in range(1, 4):
                total_cell = ws3.cell(row=total_row, column=col)
                total_cell.fill = stats_fill
                total_cell.border = thin_border
                total_cell.alignment = center_alignment
            
            # Create pie chart for this question
            question_pie_chart = PieChart()
            question_pie_chart.title = f"Q{question.order} Rating Distribution"
            
            # Define data ranges for this question (only include ratings with responses)
            labels = Reference(ws3, min_col=data_col, min_row=data_rows_start, max_row=data_rows_start + 4)
            data = Reference(ws3, min_col=data_col + 1, min_row=data_rows_start - 1, max_row=data_rows_start + 4)
            
            question_pie_chart.add_data(data, titles_from_data=True)
            question_pie_chart.set_categories(labels)
            question_pie_chart.height = 5.5
            question_pie_chart.width = 7.75
            
            # Position chart beside the table and total row.
            chart_cell = f"E{data_start_row}"
            ws3.add_chart(question_pie_chart, chart_cell)


        # Calculate next available row for summary section
        num_chart_rows = len(rating_questions) * chart_block_height
        summary_start_row = chart_row + num_chart_rows + 5
        ws3.row_breaks.append(Break(id=summary_start_row - 1))
        
        # Overall Summary Section
        ws3.merge_cells(f'A{summary_start_row}:G{summary_start_row}')
        summary_title = ws3.cell(row=summary_start_row, column=1, value="Overall Rating Summary")
        summary_title.font = title_font
        summary_title.fill = title_fill
        summary_title.alignment = center_alignment
        summary_start_row += 3
        
        # Overall statistics table
        for col, text in enumerate(["Rating", "Total Students", "Across All Questions", "Percentage"], 1):
            cell = ws3.cell(row=summary_start_row, column=col, value=text)
            cell.font = Font(bold=True, size=12, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = center_alignment
            cell.border = thin_border
        
        # Calculate overall statistics
        overall_total = 0
        overall_ratings = {}
        for rating in range(1, 6):
            total_for_rating = 0
            for question in rating_questions:
                total_for_rating += rating_data[rating].get(question.id, 0)
            overall_ratings[rating] = total_for_rating
            overall_total += total_for_rating
        
        # Write overall statistics
        for rating in range(1, 6):
            count = overall_ratings[rating]
            percentage = round((count / overall_total * 100), 1) if overall_total > 0 else 0
            
            row = summary_start_row + rating
            ws3.cell(row=row, column=1, value=f"Rating {rating}")
            ws3.cell(row=row, column=2, value=count)
            ws3.cell(row=row, column=3, value=f"Out of {overall_total} total responses")
            ws3.cell(row=row, column=4, value=f"{percentage}%")
            for col in range(1, 5):
                data_cell = ws3.cell(row=row, column=col)
                data_cell.font = Font(size=12)
                data_cell.border = thin_border
                data_cell.alignment = center_alignment
        
        # Add overall total
        total_row = summary_start_row + 6
        ws3.cell(row=total_row, column=1, value="Total").font = Font(bold=True, size=12, color="FFFFFF")
        ws3.cell(row=total_row, column=2, value=overall_total).font = Font(bold=True, size=12, color="FFFFFF")
        ws3.cell(row=total_row, column=3, value=f"{len(rating_questions)} questions × {total_responses} responses").font = Font(bold=True, size=12, color="FFFFFF")
        ws3.cell(row=total_row, column=4, value="100.0%").font = Font(bold=True, size=12, color="FFFFFF")
        for col in range(1, 5):
            total_cell = ws3.cell(row=total_row, column=col)
            total_cell.fill = stats_fill
            total_cell.border = thin_border
            total_cell.alignment = center_alignment

        # Auto-fit Overall Rating Summary table columns based on content.
        for col in range(1, 5):
            max_length = 0
            for row in range(summary_start_row, total_row + 1):
                cell_value = ws3.cell(row=row, column=col).value
                if cell_value is not None:
                    max_length = max(max_length, len(str(cell_value)))
            ws3.column_dimensions[get_column_letter(col)].width = max(12, min(max_length + 2, 42))
        
        # Create overall pie chart
        overall_pie_chart = PieChart()
        overall_pie_chart.title = "Overall Rating Distribution (All Questions)"
        
        # Data for overall chart
        overall_labels = Reference(ws3, min_col=1, min_row=summary_start_row + 1, max_row=summary_start_row + 5)
        overall_data = Reference(ws3, min_col=2, min_row=summary_start_row, max_row=summary_start_row + 5)
        
        overall_pie_chart.add_data(overall_data, titles_from_data=True)
        overall_pie_chart.set_categories(overall_labels)
        overall_pie_chart.height = 7.5
        overall_pie_chart.width = 15.75
        
        # Add overall chart below the summary table (total_row is summary_start_row + 6)
        ws3.add_chart(overall_pie_chart, f"B{summary_start_row+11}")

        # Add signature of faculty below the overall chart
        # Chart starts at summary_start_row+8, height=12cm (~19 rows), so signature at +30
        ws3_sig_row = summary_start_row + 30
        ws3.merge_cells(start_row=ws3_sig_row, start_column=5, end_row=ws3_sig_row, end_column=7)
        sig_line = ws3.cell(row=ws3_sig_row, column=5, value="_________________________")
        sig_line.font = Font(bold=True)
        sig_line.alignment = Alignment(horizontal="center", vertical="center")
        
        ws3.merge_cells(start_row=ws3_sig_row + 1, start_column=5, end_row=ws3_sig_row + 1, end_column=7)
        lbl_sig = ws3.cell(row=ws3_sig_row + 1, column=5, value="Signature of Faculty")
        lbl_sig.font = Font(bold=True)
        lbl_sig.alignment = Alignment(horizontal="center", vertical="center")
        
        ws3.merge_cells(start_row=ws3_sig_row + 2, start_column=5, end_row=ws3_sig_row + 2, end_column=7)
        lbl_name = ws3.cell(row=ws3_sig_row + 2, column=5, value=f"({feedback_form.professor.user.get_full_name()})")
        lbl_name.font = Font(bold=True)
        lbl_name.alignment = Alignment(horizontal="center", vertical="center")

        # Restrict print area to column G
        ws3.print_area = f"A1:G{ws3_sig_row + 2}"

    # Ensure the response sheets print in landscape while the rating summary and chart sheets print in portrait.
    for worksheet in wb.worksheets:
        if worksheet.title == "Question Rating Charts":
            apply_print_layout(
                worksheet,
                worksheet.ORIENTATION_PORTRAIT,
                {
                    "left": 0.18,
                    "right": 0.18,
                    "top": 0.35,
                    "bottom": 0.35,
                    "header": 0.2,
                    "footer": 0.2,
                },
            )
        elif worksheet.title == "Rating Summary":
            apply_print_layout(worksheet, worksheet.ORIENTATION_PORTRAIT)
        else:
            apply_print_layout(worksheet)
    
    # Create response
    #wb.move_sheet("Rating Summary", offset=-wb.sheetnames.index("Rating Summary"))
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    filename = f"feedback_responses_{feedback_form.id}_{feedback_form.title[:20]}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    if archive:
        _archive_export_file(
            request.user,
            f"Form Export: {feedback_form.title}",
            filename,
            output.getvalue(),
        )
    
    return response


@login_required
@user_passes_test(is_admin)
def export_all_responses(request):
    """Export all feedback responses organized by division and subject type in a zip file"""
    import zipfile
    import tempfile
    import os
    from collections import defaultdict
    
    if not request.user.is_staff:
        messages.error(request, "You don't have permission to export responses.")
        return redirect('dashboard')
    
    # Get all forms with responses
    forms_with_responses = FeedbackForm.objects.filter(
        responses__isnull=False
    ).distinct().select_related(
        'subject', 'professor__user', 'practical_batch'
    ).prefetch_related('responses')
    
    if not forms_with_responses.exists():
        messages.warning(request, "No feedback responses found to export.")
        return redirect('manage_feedback_forms')
    
    # Create a temporary directory for the zip file
    temp_dir = tempfile.mkdtemp()
    zip_filename = os.path.join(temp_dir, 'all_feedback_responses.zip')
    
    try:
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Group forms by subject category and feedback round.
            organized_forms = defaultdict(lambda: defaultdict(list))
            
            for form in forms_with_responses:
                subject_category = 'Theory' if form.subject.subject_type == 'theory' else 'Practical'
                rounds = set(form.responses.values_list('feedback_round', flat=True))
                for feedback_round in rounds:
                    organized_forms[subject_category][feedback_round].append(form)
            
            # Process each category and round. Division remains below the requested folders.
            for subject_category, rounds in organized_forms.items():
                for feedback_round, forms in rounds.items():
                    folder_path = f"{subject_category}/Feedback {feedback_round}"
                    
                    for form in forms:
                        # Create a mock request for export_responses
                        class MockRequest:
                            def __init__(self, user):
                                self.user = user
                        
                        mock_request = MockRequest(request.user)
                        
                        # Call the existing export_responses function
                        excel_response = export_responses(
                            mock_request,
                            form.id,
                            archive=False,
                            feedback_round=feedback_round,
                        )
                        
                        # Extract Excel content from the response
                        excel_content = excel_response.content
                        
                        # Create safe filename
                        safe_subject_name = "".join(c for c in form.subject.name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                        safe_professor_name = "".join(c for c in form.professor.user.get_full_name() if c.isalnum() or c in (' ', '-', '_')).rstrip()
                        
                        if form.practical_batch:
                            filename = f"{safe_subject_name}_{safe_professor_name}_{form.subject.get_subject_type_display()}_{form.practical_batch.name}.xlsx"
                        else:
                            filename = f"{safe_subject_name}_{safe_professor_name}_{form.subject.get_subject_type_display()}.xlsx"
                        file_path = f"{folder_path}/{form.division}/{filename}"
                        
                        # Add to zip
                        zipf.writestr(file_path, excel_content)

            # Always include the combined report; missing round-two values remain blank.
            final_request = MockRequest(request.user)
            final_excel_response = export_final_feedback(final_request)
            if final_excel_response.status_code == 200:
                zipf.writestr(
                    'Final Feedback/kjsit_feedback_final_four_years.xlsx',
                    final_excel_response.content,
                )
        
        # Read the zip file and create response
        with open(zip_filename, 'rb') as f:
            zip_content = f.read()

        _archive_export_file(
            request.user,
            "All Responses Export",
            "all_feedback_responses.zip",
            zip_content,
        )
        
        response = HttpResponse(zip_content, content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="all_feedback_responses.zip"'
        
        return response
        
    except Exception as e:
        messages.error(request, f"Error creating export file: {str(e)}")
        return redirect('manage_feedback_forms')
    
    finally:
        # Clean up temporary files
        try:
            if os.path.exists(zip_filename):
                os.remove(zip_filename)
            os.rmdir(temp_dir)
        except:
            pass


@login_required
@user_passes_test(is_admin)
def export_final_feedback(request):
    """Export both feedback rounds as one workbook with a sheet for each academic year."""
    if not request.user.is_staff:
        messages.error(request, "You don't have permission to export responses.")
        return redirect('dashboard')

    forms = FeedbackForm.objects.filter(
        responses__isnull=False
    ).distinct().select_related(
        'subject', 'professor__user', 'division'
    ).prefetch_related('responses__answers')

    grouped = defaultdict(lambda: {
        'subject': '',
        'professor': '',
        'sub_id': '',
        'divisions': defaultdict(dict),
    })
    for feedback_form in forms:
        group_key = (
            feedback_form.division.year,
            feedback_form.subject.code,
            feedback_form.professor_id,
        )
        group = grouped[group_key]
        group['subject'] = feedback_form.subject.name
        group['professor'] = feedback_form.professor.user.get_full_name()
        group['sub_id'] = feedback_form.subject.code

        round_scores = {1: [], 2: []}
        for response in feedback_form.responses.all():
            ratings = [
                answer.rating_answer
                for answer in response.answers.all()
                if answer.rating_answer is not None
            ]
            if ratings:
                round_scores[response.feedback_round].append(sum(ratings) / len(ratings))

        division_scores = group['divisions'][feedback_form.division.name]
        for feedback_round, scores in round_scores.items():
            if scores:
                division_scores[feedback_round] = sum(scores) / len(scores)

    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.calculation.calcMode = 'auto'
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    header_fill = PatternFill(start_color='A50C22', end_color='A50C22', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    border = Border(
        left=Side(style='thin', color='BFBFBF'),
        right=Side(style='thin', color='BFBFBF'),
        top=Side(style='thin', color='BFBFBF'),
        bottom=Side(style='thin', color='BFBFBF'),
    )
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    logo_path = settings.BASE_DIR / 'appfeedback' / 'static' / 'appfeedback' / 'images' / 'somaiya.png'

    for year, year_name in Division.YEAR_CHOICES:
        worksheet = workbook.create_sheet(title=year_name)
        worksheet.merge_cells('B1:N1')
        worksheet['B1'] = 'K J Somaiya Institute of Technology'
        worksheet['B1'].font = Font(bold=True, size=16, color='A50C22')
        worksheet['B1'].alignment = center
        worksheet.merge_cells('B2:N2')
        worksheet['B2'] = f'Department: {settings.BRANCH}'
        worksheet['B2'].font = Font(italic=True, size=11, color='555555')
        worksheet['B2'].alignment = center
        worksheet['B3'] = 'Highlight above (%)'
        worksheet['B3'].font = Font(bold=True, color='A50C22')
        worksheet['B3'].alignment = center
        worksheet['C3'] = 80
        worksheet['C3'].number_format = '0'
        worksheet['C3'].font = Font(bold=True, color='A50C22')
        worksheet['C3'].alignment = center
        worksheet['C3'].border = border
        threshold_validation = DataValidation(
            type='decimal',
            operator='between',
            formula1='0',
            formula2='100',
            allow_blank=False,
        )
        threshold_validation.error = 'Enter a percentage from 0 to 100.'
        threshold_validation.errorTitle = 'Invalid threshold'
        threshold_validation.prompt = 'Change this value to update highlighted faculty names.'
        threshold_validation.promptTitle = 'Interactive highlight threshold'
        worksheet.add_data_validation(threshold_validation)
        threshold_validation.add(worksheet['C3'])
        worksheet.merge_cells('D3:N3')
        worksheet['D3'] = 'Change the threshold in C3 to update the highlighted names.'
        worksheet['D3'].font = Font(italic=True, color='666666')
        worksheet['D3'].alignment = Alignment(horizontal='left', vertical='center')
        if logo_path.exists():
            logo = XLImage(str(logo_path))
            logo.width = 64
            logo.height = 64
            worksheet.add_image(logo, 'A1')

        base_headers = ['SR.NO.', 'SUBJECT', 'FACULTY NAME', 'SubID']
        for column, value in enumerate(base_headers, 1):
            cell = worksheet.cell(row=4, column=column, value=value)
            worksheet.merge_cells(start_row=4, start_column=column, end_row=5, end_column=column)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center
            cell.border = border

        grouped_headers = [
            (5, 8, 'ADiv'),
            (9, 12, 'BDiv'),
            (13, 14, 'Average (available scores)'),
        ]
        for start_column, end_column, value in grouped_headers:
            worksheet.merge_cells(start_row=4, start_column=start_column, end_row=4, end_column=end_column)
            cell = worksheet.cell(row=4, column=start_column, value=value)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center
            for column in range(start_column, end_column + 1):
                worksheet.cell(row=4, column=column).fill = header_fill
                worksheet.cell(row=4, column=column).border = border

        detail_headers = [
            'F1 SCORE', 'F2 SCORE', 'F1 %', 'F2 %',
            'F1 SCORE', 'F2 SCORE', 'F1 %', 'F2 %',
            'SCORE', 'PERCENTAGE',
        ]
        for column, value in enumerate(detail_headers, 5):
            cell = worksheet.cell(row=5, column=column, value=value)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center
            cell.border = border

        row = 6
        serial_number = 1
        year_groups = [
            group for (group_year, _, _), group in sorted(grouped.items())
            if group_year == year
        ]
        for group in year_groups:
            division_values = {}
            for division_name, scores in group['divisions'].items():
                division_values[division_name] = {
                    1: scores.get(1),
                    2: scores.get(2),
                }

            a_scores = division_values.get('A', {})
            b_scores = division_values.get('B', {})
            available_scores = [
                score for division_scores in division_values.values()
                for score in division_scores.values() if score is not None
            ]
            average_score = sum(available_scores) / len(available_scores) if available_scores else None

            def score_percentage(score):
                return score / 5 if score is not None else ''

            values = [
                serial_number,
                group['subject'],
                group['professor'],
                group['sub_id'],
                round(a_scores.get(1), 2) if a_scores.get(1) is not None else '',
                round(a_scores.get(2), 2) if a_scores.get(2) is not None else '',
                score_percentage(a_scores.get(1)),
                score_percentage(a_scores.get(2)),
                round(b_scores.get(1), 2) if b_scores.get(1) is not None else '',
                round(b_scores.get(2), 2) if b_scores.get(2) is not None else '',
                score_percentage(b_scores.get(1)),
                score_percentage(b_scores.get(2)),
                round(average_score, 2) if average_score is not None else '',
                score_percentage(average_score),
            ]
            for column, value in enumerate(values, 1):
                cell = worksheet.cell(row=row, column=column, value=value)
                cell.alignment = center
                cell.border = border
                if column in (7, 8, 11, 12, 14):
                    cell.number_format = '0.00%'
            serial_number += 1
            row += 1

        data_end_row = row - 1
        highlight_fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')
        if data_end_row >= 6:
            worksheet.conditional_formatting.add(
                f'C6:C{data_end_row}',
                FormulaRule(formula=['$N6*100>$C$3'], fill=highlight_fill)
            )

        row += 2
        worksheet.merge_cells(start_row=row, start_column=8, end_row=row, end_column=10)
        worksheet.cell(row=row, column=8, value='Signed by: ____________________').alignment = center
        worksheet.cell(row=row, column=8).font = Font(bold=True)
        worksheet.freeze_panes = 'A6'
        worksheet.row_dimensions[1].height = 48
        worksheet.row_dimensions[4].height = 30
        worksheet.row_dimensions[5].height = 30
        widths = [9, 28, 24, 14, 12, 12, 12, 12, 12, 12, 12, 12, 18, 18]
        for column, width in enumerate(widths, 1):
            worksheet.column_dimensions[get_column_letter(column)].width = width
        worksheet.page_setup.orientation = worksheet.ORIENTATION_LANDSCAPE
        worksheet.page_setup.fitToWidth = 1
        worksheet.sheet_properties.pageSetUpPr.fitToPage = True
        worksheet.print_area = f'A1:N{row}'

    output = BytesIO()
    workbook.save(output)
    content = output.getvalue()
    filename = 'kjsit_feedback_final_four_years.xlsx'
    _archive_export_file(request.user, 'Final Feedback 1 and 2 Report', filename, content)
    response = HttpResponse(
        content,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@user_passes_test(is_admin)
def send_faculty_mails_view(request):
    """Send feedback reports to respective faculty members using user SMTP setup"""
    if request.method != 'POST':
        return redirect('manage_feedback_forms')
        
    gmail_address = request.POST.get('gmail_address', '').strip()
    app_password = request.POST.get('app_password', '').strip()
    
    if not gmail_address or not app_password:
        messages.error(request, "Gmail address and App Password are required.")
        return redirect('manage_feedback_forms')
        
    # Save/remember this setup per user
    UserMailSetup.objects.update_or_create(
        user=request.user,
        defaults={
            'gmail_address': gmail_address,
            'app_password': app_password
        }
    )
    
    # Get all forms with responses
    forms_with_responses = FeedbackForm.objects.filter(
        responses__isnull=False
    ).distinct().select_related(
        'subject', 'professor__user', 'practical_batch', 'division'
    )
    
    if not forms_with_responses.exists():
        messages.warning(request, "No feedback responses found to mail.")
        return redirect('manage_feedback_forms')
        
    # Group forms by professor
    from collections import defaultdict
    professor_forms = defaultdict(list)
    for form in forms_with_responses:
        professor_forms[form.professor].append(form)
        
    # Remove spaces from Gmail app passwords
    clean_password = app_password.replace(' ', '')
    
    # Set up dynamic SMTP connection
    from django.core.mail import get_connection, EmailMessage
    
    try:
        connection = get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host='smtp.gmail.com',
            port=587,
            username=gmail_address,
            password=clean_password,
            use_tls=True,
        )
        connection.open()
    except Exception as e:
        messages.error(request, f"Failed to connect to SMTP server: {str(e)}. Please check your credentials and App Password.")
        return redirect('manage_feedback_forms')
        
    success_count = 0
    fail_count = 0
    error_details = []
    
    class MockRequest:
        def __init__(self, user):
            self.user = user
    mock_request = MockRequest(request.user)
    
    for professor, forms in professor_forms.items():
        professor_email = professor.user.email
        if not professor_email:
            fail_count += 1
            error_details.append(f"{professor.user.get_full_name()} (missing email)")
            continue
            
        try:
            current_year = timezone.now().year
            subjects_info = []
            for form in forms:
                batch_str = f", Batch: {form.practical_batch.name}" if form.practical_batch else ""
                subjects_info.append(
                    f"- {form.subject.code} - {form.subject.name} ({form.subject.get_subject_type_display()}, Division: {form.division}{batch_str})"
                )
            subjects_list_str = "\n".join(subjects_info)

            body_text = (
                f"Dear Professor {professor.user.get_full_name()},\n\n"
                f"We are pleased to share the student feedback reports for your courses. Please find the detailed Excel reports attached to this email.\n\n"
                f"Summary of Attached Reports:\n"
                f"----------------------------\n"
                f"Academic Year: {current_year}\n"
                f"Subject List:\n"
                f"{subjects_list_str}\n\n"
                f"Important Instructions:\n"
                f"- These reports are pre-configured with print layouts, print areas, and signature blocks.\n"
                f"- For the best formatting and print results, please open the files using Microsoft Excel and print/export them directly.\n\n"
                f"Please review the attached sheets for detailed statistics, student responses, and average ratings.\n\n"
                f"If you have any questions or require further assistance, please contact the administrator.\n\n"
                f"Best regards,\n"
                f"KJSIT Feedback System"
            )

            email = EmailMessage(
                subject="Student Feedback Reports - KJSIT Feedback System",
                body=body_text,
                from_email=gmail_address,
                to=[professor_email],
                connection=connection
            )
            
            for form in forms:
                excel_response = export_responses(mock_request, form.id, archive=False)
                excel_content = excel_response.content
                
                safe_subject_name = "".join(c for c in form.subject.name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                safe_professor_name = "".join(c for c in form.professor.user.get_full_name() if c.isalnum() or c in (' ', '-', '_')).rstrip()
                if form.practical_batch:
                    filename = f"{safe_subject_name}_{safe_professor_name}_{form.subject.get_subject_type_display()}_{form.practical_batch.name}.xlsx"
                else:
                    filename = f"{safe_subject_name}_{safe_professor_name}_{form.subject.get_subject_type_display()}.xlsx"
                    
                email.attach(filename, excel_content, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                
            email.send()
            success_count += 1
        except Exception as e:
            fail_count += 1
            error_details.append(f"{professor.user.get_full_name()} ({str(e)})")
            
    try:
        connection.close()
    except:
        pass
        
    if success_count > 0:
        messages.success(request, f"Successfully sent feedback reports to {success_count} professors.")
    if fail_count > 0:
        messages.error(request, f"Failed to send to {fail_count} professors: {', '.join(error_details)}")
        
    return redirect('manage_feedback_forms')


@login_required
@user_passes_test(is_admin)
def clear_data_view(request):
    """Export all responses and then clear all student data"""
    import zipfile
    import tempfile
    import os
    from collections import defaultdict
    
    if request.method == 'POST':
        try:
            # Get all forms with responses for export
            forms_with_responses = FeedbackForm.objects.filter(
                responses__isnull=False
            ).distinct().select_related(
                'subject', 'professor__user', 'practical_batch'
            ).prefetch_related('responses')
            
            # Create temporary directory and zip file
            temp_dir = tempfile.mkdtemp()
            zip_filename = os.path.join(temp_dir, 'all_feedback_responses.zip')
            
            # Export all responses to zip
            if forms_with_responses.exists():
                with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    organized_forms = defaultdict(lambda: defaultdict(list))
                    
                    for form in forms_with_responses:
                        division = form.division
                        subject_type = form.subject.subject_type
                        organized_forms[division][subject_type].append(form)
                    
                    for division, subject_types in organized_forms.items():
                        for subject_type, forms in subject_types.items():
                            folder_path = f"{division}/{subject_type.title()}"
                            
                            for form in forms:
                                class MockRequest:
                                    def __init__(self, user):
                                        self.user = user
                                
                                mock_request = MockRequest(request.user)
                                excel_response = export_responses(mock_request, form.id, archive=False)
                                excel_content = excel_response.content
                                
                                safe_subject_name = "".join(c for c in form.subject.name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                                safe_professor_name = "".join(c for c in form.professor.user.get_full_name() if c.isalnum() or c in (' ', '-', '_')).rstrip()
                                
                                if form.practical_batch:
                                    filename = f"{safe_subject_name}_{safe_professor_name}_{form.subject.get_subject_type_display()}_{form.practical_batch.name}.xlsx"
                                else:
                                    filename = f"{safe_subject_name}_{safe_professor_name}_{form.subject.get_subject_type_display()}.xlsx"
                                
                                file_path = f"{folder_path}/{filename}"
                                
                                zipf.writestr(file_path, excel_content)
                
                # Read the zip file
                with open(zip_filename, 'rb') as f:
                    zip_content = f.read()

                _archive_export_file(
                    request.user,
                    "Backup Before Clear Data",
                    "all_feedback_responses_before_clear_data.zip",
                    zip_content,
                )
            else:
                zip_content = None
            
            # Delete all data
            with transaction.atomic():
                # Get count of deleted items for message
                student_count = Student.objects.count()
                subject_count = Subject.objects.count()
                practical_assignment_count = PracticalAssignment.objects.count()
                theory_assignment_count = TeacherAssignment.objects.count()
                
                # Collect user IDs for students and professors to delete explicitly
                student_user_ids = list(Student.objects.values_list('user_id', flat=True))
                professor_user_ids = list(Professor.objects.values_list('user_id', flat=True))
                
                # Delete students (cascade will delete associated Users, but we'll be explicit)
                Student.objects.all().delete()
                
                # Delete professors
                Professor.objects.all().delete()
                
                # Explicitly delete user accounts for students and professors
                if student_user_ids:
                    User.objects.filter(id__in=student_user_ids).delete()
                if professor_user_ids:
                    User.objects.filter(id__in=professor_user_ids).delete()
                
                # Delete subjects
                Subject.objects.all().delete()
                
                # Delete practical assignments 
                PracticalAssignment.objects.all().delete()
                
                # Delete theory assignments
                TeacherAssignment.objects.all().delete()
                
                messages.success(
                    request, 
                    f'Data cleared successfully! Exported responses first. '
                    f'Deleted {student_count} students, {subject_count} subjects, '
                    f'{practical_assignment_count} practical assignments, '
                    f'{theory_assignment_count} theory assignments.'
                )
            
            # Return zip file if there were responses to export
            if zip_content:
                response = HttpResponse(zip_content, content_type='application/zip')
                response['Content-Disposition'] = 'attachment; filename="all_feedback_responses.zip"'
                return response
            else:
                messages.warning(request, "No responses to export. Data was cleared.")
                return redirect('admin_dashboard')
        
        except Exception as e:
            messages.error(request, f"Error during data clearing: {str(e)}")
            return redirect('admin_dashboard')
        
        finally:
            # Clean up temporary files
            try:
                if 'temp_dir' in locals() and os.path.exists(temp_dir):
                    import shutil
                    shutil.rmtree(temp_dir)
            except:
                pass
    
    else:
        # GET request - show confirmation page
        student_count = Student.objects.count()
        subject_count = Subject.objects.count()
        practical_assignment_count = PracticalAssignment.objects.count()
        theory_assignment_count = TeacherAssignment.objects.count()
        response_count = FeedbackResponse.objects.count()
        
        context = {
            'student_count': student_count,
            'subject_count': subject_count,
            'practical_assignment_count': practical_assignment_count,
            'theory_assignment_count': theory_assignment_count,
            'response_count': response_count,
        }
        return render(request, 'confirm_clear_data.html', context)


@login_required
@user_passes_test(is_admin)
def delete_feedback_form_view(request, form_id):
    """Delete a feedback form"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    
    if request.method == 'POST':
        form_title = feedback_form.title
        feedback_form.delete()
        messages.success(request, f'Feedback form "{form_title}" has been deleted successfully.')
        return redirect('manage_feedback_forms')
    
    # For GET request, show confirmation
    context = {
        'form': feedback_form,
        'response_count': feedback_form.responses.count(),
    }
    return render(request, 'confirm_delete_form.html', context)


@login_required
@user_passes_test(is_admin)
def test_messages_view(request):
    """Test view to verify message system is working"""
    messages.success(request, "This is a success message!")
    messages.error(request, "This is an error message!")
    messages.warning(request, "This is a warning message!")
    messages.info(request, "This is an info message!")
    
    return redirect('admin_dashboard')


@login_required
@user_passes_test(is_admin)
def bulk_generate_feedback_forms(request):
    """Generate feedback forms for all assignments automatically"""
    if request.method == 'POST':
        form_title_prefix = request.POST.get('form_title_prefix', '')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        
        if not start_date or not end_date:
            messages.error(request, "Please provide both start and end dates.")
            return redirect('admin_dashboard')
        
        try:
            from datetime import datetime
            start_date = datetime.fromisoformat(start_date.replace('T', ' '))
            end_date = datetime.fromisoformat(end_date.replace('T', ' '))
            
            if start_date >= end_date:
                messages.error(request, "End date must be after start date.")
                return redirect('admin_dashboard')
            
            created_count = 0
            skipped_count = 0
            errors = []
            
            with transaction.atomic():
                # Generate forms for theory subjects (TeacherAssignments)
                theory_assignments = TeacherAssignment.objects.select_related(
                    'professor', 'subject', 'division'
                ).filter(subject__subject_type='theory')
                
                for assignment in theory_assignments:
                    try:
                        # Check if form already exists
                        existing_form = FeedbackForm.objects.filter(
                            subject=assignment.subject,
                            professor=assignment.professor,
                            division=assignment.division,
                            practical_batch__isnull=True
                        ).first()
                        
                        if existing_form:
                            skipped_count += 1
                            continue
                        
                        # Create form title
                        form_title = f"{form_title_prefix} {assignment.subject.name} - {assignment.professor.user.get_full_name()} - {assignment.division}"
                        
                        # Create feedback form
                        feedback_form = FeedbackForm.objects.create(
                            title=form_title,
                            #description=f"Automated feedback form for {assignment.subject.name} (Theory)",
                            subject=assignment.subject,
                            professor=assignment.professor,
                            division=assignment.division,
                            practical_batch=None,
                            start_date=start_date,
                            end_date=end_date,
                            is_active=True,
                            allow_anonymous=True,
                            created_by=request.user
                        )
                        
                        # Create default questions
                        _create_default_questions(feedback_form)
                        created_count += 1
                        
                    except Exception as e:
                        errors.append(f"Theory - {assignment.subject.code} - {assignment.professor.employee_id}: {str(e)}")
                
                # Generate forms for practical/tutorial subjects (PracticalAssignments)
                practical_assignments = PracticalAssignment.objects.select_related(
                    'professor', 'subject', 'batch__division'
                ).filter(subject__subject_type__in=['practical', 'tutorials'])
                
                for assignment in practical_assignments:
                    try:
                        # Check if form already exists
                        existing_form = FeedbackForm.objects.filter(
                            subject=assignment.subject,
                            professor=assignment.professor,
                            division=assignment.batch.division,
                            practical_batch=assignment.batch
                        ).first()
                        
                        if existing_form:
                            skipped_count += 1
                            continue
                        
                        # Create form title
                        form_title = f"{form_title_prefix} {assignment.subject.name} - {assignment.professor.user.get_full_name()} - {assignment.batch}"
                        
                        # Create feedback form
                        feedback_form = FeedbackForm.objects.create(
                            title=form_title,
                            #description=f"Automated feedback form for {assignment.subject.name} ({assignment.subject.get_subject_type_display()})",
                            subject=assignment.subject,
                            professor=assignment.professor,
                            division=assignment.batch.division,
                            practical_batch=assignment.batch,
                            start_date=start_date,
                            end_date=end_date,
                            is_active=True,
                            allow_anonymous=True,
                            created_by=request.user
                        )
                        
                        # Create default questions
                        _create_default_questions(feedback_form)
                        created_count += 1
                        
                    except Exception as e:
                        errors.append(f"Practical/Tutorial - {assignment.subject.code} - {assignment.professor.employee_id} - {assignment.batch.name}: {str(e)}")
            
            # Show results
            if created_count > 0:
                messages.success(request, f"Successfully created {created_count} feedback forms!")
            
            if skipped_count > 0:
                messages.info(request, f"Skipped {skipped_count} forms (already exist).")
            
            if errors:
                error_msg = "Errors encountered:\n" + "\n".join(errors[:5])
                if len(errors) > 5:
                    error_msg += f"\n... and {len(errors) - 5} more errors."
                messages.error(request, error_msg)
                
        except ValueError as e:
            messages.error(request, f"Invalid date format: {e}")
        except Exception as e:
            messages.error(request, f"Error generating forms: {e}")
    
    return redirect('admin_dashboard')


@login_required
@user_passes_test(is_admin)
def bulk_generate_forms_page(request):
    """Page to configure bulk form generation"""
    # Get assignment statistics
    theory_count = TeacherAssignment.objects.filter(subject__subject_type='theory').count()
    practical_count = PracticalAssignment.objects.filter(subject__subject_type__in=['practical', 'tutorials']).count()
    
    # Get existing forms count
    existing_forms = FeedbackForm.objects.count()
    
    # Get server time in Asia/Kolkata timezone
    from django.utils import timezone
    from datetime import timedelta
    
    server_now = timezone.now()
    # Default end date should be same date/time next year.
    try:
        one_year_later = server_now.replace(year=server_now.year + 1)
    except ValueError:
        # Handle leap day safely by falling back to 365 days.
        one_year_later = server_now + timedelta(days=365)
    
    context = {
        'theory_assignments_count': theory_count,
        'practical_assignments_count': practical_count,
        'total_assignments': theory_count + practical_count,
        'existing_forms_count': existing_forms,
        'server_start_time': server_now.strftime('%Y-%m-%dT%H:%M'),
        'server_end_time': one_year_later.strftime('%Y-%m-%dT%H:%M'),
    }
    
    return render(request, 'bulk_generate_forms.html', context)


@login_required
@user_passes_test(is_admin)
def import_data_view(request):
    """Main import page for professors, students, and subjects"""
    return render(request, 'import_data.html')


@login_required
@user_passes_test(is_admin)
def download_professor_template(request):
    """Download Excel template for professors"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Professors Template"
    
    # Header style
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="a50c22", end_color="a50c22", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Headers
    headers = [
        'First Name', 'Last Name', 'Employee ID', 'Department'
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
    
    # Sample data
    sample_data = [
        ['John', 'Doe', 'EMP001', 'Computer Engineering'],
        ['Jane', 'Smith', 'EMP002', 'Information Technology'],
    ]
    
    for row, data in enumerate(sample_data, 2):
        for col, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = thin_border
    
    # Adjust column widths
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 20
    
    # Create response
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=professors_template.xlsx'
    return response


@login_required
@user_passes_test(is_admin)
def download_student_template(request):
    """Download Excel template for students"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Students Template"
    
    # Header style
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="a50c22", end_color="a50c22", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Headers
    headers = [
        'First Name', 'Last Name', 'Email', 'Username', 'Roll Number', 'Division', 'Semester', 'Practical Batch', 'Department'
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
    
    # Sample data
    sample_data = [
        ['Alice', 'Johnson', 'alice.johnson@student.kjsit.edu', 'alice.johnson', 'CS2023001', 'A', '3', 'A1', 'Computer Engineering'],
        ['Bob', 'Williams', 'bob.williams@student.kjsit.edu', 'bob.williams', 'CS2023002', 'A', '3', 'A2', 'Computer Engineering'],
    ]
    
    for row, data in enumerate(sample_data, 2):
        for col, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = thin_border
    
    # Add instructions sheet
    ws2 = wb.create_sheet("Instructions")
    instructions = [
        "Instructions for Students Import:",
        "",
        "1. Division: Enter division letter (A, B, C, etc.)",
        "2. Semester: Enter semester number (1-8). Year will be auto-calculated.",
        "3. Practical Batch: Enter batch name (A1, A2, B1, etc.) - Optional",
        "4. Email: Must be unique",
        "5. Username: Must be unique",
        "6. Roll Number: Must be unique",
        "7. Department: Enter department name (e.g., Computer Engineering, Electronics, etc.)",
        "",
        "Note: Division and Practical Batch must exist in the system before importing students.",
        "Year is automatically calculated from semester (1-2=Year1, 3-4=Year2, etc.)",
        "Default department will be 'Computer Engineering' if not specified."
    ]
    
    for row, instruction in enumerate(instructions, 1):
        ws2.cell(row=row, column=1, value=instruction)
    
    # Adjust column widths
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 20
    
    # Create response
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=students_template.xlsx'
    return response


@login_required
@user_passes_test(is_admin)
def download_subject_template(request):
    """Download Excel template for subjects"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Subjects Template"
    
    # Header style
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="a50c22", end_color="a50c22", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Headers
    headers = [
        'Subject Name', 'Subject Code', 'Subject Type', 'Semester','Elective'
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
    
    # Sample data
    sample_data = [
        ['Data Structures', 'CS201', 'theory', '3'],
        ['Database Management Lab', 'CS202L', 'practical', '3'],
        ['Software Engineering', 'CS203', 'tutorials', '4'],
    ]
    
    for row, data in enumerate(sample_data, 2):
        for col, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = thin_border
    
    # Add instructions sheet
    ws2 = wb.create_sheet("Instructions")
    instructions = [
        "Instructions for Subjects Import:",
        "",
        "1. Subject Type: Must be one of: theory, practical, tutorials. Elective is allocated group number, eg 1 for all subjects in the first elective group, 2 for second elective, etc. Leave blank if not an elective.",
        "2. Semester: Enter semester number (1-8)",
        "   - Semesters 1-2 = Year 1 (First Year)",
        "   - Semesters 3-4 = Year 2 (Second Year)", 
        "   - Semesters 5-6 = Year 3 (Third Year)",
        "   - Semesters 7-8 = Year 4 (Final Year)",
        "3. Subject Code: Must be unique",
        "",
        "Subject Type Definitions:",
        "- theory: Regular theory subjects",
        "- practical: Laboratory/practical subjects",
        "- tutorials: Tutorial subjects"
    ]
    
    for row, instruction in enumerate(instructions, 1):
        ws2.cell(row=row, column=1, value=instruction)
    
    # Adjust column widths
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 20
    
    # Create response
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=subjects_template.xlsx'
    return response


@login_required
@user_passes_test(is_admin)
def download_assignment_template(request):
    """Download Excel template for professor-batch assignments"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Assignments Template"
    
    # Header style
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="a50c22", end_color="a50c22", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Headers
    headers = [
        'Professor Employee ID', 'Subject Code', 'Division Name', 'Batch Name', 'Semester'
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
    
    # Sample data
    sample_data = [
        ['EMP001', 'CS202L', 'A', 'A1', '3'],
        ['EMP002', 'CS202L', 'A', 'A2', '3'],
        ['EMP001', 'CS205L', 'B', 'B1', '4'],
    ]
    
    for row, data in enumerate(sample_data, 2):
        for col, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = thin_border
    
    # Add instructions sheet
    ws2 = wb.create_sheet("Instructions")
    instructions = [
        "Instructions for Professor-Batch Assignments Import:",
        "",
        "1. Professor Employee ID: Must exist in the system",
        "2. Subject Code: Must exist and be of type 'practical'",
        "3. Division Name: Division letter (A, B, C, etc.)",
        "4. Year: Year number (1, 2, 3, 4)",
        "5. Batch Name: Batch name within the division (A1, A2, B1, etc.)",
        "",
        "Note: This assigns professors to teach practical subjects for specific batches.",
        "Both professor and practical batch must exist before importing assignments.",
        "",
        "Example: EMP001 teaching CS202L (Database Lab) to batch A1 of division A, year 2"
    ]
    
    for row, instruction in enumerate(instructions, 1):
        ws2.cell(row=row, column=1, value=instruction)
    
    # Adjust column widths
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 20
    
    # Create response
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=professor_assignments_template.xlsx'
    return response


@login_required
@user_passes_test(is_admin)
def download_theory_assignment_template(request):
    """Download Excel template for theory professor-division assignments"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Theory Assignments Template"
    
    # Header style
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="a50c22", end_color="a50c22", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Headers
    headers = [
        'Professor Employee ID', 'Subject Code', 'Division Name', 'Semester'
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
    
    # Sample data
    sample_data = [
        ['EMP001', 'CS201', 'A', '3'],
        ['EMP002', 'CS202', 'A', '3'],
        ['EMP001', 'CS301', 'B', '5'],
    ]
    
    for row, data in enumerate(sample_data, 2):
        for col, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = thin_border
    
    # Add instructions sheet
    ws2 = wb.create_sheet("Instructions")
    instructions = [
        "Instructions for Theory Professor-Division Assignments Import:",
        "",
        "1. Professor Employee ID: Must exist in the system",
        "2. Subject Code: Must exist and be of type 'theory'",
        "3. Division Name: Division letter (A, B, C, etc.)",
        "4. Semester: Enter semester number (1-8). Year will be auto-calculated.",
        "",
        "Note: This assigns professors to teach theory subjects to entire divisions.",
        "Both professor and division must exist before importing assignments.",
        "Year is automatically calculated from semester (1-2=Year1, 3-4=Year2, etc.)",
        "",
        "Example: EMP001 teaching CS201 to division A, semester 3 (Year 2)"
    ]
    
    for row, instruction in enumerate(instructions, 1):
        ws2.cell(row=row, column=1, value=instruction)
    
    # Adjust column widths
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 20
    
    # Create response
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=theory_assignments_template.xlsx'
    return response


@login_required
@user_passes_test(is_admin)
def import_professors(request):
    """Import professors from Excel file"""
    if request.method == 'POST':
        if 'excel_file' not in request.FILES:
            messages.error(request, "Please select an Excel file to upload.")
            return redirect('import_data')
        
        file = request.FILES['excel_file']
        
        if not file.name.endswith(('.xlsx', '.xls')):
            messages.error(request, "Please upload a valid Excel file (.xlsx or .xls).")
            return redirect('import_data')
        
        try:
            df = pd.read_excel(file)
            required_columns = ['First Name', 'Last Name', 'Employee ID', 'Department']
            
            # Check if all required columns exist
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                messages.error(request, f"Missing required columns: {', '.join(missing_columns)}")
                return redirect('import_data')
            
            imported_count = 0
            skipped_count = 0
            errors = []
            
            with transaction.atomic():
                for row_idx, (index, row) in enumerate(df.iterrows()):
                    row_num = row_idx + 2  # Add 2 for Excel row number (1-indexed + header)
                    try:
                        # Auto-generate username as firstname.lastname
                        first_name = str(row['First Name']).strip()
                        last_name = str(row['Last Name']).strip()
                        username = f"{first_name.lower()}.{last_name.lower()}"
                        
                        # Handle duplicate usernames by adding numbers
                        base_username = username
                        counter = 1
                        while User.objects.filter(username=username).exists():
                            username = f"{base_username}{counter}"
                            counter += 1
                        
                        # Check if employee ID already exists - skip instead of error
                        if Professor.objects.filter(employee_id=row['Employee ID']).exists():
                            #errors.append(f"Row {row_num}: Employee ID '{row['Employee ID']}' already exists")
                            skipped_count += 1
                            continue
                        
                        # Create user with auto-generated username and optional email
                        user = User.objects.create_user(
                            username=username,
                            email='',  # Empty email as it's now optional
                            first_name=first_name,
                            last_name=last_name,
                            is_staff=False
                        )
                        
                        # Create professor
                        Professor.objects.create(
                            user=user,
                            employee_id=row['Employee ID'],
                            department=row['Department']
                        )
                        
                        imported_count += 1
                        
                    except Exception as e:
                        errors.append(f"Row {row_num}: {str(e)}")
            
            # Show results
            if imported_count > 0:
                messages.success(request, f"Successfully imported {imported_count} professors.")
            
            if skipped_count > 0:
                messages.info(request, f"Skipped {skipped_count} professors (already exist).")
            
            if errors:
                error_msg = "Errors encountered:\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    error_msg += f"\n... and {len(errors) - 10} more errors."
                messages.error(request, error_msg)
            
        except Exception as e:
            messages.error(request, f"Error processing file: {str(e)}")
    
    return redirect('import_data')


@login_required
@user_passes_test(is_admin)
def import_students(request):
    """Import students from Excel file"""
    if request.method == 'POST':
        if 'excel_file' not in request.FILES:
            messages.error(request, "Please select an Excel file to upload.")
            return redirect('import_data')
        
        file = request.FILES['excel_file']
        add_prefix = request.POST.get('add_rollno_prefix') == 'on'
        
        if not file.name.endswith(('.xlsx', '.xls')):
            messages.error(request, "Please upload a valid Excel file (.xlsx or .xls).")
            return redirect('import_data')
        
        try:
            df = pd.read_excel(file)
            required_columns = ['First Name', 'Last Name', 'Email', 'Username', 'Roll Number', 'Division', 'Semester', 'Department']
            
            # Check if all required columns exist
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                messages.error(request, f"Missing required columns: {', '.join(missing_columns)}")
                return redirect('import_data')
            
            imported_count = 0
            skipped_count = 0
            errors = []
            
            with transaction.atomic():
                for row_idx, (index, row) in enumerate(df.iterrows()):
                    row_num = row_idx + 2  # Add 2 for Excel row number (1-indexed + header)
                    try:
                        # Get semester and division values
                        semester = int(row['Semester'])
                        division_name = row['Division']
                        
                        # Prepare roll number with optional prefix
                        roll_number = row['Roll Number']
                        if add_prefix:
                            roll_number = f"{semester}{settings.BRANCH}{division_name}{row['Roll Number']}"
                        
                        # Check if user already exists - skip instead of error
                        if User.objects.filter(username=row['Username']).exists():
                            skipped_count += 1
                            continue
                        
                        if User.objects.filter(email=row['Email']).exists():
                            skipped_count += 1
                            continue
                        
                        if Student.objects.filter(roll_number=roll_number).exists():
                            skipped_count += 1
                            continue
                        
                        # Calculate year from semester
                        calculated_year = ((semester - 1) // 2) + 1
                        
                        # Get or create division
                        try:
                            division = Division.objects.get(name=row['Division'], year=calculated_year)
                        except Division.DoesNotExist:
                            errors.append(f"Row {row_num}: Division '{row['Division']}' for calculated year {calculated_year} (from semester {semester}) does not exist")
                            continue
                        
                        # Get practical batch if specified
                        practical_batch = None
                        if 'Practical Batch' in df.columns and pd.notna(row['Practical Batch']):
                            try:
                                practical_batch = PracticalBatch.objects.get(name=row['Practical Batch'], division=division)
                            except PracticalBatch.DoesNotExist:
                                errors.append(f"Row {row_num}: Practical Batch '{row['Practical Batch']}' does not exist for division {division}")
                                continue
                        
                        # Create user
                        user = User.objects.create_user(
                            username=row['Username'],
                            email=row['Email'],
                            first_name=row['First Name'],
                            last_name=row['Last Name'],
                            is_staff=False
                        )
                        
                        # Create student
                        Student.objects.create(
                            user=user,
                            roll_number=roll_number,
                            division=division,
                            practical_batch=practical_batch,
                            semester=semester,
                            department=row['Department'] if 'Department' in row and pd.notna(row['Department']) else 'Computer Engineering'
                        )
                        
                        imported_count += 1
                        
                    except Exception as e:
                        errors.append(f"Row {row_num}: {str(e)}")
            
            # Show results
            if imported_count > 0:
                messages.success(request, f"Successfully imported {imported_count} students.")
            
            if skipped_count > 0:
                messages.info(request, f"Skipped {skipped_count} students (already exist).")
            
            if errors:
                error_msg = "Errors encountered:\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    error_msg += f"\n... and {len(errors) - 10} more errors."
                messages.error(request, error_msg)
            
        except Exception as e:
            messages.error(request, f"Error processing file: {str(e)}")
    
    return redirect('import_data')


@login_required
@user_passes_test(is_admin)
def import_subjects(request):
    """Import subjects from Excel file"""
    if request.method == 'POST':
        if 'excel_file' not in request.FILES:
            messages.error(request, "Please select an Excel file to upload.")
            return redirect('import_data')
        
        file = request.FILES['excel_file']
        
        if not file.name.endswith(('.xlsx', '.xls')):
            messages.error(request, "Please upload a valid Excel file (.xlsx or .xls).")
            return redirect('import_data')
        
        try:
            df = pd.read_excel(file)
            required_columns = ['Subject Name', 'Subject Code', 'Subject Type', 'Semester']
            
            # Check if all required columns exist
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                messages.error(request, f"Missing required columns: {', '.join(missing_columns)}")
                return redirect('import_data')
            
            # Check if optional 'Elective' column exists
            has_elective_column = 'Elective' in df.columns
            
            imported_count = 0
            skipped_count = 0
            errors = []
            valid_types = ['theory', 'practical', 'tutorials']
            
            with transaction.atomic():
                for row_idx, (index, row) in enumerate(df.iterrows()):
                    row_num = row_idx + 2  # Add 2 for Excel row number (1-indexed + header)
                    try:
                        # Validate subject type
                        if row['Subject Type'].lower() not in valid_types:
                            errors.append(f"Row {row_num}: Invalid subject type '{row['Subject Type']}'. Must be one of: {', '.join(valid_types)}")
                            continue
                        
                        # Check if subject code already exists - skip instead of error
                        if Subject.objects.filter(code=row['Subject Code']).exists():
                            skipped_count += 1
                            continue
                        
                        # Get semester and calculate year
                        semester = int(row['Semester'])
                        calculated_year = ((semester - 1) // 2) + 1
                        
                        # Get elective value if column exists
                        elective_value = None
                        if has_elective_column and pd.notna(row['Elective']) and row['Elective'] != '':
                            try:
                                elective_value = int(row['Elective'])
                                if elective_value < 1:
                                    errors.append(f"Row {row_num}: Elective value must be a positive number")
                                    continue
                            except (ValueError, TypeError):
                                errors.append(f"Row {row_num}: Invalid elective value '{row['Elective']}'. Must be a number.")
                                continue
                        
                        # Create subject
                        Subject.objects.create(
                            name=row['Subject Name'],
                            code=row['Subject Code'],
                            subject_type=row['Subject Type'].lower(),
                            semester=semester,
                            elective=elective_value
                        )
                        
                        imported_count += 1
                        
                    except Exception as e:
                        errors.append(f"Row {row_num}: {str(e)}")
            
            # Show results
            if imported_count > 0:
                messages.success(request, f"Successfully imported {imported_count} subjects.")
            
            if skipped_count > 0:
                messages.info(request, f"Skipped {skipped_count} subjects (already exist).")
            
            if errors:
                error_msg = "Errors encountered:\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    error_msg += f"\n... and {len(errors) - 10} more errors."
                messages.error(request, error_msg)
            
        except Exception as e:
            messages.error(request, f"Error processing file: {str(e)}")
    
    return redirect('import_data')


@login_required
@user_passes_test(is_admin)
def import_assignments(request):
    """Import professor-batch assignments from Excel file"""
    if request.method == 'POST':
        if 'excel_file' not in request.FILES:
            messages.error(request, "Please select an Excel file to upload.")
            return redirect('import_data')
        
        file = request.FILES['excel_file']
        
        if not file.name.endswith(('.xlsx', '.xls')):
            messages.error(request, "Please upload a valid Excel file (.xlsx or .xls).")
            return redirect('import_data')
        
        try:
            df = pd.read_excel(file)
            required_columns = ['Professor Employee ID', 'Subject Code', 'Division Name', 'Batch Name', 'Semester']
            
            # Check if all required columns exist
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                messages.error(request, f"Missing required columns: {', '.join(missing_columns)}")
                return redirect('import_data')
            
            imported_count = 0
            skipped_count = 0
            errors = []
            
            with transaction.atomic():
                for row_idx, (index, row) in enumerate(df.iterrows()):
                    row_num = row_idx + 2  # Add 2 for Excel row number (1-indexed + header)
                    try:
                        # Get professor
                        try:
                            professor = Professor.objects.get(employee_id=row['Professor Employee ID'])
                        except Professor.DoesNotExist:
                            errors.append(f"Row {row_num}: Professor with Employee ID '{row['Professor Employee ID']}' does not exist")
                            continue
                        
                        # Get subject
                        try:
                            subject = Subject.objects.get(code=row['Subject Code'])
                            if subject.subject_type not in ['practical', 'tutorials']:
                                errors.append(f"Row {row_num}: Subject '{row['Subject Code']}' is not a practical or tutorial subject")
                                continue
                        except Subject.DoesNotExist:
                            errors.append(f"Row {row_num}: Subject with code '{row['Subject Code']}' does not exist")
                            continue
                        
                        # Get semester and calculate year
                        semester = int(row['Semester'])
                        calculated_year = ((semester - 1) // 2) + 1
                        
                        # Get division
                        try:
                            division = Division.objects.get(name=row['Division Name'], year=calculated_year)
                        except Division.DoesNotExist:
                            errors.append(f"Row {row_num}: Division '{row['Division Name']}' for calculated year {calculated_year} (from semester {semester}) does not exist")
                            continue
                        
                        # Get batch
                        try:
                            batch = PracticalBatch.objects.get(name=row['Batch Name'], division=division)
                        except PracticalBatch.DoesNotExist:
                            errors.append(f"Row {row_num}: Batch '{row['Batch Name']}' does not exist for division {division}")
                            continue
                        
                        # Check if assignment already exists - skip instead of error
                        if PracticalAssignment.objects.filter(professor=professor, subject=subject, batch=batch, semester=semester).exists():
                            skipped_count += 1
                            continue
                        
                        # Create assignment
                        PracticalAssignment.objects.create(
                            professor=professor,
                            subject=subject,
                            batch=batch,
                            semester=semester
                        )
                        
                        imported_count += 1
                        
                    except Exception as e:
                        errors.append(f"Row {row_num}: {str(e)}")
            
            # Show results
            if imported_count > 0:
                messages.success(request, f"Successfully imported {imported_count} professor-batch assignments.")
            
            if skipped_count > 0:
                messages.info(request, f"Skipped {skipped_count} assignments (already exist).")
            
            if errors:
                error_msg = "Errors encountered:\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    error_msg += f"\n... and {len(errors) - 10} more errors."
                messages.error(request, error_msg)
            
        except Exception as e:
            messages.error(request, f"Error processing file: {str(e)}")
    
    return redirect('import_data')


@login_required
@user_passes_test(is_admin)
def import_theory_assignments(request):
    """Import theory professor-division assignments from Excel file"""
    if request.method == 'POST':
        if 'excel_file' not in request.FILES:
            messages.error(request, "Please select an Excel file to upload.")
            return redirect('import_data')
        
        file = request.FILES['excel_file']
        
        if not file.name.endswith(('.xlsx', '.xls')):
            messages.error(request, "Please upload a valid Excel file (.xlsx or .xls).")
            return redirect('import_data')
        
        try:
            df = pd.read_excel(file)
            required_columns = ['Professor Employee ID', 'Subject Code', 'Division Name', 'Semester']
            
            # Check if all required columns exist
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                messages.error(request, f"Missing required columns: {', '.join(missing_columns)}")
                return redirect('import_data')
            
            imported_count = 0
            skipped_count = 0
            errors = []
            
            with transaction.atomic():
                for row_idx, (index, row) in enumerate(df.iterrows()):
                    row_num = row_idx + 2  # Add 2 for Excel row number (1-indexed + header)
                    try:
                        # Get professor
                        try:
                            professor = Professor.objects.get(employee_id=row['Professor Employee ID'])
                        except Professor.DoesNotExist:
                            errors.append(f"Row {row_num}: Professor with Employee ID '{row['Professor Employee ID']}' does not exist")
                            continue
                        
                        # Get subject
                        try:
                            subject = Subject.objects.get(code=row['Subject Code'])
                            if subject.subject_type != 'theory':
                                errors.append(f"Row {row_num}: Subject '{row['Subject Code']}' is not a theory subject")
                                continue
                        except Subject.DoesNotExist:
                            errors.append(f"Row {row_num}: Subject with code '{row['Subject Code']}' does not exist")
                            continue
                        
                        # Get semester and calculate year
                        semester = int(row['Semester'])
                        calculated_year = ((semester - 1) // 2) + 1
                        
                        # Get division
                        try:
                            division = Division.objects.get(name=row['Division Name'], year=calculated_year)
                        except Division.DoesNotExist:
                            errors.append(f"Row {row_num}: Division '{row['Division Name']}' for calculated year {calculated_year} (from semester {semester}) does not exist")
                            continue
                        
                        # Check if assignment already exists - skip instead of error
                        if TeacherAssignment.objects.filter(professor=professor, subject=subject, division=division, semester=semester).exists():
                            skipped_count += 1
                            continue
                        
                        # Create assignment
                        TeacherAssignment.objects.create(
                            professor=professor,
                            subject=subject,
                            division=division,
                            semester=semester
                        )
                        
                        imported_count += 1
                        
                    except Exception as e:
                        errors.append(f"Row {row_num}: {str(e)}")
            
            # Show results
            if imported_count > 0:
                messages.success(request, f"Successfully imported {imported_count} theory professor-division assignments.")
            
            if skipped_count > 0:
                messages.info(request, f"Skipped {skipped_count} theory assignments (already exist).")
            
            if errors:
                error_msg = "Errors encountered:\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    error_msg += f"\n... and {len(errors) - 10} more errors."
                messages.error(request, error_msg)
            
        except Exception as e:
            messages.error(request, f"Error processing file: {str(e)}")
    
    return redirect('import_data')
