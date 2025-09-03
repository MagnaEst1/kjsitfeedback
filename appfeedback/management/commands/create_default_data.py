from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.conf import settings
from appfeedback.models import Division, Subject, Professor, PracticalBatch, PracticalAssignment, TeacherAssignment
import os


class Command(BaseCommand):
    help = 'Create default divisions, subjects, professors, and practical batches'

    def handle(self, *args, **options):
        self.stdout.write('Creating default data...')
        
        # Create divisions for years 1-4 with A and B divisions
        divisions_created = 0
        for year in range(1, 5):  # Years 1, 2, 3, 4
            for div_name in ['A', 'B']:
                division, created = Division.objects.get_or_create(
                    name=div_name,
                    year=year
                )
                if created:
                    divisions_created += 1
                    self.stdout.write(f'Created division: {division}')
        
        self.stdout.write(f'Created {divisions_created} new divisions')
        
        # Create some default subjects
        subjects_data = [
            # Year 1 subjects
            {'name': 'Engineering Mathematics I', 'code': 'EM1', 'type': 'theory', 'year': 1, 'semester': 1},
            {'name': 'Engineering Physics', 'code': 'EP', 'type': 'theory', 'year': 1, 'semester': 1},
            {'name': 'Engineering Chemistry', 'code': 'EC', 'type': 'theory', 'year': 1, 'semester': 1},
            {'name': 'Basic Electronics Engineering', 'code': 'BEE', 'type': 'theory', 'year': 1, 'semester': 1},
            {'name': 'Physics Lab', 'code': 'PL', 'type': 'practical', 'year': 1, 'semester': 1},
            {'name': 'Chemistry Lab', 'code': 'CL', 'type': 'practical', 'year': 1, 'semester': 1},
            {'name': 'Programming Lab', 'code': 'PROG', 'type': 'practical', 'year': 1, 'semester': 1},
            
            # Year 2 subjects
            {'name': 'Data Structures', 'code': 'DS', 'type': 'theory', 'year': 2, 'semester': 3},
            {'name': 'Computer Networks', 'code': 'CN', 'type': 'theory', 'year': 2, 'semester': 3},
            {'name': 'Database Management Systems', 'code': 'DBMS', 'type': 'theory', 'year': 2, 'semester': 3},
            {'name': 'Data Structures Lab', 'code': 'DSL', 'type': 'practical', 'year': 2, 'semester': 3},
            {'name': 'DBMS Lab', 'code': 'DBMSL', 'type': 'practical', 'year': 2, 'semester': 3},
            
            # Year 3 subjects
            {'name': 'Software Engineering', 'code': 'SE', 'type': 'theory', 'year': 3, 'semester': 5},
            {'name': 'Web Technology', 'code': 'WT', 'type': 'theory', 'year': 3, 'semester': 5},
            {'name': 'Machine Learning', 'code': 'ML', 'type': 'theory', 'year': 3, 'semester': 5},
            {'name': 'Web Technology Lab', 'code': 'WTL', 'type': 'practical', 'year': 3, 'semester': 5},
            {'name': 'ML Lab', 'code': 'MLL', 'type': 'practical', 'year': 3, 'semester': 5},
            
            # Year 4 subjects
            {'name': 'Distributed Systems', 'code': 'DIST', 'type': 'theory', 'year': 4, 'semester': 7},
            {'name': 'Cloud Computing', 'code': 'CC', 'type': 'theory', 'year': 4, 'semester': 7},
            {'name': 'Project Lab', 'code': 'PROJ', 'type': 'practical', 'year': 4, 'semester': 7},
            
            # Tutorial subjects for all years
            {'name': 'Soft Skills Development', 'code': 'SSD', 'type': 'tutorials', 'year': 1, 'semester': 1},
            {'name': 'Professional Ethics', 'code': 'PE', 'type': 'tutorials', 'year': 2, 'semester': 3},
            {'name': 'Communication Skills', 'code': 'CS', 'type': 'tutorials', 'year': 3, 'semester': 5},
            {'name': 'Industry Readiness', 'code': 'IR', 'type': 'tutorials', 'year': 4, 'semester': 7},
        ]
        
        subjects_created = 0
        for subject_data in subjects_data:
            subject, created = Subject.objects.get_or_create(
                code=subject_data['code'],
                defaults={
                    'name': subject_data['name'],
                    'subject_type': subject_data['type'],
                    'year': subject_data['year'],
                    'semester': subject_data['semester']
                }
            )
            if created:
                subjects_created += 1
                self.stdout.write(f'Created subject: {subject}')
        
        self.stdout.write(f'Created {subjects_created} new subjects')
        
        # Create some default professors
        professors_data = [
            {'first_name': 'Dr. Rajesh', 'last_name': 'Kumar', 'email': 'rajesh.kumar@kjsit.edu.in', 'emp_id': 'EMP001', 'dept': 'Computer Engineering'},
            {'first_name': 'Prof. Priya', 'last_name': 'Sharma', 'email': 'priya.sharma@kjsit.edu.in', 'emp_id': 'EMP002', 'dept': 'Computer Engineering'},
            {'first_name': 'Dr. Amit', 'last_name': 'Patel', 'email': 'amit.patel@kjsit.edu.in', 'emp_id': 'EMP003', 'dept': 'Information Technology'},
            {'first_name': 'Prof. Sunita', 'last_name': 'Joshi', 'email': 'sunita.joshi@kjsit.edu.in', 'emp_id': 'EMP004', 'dept': 'Computer Engineering'},
            {'first_name': 'Dr. Vikram', 'last_name': 'Singh', 'email': 'vikram.singh@kjsit.edu.in', 'emp_id': 'EMP005', 'dept': 'Information Technology'},
            {'first_name': 'Prof. Kavita', 'last_name': 'Mehta', 'email': 'kavita.mehta@kjsit.edu.in', 'emp_id': 'EMP006', 'dept': 'Computer Engineering'},
            {'first_name': 'Dr. Sandeep', 'last_name': 'Gupta', 'email': 'sandeep.gupta@kjsit.edu.in', 'emp_id': 'EMP007', 'dept': 'Electronics Engineering'},
            {'first_name': 'Prof. Neha', 'last_name': 'Agarwal', 'email': 'neha.agarwal@kjsit.edu.in', 'emp_id': 'EMP008', 'dept': 'Computer Engineering'},
        ]
        
        professors_created = 0
        for prof_data in professors_data:
            # Create user first
            user, user_created = User.objects.get_or_create(
                username=prof_data['email'],
                defaults={
                    'email': prof_data['email'],
                    'first_name': prof_data['first_name'],
                    'last_name': prof_data['last_name'],
                    'is_staff': True  # Professors can access admin
                }
            )
            
            # Create professor profile
            professor, prof_created = Professor.objects.get_or_create(
                employee_id=prof_data['emp_id'],
                defaults={
                    'user': user,
                    'department': prof_data['dept']
                }
            )
            
            if prof_created:
                professors_created += 1
                self.stdout.write(f'Created professor: {professor}')
        
        self.stdout.write(f'Created {professors_created} new professors')
        
        # Create practical batches (A1, A2, A3, A4, B1, B2, B3, B4) for each division
        batches_created = 0
        
        for division in Division.objects.all():
            for batch_num in range(1, 5):  # 1, 2, 3, 4
                batch_name = f"{division.name}{batch_num}"
                
                batch, created = PracticalBatch.objects.get_or_create(
                    name=batch_name,
                    division=division,
                    defaults={
                        'max_students': 15  # Default 15 students per batch
                    }
                )
                
                if created:
                    batches_created += 1
                    self.stdout.write(f'Created practical batch: {batch}')
        
        self.stdout.write(f'Created {batches_created} new practical batches')
        
        # Create practical assignments (professor-subject-batch mappings)
        # Each practical subject gets ONE professor per batch
        assignments_created = 0
        practical_subjects = Subject.objects.filter(subject_type='practical')
        professors = list(Professor.objects.all())
        
        if professors:
            professor_index = 0
            for subject in practical_subjects:
                # Get batches for the same year as the subject
                year_batches = PracticalBatch.objects.filter(division__year=subject.year)
                
                # Assign ONE professor to this subject for all batches
                assigned_professor = professors[professor_index % len(professors)]
                professor_index += 1
                
                for batch in year_batches:
                    assignment, created = PracticalAssignment.objects.get_or_create(
                        professor=assigned_professor,
                        subject=subject,
                        batch=batch
                    )
                    
                    if created:
                        assignments_created += 1
                        self.stdout.write(f'Created practical assignment: {assignment}')
        
        self.stdout.write(f'Created {assignments_created} new practical assignments')
        
        # Create teacher assignments for theory and tutorial subjects
        # Each theory/tutorial subject gets ONE professor per division
        teacher_assignments_created = 0
        theory_subjects = Subject.objects.filter(subject_type='theory')
        
        if professors:
            professor_index = 0
            for subject in theory_subjects:
                # Get divisions for the same year as the subject
                year_divisions = Division.objects.filter(year=subject.year)
                
                # Assign ONE professor to this subject for all divisions of that year
                assigned_professor = professors[professor_index % len(professors)]
                professor_index += 1
                
                for division in year_divisions:
                    assignment, created = TeacherAssignment.objects.get_or_create(
                        professor=assigned_professor,
                        subject=subject,
                        division=division
                    )
                    
                    if created:
                        teacher_assignments_created += 1
                        self.stdout.write(f'Created teacher assignment: {assignment}')
        
        self.stdout.write(f'Created {teacher_assignments_created} new teacher assignments')
        
        # Create practical assignments for tutorial subjects (similar to practical subjects)
        # Each tutorial subject gets ONE professor per batch
        tutorial_assignments_created = 0
        tutorial_subjects = Subject.objects.filter(subject_type='tutorials')
        
        if professors:
            professor_index = 0
            for subject in tutorial_subjects:
                # Get batches for the same year as the subject
                year_batches = PracticalBatch.objects.filter(division__year=subject.year)
                
                # Assign ONE professor to this subject for all batches
                assigned_professor = professors[professor_index % len(professors)]
                professor_index += 1
                
                for batch in year_batches:
                    assignment, created = PracticalAssignment.objects.get_or_create(
                        professor=assigned_professor,
                        subject=subject,
                        batch=batch
                    )
                    
                    if created:
                        tutorial_assignments_created += 1
                        self.stdout.write(f'Created tutorial assignment: {assignment}')
        
        self.stdout.write(f'Created {tutorial_assignments_created} new tutorial assignments')
        
        # Create a demo student
        student_user, created = User.objects.get_or_create(
            username='student001',
            defaults={
                'email': 'student001@somaiya.edu',
                'first_name': 'Demo',
                'last_name': 'Student',
                'is_staff': False
            }
        )
        
        if created:
            from appfeedback.models import Student
            # Get first year A division
            first_year_a = Division.objects.filter(year=1, name='A').first()
            if first_year_a:
                # Get A1 batch for this division
                a1_batch = PracticalBatch.objects.filter(division=first_year_a, name='A1').first()
                
                student, student_created = Student.objects.get_or_create(
                    user=student_user,
                    defaults={
                        'roll_number': '2024A001',
                        'division': first_year_a,
                        'practical_batch': a1_batch
                    }
                )
                
                if student_created:
                    self.stdout.write(f'Created demo student: {student}')
        
        # Create admin user if it doesn't exist
        admin_user, admin_created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@somaiya.edu',
                'first_name': 'Administrator',
                'last_name': '',
                'is_staff': True,
                'is_superuser': True
            }
        )
        
        if admin_created:
            admin_user.set_password('Pass123@')  # Set a default password
            admin_user.save()
            self.stdout.write('Created admin user (username: admin, password: Pass123@)')
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\nDefault data creation completed!\n'
                f'- Divisions: {Division.objects.count()}\n'
                f'- Subjects: {Subject.objects.count()}\n'
                f'- Professors: {Professor.objects.count()}\n'
                f'- Practical Batches: {PracticalBatch.objects.count()}\n'
                f'- Practical Assignments: {PracticalAssignment.objects.count()}\n'
                f'- Teacher Assignments: {TeacherAssignment.objects.count()}\n'
                f'- Users: {User.objects.count()}\n'
            )
        )
        
        self.stdout.write(
            self.style.WARNING(
                '\nDemo accounts created:\n'
                '- Admin: username=admin, password=Pass123@\n'
                '- Student: username=student001, password=(use Django admin to set)\n'
                '- Professors: Use Django admin to set passwords\n'
            )
        )
