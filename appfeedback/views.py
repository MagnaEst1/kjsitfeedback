from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.db.models import Max
from django.http import JsonResponse
from django.forms import formset_factory
from django.core.exceptions import ValidationError
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


@login_required
def dashboard_view(request):
    try:
        student = Student.objects.get(user=request.user)
        
        # Get all active feedback forms for this student
        current_time = timezone.now()
        
        # Theory and SAT forms for student's division
        theory_sat_forms = FeedbackForm.objects.filter(
            division=student.division,
            subject__subject_type__in=['theory', 'sat'],
            is_active=True,
            start_date__lte=current_time,
            end_date__gte=current_time
        ).exclude(
            responses__student=student
        ).select_related('subject', 'professor', 'division')
        
        # Practical forms for student's practical batch
        practical_forms = []
        if student.practical_batch:
            practical_forms = FeedbackForm.objects.filter(
                practical_batch=student.practical_batch,
                subject__subject_type='practical',
                is_active=True,
                start_date__lte=current_time,
                end_date__gte=current_time
            ).exclude(
                responses__student=student
            ).select_related('subject', 'professor', 'division', 'practical_batch')
        
        # Combine all available forms
        available_forms = list(theory_sat_forms) + list(practical_forms)
        
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
                    
                    # Create default questions if none exist
                    default_questions = [
                        {"text": "Rate the overall teaching quality", "type": "rating", "order": 1},
                        {"text": "How would you rate the clarity of explanations?", "type": "rating", "order": 2},
                        {"text": "Rate the professor's punctuality", "type": "rating", "order": 3},
                        {"text": "How helpful was the professor in addressing doubts?", "type": "rating", "order": 4},
                        {"text": "Any additional comments or suggestions", "type": "text", "order": 5, "required": False},
                    ]
                    
                    for q_data in default_questions:
                        question = FeedbackQuestion(
                            form=feedback_form,
                            question_text=q_data["text"],
                            question_type=q_data["type"],
                            order=q_data["order"],
                            is_required=q_data.get("required", True)
                        )
                        question.save()
                    
                    messages.success(request, f'Feedback form "{feedback_form.title}" created successfully!')
                    return redirect('manage_feedback_forms')
                    
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
    
    return render(request, 'create_feedback_form.html', {'form': form})


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
    if feedback_form.subject.subject_type in ['theory', 'sat']:
        if feedback_form.division == student.division:
            eligible = True
    elif feedback_form.subject.subject_type == 'practical':
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
    
    # For practical subjects, filter by assignments to specific batches
    if subject_type == 'practical' and division_id and practical_batch_id:
        # Get subjects that have practical assignments for this batch
        assigned_subjects = PracticalAssignment.objects.filter(
            batch_id=practical_batch_id
        ).values_list('subject_id', flat=True)
        subjects_query = subjects_query.filter(id__in=assigned_subjects)
    
    # For theory/SAT subjects, filter by teacher assignments to the division
    elif subject_type in ['theory', 'sat'] and division_id:
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
        
        if subject.subject_type == 'practical' and practical_batch_id:
            # For practical subjects, get professors from PracticalAssignment for specific batch
            professors = Professor.objects.filter(
                practicalassignment__subject=subject,
                practicalassignment__batch_id=practical_batch_id
            ).distinct().values('id', 'user__first_name', 'user__last_name', 'employee_id')
        else:
            # For theory/SAT subjects, get professors from TeacherAssignment
            professors = Professor.objects.filter(
                teacherassignment__subject=subject,
                teacherassignment__division_id=division_id
            ).distinct().values('id', 'user__first_name', 'user__last_name', 'employee_id')
        
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
    
    # Prepare question-wise analysis
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
                response__form=feedback_form,
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
                response__form=feedback_form,
                text_answer__isnull=False
            ).exclude(text_answer='').values_list('text_answer', flat=True)
            
            question_data.update({
                'text_responses': list(text_answers),
                'total_responses': len(text_answers),
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
    import csv
    from django.http import HttpResponse
    
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
