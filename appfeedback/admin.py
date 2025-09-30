from django.contrib import admin
from .models import (
    Division, Professor, Subject, PracticalBatch, PracticalAssignment, Student, 
    TeacherAssignment, FeedbackForm, FeedbackQuestion, 
    FeedbackResponse, FeedbackAnswer
)


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ['name', 'year']
    list_filter = ['year']
    ordering = ['year', 'name']


@admin.register(Professor)
class ProfessorAdmin(admin.ModelAdmin):
    list_display = ['get_full_name', 'get_username', 'employee_id', 'department']
    search_fields = ['user__first_name', 'user__last_name', 'employee_id', 'user__username']
    list_filter = ['department']
    
    def get_full_name(self, obj):
        return obj.user.get_full_name()
    get_full_name.short_description = 'Full Name'
    
    def get_username(self, obj):
        return obj.user.username
    get_username.short_description = 'Username'


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'subject_type', 'get_year', 'semester']
    list_filter = ['subject_type', 'semester']
    search_fields = ['name', 'code']
    ordering = ['semester', 'name']
    
    def get_year(self, obj):
        return obj.year
    get_year.short_description = 'Year'


@admin.register(PracticalBatch)
class PracticalBatchAdmin(admin.ModelAdmin):
    list_display = ['name', 'division', 'max_students']
    list_filter = ['division__year', 'division__name']
    search_fields = ['name']
    ordering = ['division', 'name']


@admin.register(PracticalAssignment)
class PracticalAssignmentAdmin(admin.ModelAdmin):
    list_display = ['professor', 'subject', 'batch', 'semester']
    list_filter = ['subject', 'batch__division__year', 'semester']
    search_fields = ['professor__user__first_name', 'professor__user__last_name', 'subject__name']


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['roll_number', 'user', 'get_year', 'semester', 'division', 'practical_batch', 'department']
    search_fields = ['roll_number', 'user__first_name', 'user__last_name', 'department']
    list_filter = ['semester', 'division__name', 'practical_batch', 'department']
    
    def get_year(self, obj):
        return obj.year
    get_year.short_description = 'Year'


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ['professor', 'subject', 'division', 'semester']
    list_filter = ['subject__subject_type', 'division__year', 'semester']
    search_fields = ['professor__user__first_name', 'professor__user__last_name', 'subject__name']


class FeedbackQuestionInline(admin.TabularInline):
    model = FeedbackQuestion
    extra = 1
    ordering = ['order']


@admin.register(FeedbackForm)
class FeedbackFormAdmin(admin.ModelAdmin):
    list_display = ['title', 'subject', 'division', 'professor', 'practical_batch', 'is_active', 'start_date', 'end_date']
    list_filter = ['is_active', 'subject__subject_type', 'division__year', 'start_date']
    search_fields = ['title', 'subject__name', 'professor__user__first_name']
    inlines = [FeedbackQuestionInline]
    readonly_fields = ['created_at', 'created_by']
    
    def save_model(self, request, obj, form, change):
        if not change:  # Only set created_by when creating new form
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(FeedbackQuestion)
class FeedbackQuestionAdmin(admin.ModelAdmin):
    list_display = ['form', 'question_text', 'question_type', 'is_required', 'order']
    list_filter = ['question_type', 'is_required']
    search_fields = ['question_text', 'form__title']


class FeedbackAnswerInline(admin.TabularInline):
    model = FeedbackAnswer
    extra = 0
    readonly_fields = ['question', 'rating_answer', 'text_answer', 'choice_answer']


@admin.register(FeedbackResponse)
class FeedbackResponseAdmin(admin.ModelAdmin):
    list_display = ['student', 'form', 'submitted_at', 'is_anonymous']
    list_filter = ['is_anonymous', 'submitted_at', 'form__subject__subject_type']
    search_fields = ['student__roll_number', 'form__title']
    readonly_fields = ['submitted_at']
    inlines = [FeedbackAnswerInline]


@admin.register(FeedbackAnswer)
class FeedbackAnswerAdmin(admin.ModelAdmin):
    list_display = ['response', 'question', 'get_answer']
    list_filter = ['question__question_type']
    search_fields = ['response__student__roll_number', 'question__question_text']
