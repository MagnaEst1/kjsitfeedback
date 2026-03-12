from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from .models import (
    Division, Professor, Subject, PracticalBatch, 
    FeedbackForm, FeedbackQuestion, FeedbackResponse, FeedbackAnswer,
    TeacherAssignment, PracticalAssignment, StoredExport
)


class FeedbackFormCreationForm(forms.ModelForm):
    subject_type = forms.ChoiceField(
        choices=[('', '--- Select Subject Type ---')] + Subject.SUBJECT_TYPES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_subject_type'})
    )
    
    class Meta:
        model = FeedbackForm
        fields = [
            'title', 'description', 'subject', 'division', 'professor', 
            'practical_batch', 'is_active', 'allow_anonymous', 'start_date', 'end_date'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'start_date': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'end_date': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'subject': forms.Select(attrs={'class': 'form-control'}),
            'division': forms.Select(attrs={'class': 'form-control'}),
            'professor': forms.Select(attrs={'class': 'form-control'}),
            'practical_batch': forms.Select(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_anonymous': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Make practical_batch field conditional based on subject type
        self.fields['practical_batch'].required = False
        
        # Set default dates
        if not self.instance.pk:
            now = timezone.now()
            self.fields['start_date'].initial = now
            self.fields['end_date'].initial = now + timedelta(weeks=1)  # Default 1 week later
        
        # For new forms, show all options initially (AJAX will filter them)
        # For existing forms, show relevant options
        if not self.instance.pk:
            # New form - show all subjects, professors, and batches
            self.fields['subject'].queryset = Subject.objects.all()
            self.fields['professor'].queryset = Professor.objects.all()
            self.fields['practical_batch'].queryset = PracticalBatch.objects.all()
        else:
            # Existing form - show only relevant options
            if self.instance.subject:
                self.fields['subject_type'].initial = self.instance.subject.subject_type
                self.fields['subject'].queryset = Subject.objects.filter(subject_type=self.instance.subject.subject_type)
                
                if self.instance.subject.subject_type == 'practical':
                    self.fields['professor'].queryset = Professor.objects.filter(
                        practicalassignment__subject=self.instance.subject,
                        practicalassignment__batch__division=self.instance.division
                    ).distinct()
                    self.fields['practical_batch'].queryset = PracticalBatch.objects.filter(
                        division=self.instance.division
                    )
                else:
                    self.fields['professor'].queryset = Professor.objects.filter(
                        teacherassignment__subject=self.instance.subject,
                        teacherassignment__division=self.instance.division
                    ).distinct()
    
    def clean(self):
        cleaned_data = super().clean()
        subject = cleaned_data.get('subject')
        practical_batch = cleaned_data.get('practical_batch')
        division = cleaned_data.get('division')
        professor = cleaned_data.get('professor')
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        # Validate practical batch for practical and tutorial subjects
        if subject and subject.subject_type in ['practical', 'tutorials']:
            if not practical_batch:
                raise ValidationError("Practical batch is required for practical and tutorial subjects.")
            
            # Ensure practical batch belongs to the selected division
            if practical_batch.division != division:
                raise ValidationError("Selected practical batch does not belong to the selected division.")
            
            # Check if there's a practical assignment for this professor, subject, and batch
            try:
                PracticalAssignment.objects.get(
                    professor=professor,
                    subject=subject,
                    batch=practical_batch
                )
            except PracticalAssignment.DoesNotExist:
                raise ValidationError("The selected professor is not assigned to teach this subject for the selected batch.")
            
            # Constraint removed - professors can now be assigned to multiple batches
            pass
        
        elif subject and subject.subject_type == 'theory':
            if practical_batch:
                raise ValidationError("Practical batch should not be selected for theory subjects.")
            
            # Check if there's a teacher assignment for theory subjects
            try:
                TeacherAssignment.objects.get(
                    professor=professor,
                    subject=subject,
                    division=division
                )
            except TeacherAssignment.DoesNotExist:
                raise ValidationError("The selected professor is not assigned to teach this subject for the selected division.")
            
            # Constraint removed - professors can now be assigned to multiple divisions
            pass
        
        # Validate date range
        if start_date and end_date:
            if start_date >= end_date:
                raise ValidationError("End date must be after start date.")
        
        return cleaned_data


class FeedbackQuestionForm(forms.ModelForm):
    class Meta:
        model = FeedbackQuestion
        fields = ['question_text', 'question_type', 'is_required', 'order', 'choices']
        widgets = {
            'question_text': forms.Textarea(attrs={
                'rows': 3, 
                'class': 'block w-full border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'Enter your question here...'
            }),
            'question_type': forms.Select(attrs={
                'class': 'block w-full border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500'
            }),
            'order': forms.NumberInput(attrs={
                'class': 'block w-full border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500',
                'min': 1
            }),
            'is_required': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'
            }),
            'choices': forms.HiddenInput(),  # Hidden because we handle it with JavaScript
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make order field not required
        self.fields['order'].required = False
    
    def clean_choices(self):
        choices = self.cleaned_data.get('choices')
        question_type = self.cleaned_data.get('question_type')
        
        if question_type == 'multiple_choice':
            if not choices:
                raise ValidationError("Choices are required for multiple choice questions.")
            
            try:
                import json
                # Handle case where choices is already a list (from database)
                if isinstance(choices, list):
                    parsed_choices = choices
                elif isinstance(choices, str):
                    parsed_choices = json.loads(choices) if choices else []
                else:
                    parsed_choices = []
                
                if not isinstance(parsed_choices, list) or len(parsed_choices) < 2:
                    raise ValidationError("Multiple choice questions must have at least 2 options.")
                
                # Check that choices are not empty
                non_empty_choices = [choice.strip() for choice in parsed_choices if choice and str(choice).strip()]
                if len(non_empty_choices) < 2:
                    raise ValidationError("Multiple choice questions must have at least 2 non-empty options.")
                
                return json.dumps(non_empty_choices)
            except (json.JSONDecodeError, TypeError) as e:
                raise ValidationError("Invalid format for choices.")
        else:
            # For non-multiple choice questions, clear choices
            return None
        
        return choices


class FeedbackResponseForm(forms.ModelForm):
    class Meta:
        model = FeedbackResponse
        fields = ['is_anonymous']
        widgets = {
            'is_anonymous': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class FeedbackAnswerForm(forms.ModelForm):
    class Meta:
        model = FeedbackAnswer
        fields = ['rating_answer', 'text_answer', 'choice_answer']
    
    def __init__(self, *args, **kwargs):
        question = kwargs.pop('question', None)
        super().__init__(*args, **kwargs)
        
        if question:
            self.question = question
            
            # Only show relevant field based on question type
            if question.question_type == 'rating':
                self.fields = {'rating_answer': self.fields['rating_answer']}
                self.fields['rating_answer'].widget = forms.Select(
                    choices=[(i, i) for i in range(1, 6)],
                    attrs={'class': 'form-control'}
                )
                self.fields['rating_answer'].required = question.is_required
                
            elif question.question_type == 'text':
                self.fields = {'text_answer': self.fields['text_answer']}
                self.fields['text_answer'].widget = forms.Textarea(
                    attrs={'rows': 3, 'class': 'form-control'}
                )
                self.fields['text_answer'].required = question.is_required
                
            elif question.question_type == 'multiple_choice':
                self.fields = {'choice_answer': self.fields['choice_answer']}
                
                if question.choices:
                    try:
                        import json
                        choices = json.loads(question.choices)
                        choice_options = [(choice, choice) for choice in choices]
                        self.fields['choice_answer'].widget = forms.Select(
                            choices=[('', '--- Select ---')] + choice_options,
                            attrs={'class': 'form-control'}
                        )
                    except (json.JSONDecodeError, TypeError):
                        self.fields['choice_answer'].widget = forms.TextInput(
                            attrs={'class': 'form-control'}
                        )
                
                self.fields['choice_answer'].required = question.is_required


# Formset for handling multiple feedback answers
FeedbackAnswerFormSet = forms.modelformset_factory(
    FeedbackAnswer,
    form=FeedbackAnswerForm,
    extra=0,
    can_delete=False
)


class StoredExportUploadForm(forms.ModelForm):
    class Meta:
        model = StoredExport
        fields = ['title', 'export_file']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'block w-full border-gray-300 rounded-md shadow-sm focus:ring-kjsit-red focus:border-kjsit-red',
                'placeholder': 'e.g., Semester 5 Backup - 2025'
            }),
            'export_file': forms.ClearableFileInput(attrs={
                'class': 'block w-full text-sm text-gray-700 border border-gray-300 rounded-md cursor-pointer bg-white focus:outline-none'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].required = True
        self.fields['export_file'].required = True
    
    def clean_export_file(self):
        file = self.cleaned_data.get('export_file')
        if file:
            # 25MB limit
            max_size = 25 * 1024 * 1024
            if file.size > max_size:
                raise forms.ValidationError(f'File size exceeds 25MB limit. Current size: {file.size / (1024 * 1024):.2f}MB')
        return file


class QuickFeedbackFormForm(forms.Form):
    """Quick form creation for common feedback scenarios"""
    title = forms.CharField(max_length=200, widget=forms.TextInput(attrs={'class': 'form-control'}))
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    division = forms.ModelChoiceField(
        queryset=Division.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    start_date = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'})
    )
    end_date = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'})
    )
    
    TEMPLATE_CHOICES = [
        ('standard', 'Standard Teaching Evaluation'),
        ('practical', 'Practical Session Evaluation'),
        ('sat', 'SAT Evaluation'),
        ('custom', 'Custom (Create your own questions)'),
    ]
    
    template_type = forms.ChoiceField(
        choices=TEMPLATE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['start_date'].initial = timezone.now()
