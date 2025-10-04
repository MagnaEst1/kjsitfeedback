from django.core.management.base import BaseCommand
from appfeedback.models import Division, Subject, Professor, PracticalBatch, PracticalAssignment, TeacherAssignment

class Command(BaseCommand):
    help = "Create practical batches for SY, TY, and LY divisions"

    def handle(self, *args, **kwargs):
        batches_created = 0

        # ----- SY -----
        sya = Division.objects.filter(year=2, name="A").first()
        if sya:
            for i in range(1, 5):
                batch_name = f"S{i}"
                batch, created = PracticalBatch.objects.get_or_create(
                    name=batch_name,
                    division=sya,
                    defaults={'max_students': 15}
                )
                if created:
                    batches_created += 1
                    self.stdout.write(f'Created practical batch: {batch}')

        syb = Division.objects.filter(year=2, name="B").first()
        if syb:
            for i in range(5, 9):
                batch_name = f"S{i}"
                batch, created = PracticalBatch.objects.get_or_create(
                    name=batch_name,
                    division=syb,
                    defaults={'max_students': 15}
                )
                if created:
                    batches_created += 1
                    self.stdout.write(f'Created practical batch: {batch}')

        # ----- TY -----
        tya = Division.objects.filter(year=3, name="A").first()
        if tya:
            for i in range(1, 5):
                batch_name = f"T{i}"
                batch, created = PracticalBatch.objects.get_or_create(
                    name=batch_name,
                    division=tya,
                    defaults={'max_students': 15}
                )
                if created:
                    batches_created += 1
                    self.stdout.write(f'Created practical batch: {batch}')

        tyb = Division.objects.filter(year=3, name="B").first()
        if tyb:
            for i in range(5, 9):
                batch_name = f"T{i}"
                batch, created = PracticalBatch.objects.get_or_create(
                    name=batch_name,
                    division=tyb,
                    defaults={'max_students': 15}
                )
                if created:
                    batches_created += 1
                    self.stdout.write(f'Created practical batch: {batch}')

        # ----- LY -----
        lya = Division.objects.filter(year=4, name="A").first()
        if lya:
            for i in range(1, 5):
                batch_name = f"L{i}"
                batch, created = PracticalBatch.objects.get_or_create(
                    name=batch_name,
                    division=lya,
                    defaults={'max_students': 15}
                )
                if created:
                    batches_created += 1
                    self.stdout.write(f'Created practical batch: {batch}')

        lyb = Division.objects.filter(year=4, name="B").first()
        if lyb:
            for i in range(5, 9):
                batch_name = f"L{i}"
                batch, created = PracticalBatch.objects.get_or_create(
                    name=batch_name,
                    division=lyb,
                    defaults={'max_students': 15}
                )
                if created:
                    batches_created += 1
                    self.stdout.write(f'Created practical batch: {batch}')

        # ----- Summary -----
        self.stdout.write(self.style.SUCCESS(f'Created {batches_created} new practical batches'))
