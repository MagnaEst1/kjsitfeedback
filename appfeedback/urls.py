from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('adminlogin/', views.admin_login_view, name='admin_login'),
    path('a/', views.admin_login_view, name='admin'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    
    # Admin views for feedback management
    path('admin-dashboard/', views.admin_dashboard_view, name='admin_dashboard'),
    path('students-not-filled/', views.students_not_filled_forms_view, name='students_not_filled'),
    path('students-not-filled/export/', views.export_students_not_filled_forms_view, name='export_students_not_filled'),
    path('create-form/', views.create_feedback_form_view, name='create_feedback_form'),
    path('manage-forms/', views.manage_feedback_forms_view, name='manage_feedback_forms'),
    path('stored-exports/', views.stored_exports_view, name='stored_exports'),
    path('stored-exports/upload/', views.upload_stored_export_view, name='upload_stored_export'),
    path('stored-exports/update-title/<int:export_id>/', views.update_stored_export_title_view, name='update_stored_export_title'),
    path('stored-exports/delete/<int:export_id>/', views.delete_stored_export_view, name='delete_stored_export'),
    path('edit-form/<int:form_id>/', views.edit_feedback_form_view, name='edit_feedback_form'),
    path('manage-questions/<int:form_id>/', views.manage_questions_view, name='manage_questions'),
    path('add-question/<int:form_id>/', views.add_question_view, name='add_question'),
    path('edit-question/<int:form_id>/<int:question_id>/', views.edit_question_view, name='edit_question'),
    path('delete-question/<int:form_id>/<int:question_id>/', views.delete_question_view, name='delete_question'),
    path('reorder-questions/<int:form_id>/', views.reorder_questions_view, name='reorder_questions'),
    path('delete-form/<int:form_id>/', views.delete_feedback_form_view, name='delete_feedback_form'),
    path('toggle-form/<int:form_id>/', views.toggle_form_status_view, name='toggle_form_status'),
    path('view-responses/<int:form_id>/', views.view_feedback_responses, name='view_feedback_responses'),
    path('delete-response/<int:form_id>/<int:response_id>/', views.delete_feedback_response, name='delete_feedback_response'),
    path('bulk-delete-responses/<int:form_id>/', views.bulk_delete_responses, name='bulk_delete_responses'),
    path('clear-all-responses/', views.clear_all_responses_view, name='clear_all_responses'),
    path('export-responses/<int:form_id>/', views.export_responses, name='export_responses'),
    path('export-all-responses/', views.export_all_responses, name='export_all_responses'),
    path('send-faculty-mails/', views.send_faculty_mails_view, name='send_faculty_mails'),
    path('clear-data/', views.clear_data_view, name='clear_data'),
    path('bulk-generate-forms/', views.bulk_generate_forms_page, name='bulk_generate_forms_page'),
    path('bulk-generate-feedback-forms/', views.bulk_generate_feedback_forms, name='bulk_generate_feedback_forms'),
    
    # Student views
    path('fill-feedback/<int:form_id>/', views.fill_feedback_form_view, name='fill_feedback_form'),
    path('select-electives/', views.select_electives_view, name='select_electives'),
    # path('feedback-completed/<int:form_id>/', views.feedback_completed_view, name='feedback_completed'),  # Disabled - auto redirect now
    
    # Professor views
    path('professor-dashboard/', views.professor_dashboard_view, name='professor_dashboard'),
    
    # AJAX endpoints
    path('ajax/get-subjects/', views.get_subjects_by_type, name='get_subjects_by_type'),
    path('ajax/get-professors/', views.get_professors_by_subject_division, name='get_professors_by_subject_division'),
    path('ajax/get-batches/', views.get_batches_by_division, name='get_batches_by_division'),
    path('ajax/get-default-questions/', views.get_default_questions_by_subject_type, name='get_default_questions_by_subject_type'),
    path('ajax/update-question/<int:form_id>/<int:question_id>/', views.update_question_ajax, name='update_question_ajax'),
    path('ajax/delete-question/<int:form_id>/<int:question_id>/', views.delete_question_ajax, name='delete_question_ajax'),
    
    # Import data endpoints
    path('import-data/', views.import_data_view, name='import_data'),
    path('download-professor-template/', views.download_professor_template, name='download_professor_template'),
    path('download-student-template/', views.download_student_template, name='download_student_template'),
    path('download-subject-template/', views.download_subject_template, name='download_subject_template'),
    path('download-assignment-template/', views.download_assignment_template, name='download_assignment_template'),
    path('download-theory-assignment-template/', views.download_theory_assignment_template, name='download_theory_assignment_template'),
    path('import-professors/', views.import_professors, name='import_professors'),
    path('import-students/', views.import_students, name='import_students'),
    path('import-subjects/', views.import_subjects, name='import_subjects'),
    path('import-assignments/', views.import_assignments, name='import_assignments'),
    path('import-theory-assignments/', views.import_theory_assignments, name='import_theory_assignments'),
]
