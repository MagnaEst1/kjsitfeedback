from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator


class Division(models.Model):
    YEAR_CHOICES = [
        (1, 'FY'),  # First Year
        (2, 'SY'),  # Second Year
        (3, 'TY'),  # Third Year
        (4, 'LY'),  # Last Year
    ]
    
    name = models.CharField(max_length=10)  # e.g., 'A', 'B', 'C'
    year = models.PositiveIntegerField(choices=YEAR_CHOICES)  # e.g., 1, 2, 3, 4
    
    class Meta:
        unique_together = ['name', 'year']
        ordering = ['year', 'name']
    
    def __str__(self):
        year_display = dict(self.YEAR_CHOICES).get(self.year, str(self.year))
        return f"{year_display}-{self.name}"
    
    def get_year_display_full(self):
        return dict(self.YEAR_CHOICES).get(self.year, str(self.year))


class Professor(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    employee_id = models.CharField(max_length=20, unique=True)
    department = models.CharField(max_length=100)
    
    def __str__(self):
        return f"{self.user.get_full_name()} ({self.employee_id})"


class Subject(models.Model):
    SUBJECT_TYPES = [
        ('theory', 'Theory'),
        ('practical', 'Practical'),
        ('sat', 'SAT'),
    ]
    
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    subject_type = models.CharField(max_length=20, choices=SUBJECT_TYPES)
    year = models.PositiveIntegerField()
    semester = models.PositiveIntegerField()
    
    class Meta:
        ordering = ['year', 'semester', 'name']
    
    def __str__(self):
        return f"{self.code} - {self.name} ({self.get_subject_type_display()})"


class PracticalBatch(models.Model):
    """Represents a batch within a division (e.g., A1, A2, A3, A4, B1, B2, B3, B4)"""
    name = models.CharField(max_length=10)  # e.g., 'A1', 'A2', 'B1', 'B2'
    division = models.ForeignKey(Division, on_delete=models.CASCADE)
    max_students = models.PositiveIntegerField(default=15)
    
    class Meta:
        unique_together = ['name', 'division']
        ordering = ['division', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.division})"


class PracticalAssignment(models.Model):
    """Assignment of professors to teach practical subjects for specific batches"""
    professor = models.ForeignKey(Professor, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, limit_choices_to={'subject_type': 'practical'})
    batch = models.ForeignKey(PracticalBatch, on_delete=models.CASCADE)
    
    class Meta:
        unique_together = ['professor', 'subject', 'batch']
        ordering = ['batch', 'subject']
    
    def __str__(self):
        return f"{self.professor.user.get_full_name()} - {self.subject.code} ({self.batch})"


class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    roll_number = models.CharField(max_length=20, unique=True)
    division = models.ForeignKey(Division, on_delete=models.CASCADE)
    practical_batch = models.ForeignKey(PracticalBatch, on_delete=models.CASCADE, null=True, blank=True)
    
    def __str__(self):
        return f"{self.roll_number} - {self.user.get_full_name()}"


class TeacherAssignment(models.Model):
    """Assignment of teachers to subjects for theory and SAT classes"""
    professor = models.ForeignKey(Professor, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    division = models.ForeignKey(Division, on_delete=models.CASCADE)
    
    class Meta:
        unique_together = ['professor', 'subject', 'division']
        ordering = ['division', 'subject']
    
    def __str__(self):
        return f"{self.professor} - {self.subject.code} ({self.division})"


class FeedbackForm(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    division = models.ForeignKey(Division, on_delete=models.CASCADE)
    professor = models.ForeignKey(Professor, on_delete=models.CASCADE)
    practical_batch = models.ForeignKey(PracticalBatch, on_delete=models.CASCADE, null=True, blank=True)
    
    # Form settings
    is_active = models.BooleanField(default=True)
    allow_anonymous = models.BooleanField(default=True, help_text="Allow students to submit anonymous feedback")
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_forms')
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        batch_info = f" - {self.practical_batch.name}" if self.practical_batch else ""
        return f"{self.title} - {self.subject.code} ({self.division}){batch_info}"
    
    def clean(self):
        from django.core.exceptions import ValidationError
        
        # If subject is practical, practical_batch must be specified
        if self.subject.subject_type == 'practical' and not self.practical_batch:
            raise ValidationError("Practical batch must be specified for practical subjects")
        
        # If subject is not practical, practical_batch should be None
        if self.subject.subject_type != 'practical' and self.practical_batch:
            raise ValidationError("Practical batch should not be specified for non-practical subjects")
        
        # If practical_batch is specified, ensure it belongs to the same division
        if self.practical_batch and self.practical_batch.division != self.division:
            raise ValidationError("Selected practical batch does not belong to the selected division")


class FeedbackQuestion(models.Model):
    QUESTION_TYPES = [
        ('rating', 'Rating (1-5)'),
        ('text', 'Text Response'),
        ('multiple_choice', 'Multiple Choice (Radio)'),
        ('checkbox', 'Multiple Choice (Checkbox)'),
    ]
    
    form = models.ForeignKey(FeedbackForm, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
    is_required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=1)
    
    # For multiple choice questions
    choices = models.JSONField(blank=True, null=True, help_text="JSON array of choices for multiple choice questions")
    
    class Meta:
        ordering = ['form', 'order']
    
    def __str__(self):
        return f"{self.form.title} - Q{self.order}: {self.question_text[:50]}..."


class FeedbackResponse(models.Model):
    form = models.ForeignKey(FeedbackForm, on_delete=models.CASCADE, related_name='responses')
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_anonymous = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['form', 'student']
        ordering = ['-submitted_at']
    
    def __str__(self):
        return f"{self.student.roll_number} - {self.form.title}"


class FeedbackAnswer(models.Model):
    response = models.ForeignKey(FeedbackResponse, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(FeedbackQuestion, on_delete=models.CASCADE)
    
    # Different answer types
    rating_answer = models.PositiveIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    text_answer = models.TextField(null=True, blank=True)
    choice_answer = models.CharField(max_length=200, null=True, blank=True)  # For single choice (radio)
    checkbox_answer = models.JSONField(null=True, blank=True, help_text="JSON array for multiple checkbox selections")
    
    class Meta:
        unique_together = ['response', 'question']
    
    def __str__(self):
        return f"{self.response.student.roll_number} - {self.question.question_text[:30]}..."
    
    def get_answer(self):
        """Return the appropriate answer based on question type"""
        if self.question.question_type == 'rating':
            return self.rating_answer
        elif self.question.question_type == 'text':
            return self.text_answer
        elif self.question.question_type == 'multiple_choice':
            return self.choice_answer
        elif self.question.question_type == 'checkbox':
            return self.checkbox_answer
        return None
