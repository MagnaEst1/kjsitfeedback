from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from io import BytesIO
from openpyxl import load_workbook
from appfeedback.models import (
    Division, Professor, Subject, FeedbackForm, FeedbackQuestion, 
    Student, FeedbackResponse, FeedbackAnswer, PracticalBatch
)

class ExcelExportTestCase(TestCase):
    def setUp(self):
        # Create a staff user to access the export view
        self.user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='password123'
        )
        self.client.login(username='admin', password='password123')

        # Create basic Django models required for feedback form
        self.division = Division.objects.create(name='A', year=3)
        self.professor_user = User.objects.create_user(
            username='prof',
            first_name='Professor',
            last_name='Test',
            email='prof@example.com'
        )
        self.professor = Professor.objects.create(
            user=self.professor_user,
            employee_id='EMP123',
            department='Computer Engineering'
        )
        self.subject = Subject.objects.create(
            name='Software Engineering',
            code='CS301',
            subject_type='theory',
            semester=5
        )
        self.form = FeedbackForm.objects.create(
            title='Course Exit Survey',
            subject=self.subject,
            division=self.division,
            professor=self.professor,
            is_active=True,
            allow_anonymous=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timezone.timedelta(days=7),
            created_by=self.user
        )
        
        # Create 2 rating questions
        self.q1 = FeedbackQuestion.objects.create(
            form=self.form,
            question_text='How is the teaching quality?',
            question_type='rating',
            order=1
        )
        self.q2 = FeedbackQuestion.objects.create(
            form=self.form,
            question_text='How is the course content?',
            question_type='rating',
            order=2
        )

        # Create student and response
        self.student_user = User.objects.create_user(
            username='student',
            first_name='Student',
            last_name='One'
        )
        self.student = Student.objects.create(
            user=self.student_user,
            roll_number='101',
            semester=5,
            division=self.division
        )
        self.response = FeedbackResponse.objects.create(
            form=self.form,
            student=self.student,
            is_anonymous=False
        )
        FeedbackAnswer.objects.create(
            response=self.response,
            question=self.q1,
            rating_answer=4
        )
        FeedbackAnswer.objects.create(
            response=self.response,
            question=self.q2,
            rating_answer=5
        )

    def test_export_responses_layout(self):
        url = reverse('export_responses', args=[self.form.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        # Load the generated workbook
        wb = load_workbook(BytesIO(response.content))
        self.assertIn("Student Responses", wb.sheetnames)
        self.assertIn("Rating Summary", wb.sheetnames)

        ws1 = wb["Student Responses"]
        ws2 = wb["Rating Summary"]

        # Check ws1 print area and layout rules
        self.assertTrue(bool(ws1.print_area))
        self.assertIn("$B$1", ws1.print_area)
        # In ws1, info table label columns B-D are merged. Top-left cell is B.
        # Check that cells are indeed merged.
        merged_ranges_ws1 = [r.coord for r in ws1.merged_cells.ranges]
        # In openpyxl, merged cells coords are e.g. "B3:D3"
        # Since info starts at row 3 (after title Feedback Response Report at row 1, row 2 is blank), 
        # let's assert that merged cells containing columns B to D exist for the info rows.
        b_d_merges_found = 0
        e_merges_found = 0
        for r in merged_ranges_ws1:
            if r.startswith("B") and r.endswith("3") or r.endswith("4") or r.endswith("5"):
                if "D" in r:
                    b_d_merges_found += 1
            if r.startswith("E") and (r.endswith("3") or r.endswith("4") or r.endswith("5")):
                e_merges_found += 1
        
        self.assertTrue(b_d_merges_found >= 1, "Expected columns B-D to be merged for info labels.")
        self.assertTrue(e_merges_found >= 1, "Expected column E to be merged to the end column for values.")

        # Check ws2 (Rating Summary) print area and layout rules
        self.assertTrue(bool(ws2.print_area))
        self.assertIn("$B$1", ws2.print_area)
        
        # Verify that ws2 title 'Rating Statistics Summary' is merged starting from column B (any row)
        # since rows 1-3 are now the logo/institute header block
        merged_ranges_ws2 = [r.coord for r in ws2.merged_cells.ranges]
        title_merge_found = False
        info_b_d_merges_ws2 = 0
        info_e_merges_ws2 = 0
        
        for r in merged_ranges_ws2:
            if r.startswith("B"):
                # Check the cell value for title
                row_num = int(''.join(c for c in r.split(":")[0] if c.isdigit()))
                if ws2.cell(row=row_num, column=2).value == "Rating Statistics Summary":
                    title_merge_found = True
            if r.startswith("B") and ("D" in r):
                row_num = int(''.join(c for c in r.split(":")[0] if c.isdigit()))
                if row_num > 4:  # skip logo/title rows at top
                    info_b_d_merges_ws2 += 1
            if r.startswith("E"):
                row_num = int(''.join(c for c in r.split(":")[0] if c.isdigit()))
                if row_num > 4:
                    info_e_merges_ws2 += 1

        self.assertTrue(title_merge_found, "Expected ws2 title 'Rating Statistics Summary' to be merged starting from column B.")
        self.assertTrue(info_b_d_merges_ws2 >= 1, "Expected columns B-D to be merged for info labels in ws2.")
        self.assertTrue(info_e_merges_ws2 >= 1, "Expected column E to be merged for info values in ws2.")

        # Verify that ws2 has rating columns starting at column B (column 2)
        # In ws2: 'Rating' label, Q1, Q2, Total should start at column B (2)
        # The rating headers start at some row, let's find the row that contains 'Rating'
        found_rating_header = False
        for row in range(1, 60):
            if ws2.cell(row=row, column=2).value == 'Rating':
                found_rating_header = True
                self.assertEqual(ws2.cell(row=row, column=3).value, 'Q1')
                self.assertEqual(ws2.cell(row=row, column=4).value, 'Q2')
                self.assertEqual(ws2.cell(row=row, column=5).value, 'Total')
                break
        self.assertTrue(found_rating_header, "Rating table header was not found starting at column B in ws2.")

        # Assert column A cells have no background fill
        for row in range(1, 15):
            self.assertTrue(
                ws1.cell(row=row, column=1).fill.fill_type is None or
                ws1.cell(row=row, column=1).fill.start_color.rgb == '00000000',
                f"Expected column A in ws1 row {row} to have no background fill color."
            )
            self.assertTrue(
                ws2.cell(row=row, column=1).fill.fill_type is None or
                ws2.cell(row=row, column=1).fill.start_color.rgb == '00000000',
                f"Expected column A in ws2 row {row} to have no background fill color."
            )

        # Assert ws1 Question List themed table merges and colors
        legend_header_found = False
        legend_q1_found = False
        for r in merged_ranges_ws1:
            start_cell = r.split(":")[0]
            end_cell = r.split(":")[1]
            if start_cell.startswith("B") and end_cell.startswith("D"):
                row_num = int(start_cell[1:])
                if row_num > 8:
                    val = ws1.cell(row=row_num, column=2).value
                    if val == "Q. No.":
                        legend_header_found = True
                        # Verify the legend header fill color is red (a50c22)
                        self.assertEqual(ws1.cell(row=row_num, column=2).fill.start_color.rgb, "00a50c22")
                    elif val == "Q1":
                        legend_q1_found = True

        self.assertTrue(legend_header_found, "Expected legend header 'Q. No.' to be merged across columns B-D.")
        self.assertTrue(legend_q1_found, "Expected question 'Q1' to be merged across columns B-D in Question List table.")

        # Assert ws2 Overall Percentage row merges and left alignment
        percent_row_merge_found = False
        for r in merged_ranges_ws2:
            start_cell = r.split(":")[0]
            end_cell = r.split(":")[1]
            if start_cell.startswith("B") and end_cell.startswith("D"):
                row_num = int(start_cell[1:])
                lbl_cell = ws2.cell(row=row_num, column=2)
                if lbl_cell.value == "Overall Percentage (%)":
                    percent_row_merge_found = True
                    # Check left-alignment
                    self.assertEqual(lbl_cell.alignment.horizontal, 'left')
                    # Check that the last column has the percentage value
                    self.assertIn("%", str(ws2.cell(row=row_num, column=5).value))
                    break
        self.assertTrue(percent_row_merge_found, "Expected 'Overall Percentage (%)' row to be merged from B to D.")

        # Assert that the Average Rating row on ws2 is inside the print area
        found_average_row = False
        for row in range(1, 40):
            if ws2.cell(row=row, column=2).value == 'Average Rating':
                found_average_row = True
                # The print area should cover up to this row number or beyond
                # print_area format: "B1:[Col][EndRow]"
                # So we extract the row number from the end of the print_area string
                end_row = int(''.join(c for c in ws2.print_area.split(":")[-1] if c.isdigit()))
                self.assertGreaterEqual(end_row, row, f"Expected print area end row ({end_row}) to cover average rating row ({row})")
                break
        self.assertTrue(found_average_row, "Expected to find 'Average Rating' row on ws2.")

        # Assert ws2 print orientation is Portrait
        self.assertEqual(ws2.page_setup.orientation, ws2.ORIENTATION_PORTRAIT)

        # Assert signature blocks are present on the right-hand side (column 4 for ws1/ws2, column 6 for ws3)
        found_sig_ws1 = False
        for row in range(1, 100):
            if ws1.cell(row=row, column=4).value == "_________________________":
                found_sig_ws1 = True
                self.assertEqual(ws1.cell(row=row + 1, column=4).value, "Signature of Faculty")
                self.assertEqual(ws1.cell(row=row + 2, column=4).value, "(Professor Test)")
                # Ensure it is covered in the print area
                end_row = int(''.join(c for c in ws1.print_area.split(":")[-1] if c.isdigit()))
                self.assertGreaterEqual(end_row, row + 2)
                break
        self.assertTrue(found_sig_ws1, "Expected to find Signature of Faculty block on ws1 right side.")

        found_sig_ws2 = False
        for row in range(1, 100):
            if ws2.cell(row=row, column=4).value == "_________________________":
                found_sig_ws2 = True
                self.assertEqual(ws2.cell(row=row + 1, column=4).value, "Signature of Faculty")
                self.assertEqual(ws2.cell(row=row + 2, column=4).value, "(Professor Test)")
                # Ensure it is covered in the print area
                end_row = int(''.join(c for c in ws2.print_area.split(":")[-1] if c.isdigit()))
                self.assertGreaterEqual(end_row, row + 2)
                break
        self.assertTrue(found_sig_ws2, "Expected to find Signature of Faculty block on ws2 right side.")

        # In the test we created questions of type rating, so ws3 was created
        ws3 = wb["Question Rating Charts"]
        found_sig_ws3 = False
        for row in range(1, 200):
            if ws3.cell(row=row, column=5).value == "_________________________":
                found_sig_ws3 = True
                self.assertEqual(ws3.cell(row=row + 1, column=5).value, "Signature of Faculty")
                self.assertEqual(ws3.cell(row=row + 2, column=5).value, "(Professor Test)")
                break
        self.assertTrue(found_sig_ws3, "Expected to find Signature of Faculty block on ws3 right side.")

    def test_export_all_responses_zip(self):
        import zipfile
        
        # Create practical batch
        practical_batch = PracticalBatch.objects.create(name='A1', division=self.division)
        
        # Create a practical subject
        practical_subject = Subject.objects.create(
            name='Operating System Lab',
            code='CS302',
            subject_type='practical',
            semester=5
        )
        
        # Create a practical feedback form
        practical_form = FeedbackForm.objects.create(
            title='OS Lab Practical Exit Survey',
            subject=practical_subject,
            division=self.division,
            professor=self.professor,
            practical_batch=practical_batch,
            is_active=True,
            allow_anonymous=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timezone.timedelta(days=7),
            created_by=self.user
        )
        
        # Create a student and a response for the practical form (so it gets exported)
        student_user_2 = User.objects.create_user(
            username='student2',
            first_name='Student',
            last_name='Two'
        )
        student_2 = Student.objects.create(
            user=student_user_2,
            roll_number='102',
            semester=5,
            division=self.division,
            practical_batch=practical_batch
        )
        response_2 = FeedbackResponse.objects.create(
            form=practical_form,
            student=student_2,
            is_anonymous=False
        )
        
        # Also need a rating answer to generate the sheet without error
        FeedbackAnswer.objects.create(
            response=response_2,
            question=self.q1,
            rating_answer=4
        )

        url = reverse('export_all_responses')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')

        # Load the generated ZIP and verify filenames
        with zipfile.ZipFile(BytesIO(response.content)) as zf:
            filenames = zf.namelist()
            # The folder path is: Practical/Feedback 1/{division}/
            expected_filename = (
                "Practical/Feedback 1/"
                f"{self.division}/"
                f"Operating System Lab_Professor Test_Practical_A1.xlsx"
            )
            self.assertIn(expected_filename, filenames)

    def test_send_faculty_mails(self):
        from unittest.mock import patch, MagicMock
        from appfeedback.models import UserMailSetup
        
        # Set email for professor user
        self.professor_user.email = 'prof@example.com'
        self.professor_user.save()
        
        with patch('django.core.mail.get_connection') as mock_get_connection:
            mock_conn = MagicMock()
            mock_get_connection.return_value = mock_conn
            
            url = reverse('send_faculty_mails')
            post_data = {
                'gmail_address': 'testadmin@gmail.com',
                'app_password': 'abcd efgh ijkl mnop'
            }
            
            response = self.client.post(url, post_data)
            
            self.assertEqual(response.status_code, 302)
            self.assertRedirects(response, reverse('manage_feedback_forms'))
            
            # Verify UserMailSetup is saved
            setup = UserMailSetup.objects.get(user=self.user)
            self.assertEqual(setup.gmail_address, 'testadmin@gmail.com')
            self.assertEqual(setup.app_password, 'abcd efgh ijkl mnop')
            
            # Verify connection was opened and closed
            mock_conn.open.assert_called_once()
            mock_conn.close.assert_called_once()
            
            # Verify messages were sent
            self.assertTrue(mock_conn.send_messages.called)

    def test_export_final_feedback_has_year_sheets_and_round_average(self):
        self.form.second_feedback_enabled = True
        self.form.save(update_fields=['second_feedback_enabled'])
        response_two = FeedbackResponse.objects.create(
            form=self.form,
            student=self.student,
            feedback_round=2,
            is_anonymous=False
        )
        FeedbackAnswer.objects.create(response=response_two, question=self.q1, rating_answer=2)
        FeedbackAnswer.objects.create(response=response_two, question=self.q2, rating_answer=3)

        response = self.client.get(reverse('export_final_feedback'))
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(workbook.sheetnames, ['FY', 'SY', 'TY', 'LY'])

        worksheet = workbook['TY']
        self.assertEqual(worksheet['B1'].value, 'K J Somaiya Institute of Technology')
        self.assertEqual(worksheet['B2'].value, 'Department: COMPS')
        self.assertEqual(worksheet['A4'].value, 'SR.NO.')
        self.assertEqual(worksheet['E4'].value, 'ADiv')
        self.assertEqual(worksheet['I4'].value, 'BDiv')
        self.assertEqual(worksheet['M4'].value, 'Average (available scores)')
        self.assertEqual(worksheet['B3'].value, 'Highlight above (%)')
        self.assertEqual(worksheet['C3'].value, 80)
        self.assertEqual(worksheet['D3'].value, 'Change the threshold in C3 to update the highlighted names.')
        self.assertEqual(len(worksheet.data_validations.dataValidation), 1)
        self.assertEqual(worksheet['M6'].value, 3.5)
        self.assertEqual(worksheet['N6'].value, 0.7)
        self.assertEqual(worksheet['N6'].number_format, '0.00%')
        self.assertTrue(worksheet.conditional_formatting)


