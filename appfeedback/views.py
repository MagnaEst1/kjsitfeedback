from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.db.models import Max
from django.http import JsonResponse, HttpResponse
from django.forms import formset_factory
from django.core.exceptions import ValidationError
import pandas as pd
import openpyxl
import json
import csv
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from io import BytesIO
from .models import (
    Division, Professor, Subject, PracticalBatch, Student, 
    TeacherAssignment, FeedbackForm, FeedbackQuestion, 
    FeedbackResponse, FeedbackAnswer, PracticalAssignment
)
from .forms import (
    FeedbackFormCreationForm, FeedbackQuestionForm, 
    FeedbackResponseForm, FeedbackAnswerFormSet
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
        
        # Theory forms for student's division
        theory_forms = FeedbackForm.objects.filter(
            division=student.division,
            subject__subject_type='theory',
            is_active=True,
            start_date__lte=current_time,
            end_date__gte=current_time
        ).exclude(
            responses__student=student
        ).select_related('subject', 'professor', 'division')
        
        # Practical and tutorial forms for student's practical batch
        practical_tutorial_forms = []
        if student.practical_batch:
            practical_tutorial_forms = FeedbackForm.objects.filter(
                practical_batch=student.practical_batch,
                subject__subject_type__in=['practical', 'tutorials'],
                is_active=True,
                start_date__lte=current_time,
                end_date__gte=current_time
            ).exclude(
                responses__student=student
            ).select_related('subject', 'professor', 'division', 'practical_batch')
        
        # Combine all available forms
        available_forms = list(theory_forms) + list(practical_tutorial_forms)
        
        # Get completed forms
        completed_forms = FeedbackResponse.objects.filter(
            student=student
        ).select_related('form__subject', 'form__professor', 'form__division')
        
        context = {
            'student': student,
            'available_forms': available_forms,
            'completed_forms': completed_forms,
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


def is_admin(user):
    return user.is_staff or user.is_superuser


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
    
    return render(request, 'manage_feedback_forms.html', {
        'forms': forms,
        'active_forms_count': active_forms_count
    })


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
    
    # Check if student has already responded
    if FeedbackResponse.objects.filter(form=feedback_form, student=student).exists():
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
    
    questions = feedback_form.questions.all().order_by('order')
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Create feedback response
                response = FeedbackResponse.objects.create(
                    form=feedback_form,
                    student=student,
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
                
                messages.success(request, "Feedback submitted successfully!")
                return redirect('dashboard')
                
        except (ValidationError, ValueError) as e:
            messages.error(request, f"Error submitting feedback: {e}")
    
    return render(request, 'fill_feedback_form.html', {
        'form': feedback_form,
        'questions': questions,
    })


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
    
    # For practical and tutorial subjects, filter by assignments to specific batches
    if subject_type in ['practical', 'tutorials'] and division_id and practical_batch_id:
        # Get subjects that have practical assignments for this batch
        assigned_subjects = PracticalAssignment.objects.filter(
            batch_id=practical_batch_id
        ).values_list('subject_id', flat=True)
        subjects_query = subjects_query.filter(id__in=assigned_subjects)
    
    # For theory subjects, filter by teacher assignments to the division
    elif subject_type == 'theory' and division_id:
        # Get subjects that have teacher assignments for this division
        assigned_subjects = TeacherAssignment.objects.filter(
            division_id=division_id
        ).values_list('subject_id', flat=True)
        subjects_query = subjects_query.filter(id__in=assigned_subjects)
    
    subjects = subjects_query.values('id', 'code', 'name', 'year').order_by('year', 'code')
    return JsonResponse({'subjects': list(subjects)})


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
        
        if subject.subject_type in ['practical', 'tutorials'] and practical_batch_id:
            # For practical and tutorial subjects, get professors who:
            # 1. Are assigned to this specific subject and batch
            # 2. Are not already assigned to any other batch for practical/tutorial subjects
            assigned_professors = PracticalAssignment.objects.filter(
                subject=subject,
                batch_id=practical_batch_id
            ).values_list('professor_id', flat=True)
            
            # Get professors who are not assigned to other batches for practical/tutorial subjects
            professors_with_other_batches = PracticalAssignment.objects.exclude(
                subject=subject,
                batch_id=practical_batch_id
            ).filter(
                subject__subject_type__in=['practical', 'tutorials']
            ).values_list('professor_id', flat=True)
            
            # Only include professors assigned to this batch and not assigned to other batches
            available_professor_ids = [pid for pid in assigned_professors if pid not in professors_with_other_batches]
            
            professors = Professor.objects.filter(
                id__in=available_professor_ids
            ).values('id', 'user__first_name', 'user__last_name', 'employee_id')
        else:
            # For theory subjects, get professors who:
            # 1. Are assigned to this specific subject and division
            # 2. Are not already assigned to any other division for theory subjects
            assigned_professors = TeacherAssignment.objects.filter(
                subject=subject,
                division_id=division_id
            ).values_list('professor_id', flat=True)
            
            # Get professors who are assigned to other divisions for theory subjects
            professors_with_other_divisions = TeacherAssignment.objects.exclude(
                subject=subject,
                division_id=division_id
            ).filter(
                subject__subject_type='theory'
            ).values_list('professor_id', flat=True)
            
            # Only include professors assigned to this division and not assigned to other divisions
            available_professor_ids = [pid for pid in assigned_professors if pid not in professors_with_other_divisions]
            
            professors = Professor.objects.filter(
                id__in=available_professor_ids
            ).values('id', 'user__first_name', 'user__last_name', 'employee_id')
        
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
    
    # Calculate eligible students count
    if feedback_form.practical_batch:
        # For practical subjects, count students in the specific batch
        eligible_students = Student.objects.filter(
            division=feedback_form.division,
            practical_batch=feedback_form.practical_batch
        ).distinct()
    else:
        # For theory subjects, count all students in the division
        eligible_students = Student.objects.filter(division=feedback_form.division)
    
    eligible_students_count = eligible_students.count()
    
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
def export_responses(request, form_id):
    """Export feedback responses to CSV"""
    feedback_form = get_object_or_404(FeedbackForm, id=form_id)
    
    if not request.user.is_staff:
        messages.error(request, "You don't have permission to export responses.")
        return redirect('dashboard')
    
    # Create the HttpResponse object with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="feedback_responses_{feedback_form.id}_{feedback_form.title[:20]}.csv"'
    
    writer = csv.writer(response)
    
    # Write header row
    questions = feedback_form.questions.all().order_by('order')
    header = ['Student Roll Number', 'Student Name', 'Submission Date', 'Is Anonymous']
    for question in questions:
        header.append(f"Q{question.order}: {question.question_text[:50]}")
    writer.writerow(header)
    
    # Add a note about anonymous responses
    if feedback_form.allow_anonymous:
        note_row = ['Note: Anonymous responses show "Anonymous Student" and "Anonymous-ID" to protect privacy', '', '', '']
        for _ in questions:
            note_row.append('')
        writer.writerow(note_row)
        writer.writerow([])  # Empty row for spacing
    
    # Write data rows
    responses = FeedbackResponse.objects.filter(form=feedback_form).select_related(
        'student__user'
    ).prefetch_related('answers__question')
    
    for feedback_response in responses:
        # Respect anonymity settings
        if feedback_response.is_anonymous:
            student_roll = f"Anonymous-{feedback_response.id}"
            student_name = "Anonymous Student"
        else:
            student_roll = feedback_response.student.roll_number
            student_name = feedback_response.student.user.get_full_name()
        
        row = [
            student_roll,
            student_name,
            feedback_response.submitted_at.strftime('%Y-%m-%d %H:%M:%S IST'),
            'Yes' if feedback_response.is_anonymous else 'No'
        ]
        
        # Add answers in question order
        answers_dict = {answer.question_id: answer for answer in feedback_response.answers.all()}
        for question in questions:
            answer = answers_dict.get(question.id)
            if answer:
                answer_text = answer.get_answer()
                row.append(str(answer_text) if answer_text is not None else '')
            else:
                row.append('')
        
        writer.writerow(row)
    
    return response


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
        form_title_prefix = request.POST.get('form_title_prefix', 'Feedback')
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
                        form_title = f"{form_title_prefix} - {assignment.subject.name} - {assignment.professor.user.get_full_name()} - {assignment.division}"
                        
                        # Create feedback form
                        feedback_form = FeedbackForm.objects.create(
                            title=form_title,
                            description=f"Automated feedback form for {assignment.subject.name} (Theory)",
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
                        form_title = f"{form_title_prefix} - {assignment.subject.name} - {assignment.professor.user.get_full_name()} - {assignment.batch}"
                        
                        # Create feedback form
                        feedback_form = FeedbackForm.objects.create(
                            title=form_title,
                            description=f"Automated feedback form for {assignment.subject.name} ({assignment.subject.get_subject_type_display()})",
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
    one_week_later = server_now + timedelta(weeks=1)
    
    context = {
        'theory_assignments_count': theory_count,
        'practical_assignments_count': practical_count,
        'total_assignments': theory_count + practical_count,
        'existing_forms_count': existing_forms,
        'server_start_time': server_now.strftime('%Y-%m-%dT%H:%M'),
        'server_end_time': one_week_later.strftime('%Y-%m-%dT%H:%M'),
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
        'Subject Name', 'Subject Code', 'Subject Type', 'Semester'
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
        "1. Subject Type: Must be one of: theory, practical, tutorials",
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
                        
                        # Check if employee ID already exists
                        if Professor.objects.filter(employee_id=row['Employee ID']).exists():
                            errors.append(f"Row {row_num}: Employee ID '{row['Employee ID']}' already exists")
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
            
            if imported_count > 0:
                messages.success(request, f"Successfully imported {imported_count} professors.")
            
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
            errors = []
            
            with transaction.atomic():
                for row_idx, (index, row) in enumerate(df.iterrows()):
                    row_num = row_idx + 2  # Add 2 for Excel row number (1-indexed + header)
                    try:
                        # Check if user already exists
                        if User.objects.filter(username=row['Username']).exists():
                            errors.append(f"Row {row_num}: Username '{row['Username']}' already exists")
                            continue
                        
                        if User.objects.filter(email=row['Email']).exists():
                            errors.append(f"Row {row_num}: Email '{row['Email']}' already exists")
                            continue
                        
                        if Student.objects.filter(roll_number=row['Roll Number']).exists():
                            errors.append(f"Row {row_num}: Roll Number '{row['Roll Number']}' already exists")
                            continue
                        
                        # Get semester and calculate year
                        semester = int(row['Semester'])
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
                            roll_number=row['Roll Number'],
                            division=division,
                            practical_batch=practical_batch,
                            semester=semester,
                            department=row['Department'] if 'Department' in row and pd.notna(row['Department']) else 'Computer Engineering'
                        )
                        
                        imported_count += 1
                        
                    except Exception as e:
                        errors.append(f"Row {row_num}: {str(e)}")
            
            if imported_count > 0:
                messages.success(request, f"Successfully imported {imported_count} students.")
            
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
            
            imported_count = 0
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
                        
                        # Check if subject code already exists
                        if Subject.objects.filter(code=row['Subject Code']).exists():
                            errors.append(f"Row {row_num}: Subject Code '{row['Subject Code']}' already exists")
                            continue
                        
                        # Get semester and calculate year
                        semester = int(row['Semester'])
                        calculated_year = ((semester - 1) // 2) + 1
                        
                        # Create subject
                        Subject.objects.create(
                            name=row['Subject Name'],
                            code=row['Subject Code'],
                            subject_type=row['Subject Type'].lower(),
                            semester=semester
                        )
                        
                        imported_count += 1
                        
                    except Exception as e:
                        errors.append(f"Row {row_num}: {str(e)}")
            
            if imported_count > 0:
                messages.success(request, f"Successfully imported {imported_count} subjects.")
            
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
                        
                        # Check if assignment already exists
                        if PracticalAssignment.objects.filter(professor=professor, subject=subject, batch=batch, semester=semester).exists():
                            errors.append(f"Row {row_num}: Assignment already exists for {professor.employee_id} - {subject.code} - {batch.name} - Sem {semester}")
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
            
            if imported_count > 0:
                messages.success(request, f"Successfully imported {imported_count} professor-batch assignments.")
            
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
                        
                        # Check if assignment already exists
                        if TeacherAssignment.objects.filter(professor=professor, subject=subject, division=division, semester=semester).exists():
                            errors.append(f"Row {row_num}: Assignment already exists for {professor.employee_id} - {subject.code} - {division} - Sem {semester}")
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
            
            if imported_count > 0:
                messages.success(request, f"Successfully imported {imported_count} theory professor-division assignments.")
            
            if errors:
                error_msg = "Errors encountered:\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    error_msg += f"\n... and {len(errors) - 10} more errors."
                messages.error(request, error_msg)
            
        except Exception as e:
            messages.error(request, f"Error processing file: {str(e)}")
    
    return redirect('import_data')
