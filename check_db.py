import os
import django
from django.conf import settings
from django.db import connection
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'LMS.settings')
django.setup()

def drop_table(table_name):
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        connection.commit()
    print(f"Dropped table {table_name}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "drop":
        drop_table("course_payments")
    else:
        with connection.cursor() as cursor:
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'staff_permissions'")
            columns = [row[0] for row in cursor.fetchall()]
            print(f"Columns in staff_permissions: {columns}")
            
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'course_payments'")
            columns = [row[0] for row in cursor.fetchall()]
            print(f"Columns in course_payments: {columns}")
            
            if columns:
                try:
                    cursor.execute("SELECT count(*) FROM course_payments")
                    count = cursor.fetchone()[0]
                    print(f"Rows in course_payments: {count}")
                except:
                    print("Could not count rows (table might not exist yet)")
