# 🐸 Leapfrog Connect

### *From Learning to Earning — One Seamless Journey*

---

## 📌 Overview

Leapfrog Connect is a unified web ecosystem that bridges the gap between education and employment in Nepal. The platform integrates a Learning Management System (LMS) with an HR Service Tracking Platform to streamline training, assessment, and candidate placement for students, professionals, and partner employers.

**Core Mission:** Every skill learned becomes a verifiable credential that employers can instantly trust and filter.

---

## 🎯 Problem Statement

| Problem | Impact |
|---------|--------|
| Credentials die inside LMS | Certificates never reach employers |
| Companies can't filter by real skills | HR wastes time on unqualified candidates |
| No feedback loop between hiring & training | Courses don't improve |
| Fragmented systems (LMS + HR are separate) | Manual work, outdated data, no single source of truth |

---

## 🧠 Our Solution

**One Loop: Learn → Prove → Hire → Feedback → Fix**



---

## 👥 User Roles

| Role | Level | Responsibilities |
|------|-------|------------------|
| **Super Admin** | 1 | Platform owner, creates admins, full system access |
| **Admin** | 2 | Manages staff, tutors, companies, students |
| **Staff** | 3 | Support role, creates users if permitted |
| **Tutor** | 3 | Creates courses, teaches, assesses students |
| **Company** | 3 | Searches talent pool, schedules interviews, hires |
| **Student** | 3 | Enrolls in courses, earns badges, applies for jobs |

**Role Hierarchy:**



---

## 🏗️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Django 5.x, Django REST Framework |
| **Authentication** | JWT (djangorestframework-simplejwt) |
| **Database** | PostgreSQL (production), SQLite (development) |
| **Email** | Gmail SMTP / Console (dev) |
| **CORS** | django-cors-headers |
| **Environment** | python-decouple |
| **Hosting** | AWS/GCP (planned) |

---

## 📁 Project Structure



---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL (optional, SQLite works for development)
- Git

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/leapfrog-connect.git
cd leapfrog-connect

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Create .env file
cp .env.example .env
# Edit .env with your credentials

# 6. Run migrations
python manage.py makemigrations
python manage.py migrate

# 7. Create superuser (admin)
python manage.py createsuperuser

# 8. Run development server
python manage.py runserver



# Django
SECRET_KEY=your-secret-key-here
DEBUG=True

# Email (Gmail SMTP)
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_16_digit_app_password

# Database (optional, for PostgreSQL)
DB_NAME=leapfrog_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432