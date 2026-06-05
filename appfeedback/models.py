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
    employee_id = models.CharField(max_length=100, unique=True)
    department = models.CharField(max_length=100)
    
    def __str__(self):
        return f"{self.user.get_full_name()} ({self.employee_id})"


class Subject(models.Model):
    SUBJECT_TYPES = [
        ('theory', 'Theory'),
        ('practical', 'Practical'),
        ('tutorials', 'Tutorials'),
    ]
    
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    subject_type = models.CharField(max_length=20, choices=SUBJECT_TYPES)
    semester = models.PositiveIntegerField()
    elective = models.PositiveIntegerField(null=True, blank=True, help_text="Elective group number (e.g., 1, 2, 3). Leave blank for non-elective subjects.")
    
    class Meta:
        ordering = ['semester', 'name']
    
    @property
    def year(self):
        """Calculate year from semester (1-2 = year 1, 3-4 = year 2, etc.)"""
        return ((self.semester - 1) // 2) + 1
    
    @property
    def is_elective(self):
        """Check if this subject is an elective"""
        return self.elective is not None
    
    def __str__(self):
        elective_info = f" [Elective {self.elective}]" if self.is_elective else ""
        return f"{self.code} - {self.name} ({self.get_subject_type_display()}){elective_info}"  # type: ignore


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
    """Assignment of professors to teach practical and tutorial subjects for specific batches"""
    professor = models.ForeignKey(Professor, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, limit_choices_to={'subject_type__in': ['practical', 'tutorials']})
    batch = models.ForeignKey(PracticalBatch, on_delete=models.CASCADE)
    semester = models.PositiveIntegerField(help_text="Semester number (1-8)", default=1)
    
    class Meta:
        unique_together = ['professor', 'subject', 'batch', 'semester']
        ordering = ['batch', 'subject', 'semester']
    
    def __str__(self):
        return f"{self.professor.user.get_full_name()} - {self.subject.code} ({self.batch}) - Sem {self.semester}"
    
    def clean(self):
        # Validation removed - professors can now be assigned to multiple batches
        pass
    
    def save(self, *args, **kwargs):
        # Skip validation for now
        super().save(*args, **kwargs)


class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    roll_number = models.CharField(max_length=20, unique=True)
    semester = models.PositiveIntegerField(default=1, help_text="Semester number (1-8)")
    division = models.ForeignKey(Division, on_delete=models.CASCADE)
    practical_batch = models.ForeignKey(PracticalBatch, on_delete=models.CASCADE, null=True, blank=True)
    department = models.CharField(max_length=100, default='Computer Engineering')
    
    @property
    def year(self):
        """Calculate year from semester (1-2 = year 1, 3-4 = year 2, etc.)"""
        return ((self.semester - 1) // 2) + 1
    
    def __str__(self):
        return f"{self.roll_number} - {self.user.get_full_name()} (Sem {self.semester}, {self.department})"


class StudentElectiveSelection(models.Model):
    """Track student selections for elective subjects"""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='elective_selections')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, limit_choices_to={'elective__isnull': False})
    elective_group = models.PositiveIntegerField(help_text="Elective group number (matches Subject.elective)")
    semester = models.PositiveIntegerField(help_text="Semester when the elective was chosen")
    selected_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['student', 'elective_group', 'semester']
        ordering = ['student', 'semester', 'elective_group']
    
    def __str__(self):
        return f"{self.student.roll_number} - Elective {self.elective_group}: {self.subject.code}"
    
    def clean(self):
        from django.core.exceptions import ValidationError
        
        # Validate that the subject's elective field matches the elective_group
        if self.subject.elective != self.elective_group:
            raise ValidationError(f"Subject {self.subject.code} does not belong to elective group {self.elective_group}")
        
        # Validate that the subject's semester matches the student's semester
        if self.subject.semester != self.semester:
            raise ValidationError(f"Subject {self.subject.code} is for semester {self.subject.semester}, not semester {self.semester}")


class TeacherAssignment(models.Model):
    """Assignment of teachers to subjects for theory classes"""
    professor = models.ForeignKey(Professor, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    division = models.ForeignKey(Division, on_delete=models.CASCADE)
    semester = models.PositiveIntegerField(help_text="Semester number (1-8)",default=1)
    
    class Meta:
        unique_together = ['professor', 'subject', 'division', 'semester']
        ordering = ['division', 'subject', 'semester']
    
    def __str__(self):
        return f"{self.professor} - {self.subject.code} ({self.division}) - Sem {self.semester}"
    
    def clean(self):
        # Validation removed - professors can now be assigned to multiple divisions
        pass
    
    def save(self, *args, **kwargs):
        # Skip validation for now
        super().save(*args, **kwargs)


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
        
        # If subject is practical or tutorials, practical_batch must be specified
        if self.subject.subject_type in ['practical', 'tutorials'] and not self.practical_batch:
            raise ValidationError("Practical batch must be specified for practical and tutorial subjects")
        
        # If subject is theory, practical_batch should be None
        if self.subject.subject_type == 'theory' and self.practical_batch:
            raise ValidationError("Practical batch should not be specified for theory subjects")
        
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


class StoredExport(models.Model):
    """Admin-uploaded archive of previously exported feedback files."""
    title = models.CharField(max_length=255)
    export_file = models.FileField(upload_to='stored_exports/%Y/%m/%d/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.title


class UserMailSetup(models.Model):
    """Stores Gmail SMTP settings (address & app password) remembered per user"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='mail_setup')
    gmail_address = models.EmailField()
    app_password = models.CharField(max_length=255)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Mail Setup for {self.user.username} ({self.gmail_address})"

